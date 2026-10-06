---
name: cycle-time
description: Measures Jira cycle time for the last closed sprints — median working days from "In Progress" to "Done" — together with the share of tickets that moved backward in the workflow and the time spent blocked, per sprint, per issue type and per developer, and writes an HTML report with charts. Computes everything with a bundled script, reading Jira directly when the environment allows it and through a collector agent otherwise. Use when the user says "cycle time", "sprint health report", "how long do tickets take", "how many tickets bounce back from acceptance", "blocked time", or "cycle time per developer".
argument-hint: "[--project KEY] [--sprints 3] [--board ID] [--refresh]"
---

# ai-enabler-kpi:cycle-time — Jira cycle time, backward moves, blocked time

How long does a ticket take once work starts, how often is it sent back, and how long does it sit blocked? The script `jira_cycle.py` does all the arithmetic from each ticket's status history and writes a snapshot plus an HTML report with charts. Your job is to get it the data and to read the result.

## Flow

1. **Settle the inputs.** The project key comes from `$ARGUMENTS`, else `delivery.jira.project` in `.enabler/kpi/config.json`; if neither exists, ask once and offer to save it. Sprints default to the last 3 closed ones.
2. **Try the direct route first:**

   ```
   python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jira_cycle.py" --project <KEY> [--sprints N] [--board ID]
   ```

   It reads Jira's REST API when the environment has `JIRA_URL` and `JIRA_PERSONAL_TOKEN` (or `JIRA_USERNAME` and `JIRA_API_TOKEN`) — the same variables the `mcp-atlassian` server uses. This is the preferred route: nothing passes through a model, so nothing can be mistyped. Never ask for a token in the chat and never write one to a file.
3. **If it answers `NO_JIRA_ACCESS`,** collect through MCP instead:
   - Unless `--refresh` was passed, reuse an existing collection in `.enabler/kpi/delivery/jira-input/` that is less than a day old.
   - Otherwise launch the `ai-enabler-kpi:jira-collector` agent with the project key, the number of sprints, and the output directory `.enabler/kpi/delivery/jira-input/`. For more than about 25 tickets, launch several collectors in parallel, one per batch of ticket keys, each writing its own file. They return a count and a path, never ticket data.
   - Check the collection before using it: the number of issue records equals the number of tickets in the sprints, no key is duplicated, and — because an agent copied the data — re-fetch three tickets yourself and compare their status transitions with what was saved. If any differs, re-collect that batch.
   - Then run the script on the files:

     ```
     python3 "${CLAUDE_PLUGIN_ROOT}/scripts/jira_cycle.py" --project <KEY> --input .enabler/kpi/delivery/jira-input
     ```
   - If no Jira MCP server is connected either, say what is needed (the environment variables above, or a Jira MCP server) and stop.
4. **Read the snapshot** `.enabler/kpi/delivery/cycle-time.json` and tell the person:
   - the headline: median cycle time with its 90 % confidence interval and coverage, per sprint, and whether the sprint-to-sprint differences are larger than the intervals (usually they are not);
   - the backward rate, and how many of those tickets were sent back from testing, acceptance or done rather than re-planned;
   - blocked time: how many tickets, how many days, which are blocked right now;
   - what stands out per issue type and per developer, with the report's own caveat about assignees;
   - **statuses the script did not recognise** (`unknown_statuses`). They are ignored when looking for backward moves, so if the list is not empty, propose adding them to `delivery.jira.statuses.order` in the configuration, in the right position, and offer to rerun;
   - how the data was obtained (REST, or collected by an agent and spot-checked), and the path of the HTML report.

## The workflow is configuration

Which statuses count as in progress, which as blocked, and their order from first to last are in `.enabler/kpi/config.json` under `delivery.jira.statuses` (the defaults are in `${CLAUDE_PLUGIN_ROOT}/scripts/delivery_lib.py`). The order decides what "backward" means, so two teams with different workflows need different orders. Statuses in the same group — for example To Do, Ready and In Estimation — are the same step: moving between them is not backward.

The input file formats are in `${CLAUDE_PLUGIN_ROOT}/skills/cycle-time/references/jira-input.md`.

## Rules

- The figures come from the script. Do not recompute them, and do not compute anything from ticket data in the conversation.
- Read-only: nothing is written to Jira.
- Cycle time includes blocked and rework time by definition; say so when a long-running ticket drives a sprint's mean.
- A bucket flagged `low n` (fewer than 20 tickets) is a direction, not a result. With three sprints of about 25 tickets, sprint-over-sprint changes are rarely established; do not present them as trends.
- Per-developer figures describe the tickets as much as the person. Do not rank people or conclude anything about an individual from them.
