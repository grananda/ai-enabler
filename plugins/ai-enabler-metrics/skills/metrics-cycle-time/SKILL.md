---
name: metrics-cycle-time
description: Measures Jira cycle time, backward moves and blocked time for Scrum closed sprints or an opt-in Kanban date window, per period, issue type and developer, with an HTML report. A bundled script computes the figures from read-only REST or collector files. Use for cycle time, sprint health, Kanban metrics, how long tickets take, backward moves or blocked time.
argument-hint: "[--profile NAME] [--project KEY] [--mode scrum|kanban] [--sprints 3] [--board ID | --filter ID] [--since DATE --until DATE] [--group-by week|month] [--refresh]"
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.0.5"
---

# ai-enabler-metrics:metrics-cycle-time — Jira cycle time, backward moves, blocked time

How long does a ticket take once work starts, how often is it sent back, and how long does it sit blocked? The script `jira_cycle.py` does all the arithmetic from each ticket's status history and writes a snapshot plus an HTML report with charts. Your job is to get it the data and to read the result.

## Flow

1. **Settle the inputs.** The project key comes from `$ARGUMENTS`, else `delivery.jira.project` in `.enabler/metrics/config.json`; if neither exists, ask once and offer to save it. `delivery.jira.mode` defaults to `scrum`, retaining the last 3 closed sprints. Opt in per project with `kanban`: choose a board or saved-filter ID, both `since` and `until` (ISO 8601, UTC, inclusive start and exclusive end), and `group_by: week|month`. Without dates, Kanban uses `jira.weeks` (default 6) complete Monday-to-Monday weeks. CLI flags override configured values. Do not silently change mode or broaden a board to its whole project. Scrum asks nothing new: it takes the first Scrum board, as before. Only Kanban may need one answer, when the project has several Kanban boards and none is configured: list them (ID and name), ask once which one, and offer to save it as `delivery.jira.board`.
2. **Try the direct route first:**

   ```
   /bin/bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/jira_cycle.py" --project <KEY> [--mode scrum|kanban] [--sprints N] [--board ID | --filter ID] [--since DATE --until DATE] [--group-by week|month]
   ```

   (`--refresh` is this skill's own flag, not the script's.) It reads Jira's REST API when the environment has `JIRA_URL` and `JIRA_PERSONAL_TOKEN` (or `JIRA_USERNAME` and `JIRA_API_TOKEN`) — the same variables the `mcp-atlassian` server uses. This is the preferred route: nothing passes through a model, so nothing can be mistyped. `JIRA_URL` must be https. Never ask for a token in the chat and never write one to a file.
3. **If it answers `NO_JIRA_ACCESS`,** collect through MCP instead:
   - Unless `--refresh` was passed, reuse files only when `collection.json` has a `collected_at` less than 24 hours old and exactly matches mode, project, board/resolved filter, sprint IDs or resolved UTC window and grouping. Also verify current board/filter definition and status configuration; never use file mtime alone. Missing metadata means recollect, not guess — except for a Scrum collection without a profile, which has none when it was written before this version or by the collector's fallback: reuse it when its files are less than a day old, as before. Current status and even closed-sprint issues can change.
   - Otherwise launch `ai-enabler-metrics:metrics-jira-collector` with the complete settled scope and output directory `delivery/jira-input/` inside the metrics folder in use. Start a clean collection directory on scope change, avoiding leftover issue batches. For more than about 25 tickets, use independent batches of exact keys; only the coordinator writes `collection.json` after all pages and batches succeed.
   - Check that records equal the complete scoped candidate-key list, with no duplicates. For Kanban this includes issues created before the window, unresolved issues and issues resolved later, not merely created/resolved within it. Re-fetch up to three tickets and compare full transitions with the saved data. Recollect a differing batch. Never mark truncated or unverifiable histories complete. When the collector reports "board scope unverified" (a Scrum collection through a server without board tools), the figures are computed as before; say in the report that tickets of other boards sharing the sprint may be included, and that enabling the server's board tools (`jira_get_agile_boards`, `jira_get_sprints_from_board`, `jira_get_sprint_issues` on mcp-atlassian) removes them.
   - Then run the script on the files:

     ```
     /bin/bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/jira_cycle.py" --project <KEY> --input .enabler/metrics/delivery/jira-input [same mode, scope and window flags as above]
     ```
   - If no Jira MCP server is connected either, say what is needed (the environment variables above, or a Jira MCP server) and stop.
