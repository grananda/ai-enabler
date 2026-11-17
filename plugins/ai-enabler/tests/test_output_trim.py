#!/usr/bin/env python3
"""Checks the output trim hook: long runner output from a delivery subagent is cut down
to failures and summary with the full log saved; everything else is left alone.

    python3 tests/test_output_trim.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "output_trim.py")
AGENT = "ai-enabler:delivery-test-engineer"


def dotnet_test_output(passing=600):
    lines = ["  Determining projects to restore...", "  All projects are up-to-date for restore.",
             "  Shop -> /src/Shop/bin/Debug/net8.0/Shop.dll",
             "  Shop.Tests -> /src/Shop.Tests/bin/Debug/net8.0/Shop.Tests.dll",
             "Test run for /src/Shop.Tests/bin/Debug/net8.0/Shop.Tests.dll (.NETCoreApp,Version=v8.0)",
             "Starting test execution, please wait..."]
    lines += ["  Passed Shop.Tests.CatalogTests.Lists_item_%d [2 ms]" % i for i in range(passing // 2)]
    lines += [
        "  Failed Shop.Tests.OrderTests.Total_includes_tax [14 ms]",
        "  Error Message:",
        "   Assert.Equal() Failure: Values differ",
        "Expected: 119.00",
        "Actual:   100.00",
        "  Stack Trace:",
        "     at Shop.Tests.OrderTests.Total_includes_tax() in /src/Shop.Tests/OrderTests.cs:line 42",
        "     at System.RuntimeMethodHandle.InvokeMethod(Object target, Void** arguments)",
    ]
    lines += ["  Passed Shop.Tests.CatalogTests.Filters_item_%d [1 ms]" % i for i in range(passing // 2)]
    lines += ["", "Failed!  - Failed:     1, Passed:   %d, Skipped:     0, Total:   %d, Duration: 3 s"
              % (passing, passing + 1)]
    return "\n".join(lines) + "\n"


class OutputTrim(unittest.TestCase):
    def setUp(self):
        self.project = tempfile.mkdtemp(prefix="ai-enabler-trim-")
        os.makedirs(os.path.join(self.project, ".enabler"))
        self.addCleanup(shutil.rmtree, self.project, True)

    def run_hook(self, payload, raw=None):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.project)
        data = raw if raw is not None else json.dumps(payload).encode("ascii")
        return subprocess.run([sys.executable, HOOK], input=data, capture_output=True, env=env, timeout=30)

    def payload(self, command, response, tool="Bash", **extra):
        p = {"hook_event_name": "PostToolUse", "tool_name": tool, "tool_input": {"command": command},
             "tool_response": response, "tool_use_id": "toolu_01ABC", "cwd": self.project,
             "agent_id": "a1", "agent_type": AGENT}
        p.update(extra)
        return p

    def bash(self, stdout, stderr=""):
        return {"stdout": stdout, "stderr": stderr, "interrupted": False, "isImage": False}

    def updated(self, out):
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertTrue(out.stdout, "expected a replacement")
        result = json.loads(out.stdout)["hookSpecificOutput"]
        self.assertEqual(result["hookEventName"], "PostToolUse")
        return result["updatedToolOutput"]

    def untouched(self, out):
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertEqual(out.stdout, b"")

    def test_failing_dotnet_test_keeps_assertion_and_summary(self):
        full = dotnet_test_output()
        out = self.updated(self.run_hook(self.payload("cd src && dotnet test --no-build", self.bash(full))))
        self.assertEqual(set(out), {"stdout", "stderr", "interrupted", "isImage"})
        self.assertEqual((out["stderr"], out["interrupted"], out["isImage"]), ("", False, False))
        text = out["stdout"]
        self.assertLess(len(text), len(full) // 4)
        for kept in ("Failed Shop.Tests.OrderTests.Total_includes_tax", "Assert.Equal() Failure: Values differ",
                     "Expected: 119.00", "Actual:   100.00", "OrderTests.cs:line 42",
                     "Failed!  - Failed:     1, Passed:   600", "Determining projects to restore"):
            self.assertIn(kept, text)
        self.assertNotIn("Lists_item_150 ", text)
        log = os.path.join(self.project, ".enabler", "tmp", "output", "toolu_01ABC.log")
        self.assertIn("lines omitted by ai-enabler output_trim", text)
        self.assertIn("full output: " + os.path.abspath(log), text)
        with open(log, encoding="utf-8") as fh:
            self.assertIn(full, fh.read())
        with open(os.path.join(self.project, ".enabler", "tmp", ".gitignore")) as fh:
            self.assertEqual(fh.read().strip(), "*")
        # Order is preserved.
        self.assertLess(text.index("Expected: 119.00"), text.index("Failed!  - Failed"))

    def test_stderr_is_saved_and_trimmed_too(self):
        noise = "\n".join("progress %d" % i for i in range(800))
        out = self.updated(self.run_hook(self.payload(
            "pytest -q", self.bash("1 failed, 3 passed in 0.2s\n", noise + "\nE   AssertionError: boom\n"))))
        self.assertIn("AssertionError: boom", out["stderr"])
        self.assertLess(len(out["stderr"]), len(noise))
        self.assertEqual(out["stdout"], "1 failed, 3 passed in 0.2s\n")
        with open(os.path.join(self.project, ".enabler", "tmp", "output", "toolu_01ABC.log"), encoding="utf-8") as fh:
            saved = fh.read()
        self.assertIn("progress 400", saved)
        self.assertIn("1 failed, 3 passed", saved)

    def test_runners_recognised(self):
        full = dotnet_test_output()
        for command in ("dotnet build -c Release", "./mvnw -q verify", "mvn test", "gradlew.bat test",
                        "./gradlew check", "npm test", "npm run test:unit", "npx vitest run", "npx jest",
                        "yarn test", "pnpm test", "pytest -x", "python -m pytest tests", "py -3 -m pytest",
                        "go test ./...", "cargo test", "cd app; DOTNET test", "set -e && jest --ci",
                        "timeout 600 npm test", "uv run pytest", "CI=1 npx jest", "/usr/bin/mvn -B test"):
            with self.subTest(command=command):
                self.updated(self.run_hook(self.payload(command, self.bash(full))))

    def test_unknown_command_untouched(self):
        full = dotnet_test_output()
        for command in ("cat build.log", "git log -p", "npm install", "echo dotnet", "grep -r pytest .",
                        "cat logs/mvn-test.log", "less target/jest.txt"):
            with self.subTest(command=command):
                self.untouched(self.run_hook(self.payload(command, self.bash(full))))

    def test_short_output_untouched(self):
        self.untouched(self.run_hook(self.payload("dotnet test", self.bash(dotnet_test_output(passing=20)))))

    def test_only_delivery_subagents(self):
        full = dotnet_test_output()
        main_thread = self.payload("dotnet test", self.bash(full))
        del main_thread["agent_type"], main_thread["agent_id"]
        self.untouched(self.run_hook(main_thread))
        for agent in ("general-purpose", "other-plugin:delivery-test-engineer", "delivery-test-engineer"):
            self.untouched(self.run_hook(self.payload("dotnet test", self.bash(full), agent_type=agent)))
        self.assertFalse(os.path.exists(os.path.join(self.project, ".enabler", "tmp")))

    def test_configuration(self):
        full = dotnet_test_output()
        config = os.path.join(self.project, ".enabler", "config.json")
        with open(config, "w") as fh:
            json.dump({"output_trim": {"enabled": False}}, fh)
        self.untouched(self.run_hook(self.payload("dotnet test", self.bash(full))))
        with open(config, "w") as fh:
            json.dump({"output_trim": {"max_chars": len(full) + 1}}, fh)
        self.untouched(self.run_hook(self.payload("dotnet test", self.bash(full))))
        short = dotnet_test_output(passing=120)
        self.untouched(self.run_hook(self.payload("dotnet test", self.bash(short))))
        with open(config, "w") as fh:
            json.dump({"output_trim": {"max_chars": 1000}}, fh)
        self.updated(self.run_hook(self.payload("dotnet test", self.bash(short))))
        with open(config, "w") as fh:
            fh.write("{not json")
        self.updated(self.run_hook(self.payload("dotnet test", self.bash(full))))

    def test_powershell_shapes(self):
        full = dotnet_test_output()
        out = self.updated(self.run_hook(self.payload("dotnet test", {"output": full, "exitCode": 1},
                                                      tool="PowerShell")))
        self.assertEqual(out["exitCode"], 1)
        self.assertIn("Expected: 119.00", out["output"])
        self.assertLess(len(out["output"]), len(full))
        out = self.updated(self.run_hook(self.payload("dotnet test", full, tool="PowerShell")))
        self.assertIsInstance(out, str)
        self.assertIn("Actual:   100.00", out)

    def test_malformed_input_is_ignored(self):
        for raw in (b"not json", b"", b"[1, 2]", b'{"tool_name": "Bash"}',
                    json.dumps(self.payload("dotnet test", None)).encode(),
                    json.dumps(self.payload("dotnet test", dict(self.bash(dotnet_test_output()), isImage=True))).encode()):
            with self.subTest(raw=raw[:40]):
                self.untouched(self.run_hook(None, raw=raw))

    def test_save_failure_means_no_trim(self):
        # .enabler/tmp is a file, so the log cannot be written.
        with open(os.path.join(self.project, ".enabler", "tmp"), "w") as fh:
            fh.write("x")
        self.untouched(self.run_hook(self.payload("dotnet test", self.bash(dotnet_test_output()))))


if __name__ == "__main__":
    unittest.main()
