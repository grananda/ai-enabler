---
name: metrics-delivery-report
description: Builds the delivery-flow dashboard — one HTML page with charts over pull request size, review waiting time, rework and Jira cycle time, including per-developer figures — by running the four delivery metric skills and combining their results. Use when the user says "delivery report", "delivery metrics", "team flow report", "DORA-style report", "how is the team delivering", "all the delivery metrics", "sprint and PR metrics together", or "numbers per developer".
argument-hint: "[--repo OWNER/NAME] [--base <branch>] [--weeks 6] [--project KEY] [--sprints 3] [--refresh] [--no-jira]"
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.0.0"
---

# ai-enabler-metrics:metrics-delivery-report — the delivery-flow dashboard

Runs every delivery metric and puts the results on one page. The four metrics are also skills of their own (`metrics-pr-size`, `metrics-review-wait`, `metrics-rework`, `metrics-cycle-time`); this one calls them all.

## Flow

1. **Pull-request metrics, in one go.** One command fetches once and computes the three of them:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/pr_metrics.py" all [--repo ...] [--base ...] [--weeks N] [--refresh]
   ```

   Only those flags go to this script. `--project`, `--sprints` and `--no-jira` belong to the cycle-time step, and `--refresh` applies to both.

   If it stops because the GitHub CLI is missing or not signed in, relay the message and recommend `gh` as `${CLAUDE_PLUGIN_ROOT}/skills/metrics-pr-size/SKILL.md` describes, then continue with what can be collected.
2. **Cycle time.** Unless `--no-jira` was passed, follow `${CLAUDE_PLUGIN_ROOT}/skills/metrics-cycle-time/SKILL.md` from its step 1. If the project has no Jira project configured and none was given, skip it and say so rather than asking in the middle of a report. If Jira can only be read through MCP and a snapshot `.enabler/metrics/delivery/cycle-time.json` less than 7 days old exists, reuse it unless `--refresh` was passed: closed sprints do not change.
3. **AI usage, for context.** If today's report folder already holds `usage.json` — because `/ai-enabler-metrics:metrics-usage-report` just wrote it, possibly with filters — leave it as it is. Otherwise, if usage capture is on (`.enabler/metrics/events/` has data), run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/usage_report.py" --quiet` so its headline figures appear on the dashboard too.
4. **The dashboard:**

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/delivery_report.py"
   ```

   It writes `.enabler/metrics/reports/<date>/delivery.html` (or `.enabler/delivery/reports/<date>/` in a project where usage capture was never switched on — running a report does not switch it on), next to the detailed pages (`pr-size.html`, `review-wait.html`, `rework.html`, `cycle-time.html`, and `report.html` for AI usage), and links to them.
5. **Tell the person**, in this order:
   - the path of `delivery.html`, as the page to open;
   - the KPIs, if the team has set targets (`.enabler/metrics/delivery/kpis.json`): each one with its target, the measured value, the interval and the verdict — met, not met, or inconclusive. If there are no targets, say that these are metrics and not KPIs yet, and leave it there;
   - one line per metric with its headline figure and its interval;
   - the two or three things most worth attention, across metrics — for example large PRs waiting longest for review, follow-ups clustering in one ticket, time lost to blocked tickets, first reviews resting on one or two people;
   - what could not be collected, and what is needed to collect it.

## Metrics and KPIs

A delivery metric becomes a KPI only when the team sets a target for it (`delivery.targets` in `.enabler/metrics/config.json`). The dashboard then gives a verdict, and it is deliberately cautious: **met** or **not met** only when the whole 90 % interval is on one side of the target, **inconclusive** otherwise.

- Report the verdict as the script gives it. An inconclusive KPI is not "almost met" or "at risk"; it means there is not enough data to tell, which is normal for a small team and a few weeks.
- Do not set or change targets yourself. If the person wants one, write it to the configuration as they state it, and suggest taking a baseline first: a target chosen before the first measurement is a guess.
- Only the four delivery metrics take targets. If the dashboard lists ignored targets, explain that usage figures are context and never targets.

## Reading across the metrics

- They describe one system. Large PRs wait longer for review; long waits and late rejections stretch cycle time; rework shows up as follow-up PRs and as tickets bouncing back from acceptance. Look for the same story told twice before calling something a finding.
- Small numbers everywhere. With a team of five and a six-week window, most weekly buckets hold fewer than 20 PRs. Prefer the overall figures and the intervals to week-to-week movement.
- Per-developer figures are there because the team wants them. Present them as the report does — side by side, with the caveats attached — and leave conclusions about individuals to the people who know the context.
- The delivery metrics cover the whole team, with or without AI. Set next to the AI usage figures they give a before-and-after only if the same metrics were captured before; do not infer an effect of AI from one report.

## Which folder

Paths in this skill say `.enabler/metrics/`. A project set up before 1.0.0 may still keep its data in `.enabler/kpi/`; the scripts use whichever exists and print the paths they write. In such a project read and write under `.enabler/kpi/` — never create `.enabler/metrics/` beside it, which would split the data.

## Rules

- Every figure comes from a script. Compute nothing yourself.
- Read-only towards GitHub and Jira.
- If the dashboard warns that its sections do not describe the same scope, say so and offer to rerun the pull-request metrics together; do not present mixed scopes as one picture.
- The reports contain names, logins and ticket keys. Do not publish or send them anywhere unless asked.
