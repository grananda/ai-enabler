---
name: metrics-usage-report
description: Produces the AI usage report from the events captured by the ai-enabler-metrics hooks — human interaction with the machine, AI working time versus human waiting and thinking time, output, token usage with its cost in USD per session, user, ticket, skill, agent and model, and which skills and agents are in use — followed by the delivery-flow dashboard (pull request size, review waiting time, rework, Jira cycle time). Runs the bundled scripts, which write HTML with charts plus Markdown, JSON and CSV, then adds a short reading of the numbers. Use when the user says "usage report", "metrics report", "how much did the AI cost", "AI usage report", "cost per ticket", "how much time did we spend with the AI", "show the metrics", "usage for PROJ-123", or "export the metrics".
argument-hint: [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--user <id>] [--ticket <KEY>] [--metrics-dir <dir> ...] [--out-dir <dir>] [--provider anthropic|bedrock|vertex|foundry] [--bedrock-region <region>] [--bedrock-scope global|regional] [--no-delivery] [--refresh]
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.0.0"
---

# ai-enabler-metrics:metrics-usage-report — the usage report

The numbers come from a script, not from you. Your part is to run it with the right filters and to help the human read the result.

## Flow

1. **Run the script**, passing through the filters in `$ARGUMENTS`:

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/usage_report.py" --quiet [filters]
   ```

   - `--no-delivery` and `--refresh` are for this skill: do not pass them to `usage_report.py`, which does not know them (`--refresh` goes to the delivery scripts in step 4).
   - With no `--metrics-dir` it uses the project's `.enabler/metrics/` (or `ENABLER_METRICS_DIR`). Repeat `--metrics-dir` to merge several repositories into one report.
   - Translate what the human said into filters: "this week" or "October" into `--since`/`--until` dates, a Jira key into `--ticket`, a person into `--user` (the id as it appears under `.enabler/metrics/events/`).
   - It writes `report.md`, `report.html`, `usage.json`, `sessions.csv`, `tickets.csv`, `users.csv` and `daily.csv` to `.enabler/metrics/reports/<today>/` unless `--out-dir` says otherwise, and prints that location.
2. **If it exits with a message instead of a report**, relay it. "No metrics directory found" means capture was never switched on: point to `/ai-enabler-metrics:metrics-usage-init`. "No events" means capture is on but no session has run since, or the filters exclude everything.
3. **Read `report.md`** and give the human:
   - the headline figures: total cost, AI working time, human time, human interactions, tool calls per prompt, cost per ticket;
   - three or four observations that the tables support — for example which ticket, skill or subagent takes most of the cost, whether human time is mostly waiting on approvals (a sign that permission rules are worth tuning) or mostly thinking between turns, how many interactions a ticket needed;
   - from the "Skills and agents in use" table: which assets are stale (unused for 90 days) and which have no owner — candidates for the quarterly review, to be checked with their owner, not deleted on the spot;
   - the paths of the files written, naming `report.html` as the one to open or share and the CSV files as the ones to load into a spreadsheet or BI tool.
4. **Add the delivery-flow metrics.** A report request means the whole picture, so unless `--no-delivery` was passed, follow `${CLAUDE_PLUGIN_ROOT}/skills/metrics-delivery-report/SKILL.md` from its step 1 (it will find the AI usage report already written and put its headline on the dashboard). Then name `delivery.html` as the page that brings everything together. If neither GitHub nor Jira can be read, say what is missing in one line and leave it at the AI usage report.
5. **Offer nothing further unless asked.** If the human wants the report somewhere else, in another format, or published, do that as a separate step.

## Reading the numbers honestly

- **Usage metrics are context, never targets.** Cost, tokens, AI time, prompts, lines written by the AI and the number of skills show whether and how AI is being used. None of them measures delivery, and a team optimises whatever becomes a target. Do not rank people by them, do not propose a goal for any of them, and if the person asks for a target on one, say why it does not take one and point to the delivery metrics, which can.

- **Measured versus derived.** Counts, durations and tokens are measured by hooks. Cost is tokens multiplied by a price table: `${CLAUDE_PLUGIN_ROOT}/scripts/pricing.json`, or the project's `.enabler/metrics/pricing.json`. If the report lists unpriced models, say the total is understated and by which models.
- **Check the price basis before quoting a cost.** The "Cost by price basis" table says which table priced the total — `anthropic`, or `bedrock · <region> · <scope>` — and lists every assumption made. On Amazon Bedrock, regional and geographic inference profiles cost more than global ones, so an assumed scope moves the total by about 10 %. If an assumption is listed, tell the human what was assumed and how to settle it (`bedrock_scope`, `bedrock_region`, `provider` or `model_aliases` in `.enabler/metrics/config.json`, or the matching `--bedrock-scope`, `--bedrock-region`, `--provider` flags), then offer to rerun. If the region is missing from the table, `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/update_pricing.py" --region <region> --file .enabler/metrics/pricing.json` fetches it from AWS's public price list.
- **Published price is not the invoice.** The figure is on-demand token pricing. It excludes discounts, provisioned or reserved throughput, service tiers, taxes and credits; on a subscription plan nothing is billed per token. For the billed amount on Bedrock, point to AWS Cost Explorer. The figure is a sound relative measure between tickets, users and skills.
- **Human time is attention, not effort.** It counts waiting on approvals and questions, plus the gap between turns up to the idle cap. It does not see reading code in the editor, hand edits, or meetings. Never present it as the hours a person worked on a ticket.
- **No savings claims.** The report does not know how long the work would have taken without AI. Do not compute or imply a saving, a productivity gain or a return on investment from these numbers alone; if the human wants one, they need a baseline (an estimate or logged hours), and the comparison is theirs to make.
- **Small samples.** With a handful of sessions, describe what happened; do not generalise.

## Which folder

Paths in this skill say `.enabler/metrics/`. A project set up before 1.0.0 may still keep its data in `.enabler/kpi/`; the scripts use whichever exists and print the paths they write. In such a project read and write under `.enabler/kpi/` — never create `.enabler/metrics/` beside it, which would split the data.

## Rules

- Do not recompute or adjust figures yourself. If a number looks wrong, say so and show the events behind it (`.enabler/metrics/events/<user>/<session>.jsonl`) rather than correcting it by hand.
- Report files can contain user identifiers and ticket keys. Do not publish or send them anywhere unless the human asks.
