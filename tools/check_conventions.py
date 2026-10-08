#!/usr/bin/env python3
"""Checks the naming and metadata convention of every skill and agent.

    python3 tools/check_conventions.py [--strict] [plugin-dir ...]

The convention (one line each):
  - name: lowercase letters, numbers and hyphens; area first, then what it does
    (delivery-plan, metrics-usage-report); equal to the folder (skills) or file
    (agents) name.
  - metadata.owner: one named owner, as "Name <email>".
  - metadata.version: a semantic version, quoted ("1.2.0").

Without arguments it checks every plugin under plugins/. A plugin listed in
PENDING below is reported but does not fail the check, so the convention can be
adopted plugin by plugin; --strict makes every plugin fail.
Exit code 0 when the checked plugins comply, 1 otherwise.
"""

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)+$")          # at least "area-thing"
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")
OWNER = re.compile(r"^[^<>,;]+\s<[^<>@\s,;]+@[^<>@\s,;]+>$")     # one person: Name <email>
# Plugins that have not adopted the convention yet.
PENDING = {"ai-enabler-kpi"}


def frontmatter(path):
    """A minimal reader for the flat frontmatter these files use, plus one nested map."""
    text = open(path, encoding="utf-8", errors="replace").read()
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        return None
    block = text[4:text.index("\n---", 4)]
    data, parent = {}, None
    for line in block.split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indented = line.startswith((" ", "\t"))
        key, _, value = line.strip().partition(":")
        value = value.strip()
        if value.startswith("#"):          # "metadata:   # comment" opens a block, it is not a value
            value = ""
        if indented and parent is not None:
            data[parent][key] = value.strip("\"'")
            data[parent]["_raw_" + key] = value
        elif not indented:
            if value == "":
                data[key] = {}
                parent = key
            else:
                data[key] = value.strip("\"'")
                parent = None
    return data


def check(path, expected_name):
    problems = []
    if not os.path.isfile(path):
        return ["%s is missing" % os.path.basename(path)]
    fm = frontmatter(path)
    if fm is None:
        return ["no frontmatter"]
    name = fm.get("name")
    if name != expected_name:
        problems.append("name %r does not match %r" % (name, expected_name))
    if not name or not NAME.match(str(name)):
        problems.append("name is not area-first (lowercase words joined by hyphens, at least two)")
    meta = fm.get("metadata")
    if not isinstance(meta, dict):
        return problems + ["no metadata block (owner, version)"]
    if not meta.get("owner"):
        problems.append("metadata.owner is missing")
    elif not OWNER.match(meta["owner"]):
        problems.append("metadata.owner must be a person: Name <email>")
    version = meta.get("version")
    if not version or not SEMVER.match(version):
        problems.append("metadata.version is missing or not a semantic version")
    elif not meta.get("_raw_version", "").startswith(("\"", "'")):
        problems.append('metadata.version must be quoted ("%s"), or YAML reads it as a number' % version)
    return problems


def assets(plugin_dir):
    skills = os.path.join(plugin_dir, "skills")
    if os.path.isdir(skills):
        for name in sorted(os.listdir(skills)):
            if os.path.isdir(os.path.join(skills, name)):
                # A folder without SKILL.md is reported, not skipped: it would not load.
                yield "skill", name, os.path.join(skills, name, "SKILL.md")
    agents = os.path.join(plugin_dir, "agents")
    if os.path.isdir(agents):
        for name in sorted(os.listdir(agents)):
            if name.endswith(".md"):
                yield "agent", name[:-3], os.path.join(agents, name)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    strict = "--strict" in sys.argv
    plugins = args or sorted(os.path.join(ROOT, "plugins", d) for d in os.listdir(os.path.join(ROOT, "plugins"))
                             if os.path.isdir(os.path.join(ROOT, "plugins", d)))
    failed = False
    for plugin in plugins:
        pname = os.path.basename(os.path.normpath(plugin))
        if not os.path.isfile(os.path.join(plugin, ".claude-plugin", "plugin.json")):
            print("%s: not a plugin directory (no .claude-plugin/plugin.json) — FAIL" % plugin)
            failed = True
            continue
        pending = pname in PENDING and not strict
        total = bad = 0
        lines = []
        for kind, name, path in assets(plugin):
            total += 1
            problems = check(path, name)
            if problems:
                bad += 1
                lines.append("  %s %s: %s" % (kind, name, "; ".join(problems)))
        status = "ok" if not bad else ("pending" if pending else "FAIL")
        print("%s: %d assets, %d not compliant — %s" % (pname, total, bad, status))
        if bad:
            print("\n".join(lines))
            failed = failed or not pending
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
