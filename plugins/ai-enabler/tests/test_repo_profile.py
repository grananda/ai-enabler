#!/usr/bin/env python3
"""Checks the repository-profile bookkeeping: missing, unrecorded, fresh, stale; deltas in order;
nothing recorded that was not written; nothing committed.

    python3 tests/test_repo_profile.py
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "repo_profile.py")
HAS_GIT = shutil.which("git") is not None


class Project:
    def __init__(self, git=True):
        self.root = os.path.realpath(tempfile.mkdtemp(prefix="ai-enabler-profile-test-"))
        self.env = dict(os.environ)
        if git:
            subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)

    def run(self, *args, ok=True, cwd=None):
        cwd = cwd or self.root
        env = dict(self.env, CLAUDE_PROJECT_DIR=cwd)
        out = subprocess.run([sys.executable, SCRIPT] + list(args), cwd=cwd, env=env, capture_output=True, text=True)
        assert (out.returncode == 0) == ok, (args, out.stdout, out.stderr)
        assert "Traceback" not in out.stderr, out.stderr
        return out.stdout.strip()

    def check(self, **kw):
        return json.loads(self.run("check", **kw))

    def check_with(self, *args, **kw):
        return json.loads(self.run("check", *args, **kw))

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


class Repo(Project):
    """A git repository with commits, independent of the machine's git configuration."""

    def __init__(self):
        super().__init__(git=False)
        self.home = os.path.realpath(tempfile.mkdtemp(prefix="ai-enabler-profile-home-"))
        config = os.path.join(self.home, "gitconfig")
        open(config, "w").close()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=config, HOME=self.home)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "core.autocrlf", "false")
        self.git("checkout", "-q", "-b", "main")

    def git(self, *args):
        out = subprocess.run(["git"] + list(args), cwd=self.root, env=self.env, capture_output=True, text=True)
        assert out.returncode == 0, (args, out.stdout, out.stderr)
        return out.stdout.strip()

    def commit(self, message):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        return self.git("rev-parse", "HEAD")

    def write_bytes(self, rel, data):
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), "wb") as fh:
            fh.write(data)

    def cleanup(self):
        remove(self.root)
        remove(self.home)


def remove(path):
    """Git writes its objects read-only, which Windows refuses to delete as they are."""
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            os.chmod(os.path.join(dirpath, name), stat.S_IWRITE | stat.S_IREAD)
    shutil.rmtree(path, ignore_errors=True)

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
    assert (rec["recorded"], rec["deltas"]) == (5, 0), rec
    assert rec["against"] == {"kind": "working tree", "reason": "no commit yet"}, rec
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
    p.write(".enabler/tickets/export-orders.md", "# a ticket written by delivery-ticket-create\n")
    assert subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=p.root, capture_output=True,
                          text=True).stdout.count(".enabler") == 0

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


def summary(p):
    """The scout gets a summary of what changed, never hundreds of paths: every file when there are
    few, groups by kind and folder when there are many, and nothing when nothing watched changed."""
    for i in range(300):
        p.write("libs/lib%03d/package.json" % i, "{}")
    for i in range(30):
        p.write("apps/app%02d/src/main.ts" % i, "x")
    p.write("package.json", "{}")
    p.write(".github/workflows/ci.yml", "on: push")
    p.write(".github/workflows/nightly.yml", "on: schedule")
    p.write(".enabler/repo-profile/profile.md", "# Profile\n")
    p.run("record")

    # Only files the profile does not depend on: fresh, and nothing to summarise.
    p.write("apps/app00/src/main.ts", "y")
    p.write("package-lock.json", "{}")
    c = p.check()
    assert c["status"] == "fresh" and c["summary"] == [], c

    # A few files: one line each, rules first.
    p.write("package.json", '{"x": 1}')
    p.write("CLAUDE.md", "Use named exports.")
    c = p.check()
    assert c["summary"] == ["2 watched files: 1 changed, 1 added, 0 removed.",
                            "added CLAUDE.md (rules)", "changed package.json (build)"], c["summary"]
    p.run("record")

    # A merge that touches 300 manifests: a handful of lines, the root files still named one by one.
    for i in range(300):
        p.write("libs/lib%03d/package.json" % i, '{"version": "2.0.0"}')
    p.write("package.json", '{"x": 2}')
    p.write("AGENTS.md", "Agents rules.")
    os.remove(p.path(".github/workflows/nightly.yml"))
    c = p.check()
    lines = c["summary"]
    assert len(c["changed"]) == 301, c["changed"][:3]
    assert lines == [
        "303 watched files: 301 changed, 1 added, 1 removed.",
        "added AGENTS.md (rules)",
        "ci · .github/ · 1 removed · nightly.yml ×1 · e.g. .github/workflows/nightly.yml",
        "changed package.json (build)",
        "build · libs/ · 300 changed · package.json ×300 · e.g. libs/lib000/package.json, libs/lib001/package.json",
    ], lines
    p.run("record")

    # More folders than the summary holds: the rest is counted, not listed.
    for i in range(25):
        p.write("mod%02d/pom.xml" % i, "<project/>")
    c = p.check()
    assert len(c["summary"]) == 1 + 20 + 1 and c["summary"][-1] == "… and 5 more groups (5 files).", c["summary"]


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
    c = p.check()
    assert c["changed"] == ["go.mod"] and c["provisional"] == [], c
    assert c["against"] == {"kind": "working tree", "reason": "not a git work tree"}, c


