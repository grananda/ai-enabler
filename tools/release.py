#!/usr/bin/env python3
"""Offline changes-fragment validation and deterministic release preparation (stdlib only)."""
import argparse
import datetime
import fnmatch
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "release/baseline.json"
CURRENT = "release/current.json"
DEPENDENCIES = "release/dependencies.json"
LEVELS = {"patch": 0, "minor": 1, "major": 2}
BRANCH = re.compile(r"(?:feat|fix|docs|chore|refactor|experiment)/[a-z0-9]+(?:-[a-z0-9]+)*$|release/(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$")
COMMIT = re.compile(r"(?:feat|fix|docs|chore|refactor|test|build|ci|perf|style|revert)(?:\([a-z0-9][a-z0-9/-]*\))?!?: \S.*$")
ASSET_VERSION = re.compile(r'(^  version: )[\"\']([^\"\']+)[\"\']', re.M)


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def git(root, *args):
    result = subprocess.run(["git", *args], cwd=root, capture_output=True)
    require(result.returncode == 0, "git " + " ".join(args) + ": " + result.stderr.decode("utf-8", "replace"))
    return result.stdout.decode("utf-8")


def json_text(value):
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def version(value):
    require(isinstance(value, str) and re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value), "Invalid stable version: " + str(value))
    return tuple(map(int, value.split(".")))


def bump(value, level):
    nums = list(version(value))
    i = {"major": 0, "minor": 1, "patch": 2}[level]
    nums[i] += 1
    nums[i + 1:] = [0] * (2 - i)
    return ".".join(map(str, nums))


def asset(path):
    match = re.match(r"(plugins/[^/]+/skills/[^/]+)/", path)
    if match:
        return match[1] + "/SKILL.md"
    if re.fullmatch(r"plugins/[^/]+/agents/[^/]+\.md", path):
        return path
    return None


def plugin(path):
    match = re.match(r"plugins/([^/]+)/", path)
    return match[1] if match else None


def read_tree(root, ref=None):
    if ref:
        git(root, "rev-parse", "--verify", ref + "^{commit}")
        names = git(root, "ls-tree", "-r", "--name-only", "-z", ref).split("\0")
        return {p: git(root, "show", ref + ":" + p).replace("\r\n", "\n") for p in names if p}
    names = git(root, "ls-files", "-z").split("\0") + git(root, "ls-files", "--others", "--exclude-standard", "-z").split("\0")
    result = {}
    for p in sorted(set(names) - {""}):
        path = root / p
        require(not path.is_symlink(), "Symlinks are unsupported release inputs: " + p)
        if path.is_file():
            result[p] = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return result


def versions(tree):
    result = {"marketplace": tree["VERSION"].strip()}
    for p, text in tree.items():
        if re.fullmatch(r"plugins/[^/]+/\.claude-plugin/plugin\.json", p):
            result[plugin(p)] = json.loads(text)["version"]
        elif asset(p) == p:
            front = text.split("\n---", 1)[0]
            match = ASSET_VERSION.search(front)
            require(match is not None, "Missing quoted metadata.version: " + p)
            result[p] = match[2]
    for value in result.values():
        version(value)
    return result


def hashes(tree):
    # Control records cannot hash themselves. Everything else, including docs/tests,
    # participates. Text normalization makes plans portable across Git checkouts.
    return {p: hashlib.sha256(text.encode("utf-8")).hexdigest() for p, text in sorted(tree.items())
            if not (p.startswith(".changes/") and p != ".changes/README.md") and p not in (BASELINE, CURRENT)}


def snapshot(tree):
    return json.loads(tree[CURRENT] if CURRENT in tree else tree[BASELINE])


def fragments(tree):
    result = {}
    for p in sorted(tree):
        if not p.startswith(".changes/") or p == ".changes/README.md":
            continue
        require(re.fullmatch(r"\.changes/[a-z0-9]+(?:-[a-z0-9]+)*\.json", p), "Unknown fragment file: " + p)
        f = json.loads(tree[p])
        require(set(f) == {"summary", "category", "components", "assets", "migration"}, "Invalid fragment fields: " + p)
        require(isinstance(f["summary"], str) and f["summary"].strip() and "\n" not in f["summary"], "Single-line summary required: " + p)
        require(f["category"] in ("Breaking", "Added", "Changed", "Fixed"), "Invalid category: " + p)
        require(isinstance(f["migration"], str), "Migration must be a string: " + p)
        for key in ("components", "assets"):
            require(isinstance(f[key], dict), "Expected bump map: " + p)
            require(all(isinstance(v, str) and v in LEVELS for v in f[key].values()), "Invalid bump: " + p)
        require(all(not k.startswith("plugins/") for k in f["components"]), "Asset paths belong in assets: " + p)
        require(all(asset(k) == k for k in f["assets"]), "Only metadata paths belong in assets: " + p)
        require("marketplace" in f["components"], "Marketplace bump required: " + p)
        breaking = "major" in list(f["components"].values()) + list(f["assets"].values())
        require(not (breaking or f["category"] == "Breaking") or (f["category"] == "Breaking" and f["migration"].strip()), "Breaking changes require category Breaking and migration instructions: " + p)
        result[p] = f
    return result


