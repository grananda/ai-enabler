---
name: delivery-report
description: Builds the delivery-flow dashboard — one HTML page with charts over pull request size, review waiting time, rework and Jira cycle time, including per-developer figures — by running the four delivery metric skills and combining their results. Use when the user says "delivery report", "delivery metrics", "team flow report", "DORA-style report", "how is the team delivering", "all the delivery KPIs", "sprint and PR metrics together", or "numbers per developer".
argument-hint: "[--repo OWNER/NAME] [--base <branch>] [--weeks 6] [--project KEY] [--sprints 3] [--refresh] [--no-jira]"
---

# ai-enabler-kpi:delivery-report — the delivery-flow dashboard

Runs every delivery metric and puts the results on one page. The four metrics are also skills of their own (`pr-size`, `review-wait`, `rework`, `cycle-time`); this one calls them all.

## Flow

1. **Pull-request metrics, in one go.** One command fetches once and computes the three of them:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_metrics.py" all [--repo ...] [--base ...] [--weeks N] [--refresh]
   ```

   If it stops because the GitHub CLI is missing or not signed in, relay the message and recommend `gh` as `${CLAUDE_PLUGIN_ROOT}/skills/pr-size/SKILL.md` describes, then continue with what can be collected.
2. **Cycle time.** Unless `--no-jira` was passed, follow `${CLAUDE_PLUGIN_ROOT}/skills/cycle-time/SKILL.md` from its step 1. If the project has no Jira project configured and none was given, skip it and say so rather than asking in the middle of a report. If Jira can only be read through MCP and a snapshot `.enabler/kpi/delivery/cycle-time.json` less than 7 days old exists, reuse it unless `--refresh` was passed: closed sprints do not change.
3. **AI usage, for context.** If KPI capture is on (`.enabler/kpi/events/` has data), run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/kpi_report.py" --quiet` so its headline figures appear on the dashboard too.
4. **The dashboard:**

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/delivery_report.py"
   ```

   It writes `.enabler/kpi/reports/<date>/delivery.html`, next to the detailed pages (`pr-size.html`, `review-wait.html`, `rework.html`, `cycle-time.html`, and `report.html` for AI usage), and links to them.
5. **Tell the person**, in this order:
   - the path of `delivery.html`, as the page to open;
   - one line per metric with its headline figure and its interval;
   - the two or three things most worth attention, across metrics — for example large PRs waiting longest for review, follow-ups clustering in one ticket, time lost to blocked tickets, first reviews resting on one or two people;
   - what could not be collected, and what is needed to collect it.

## Reading across the metrics

- They describe one system. Large PRs wait longer for review; long waits and late rejections stretch cycle time; rework shows up as follow-up PRs and as tickets bouncing back from acceptance. Look for the same story told twice before calling something a finding.
- Small numbers everywhere. With a team of five and a six-week window, most weekly buckets hold fewer than 20 PRs. Prefer the overall figures and the intervals to week-to-week movement.
- Per-developer figures are there because the team wants them. Present them as the report does — side by side, with the caveats attached — and leave conclusions about individuals to the people who know the context.
- The delivery metrics cover the whole team, with or without AI. Set next to the AI usage figures they give a before-and-after only if the same metrics were captured before; do not infer an effect of AI from one report.

## Rules

- Every figure comes from a script. Compute nothing yourself.
- Read-only towards GitHub and Jira.
- The reports contain names, logins and ticket keys. Do not publish or send them anywhere unless asked.