def against_base(r):
    """A run's own edits to watched files, committed or not, do not make the profile stale: it is
    compared with the merge-base of HEAD and the base branch. Merged into main, they do."""
    r.write("package.json", "{}")
    r.write("docs/adr/time.md", "# Time\nUse UTC.\n")
    r.write("src/a.ts", "x")
    main = r.commit("initial")
    r.write(".enabler/repo-profile/profile.md", "# Profile\n")
    assert json.loads(r.run("record"))["against"] == {"kind": "commit", "ref": main, "base": "main"}
    assert r.check()["status"] == "fresh"

    # (a) On a feature branch, uncommitted: an ADR edited, one added, a manifest deleted.
    r.git("checkout", "-q", "-b", "feat/time-boundary")
    r.write("docs/adr/time.md", "# Time\nUse the local time zone.\n")
    r.write("docs/adr/http.md", "# HTTP\nOne client.\n")
    os.remove(r.path("package.json"))
    c = r.check()
    assert c["status"] == "fresh" and c["against"] == {"kind": "commit", "ref": main, "base": "main"}, c
    assert not os.path.exists(r.path(".enabler/repo-profile/pending.json"))

    # (b) Committed on the feature branch: the merge-base is still main.
    feature = r.commit("time and http boundary")
    c = r.check()
    assert c["status"] == "fresh" and c["against"]["ref"] == main, c

    # --base and git.base_branch choose another base; null in the config means "not set".
    c = r.check_with("--base", "feat/time-boundary")
    assert c["status"] == "stale" and c["against"] == {"kind": "commit", "ref": feature,
                                                        "base": "feat/time-boundary"}, c
    r.write(".enabler/config.json", json.dumps({"git": {"base_branch": "feat/time-boundary"}}))
    assert r.check()["against"]["base"] == "feat/time-boundary"
    r.write(".enabler/config.json", json.dumps({"git": {"base_branch": None}}))
    assert r.check()["against"]["base"] == "main"
    os.remove(r.path(".enabler/config.json"))
    assert r.check_with("--base", "no-such-branch")["against"]["base"] == "main"

    # (c) Merged into main: now the profile is stale, and says why.
    r.git("checkout", "-q", "main")
    r.git("merge", "-q", "--no-ff", "feat/time-boundary", "-m", "merge")
    c = r.check()
    assert (c["status"], c["changed"], c["added"], c["removed"]) == \
        ("stale", ["docs/adr/time.md"], ["docs/adr/http.md"], ["package.json"]), c
    assert c["against"]["ref"] == r.git("rev-parse", "HEAD"), c


def base_resolution(r):
    """No main or master: origin/HEAD names the base, and origin's branch stands in for a missing local one."""
    r.git("checkout", "-q", "-b", "trunk")
    r.write("pom.xml", "<project/>")
    head = r.commit("initial")                                 # main was never born: only trunk exists
    r.write(".enabler/repo-profile/profile.md", "# Profile\n")
    c = r.check()
    assert c["against"]["kind"] == "working tree" and "no base branch" in c["against"]["reason"], c
    r.git("update-ref", "refs/remotes/origin/develop", head)
    r.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
    assert r.check()["against"] == {"kind": "commit", "ref": head, "base": "origin/develop"}


