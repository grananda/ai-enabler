#!/usr/bin/env python3
"""Which skills and agents are in use, and which have gone stale.

    assets.py [--metrics-dir DIR ...] [--assets-dir DIR ...] [--stale-days 90] [--out-dir DIR]

Shared assets rot when nobody prunes them: the author moves on, nobody dares
delete, nobody trusts the folder. This lists every skill and agent that is
installed, with its owner and version, when it was last used and how often,
taken from the events the usage hooks record. An asset unused for 90 days is a
candidate for archiving at the quarterly review.

Assets are looked for in the project's `.claude/skills` and `.claude/agents`,
and in the plugins of the marketplace this script ships with. `--assets-dir`
adds a directory that holds `skills/` and `agents/` (for example another
plugin).

It only knows what was recorded: projects where capture is on, on this machine
unless event files are shared. "Not seen" is evidence of no use only when the
recording covers the period, which the report states.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import charts as C                      # noqa: E402

STALE_DAYS = 90


def frontmatter(path):
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return {}
    if not text.startswith("---\n") or "\n---" not in text[4:]:
        return {}
    block = text[4:text.index("\n---", 4)]
    out = {}
    for key in ("name",):
        m = re.search(r"^%s:\s*(.+)$" % key, block, re.M)
        if m:
            out[key] = m.group(1).strip().strip("\"'")
    for key in ("owner", "version"):
        m = re.search(r"^[ \t]+%s:\s*(.+)$" % key, block, re.M)
        if m:
            out[key] = m.group(1).strip().strip("\"'")
    return out


def scan(directory, prefix=""):
    """Skills and agents under one directory that holds skills/ and agents/."""
    found = []
    skills = os.path.join(directory, "skills")
    if os.path.isdir(skills):
        for name in sorted(os.listdir(skills)):
            path = os.path.join(skills, name, "SKILL.md")
            if os.path.isfile(path):
                fm = frontmatter(path)
                found.append({"kind": "skill", "name": prefix + (fm.get("name") or name), "path": path,
                              "owner": fm.get("owner"), "version": fm.get("version")})
    agents = os.path.join(directory, "agents")
    if os.path.isdir(agents):
        for name in sorted(os.listdir(agents)):
            if name.endswith(".md"):
                path = os.path.join(agents, name)
                fm = frontmatter(path)
                found.append({"kind": "agent", "name": prefix + (fm.get("name") or name[:-3]), "path": path,
                              "owner": fm.get("owner"), "version": fm.get("version")})
    return found


def version_key(name):
    m = re.match(r"^(\d+)\.(\d+)\.(\d+)", name)
    return tuple(int(x) for x in m.groups()) if m else (-1, -1, -1)


def marketplace_plugins():
    """Directories of the plugins of the marketplace this script ships with.

    Two layouts exist. In a clone of the marketplace the plugins are siblings:
    plugins/<plugin>/scripts/. Installed, Claude Code keeps each plugin as
    cache/<marketplace>/<plugin>/<version>/, so the siblings are one level
    further up and each has one folder per installed version: the running
    plugin is taken as it is, the others at their newest version.
    """
    me = os.path.dirname(HERE)
    parent = os.path.dirname(me)
    def is_plugin(d):
        return os.path.isfile(os.path.join(d, ".claude-plugin", "plugin.json"))
    siblings = [os.path.join(parent, d) for d in sorted(os.listdir(parent))] if os.path.isdir(parent) else []
    if any(is_plugin(d) for d in siblings if d != me):
        return [d for d in siblings if is_plugin(d)]                      # a clone: plugins/<plugin>
    out = [me] if is_plugin(me) else []
    market = os.path.dirname(parent)                                      # cache/<marketplace>
    for name in sorted(os.listdir(market)) if os.path.isdir(market) else []:
        folder = os.path.join(market, name)
        if folder == parent or not os.path.isdir(folder):
            continue
        versions = [v for v in os.listdir(folder) if is_plugin(os.path.join(folder, v))]
        if versions:
            out.append(os.path.join(folder, max(versions, key=version_key)))
    return out


def plugin_prefix(directory):
    try:
        with open(os.path.join(directory, ".claude-plugin", "plugin.json"), encoding="utf-8") as fh:
            name = json.load(fh).get("name")
    except (OSError, ValueError):
        name = None
    return (name + ":") if name else ""


def installed(extra_dirs=(), project=None):
    """Every asset we can see: the project's own, this marketplace's plugins, and any extra directory."""
    project = project or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    assets = scan(os.path.join(project, ".claude"))
    for d in marketplace_plugins():
        assets += scan(d, prefix=plugin_prefix(d))
    for d in extra_dirs:
        assets += scan(d, prefix=plugin_prefix(d))
    seen, unique = set(), []
    for a in assets:
        if (a["kind"], a["name"]) not in seen:
            seen.add((a["kind"], a["name"]))
            unique.append(a)
    return unique


def usage(events):
    """{(kind, name): {"uses": n, "last": epoch}} from recorded events."""
    out = {}

    def hit(kind, name, t):
        if not name:
            return
        u = out.setdefault((kind, name), {"uses": 0, "last": 0})
        u["uses"] += 1
        u["last"] = max(u["last"], t)

    for e in events:
        ev = e.get("ev")
        if ev == "tool" and e.get("skill"):
            hit("skill", e["skill"], e["t"])
        elif ev == "prompt" and e.get("kind") == "command" and e.get("command"):
            hit("skill", e["command"], e["t"])          # a skill run as a slash command
        elif ev == "subagent" and e.get("agent"):
            hit("agent", e["agent"], e["t"])
    return out


def classify(assets, events, stale_days=STALE_DAYS, now=None):
    """Pass every recorded event, not a filtered subset: an asset used by someone
    else, or outside a date range, is still in use."""
    now = now or datetime.now(timezone.utc).timestamp()
    used = usage(events)
    # A plugin skill can be recorded without its plugin prefix; count that use
    # when the short name belongs to exactly one installed asset of that kind.
    short = {}
    for a in assets:
        short.setdefault((a["kind"], a["name"].split(":")[-1]), []).append(a["name"])
    for (kind, name), u in list(used.items()):
        owners = short.get((kind, name)) or []
        if ":" not in name and len(owners) == 1 and owners[0] != name:
            full = used.setdefault((kind, owners[0]), {"uses": 0, "last": 0})
            full["uses"] += u["uses"]
            full["last"] = max(full["last"], u["last"])
    first = min((e["t"] for e in events), default=None)
    recorded = (now - first) / 86400.0 if first else 0.0
    rows = []
    for a in assets:
        u = used.get((a["kind"], a["name"]))
        # An asset cannot have gone unused for longer than it has existed.
        try:
            born = os.path.getmtime(a["path"]) if a.get("path") else None
        except OSError:
            born = None
        covered = min(recorded, (now - born) / 86400.0) if born else recorded
        row = dict(a, uses=u["uses"] if u else 0, last=u["last"] if u else None)
        if u:
            idle = (now - u["last"]) / 86400.0
            row["idle_days"] = idle
            row["status"] = "in use" if idle < stale_days else "stale"
            row["why"] = "last used %d days ago" % idle
        elif covered >= stale_days:
            row["idle_days"] = covered
            row["status"] = "stale"
            row["why"] = "never used in %d days of recorded sessions" % covered
        else:
            row["idle_days"] = None
            row["status"] = "not seen yet"
            row["why"] = ("no use recorded, but only %d days can be judged (recording, or the age of the file)"
                          % max(covered, 0))
        rows.append(row)
    order = {"stale": 0, "not seen yet": 1, "in use": 2}
    rows.sort(key=lambda r: (order[r["status"]], -(r["idle_days"] or 0), r["name"]))
    return {"stale_days": stale_days, "covered_days": recorded, "assets": rows,
            "counts": {s: sum(1 for r in rows if r["status"] == s) for s in order}}


def table_rows(result):
    def day(t):
        return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d") if t else "–"
    return [[r["name"], r["kind"], r["owner"] or "no owner", r["version"] or "–", day(r["last"]),
             "%d" % r["uses"], r["status"], r["why"]] for r in result["assets"]]


HEADERS = ["Skill or agent", "Kind", "Owner", "Version", "Last used", "Uses", "Status", "Why"]
NOTE = ("Unused for %d days means a candidate for archiving at the next quarterly review; an asset without an "
        "owner is a candidate for removal. This only knows the sessions that were recorded (%d days so far, in "
        "projects with capture on), so check with the owner before archiving. The number of assets is context, "
        "never a target.")


def report_section(result):
    """The table as a section of the usage report (Markdown, HTML and JSON alike)."""
    return {"title": "Skills and agents in use", "note": NOTE % (result["stale_days"], result["covered_days"]),
            "headers": HEADERS, "rows": table_rows(result), "bar": None}


def main():
    import usage_report as U
    ap = argparse.ArgumentParser(description="Skills and agents in use, and the ones gone stale.")
    ap.add_argument("--metrics-dir", "--kpi-dir", action="append", dest="metrics_dir")
    ap.add_argument("--assets-dir", action="append", default=[],
                    help="A directory holding skills/ and agents/ to include. Repeatable.")
    ap.add_argument("--stale-days", type=int, default=STALE_DAYS)
    ap.add_argument("--out-dir")
    args = ap.parse_args()
    dirs = args.metrics_dir or U.default_metrics_dirs()
    if not dirs:
        sys.exit("No metrics directory found. Usage capture has to be on for this report: "
                 "run /ai-enabler-metrics:metrics-usage-init in the project, or pass --metrics-dir.")
    events, _files = U.load_events(dirs, None, None, None, None)
    result = classify(installed(args.assets_dir), events, args.stale_days)
    out_dir = args.out_dir or os.path.join(dirs[0], "reports", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    os.makedirs(out_dir, exist_ok=True)
    c = result["counts"]
    page = C.page("Skills and agents in use",
                  ["%d assets" % len(result["assets"]), "stale after %d days" % result["stale_days"],
                   "recording covers %d days" % result["covered_days"],
                   "generated %s UTC" % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")],
                  C.tiles([("Stale", "%d" % c["stale"], "unused for %d days or more" % result["stale_days"]),
                           ("Not seen yet", "%d" % c["not seen yet"], "too little recording to tell"),
                           ("In use", "%d" % c["in use"], None),
                           ("Without an owner", "%d" % sum(1 for r in result["assets"] if not r["owner"]), None)]),
                  C.table(HEADERS, table_rows(result), numeric=(5,)),
                  "<p class='note'>%s</p>" % C.e(NOTE % (result["stale_days"], result["covered_days"])),
                  footer="Computed by assets.py from the events recorded by the usage hooks.")
    with open(os.path.join(out_dir, "assets.html"), "w", encoding="utf-8") as fh:
        fh.write(page)
    with open(os.path.join(out_dir, "assets.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    print(os.path.join(out_dir, "assets.html"))


if __name__ == "__main__":
    main()