4. **Read the snapshot** `.enabler/metrics/delivery/cycle-time.json` and tell the person:
   - the headline: median cycle time with its 90 % confidence interval and coverage, per sprint (Scrum) or week/month (Kanban). Kanban snapshots use `periods` and `by_period`; old Scrum snapshots retain `sprints` and `by_sprint`. Compare differences with intervals, not as established trends;
   - the backward rate, and how many of those tickets were sent back from a stage after in progress (review, test, acceptance, done) rather than re-planned;
   - blocked time: how many tickets and days. Kanban historical time is clipped to the UTC window and collection time, including open and later-resolved issues; `blocked_now` is a separate status-at-collection list among window candidates, not extra historical time. With no resolutions, cycle time is absent, not zero, while blocking can still be measured;
   - what stands out per issue type and per developer, with the report's own caveat about assignees;
   - **statuses the script did not recognise** (`unknown_statuses`). They are ignored when looking for backward moves, so if the list is not empty, propose adding them to `delivery.jira.statuses.order` in the configuration, in the right position, and offer to rerun;
   - anything under `resolved_outside` (tickets resolved before the first sprint or after the last, in no bucket), `truncated_changelogs` or `unverified_changelogs` (incomplete or unverifiable history — paginate/fetch each issue and rerun; the provisional figures may be wrong) and `duplicates_dropped`;
   - how the data was obtained (REST, or collected by an agent and spot-checked), and the path of the HTML report.

## Optional profile

Forward `--profile NAME` to every script/collector step. Read `<metrics-dir>/profiles/NAME.json`; it separates `connection` (HTTPS URL and credential environment-variable references, never secrets) from `delivery.jira` project/mode/selectors/statuses. CLI overrides profile delivery, which overrides legacy base/defaults. An explicit connection resets inherited Jira context; changing project/mode/board/filter resets inherited selectors/window/workflow, so state them together. No profile means the legacy behavior. Never load `.env` or copy tokens into a profile.

Use `<metrics-dir>/profiles-data/NAME/delivery/` for input collections/snapshots and `profiles-data/NAME/reports/<date>/` for reports. Cache identity includes profile and connection endpoint as well as scope/freshness. For MCP, verify the server matches the profile's exact endpoint/context; stop on mismatch or unverifiable server identity. `collection.json` requires `scope.profile` and `scope.connection_url` for either mode. Missing profile credentials never authorize fallback to global credentials or another server. An explicit `--input` is read as given but must match metadata. `--out-dir` changes only report location and must be empty or already owned by this profile; snapshots/cache stay isolated. See the plugin README for schema and merge rules.

## The workflow is configuration

Which statuses count as in progress, which as blocked, and their order from first to last are in `.enabler/metrics/config.json` under `delivery.jira.statuses` (the defaults are in `${CLAUDE_PLUGIN_ROOT}/scripts/delivery_lib.py`). The order decides what "backward" means, so two teams with different workflows need different orders. Statuses in the same group — for example To Do, Ready and In Estimation — are the same step: moving between them is not backward.

The input file formats are in `${CLAUDE_PLUGIN_ROOT}/skills/metrics-cycle-time/references/jira-input.md`.

## Which folder

Paths in this skill say `.enabler/metrics/`. A project set up before 1.0.0 may still keep its data in `.enabler/kpi/`; the scripts use whichever exists and print the paths they write. In such a project read and write under `.enabler/kpi/` — never create `.enabler/metrics/` beside it, which would split the data.

In a project where usage capture was never switched on — no `.enabler/metrics/` and no `.enabler/kpi/` — the delivery scripts write to `.enabler/delivery/` instead (snapshots, `cache/`, `jira-input/`, and `reports/<date>/`), because creating `.enabler/metrics/` would switch capture on. There, read and write every path below `.enabler/delivery/` in place of `.enabler/metrics/delivery/`, and never create `.enabler/metrics/` yourself. Use the paths the scripts print.

## Rules

- The figures come from the script. Do not recompute them, and do not compute anything from ticket data in the conversation.
- Read-only: nothing is written to Jira.
- Cycle time includes blocked and rework time by definition; say so when a long-running ticket drives a sprint's mean.
- A bucket flagged `low n` (fewer than 20 tickets) is a direction, not a result. With three sprints of about 25 tickets, sprint-over-sprint changes are rarely established; do not present them as trends.
- Per-developer figures describe the tickets as much as the person. Do not rank people or conclude anything about an individual from them.