def combined(records):
    result = {}
    for f in records.values():
        for key, level in {**f["components"], **f["assets"]}.items():
            if key not in result or LEVELS[level] > LEVELS[result[key]]:
                result[key] = level
    return result


def coverage(tree, old, records, changed):
    bumps = combined(records)
    known = set(versions(tree)) | set(old["versions"])
    require(set(bumps) <= known, "Unknown component or asset in fragments: " + str(sorted(set(bumps) - known)))
    if changed:
        require("marketplace" in bumps, "Changes need a marketplace fragment")
    deps = json.loads(tree[DEPENDENCIES])
    require(isinstance(deps, dict), "Dependencies must map path patterns to asset lists")
    for pattern, targets in deps.items():
        require(isinstance(targets, list) and all(t in known and t.startswith("plugins/") for t in targets), "Unknown dependency target: " + pattern)
    needed = set()
    for path in changed:
        name = plugin(path)
        if name:
            require(name in bumps, "Missing plugin fragment coverage: " + path)
        target = asset(path)
        if target:
            needed.add(target)
        for pattern, targets in deps.items():
            if fnmatch.fnmatchcase(path, pattern):
                needed.update(targets)
    for target in needed:
        require(target in bumps, "Missing asset fragment coverage: " + target)
        if target in old["versions"] and target not in tree:
            require(bumps[target] == "major", "Removed/renamed assets require major and migration notes: " + target)
    for key, level in bumps.items():
        if key.startswith("plugins/"):
            require(plugin(key) in bumps, "Asset bump requires plugin bump: " + key)
            require(LEVELS[bumps[plugin(key)]] >= LEVELS[level], "Plugin bump must cover asset severity: " + key)
    if any(v != "patch" for k, v in bumps.items() if k != "marketplace"):
        require(LEVELS[bumps.get("marketplace", "patch")] >= 1, "New/breaking plugin behavior requires marketplace minor or major")
    return bumps


def validate_branch(name, target=None):
    require(name == "main" or BRANCH.fullmatch(name), "Invalid branch name: " + name)
    require(not (name.startswith("experiment/") and target == "main"), "Experiments cannot merge directly to main; promote to a governed branch")


def validate_commit(subject):
    require(COMMIT.fullmatch(subject), "Not a Conventional Commit: " + subject)


def validate_pending(tree, base, branch):
    current = versions(tree)
    previous = versions(base)
    require(set(k for k in current if not k.startswith("plugins/")) == set(k for k in previous if not k.startswith("plugins/")), "Plugin addition/removal needs a separate reviewed tooling migration")
    for key in current.keys() & previous.keys():
        require(current[key] == previous[key], "Final versions change only in release MRs: " + key)
    for key in current.keys() - previous.keys():
        require(current[key] == "0.0.0", "New assets use unreleased metadata.version 0.0.0: " + key)
    for p in set(tree) | set(base):
        if p == CURRENT or p.startswith("release/archive/") or (p == BASELINE and p in base):
            require(tree.get(p) == base.get(p), "Release record is immutable outside release MRs: " + p)
    require(tree.get("CHANGELOG.md") == base.get("CHANGELOG.md"), "Published changelog changes only in release MRs")
    records = fragments(tree)
    for p in fragments(base):
        require(tree.get(p) == base[p], "Merged fragments are immutable; add a correcting fragment: " + p)
    changed = {p for p in set(base) | set(tree) if base.get(p) != tree.get(p)
               and (not p.startswith(".changes/") or p == ".changes/README.md")}
    added = {p: f for p, f in records.items() if p not in base}
    if branch.startswith("experiment/"):
        return
    coverage(tree, {"versions": previous}, added, changed)


