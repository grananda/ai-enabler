---
name: pr-size
description: Measures pull request size — the median lines changed per merged PR, with lock files and generated code left out — per week, per area of the repository and per developer, and writes an HTML report with charts. Reads GitHub through the GitHub CLI and computes everything with a bundled script. Use when the user says "PR size report", "how big are our pull requests", "are our PRs too large", "pull request size per developer", or "lines changed per PR".
argument-hint: "[--repo OWNER/NAME] [--base <branch>] [--weeks 6] [--refresh]"
---

# ai-enabler-kpi:pr-size — pull request size

How large are the pull requests this team merges? The metric is the median number of lines changed (added plus deleted) per merged PR, after leaving out lock files and generated code, with the share of PRs over 400 and over 1,000 lines.

The arithmetic is done by a script, not by you: `pr_metrics.py` reads GitHub through the GitHub CLI, computes every figure, and writes a snapshot plus an HTML report with charts.

## Flow

1. **Run it**, passing through any flags from `$ARGUMENTS`:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_metrics.py" pr-size [flags]
   ```

   With no flags it analyses the repository of the current directory, its default branch, and the window in `.enabler/kpi/config.json` (`delivery.weeks`, default 6). Translate what the person said into flags: "last quarter" → `--weeks 13`, "on develop" → `--base develop`, another repository → `--repo owner/name`. `--refresh` ignores the local cache of GitHub answers.
2. **If it stops with a message**, relay it. A message about `gh` means the GitHub CLI is missing or not signed in: see the rules below.
3. **It prints the path of the HTML report** (`.enabler/kpi/reports/<date>/pr-size.html`). Read the snapshot `.enabler/kpi/delivery/pr-size.json` and tell the person:
   - the headline: median size with its 90 % confidence interval, and the share of PRs over 400 and over 1,000 lines;
   - whether the mean is far above the median (a few very large PRs), and which PRs those are;
   - what stands out per area and per developer, with the caveat that size follows the kind of work;
   - which exclusion patterns actually matched files, and anything under "Data quality";
   - the path of the HTML report, as the thing to open.
4. If the person wants the whole picture, point to `/ai-enabler-kpi:delivery-report`, which runs every delivery metric and builds one dashboard.

## Rules

- The figures come from the script. Do not recompute, round differently or "correct" them; if one looks wrong, say so and point at the snapshot (`.enabler/kpi/delivery/pr-size.json`) and the cached GitHub answers under `.enabler/kpi/delivery/cache/`.
- **GitHub is read with the GitHub CLI (`gh`)**, which is the recommended and only path: it uses the person's own access, keeps no token in any file, works with GitHub Enterprise, and returns the same data on every run. If the script says `gh` is missing or not signed in, relay its message and recommend installing it (https://cli.github.com) and running `gh auth login` (`gh auth login --hostname <host>` for GitHub Enterprise). Do not fall back to an MCP server, to scraping, or to estimating from local git.
- Read-only: nothing is written to GitHub.
- Per-developer figures are part of the report by default (`delivery.show_people`). When you comment on them, keep to what the report's own notes say: they describe the work as much as the person. Do not rank people or draw conclusions about an individual from one window.
- A bucket flagged `low n` (fewer than 20 PRs) is a direction, not a result. Say so when you quote it.
- The report can contain names and ticket keys. Do not publish or send it anywhere unless asked.
