#!/usr/bin/env python3
"""Jira cycle time, backward moves and blocked time for the last closed sprints.

    jira_cycle.py [--project KEY] [--sprints N] [--board ID]
                  [--input DIR] [--kpi-dir DIR] [--out-dir DIR]

Two ways to get the data, both ending in the same deterministic computation:

1. Directly from Jira's REST API, when the environment has JIRA_URL and either
   JIRA_PERSONAL_TOKEN (Data Center) or JIRA_USERNAME + JIRA_API_TOKEN (Cloud).
   These are the variables the `mcp-atlassian` server uses, so a machine set up
   for it needs nothing more. Read-only; the token is never written anywhere.
2. From files (`--input DIR`): `sprints.json` plus issues with their changelog,
   saved there by whoever can read Jira (for example the jira-collector agent
   through an MCP server). See references/jira-input.md of the cycle-time skill.

Writes <kpi-dir>/delivery/cycle-time.json and an HTML report with charts.
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import charts as C                      # noqa: E402
import delivery_lib as L                # noqa: E402

FLAP_SECONDS = 60


# ---------------------------------------------------------------------- REST

class Jira:
    def __init__(self):
        self.base = (os.environ.get("JIRA_URL") or "").rstrip("/")
        token = os.environ.get("JIRA_PERSONAL_TOKEN")
        user, api_token = os.environ.get("JIRA_USERNAME"), os.environ.get("JIRA_API_TOKEN")
        if token:
            self.auth = "Bearer " + token
        elif user and api_token:
            self.auth = "Basic " + base64.b64encode(("%s:%s" % (user, api_token)).encode()).decode()
        else:
            self.auth = None

    @property
    def available(self):
        return bool(self.base and self.auth)

    def get(self, path, **params):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"Authorization": self.auth, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            raise RuntimeError("Jira answered %s for %s" % (exc.code, path))
        except urllib.error.URLError as exc:
            raise RuntimeError("Jira is not reachable at %s: %s" % (self.base, exc.reason))

    def paged(self, path, key, **params):
        start, out = 0, []
        while True:
            page = self.get(path, startAt=start, maxResults=50, **params)
            items = page.get(key) or []
            out += items
            start += len(items)
            if not items or page.get("isLast") or start >= (page.get("total") or 10 ** 9):
                return out

    def collect(self, project, n_sprints, board=None):
        if not board:
            boards = self.paged("/rest/agile/1.0/board", "values", projectKeyOrId=project, type="scrum")
            if not boards:
                raise RuntimeError("No scrum board found for project %s; pass --board." % project)
            board = boards[0]["id"]
        closed = self.paged("/rest/agile/1.0/board/%s/sprint" % board, "values", state="closed")
        closed = sorted([s for s in closed if s.get("endDate")], key=lambda s: s["endDate"])[-n_sprints:]
        if not closed:
            raise RuntimeError("Board %s has no closed sprint." % board)
        issues, seen = [], set()
        for s in closed:
            for it in self.paged("/rest/agile/1.0/sprint/%s/issue" % s["id"], "issues", expand="changelog",
                                 fields="summary,issuetype,status,assignee,created,resolutiondate"):
                if it["key"] not in seen:
                    seen.add(it["key"])
                    issues.append(it)
        return closed, issues


# --------------------------------------------------------------------- input

def load_dir(path):
    sprints, issues = [], []
    for name in sorted(os.listdir(path)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(path, name), encoding="utf-8") as fh:
            data = json.load(fh)
        if name == "sprints.json":
            sprints = data.get("values", data) if isinstance(data, dict) else data
        elif isinstance(data, list):
            issues += data
        elif isinstance(data, dict) and "issues" in data:
            issues += data["issues"]
        elif isinstance(data, dict):
            issues.append(data)
    return sprints, issues


def normalize(issue):
    """One issue, from Jira's REST shape or the compact shape, to plain fields."""
    if "transitions" in issue:      # compact shape
        trans = [{"at": L.parse_ts(t.get("at")), "from": t.get("from"), "to": t.get("to")}
                 for t in issue["transitions"]]
        out = {"key": issue.get("key"), "type": issue.get("type") or "Unknown",
               "assignee": issue.get("assignee") or "(unassigned)", "status": issue.get("status"),
               "created": L.parse_ts(issue.get("created")), "resolved": L.parse_ts(issue.get("resolved")),
               "summary": issue.get("summary") or ""}
    else:
        f = issue.get("fields") or {}
        trans = []
        for h in (issue.get("changelog") or {}).get("histories") or []:
            for item in h.get("items") or []:
                if item.get("field") == "status":
                    trans.append({"at": L.parse_ts(h.get("created")), "from": item.get("fromString"),
                                  "to": item.get("toString")})
        out = {"key": issue.get("key"), "type": (f.get("issuetype") or {}).get("name") or "Unknown",
               "assignee": (f.get("assignee") or {}).get("displayName") or "(unassigned)",
               "status": (f.get("status") or {}).get("name"), "created": L.parse_ts(f.get("created")),
               "resolved": L.parse_ts(f.get("resolutiondate")), "summary": f.get("summary") or ""}
    out["transitions"] = sorted([t for t in trans if t["at"]], key=lambda t: t["at"])
    return out


