#!/usr/bin/env python3
"""Checks the delivery-flow metrics on fixtures, without GitHub or Jira.

    python3 tests/test_delivery.py
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import delivery_lib as L       # noqa: E402
import pr_metrics as P         # noqa: E402

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)   # a Monday
START = NOW - timedelta(weeks=4)


def ts(days_ago, hours=0):
    return (NOW - timedelta(days=days_ago, hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(number, author, merged_days_ago, title, add, dele, head="feature/x", created_before_h=30, bot=False):
    merged = NOW - timedelta(days=merged_days_ago)
    return {"number": number, "title": title, "url": "", "author": author, "bot": bot,
            "created_at": (merged - timedelta(hours=created_before_h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "merged_at": merged.strftime("%Y-%m-%dT%H:%M:%SZ"), "additions": add, "deletions": dele,
            "changed_files": 1, "head_ref": head, "merge_sha": "sha%d" % number}


def stats_checks():
    assert L.median([3, 1, 2]) == 2 and L.median([1, 2, 3, 4]) == 2.5 and L.median([]) is None
    lo, hi = L.bootstrap_ci([10] * 30)
    assert lo == hi == 10
    lo, hi = L.wilson_ci(0, 10)
    assert lo == 0 and 0.2 < hi < 0.25, (lo, hi)
    # Friday 12:00 to Monday 12:00 is one working day, three calendar days.
    fri = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
    assert abs(L.business_days(fri, fri + timedelta(days=3)) - 1.0) < 1e-9
    assert L.parse_ts("2026-10-02T12:00:00.000+0200").hour == 10
    assert L.iso_week(datetime(2026, 10, 5, tzinfo=timezone.utc)) == "2026-W41"
    assert P.excluded("apps/web/package-lock.json", L.DEFAULT_EXCLUDES)
    assert P.excluded("apps/web/dist/main.js", L.DEFAULT_EXCLUDES)
    assert not P.excluded("apps/web/src/distance.ts", L.DEFAULT_EXCLUDES)
    assert P.area_of("apps/web/src/a.ts", ["apps", "libs"]) == "apps/web"
    assert P.area_of("docs/a.md", ["apps"]) == "docs" and P.area_of("README.md", ["apps"]) == "(root)"


def pr_checks(tmp):
    prs = [
        pr(1, "ana", 20, "feat(web): PROJ-1: first", 100, 20),                       # anchor of PROJ-1
        pr(2, "ben", 15, "fix(web): PROJ-1: follow up", 10, 5),                      # follow-up, 5 days
        pr(3, "ana", 10, "PROJ-2 add api", 600, 100, head="feature/PROJ-2-api"),     # large
        pr(4, "ben", 9, 'Revert "PROJ-2 add api"', 100, 600),                         # revert
        pr(5, "cy", 3, "chore: tidy", 4, 2, head="chore/proj-3-tidy"),               # key from branch
        pr(6, "dependabot[bot]", 5, "bump x", 1, 1, bot=True),
        pr(7, "cy", 35, "feat(api): PROJ-9: before window", 50, 5),                  # lookback anchor
        pr(8, "ana", 26, "fix(api): PROJ-9: tweak", 5, 5),                           # follow-up of #7
    ]
    files = {
        "1": [{"filename": "apps/web/src/a.ts", "additions": 100, "deletions": 20}],
        "2": [{"filename": "apps/web/src/a.ts", "additions": 10, "deletions": 5}],
        "3": [{"filename": "libs/api/src/b.ts", "additions": 100, "deletions": 100},
              {"filename": "package-lock.json", "additions": 500, "deletions": 0}],
        "4": [{"filename": "libs/api/src/b.ts", "additions": 100, "deletions": 600}],
        "5": [{"filename": "yarn.lock", "additions": 4, "deletions": 2}],              # only excluded files
        "8": [{"filename": "apps/api/x.ts", "additions": 5, "deletions": 5}],
    }
    reviews = {
        # PR 1: bot review first, then the author, then a human 6 h after ready.
        "1": [{"login": "sonar[bot]", "bot": True, "state": "COMMENTED", "submitted_at": ts(21, -1)},
              {"login": "ana", "bot": False, "state": "COMMENTED", "submitted_at": ts(21, -2)},
              {"login": "ben", "bot": False, "state": "APPROVED",
               "submitted_at": (NOW - timedelta(days=20, hours=30) + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")}],
        "2": [{"login": "ana", "bot": False, "state": "APPROVED",
               "submitted_at": (NOW - timedelta(days=15, hours=30) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")}],
        "3": [{"login": "ben", "bot": False, "state": "CHANGES_REQUESTED",
               "submitted_at": (NOW - timedelta(days=10, hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ")}],
        "4": [], "5": [], "8": [],
    }
    # PR 3 was a draft: marked ready 12 h before its review, so the wait is 12 h, not 20 h.
    timeline = {"3": [{"event": "ready_for_review",
                       "created_at": (NOW - timedelta(days=10, hours=22)).strftime("%Y-%m-%dT%H:%M:%SZ")}]}
    data = {"repo": "acme/shop", "host": "github.com", "base": "main", "weeks": 4, "followup_days": 14,
            "window_start": START.isoformat(), "window_end": NOW.isoformat(),
            "lookback_start": (START - timedelta(days=14)).isoformat(),
            "prs": prs, "files": files, "reviews": reviews, "timeline": timeline}
    inp = os.path.join(tmp, "prs.json")
    json.dump(data, open(inp, "w"))
    kpi = os.path.join(tmp, "kpi")
    os.makedirs(kpi)
    json.dump({"ticket_pattern": r"PROJ-\d+"}, open(os.path.join(kpi, "config.json"), "w"))
    out = os.path.join(tmp, "out")
    run = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "pr_metrics.py"), "all",
                          "--input", inp, "--kpi-dir", kpi, "--out-dir", out], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    snap = lambda name: json.load(open(os.path.join(kpi, "delivery", name + ".json")))

    size = snap("pr-size")
    # In the window: 1, 2, 3, 4, 5, 8 (6 is a bot, 7 is lookback). PR 5 has only excluded files.
    assert size["prs"] == 6 and size["bots_dropped"] == 1 and size["net_zero_prs"] == 1, size
    assert size["overall"]["n"] == 5 and size["overall"]["median"] == 120, size["overall"]   # 10,15,120,200,700
    assert size["patterns_matched"] == {"package-lock.json": 1, "yarn.lock": 1}
    assert size["by_author"]["ana"]["n"] == 3 and size["by_area"]["libs/api"]["n"] == 2
    assert size["largest"][0]["number"] == 4 and size["largest"][0]["net"] == 700
    assert size["mismatches"] == []

    wait = snap("review-wait")
    o = wait["overall"]
    assert o["total"] == 6 and o["n"] == 3 and o["never_reviewed"] == 3, o
    assert abs(o["median"] - 6.0) < 1e-6, o["median"]                                 # 2 h, 6 h, 12 h
    assert sorted(wait["never_reviewed"]) == [4, 5, 8]
    assert wait["by_reviewer"]["ben"]["first_reviews"] == 2 and wait["by_reviewer"]["ana"]["first_reviews"] == 1
    assert wait["ready_from_open"] == 5

    rw = snap("rework")
    o = rw["overall"]
    assert o["n"] == 6 and o["reverts"] == 1 and o["followups"] == 2 and abs(o["rate"] - 0.5) < 1e-9, o
    kinds = {p["number"]: (p["kind"], p["anchor"]) for p in rw["rework_prs"]}
    assert kinds == {2: ("follow-up", 1), 4: ("revert", None), 8: ("follow-up", 7)}, kinds
    assert rw["keyless"] == 0 and rw["by_app"]["web"]["n"] == 2
    assert rw["by_author"]["ben"]["rework"] == 2

    for name in ("pr-size", "review-wait", "rework"):
        page = open(os.path.join(out, name + ".html")).read()
        assert page.count("<svg") >= 3 and "ana" in page and "</html>" in page, name
    return kpi, out


def jira_checks(tmp, kpi, out):
    d = os.path.join(tmp, "jira")
    os.makedirs(d)
    json.dump([{"name": "Sprint 1", "startDate": "2026-09-07T08:00:00.000+0000", "endDate": "2026-09-18T16:00:00.000+0000"},
               {"name": "Sprint 2", "startDate": "2026-09-21T08:00:00.000+0000", "endDate": "2026-10-02T16:00:00.000+0000"}],
              open(os.path.join(d, "sprints.json"), "w"))

    def issue(key, typ, who, resolved, moves):
        return {"key": key, "fields": {"issuetype": {"name": typ}, "assignee": {"displayName": who},
                                       "status": {"name": moves[-1][2] if moves else "To Do"},
                                       "created": "2026-09-01T09:00:00.000+0000", "resolutiondate": resolved,
                                       "summary": key},
                "changelog": {"histories": [{"created": at, "items": [{"field": "status", "fromString": a, "toString": b}]}
                                            for at, a, b in moves]}}
    issues = [
        # Mon 09:00 to Wed 09:00: 2 working days.
        issue("T-1", "Story", "Ana", "2026-09-09T09:00:00.000+0000",
              [("2026-09-07T09:00:00.000+0000", "To Do", "In Progress"),
               ("2026-09-09T09:00:00.000+0000", "In Progress", "Done")]),
        # Fri to Tue across a weekend: 2 working days; sent back from acceptance once.
        issue("T-2", "Story", "Ben", "2026-09-15T09:00:00.000+0000",
              [("2026-09-11T09:00:00.000+0000", "To Do", "In Progress"),
               ("2026-09-11T15:00:00.000+0000", "In Progress", "In Acceptance"),
               ("2026-09-14T09:00:00.000+0000", "In Acceptance", "In Progress"),
               ("2026-09-15T09:00:00.000+0000", "In Progress", "Done")]),
        # A backward move from a year before the sprints must not count; a flap undone in 30 s neither.
        issue("T-3", "Bug", "Ana", "2026-09-22T09:00:00.000+0000",
              [("2025-09-01T09:00:00.000+0000", "In Progress", "To Do"),
               ("2026-09-21T09:00:00.000+0000", "To Do", "In Progress"),
               ("2026-09-21T10:00:00.000+0000", "In Progress", "To Do"),
               ("2026-09-21T10:00:30.000+0000", "To Do", "In Progress"),
               ("2026-09-22T09:00:00.000+0000", "In Progress", "Done")]),
        # Blocked for exactly 3 days, then done in sprint 2. Unknown status "Parked" is reported.
        issue("T-4", "Story", "Ben", "2026-09-30T09:00:00.000+0000",
              [("2026-09-22T09:00:00.000+0000", "To Do", "In Progress"),
               ("2026-09-23T09:00:00.000+0000", "In Progress", "Blocked"),
               ("2026-09-26T09:00:00.000+0000", "Blocked", "In Progress"),
               ("2026-09-29T09:00:00.000+0000", "In Progress", "Parked"),
               ("2026-09-30T09:00:00.000+0000", "Parked", "Done")]),
        # Resolved without ever being in progress: no cycle time, lowers coverage.
        issue("T-5", "Bug", "Ana", "2026-09-25T09:00:00.000+0000",
              [("2026-09-25T09:00:00.000+0000", "To Do", "Done")]),
        # Still open: not in any sprint bucket.
        issue("T-6", "Story", "Ben", None, [("2026-09-28T09:00:00.000+0000", "To Do", "In Progress")]),
    ]
    json.dump(issues, open(os.path.join(d, "issues.json"), "w"))
    run = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "jira_cycle.py"), "--project", "T",
                          "--input", d, "--kpi-dir", kpi, "--out-dir", out], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    r = json.load(open(os.path.join(kpi, "delivery", "cycle-time.json")))
    assert r["issues"] == 6 and r["resolved_in_window"] == 5
    s1, s2 = r["by_sprint"]["Sprint 1"], r["by_sprint"]["Sprint 2"]
    assert s1["total"] == 2 and abs(s1["median"] - 2.0) < 1e-6, s1
    assert s1["reverted"] == 1 and s2["reverted"] == 0, (s1["reverted"], s2["reverted"])
    assert s2["total"] == 3 and s2["n"] == 2 and abs(s2["coverage"] - 2 / 3.0) < 1e-9
    assert [b["key"] for b in r["blocked"]] == ["T-4"] and abs(r["blocked"][0]["days"] - 3.0) < 1e-6
    assert r["unknown_statuses"] == ["Parked"] and r["no_cycle"] == ["T-5"]
    assert r["reverted"][0]["key"] == "T-2" and r["reverted"][0]["moves"][0]["from_late_stage"]
    assert set(r["by_assignee"]) == {"Ana", "Ben"}
    page = open(os.path.join(out, "cycle-time.html")).read()
    assert page.count("<svg") >= 4 and "Ben" in page


def dashboard_checks(kpi, out):
    run = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "delivery_report.py"),
                          "--kpi-dir", kpi, "--out-dir", out], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    page = open(os.path.join(out, "delivery.html")).read()
    for needle in ("Pull request size", "Review waiting time", "Rework", "Cycle time", "pr-size.html", "<svg"):
        assert needle in page, needle


def main():
    tmp = tempfile.mkdtemp(prefix="ai-enabler-delivery-test-")
    stats_checks()
    kpi, out = pr_checks(tmp)
    jira_checks(tmp, kpi, out)
    dashboard_checks(kpi, out)
    print("ok — reports in %s" % out)


if __name__ == "__main__":
    main()
