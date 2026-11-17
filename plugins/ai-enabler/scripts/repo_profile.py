#!/usr/bin/env python3
"""Keeps track of whether the repository profile is still true.

    repo_profile.py check             missing, unrecorded, fresh or stale? (JSON on stdout; `summary` is what
                                      changed, in a few lines whatever the number of files: hand that to the
                                      scout, not the full `changed`/`added`/`removed` lists)
        --base BRANCH                 the branch to compare against (see "What is compared" below)
    repo_profile.py record            remember the state of the watched files
        --expect PATH                 refuse unless PATH (the profile or the delta just asked for) was written
        --keep                        keep the fingerprints as they are (a delta about something learned,
                                      not about a changed file); with --expect, also remember where the
                                      delta was learned (branch, base branch, base commit)
        --base BRANCH                 as for check
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
Line endings do not count: CRLF is read as LF before hashing, so a Windows
checkout and the committed file have the same fingerprint.

What is compared. The profile is shared by every run in the project, so it must
describe the base branch, not the unmerged work of one run. Inside a git work
tree, `check` and `record` read the watched files (which ones exist, and their
content) from the merge-base of HEAD and the base branch, never from the working
tree: a run that edits an ADR or package.json on its feature branch, committed or
not, leaves the profile fresh; once that change is merged into the base branch,
the next check reports it. The base branch is the first that exists of: `--base`,
`git.base_branch` in <project>/.enabler/config.json, the target of
refs/remotes/origin/HEAD, `main`, `master` (the local branch, else origin's).
Without git, without a commit, without a base branch or when git fails, the
working tree is read, as before. Both commands print what they compared:

    "against": {"kind": "commit", "ref": "<sha of the merge-base>", "base": "<branch>"}
    "against": {"kind": "working tree", "reason": "<why not a commit>"}

Learned deltas (`record --keep --expect DELTA`) can only come from the run's own
branch. `check` lists in `provisional` each one learned on a branch that is not
the base branch and has not been merged into it (or no longer exists), as
{"delta", "branch", "reason"}: what it says is unconfirmed until that work lands.
A branch counts as merged once it has commits beyond the point it was learned
from and its tip is in the base branch. Nothing is deleted or rewritten; deltas
recorded without that information are never provisional.

Fingerprints recorded before line endings were normalised (no "hash" key in
profile.json) are still compared the old way, so upgrading does not make a
profile stale; the next `record` rewrites them the new way.

The folders the pipeline writes to (repo-profile, runs, tickets, sources) get a .gitignore of their own that ignores
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
# How fingerprints are taken: sha256 of the content with CRLF read as LF. Stored in profile.json;
# files without it were hashed from the raw bytes and are compared the old way.
HASH = "sha256-lf"
BASE_FALLBACKS = ("main", "master")
# What is watched, by what it tells the profile. The kind only labels the change summary.
WATCHED_KINDS = [
    ("rules", [
        # the project's own rules
        "CLAUDE.md", "claude.md", "AGENTS.md", "CONTRIBUTING.md", "CONTRIBUTING", "ARCHITECTURE.md",
        ".claude/rules/*", ".github/CODEOWNERS", "CODEOWNERS", "docs/adr/*", "adr/*",
    ]),
    ("ci", [
        ".github/workflows/*.yml", ".github/workflows/*.yaml", "Jenkinsfile", ".gitlab-ci.yml",
        "azure-pipelines.yml", "bitbucket-pipelines.yml", ".circleci/config.yml", ".pre-commit-config.yaml",
    ]),
    ("build", [
        # build manifests
        "pom.xml", "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts", "gradle.properties",
        "package.json", "angular.json", "nx.json", "turbo.json", "lerna.json", "pnpm-workspace.yaml",
        "tsconfig.json", "tsconfig.*.json", "vite.config.*", "next.config.*", "webpack.config.*", "jest.config.*",
        "vitest.config.*", "karma.conf.*", "playwright.config.*", "cypress.config.*", "babel.config.*", "biome.json",
        "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "requirements-*.txt", "requirements/*.txt",
        "tox.ini", "pytest.ini", "mypy.ini", "go.mod", "Cargo.toml", "*.csproj", "*.sln", "Directory.Build.props",
        "Gemfile", "composer.json", "Makefile", "makefile", "GNUmakefile", "justfile", "Taskfile.yml", "Taskfile.yaml",
        "Dockerfile", "docker-compose.yml", "docker-compose.yaml", ".nvmrc", ".tool-versions",
    ]),
    ("lint", [
        # lint and format
        ".eslintrc", ".eslintrc.*", "eslint.config.*", ".prettierrc", ".prettierrc.*", "checkstyle.xml",
        "ruff.toml", ".ruff.toml", ".flake8", ".pylintrc", ".editorconfig", "sonar-project.properties",
        ".golangci.yml", ".golangci.yaml",
    ]),
]
# Watched at the root of the project only: every folder may have a README, one of them documents the commands.
ROOT_ONLY = ["README", "README.*"]
# Never looked into, wherever they are. Build output (dist, build, target ...) is left to .gitignore,
# because a source directory can legitimately carry one of those names.
IGNORED_DIRS = ("node_modules/", "vendor/", ".git/", ".enabler/")
WALK_SKIP = IGNORED_DIRS + ("dist/", "build/", "target/", "coverage/", ".nx/", ".venv/", "venv/", "__pycache__/")
PROFILE_LINES, DELTA_LINES, MANY_DELTAS = 150, 30, 10
# The change summary handed to the scout: every file when there are few, groups when there are many.
LIST_ALL, SUMMARY_GROUPS, EXAMPLES = 12, 20, 2
KIND_ORDER = ["rules", "ci", "build", "lint", "docs"]


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


def kind_of(path):
    """What a watched file tells the profile (rules, ci, build, lint, docs), or None if it is not watched."""
    if any(("/" + path).find("/" + d) >= 0 for d in IGNORED_DIRS):
        return None
    name = path.rsplit("/", 1)[-1]
    if "/" not in path and any(fnmatch.fnmatch(name, pat) for pat in ROOT_ONLY):
        return "docs"
    for kind, patterns in WATCHED_KINDS:
        for pat in patterns:
            if "/" in pat:
                # Directory patterns match at the root and under any module.
                if fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(path, "*/" + pat):
                    return kind
            elif fnmatch.fnmatch(name, pat):
                return kind
    return None


def watched(root):
    """Watched files, at the root and in the modules of a monorepo. Every one of them: no cap."""
    return sorted(path for path in set(candidates(root)) if kind_of(path))


def change_summary(changed, added, removed):
    """What changed, short enough to hand to the scout whatever the number of files. Up to LIST_ALL
    files, one line each. Beyond that, one line per kind and top-level folder with counts, file names
    and a couple of examples; files at the root of the project are always named one by one, since
    each of them (the root manifest, CLAUDE.md, the CI file) can change what the profile says."""
    entries = [(p, "changed") for p in changed] + [(p, "added") for p in added] + \
        [(p, "removed") for p in removed]
    if not entries:
        return []
    total = "%d watched files: %d changed, %d added, %d removed." % (
        len(entries), len(changed), len(added), len(removed))
    rank = lambda kind: KIND_ORDER.index(kind) if kind in KIND_ORDER else len(KIND_ORDER)
    if len(entries) <= LIST_ALL:
        rows = sorted(entries, key=lambda e: (rank(kind_of(e[0]) or ""), e[0]))
        return [total] + ["%s %s (%s)" % (how, p, kind_of(p) or "other") for p, how in rows]
    groups = {}
    for p, how in entries:
        kind = kind_of(p) or "other"
        key = (kind, p) if "/" not in p else (kind, p.split("/", 1)[0] + "/")
        g = groups.setdefault(key, {"changed": 0, "added": 0, "removed": 0, "names": {}, "paths": []})
        g[how] += 1
        name = p.rsplit("/", 1)[-1]
        g["names"][name] = g["names"].get(name, 0) + 1
        g["paths"].append(p)
    order = sorted(groups, key=lambda k: (rank(k[0]), "/" in k[1], -len(groups[k]["paths"]), k[1]))
    lines = [total]
    for kind, where in order[:SUMMARY_GROUPS]:
        g = groups[(kind, where)]
        counts = ", ".join("%d %s" % (g[h], h) for h in ("changed", "added", "removed") if g[h])
        if "/" not in where:
            lines.append("%s %s (%s)" % (counts.split(" ", 1)[1], where, kind))
            continue
        names = sorted(g["names"].items(), key=lambda kv: (-kv[1], kv[0]))
        named = ", ".join("%s ×%d" % kv for kv in names[:3]) + (", …" if len(names) > 3 else "")
        examples = ", ".join(sorted(g["paths"])[:EXAMPLES])
        lines.append("%s · %s · %s · %s · e.g. %s" % (kind, where, counts, named, examples))
    rest = order[SUMMARY_GROUPS:]
    if rest:
        lines.append("… and %d more groups (%d files)." % (len(rest), sum(len(groups[k]["paths"]) for k in rest)))
    return lines


def digest(content):
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def legacy_digests(content):
    """What a fingerprint taken the old way (raw bytes of the working tree) may be for this content:
    the bytes as they are, with LF, or with CRLF as a Windows checkout writes them."""
    lf = content.replace(b"\r\n", b"\n")
    return {hashlib.sha256(c).hexdigest() for c in (content, lf, lf.replace(b"\n", b"\r\n"))}


def key(path):
    return path.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def git(root, *args, data=None):
    """(return code, stdout bytes) of a git command; (None, b"") when git cannot be run."""
    try:
        out = subprocess.run(["git"] + list(args), cwd=root, input=data, capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None, b""
    return out.returncode, out.stdout


def git_text(root, *args):
    code, out = git(root, *args)
    return out.decode("utf-8", "surrogateescape").strip() if code == 0 else None


def config_base(root):
    try:
        with open(os.path.join(root, ".enabler", "config.json"), encoding="utf-8") as fh:
            config = json.load(fh)
    except (OSError, ValueError):
        return None
    section = config.get("git") if isinstance(config, dict) else None
    name = section.get("base_branch") if isinstance(section, dict) else None
    return name.strip() if isinstance(name, str) and name.strip() else None


def branch_commit(root, name):
    """(name shown, commit) of a branch: the local one, else origin's remote-tracking one."""
    for ref, shown in (("refs/heads/" + name, name), ("refs/remotes/origin/" + name, "origin/" + name),
                       ("refs/remotes/" + name, name)):
        sha = git_text(root, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
        if sha:
            return shown, sha
    return None


def base_names(root, requested):
    yield requested
    yield config_base(root)
    origin_head = git_text(root, "symbolic-ref", "-q", "refs/remotes/origin/HEAD")
    if origin_head and origin_head.startswith("refs/remotes/origin/"):
        yield origin_head[len("refs/remotes/origin/"):]
    yield from BASE_FALLBACKS


def reference(root, requested=None):
    """What the watched files are read from: (against, tip of the base branch or None)."""
    if git_text(root, "rev-parse", "--is-inside-work-tree") != "true":
        return {"kind": "working tree", "reason": "not a git work tree"}, None
    if not git_text(root, "rev-parse", "--verify", "--quiet", "HEAD^{commit}"):
        return {"kind": "working tree", "reason": "no commit yet"}, None
    base = next((b for b in (branch_commit(root, n) for n in base_names(root, requested) if n) if b), None)
    if base is None:
        return {"kind": "working tree", "reason": "no base branch (tried --base, git.base_branch, "
                                                  "origin/HEAD, main, master)"}, None
    name, tip = base
    ref = git_text(root, "merge-base", "HEAD", tip)
    if not ref:
        return {"kind": "working tree", "reason": "HEAD and %s have no common history" % name}, tip
    return {"kind": "commit", "ref": ref, "base": name}, tip


def committed(root, ref):
    """Content of the watched files at a commit: one ls-tree, one cat-file. None if git fails."""
    code, out = git(root, "ls-tree", "-r", "-z", ref)
    if code != 0:
        return None
    blobs = {}
    for entry in out.split(b"\0"):
        meta, _, name = entry.partition(b"\t")
        parts = meta.split()
        path = name.decode("utf-8", "surrogateescape")
        if len(parts) == 3 and parts[1] == b"blob" and kind_of(path):
            blobs[key(path)] = parts[2].decode("ascii")
    wanted = sorted(set(blobs.values()))
    if not wanted:
        return {}
    code, out = git(root, "cat-file", "--batch", data=("\n".join(wanted) + "\n").encode("ascii"))
    if code != 0:
        return None
    content, pos = {}, 0
    try:
        for sha in wanted:
            end = out.index(b"\n", pos)
            header = out[pos:end].split()
            if len(header) != 3:
                return None
            size = int(header[2])
            content[sha] = out[end + 1:end + 1 + size]
            pos = end + 1 + size + 1
    except ValueError:
        return None
    return {path: content[sha] for path, sha in blobs.items()}


def contents(root, against):
    """Content of the watched files, read from the commit in `against` or from the working tree.
    When git cannot read the commit, `against` is changed to say the working tree was read."""
    if against.get("kind") == "commit":
        found = committed(root, against["ref"])
        if found is not None:
            return found
        against.clear()
        against.update({"kind": "working tree", "reason": "git could not read the base commit"})
    found = {}
    for path in watched(root):
        try:
            with open(os.path.join(root, path).encode("utf-8", "surrogateescape"), "rb") as fh:
                found[key(path)] = fh.read()
        except OSError:
            continue
    return found


def fingerprints(root, against):
    return {path: digest(c) for path, c in contents(root, against).items()}


def paths(root):
    base = os.path.join(root, ".enabler", "repo-profile")
    return base, os.path.join(base, "profile.md"), os.path.join(base, "profile.json"), os.path.join(base, "deltas")


def keep_local(root):
    """Make sure git never picks these folders up, without touching any file of the project:
    each gets its own .gitignore that ignores everything in it."""
    for folder in (os.path.join(root, ".enabler", name) for name in ("repo-profile", "runs", "tickets", "sources")):
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


def provisional(root, state, names, base_tip, against):
    """Learned deltas whose branch has not been merged into the base branch."""
    learned = state.get("learned") if isinstance(state.get("learned"), dict) else {}
    if not learned or base_tip is None:
        return []
    base_name = against.get("base") or ""
    base_short = base_name[len("origin/"):] if base_name.startswith("origin/") else base_name
    found = []
    for name in names:
        info = learned.get(name)
        if not isinstance(info, dict):
            continue
        branch = info.get("branch")
        if branch and branch in (info.get("base"), base_name, base_short):
            continue
        if branch:
            hit = branch_commit(root, branch)
            if hit is None:
                found.append({"delta": name, "branch": branch,
                              "reason": "learned on %s, which no longer exists" % branch})
                continue
            tip = hit[1]
        else:
            tip = info.get("commit")
            branch = "a detached HEAD (%s)" % (tip or "?")[:12]
        in_base = bool(tip) and git(root, "merge-base", "--is-ancestor", tip, base_tip)[0] == 0
        # Learned from uncommitted work on a branch that never got past its fork point: nothing landed.
        moved = not info.get("base_ref") or \
            git(root, "merge-base", "--is-ancestor", tip, info["base_ref"])[0] != 0
        if not (in_base and moved):
            found.append({"delta": name, "branch": info.get("branch") or branch,
                          "reason": "learned on %s, not merged into %s" % (branch, base_name)})
    return found


def check(root, base_branch=None):
    base, profile, _state, delta_dir = paths(root)
    keep_local(root)
    state = load_state(root)
    names = deltas(root)
    against, base_tip = reference(root, base_branch)
    result = {"status": "missing", "root": root, "profile": profile, "deltas": len(names),
              "changed": [], "added": [], "removed": [], "summary": [], "against": against, "provisional": []}
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
    now_content, then = contents(root, against), state["files"]
    now = {p: digest(c) for p, c in now_content.items()}
    if state.get("hash") == HASH:
        same = lambda p: now[p] == then[p]
    else:
        same = lambda p: then[p] in legacy_digests(now_content[p])
    result["changed"] = sorted(p for p in now if p in then and not same(p))
    result["added"] = sorted(p for p in now if p not in then)
    result["removed"] = sorted(p for p in then if p not in now)
    result["summary"] = change_summary(result["changed"], result["added"], result["removed"])
    result["status"] = "stale" if (result["changed"] or result["added"] or result["removed"]) else "fresh"
    result["recorded"] = state.get("recorded")
    result["provisional"] = provisional(root, state, names, base_tip, against)
    pending = os.path.join(base, "pending.json")
    if result["status"] == "fresh" and os.path.isfile(pending):
        os.remove(pending)
    if result["status"] == "stale":
        # What `record` will store: the files as they were when the change was noticed, not as
        # they are when the delta is finished. An edit made in between is noticed by the next check.
        with open(pending, "w", encoding="utf-8") as fh:
            json.dump({"hash": HASH, "against": against, "files": now}, fh)
    return result


def learned_where(root, against):
    """Where a delta is being learned: branch, base branch and base commit. None outside git."""
    if against.get("kind") != "commit":
        return None
    branch = git_text(root, "rev-parse", "--abbrev-ref", "HEAD")
    return {"branch": branch if branch and branch != "HEAD" else None,
            "commit": git_text(root, "rev-parse", "HEAD"), "base": against["base"], "base_ref": against["ref"],
            "recorded": datetime.now(timezone.utc).isoformat()}


def record(root, expect=None, keep=False, base_branch=None):
    base, profile, state_path, delta_dir = paths(root)
    if not os.path.isfile(profile):
        sys.exit("There is no profile to record: %s does not exist." % profile)
    target = None
    if expect:
        target = expect if os.path.isabs(expect) else os.path.join(root, expect)
        if not os.path.isfile(target) or os.path.getsize(target) == 0:
            sys.exit("Not recorded: %s was not written. Recording now would mark the change as seen "
                     "without anything describing it." % target)
    keep_local(root)
    os.makedirs(delta_dir, exist_ok=True)
    previous = load_state(root) or {}
    pending = os.path.join(base, "pending.json")
    current = reference(root, base_branch)[0]
    against = dict(current)
    if keep and previous.get("files"):
        files, method = previous["files"], previous.get("hash")   # a learned delta: nothing watched changed
    else:
        try:
            with open(pending, encoding="utf-8") as fh:
                saved = json.load(fh)
        except (OSError, ValueError):
            saved = None
        if isinstance(saved, dict) and isinstance(saved.get("files"), dict):
            files, method = saved["files"], saved.get("hash")
            if isinstance(saved.get("against"), dict):
                against = saved["against"]
        elif isinstance(saved, dict):
            files, method = saved, None      # written by an earlier version: raw-byte fingerprints
            against = {"kind": "working tree", "reason": "noticed by an earlier version of this script"}
        else:
            files, method = fingerprints(root, against), HASH
    if not keep and os.path.isfile(pending):
        os.remove(pending)
    learned = dict(previous["learned"]) if isinstance(previous.get("learned"), dict) else {}
    if keep and target and os.path.normcase(os.path.dirname(os.path.abspath(target))) == \
            os.path.normcase(os.path.abspath(delta_dir)):
        where = learned_where(root, current)
        if where:
            learned[os.path.basename(target)] = where
    state = {"schema": SCHEMA, "created": previous.get("created") or datetime.now(timezone.utc).isoformat(),
             "recorded": datetime.now(timezone.utc).isoformat(), "files": files, "deltas": len(deltas(root))}
    if method:
        state["hash"] = method
    state["against"] = against
    if learned:
        state["learned"] = learned
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    return {"recorded": len(files), "deltas": state["deltas"], "against": against}


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


def option(args, name):
    if name in args and len(args) > args.index(name) + 1:
        return args[args.index(name) + 1]
    return None


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "check"
    root = project_root()
    if cmd == "check":
        print(json.dumps(check(root, base_branch=option(args, "--base")), indent=1))
    elif cmd == "record":
        print(json.dumps(record(root, expect=option(args, "--expect"), keep="--keep" in args,
                                base_branch=option(args, "--base"))))
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
        sys.exit("Unknown command %r. Use: check [--base BRANCH] | record [--expect PATH] [--keep] "
                 "[--base BRANCH] | next-delta SLUG | list | reset" % cmd)


if __name__ == "__main__":
    main()
