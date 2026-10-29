#!/usr/bin/env python3
"""Versions travel with what changes.

    python3 tools/check_versions.py [base]        # base: origin/main

Compares the working tree (committed or not) with a base reference and checks
that every change carries its version bump. Same rules as the sibling
aidd-marketplace repository:

1. If anything in the repository changes, VERSION — the marketplace's own
   version — changes, and CHANGELOG.md gets a section for the new version.
2. If a skill changes (its SKILL.md, or anything in its scripts/ or references/),
   its metadata.version changes. Likewise an agent file and its metadata.version.
   A change that only touches a README does not count: it does not change what
   the skill does.
3. If a skill or agent of a plugin needs a bump, or the plugin's own hooks,
   scripts, references or manifest change, the version in its plugin.json changes.

The versions are independent of each other: a skill at 1.2.0 inside a plugin at
1.5.0 inside a marketplace at 1.9.0 is normal.

How much to bump is a judgement the check cannot make, so it is a rule for the
author: a fix is a patch, new behaviour is a minor, anything that breaks a
command, a flag, a file format or an output someone relies on is a major.

A version only counts as bumped when it is a valid semantic version higher than
the one at the base: a deleted, emptied, malformed or lowered version fails.
A skill or agent that has no metadata.version yet (a plugin that has not adopted
the convention) is skipped for rule 2; rules 1 and 3 still apply to it. A renamed
or moved skill is a removal plus a new asset: both plugins involved need a bump.
Exit codes: 0 up to date, 1 a bump is missing, 2 the base reference does not exist.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sh(*args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True).stdout


def at(ref, path):
    """A file's content at a reference, or None if it did not exist there."""
    r = subprocess.run(["git", "show", "%s:%s" % (ref, path)], cwd=ROOT, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def now(path):
    p = ROOT / path
    return p.read_text(encoding="utf-8") if p.is_file() else None


def asset_version(text):
    """metadata.version of a skill or agent, however it is quoted; None if it has none."""
    if not text or not text.startswith("---"):
        return None
    front = text[3:].split("\n---", 1)[0]
    m = re.search(r'^[ \t]+version:\s*["\']?([^"\'\s#]+)', front, re.M)
    return m.group(1) if m else None


def semver(value):
    """(major, minor, patch) or None when the value is not a semantic version."""
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)$", (value or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def moved_forward(before, after, what, errors):
    """Record an error unless `after` is a valid version greater than `before`."""
    if semver(after) is None:
        errors.append("%s has no valid semantic version (found %r)." % (what, after))
    elif before is not None and semver(before) is not None and semver(after) <= semver(before):
        errors.append("%s changed but its version did not go up (%s -> %s)." % (what, before, after))


def plugin_version(text):
    try:
        return json.loads(text).get("version") if text else None
    except ValueError:
        return None


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "origin/main"
    if subprocess.run(["git", "rev-parse", "--verify", base], cwd=ROOT, capture_output=True).returncode != 0:
        print("Base reference '%s' does not exist, so nothing was checked. Fetch it, or pass the "
              "reference to compare with: python3 tools/check_versions.py <base>." % base)
        return 2
    # --no-renames: a renamed or moved file must show up as gone from one place and new in another.
    changed = [f for f in sh("git", "diff", "--name-only", "--no-renames", base).splitlines() if f]
    changed += [f for f in sh("git", "ls-files", "--others", "--exclude-standard").splitlines() if f]
    changed = sorted(set(changed))
    if not changed:
        print("No changes against %s." % base)
        return 0

    errors, need_plugin_bump = [], set()

    # 1. The marketplace version accompanies any change.
    before, after = (at(base, "VERSION") or "").strip() or None, (now("VERSION") or "").strip() or None
    if after == before:
        errors.append("VERSION is still %s and %d file(s) changed. Bump it: patch for a fix, minor for new "
                      "behaviour, major for a breaking change." % (after or "missing", len(changed)))
    else:
        moved_forward(before, after, "VERSION", errors)

    # 1b. The changelog says what the new version brings.
    log = now("CHANGELOG.md")
    if log is None:
        errors.append("CHANGELOG.md is missing.")
    elif after and after != before:
        if not re.search(r"^## \[%s\]" % re.escape(after), log, re.M):
            errors.append("CHANGELOG.md has no entry for %s. Add a '## [%s] — <date>' section saying what changed."
                          % (after, after))
        elif "CHANGELOG.md" not in changed:
            errors.append("CHANGELOG.md was not updated, although VERSION changed.")
    elif "CHANGELOG.md" not in changed and after == before:
        pass    # already reported above: VERSION did not move

    # 2. Skills and agents that changed bump their own version.
    assets = {}
    for f in changed:
        m = re.match(r"(plugins/[^/]+)/skills/([^/]+)/(.+)$", f)
        if m and not f.endswith("README.md") and (m.group(3) == "SKILL.md"
                                                  or m.group(3).startswith(("scripts/", "references/"))):
            assets.setdefault("%s/skills/%s/SKILL.md" % (m.group(1), m.group(2)), []).append(f)
        m = re.match(r"(plugins/[^/]+)/agents/([^/]+\.md)$", f)
        if m:
            assets.setdefault(f, []).append(f)
    for manifest, files in sorted(assets.items()):
        plugin = "/".join(manifest.split("/")[:2])
        need_plugin_bump.add(plugin)        # also when the asset was removed or moved away
        current = now(manifest)
        if current is None:
            continue                        # gone: nothing left to version, the plugin bump records it
        version, previous = asset_version(current), asset_version(at(base, manifest))
        if version is None and previous is None:
            continue                        # this plugin has not adopted metadata.version yet
        if version is None:
            errors.append("%s lost its metadata.version." % manifest)
        elif previous is None:
            if semver(version) is None:     # a new asset arrives with a valid first version
                errors.append("%s has no valid semantic version (found %r)." % (manifest, version))
        else:
            moved_forward(previous, version, manifest, errors)

    # 3. Plugins whose content changed bump theirs.
    for f in changed:
        m = re.match(r"(plugins/[^/]+)/(hooks|scripts|references|agents|skills|\.claude-plugin)/", f)
        if m and not f.endswith("README.md"):
            need_plugin_bump.add(m.group(1))
    for plugin in sorted(need_plugin_bump):
        manifest = "%s/.claude-plugin/plugin.json" % plugin
        if now(manifest) is None:
            continue
        before, after = plugin_version(at(base, manifest)), plugin_version(now(manifest))
        if after is None:
            errors.append("%s is not valid JSON or has no version." % manifest)
        elif before == after:
            errors.append("%s changed but its plugin.json is still at %s." % (plugin, after))
        else:
            moved_forward(before, after, manifest, errors)

    if errors:
        print("Versions that did not follow the change:\n")
        for e in errors:
            print("  - " + e)
        print("\nRule: VERSION always; a skill, agent or plugin only when it changed. See AGENTS.md.")
        return 1
    print("Versions are up to date for the %d changed file(s)." % len(changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
