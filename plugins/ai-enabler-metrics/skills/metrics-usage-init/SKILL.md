---
name: metrics-usage-init
description: Switches on AI usage capture for the current project by creating the `.enabler/metrics/` directory the ai-enabler-metrics hooks look for, with its configuration and git-ignore rules, and explains what will and will not be recorded. Also reports whether capture is already active, moves a project from the old `.enabler/kpi/` folder, sets targets for the delivery metrics, or switches capture off. Use when the user says "enable usage capture", "start measuring AI usage", "turn on metrics for this repo", "set up ai-enabler-metrics", "is capture on", "set a target for review time", or "stop collecting metrics".
argument-hint: [--status | --off] [--share] [--anonymize] [--ticket-pattern <regex>]
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.0.0"
---

# ai-enabler-metrics:metrics-usage-init — switch capture on for this project

The plugin's hooks are installed for every session but stay silent until a project opts in. A project opts in by having a `.enabler/metrics/` directory at its root. This skill creates it.

## Flow

0. **A project from before 1.0.0.** If `.enabler/kpi/` exists, capture is already on: the hooks read that folder, and `ENABLER_KPI_DIR` / `ENABLER_KPI_USER` are still honoured (their new names are `ENABLER_METRICS_DIR` and `ENABLER_METRICS_USER`). Offer to rename it — `mv .enabler/kpi .enabler/metrics` moves every event, snapshot and report with it — and do it only when the person says yes. If they decline, treat `.enabler/kpi/` as the metrics folder in every step below and **do not create `.enabler/metrics/`**: two folders would split the data. If both already exist, say so, and offer to move what is left in `.enabler/kpi/` (its `events/`, `delivery/` and `reports/`) into `.enabler/metrics/` and remove the old folder. When event files are shared through git, the rename has to be made by everyone: each person's ignored files stay in their own old folder until they move them.
1. **Find the project root** (`git rev-parse --show-toplevel`, else the current directory) and check whether `.enabler/metrics/` (or the older `.enabler/kpi/`) exists.
2. **`--status`**, or capture already on: report whether it is active, how many session files exist under `.enabler/metrics/events/`, the date of the first and the last one, and the current `config.json`. Stop here for `--status`.
3. **`--off`**: explain that capture stops when the directory is gone, and that removing it also removes the collected data. Do not delete it yourself; give the human the two options — delete the directory, or keep the data and rename it (for example to `.enabler/metrics-archived/`) — and let them do it.
4. **Switch on.** Create `.enabler/metrics/` with:
   - `config.json`:

     ```json
     {
       "idle_cap_seconds": 600,
       "anonymize_users": false,
       "record_paths": true,
       "ticket_pattern": null
     }
     ```

     Set `anonymize_users` to true with `--anonymize` (users become a stable hash instead of their git e-mail). Set `ticket_pattern` with `--ticket-pattern`, for example `"(PROJ|OPS)-\\d+"`; when the project's Jira keys can be seen (in branch names or recent commit messages), propose a pattern, because the default matches anything shaped like `ABC-123`.
     When the session runs on Amazon Bedrock (`CLAUDE_CODE_USE_BEDROCK` is set), cost is priced with Bedrock's table for `AWS_REGION` automatically. Add pricing keys only for what cannot be detected, and ask the human rather than guessing: `"bedrock_scope": "global"` or `"regional"` when the project's inference profiles are known, `"provider": "bedrock"` when sessions go through an LLM gateway, `"cost_multiplier"` for a negotiated discount, `"model_aliases"` for application inference profile ARNs. If the region is not in the bundled table, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/update_pricing.py" --region <region> --file .enabler/metrics/pricing.json`.
     For the delivery-flow metrics, add a `delivery` block only with what is known — the Jira project key and, when the team's workflow differs from the defaults, its statuses:

     ```json
     "delivery": {
       "weeks": 6,
       "base_branch": null,
       "show_people": true,
       "targets": { "review_wait_median_hours": { "max": 8 } },
       "jira": { "project": "PROJ", "sprints": 3,
                 "statuses": { "order": [["To Do", "Ready"], "In Progress", "In Test", "In Acceptance", "Done"],
                               "in_progress": ["In Progress"], "blocked": ["Blocked"] } }
     }
     ```

     **Targets make KPIs.** Without `targets` the delivery figures are metrics. A target turns one into a KPI, and the dashboard then says whether it is met. Only the four delivery metrics can carry one: `pr_size_median_lines`, `review_wait_median_hours`, `rework_rate_percent`, `cycle_time_median_days`, each as `{"max": n}` (or `{"min": n}`). Do not invent targets: add one only when the team names it, and prefer a first report without any, so the target is set against a measured baseline. Never add a target on a usage figure — cost, tokens, lines written by AI, number of prompts or skills: those are context, and the script ignores them.

     Check that the GitHub CLI is installed and signed in (`gh auth status`); if not, recommend it — the pull-request metrics need it.
   - `.gitignore` inside `.enabler/metrics/`:
     - always: `.state/`, `reports/`, `delivery/cache/` and `delivery/jira-input/`;
     - by default also `events/` and `delivery/`, so each developer's usage data and the delivery snapshots (which name people) stay on their machine;
     - with `--share`, leave `events/` and `delivery/*.json` out of it (keep `delivery/cache/` and `delivery/jira-input/` ignored), so event files are committed and the team's data can be reported together. There is one file per user and session, so they do not conflict on merge.
5. **Tell the human what happens next**, briefly:
   - capture starts with the next prompt of this session; what the session spent before is not counted;
   - what is recorded: counts and names of prompts, tools, skills and subagents, durations, lines added and removed, token totals per model, the ticket key; and what is not: prompt text, model output, file contents, command lines;
   - with `--share`, the e-mail from `git config user.email` is written into committed files unless `--anonymize` is set — say this plainly so the team decides knowingly;
   - `/ai-enabler-metrics:metrics-usage-report` produces the report.

## Rules

- Create only what is listed here. Do not touch the root `.gitignore` beyond what the human asks.
- Sharing other people's usage data is a team decision: default to local-only and mention `--share` rather than choosing it for them.
- To collect across many repositories into one place instead, the environment variable `ENABLER_METRICS_DIR` (an absolute path) switches capture on everywhere for that user; mention it when the human asks for organisation-wide measurement.
