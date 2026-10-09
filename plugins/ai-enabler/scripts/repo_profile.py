#!/usr/bin/env python3
"""Keeps track of whether the repository profile is still true.

    repo_profile.py check             missing, unrecorded, fresh or stale? (JSON on stdout)
    repo_profile.py record            remember the state of the watched files
        --expect PATH                 refuse unless PATH (the profile or the delta just asked for) was written
        --keep                        keep the fingerprints as they are (a delta about something learned,
                                      not about a changed file)
    repo_profile.py next-delta SLUG   print the path the next delta must be written to
    repo_profile.py list              print the files that make up the profile, in reading order
    repo_profile.py reset             forget the profile and all its deltas (used by --relearn)

Paths are printed absolute. The folder is the `.enabler/` of the session's project directory
(or of the nearest parent that has one), the same place the runs are written to.

The profile lives in <project>/.enabler/repo-profile/ and never leaves the machine:

    profile.md               what the repository is: stack, commands, structure, conventions, rules
    deltas/delta-NNN-*.md    small complements, one per thing that changed or was learned
    profile.json             fingerprints of the files the profile was derived from (this script's)

The repository is learned once. Afterwards a run only asks this script whether
anything the profile was derived from has changed. The comparison is a hash of
each watched file, so it is exact and costs nothing; no model is involved.

Both folders the pipeline writes to get a .gitignore of their own that ignores
everything in them, so nothing is committed and no file of the project is touched.

Watched: build manifests, CI and lint configuration, the root README, and the
files that carry the project's rules (CLAUDE.md, AGENTS.md, contribution
guides, ADRs, .claude/rules).
Lock files are left out on purpose: they change with every dependency bump and
say nothing new about how the repository is built or written.
"""

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

