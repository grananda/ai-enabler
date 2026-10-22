---
name: metrics-review-wait
description: Measures review waiting time — the median hours from a pull request being ready for review to its first human review — per week, per PR size, per author and per reviewer, and writes an HTML report with charts. Reads GitHub through the GitHub CLI and computes everything with a bundled script. Use when the user says "review waiting time", "how long do PRs wait for review", "time to first review", "who reviews the most", "are reviews a bottleneck", or "review turnaround".
argument-hint: "[--repo OWNER/NAME] [--base <branch>] [--weeks 6] [--refresh]"
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.0.0"
---

# ai-enabler-metrics:metrics-review-wait — review waiting time

How long does a pull request wait for a person to look at it? The metric is the median number of hours from "ready for review" to the first human review, with the share reviewed within 4 and within 24 hours, and the PRs merged with no human review at all.

The arithmetic is done by a script, not by you: `pr_metrics.py` reads GitHub through the GitHub CLI, computes every figure, and writes a snapshot plus an HTML report with charts.

## Flow

1. **Run it**, passing through any flags from `$ARGUMENTS`:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_metrics.py" review-wait [flags]
   ```

   With no flags it analyses the repository of the current directory, its default branch, and the window in `.enabler/metrics/config.json` (`delivery.weeks`, default 6). Translate what the person said into flags: "last quarter" → `--weeks 13`, "on develop" → `--base develop`, another repository → `--repo owner/name`. `--refresh` ignores the local cache of GitHub answers.
2. **If it stops with a message**, relay it. A message about `gh` means the GitHub CLI is missing or not signed in: see the rules below.
3. **It prints the path of the HTML report** (`.enabler/metrics/reports/<date>/review-wait.html`). Read the snapshot `.enabler/metrics/delivery/review-wait.json` and tell the person:
   - the headline: median wait with its 90 % confidence interval, the share reviewed within 4 and 24 hours, and coverage;
   - how the wait changes with PR size (S, M, L), which is usually the strongest effect;
   - how first reviews are spread across reviewers — a team where one or two people give most first reviews has a review bottleneck whatever the median says;
   - how many PRs were merged with no human review, and which;
   - how many PRs had no ready-for-review event, because for those the clock starts when the PR was opened;
   - the path of the HTML report, as the thing to open.
4. If the person wants the whole picture, point to `/ai-enabler-metrics:metrics-delivery-report`, which runs every delivery metric and builds one dashboard, with a verdict for each metric the team has set a target for.

## Which folder

Paths in this skill say `.enabler/metrics/`. A project set up before 1.0.0 may still keep its data in `.enabler/kpi/`; the scripts use whichever exists and print the paths they write. In such a project read and write under `.enabler/kpi/` — never create `.enabler/metrics/` beside it, which would split the data.

## Rules

- The figures come from the script. Do not recompute, round differently or "correct" them; if one looks wrong, say so and point at the snapshot (`.enabler/metrics/delivery/review-wait.json`) and the cached GitHub answers under `.enabler/metrics/delivery/cache/`.
- **GitHub is read with the GitHub CLI (`gh`)**, which is the recommended and only path: it uses the person's own access, keeps no token in any file, works with GitHub Enterprise, and returns the same data on every run. If the script says `gh` is missing or not signed in, relay its message and recommend installing it (https://cli.github.com) and running `gh auth login` (`gh auth login --hostname <host>` for GitHub Enterprise). Do not fall back to an MCP server, to scraping, or to estimating from local git.
- Read-only: nothing is written to GitHub.
- Per-developer figures are part of the report by default (`delivery.show_people`). When you comment on them, keep to what the report's own notes say: they describe the work as much as the person. Do not rank people or draw conclusions about an individual from one window.
- A bucket flagged `low n` (fewer than 20 PRs) is a direction, not a result. Say so when you quote it.
- The report can contain names and ticket keys. Do not publish or send it anywhere unless asked.
