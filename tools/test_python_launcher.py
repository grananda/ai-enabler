"""Offline launcher regression tests; run with a working Python 3.8+ interpreter.

On Windows pass --bash with the full path to Git for Windows' bin/bash.exe.
No installations, user settings or global PATH changes; fixtures are temporary.
"""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PLUGINS = [ROOT / "plugins" / name for name in ("ai-enabler", "ai-enabler-metrics")]
parser = argparse.ArgumentParser()
parser.add_argument("--bash", default=shutil.which("bash"))
options, unittest_args = parser.parse_known_args()
BASH = options.bash
if not BASH or "windowsapps" in BASH.lower():
    parser.error("A working Bash is required; on Windows pass --bash with Git for Windows' bash.exe (not the Store/WSL alias).")
subprocess.run([BASH, "--version"], check=True, stdout=subprocess.DEVNULL, timeout=10)


def shell_path(path):
    return str(path).replace("\\", "/")


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="python launcher ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / "candidate bin"
        self.bin.mkdir()
        self.log = self.root / "calls.txt"
        self.env = dict(os.environ)
        for key in ("BASH_ENV", "ENV", "CLAUDE_PROJECT_DIR", "ENABLER_METRICS_DIR", "ENABLER_KPI_DIR"):
            self.env.pop(key, None)
        self.env["LAUNCHER_TEST_LOG"] = shell_path(self.log)
        self.path = self.posix_path(self.bin)
        self.target = self.root / "target script.py"
        self.target.write_text(
            'import json, sys\n'
            'print(json.dumps(sys.argv[1:]))\n'
            'sys.stdout.flush()\n'
            'sys.stdout.buffer.write(sys.stdin.buffer.read())\n'
            'sys.stderr.write("target stderr\\n")\n'
            'sys.exit(2 if "exit2" in sys.argv else 0)\n', encoding="utf-8")

    def posix_path(self, path):
        if os.name == "nt":
            return subprocess.check_output([BASH, "-c", '/usr/bin/cygpath -u "$1"',
                                            "test", shell_path(path)], text=True).strip()
        return str(path)

    def wrapper(self, name, body, directory=None):
        path = (directory or self.bin) / name
        with path.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write("#!/bin/bash\n" + body)
        path.chmod(0o755)
        return path

    def candidate(self, name, mode="working", directory=None):
        python = shlex.quote(shell_path(sys.executable))
        body = 'printf "%s\\n" "' + name + ':$1" >> "$LAUNCHER_TEST_LOG"\n'
        if name == "py":
            body += '[[ "$1" == -3 ]] || exit 9\nshift\n'
        if mode == "failing":
            body += 'printf "Store stub failure\\n" >&2\nexit 9009\n'
        elif mode == "old":
            body += '[[ "$1" == -I ]] || exit 9\n'
            body += 'exec ' + python + ' -I -S -c "import sys; sys.version_info=(3, 7); $4"\n'
        elif mode == "hanging":
            body += 'exec ' + python + ' -I -S -c "import time; time.sleep(10)"\n'
        else:
            body += 'exec ' + python + ' "$@"\n'
        return self.wrapper(name, body, directory)

    def run_launcher(self, plugin, args, data=b"", controlled=True):
        launcher = plugin / "scripts/run-python.sh"
        # Build shell argv in a fixture file, not a Windows CreateProcess argument
        # string (MSYS Bash and Python list2cmdline disagree on embedded quotes).
        command = 'exec /bin/bash ' + shlex.quote(shell_path(launcher))
        command += ''.join(' ' + shlex.quote(arg) for arg in args)
        if controlled:
            command = 'PATH=' + shlex.quote(self.path) + '; export PATH\n' + command
        invocation = self.wrapper("invoke", command + '\n', self.root)
        return subprocess.run([BASH, shell_path(invocation)], input=data, capture_output=True,
                              env=self.env, cwd=self.root, timeout=20)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_copies_and_all_hook_commands(self):
        self.assertEqual((PLUGINS[0] / "scripts/run-python.sh").read_bytes(),
                         (PLUGINS[1] / "scripts/run-python.sh").read_bytes())
        for plugin in PLUGINS:
            config = json.loads((plugin / "hooks/hooks.json").read_text())
            count = sum(len(group["hooks"]) for groups in config["hooks"].values() for group in groups)
            self.assertEqual(count, 5 if plugin.name == "ai-enabler" else 14)
        doctor = (PLUGINS[0] / "skills/delivery-doctor/SKILL.md").read_text(encoding="utf-8")
        status = (PLUGINS[1] / "skills/metrics-usage-init/SKILL.md").read_text(encoding="utf-8")
        for text in (doctor, status):
            self.assertIn('scripts/run-python.sh" --check', text)
            self.assertIn('not ready', text)
        for plugin in PLUGINS:
            for path in plugin.glob("skills/*/SKILL.md"):
                self.assertNotIn('python3 "${CLAUDE_PLUGIN_ROOT}', path.read_text(encoding="utf-8"))

    def test_fallback_preserves_input_arguments_and_target_exit(self):
        payload = b'{"tool_input": {"text": "untouched"}}\r\n\x00end\n'
        args = ["space here", "", 'quotes\"and\'apostrophe', "$HOME;*", "/api/resource", "a;b", "exit2"]
        for mode in ("failing", "old"):
            self.candidate("python3", mode)
            self.candidate("python")
            self.candidate("py")
            for plugin in PLUGINS:
                with self.subTest(plugin=plugin.name, first=mode):
                    self.log.write_text("")
                    result = self.run_launcher(plugin, [shell_path(self.target)] + args, payload)
                    self.assertEqual(result.returncode, 2, (result.stderr, result.stdout, self.calls()))
                    line, rest = result.stdout.split(b"\n", 1)
                    self.assertEqual(json.loads(line), args)
                    self.assertEqual(rest, payload)
                    self.assertEqual(result.stderr, b"target stderr\r\n" if os.name == "nt" else b"target stderr\n")
                    self.assertEqual([c.split(":", 1)[0] for c in self.calls()], ["python3", "python", "python"])

    def test_first_working_and_py_only(self):
        for name in ("python3", "py"):
            candidate = self.candidate(name)
            for plugin in PLUGINS:
                self.log.write_text("")
                check = self.run_launcher(plugin, ["--check"], b"unconsumed")
                self.assertEqual(check.returncode, 0, check.stderr)
                executable, version = check.stdout.decode().strip().split("\t")
                self.assertEqual(Path(executable), Path(sys.executable))
                self.assertEqual(version, sys.version.split()[0])
                self.assertEqual(len(self.calls()), 1)
                result = self.run_launcher(plugin, [shell_path(self.target)], b"input")
                self.assertEqual(result.returncode, 0, result.stderr)
            candidate.unlink()

    def test_windows_store_path_is_never_invoked(self):
        store = self.root / "Microsoft" / "WindowsApps"
        store.mkdir(parents=True)
        self.candidate("python3", "failing", store)
        self.candidate("python")
        self.path = self.posix_path(store) + ":" + self.path
        for plugin in PLUGINS:
            self.log.write_text("")
            result = self.run_launcher(plugin, ["--check"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(self.calls(), ["python:-I"])

    def test_missing_runtime_and_missing_script_fail(self):
        for plugin in PLUGINS:
            result = self.run_launcher(plugin, ["--check"])
            self.assertEqual(result.returncode, 1)
            self.assertEqual(result.stdout, b"")
            self.assertIn(b"Install Python 3", result.stderr)
            result = self.run_launcher(plugin, [shell_path(self.root / "missing.py")])
            self.assertEqual(result.returncode, 1)
            self.assertIn(b"existing Python script", result.stderr)
            self.assertEqual(self.calls(), [])

    def test_probe_timeout(self):
        timer = subprocess.check_output([BASH, "-c", "[[ -x /usr/bin/timeout ]] && printf /usr/bin/timeout || command -v gtimeout || true"], text=True).strip()
        if not timer:
            self.skipTest("GNU timeout not installed; hook timeout is the documented outer bound")
        self.wrapper("timeout", 'exec ' + shlex.quote(timer) + ' "$@"\n')
        self.candidate("python3", "hanging")
        self.candidate("python")
        for plugin in PLUGINS:
            result = self.run_launcher(plugin, ["--check"])
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_hooks_from_copied_plugin_with_spaces(self):
        project = self.root / "fixture project"
        project.mkdir()
        self.env["CLAUDE_PROJECT_DIR"] = shell_path(project)
        for original in PLUGINS:
            plugin = self.root / (original.name + " installed copy")
            shutil.copytree(original, plugin, ignore=shutil.ignore_patterns("__pycache__"))
            config = json.loads((plugin / "hooks/hooks.json").read_text())
            for event, groups in config["hooks"].items():
                for group in groups:
                    for hook in group["hooks"]:
                        command = hook["command"]
                        self.assertIn('exec /bin/bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh"', command)
                        self.assertEqual(hook["shell"], "bash")
                        if original.name == "ai-enabler":
                            # Guards block on failure; the output trim and gate notification only help, so they never do.
                            self.assertEqual(hook["onFailure"], "block" if event == "PreToolUse" else "continue")
                        self.env["CLAUDE_PLUGIN_ROOT"] = shell_path(plugin)
                        if original.name == "ai-enabler-metrics":
                            metrics = project / ".enabler/metrics"
                            metrics.mkdir(parents=True, exist_ok=True)
                            self.env["ENABLER_METRICS_DIR"] = shell_path(metrics)
                        payload = {"hook_event_name": event, "cwd": str(project),
                                   "session_id": "launcher-fixture", "tool_name": "Bash",
                                   "tool_input": {"command": "git status"}}
                        result = subprocess.run([BASH, "-c", command], input=json.dumps(payload).encode(),
                                                env=self.env, cwd=project, capture_output=True, timeout=20)
                        self.assertEqual(result.returncode, 0, (event, result.stderr))
            # The same command cannot report success if no interpreter is available.
            # Guards turn this startup exit 1 into a block via onFailure; metrics do not.
            empty_path = self.posix_path(self.bin)
            missing_command = 'PATH=' + shlex.quote(empty_path) + '; export PATH; ' + command
            missing = subprocess.run([BASH, "-c", missing_command], input=b'{}',
                                     env=self.env, cwd=project, capture_output=True, timeout=20)
            self.assertEqual(missing.returncode, 1, missing.stderr)
            self.assertIn(b'Install Python 3', missing.stderr)
            if original.name == "ai-enabler-metrics":
                self.assertNotIn('onFailure', hook)
                self.assertTrue(list(metrics.glob("events/**/*.jsonl")))
            else:
                (project / ".enabler").mkdir(exist_ok=True)
                (project / ".enabler/local-only").write_text("fixture only")
                payload["tool_input"] = {"command": "git push"}
                command = config["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
                result = subprocess.run([BASH, "-c", command], input=json.dumps(payload).encode(),
                                        env=self.env, cwd=project, capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 2, result.stderr)
                sources = project / '.enabler/sources'
                sources.mkdir()
                protected = project / 'external source'
                protected.mkdir()
                (sources / 'sources.json').write_text(json.dumps({'sources': [
                    {'name': 'fixture', 'kind': 'folder', 'location': str(protected)}]}))
                payload['tool_name'] = 'Write'
                payload['tool_input'] = {'file_path': str(protected / 'blocked.txt'), 'content': 'never written'}
                command = config['hooks']['PreToolUse'][1]['hooks'][0]['command']
                result = subprocess.run([BASH, '-c', command], input=json.dumps(payload).encode(),
                                        env=self.env, cwd=project, capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertFalse((protected / 'blocked.txt').exists())
                for script in ('repo_profile.py', 'sources.py'):
                    result = self.run_launcher(plugin, [shell_path(plugin / 'scripts' / script), 'check'],
                                               controlled=False)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIsInstance(json.loads(result.stdout), dict)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]] + unittest_args)
