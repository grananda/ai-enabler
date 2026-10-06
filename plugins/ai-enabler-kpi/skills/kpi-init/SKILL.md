---
name: kpi-init
description: Switches on AI usage KPI capture for the current project by creating the `.enabler/kpi/` directory the ai-enabler-kpi hooks look for, with its configuration and git-ignore rules, and explains what will and will not be recorded. Also reports whether capture is already active, or switches it off. Use when the user says "enable KPI capture", "start measuring AI usage", "turn on metrics for this repo", "set up ai-enabler-kpi", "is KPI capture on", or "stop collecting KPIs".
argument-hint: [--status | --off] [--share] [--anonymize] [--ticket-pattern <regex>]
---

# ai-enabler-kpi:kpi-init — switch capture on for this project

The plugin's hooks are installed for every session but stay silent until a project opts in. A project opts in by having a `.enabler/kpi/` directory at its root. This skill creates it.

## Flow

1. **Find the project root** (`git rev-parse --show-toplevel`, else the current directory) and check whether `.enabler/kpi/` exists.
2. **`--status`**, or capture already on: report whether it is active, how many session files exist under `.enabler/kpi/events/`, the date of the first and the last one, and the current `config.json`. Stop here for `--status`.
3. **`--off`**: explain that capture stops when the directory is gone, and that removing it also removes the collected data. Do not delete it yourself; give the human the two options — delete the directory, or keep the data and rename it (for example to `.enabler/kpi-archived/`) — and let them do it.
4. **Switch on.** Create `.enabler/kpi/` with:
   - `config.json`:

     ```json
     {
       "idle_cap_seconds": 600,
       "anonymize_users": false,
       "record_paths": true,
       "ticket_pattern": null
     }
     ```

     Set `anonymize_users` to true with `--anonymize` (users become a stable hash instead of their git e-mail). Set `ticket_pattern` with `--ticket-pattern`, for example `"(PROJ|OPS)-\\d+"`; when the project's Jira keys are known (from `.enabler/config.json`, branch names or recent commits), propose a pattern, because the default matches anything shaped like `ABC-123`.
     When the session runs on Amazon Bedrock (`CLAUDE_CODE_USE_BEDROCK` is set), cost is priced with Bedrock's table for `AWS_REGION` automatically. Add pricing keys only for what cannot be detected, and ask the human rather than guessing: `"bedrock_scope": "global"` or `"regional"` when the project's inference profiles are known, `"provider": "bedrock"` when sessions go through an LLM gateway, `"cost_multiplier"` for a negotiated discount, `"model_aliases"` for application inference profile ARNs. If the region is not in the bundled table, run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/update_pricing.py" --region <region> --file .enabler/kpi/pricing.json`.
   - `.gitignore` inside `.enabler/kpi/`:
     - always: `.state/` and `reports/`;
     - by default also `events/`, so each developer's data stays on their machine;
     - with `--share`, leave `events/` out of it, so event files are committed and the team's data can be reported together. There is one file per user and session, so they do not conflict on merge.
5. **Tell the human what happens next**, briefly:
   - capture starts with the next session in this project (hooks load at session start);
   - what is recorded: counts and names of prompts, tools, skills and subagents, durations, lines added and removed, token totals per model, the ticket key; and what is not: prompt text, model output, file contents, command lines;
   - with `--share`, the e-mail from `git config user.email` is written into committed files unless `--anonymize` is set — say this plainly so the team decides knowingly;
   - `/ai-enabler-kpi:kpi-report` produces the report.

## Rules

- Create only what is listed here. Do not touch the root `.gitignore` beyond what the human asks.
- Sharing other people's usage data is a team decision: default to local-only and mention `--share` rather than choosing it for them.
- To collect across many repositories into one place instead, the environment variable `ENABLER_KPI_DIR` (an absolute path) switches capture on everywhere for that user; mention it when the human asks for organisation-wide measurement.
