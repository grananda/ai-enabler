#!/usr/bin/env python3
"""Checks the repository-profile bookkeeping: missing, unrecorded, fresh, stale; deltas in order;
nothing recorded that was not written; nothing committed.

    python3 tests/test_repo_profile.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "repo_profile.py")


class Project:
    def __init__(self, git=True):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="ai-enabler-profile-test-"))
        if git:
            subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)

    def run(self, *args, ok=True, cwd=None):
        cwd = cwd or self.root
        env = dict(os.environ, CLAUDE_PROJECT_DIR=cwd)
        out = subprocess.run([sys.executable, SCRIPT] + list(args), cwd=cwd, env=env, capture_output=True, text=True)
        assert (out.returncode == 0) == ok, (args, out.stdout, out.stderr)
        assert "Traceback" not in out.stderr, out.stderr
        return out.stdout.strip()

    def check(self, **kw):
        return json.loads(self.run("check", **kw))

    def path(self, rel):
        return os.path.join(self.root, rel)

    def write(self, rel, text):
        full = rel if os.path.isabs(rel) else self.path(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(text)

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as fh:
            return fh.read()


def basics(p):
    p.write("package.json", '{"scripts": {"test": "jest"}}')
    p.write("package-lock.json", "{}")                       # a lock file: not watched
    p.write("apps/web/package.json", "{}")                   # a module of a monorepo: watched
    p.write("apps/web/src/a.ts", "export const a = 1")
    p.write("apps/web/README.md", "module notes")            # only the root README is watched
    p.write("CLAUDE.md", "Use named exports.")
    p.write(".github/workflows/ci.yml", "on: push")
    p.write("node_modules/x/package.json", "{}")             # never watched
    p.write("src/build/pom.xml", "<project/>")               # a source folder called build: watched

    c = p.check()
    assert c["status"] == "missing" and os.path.isabs(c["profile"]) and c["root"] == p.root, c
    p.run("record", ok=False)                                # nothing to record before a profile exists
    profile = c["profile"]
    p.run("record", "--expect", profile, ok=False)           # the scout said it wrote a profile, and did not

    p.write(profile, "# Profile\n\n## Commands\nnpm test\n")
    rec = json.loads(p.run("record", "--expect", profile))
    assert rec == {"recorded": 5, "deltas": 0}, rec
    state = json.loads(p.read(".enabler/repo-profile/profile.json"))
    assert sorted(state["files"]) == [".github/workflows/ci.yml", "CLAUDE.md", "apps/web/package.json",
                                      "package.json", "src/build/pom.xml"], sorted(state["files"])
    assert p.check()["status"] == "fresh"

    # Source code and lock files change all the time; the profile does not care.
    p.write("apps/web/src/a.ts", "export const a = 2")
    p.write("package-lock.json", '{"x": 1}')
    assert p.check()["status"] == "fresh"

    # A watched file changes, one appears, one goes: the profile is stale, and says why.
    p.write("package.json", '{"scripts": {"test": "vitest"}}')
    p.write("README.md", "Run `npm test`.")
    os.remove(p.path(".github/workflows/ci.yml"))
    c = p.check()
    assert (c["status"], c["changed"], c["added"], c["removed"]) == \
        ("stale", ["package.json"], ["README.md"], [".github/workflows/ci.yml"]), c

    # The answer is a delta that complements the profile; the profile itself is not rewritten.
    first = p.run("next-delta", "Test runner changed to Vitest!")
    assert first == p.path(".enabler/repo-profile/deltas/delta-001-test-runner-changed-to-vitest.md"), first

    # Recording without the delta would mark the change as seen with nothing describing it.
    p.run("record", "--expect", first, ok=False)
    assert p.check()["status"] == "stale"
    p.write(first, "")
    p.run("record", "--expect", first, ok=False)             # an empty file is not a delta either

    # While the delta is being written, another watched file changes. It was not looked at, so
    # recording must not swallow it: the next check still reports it.
    p.write(first, "# Delta 001\nTests now run with vitest.\n")
    p.write("CLAUDE.md", "Use default exports.")
    assert json.loads(p.run("record", "--expect", first))["deltas"] == 1
    c = p.check()
    assert c["status"] == "stale" and c["changed"] == ["CLAUDE.md"] and not c["added"] and not c["removed"], c

    # A change that affects nothing the profile says needs no file: it is just recorded.
    assert json.loads(p.run("record"))["deltas"] == 1
    c = p.check()
    assert c["status"] == "fresh" and c["deltas"] == 1 and c["profile_lines"] == 4, c

    # Something learned during a run: a delta, and the fingerprints stay as they were, so a watched
    # file edited by that run is still noticed afterwards.
    learned = p.run("next-delta", "integration tests need docker")
    assert learned.endswith("delta-002-integration-tests-need-docker.md"), learned
    p.write(learned, "# Delta 002\nIntegration tests need Docker running.\n")
    p.write("package.json", '{"scripts": {"test": "vitest run"}}')
    assert json.loads(p.run("record", "--expect", learned, "--keep"))["deltas"] == 2
    c = p.check()
    assert c["status"] == "stale" and c["changed"] == ["package.json"], c
    p.run("record")
    assert p.run("list").splitlines() == [p.path(".enabler/repo-profile/profile.md"), first, learned]

    # Nothing of this is ever committed, and no file of the project was touched to make it so.
    status = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=p.root, capture_output=True, text=True)
    assert ".enabler" not in status.stdout, status.stdout
    assert not os.path.exists(p.path(".gitignore"))
    assert p.read(".enabler/runs/.gitignore").strip().endswith("*")

    # Starting again removes the profile and every delta, whatever its name.
    p.write(".enabler/repo-profile/deltas/notes.md", "hand-written")
    assert "notes.md" in p.run("list")
    assert json.loads(p.run("reset"))["removed"] == 5        # profile, state, three deltas
    assert p.check()["status"] == "missing" and p.run("list") == ""


def unrecorded(p):
    """A profile without usable fingerprints is adopted, never overwritten."""
    p.write("package.json", "{}")
    p.write(".enabler/repo-profile/profile.md", "# Written by hand\n")
    assert p.check()["status"] == "unrecorded"
    for broken in ("not json", "[]", '{"schema": 99, "files": {}}', '{"schema": 1, "files": []}'):
        p.write(".enabler/repo-profile/profile.json", broken)
        assert p.check()["status"] == "unrecorded", broken
    p.run("record")
    assert p.check()["status"] == "fresh"
    assert p.read(".enabler/repo-profile/profile.md") == "# Written by hand\n"


def many_files(p):
    """No cap: the root manifest of a large monorepo is watched like any other."""
    for i in range(450):
        p.write("libs/lib%03d/package.json" % i, "{}")
    p.write("pom.xml", "<project/>")
    p.write(".enabler/repo-profile/profile.md", "# Profile\n")
    assert json.loads(p.run("record"))["recorded"] == 451
    p.write("pom.xml", "<project><x/></project>")
    c = p.check()
    assert c["status"] == "stale" and c["changed"] == ["pom.xml"] and not c["removed"], c


def odd_names(p):
    """Names with accents and spaces are watched like any other."""
    p.write("módulo año/package.json", "{}")
    p.write(".enabler/repo-profile/profile.md", "# Profile\n")
    p.run("record")
    assert "módulo año/package.json" in json.loads(p.read(".enabler/repo-profile/profile.json"))["files"]
    p.write("módulo año/package.json", '{"a": 1}')
    assert p.check()["changed"] == ["módulo año/package.json"]


def one_folder(p):
    """Opened in a module of a monorepo, the profile sits next to the runs: under that module,
    not at the top of the repository. From a subfolder of it, the same one is found."""
    module = p.path("services/billing")
    p.write("services/billing/pom.xml", "<project/>")
    p.write("pom.xml", "<project/>")
    c = p.check(cwd=module)
    assert c["root"] == module and c["profile"] == os.path.join(module, ".enabler/repo-profile/profile.md"), c
    p.write(c["profile"], "# Profile\n")
    assert json.loads(p.run("record", cwd=module))["recorded"] == 1
    deeper = os.path.join(module, "src")
    os.makedirs(deeper)
    assert p.check(cwd=deeper)["root"] == module


def limits(p):
    """A profile or a set of deltas that has outgrown its purpose is reported, not silently kept."""
    p.write("package.json", "{}")
    p.write(".enabler/repo-profile/profile.md", "line\n" * 200)
    p.run("record")
    assert any("200 lines" in r for r in p.check()["suggest_relearn"])
    p.write(".enabler/repo-profile/profile.md", "line\n" * 100)
    assert p.check()["suggest_relearn"] == []
    p.write(p.run("next-delta", "long"), "line\n" * 60)
    assert any("run long" in r for r in p.check()["suggest_relearn"])
    for i in range(11):
        p.write(p.run("next-delta", "d%d" % i), "x\n")
    assert any("12 deltas" in r for r in p.check()["suggest_relearn"])
    assert p.run("next-delta", "next").endswith("delta-013-next.md")
    p.write(".enabler/repo-profile/deltas/delta-1200-far.md", "x\n")
    assert p.run("next-delta", "after").endswith("delta-1201-after.md")


def without_git(p):
    p.write("go.mod", "module x")
    p.write("build/go.mod", "module out")                    # no .gitignore to ask: build output is skipped
    p.write(".enabler/repo-profile/profile.md", "# Profile\n")
    assert json.loads(p.run("record"))["recorded"] == 1
    p.write("go.mod", "module y")
    assert p.check()["changed"] == ["go.mod"]


def main():
    cases = [(basics, True), (unrecorded, True), (many_files, True), (odd_names, True), (one_folder, True),
             (limits, True), (without_git, False)]
    for case, git in cases:
        p = Project(git=git)
        try:
            case(p)
        finally:
            shutil.rmtree(p.root, ignore_errors=True)
    print("ok — repository profile bookkeeping (%d cases)" % len(cases))


if __name__ == "__main__":
    main()
