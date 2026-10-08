#!/usr/bin/env python3
"""The delivery-flow dashboard: one page over the four metric snapshots.

    delivery_report.py [--metrics-dir DIR] [--out-dir DIR]

Reads <metrics-dir>/delivery/{pr-size,review-wait,rework,cycle-time}.json — whatever
exists — and writes delivery.html next to the detailed reports. It computes
nothing new: every figure comes from a snapshot written by pr_metrics.py or
jira_cycle.py. If the AI usage report (usage.json) is in the same folder, its
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


REP_DIR = None


def link(name, text):
    """A link to a detail page, only when that page is in the same folder."""
    if REP_DIR and os.path.isfile(os.path.join(REP_DIR, name + ".html")):
        return "<p class='note'><a href='%s.html'>%s</a></p>" % (name, C.e(text))
    return "<p class='note'>%s</p>" % C.e("The detailed page is not in this folder; rerun the metric to get it.")


def origin(snap):
    """Where and when a snapshot comes from, shown with each section."""
    bits = []
    if snap.get("repo"):
        bits.append("%s · base %s" % (snap["repo"], snap.get("base")))
    if snap.get("window"):
        bits.append("%s to %s" % (snap["window"][0][:10], snap["window"][1][:10]))
    if snap.get("generated"):
        bits.append("computed %s" % snap["generated"][:10])
    return " · ".join(bits)


def main():
    ap = argparse.ArgumentParser(description="Delivery-flow dashboard from the metric snapshots.")
    ap.add_argument("--metrics-dir", "--kpi-dir", dest="metrics_dir")
    ap.add_argument("--out-dir")
    args = ap.parse_args()
    metrics_dir = args.metrics_dir or L.find_metrics_dir()
    global REP_DIR
    snap_dir, rep_dir = L.output_dirs(metrics_dir, args.out_dir, create=False)
    size, wait, rework, cycle = (L.load_snapshot(snap_dir, n) for n in ("pr-size", "review-wait", "rework", "cycle-time"))
    if not any((size, wait, rework, cycle)):
        L.die("No delivery snapshots in %s. Run the metric skills first." % snap_dir)
    os.makedirs(rep_dir, exist_ok=True)
    REP_DIR = rep_dir
    scopes = {(s_["repo"], s_["base"], s_["window"][0][:10], s_["window"][1][:10])
              for s_ in (size, wait, rework) if s_}

    try:
        cfg = L.load_config(metrics_dir)
    except L.ConfigError as exc:
        L.die("Configuration problem in the metrics config: %s" % exc)
    verdicts = L.evaluate_targets(cfg, {"pr-size": size, "review-wait": wait, "rework": rework, "cycle-time": cycle})
    L.save_snapshot(snap_dir, "kpis", {"generated": datetime.now(timezone.utc).isoformat(), "kpis": verdicts,
                                       "rejected_targets": cfg["_rejected_targets"]})
    marks = {"met": "✓ met", "not met": "✗ not met", "inconclusive": "~ inconclusive", "no data": "– no data"}

    def interval(v):
        return "–" if v["lo"] is None else "%s – %s" % (C.fmt_num(v["lo"], 1), C.fmt_num(v["hi"], 1))

    if verdicts:
        kpis = C.section(
            "KPIs",
            C.table(["Metric", "Target", "Measured", "90 % interval", "Observations", "Status", "Why"],
                    [[v["label"], "%s %s %s" % ("at most" if v["bound"] == "max" else "at least",
                                                 C.fmt_num(v["target"], 1), v["unit"]),
                      "–" if v["value"] is None else "%s %s" % (C.fmt_num(v["value"], 1), v["unit"]),
                      interval(v), "%d" % v["n"], marks[v["status"]], v["why"]] for v in verdicts],
                    numeric=(4,)),
            note="A KPI is a delivery metric the team has set a target for. The verdict is 'met' or 'not met' "
                 "only when the whole 90 % interval falls on one side of the target; otherwise it is "
                 "inconclusive, which with a small team and a short window is the usual, honest answer.")
    else:
        kpis = C.section("KPIs", note="None. These are metrics: no target has been set for any of them. A "
                                      "delivery metric becomes a KPI when the team gives it a target under "
                                      "delivery.targets in the metrics configuration.")
    if cfg["_rejected_targets"]:
        kpis += ("<p class='note'>Ignored targets: %s. They are not among the four delivery metrics that can "
                 "carry a target (pr_size_median_lines, review_wait_median_hours, rework_rate_percent, "
                 "cycle_time_median_days). Check the spelling; and note that usage figures — cost, tokens, "
                 "lines written by AI — are context and never take a target.</p>"
                 % C.e(", ".join(cfg["_rejected_targets"])))
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
            note="Last %d closed sprints, %s to %s · computed %s."
                 % (len(names), cycle["sprints"][0]["start"][:10], cycle["sprints"][-1]["end"][:10],
                    (cycle.get("generated") or "")[:10])))
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
            note="%s over 400 lines, %s over 1,000 lines, across %d PRs. %s."
                 % (pct(o["over_400"]), pct(o["over_1000"]), o["n"], origin(size))))
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
            note="%s reviewed within 4 hours; %d PRs merged with no human review. %s."
                 % (pct(o["within_4h"]), o["never_reviewed"], origin(wait))))
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
            note="Upper bound: a second PR for the same ticket is often a planned split. %s." % origin(rework)))
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
        with open(os.path.join(rep_dir, "usage.json"), encoding="utf-8") as fh:
            usage = json.load(fh)
        k = usage["overall"]
        ai = C.section("AI usage", C.tiles([
            ("AI cost", "$%.2f" % k["cost_usd"], "published prices"),
            ("Cost per ticket", "–" if k.get("cost_usd_per_ticket") is None else "$%.2f" % k["cost_usd_per_ticket"], None),
            ("AI working time", "%.1f hours" % (k["ai_seconds"] / 3600.0), None),
            ("Human interactions", "%d" % k["human_interactions"], None),
            ("Lines written by AI", "{:,}".format(k["lines_added"]), None)]),
            link("report", "Full AI usage report →"),
            note="Captured by the hooks of this plugin for %s — its own period, which need not match the "
                 "windows above. The delivery metrics come from GitHub and Jira and cover the whole team, "
                 "with or without AI." % usage.get("period", "the sessions recorded"))
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
    mixed = ("<p class='note'><b>The pull-request sections do not describe the same scope</b> — they were "
             "computed for different repositories, branches or windows (see the line under each). Rerun "
             "them together for a consistent page.</p>") if len(scopes) > 1 else ""
    page = C.page("Delivery flow", meta, C.tiles(tiles), mixed, kpis,
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
