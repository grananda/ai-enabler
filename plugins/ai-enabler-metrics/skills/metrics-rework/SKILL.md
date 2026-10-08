---
name: metrics-rework
description: Measures rework — reverts plus follow-up pull requests for the same ticket within 14 days, as a share of merged PRs — per week, per app and per developer, and writes an HTML report with charts. Reads GitHub through the GitHub CLI and computes everything with a bundled script. Use when the user says "rework rate", "how many reverts", "follow-up fixes", "how often do we fix what we just merged", "revert rate", or "rework per developer".
argument-hint: "[--repo OWNER/NAME] [--base <branch>] [--weeks 6] [--followup-days 14] [--refresh]"
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.0.0"
---

# ai-enabler-metrics:metrics-rework — rework and reverts

How often does merged work need to be undone or fixed straight away? The metric is reverts plus follow-up PRs — a PR whose ticket already had another PR merged within the follow-up window (14 days by default) of the first one — as a share of merged PRs.

The arithmetic is done by a script, not by you: `pr_metrics.py` reads GitHub through the GitHub CLI, computes every figure, and writes a snapshot plus an HTML report with charts.

## Flow

1. **Run it**, passing through any flags from `$ARGUMENTS`:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_metrics.py" rework [flags]
   ```

   With no flags it analyses the repository of the current directory, its default branch, and the window in `.enabler/metrics/config.json` (`delivery.weeks`, default 6). Translate what the person said into flags: "last quarter" → `--weeks 13`, "on develop" → `--base develop`, another repository → `--repo owner/name`. `--refresh` ignores the local cache of GitHub answers.
2. **If it stops with a message**, relay it. A message about `gh` means the GitHub CLI is missing or not signed in: see the rules below.
3. **It prints the path of the HTML report** (`.enabler/metrics/reports/<date>/rework.html`). Read the snapshot `.enabler/metrics/delivery/rework.json` and tell the person:
   - the headline: the rework rate with its 90 % confidence interval, split into reverts and follow-ups;
   - **that the follow-up share is an upper bound**: a second PR for the same ticket is often a planned split or a review-driven polish, not a defect. Say this every time you quote the rate;
   - which tickets account for most follow-ups — they usually cluster in two or three;
   - how many PRs carry no ticket key (they cannot be follow-ups) and that hand-made reverts are not detected;
   - whether a ticket pattern is configured (`default_ticket_pattern` in the snapshot). Without one, keys are guessed from anything shaped like ABC-123 and lower-case branch names are not read, so the follow-up count is less reliable: recommend setting `ticket_pattern` in `.enabler/metrics/config.json`;
   - the path of the HTML report, as the thing to open.
4. If the person wants the whole picture, point to `/ai-enabler-metrics:metrics-delivery-report`, which runs every delivery metric and builds one dashboard, with a verdict for each metric the team has set a target for.

## Which folder

Paths in this skill say `.enabler/metrics/`. A project set up before 1.0.0 may still keep its data in `.enabler/kpi/`; the scripts use whichever exists and print the paths they write. In such a project read and write under `.enabler/kpi/` — never create `.enabler/metrics/` beside it, which would split the data.

## Rules

- The figures come from the script. Do not recompute, round differently or "correct" them; if one looks wrong, say so and point at the snapshot (`.enabler/metrics/delivery/rework.json`) and the cached GitHub answers under `.enabler/metrics/delivery/cache/`.
- **GitHub is read with the GitHub CLI (`gh`)**, which is the recommended and only path: it uses the person's own access, keeps no token in any file, works with GitHub Enterprise, and returns the same data on every run. If the script says `gh` is missing or not signed in, relay its message and recommend installing it (https://cli.github.com) and running `gh auth login` (`gh auth login --hostname <host>` for GitHub Enterprise). Do not fall back to an MCP server, to scraping, or to estimating from local git.
- Read-only: nothing is written to GitHub.
- Per-developer figures are part of the report by default (`delivery.show_people`). When you comment on them, keep to what the report's own notes say: they describe the work as much as the person. Do not rank people or draw conclusions about an individual from one window.
- A bucket flagged `low n` (fewer than 20 PRs) is a direction, not a result. Say so when you quote it.
- The report can contain names and ticket keys. Do not publish or send it anywhere unless asked.
