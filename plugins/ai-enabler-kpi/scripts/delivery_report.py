#!/usr/bin/env python3
"""The delivery-flow dashboard: one page over the four metric snapshots.

    delivery_report.py [--kpi-dir DIR] [--out-dir DIR]

Reads <kpi-dir>/delivery/{pr-size,review-wait,rework,cycle-time}.json — whatever
exists — and writes delivery.html next to the detailed reports. It computes
nothing new: every figure comes from a snapshot written by pr_metrics.py or
jira_cycle.py. If the AI usage report (kpi.json) is in the same folder, its
headline figures are shown alongside.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import charts as C                      # noqa: E402
import delivery_lib as L                # noqa: E402


def fmt(v, unit, digits=None):
    return "–" if v is None else ("%s %s" % (C.fmt_num(v, digits), unit)).strip()


def pct(v):
    return "–" if v is None else "%d %%" % round(v * 100)


def week_points(by_week, key="median", scale=1.0, lo="ci_lo", hi="ci_hi"):
    pts = []
    for w in sorted(by_week):
        s = by_week[w]
        v = s.get(key)
        pts.append({"label": w.split("-")[1], "value": None if v is None or not s["n"] else v * scale,
                    "lo": None if s.get(lo) is None or not s["n"] else s[lo] * scale,
                    "hi": None if s.get(hi) is None or not s["n"] else s[hi] * scale,
                    "low": s.get("low"), "n": "n=%d" % s["n"]})
    return pts


def link(name, text):
    return "<p class='note'><a href='%s.html'>%s</a></p>" % (name, C.e(text))


def main():
    ap = argparse.ArgumentParser(description="Delivery-flow dashboard from the metric snapshots.")
    ap.add_argument("--kpi-dir")
    ap.add_argument("--out-dir")
    args = ap.parse_args()
    kpi_dir = args.kpi_dir or L.find_kpi_dir()
    cfg = L.load_config(kpi_dir)
    snap_dir, rep_dir = L.output_dirs(kpi_dir, args.out_dir)
    size, wait, rework, cycle = (L.load_snapshot(snap_dir, n) for n in ("pr-size", "review-wait", "rework", "cycle-time"))
    if not any((size, wait, rework, cycle)):
        L.die("No delivery snapshots in %s. Run the metric skills first." % snap_dir)

    tiles, parts, missing = [], [], []
    if cycle:
        o = cycle["overall"]
        tiles += [("Cycle time", fmt(o["median"], "days", 1), "median working days, in progress to done"),
                  ("Tickets moved backward", pct(o["revert_rate"]), "%d of %d resolved" % (o["reverted"], o["total"]))]
        names = [s["name"] for s in cycle["sprints"]]
        parts.append(C.section(
            "Cycle time — %s" % (cycle.get("project") or "Jira"),
            C.grid(C.card("Median cycle time per sprint", C.columns(
                [{"label": n, "value": cycle["by_sprint"][n]["median"], "lo": cycle["by_sprint"][n]["ci_lo"],
                  "hi": cycle["by_sprint"][n]["ci_hi"], "low": cycle["by_sprint"][n]["low"],
                  "n": "n=%d" % cycle["by_sprint"][n]["n"]} for n in names], "days", digits=1),
                "working days · whisker = 90 % CI"),
                   C.card("Blocked time per ticket", C.hbars(
                       [{"label": b["key"], "value": b["days"],
                         "note": "blocked now" if b["still_blocked"] else b["type"]} for b in cycle["blocked"][:8]],
                       "days", color_index=7, digits=1), "calendar days, longest first")),
            link("cycle-time", "Full cycle-time report: per issue type, per developer, every backward move →"),
            note="Last %d closed sprints, %s to %s." % (len(names), cycle["sprints"][0]["start"][:10],
                                                         cycle["sprints"][-1]["end"][:10])))
    else:
        missing.append("cycle time (Jira)")
    if size:
        o = size["overall"]
        tiles.append(("PR size", fmt(o["median"], "lines"), "median, generated files excluded"))
        parts.append(C.section(
            "Pull request size",
            C.grid(C.card("Median PR size per week", C.columns(week_points(size["by_week"]), "lines"),
                          "lines · whisker = 90 % CI · faded = little data"),
                   C.card("Median PR size per area", C.hbars(
                       [{"label": a, "value": s["median"], "low": s["low"], "note": "%d PRs" % s["n"]}
                        for a, s in sorted(size["by_area"].items(), key=lambda kv: -kv[1]["n"])[:8]], "lines"))),
            link("pr-size", "Full PR size report: per developer, largest PRs, exclusions →"),
            note="%s over 400 lines, %s over 1,000 lines, across %d PRs."
                 % (pct(o["over_400"]), pct(o["over_1000"]), o["n"])))
    else:
        missing.append("pull request size")
    if wait:
        o = wait["overall"]
        tiles.append(("Wait for first review", fmt(o["median"], "hours", 1), "%s within 24 hours" % pct(o["within_24h"])))
        parts.append(C.section(
            "Review waiting time",
            C.grid(C.card("Median wait per week", C.columns(week_points(wait["by_week"]), "hours", digits=1),
                          "hours · whisker = 90 % CI · faded = little data"),
                   C.card("Median wait by PR size", C.columns(
                       [{"label": k.split(" ")[0], "value": s["median"], "lo": s["ci_lo"], "hi": s["ci_hi"],
                         "low": s["low"], "n": "n=%d" % s["n"]} for k, s in wait["by_size"].items()],
                       "hours", digits=1), "hours · S, M, L by lines changed")),
            link("review-wait", "Full review report: per developer, per reviewer, slowest PRs →"),
            note="%s reviewed within 4 hours; %d PRs merged with no human review."
                 % (pct(o["within_4h"]), o["never_reviewed"])))
    else:
        missing.append("review waiting time")
    if rework:
        o = rework["overall"]
        tiles.append(("Rework rate", pct(o["rate"]), "%d reverts, %d follow-ups" % (o["reverts"], o["followups"])))
        weeks = sorted(rework["by_week"])
        parts.append(C.section(
            "Rework and reverts",
            C.grid(C.card("Rework rate per week", C.columns(week_points(rework["by_week"], "rate", 100.0), "%"),
                          "% of merged PRs · whisker = 90 % CI"),
                   C.card("Merged PRs by kind", C.stacked(
                       [{"label": w.split("-")[1], "values": [
                           rework["by_week"][w]["n"] - rework["by_week"][w]["rework"],
                           rework["by_week"][w]["followups"], rework["by_week"][w]["reverts"]]} for w in weeks],
                       ["first delivery", "follow-up", "revert"], "PRs"))),
            link("rework", "Full rework report: per app, per developer, every rework PR →"),
            note="Upper bound: a second PR for the same ticket is often a planned split. On mature PRs only: %s."
                 % pct(rework["mature"]["rate"])))
    else:
        missing.append("rework")

    # One row per developer across the three pull-request metrics (same GitHub logins).
    people = ""
    if cfg["show_people"] and any((size, wait, rework)):
        logins = set()
        for snap, key in ((size, "by_author"), (wait, "by_author"), (wait, "by_reviewer"), (rework, "by_author")):
            if snap:
                logins |= {k for k in snap.get(key, {}) if k}
        rows = []
        for who in sorted(logins, key=lambda w: -((rework or {}).get("by_author", {}).get(w, {}).get("n")
                                                   or (size or {}).get("by_author", {}).get(w, {}).get("n") or 0)):
            s = (size or {}).get("by_author", {}).get(who)
            a = (wait or {}).get("by_author", {}).get(who)
            v = (wait or {}).get("by_reviewer", {}).get(who)
            r = (rework or {}).get("by_author", {}).get(who)
            merged = (r or {}).get("n") or (a or {}).get("total") or (s or {}).get("n") or 0
            rows.append([who, "%d PRs" % merged, fmt(s["median"], "lines") if s else "–",
                         fmt(a["median"], "hours", 1) if a else "–",
                         "%d reviews" % v["first_reviews"] if v else "0 reviews",
                         fmt(v["median"], "hours", 1) if v else "–",
                         "%d PRs" % r["rework"] if r else "–", pct(r["rate"]) if r else "–"])
        merged_rows = [{"label": r_[0], "value": float(r_[1].split()[0])} for r_ in rows]
        people = C.section(
            "Per developer",
            C.grid(C.card("Merged PRs per author", C.hbars(merged_rows, "PRs")),
                   C.card("First reviews given", C.hbars(
                       sorted([{"label": r_[0], "value": float(r_[4].split()[0])} for r_ in rows],
                              key=lambda x: -x["value"]), "reviews", color_index=1))),
            C.table(["Developer", "Merged PRs", "Median PR size", "Their PRs wait for review",
                     "First reviews given", "Their response time", "Rework PRs", "Rework rate"],
                    rows, numeric=(1, 2, 3, 4, 5, 6, 7)),
            note="GitHub logins. These numbers describe the work as much as the person: someone on a migration "
                 "has large PRs, someone finishing a colleague's ticket has follow-ups, and whoever reviews "
                 "most is carrying the team's review load. Read them together, and with the people concerned.")
        if cycle:
            by = cycle["by_assignee"]
            order = sorted(by, key=lambda k: -(by[k]["n"]))
            people += (C.card("Cycle time per assignee (Jira names)", C.hbars(
                [{"label": k, "value": by[k]["median"], "low": by[k]["low"], "note": "%d tickets" % by[k]["n"]}
                 for k in order], "days", digits=1)))

    ai = ""
    try:
        with open(os.path.join(rep_dir, "kpi.json"), encoding="utf-8") as fh:
            k = json.load(fh)["overall"]
        ai = C.section("AI usage in the same period", C.tiles([
            ("AI cost", "$%.2f" % k["cost_usd"], "published prices"),
            ("Cost per ticket", "–" if k.get("cost_usd_per_ticket") is None else "$%.2f" % k["cost_usd_per_ticket"], None),
            ("AI working time", "%.1f hours" % (k["ai_seconds"] / 3600.0), None),
            ("Human interactions", "%d" % k["human_interactions"], None),
            ("Lines written by AI", "{:,}".format(k["lines_added"]), None)]),
            link("report", "Full AI usage report →"),
            note="From the hooks of this plugin. Shown here for context; the delivery metrics above come from "
                 "GitHub and Jira and cover the whole team, with or without AI.")
    except (OSError, ValueError, KeyError):
        pass

    first = size or wait or rework
    meta = []
    if first:
        meta.append("%s · base %s · %s to %s" % (first["repo"], first["base"], first["window"][0][:10],
                                                 first["window"][1][:10]))
    if cycle:
        meta.append("Jira %s" % (cycle.get("project") or ""))
    meta.append("generated %s UTC" % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"))
    page = C.page("Delivery flow", meta, C.tiles(tiles),
                  ("<p class='note'>Not in this report, because it has not been collected yet: %s.</p>"
                   % C.e(", ".join(missing))) if missing else "",
                  *parts, people, ai,
                  footer="Figures come from the snapshots in %s; nothing is recomputed here." % snap_dir)
    path = os.path.join(rep_dir, "delivery.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(path)


if __name__ == "__main__":
    main()