def tags_for(old, new):
    tags = ["marketplace-v" + new["marketplace"]]
    tags += [k + "-v" + v for k, v in sorted(new.items()) if k != "marketplace" and not k.startswith("plugins/") and old.get(k) != v]
    return tags


def guard_new_tags(tags, local_tags):
    require(not set(tags) & set(local_tags), "Release tag already exists (immutable): " + ", ".join(sorted(set(tags) & set(local_tags))))


def plan(tree, date, local_tags=()):
    datetime.date.fromisoformat(date)
    old = snapshot(tree)
    current_versions = versions(tree)
    require(all(current_versions.get(k) == v for k, v in old["versions"].items() if k in current_versions), "Restore published versions before preparing a release")
    require(all(current_versions[k] == "0.0.0" for k in current_versions.keys() - old["versions"].keys()), "New assets must start at 0.0.0")
    records = fragments(tree)
    require(records, "No pending fragments")
    current_hashes = hashes(tree)
    changed = {p for p in set(current_hashes) | set(old["hashes"]) if current_hashes.get(p) != old["hashes"].get(p)}
    bumps = coverage(tree, old, records, changed)
    before = versions(tree)
    after = dict(before)
    for key, level in bumps.items():
        if key in after:
            after[key] = bump(old["versions"].get(key, "0.0.0"), level)
    require(version(after["marketplace"]) > version(old["versions"]["marketplace"]), "Marketplace version must increase")
    tags = tags_for(old["versions"], after)
    guard_new_tags(tags, local_tags)
    out = dict(tree)
    out["VERSION"] = after["marketplace"] + "\n"
    for key, value in after.items():
        if key == "marketplace" or before[key] == value:
            continue
        if key.startswith("plugins/"):
            out[key] = ASSET_VERSION.sub(lambda m: m[1] + '"' + value + '"', out[key], count=1)
        else:
            path = "plugins/" + key + "/.claude-plugin/plugin.json"
            data = json.loads(out[path])
            data["version"] = value
            out[path] = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    heading = "## [" + after["marketplace"] + "] — " + date
    require(heading.split(" — ")[0] not in tree["CHANGELOG.md"], "Duplicate changelog version")
    section = heading + "\n\n" + " · ".join("`" + k + "` " + v for k, v in sorted(after.items()) if k != "marketplace" and not k.startswith("plugins/")) + "\n"
    for category in ("Breaking", "Added", "Changed", "Fixed"):
        entries = [f for f in records.values() if f["category"] == category]
        if entries:
            section += "\n### " + category + "\n\n"
            for f in entries:
                names = ", ".join(sorted(f["components"]))
                section += "- **" + names + ":** " + f["summary"] + (" Migration: " + f["migration"] if f["migration"] else "") + "\n"
    match = re.search(r"^## \[", out["CHANGELOG.md"], re.M)
    require(match is not None, "Changelog needs existing release history")
    pos = match.start()
    out["CHANGELOG.md"] = out["CHANGELOG.md"][:pos] + section + "\n" + out["CHANGELOG.md"][pos:]
    for p in records:
        dest = "release/archive/" + after["marketplace"] + "/" + p.split("/")[-1]
        require(dest not in tree, "Archive collision: " + dest)
        out[dest] = out.pop(p)
    out[CURRENT] = json_text({"schema": 1, "status": "prepared-not-proof-of-publication", "date": date,
                              "versions": after, "hashes": hashes(out), "tags": tags,
                              "fragments": sorted(records)})
    return out, {"versions": after, "tags": tags, "fragments": sorted(records), "date": date}


def validate_release(tree, base, branch, local_tags=()):
    require(CURRENT in tree, "Release snapshot missing")
    receipt = json.loads(tree[CURRENT])
    expected, report = plan(base, receipt["date"], local_tags)
    require(branch == "main" or branch == "release/" + report["versions"]["marketplace"], "Release branch must match planned marketplace version")
    different = sorted(p for p in set(tree) | set(expected) if tree.get(p) != expected.get(p))
    require(not different, "Release differs from deterministic plan against base: " + ", ".join(different))
    return report


def verify_tag(root, tree, tag):
    require(CURRENT in tree, "Legacy bootstrap is not a published release; verify first tag manually")
    record = snapshot(tree)
    require(tag in record["tags"], "Tag not in release snapshot: " + tag)
    require(git(root, "cat-file", "-t", "refs/tags/" + tag).strip() == "tag", "Release tags must be annotated")
    require(git(root, "rev-parse", "refs/tags/" + tag + "^{commit}").strip() == git(root, "rev-parse", "HEAD").strip(), "Tag does not point to checked-out commit")
    require(record["hashes"] == hashes(tree) and record["versions"] == versions(tree), "Published version content differs from release snapshot")
    require(not fragments(tree), "Release tag contains pending changes")


