#!/usr/bin/env python3
"""Checks review_scope.py: which lenses a change needs, how they are grouped, and the review pack.

    python3 tests/test_review_scope.py
"""

import json
import os
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "review_scope.py")


class Repo:
    def __init__(self):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="ai-enabler-review-scope-"))
        self.git("init", "-q", "-b", "main")
        self.write("src/Billing/Invoice.cs", "class Invoice {\n    decimal Total(decimal a, decimal b) => a + b;\n}\n")
        self.write("src/Legacy/Login.cs", "class Login {\n    string password = \"\";\n}\n")
        self.write("README.md", "# Demo\n")
        self.commit("initial")
        self.git("checkout", "-q", "-b", "feature")

    def git(self, *args):
        out = subprocess.run(["git", "-c", "user.name=T", "-c", "user.email=t@example.invalid",
                              "-c", "core.autocrlf=false"] + list(args),
                             cwd=self.root, capture_output=True, text=True)
        assert out.returncode == 0, (args, out.stderr)
        return out.stdout

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)

    def commit(self, msg):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)

    def scope(self, *args):
        out = subprocess.run([sys.executable, SCRIPT, "--base", "main"] + list(args), cwd=self.root,
                             capture_output=True, text=True, encoding="utf-8")
        assert out.returncode == 0 and "Traceback" not in out.stderr, (args, out.stdout, out.stderr)
        return json.loads(out.stdout)


def small_internal_change():
    """Business logic and its test: no security, two grouped instances, a pack with what the reviewers need."""
    r = Repo()
    r.write("src/Billing/Invoice.cs", "class Invoice {\n    decimal Total(decimal a, decimal b) => Math.Round(a + b, 2);\n"
                                      "    async Task Save(CancellationToken cancellationToken) { }\n}\n")
    r.commit("round totals")
    r.write("tests/Billing/InvoiceTests.cs", "class InvoiceTests { void RoundsTotal() { var x = fetch(\"/x\"); } }\n")  # untracked
    run_dir = os.path.join(r.root, ".enabler", "runs", "PROJ-1")
    os.makedirs(run_dir)
    with open(os.path.join(run_dir, "requirements.json"), "w", encoding="utf-8") as fh:
        json.dump({"acceptance_criteria": [{"id": "AC-1", "text": "Totals are rounded to cents."},
                                           {"id": "AC-2", "text": "Dropped at the plan gate.", "removed_by": "plan"}]}, fh)
    with open(os.path.join(run_dir, "test-report.md"), "w", encoding="utf-8") as fh:
        fh.write("## Coverage\n\n100 % of the changed lines.\n")
    out = r.scope("--run-dir", run_dir)
    assert out["lenses"] == ["correctness", "quality", "tests"], out
    assert "security" in out["skipped"] and not out["triggers"], out          # the token is a cancellation token
    assert out["groups"] == [["correctness", "tests"], ["quality"]], out
    assert out["files"] == 2 and out["diff_in_pack"], out                      # the untracked test counts
    pack = open(out["pack"], encoding="utf-8").read()
    assert "**AC-1** Totals are rounded to cents." in pack and "AC-2" not in pack
    assert "### Coverage" in pack and "## Coverage" not in pack.replace("### Coverage", "")
    assert "Math.Round" in pack                                                # the code diff is in
    assert "`tests/Billing/InvoiceTests.cs` (test, untracked)" in pack and "fetch(" not in pack
    assert "Not run: security" in pack


def security_triggers():
    """Entry points, dependencies, configured paths and untracked or deleted code bring security in."""
    r = Repo()
    r.write("src/Api/Program.cs", "app.MapGet(\"/time\", () => Results.Ok());\n")
    out = r.scope()
    assert "security" in out["lenses"] and out["triggers"] == ["src/Api/Program.cs: entry point"], out

    r = Repo()
    r.write("package.json", "{\"dependencies\": {\"left-pad\": \"1.0.0\"}}\n")
    assert r.scope()["triggers"] == ["package.json: dependencies"]

    r = Repo()
    r.write("src/Billing/Invoice.cs", "class Invoice {\n    decimal Total(decimal a, decimal b) => a - b;\n}\n")
    assert "security" not in r.scope()["lenses"]
    assert r.scope("--sensitive", "src/Billing/*")["triggers"] == ["src/Billing/Invoice.cs: configured as sensitive"]
    assert "security" in r.scope("--no-select")["lenses"]

    r = Repo()
    r.write("src/Reports/Export.cs", "class Export { void Run(string p) => File.WriteAllText(p, \"x\"); }\n")  # untracked
    assert r.scope()["triggers"] == ["src/Reports/Export.cs: file system"]

    r = Repo()
    os.remove(os.path.join(r.root, "src", "Legacy", "Login.cs"))                 # removing code is a change too
    assert r.scope()["triggers"] == ["src/Legacy/Login.cs: authentication or permissions"]

    r = Repo()
    r.write("README.md", "# Demo\n\nCall `fetch(\"/api\")` with your password.\n")
    r.write("tests/test_api.py", "requests.get('http://x', headers={'token': 'secret'})\n")
    out = r.scope()
    assert "security" not in out["lenses"] and out["groups"] == [["correctness", "tests"], ["quality"]], out


def size_and_limits():
    """A large change gets one instance per lens; a code diff over the limit stays out of the pack."""
    r = Repo()
    r.write("src/Billing/Invoice.cs", "class Invoice {\n" + "".join("    int F%d() => %d;\n" % (i, i) for i in range(200)) + "}\n")
    out = r.scope("--out", os.path.join(r.root, "pack.md"), "--max-diff-lines", "50")
    assert out["changed_lines"] >= 200 and out["groups"] == [["correctness"], ["quality"], ["tests"]], out
    assert not out["diff_in_pack"] and "not copied here" in open(out["pack"], encoding="utf-8").read()
    assert r.scope("--group-below", "0", "--lenses", "correctness,tests")["groups"] == [["correctness"], ["tests"]]
    out = subprocess.run([sys.executable, SCRIPT, "--base", "main", "--lenses", "style"], cwd=r.root,
                         capture_output=True, text=True)
    assert out.returncode != 0 and "unknown lens" in out.stderr


def main():
    small_internal_change()
    security_triggers()
    size_and_limits()
    print("ok — review scope: lens selection, grouping and pack")


if __name__ == "__main__":
    main()