# ------------------------------------------------------------------- compute

def analyse(sprints, raw_issues, cfg, now=None):
    now = now or datetime.now(timezone.utc)
    st = cfg["jira"]["statuses"]
    rank = {}
    for i, group in enumerate(st["order"]):
        for name in ([group] if isinstance(group, str) else group):
            rank[name.lower()] = i
    in_progress = {s.lower() for s in st["in_progress"]}
    blocked = {s.lower() for s in st["blocked"]}
    sprints = sorted([{"name": s.get("name"), "start": L.parse_ts(s.get("startDate") or s.get("start")),
                       "end": L.parse_ts(s.get("endDate") or s.get("end"))} for s in sprints],
                     key=lambda s: s["start"])
    period_start, period_end = sprints[0]["start"], sprints[-1]["end"]
    unknown = set()
    issues = [normalize(i) for i in raw_issues]
    for it in issues:
        tr = it["transitions"]
        for t in tr:
            for name in (t["from"], t["to"]):
                if name and name.lower() not in rank and name.lower() not in blocked:
                    unknown.add(name)
        started = next((t["at"] for t in tr if (t["to"] or "").lower() in in_progress), None)
        it["started"] = started
        it["cycle"] = L.business_days(started, it["resolved"]) if started and it["resolved"] and it["resolved"] > started else None
        # Blocked time: every visit to a blocked status, open visits run until resolution or now.
        days = 0.0
        for i, t in enumerate(tr):
            if (t["to"] or "").lower() in blocked:
                until = tr[i + 1]["at"] if i + 1 < len(tr) else (it["resolved"] or now)
                days += max(0.0, (until - t["at"]).total_seconds() / 86400.0)
        it["blocked_days"] = days
        it["still_blocked"] = (it["status"] or "").lower() in blocked
        # Backward moves inside the analysed period; a move undone within a minute is a slip of the hand.
        back = []
        for i, t in enumerate(tr):
            a, b = rank.get((t["from"] or "").lower()), rank.get((t["to"] or "").lower())
            if a is None or b is None or b >= a or not (period_start <= t["at"] <= period_end):
                continue
            nxt = tr[i + 1] if i + 1 < len(tr) else None
            if nxt and nxt["to"] == t["from"] and (nxt["at"] - t["at"]).total_seconds() <= FLAP_SECONDS:
                continue
            back.append({"at": t["at"].isoformat(), "from": t["from"], "to": t["to"],
                         "from_late_stage": a >= rank.get("in test", 3)})
        it["backward"] = back
        it["sprint"] = next((s["name"] for s in sprints
                             if it["resolved"] and s["start"] <= it["resolved"] <= s["end"]), None)
    resolved = [i for i in issues if i["sprint"]]

    def stats(items):
        s = L.summarize([i["cycle"] for i in items if i["cycle"] is not None], total=len(items))
        rev = sum(1 for i in items if i["backward"])
        lo, hi = L.wilson_ci(rev, len(items))
        s.update({"reverted": rev, "revert_rate": rev / float(len(items)) if items else None,
                  "revert_lo": lo, "revert_hi": hi,
                  "blocked_days": sum(i["blocked_days"] for i in items),
                  "blocked_tickets": sum(1 for i in items if i["blocked_days"] > 0)})
        return s

    names = [s["name"] for s in sprints]
    by_sprint = {n: stats([i for i in resolved if i["sprint"] == n]) for n in names}
    by_type = {k: stats(v) for k, v in L.group_by(resolved, lambda i: i["type"]).items()}
    by_assignee = {k: stats(v) for k, v in L.group_by(resolved, lambda i: i["assignee"]).items()}
    blocked_rank = sorted([i for i in issues if i["blocked_days"] > 0], key=lambda i: -i["blocked_days"])
    return {
        "sprints": [{"name": s["name"], "start": s["start"].isoformat(), "end": s["end"].isoformat()} for s in sprints],
        "issues": len(issues), "resolved_in_window": len(resolved),
        "overall": stats(resolved), "by_sprint": by_sprint, "by_type": by_type, "by_assignee": by_assignee,
        "unknown_statuses": sorted(unknown),
        "no_cycle": [i["key"] for i in resolved if i["cycle"] is None],
        "reverted": [{"key": i["key"], "type": i["type"], "sprint": i["sprint"], "assignee": i["assignee"],
                      "moves": i["backward"]} for i in resolved if i["backward"]],
        "blocked": [{"key": i["key"], "type": i["type"], "status": i["status"], "assignee": i["assignee"],
                     "days": i["blocked_days"], "still_blocked": i["still_blocked"],
                     "bucket": i["sprint"] or "open"} for i in blocked_rank],
        "longest": [{"key": i["key"], "type": i["type"], "assignee": i["assignee"], "cycle": i["cycle"],
                     "sprint": i["sprint"]} for i in sorted([i for i in resolved if i["cycle"] is not None],
                                                             key=lambda i: -i["cycle"])[:10]],
    }