def ensure_prior_tags(root, tree):
    if CURRENT not in tree:
        return  # explicitly recorded legacy bootstrap, never invented tags
    for tag in snapshot(tree)["tags"]:
        require(git(root, "cat-file", "-t", "refs/tags/" + tag).strip() == "tag", "Prior release needs verified annotated tags: " + tag)
        published = read_tree(root, "refs/tags/" + tag)
        require(published.get(CURRENT) == tree[CURRENT] and hashes(published) == snapshot(tree)["hashes"], "Prior tag does not match stored release snapshot: " + tag)


def verify_bootstrap(root, tree):
    record = json.loads(tree[BASELINE])
    require(record.get("status") == "legacy-bootstrap-not-proof-of-publication" and record.get("tags") == [], "Bootstrap must not claim published tags")
    source = record.get("source_commit", "")
    require(re.fullmatch(r"[0-9a-f]{40}", source), "Bootstrap needs an exact source commit")
    original = read_tree(root, source)
    require(record["versions"] == versions(original) and record["hashes"] == hashes(original), "Bootstrap differs from its original Git source")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "plan", "prepare", "validate-release", "verify-tag"))
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--branch")
    parser.add_argument("--target")
    parser.add_argument("--commit", action="append", default=[])
    parser.add_argument("--commits", action="store_true", help="Validate non-merge commit subjects base..HEAD")
    parser.add_argument("--date", help="Explicit ISO release date; never inferred from wall clock")
    parser.add_argument("--tag")
    args = parser.parse_args(argv)
    try:
        tree = read_tree(ROOT)
        branch = args.branch or git(ROOT, "branch", "--show-current").strip()
        if args.command == "verify-tag":
            require(args.tag, "--tag required")
            verify_tag(ROOT, tree, args.tag)
        elif args.command in ("validate", "validate-release"):
            validate_branch(branch, args.target)
            base = read_tree(ROOT, args.base)
            if BASELINE not in base:
                verify_bootstrap(ROOT, tree)
            subjects = list(args.commit)
            if args.commits:
                subjects += git(ROOT, "log", "--no-merges", "--format=%s", args.base + "..HEAD").splitlines()
            for subject in subjects:
                validate_commit(subject)
            if args.command == "validate-release" or branch.startswith("release/") or base.get(CURRENT) != tree.get(CURRENT):
                ensure_prior_tags(ROOT, base)
                local_tags = git(ROOT, "tag", "--list").splitlines()
                if branch == "main" and CURRENT in tree:
                    # A main pipeline rerun after publication may encounter its own
                    # tags. Accept only annotated tags verified at this exact HEAD.
                    for tag in snapshot(tree)["tags"]:
                        if tag in local_tags:
                            verify_tag(ROOT, tree, tag)
                            local_tags.remove(tag)
                validate_release(tree, base, branch, local_tags)
            else:
                validate_pending(tree, base, branch)
        else:
            require(args.date, "--date YYYY-MM-DD required")
            ensure_prior_tags(ROOT, tree)
            out, report = plan(tree, args.date, git(ROOT, "tag", "--list").splitlines())
            if args.command == "prepare":
                require(branch == "release/" + report["versions"]["marketplace"], "Prepare only on matching release/<version> branch")
                require(not git(ROOT, "status", "--porcelain").strip(), "Prepare requires a clean committed working tree")
                # Preflight every output before writing. Delete only known parsed fragment
                # paths, after their exact content has been archived. Never glob-delete.
                for p in out:
                    path = ROOT / p
                    require(all(not parent.is_symlink() for parent in (path, *path.parents) if parent != ROOT.parent), "Refusing symlink output or ancestor: " + p)
                for p, text in out.items():
                    if tree.get(p) != text:
                        (ROOT / p).parent.mkdir(parents=True, exist_ok=True)
                        (ROOT / p).write_text(text, encoding="utf-8", newline="\n")
                for p in report["fragments"]:
                    (ROOT / p).unlink()
            print(json_text(report), end="")
        print("Release policy checks passed.")
        return 0
    except (Invalid, ValueError, KeyError, TypeError, OSError) as exc:
        print("Release policy: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
