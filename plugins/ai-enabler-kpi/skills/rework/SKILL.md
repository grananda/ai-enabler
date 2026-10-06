---
name: rework
description: Measures rework — reverts plus follow-up pull requests for the same ticket within 14 days, as a share of merged PRs — per week, per app and per developer, and writes an HTML report with charts. Reads GitHub through the GitHub CLI and computes everything with a bundled script. Use when the user says "rework rate", "how many reverts", "follow-up fixes", "how often do we fix what we just merged", "revert rate", or "rework per developer".
argument-hint: "[--repo OWNER/NAME] [--base <branch>] [--weeks 6] [--followup-days 14] [--refresh]"
---

# ai-enabler-kpi:rework — rework and reverts

How often does merged work need to be undone or fixed straight away? The metric is reverts plus follow-up PRs — a later PR for the same ticket key merged within the follow-up window (14 days by default) of the first one — as a share of merged PRs.

The arithmetic is done by a script, not by you: `pr_metrics.py` reads GitHub through the GitHub CLI, computes every figure, and writes a snapshot plus an HTML report with charts.

## Flow

1. **Run it**, passing through any flags from `$ARGUMENTS`:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_metrics.py" rework [flags]
   ```

   With no flags it analyses the repository of the current directory, its default branch, and the window in `.enabler/kpi/config.json` (`delivery.weeks`, default 6). Translate what the person said into flags: "last quarter" → `--weeks 13`, "on develop" → `--base develop`, another repository → `--repo owner/name`. `--refresh` ignores the local cache of GitHub answers.
2. **If it stops with a message**, relay it. A message about `gh` means the GitHub CLI is missing or not signed in: see the rules below.
3. **It prints the path of the HTML report** (`.enabler/kpi/reports/<date>/rework.html`). Read the snapshot `.enabler/kpi/delivery/rework.json` and tell the person:
   - the headline: the rework rate with its 90 % confidence interval, split into reverts and follow-ups, and the rate on mature PRs only;
   - **that the follow-up share is an upper bound**: a second PR for the same ticket is often a planned split or a review-driven polish, not a defect. Say this every time you quote the rate;
   - which tickets account for most follow-ups — they usually cluster in two or three;
   - how many PRs carry no ticket key (they cannot be follow-ups) and that hand-made reverts are not detected;
   - that the most recent weeks are immature and understate the rate;
   - the path of the HTML report, as the thing to open.
4. If the person wants the whole picture, point to `/ai-enabler-kpi:delivery-report`, which runs every delivery metric and builds one dashboard.

## Rules

- The figures come from the script. Do not recompute, round differently or "correct" them; if one looks wrong, say so and point at the snapshot (`.enabler/kpi/delivery/rework.json`) and the cached GitHub answers under `.enabler/kpi/delivery/cache/`.
- **GitHub is read with the GitHub CLI (`gh`)**, which is the recommended and only path: it uses the person's own access, keeps no token in any file, works with GitHub Enterprise, and returns the same data on every run. If the script says `gh` is missing or not signed in, relay its message and recommend installing it (https://cli.github.com) and running `gh auth login` (`gh auth login --hostname <host>` for GitHub Enterprise). Do not fall back to an MCP server, to scraping, or to estimating from local git.
- Read-only: nothing is written to GitHub.
- Per-developer figures are part of the report by default (`delivery.show_people`). When you comment on them, keep to what the report's own notes say: they describe the work as much as the person. Do not rank people or draw conclusions about an individual from one window.
- A bucket flagged `low n` (fewer than 20 PRs) is a direction, not a result. Say so when you quote it.
- The report can contain names and ticket keys. Do not publish or send it anywhere unless asked.