def provisional_deltas(r):
    """A delta learned on a branch that is not in main yet is reported as provisional, until merged."""
    r.write("package.json", "{}")
    r.write("src/a.ts", "x")
    r.commit("initial")
    r.write(".enabler/repo-profile/profile.md", "# Profile\n")
    r.run("record")
    on_main = r.run("next-delta", "learned on main")
    r.write(on_main, "# Delta\nOn main.\n")
    r.run("record", "--expect", on_main, "--keep")

    # (e) Learned from uncommitted work on a feature branch.
    r.git("checkout", "-q", "-b", "feat/rule")
    r.write("src/a.ts", "y")
    delta = r.run("next-delta", "time boundary")
    r.write(delta, "# Delta\nAll time goes through Clock.\n")
    r.run("record", "--expect", delta, "--keep")
    learned = json.loads(r.read(".enabler/repo-profile/profile.json"))["learned"]
    name = os.path.basename(delta)
    assert learned[name]["branch"] == "feat/rule" and learned[name]["base"] == "main", learned
    expected = [{"delta": name, "branch": "feat/rule", "reason": "learned on feat/rule, not merged into main"}]
    c = r.check()
    assert c["status"] == "fresh" and c["provisional"] == expected, c
    r.commit("rule")
    r.git("checkout", "-q", "main")
    assert r.check()["provisional"] == expected

    # A branch deleted without being merged stays provisional.
    r.git("checkout", "-q", "-b", "feat/held")
    held = r.run("next-delta", "held")
    r.write(held, "# Delta\nHeld.\n")
    r.run("record", "--expect", held, "--keep")
    r.git("checkout", "-q", "main")
    r.git("branch", "-D", "feat/held")
    assert [d["delta"] for d in r.check()["provisional"]] == [name, os.path.basename(held)]

    # Merged: no longer provisional. The delta files are never touched.
    r.git("merge", "-q", "--no-ff", "feat/rule", "-m", "merge")
    c = r.check()
    assert c["provisional"] == [{"delta": os.path.basename(held), "branch": "feat/held",
                                 "reason": "learned on feat/held, which no longer exists"}], c
    assert r.read(delta) == "# Delta\nAll time goes through Clock.\n"


def legacy_fingerprints(r):
    """(f) A profile.json fingerprinted the old way (raw bytes of a clean working tree) stays fresh
    after the upgrade, even when that working tree had CRLF for files committed with LF."""
    lf = b"# Rules\nUse UTC.\n"
    r.write_bytes("CLAUDE.md", lf)
    r.write_bytes("package.json", b"{}\n")
    r.commit("initial")
    r.write_bytes("CLAUDE.md", lf.replace(b"\n", b"\r\n"))     # what a core.autocrlf checkout writes
    r.write(".enabler/repo-profile/profile.md", "# Profile\n")
    old = {"schema": 1, "created": "2026-01-01T00:00:00+00:00", "recorded": "2026-01-01T00:00:00+00:00",
           "files": {"CLAUDE.md": hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest(),
                     "package.json": hashlib.sha256(b"{}\n").hexdigest()}, "deltas": 0}
    r.write(".enabler/repo-profile/profile.json", json.dumps(old))
    c = r.check()
    assert c["status"] == "fresh" and c["against"]["kind"] == "commit", c

    # The old comparison does not hide a real change.
    r.write_bytes("CLAUDE.md", b"# Rules\nUse local time.\n")
    r.commit("rules")
    assert r.check()["changed"] == ["CLAUDE.md"]
    r.run("record")
    state = json.loads(r.read(".enabler/repo-profile/profile.json"))
    assert state["hash"] == "sha256-lf" and r.check()["status"] == "fresh", state

    # Without git the working tree is read: the same old profile.json with CRLF is fresh too.
    remove(r.path(".git"))
    r.write_bytes("CLAUDE.md", lf.replace(b"\n", b"\r\n"))
    r.write(".enabler/repo-profile/profile.json", json.dumps(old))
    c = r.check()
    assert c["status"] == "fresh" and c["against"]["kind"] == "working tree", c
    r.run("record")
    r.write_bytes("CLAUDE.md", lf)                                # only the line endings: still fresh
    assert r.check()["status"] == "fresh"


def main():
    cases = [(basics, True), (unrecorded, True), (many_files, True), (summary, True), (odd_names, True),
             (one_folder, True), (limits, True), (without_git, False)]
    for case, git in cases:
        p = Project(git=git)
        try:
            case(p)
        finally:
            shutil.rmtree(p.root, ignore_errors=True)
    repo_cases = [against_base, base_resolution, provisional_deltas, legacy_fingerprints]
    if not HAS_GIT:
        print("skipped — %d cases need git on PATH" % len(repo_cases))
        repo_cases = []
    for case in repo_cases:
        r = Repo()
        try:
            case(r)
        finally:
            r.cleanup()
    print("ok — repository profile bookkeeping (%d cases)" % (len(cases) + len(repo_cases)))


if __name__ == "__main__":
    main()