SCHEMA = 1
WATCHED = [
    # build manifests
    "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradle.properties",
    "package.json", "angular.json", "nx.json", "turbo.json", "lerna.json", "pnpm-workspace.yaml",
    "tsconfig.json", "tsconfig.*.json", "vite.config.*", "next.config.*", "webpack.config.*", "jest.config.*",
    "vitest.config.*", "karma.conf.*", "playwright.config.*", "cypress.config.*", "babel.config.*", "biome.json",
    "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "requirements-*.txt", "requirements/*.txt",
    "tox.ini", "pytest.ini", "mypy.ini", "go.mod", "Cargo.toml", "*.csproj", "*.sln", "Directory.Build.props",
    "Gemfile", "composer.json", "Makefile", "makefile", "GNUmakefile", "justfile", "Taskfile.yml", "Taskfile.yaml",
    "Dockerfile", "docker-compose.yml", "docker-compose.yaml", ".nvmrc", ".tool-versions",
    # CI
    ".github/workflows/*.yml", ".github/workflows/*.yaml", "Jenkinsfile", ".gitlab-ci.yml",
    "azure-pipelines.yml", "bitbucket-pipelines.yml", ".circleci/config.yml", ".pre-commit-config.yaml",
    # lint and format
    ".eslintrc", ".eslintrc.*", "eslint.config.*", ".prettierrc", ".prettierrc.*", "checkstyle.xml",
    "ruff.toml", ".ruff.toml", ".flake8", ".pylintrc", ".editorconfig", "sonar-project.properties",
    ".golangci.yml", ".golangci.yaml",
    # the project's own rules
    "CLAUDE.md", "claude.md", "AGENTS.md", "CONTRIBUTING.md", "CONTRIBUTING", "ARCHITECTURE.md",
    ".claude/rules/*", ".github/CODEOWNERS", "CODEOWNERS", "docs/adr/*", "adr/*",
]
# Watched at the root of the project only: every folder may have a README, one of them documents the commands.
ROOT_ONLY = ["README", "README.*"]
# Never looked into, wherever they are. Build output (dist, build, target ...) is left to .gitignore,
# because a source directory can legitimately carry one of those names.
IGNORED_DIRS = ("node_modules/", "vendor/", ".git/", ".enabler/")
WALK_SKIP = IGNORED_DIRS + ("dist/", "build/", "target/", "coverage/", ".nx/", ".venv/", "venv/", "__pycache__/")
PROFILE_LINES, DELTA_LINES, MANY_DELTAS = 150, 30, 10


def project_root():
    """Where .enabler/ lives: the nearest folder that already has one, from the session's project
    directory up to the top of the git repository; otherwise that project directory. The run
    directories belong in the same .enabler/, which is why `check` prints `root`."""
    start = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=start, capture_output=True, timeout=10)
        top = os.path.abspath(out.stdout.decode("utf-8", "surrogateescape").strip()) if out.returncode == 0 else start
    except (OSError, subprocess.SubprocessError):
        top = start
    d = start
    while True:
        if os.path.isdir(os.path.join(d, ".enabler")):
            return d
        parent = os.path.dirname(d)
        if d == top or parent == d:
            return start
        d = parent


def candidates(root):
    """Files of the project: what git tracks or would track, or a bounded walk without git."""
    try:
        out = subprocess.run(["git", "-c", "core.quotepath=off", "ls-files", "-z", "-co", "--exclude-standard"],
                             cwd=root, capture_output=True, timeout=30)
        if out.returncode == 0:
            # -z and bytes: names with spaces, accents or odd encodings come through untouched.
            return [f.decode("utf-8", "surrogateescape") for f in out.stdout.split(b"\0") if f]
    except (OSError, subprocess.SubprocessError):
        pass
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirnames[:] = [d for d in dirnames if depth < 6 and (d + "/") not in WALK_SKIP]
        for name in filenames:
            found.append(os.path.normpath(os.path.join(rel, name)).replace(os.sep, "/"))
    return found


def watched(root):
    """Watched files, at the root and in the modules of a monorepo. Every one of them: no cap."""
    out = set()
    for path in candidates(root):
        if any(("/" + path).find("/" + d) >= 0 for d in IGNORED_DIRS):
            continue
        name = path.rsplit("/", 1)[-1]
        if "/" not in path and any(fnmatch.fnmatch(name, pat) for pat in ROOT_ONLY):
            out.add(path)
            continue
        for pat in WATCHED:
            if "/" in pat:
                # Directory patterns match at the root and under any module.
                if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path, "*/" + pat):
                    out.add(path)
                    break
            elif fnmatch.fnmatch(name, pat):
                out.add(path)
                break
    return sorted(out)


def fingerprints(root):
    prints = {}
    for path in watched(root):
        try:
            with open(os.path.join(root, path).encode("utf-8", "surrogateescape"), "rb") as fh:
                prints[path.encode("utf-8", "surrogateescape").decode("utf-8", "replace")] = \
                    hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            continue
    return prints


def paths(root):
    base = os.path.join(root, ".enabler", "repo-profile")
    return base, os.path.join(base, "profile.md"), os.path.join(base, "profile.json"), os.path.join(base, "deltas")


def keep_local(root):
    """Make sure git never picks these folders up, without touching any file of the project:
    each gets its own .gitignore that ignores everything in it."""
    for folder in (os.path.join(root, ".enabler", "repo-profile"), os.path.join(root, ".enabler", "runs")):
        os.makedirs(folder, exist_ok=True)
        marker = os.path.join(folder, ".gitignore")
        if not os.path.isfile(marker):
            with open(marker, "w", encoding="utf-8") as fh:
                fh.write("# Local working files of the ai-enabler plugin. Never committed.\n*\n")


def delta_number(name):
    m = re.match(r"^delta-(\d+)", name)
    return int(m.group(1)) if m else None


def deltas(root):
    """Every Markdown file in deltas/, numbered ones first in order: agents read them all, so all count."""
    d = paths(root)[3]
    if not os.path.isdir(d):
        return []
    names = [f for f in os.listdir(d) if f.endswith(".md")]
    return sorted(names, key=lambda n: (delta_number(n) is None, delta_number(n) or 0, n))


def load_state(root):
    """The recorded fingerprints, or None when there are none we can use."""
    try:
        with open(paths(root)[2], encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(state, dict) or state.get("schema") != SCHEMA or not isinstance(state.get("files"), dict):
        return None
    return state


def line_count(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return sum(1 for _ in fh)
    except OSError:
        return 0


def check(root):
    base, profile, _state, delta_dir = paths(root)
    keep_local(root)
    state = load_state(root)
    names = deltas(root)
    result = {"status": "missing", "root": root, "profile": profile, "deltas": len(names),
              "changed": [], "added": [], "removed": []}
    if not os.path.isfile(profile):
        return result
    result["profile_lines"] = line_count(profile)
    long_deltas = [n for n in names if line_count(os.path.join(delta_dir, n)) > DELTA_LINES + 10]
    reasons = []
    if result["profile_lines"] > PROFILE_LINES + 30:
        reasons.append("the profile has %d lines" % result["profile_lines"])
    if len(names) > MANY_DELTAS:
        reasons.append("there are %d deltas" % len(names))
    if long_deltas:
        reasons.append("%d deltas run long" % len(long_deltas))
    result["suggest_relearn"] = reasons
    if state is None:
        # A profile without usable fingerprints: someone wrote or restored it by hand, or the
        # bookkeeping was lost. It is adopted with `record`, never overwritten.
        result["status"] = "unrecorded"
        return result
    now, then = fingerprints(root), state["files"]
    result["changed"] = sorted(p for p in now if p in then and now[p] != then[p])
    result["added"] = sorted(p for p in now if p not in then)
    result["removed"] = sorted(p for p in then if p not in now)
    result["status"] = "stale" if (result["changed"] or result["added"] or result["removed"]) else "fresh"
    result["recorded"] = state.get("recorded")
    pending = os.path.join(base, "pending.json")
    if result["status"] == "fresh" and os.path.isfile(pending):
        os.remove(pending)
    if result["status"] == "stale":
        # What `record` will store: the files as they were when the change was noticed, not as
        # they are when the delta is finished. An edit made in between is noticed by the next check.
        with open(pending, "w", encoding="utf-8") as fh:
            json.dump(now, fh)
    return result


def record(root, expect=None, keep=False):
    base, profile, state_path, delta_dir = paths(root)
    if not os.path.isfile(profile):
        sys.exit("There is no profile to record: %s does not exist." % profile)
    if expect:
        target = expect if os.path.isabs(expect) else os.path.join(root, expect)
        if not os.path.isfile(target) or os.path.getsize(target) == 0:
            sys.exit("Not recorded: %s was not written. Recording now would mark the change as seen "
                     "without anything describing it." % target)
    keep_local(root)
    os.makedirs(delta_dir, exist_ok=True)
    previous = load_state(root) or {}
    pending = os.path.join(base, "pending.json")
    if keep and previous.get("files"):
        files = previous["files"]            # a learned delta: nothing about the watched files changed
    else:
        try:
            with open(pending, encoding="utf-8") as fh:
                files = json.load(fh)
        except (OSError, ValueError):
            files = fingerprints(root)
    if not keep and os.path.isfile(pending):
        os.remove(pending)
    state = {"schema": SCHEMA, "created": previous.get("created") or datetime.now(timezone.utc).isoformat(),
             "recorded": datetime.now(timezone.utc).isoformat(), "files": files, "deltas": len(deltas(root))}
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    return {"recorded": len(files), "deltas": state["deltas"]}


def next_delta(root, slug):
    slug = re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-")[:40] or "change"
    numbers = [n for n in (delta_number(x) for x in deltas(root)) if n is not None]
    os.makedirs(paths(root)[3], exist_ok=True)
    return os.path.join(paths(root)[3], "delta-%03d-%s.md" % (max(numbers) + 1 if numbers else 1, slug))


def reset(root):
    base, profile, state_path, delta_dir = paths(root)
    removed = 0
    targets = [profile, state_path, os.path.join(base, "pending.json")]
    if os.path.isdir(delta_dir):
        targets += [os.path.join(delta_dir, n) for n in os.listdir(delta_dir)
                    if os.path.isfile(os.path.join(delta_dir, n))]
    for p in targets:
        if os.path.isfile(p):
            os.remove(p)
            removed += 1
    return {"removed": removed}


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "check"
    root = project_root()
    if cmd == "check":
        print(json.dumps(check(root), indent=1))
    elif cmd == "record":
        expect = args[args.index("--expect") + 1] if "--expect" in args and len(args) > args.index("--expect") + 1 else None
        print(json.dumps(record(root, expect=expect, keep="--keep" in args)))
    elif cmd == "next-delta":
        print(next_delta(root, args[1] if len(args) > 1 else "change"))
    elif cmd == "list":
        base, profile, _s, delta_dir = paths(root)
        if os.path.isfile(profile):
            print(profile)
        for name in deltas(root):
            print(os.path.join(delta_dir, name))
    elif cmd == "reset":
        print(json.dumps(reset(root)))
    else:
        sys.exit("Unknown command %r. Use: check | record [--expect PATH] [--keep] | next-delta SLUG | list | reset" % cmd)


if __name__ == "__main__":
    main()