# -------------------------------------------------------------------- render

def fmt(v, unit, digits=1):
    return "–" if v is None else ("%s %s" % (C.fmt_num(v, digits), unit)).strip()


def pct(v):
    return "–" if v is None else "%d %%" % round(v * 100)


def render(r, project, cfg):
    o = r["overall"]
    show = cfg["show_people"]
    names = [s["name"] for s in r["sprints"]]

    def row(name, s):
        ci = "–" if s["ci_lo"] is None else "%s – %s days" % (C.fmt_num(s["ci_lo"], 1), C.fmt_num(s["ci_hi"], 1))
        return [name, "%d tickets" % s["total"], "%d tickets" % s["n"], pct(s["coverage"]),
                fmt(s["median"], "days"), fmt(s["mean"], "days"), ci,
                "%d tickets" % s["reverted"], pct(s["revert_rate"]), fmt(s["blocked_days"], "days"),
                ", ".join(s["flags"])]

    cols = ["", "Resolved", "With cycle time", "Coverage", "Median cycle time", "Mean", "90 % CI of median",
            "Moved backward", "Backward rate", "Blocked time", "Flags"]
    num = tuple(range(1, 10))

    def pts(order, table_, value="median", lo="ci_lo", hi="ci_hi", scale=1.0):
        return [{"label": k, "value": None if table_[k][value] is None else table_[k][value] * scale,
                 "lo": None if table_[k][lo] is None else table_[k][lo] * scale,
                 "hi": None if table_[k][hi] is None else table_[k][hi] * scale,
                 "low": table_[k]["low"], "n": "n=%d" % (table_[k]["n"] if value == "median" else table_[k]["total"])}
                for k in order]

    types = sorted(r["by_type"], key=lambda k: -r["by_type"][k]["n"])
    people = sorted(r["by_assignee"], key=lambda k: -(r["by_assignee"][k]["median"] or 0))
    late = sum(1 for t in r["reverted"] if any(m["from_late_stage"] for m in t["moves"]))
    bottom = [
        "Median cycle time is %s over %d tickets (90 %% CI %s – %s days); %s of resolved tickets have one."
        % (fmt(o["median"], "working days"), o["n"], C.fmt_num(o["ci_lo"] or 0, 1), C.fmt_num(o["ci_hi"] or 0, 1),
           pct(o["coverage"])),
        "%s of resolved tickets (%d of %d) moved backward in the workflow during these sprints; %d of them "
        "were sent back from testing, acceptance or done." % (pct(o["revert_rate"]), o["reverted"], o["total"], late),
        "%d tickets spent time blocked, %s in total; %d are blocked now."
        % (len(r["blocked"]), fmt(sum(b["days"] for b in r["blocked"]), "days"),
           sum(1 for b in r["blocked"] if b["still_blocked"])),
    ]
    if "skewed" in o["flags"]:
        bottom.append("The mean (%s) is far above the median: a few long-running tickets pull it up."
                      % fmt(o["mean"], "days"))
    return C.page(
        "Cycle time — %s" % project,
        ["%s to %s" % (r["sprints"][0]["start"][:10], r["sprints"][-1]["end"][:10]),
         "%d closed sprints: %s" % (len(names), ", ".join(names)),
         "%d tickets, %d resolved inside these sprints" % (r["issues"], r["resolved_in_window"]),
         "generated %s UTC" % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")],
        C.bullets(bottom),
        C.tiles([("Median cycle time", fmt(o["median"], "days"), "working days, in progress to done"),
                 ("Backward rate", pct(o["revert_rate"]), "%d of %d tickets" % (o["reverted"], o["total"])),
                 ("Blocked time", fmt(sum(b["days"] for b in r["blocked"]), "days"), "%d tickets" % len(r["blocked"])),
                 ("Blocked now", "%d tickets" % sum(1 for b in r["blocked"] if b["still_blocked"]), None),
                 ("Coverage", pct(o["coverage"]), "%d of %d resolved tickets" % (o["n"], o["total"]))]),
        C.definitions([
            ("Cycle time", "Working days (Monday to Friday, no holiday calendar) from a ticket's first entry "
                           "into %s to its resolution, for tickets resolved inside the sprint. It includes "
                           "time spent blocked or reworked." % " / ".join(cfg["jira"]["statuses"]["in_progress"])),
            ("Sprint", "A ticket belongs to the sprint whose dates contain its resolution date, not to every "
                       "sprint it was planned in."),
            ("Moved backward", "A move to an earlier status in the configured order, dated inside the analysed "
                               "sprints. A move undone within a minute is ignored. Blocked is neither forward "
                               "nor backward."),
            ("Status order", " < ".join("/".join([g] if isinstance(g, str) else g)
                                        for g in cfg["jira"]["statuses"]["order"])),
            ("Blocked time", "Calendar days in %s, all visits added up; a ticket blocked now is counted "
                             "until today." % " / ".join(cfg["jira"]["statuses"]["blocked"])),
            ("Coverage", "Resolved tickets that have a cycle time, out of all resolved tickets. A ticket that "
                         "never entered an in-progress status has none."),
            ("Flags", "low n: fewer than %d tickets. skewed: mean more than twice the median." % L.LOW_N),
        ]),
        C.section("Per sprint",
                  C.grid(C.card("Median cycle time per sprint", C.columns(pts(names, r["by_sprint"]), "days", digits=1),
                                "working days · whisker = 90 % CI · faded = little data"),
                         C.card("Tickets moved backward per sprint", C.columns(
                             pts(names, r["by_sprint"], "revert_rate", "revert_lo", "revert_hi", 100.0), "%",
                             color_index=1), "% of resolved tickets · whisker = 90 % CI")),
                  C.table(cols, [row(n, r["by_sprint"][n]) for n in names] + [row("All sprints", o)], num)),
        C.section("Per issue type",
                  C.card("Median cycle time per type", C.hbars(
                      [{"label": t, "value": r["by_type"][t]["median"], "low": r["by_type"][t]["low"],
                        "note": "%d tickets" % r["by_type"][t]["n"]} for t in types], "days", digits=1)),
                  C.table(cols, [row(t, r["by_type"][t]) for t in types], num)),
        C.section("Per developer",
                  (C.card("Median cycle time per assignee", C.hbars(
                      [{"label": p, "value": r["by_assignee"][p]["median"], "low": r["by_assignee"][p]["low"],
                        "note": "%d tickets" % r["by_assignee"][p]["n"]} for p in people], "days", digits=1))
                   + C.table(cols, [row(p, r["by_assignee"][p]) for p in people], num)) if show
                  else "<p class='note'>Per-person figures are switched off (delivery.show_people).</p>",
                  note="The assignee is whoever holds the ticket when it is resolved, which is not always who "
                       "did the work. Ticket size and type differ between people; the numbers describe the "
                       "tickets as much as the person."),
        C.section("Blocked time",
                  C.card("Days blocked per ticket", C.hbars(
                      [{"label": b["key"], "value": b["days"],
                        "note": ("blocked now" if b["still_blocked"] else b["status"] or "") + " · " + b["type"]}
                       for b in r["blocked"]], "days", color_index=7, digits=1)),
                  C.table(["Ticket", "Type", "Status now", "Assignee", "Days blocked", "Resolved in"],
                          [[b["key"], b["type"], ("Blocked (still)" if b["still_blocked"] else b["status"] or "–"),
                            b["assignee"] if show else "–", fmt(b["days"], "days"), b["bucket"]] for b in r["blocked"]],
                          numeric=(4,))),
        C.section("Tickets that moved backward", C.table(
            ["Ticket", "Type", "Sprint", "Assignee", "Moves"],
            [[t["key"], t["type"], t["sprint"], t["assignee"] if show else "–",
              "; ".join("%s → %s (%s)" % (m["from"], m["to"], m["at"][:10]) for m in t["moves"])]
             for t in r["reverted"]])),
        C.section("Longest cycle times", C.table(
            ["Ticket", "Type", "Sprint", "Assignee", "Cycle time"],
            [[t["key"], t["type"], t["sprint"], t["assignee"] if show else "–", fmt(t["cycle"], "days")]
             for t in r["longest"]], numeric=(4,))),
        C.section("Data quality", C.bullets([
            ("Statuses not in the configured order, ignored when looking for backward moves: %s. Add them to "
             "delivery.jira.statuses.order to have them counted." % ", ".join(r["unknown_statuses"]))
            if r["unknown_statuses"] else "Every status seen is in the configured order.",
            ("Resolved without ever entering an in-progress status, so without a cycle time: %s."
             % ", ".join(r["no_cycle"])) if r["no_cycle"] else "Every resolved ticket has a cycle time.",
            "Source: " + r.get("source", "files"),
        ])),
        footer="Computed by jira_cycle.py.")


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Jira cycle time for the last closed sprints.")
    ap.add_argument("--project")
    ap.add_argument("--sprints", type=int)
    ap.add_argument("--board")
    ap.add_argument("--input", help="Directory with sprints.json and issue files, instead of the REST API.")
    ap.add_argument("--kpi-dir")
    ap.add_argument("--out-dir")
    args = ap.parse_args()

    kpi_dir = args.kpi_dir or L.find_kpi_dir()
    cfg = L.load_config(kpi_dir)
    project = args.project or cfg["jira"]["project"]
    if args.input:
        sprints, issues = load_dir(args.input)
        source = "files in %s" % args.input
        if not sprints or not issues:
            L.die("Expected sprints.json and at least one issue file in %s." % args.input)
    else:
        jira = Jira()
        if not jira.available:
            L.die("NO_JIRA_ACCESS: set JIRA_URL and JIRA_PERSONAL_TOKEN (or JIRA_USERNAME and "
                  "JIRA_API_TOKEN) in the environment, or collect the data to a directory and pass --input.")
        if not project:
            L.die("Which Jira project? Pass --project KEY or set delivery.jira.project in the KPI config.")
        try:
            sprints, issues = jira.collect(project, args.sprints or cfg["jira"]["sprints"],
                                           args.board or cfg["jira"]["board"])
        except RuntimeError as exc:
            L.die(str(exc))
        source = "Jira REST API at %s" % jira.base
    result = analyse(sprints, issues, cfg)
    result.update({"metric": "cycle-time", "unit": "working days", "project": project, "source": source,
                   "generated": datetime.now(timezone.utc).isoformat()})
    snap_dir, rep_dir = L.output_dirs(kpi_dir, args.out_dir)
    L.save_snapshot(snap_dir, "cycle-time", result)
    path = os.path.join(rep_dir, "cycle-time.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render(result, project or "Jira", cfg))
    print(path)


if __name__ == "__main__":
    main()
