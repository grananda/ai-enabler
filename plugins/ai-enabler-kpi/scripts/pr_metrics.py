#!/usr/bin/env python3
"""Pull-request delivery metrics, read with the GitHub CLI.

    pr_metrics.py pr-size      median lines changed per merged PR, generated files excluded
    pr_metrics.py review-wait  hours from "ready for review" to the first human review
    pr_metrics.py rework       reverts and same-ticket follow-up PRs as a share of merged PRs
    pr_metrics.py all          the three of them, sharing one fetch

Options: [--repo OWNER/NAME] [--base BRANCH] [--weeks N] [--followup-days N]
         [--kpi-dir DIR] [--out-dir DIR] [--refresh] [--input FILE]

Each metric writes a snapshot (<kpi-dir>/delivery/<metric>.json) and a
self-contained HTML report with charts. All arithmetic is done here; nothing
is computed by a model. `--input` replaces the GitHub fetch with a JSON file
(used by the tests).
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import charts as C                      # noqa: E402
import delivery_lib as L                # noqa: E402

# A review that was later dismissed (stale approvals are dismissed on every push
# under common branch protection) still happened when it was submitted.
HUMAN_REVIEW_STATES = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED", "DISMISSED"}
REVERT_TITLE = re.compile(r'^\s*(Revert\s+"(?!Revert\s+")|revert(\([^)]*\))?!?:\s)', re.I)


# ------------------------------------------------------------------ helpers

def is_bot_user(user):
    user = user or {}
    login = user.get("login") or ""
    return user.get("type") == "Bot" or login.endswith("[bot]")


def excluded(path, patterns):
    """Whether a file path matches an exclusion glob. `dir/**` matches the
    directory at any depth; a pattern without a slash matches the file name."""
    name = path.rsplit("/", 1)[-1]
    for pat in patterns:
        if pat.endswith("/**"):
            d = pat[:-3]
            if path.startswith(d + "/") or ("/" + d + "/") in ("/" + path):
                return pat
        elif "/" in pat:
            if fnmatch.fnmatch(path, pat):
                return pat
        elif fnmatch.fnmatch(name, pat):
            return pat
    return None


def area_of(path, roots):
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] in roots:
        return "%s/%s" % (parts[0], parts[1])
    return parts[0] if len(parts) > 1 else "(root)"


def fmt(v, unit="", digits=None):
    if v is None:
        return "–"
    return ("%s %s" % (C.fmt_num(v, digits), unit)).strip()


def pct(v):
    return "–" if v is None else "%d %%" % round(v * 100)


def ci_text(s, unit, digits=None):
    if s["ci_lo"] is None:
        return "–"
    return "%s – %s %s" % (C.fmt_num(s["ci_lo"], digits), C.fmt_num(s["ci_hi"], digits), unit)


def flags_text(s):
    return ", ".join(s["flags"]) if s["flags"] else ""


def weeks_between(start, end):
    out, cur = [], start
    while cur <= end:
        w = L.iso_week(cur)
        if w not in out:
            out.append(w)
        cur += timedelta(days=1)
    return out


def bucket_rows(groups, order, value_key, total_key=None):
    """{name: summary} for each bucket, in the given order."""
    out = {}
    for name in order:
        items = groups.get(name, [])
        values = [it[value_key] for it in items if it.get(value_key) is not None]
        out[name] = L.summarize(values, total=len(items) if total_key is None else None)
    return out


def column_points(order, summaries, short=lambda s: s):
    return [{"label": short(name), "value": s["median"], "lo": s["ci_lo"], "hi": s["ci_hi"],
             "low": s["low"], "n": "n=%d" % s["n"]} for name, s in ((n, summaries[n]) for n in order)]


def short_week(w):
    return w.split("-")[1]


# -------------------------------------------------------------------- fetch

def fetch(args, cfg, need):
    """Everything the requested metrics need, as plain data."""
    if args.input:
        with open(args.input, encoding="utf-8") as fh:
            return json.load(fh)
    L.gh_check()
    repo, default_branch, host = L.gh_repo(args.repo or cfg["repo"])
    base = args.base or cfg["base_branch"] or default_branch
    weeks = args.weeks or cfg["weeks"]
    followup = args.followup_days or cfg["followup_days"]
    now = datetime.now(timezone.utc)
    start = (now - timedelta(weeks=weeks)).replace(hour=0, minute=0, second=0, microsecond=0)
    lookback = start - timedelta(days=followup) if "rework" in need else start
    kpi_dir = args.kpi_dir or L.find_kpi_dir()
    snap_dir, _ = L.output_dirs(kpi_dir, args.out_dir)
    gh = L.Gh(repo, host, os.path.join(snap_dir, "cache"), refresh=args.refresh)
    prs = gh.merged_prs(base, lookback)
    in_window = [p for p in prs if not p["bot"] and L.parse_ts(p["merged_at"]) >= start]
    numbers = [p["number"] for p in in_window]
    data = {"repo": repo, "host": host, "base": base, "weeks": weeks, "followup_days": followup,
            "window_start": start.isoformat(), "window_end": now.isoformat(),
            "lookback_start": lookback.isoformat(), "prs": prs, "files": {}, "reviews": {}, "timeline": {}}
    sys.stderr.write("%s: %d merged PRs since %s (%d human-authored in the window)\n"
                     % (repo, len(prs), lookback.date(), len(in_window)))
    if "pr-size" in need:
        data["files"] = {str(k): [{"filename": f.get("filename"), "additions": f.get("additions") or 0,
                                   "deletions": f.get("deletions") or 0, "status": f.get("status")}
                                  for f in v] for k, v in L.parallel(gh.files, numbers).items()}
    if "review-wait" in need:
        data["reviews"] = {str(k): [{"login": (r.get("user") or {}).get("login"),
                                     "bot": is_bot_user(r.get("user")), "state": r.get("state"),
                                     "submitted_at": r.get("submitted_at")} for r in v]
                           for k, v in L.parallel(gh.reviews, numbers).items()}
        data["timeline"] = {str(k): [{"event": t.get("event"), "created_at": t.get("created_at")}
                                     for t in v if t.get("event") in ("ready_for_review", "convert_to_draft")]
                            for k, v in L.parallel(gh.timeline, numbers).items()}
    sys.stderr.write("GitHub: %d API calls, %d answers from the local cache\n" % (gh.calls, gh.hits))
    return data


def scope(data):
    start, end = L.parse_ts(data["window_start"]), L.parse_ts(data["window_end"])
    humans = [p for p in data["prs"] if not p["bot"]]
    window = [p for p in humans if start <= L.parse_ts(p["merged_at"]) <= end]
    bots = [p for p in data["prs"] if p["bot"] and start <= L.parse_ts(p["merged_at"]) <= end]
    for p in window:
        p["week"] = L.iso_week(L.parse_ts(p["merged_at"]))
    return start, end, humans, window, bots


def header(data, bots, window):
    return ["%s · base %s" % (data["repo"], data["base"]),
            "%s to %s (%d weeks)" % (data["window_start"][:10], data["window_end"][:10], data["weeks"]),
            "%d merged PRs by people, %d by bots left out" % (len(window), len(bots)),
            "generated %s UTC" % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")]


def people_table(rows, headers, numeric, show):
    if not show:
        return "<p class='note'>Per-person figures are switched off (delivery.show_people).</p>"
    return C.table(headers, rows, numeric=numeric)


# ------------------------------------------------------------------ pr-size

def pr_size(data, cfg):
    start, end, _humans, window, bots = scope(data)
    patterns = L.DEFAULT_EXCLUDES + list(cfg.get("exclude") or [])
    matched = {}
    for p in window:
        files = data["files"].get(str(p["number"])) or []
        gross = net = 0
        areas = {}
        for f in files:
            lines = (f.get("additions") or 0) + (f.get("deletions") or 0)
            gross += lines
            pat = excluded(f.get("filename") or "", patterns)
            if pat:
                matched[pat] = matched.get(pat, 0) + 1
                continue
            net += lines
            a = area_of(f.get("filename") or "", cfg["area_roots"])
            areas[a] = areas.get(a, 0) + lines
        p["gross"], p["net"] = gross, net
        p["excluded_lines"] = gross - net
        p["area"] = max(areas, key=areas.get) if areas else "(only excluded files)"
        p["truncated"] = len(files) >= 3000
        # The list API and the file list must agree; a mismatch means a truncated or changed PR.
        p["mismatch"] = bool(files) and gross != p["additions"] + p["deletions"]
    sized = [p for p in window if p["net"] > 0]
    net_zero = [p for p in window if p["net"] == 0]
    weeks = weeks_between(start, end)

    def stats(items):
        s = L.summarize([p["net"] for p in items])
        s["over_400"] = L.share([p["net"] for p in items], lambda x: x > 400)
        s["over_1000"] = L.share([p["net"] for p in items], lambda x: x > 1000)
        s["gross_median"] = L.median([p["gross"] for p in items])
        return s

    overall = stats(sized)
    by_week = {w: stats([p for p in sized if p["week"] == w]) for w in weeks}
    by_area = {a: stats(v) for a, v in L.group_by(sized, lambda p: p["area"]).items()}
    by_author = {a: stats(v) for a, v in L.group_by(sized, lambda p: p["author"]).items()}
    largest = sorted(sized, key=lambda p: -p["net"])[:10]
    snapshot = {
        "metric": "pr-size", "unit": "lines", "generated": datetime.now(timezone.utc).isoformat(),
        "repo": data["repo"], "base": data["base"], "window": [data["window_start"], data["window_end"]],
        "overall": overall, "by_week": by_week, "by_area": by_area, "by_author": by_author,
        "prs": len(window), "bots_dropped": len(bots), "net_zero_prs": len(net_zero),
        "patterns_matched": matched, "mismatches": [p["number"] for p in window if p["mismatch"]],
        "truncated": [p["number"] for p in window if p["truncated"]],
        "largest": [{"number": p["number"], "author": p["author"], "net": p["net"], "gross": p["gross"],
                     "area": p["area"], "merged_at": p["merged_at"], "title": p["title"]} for p in largest],
    }

    def row(name, s):
        return [name, "%d PRs" % s["n"], fmt(s["median"], "lines"), fmt(s["mean"], "lines", 0),
                ci_text(s, "lines"), pct(s["over_400"]), pct(s["over_1000"]),
                fmt(s["gross_median"], "lines"), flags_text(s)]

    cols = ["", "PRs", "Median", "Mean", "90 % CI of median", "Over 400 lines", "Over 1,000 lines",
            "Median, nothing excluded", "Flags"]
    num = (1, 2, 3, 4, 5, 6, 7)
    areas = sorted(by_area, key=lambda a: -by_area[a]["n"])
    authors = sorted(by_author, key=lambda a: -(by_author[a]["median"] or 0))
    bottom = [
        "The median merged pull request changes %s (90 %% CI %s), over %d PRs."
        % (fmt(overall["median"], "lines"), ci_text(overall, "lines"), overall["n"]),
        "%s of PRs are over 400 lines and %s over 1,000 lines."
        % (pct(overall["over_400"]), pct(overall["over_1000"])),
    ]
    if "skewed" in overall["flags"]:
        bottom.append("The mean (%s) is far above the median: a few very large PRs pull it up."
                      % fmt(overall["mean"], "lines", 0))
    html_ = C.page(
        "Pull request size", header(data, bots, window),
        C.bullets(bottom),
        C.tiles([("Median PR size", fmt(overall["median"], "lines"), "90 % CI " + ci_text(overall, "lines")),
                 ("PRs over 400 lines", pct(overall["over_400"]), None),
                 ("PRs over 1,000 lines", pct(overall["over_1000"]), None),
                 ("PRs measured", "%d" % overall["n"], "%d only touched excluded files" % len(net_zero)),
                 ("Lines excluded", C.fmt_num(sum(p["excluded_lines"] for p in window)),
                  "lock files and generated code")]),
        C.definitions([
            ("Size", "Lines added plus lines deleted in a merged pull request, after leaving out the "
                     "excluded files. A pure rename counts as 0 lines."),
            ("Excluded files", "Lock files and generated code: " + ", ".join(patterns) + ". "
             + ("Matched in this window: " + ", ".join("%s (%d files)" % kv for kv in sorted(matched.items()))
                if matched else "None of them matched a file in this window.")),
            ("Week", "ISO week of the merge date (UTC)."),
            ("Area", "The directory holding most of the PR's counted lines: two levels under "
                     + ", ".join(cfg["area_roots"]) + ", otherwise the top-level directory."),
            ("Median, mean, CI", "Median: half of the PRs are smaller. Mean: the average, pulled up by "
             "huge PRs. 90 % CI: the range the true median plausibly lies in (5,000 bootstrap resamples); "
             "a wide range means little data."),
            ("Flags", "low n: fewer than %d PRs, read as a direction only. skewed: mean more than twice "
                      "the median." % L.LOW_N),
        ]),
        C.section("Per week",
                  C.grid(C.card("Median PR size per week", C.columns(column_points(weeks, by_week, short_week), "lines"),
                                "lines · whisker = 90 %% CI · faded = fewer than %d PRs" % L.LOW_N),
                         C.card("Large PRs per week", C.stacked(
                             [{"label": short_week(w), "low": by_week[w]["low"],
                               "values": [sum(1 for p in sized if p["week"] == w and p["net"] <= 400),
                                          sum(1 for p in sized if p["week"] == w and 400 < p["net"] <= 1000),
                                          sum(1 for p in sized if p["week"] == w and p["net"] > 1000)]}
                              for w in weeks], ["up to 400 lines", "401 to 1,000 lines", "over 1,000 lines"], "PRs"),
                                "number of PRs by size")),
                  C.table(cols, [row(w, by_week[w]) for w in weeks], num)),
        C.section("Per area",
                  C.card("Median PR size per area", C.hbars(
                      [{"label": a, "value": by_area[a]["median"], "low": by_area[a]["low"],
                        "note": "%d PRs" % by_area[a]["n"]} for a in areas], "lines")),
                  C.table(cols, [row(a, by_area[a]) for a in areas], num)),
        C.section("Per developer",
                  C.card("Median PR size per author", C.hbars(
                      [{"label": a, "value": by_author[a]["median"], "low": by_author[a]["low"],
                        "note": "%d PRs" % by_author[a]["n"]} for a in authors], "lines"))
                  if cfg["show_people"] else "",
                  people_table([row(a, by_author[a]) for a in authors], cols, num, cfg["show_people"]),
                  note="Size reflects the kind of work as much as the habit: a migration or a generated "
                       "test suite is large by nature. Compare like with like."),
        C.section("Largest pull requests", C.table(
            ["PR", "Author", "Merged", "Counted", "Nothing excluded", "Area", "Title"],
            [["#%d" % p["number"], p["author"] if cfg["show_people"] else "–", p["merged_at"][:10],
              fmt(p["net"], "lines"), fmt(p["gross"], "lines"), p["area"], p["title"][:70]] for p in largest],
            numeric=(3, 4))),
        C.section("Data quality", C.bullets([
            "%d PRs by bots were left out." % len(bots),
            "%d PRs touched only excluded files and are not in the size statistics." % len(net_zero),
            ("File totals disagree with the PR totals for: %s."
             % ", ".join("#%d" % n for n in snapshot["mismatches"])) if snapshot["mismatches"]
            else "For every PR, the sum of its files equals the PR's own total of added and deleted lines.",
            ("Truncated at GitHub's 3,000-file limit: %s." % ", ".join("#%d" % n for n in snapshot["truncated"]))
            if snapshot["truncated"] else "No PR reached GitHub's 3,000-file limit.",
        ])),
        footer="Computed by pr_metrics.py from GitHub data read with the GitHub CLI.")
    return snapshot, html_


# -------------------------------------------------------------- review-wait

def review_wait(data, cfg):
    start, end, _humans, window, bots = scope(data)
    small, large = cfg["size_buckets"]
    for p in window:
        n = str(p["number"])
        merged_at = L.parse_ts(p["merged_at"])
        reviews = [r for r in (data["reviews"].get(n) or [])
                   if not r.get("bot") and r.get("login") and r["login"] != p["author"]
                   and (r.get("state") or "").upper() in HUMAN_REVIEW_STATES and r.get("submitted_at")
                   and L.parse_ts(r["submitted_at"]) <= merged_at]    # a comment after the merge is not a review of it
        reviews.sort(key=lambda r: r["submitted_at"])
        first = reviews[0] if reviews else None
        first_at = L.parse_ts(first["submitted_at"]) if first else None
        ready_events = sorted(L.parse_ts(t["created_at"]) for t in (data["timeline"].get(n) or [])
                              if t.get("event") == "ready_for_review" and t.get("created_at"))
        before = [t for t in ready_events if first_at is None or t <= first_at]
        # Reviewed while still a draft: someone looked before it was marked ready. No waiting happened.
        as_draft = bool(first_at and ready_events and not before)
        ready_at = before[-1] if before else (first_at if as_draft else L.parse_ts(p["created_at"]))
        p["ready_source"] = "ready event" if before else ("reviewed as draft" if as_draft else "opened")
        p["size"] = p["additions"] + p["deletions"]
        p["bucket"] = "S" if p["size"] < small else ("M" if p["size"] < large else "L")
        p["reviewer"] = first["login"] if first else None
        p["never_reviewed"] = first is None
        if first_at:
            p["hours"] = max(0.0, (first_at - ready_at).total_seconds() / 3600.0)
            p["work_hours"] = L.working_seconds(ready_at, first_at) / 3600.0
        else:
            p["hours"] = p["work_hours"] = None
        p["ready_at"] = ready_at.isoformat()
    weeks = weeks_between(start, end)

    def stats(items):
        hours = [p["hours"] for p in items if p["hours"] is not None]
        s = L.summarize(hours, total=len(items))
        s["work_median"] = L.median([p["work_hours"] for p in items if p["work_hours"] is not None])
        s["within_4h"] = L.share(hours, lambda h: h <= 4)
        s["within_24h"] = L.share(hours, lambda h: h <= 24)
        s["never_reviewed"] = sum(1 for p in items if p["never_reviewed"])
        return s

    overall = stats(window)
    by_week = {w: stats([p for p in window if p["week"] == w]) for w in weeks}
    labels = {"S": "S (under %d lines)" % small, "M": "M (%d to %d lines)" % (small, large - 1),
              "L": "L (%d lines or more)" % large}
    by_size = {labels[b]: stats([p for p in window if p["bucket"] == b]) for b in "SML"}
    by_author = {a: stats(v) for a, v in L.group_by(window, lambda p: p["author"]).items()}
    reviewers = {}
    for r, items in L.group_by(window, lambda p: p["reviewer"]).items():
        hours = [p["hours"] for p in items]
        reviewers[r] = {"first_reviews": len(items), "median": L.median(hours),
                        "within_4h": L.share(hours, lambda h: h <= 4), "low": len(items) < L.LOW_N}
    slowest = sorted([p for p in window if p["hours"] is not None], key=lambda p: -p["hours"])[:10]
    opened = sum(1 for p in window if p["ready_source"] == "opened")
    snapshot = {
        "metric": "review-wait", "unit": "hours", "generated": datetime.now(timezone.utc).isoformat(),
        "repo": data["repo"], "base": data["base"], "window": [data["window_start"], data["window_end"]],
        "overall": overall, "by_week": by_week, "by_size": by_size, "by_author": by_author,
        "by_reviewer": reviewers, "prs": len(window), "bots_dropped": len(bots),
        "ready_from_open": opened,
        "reviewed_as_draft": [p["number"] for p in window if p["ready_source"] == "reviewed as draft"],
        "never_reviewed": [p["number"] for p in window if p["never_reviewed"]],
        "slowest": [{"number": p["number"], "author": p["author"], "reviewer": p["reviewer"],
                     "hours": p["hours"], "work_hours": p["work_hours"], "size": p["size"],
                     "ready_at": p["ready_at"], "title": p["title"]} for p in slowest],
    }

    def row(name, s):
        return [name, "%d PRs" % s["total"], "%d PRs" % s["n"], pct(s["coverage"]),
                fmt(s["median"], "hours", 1), fmt(s["work_median"], "hours", 1), fmt(s["mean"], "hours", 1),
                ci_text(s, "hours", 1), pct(s["within_4h"]), pct(s["within_24h"]),
                "%d PRs" % s["never_reviewed"], flags_text(s)]

    cols = ["", "Merged", "Measured", "Coverage", "Median", "Median, weekdays only", "Mean",
            "90 % CI of median", "Reviewed within 4 hours", "Within 24 hours", "No human review", "Flags"]
    num = tuple(range(1, 11))
    authors = sorted(by_author, key=lambda a: -(by_author[a]["median"] or 0))
    revs = sorted(reviewers, key=lambda r: -reviewers[r]["first_reviews"])
    bottom = [
        "A pull request waits a median of %s for its first human review (90 %% CI %s), measured on %d of %d PRs."
        % (fmt(overall["median"], "hours", 1), ci_text(overall, "hours", 1), overall["n"], overall["total"]),
        "%s get a first review within 4 hours and %s within 24 hours."
        % (pct(overall["within_4h"]), pct(overall["within_24h"])),
        "%d PRs were merged without any human review." % overall["never_reviewed"],
    ]
    if opened > len(window) * 0.5:
        bottom.append("%d of %d PRs were never drafts, so their clock starts when the PR was opened; "
                      "waits include any time the author spent finishing it." % (opened, len(window)))
    html_ = C.page(
        "Review waiting time", header(data, bots, window),
        C.bullets(bottom),
        C.tiles([("Median wait for first review", fmt(overall["median"], "hours", 1),
                  "90 % CI " + ci_text(overall, "hours", 1)),
                 ("Reviewed within 4 hours", pct(overall["within_4h"]), None),
                 ("Reviewed within 24 hours", pct(overall["within_24h"]), None),
                 ("Merged with no human review", "%d PRs" % overall["never_reviewed"], None),
                 ("Coverage", pct(overall["coverage"]), "%d of %d PRs measured" % (overall["n"], overall["total"]))]),
        C.definitions([
            ("Ready", "The last time the PR was marked ready for review before its first human review. "
                      "A PR that was never a draft is ready when it was opened."),
            ("Human review", "The earliest review submitted before the merge — an approval, a change request "
                             "or a review comment, also one that was dismissed later — by someone other than "
                             "the author and not a bot. A plain conversation comment is not a review."),
            ("Waiting time", "Hours from ready to that first review. 'Weekdays only' counts Monday to "
                             "Friday (UTC, no holiday calendar)."),
            ("No human review", "Merged without one. Counted separately and kept out of the medians."),
            ("Week", "ISO week of the merge date (UTC), the same bucketing as the other PR reports."),
            ("Coverage", "PRs with a measured wait out of all merged PRs in the bucket. Under %d %%: "
                         "a direction only." % round(L.MIN_COVERAGE * 100)),
        ]),
        C.section("Per week",
                  C.grid(C.card("Median wait per week", C.columns(column_points(weeks, by_week, short_week), "hours", digits=1),
                                "hours · whisker = 90 % CI · faded = little data"),
                         C.card("How fast the first review arrives", C.stacked(
                             [{"label": short_week(w), "low": by_week[w]["low"],
                               "values": [sum(1 for p in window if p["week"] == w and p["hours"] is not None and p["hours"] <= 4),
                                          sum(1 for p in window if p["week"] == w and p["hours"] is not None and 4 < p["hours"] <= 24),
                                          sum(1 for p in window if p["week"] == w and p["hours"] is not None and p["hours"] > 24),
                                          sum(1 for p in window if p["week"] == w and p["never_reviewed"])]}
                              for w in weeks],
                             ["within 4 hours", "4 to 24 hours", "over 24 hours", "no human review"], "PRs"),
                                "number of PRs")),
                  C.table(cols, [row(w, by_week[w]) for w in weeks], num)),
        C.section("Per PR size",
                  C.card("Median wait by size", C.columns(
                      [{"label": k.split(" ")[0], "value": s["median"], "lo": s["ci_lo"], "hi": s["ci_hi"],
                        "low": s["low"], "n": "n=%d" % s["n"]} for k, s in by_size.items()], "hours", digits=1),
                      "hours · whisker = 90 % CI"),
                  C.table(cols, [row(k, s) for k, s in by_size.items()], num)),
        C.section("Per developer",
                  C.grid(C.card("Wait for a first review, by PR author", C.hbars(
                             [{"label": a, "value": by_author[a]["median"], "low": by_author[a]["low"],
                               "note": "%d PRs" % by_author[a]["n"]} for a in authors], "hours", digits=1),
                             "median hours their PRs waited"),
                         C.card("First reviews given, by reviewer", C.hbars(
                             [{"label": r, "value": reviewers[r]["first_reviews"], "low": reviewers[r]["low"],
                               "note": "median response %s" % fmt(reviewers[r]["median"], "hours", 1)}
                              for r in revs], "reviews", color_index=1),
                             "how the first reviews are spread across the team"))
                  if cfg["show_people"] else "",
                  people_table([row(a, by_author[a]) for a in authors], cols, num, cfg["show_people"]),
                  people_table([[r, "%d reviews" % reviewers[r]["first_reviews"],
                                 fmt(reviewers[r]["median"], "hours", 1), pct(reviewers[r]["within_4h"])]
                                for r in revs],
                               ["Reviewer", "First reviews given", "Median response", "Within 4 hours"],
                               (1, 2, 3), cfg["show_people"]),
                  note="How long an author's PRs wait depends on who is available to review and on the size "
                       "of the PR, not only on the author. A reviewer who takes most first reviews is "
                       "carrying the load, not causing the wait."),
        C.section("Slowest first reviews", C.table(
            ["PR", "Author", "First reviewer", "Size", "Ready", "Waited", "Weekdays only", "Title"],
            [["#%d" % p["number"], p["author"] if cfg["show_people"] else "–",
              (p["reviewer"] or "–") if cfg["show_people"] else "–", fmt(p["size"], "lines"),
              p["ready_at"][:16].replace("T", " "), fmt(p["hours"], "hours", 1),
              fmt(p["work_hours"], "hours", 1), p["title"][:60]] for p in slowest], numeric=(3, 5, 6))),
        C.section("Data quality", C.bullets([
            "%d PRs by bots were left out; reviews by bots do not stop the clock." % len(bots),
            "%d of %d PRs have no ready-for-review event and use the time they were opened." % (opened, len(window)),
            "%d PRs were first reviewed while still drafts; their wait counts as 0 hours."
            % len(snapshot["reviewed_as_draft"]),
            "Size buckets use all changed lines, generated files included; the PR size report excludes those.",
            ("Merged with no human review: %s." % ", ".join("#%d" % n for n in snapshot["never_reviewed"]))
            if snapshot["never_reviewed"] else "Every merged PR had a human review.",
            "Weekday hours use UTC and no holiday calendar; a wait across a public holiday is overstated.",
        ])),
        footer="Computed by pr_metrics.py from GitHub data read with the GitHub CLI.")
    return snapshot, html_


# ------------------------------------------------------------------- rework

def rework(data, cfg):
    start, end, humans, window, bots = scope(data)
    days = data["followup_days"]
    scope_re = re.compile(r"^\s*\w+\(([^)]+)\)\s*!?:")
    for p in humans:
        p["merged"] = L.parse_ts(p["merged_at"])
        p["key"], p["key_source"] = L.find_ticket(cfg, p["title"], p["head_ref"])
        p["revert"] = bool(REVERT_TITLE.match(p["title"]))
        s_ = scope_re.match(p["title"])
        p["app"] = s_.group(1).strip().lower() if s_ else "(unscoped)"
        p["kind"] = "revert" if p["revert"] else None
        p["anchor"] = p["days_apart"] = None
    # A follow-up is a PR whose ticket already had a PR merged at most `days` earlier.
    # Comparing with the previous PR of the ticket, not with its first one in the data,
    # makes the classification independent of how far back the report looks.
    for key, items in L.group_by([p for p in humans if not p["revert"]], lambda p: p["key"]).items():
        items.sort(key=lambda p: p["merged"])
        for prev, p in zip(items, items[1:]):
            gap = (p["merged"] - prev["merged"]).total_seconds() / 86400.0
            if gap <= days:
                p["kind"], p["anchor"], p["days_apart"] = "follow-up", prev["number"], gap
    weeks = weeks_between(start, end)

    def stats(items):
        n = len(items)
        rev = sum(1 for p in items if p["kind"] == "revert")
        fol = sum(1 for p in items if p["kind"] == "follow-up")
        lo, hi = L.wilson_ci(rev + fol, n)
        return {"n": n, "reverts": rev, "followups": fol, "rework": rev + fol,
                "rate": (rev + fol) / float(n) if n else None, "revert_rate": rev / float(n) if n else None,
                "followup_rate": fol / float(n) if n else None, "ci_lo": lo, "ci_hi": hi,
                "median_days": L.median([p["days_apart"] for p in items if p["days_apart"] is not None]),
                "low": n < L.LOW_N, "flags": ["low n"] if n < L.LOW_N else []}

    overall = stats(window)
    by_week = {w: stats([p for p in window if p["week"] == w]) for w in weeks}
    by_app = {a: stats(v) for a, v in L.group_by(window, lambda p: p["app"]).items()}
    by_author = {a: stats(v) for a, v in L.group_by(window, lambda p: p["author"]).items()}
    listed = [p for p in window if p["kind"]]
    keyless = sum(1 for p in window if not p["key"])
    snapshot = {
        "metric": "rework", "unit": "share of PRs", "generated": datetime.now(timezone.utc).isoformat(),
        "repo": data["repo"], "base": data["base"], "window": [data["window_start"], data["window_end"]],
        "followup_days": days, "overall": overall, "by_week": by_week, "by_app": by_app,
        "default_ticket_pattern": cfg["_ticket_default"],
        "by_author": by_author, "prs": len(window), "bots_dropped": len(bots), "keyless": keyless,
        "rework_prs": [{"number": p["number"], "week": p["week"], "kind": p["kind"], "key": p["key"],
                        "key_source": p["key_source"], "anchor": p["anchor"], "days_apart": p["days_apart"],
                        "author": p["author"], "title": p["title"]} for p in listed],
    }

    def row(name, s, note=""):
        ci = "–" if s["ci_lo"] is None else "%d – %d %%" % (round(s["ci_lo"] * 100), round(s["ci_hi"] * 100))
        return [name, "%d PRs" % s["n"], "%d PRs" % s["reverts"], "%d PRs" % s["followups"],
                pct(s["rate"]), ci, fmt(s["median_days"], "days", 1),
                ", ".join(x for x in (flags_text(s), note) if x)]

    cols = ["", "Merged", "Reverts", "Follow-ups", "Rework rate", "90 % CI", "Median days to follow-up", "Flags"]
    num = (1, 2, 3, 4, 5, 6)
    apps = sorted(by_app, key=lambda a: -by_app[a]["n"])
    authors = sorted(by_author, key=lambda a: -by_author[a]["n"])

    def rate_points(order, table_, short=lambda s: s):
        return [{"label": short(k), "value": (table_[k]["rate"] or 0) * 100 if table_[k]["n"] else None,
                 "lo": (table_[k]["ci_lo"] or 0) * 100 if table_[k]["n"] else None,
                 "hi": (table_[k]["ci_hi"] or 0) * 100 if table_[k]["n"] else None,
                 "low": table_[k]["low"], "n": "n=%d" % table_[k]["n"]} for k in order]

    html_ = C.page(
        "Rework and reverts", header(data, bots, window),
        C.bullets([
            ("%s of merged PRs are rework: %d reverts and %d follow-ups out of %d PRs (90 %% CI %d – %d %%)."
             % (pct(overall["rate"]), overall["reverts"], overall["followups"], overall["n"],
                round((overall["ci_lo"] or 0) * 100), round((overall["ci_hi"] or 0) * 100)))
            if overall["n"] else "No pull requests by people were merged in this window.",
            "Treat the follow-up share as an upper bound: a second PR for the same ticket is often a "
            "planned split, not a defect. The list at the end is there to check.",
        ]),
        C.tiles([("Rework rate", pct(overall["rate"]), "%d of %d PRs" % (overall["rework"], overall["n"])),
                 ("Reverts", "%d PRs" % overall["reverts"], pct(overall["revert_rate"])),
                 ("Follow-ups", "%d PRs" % overall["followups"], pct(overall["followup_rate"])),
                 ("Median days to follow-up", fmt(overall["median_days"], "days", 1), None),
                 ("PRs without a ticket key", "%d PRs" % keyless, "cannot be grouped")]),
        C.definitions([
            ("Revert", 'A merged PR titled Revert "…" (the title GitHub gives a revert) or with the commit '
                       'type revert:. Reverting a revert is a re-land and does not count.'),
            ("Follow-up", "A PR whose ticket already had another PR merged at most %d days earlier. That "
                          "earlier PR is shown as its anchor." % days),
            ("Ticket key", "Matched with the pattern %s in the PR title, then in the branch name. PRs "
                           "without one stay in the total but cannot be follow-ups." % cfg["ticket_pattern"]),
            ("Rework rate", "Reverts plus follow-ups, as a share of the PRs merged in the bucket. A PR that "
                            "is both counts once, as a revert."),
            ("Lookback", "PRs merged in the %d days before the window are read only to find anchors." % days),
            ("App", "The scope in a title like type(app): message; otherwise (unscoped)."),
        ]),
        C.section("Per week",
                  C.grid(C.card("Rework rate per week", C.columns(rate_points(weeks, by_week, short_week), "%"),
                                "% of merged PRs · whisker = 90 % CI · faded = little data"),
                         C.card("Merged PRs by kind", C.stacked(
                             [{"label": short_week(w), "low": by_week[w]["low"],
                               "values": [by_week[w]["n"] - by_week[w]["rework"], by_week[w]["followups"],
                                          by_week[w]["reverts"]]} for w in weeks],
                             ["first delivery", "follow-up", "revert"], "PRs"), "number of PRs")),
                  C.table(cols, [row(w, by_week[w]) for w in weeks], num)),
        C.section("Per app",
                  C.card("Rework rate per app", C.hbars(
                      [{"label": a, "value": (by_app[a]["rate"] or 0) * 100, "low": by_app[a]["low"],
                        "note": "%d of %d PRs" % (by_app[a]["rework"], by_app[a]["n"])} for a in apps], "%")),
                  C.table(cols, [row(a, by_app[a]) for a in apps], num)),
        C.section("Per developer",
                  C.card("Rework PRs by author", C.stacked(
                      [{"label": a, "low": by_author[a]["low"],
                        "values": [by_author[a]["n"] - by_author[a]["rework"], by_author[a]["followups"],
                                   by_author[a]["reverts"]]} for a in authors],
                      ["first delivery", "follow-up", "revert"], "PRs"), "number of merged PRs")
                  if cfg["show_people"] else "",
                  people_table([row(a, by_author[a]) for a in authors], cols, num, cfg["show_people"]),
                  note="A follow-up is attributed to the author of the follow-up PR, who is often the "
                       "person fixing or finishing someone else's ticket. It is not a defect count."),
        C.section("Every rework PR", C.table(
            ["PR", "Week", "Kind", "Ticket", "Key found in", "Anchor PR", "Days apart", "Author", "Title"],
            [["#%d" % p["number"], p["week"], p["kind"], p["key"] or "–", p["key_source"] or "–",
              "#%d" % p["anchor"] if p["anchor"] else "–", fmt(p["days_apart"], "days", 1),
              p["author"] if cfg["show_people"] else "–", p["title"][:60]] for p in listed], numeric=(6,)),
            note="Listed so that false positives can be spotted by eye."),
        C.section("Data quality", C.bullets([
            "%d PRs by bots were left out." % len(bots),
            "%d of %d PRs carry no ticket key." % (keyless, len(window)),
            ("No ticket_pattern is configured, so anything shaped like ABC-123 counts as a key (minus known "
             "look-alikes such as UTF-8) and lower-case branch names are not searched. Set ticket_pattern in "
             ".enabler/kpi/config.json to the project's own keys for a reliable follow-up count.")
            if cfg["_ticket_default"] else "Ticket keys follow the configured pattern.",
            "Reverts done by hand, without the standard revert title, are not detected.",
            "Revert commits pushed straight to the base branch without a PR are not in this report.",
        ])),
        footer="Computed by pr_metrics.py from GitHub data read with the GitHub CLI.")
    return snapshot, html_


# --------------------------------------------------------------------- main

PERSON_BLOCKS = ("by_author", "by_reviewer", "by_assignee")
PERSON_FIELDS = ("author", "reviewer", "assignee")


def without_people(snapshot):
    """The snapshot with no person in it, for projects that switch show_people off:
    the snapshot can end up committed, so hiding names only in the HTML is not enough."""
    out = {k: v for k, v in snapshot.items() if k not in PERSON_BLOCKS}
    for key, value in out.items():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            out[key] = [{f: v for f, v in item.items() if f not in PERSON_FIELDS} for item in value]
    return out


METRICS = {"pr-size": pr_size, "review-wait": review_wait, "rework": rework}


def main():
    ap = argparse.ArgumentParser(description="Pull-request delivery metrics (GitHub CLI).")
    ap.add_argument("metric", choices=list(METRICS) + ["all"])
    ap.add_argument("--repo")
    ap.add_argument("--base")
    ap.add_argument("--weeks", type=int)
    ap.add_argument("--followup-days", type=int)
    ap.add_argument("--kpi-dir")
    ap.add_argument("--out-dir")
    ap.add_argument("--refresh", action="store_true", help="Ignore the local cache of GitHub answers.")
    ap.add_argument("--input", help="Use this JSON file instead of fetching from GitHub.")
    args = ap.parse_args()

    kpi_dir = args.kpi_dir or L.find_kpi_dir()
    try:
        cfg = L.load_config(kpi_dir)
    except L.ConfigError as exc:
        L.die("Configuration problem in .enabler/kpi/config.json: %s" % exc)
    need = list(METRICS) if args.metric == "all" else [args.metric]
    try:
        data = fetch(args, cfg, need)
    except L.GhError as exc:
        L.die(str(exc))
    snap_dir, rep_dir = L.output_dirs(kpi_dir, args.out_dir)
    for name in need:
        snapshot, html_ = METRICS[name](data, cfg)
        if not cfg["show_people"]:
            snapshot = without_people(snapshot)
        L.save_snapshot(snap_dir, name, snapshot)
        path = os.path.join(rep_dir, name + ".html")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html_)
        print(path)


if __name__ == "__main__":
    main()
