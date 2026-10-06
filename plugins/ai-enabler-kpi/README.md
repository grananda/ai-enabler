# ai-enabler-kpi — measuring AI usage

`ai-enabler-kpi` answers three questions about a project that works with Claude Code:

1. **How much does a person have to interact with the machine?** Prompts, slash commands, permission prompts, questions answered, interruptions.
2. **Where does the time go?** AI working time, versus the time the AI spent waiting for a person, versus the time a person took between turns.
3. **What does it cost?** Tokens and USD per session, user, ticket, skill, subagent and model.

It measures with hooks, so nothing is self-reported and no skill has to cooperate. It works with the `ai-enabler` pipeline and with any other way of using Claude Code.

## Quick start

```
/ai-enabler-kpi:kpi-init       # opt this project in (creates .enabler/kpi/)
                            # capture begins with the next prompt
...work as usual...
/ai-enabler-kpi:kpi-report     # AI usage + delivery flow, as HTML dashboards
```

The report lands in `.enabler/kpi/reports/<date>/`:

| File | For |
|---|---|
| `report.html` | AI usage: headline tiles, charts (cost by agent, model, skill, day, ticket and developer; time split; interactions) and tables. Self-contained, light and dark |
| `delivery.html` | The delivery-flow dashboard, with links to `pr-size.html`, `review-wait.html`, `rework.html`, `cycle-time.html` |
| `report.md` | The same content as text |
| `kpi.json` | Every figure, overall and by ticket, user and day, for other tools |
| `sessions.csv`, `tickets.csv`, `users.csv`, `daily.csv` | Spreadsheets and BI |

Filters: `--since`, `--until`, `--user`, `--ticket`. Several repositories can be merged into one report by repeating `--kpi-dir`. The script also runs on its own, with no Claude session:

```
python3 plugins/ai-enabler-kpi/scripts/kpi_report.py --since 2026-10-01 --ticket PROJ-123
```

## Delivery-flow metrics

The hooks measure how AI is used. Four more skills measure how the team delivers, from GitHub and Jira, for everyone's work — with or without AI. Together they give the picture a cost figure alone cannot: whether pull requests are getting smaller, reviews faster, rework rarer and tickets quicker.

| Skill | Question it answers | Source |
|---|---|---|
| `/ai-enabler-kpi:pr-size` | How large are the pull requests we merge? Median lines changed, lock files and generated code excluded | GitHub CLI |
| `/ai-enabler-kpi:review-wait` | How long does a PR wait for its first human review, and who reviews? | GitHub CLI |
| `/ai-enabler-kpi:rework` | How often is merged work reverted or followed by a fix for the same ticket? | GitHub CLI |
| `/ai-enabler-kpi:cycle-time` | How long from "In Progress" to "Done", how many tickets bounce back, how long are they blocked? | Jira |
| `/ai-enabler-kpi:delivery-report` | All four, on one dashboard | — |

`/ai-enabler-kpi:kpi-report` runs these too, so one request gives AI usage and delivery flow together.

Each metric is broken down per week (or sprint), per area or issue type, and **per developer**. Every report is a self-contained HTML page with charts — `delivery.html` for the dashboard, and `pr-size.html`, `review-wait.html`, `rework.html`, `cycle-time.html` for the detail — in `.enabler/kpi/reports/<date>/`. They open offline, follow the light or dark theme, and print.

### How they work

- **A script does the arithmetic.** `scripts/pr_metrics.py` and `scripts/jira_cycle.py` compute every figure — medians, bootstrap confidence intervals, coverage, Wilson intervals for rates — with a fixed seed, so the same data gives the same report. The model runs the script and reads the result; it calculates nothing.
- **GitHub is read with the GitHub CLI.** Install `gh` (https://cli.github.com) and run `gh auth login` — for GitHub Enterprise, `gh auth login --hostname <host>`. This is the recommended way: it uses each person's own access, stores no token in the project, and needs no MCP server. Answers about merged pull requests are cached under `.enabler/kpi/delivery/cache/`, so a second run is fast.
- **Jira is read directly when possible.** With `JIRA_URL` and `JIRA_PERSONAL_TOKEN` (or `JIRA_USERNAME` and `JIRA_API_TOKEN`) in the environment — the variables the `mcp-atlassian` server already uses — the script calls Jira's REST API itself, read-only. Otherwise the `jira-collector` agent fetches the tickets through the connected Jira MCP server and saves them to files for the script; the skill then spot-checks what the agent copied.
- **Snapshots.** Each metric leaves `.enabler/kpi/delivery/<metric>.json`. The dashboard is built from those and recomputes nothing; it says so when its sections were computed for different repositories or windows. In a project where KPI capture was never switched on, snapshots and reports go to `.enabler/delivery/` instead: running a report does not opt the project into capture.
- **A ticket pattern makes rework reliable.** Follow-ups are found by ticket key. Set `ticket_pattern` to the project's own keys; without it, anything shaped like `ABC-123` counts (minus known look-alikes such as `UTF-8`), and the report says so.
- **Not in the hooks.** These metrics query remote systems and take seconds to minutes; a hook runs on every tool call and must be instant and silent. They run when a report is asked for.

### Configuration

Under `delivery` in `.enabler/kpi/config.json`; everything is optional:

| Key | Default | Meaning |
|---|---|---|
| `repo`, `base_branch` | the current repository and its default branch | What to analyse |
| `weeks` | `6` | Window for the pull-request metrics |
| `followup_days` | `14` | A PR is a follow-up when its ticket already had another PR merged at most this many days earlier |
| `exclude` | `[]` | Extra glob patterns left out of PR size, on top of lock files, `dist/`, `.nx/`, `coverage/`, `node_modules/`, `*.min.js`, `*.map`, `*.snap`, `*.generated.*` …. A pattern ending in `/**` matches that directory at any depth |
| `area_roots` | `apps`, `libs`, `packages`, `services`, `modules` | Directories whose children are areas of their own |
| `size_buckets` | `[100, 500]` | S below the first, L from the second |
| `show_people` | `true` | Per-developer charts and tables. Set to `false` to leave people out of the reports and of the snapshots |
| `jira.project`, `jira.sprints`, `jira.board` | none, `3`, first scrum board | What to analyse in Jira |
| `jira.statuses.order` | a common workflow | The statuses from first to last; statuses in the same group are the same step. Decides what "backward" means |
| `jira.statuses.in_progress`, `jira.statuses.blocked` | `In Progress`…, `Blocked`… | Where cycle time starts, and what counts as blocked |

The ticket key pattern is the top-level `ticket_pattern`, shared with the AI usage capture.

### Per-developer figures

They are on by default because knowing the numbers per developer is the point for many teams. The reports attach the context they need: PR size follows the kind of work, a follow-up is attributed to whoever opened it (often the person finishing someone else's ticket), a Jira assignee is whoever held the ticket at the end, and the reviewer with the most first reviews is carrying the load. Depending on the country and the organisation, reporting on named individuals may need agreement with the people concerned or their representatives; `show_people: false` produces the same reports with no person in them — not in the HTML and not in the snapshot files.

## What is measured

| Family | KPIs |
|---|---|
| Human interaction | free-text prompts, slash commands, permission prompts and denials, questions answered, interrupted tool calls, total interactions, tool calls per human prompt |
| Time | AI working time, human waiting time (approvals, questions), human thinking time (between turns, capped), engaged time, subagent run time, AI time per prompt |
| Output | files and lines written by the AI, commits, pushes, pull requests, skill runs, subagent runs |
| Cost | input, output, cache-read and cache-write tokens; USD by model, skill, agent, ticket, user, day, session; cost per ticket; cost per AI hour. Priced per provider: Anthropic list, or Amazon Bedrock by region and inference profile |

Definitions and formulas are in [docs/kpi-reference.md](../../docs/kpi-reference.md).

## How it works

```
Claude Code session
   │  hook events (JSON on stdin)
   ▼
hooks/kpi_hook.py ──► .enabler/kpi/events/<user>/<session>.jsonl     one line per event
   │ at the end of each turn
   └─ reads the session transcript and the subagent transcripts,
      totals message.usage per model, records the delta
                                   │
scripts/kpi_report.py ◄────────────┘ + scripts/pricing.json (per provider; Bedrock via update_pricing.py)
   ▼
report.md · report.html · kpi.json · *.csv
```

The plugin registers one script on fourteen hook events (`hooks/hooks.json`):

| Hook event | What the script records |
|---|---|
| `SessionStart`, `SessionEnd` | Session boundaries, project, branch; final usage delta |
| `UserPromptSubmit` | A prompt: its kind (human, slash command, system notification), its length, the command name, the gap since the previous turn ended |
| `PreToolUse` | Nothing by itself; a timestamp used to measure waiting |
| `PostToolUse`, `PostToolUseFailure` | A tool call: name, duration, and by type — skill name, subagent type, file with lines added and removed, the program a shell command ran, MCP server; failures and interruptions |
| `PermissionRequest`, `PermissionDenied` | A permission prompt shown to the person, and denials |
| `Notification` | The notification type |
| `SubagentStart`, `SubagentStop` | Subagent type and run time |
| `PreCompact` | A context compaction |
| `Stop`, `StopFailure` | The end of a turn: duration, time blocked on a person, tool count; the token usage added during the turn |

Hook payloads carry no token or cost information. Cost comes from the transcript Claude Code writes for each session: at the end of every turn the script totals `message.usage` for the session and its subagents and records what was added since the previous turn, tagged with the model, the active skill and the agent. Recording it turn by turn means the data survives after local transcripts are cleaned up, and each slice of cost is attributed to the ticket that was active at the time. In a test session, the figure computed this way matched the `total_cost_usd` reported by `claude -p --output-format json` to the fourth decimal.

## Opt-in, and what is stored

- **Off by default.** The hooks do nothing in a project without a `.enabler/kpi/` directory. When it is created in the middle of a session, capture starts with the next event, and what that session had already spent is taken as the baseline rather than billed. `/ai-enabler-kpi:kpi-init` creates it; removing it switches capture off. Alternatively, setting the environment variable `ENABLER_KPI_DIR` to an absolute path captures every project of that user into one place.
- **Passive.** The script never blocks a tool, never asks anything, prints nothing into the conversation, and always exits 0.
- **Stored:** event type and time, session id, user id, ticket key, tool, skill and subagent names, durations, prompt length in characters, the path of files the AI wrote with line counts, the program name of shell commands (`git`, `mvn`, ...), the name of a slash command (never its arguments), token totals per model.
- **Never stored:** prompt text, model output, file contents, command lines and their arguments, tool results.

The user id is `git config user.email`, falling back to the OS user name. Set `"anonymize_users": true` in `.enabler/kpi/config.json` to store a stable hash instead, or `ENABLER_KPI_USER` to choose the id.

## Local or shared

`kpi-init` writes a `.gitignore` inside `.enabler/kpi/`. By default it ignores `events/`, so each developer's data stays on their machine and reports are personal. With `--share`, event files are committed: there is one file per user and session, so they never conflict, and anyone can report on the whole team. Sharing puts user ids into the repository, so make it a team decision, and consider `anonymize_users`.

## Configuration

`.enabler/kpi/config.json`, all keys optional:

| Key | Default | Meaning |
|---|---|---|
| `idle_cap_seconds` | `600` | Longest gap between turns counted as thinking time; longer gaps count as the cap and as an "away" gap |
| `anonymize_users` | `false` | Store a hash instead of the e-mail |
| `record_paths` | `true` | Store the paths of files the AI wrote (needed for "files touched") |
| `provider`, `bedrock_region`, `bedrock_scope`, `cost_multiplier`, `model_aliases` | unset | Pricing overrides; see "Pricing, and Amazon Bedrock" |
| `ticket_pattern` | `null` | Regular expression for ticket keys, for example `"(PROJ|OPS)-\\d+"`. The default matches anything shaped like `ABC-123`, minus a list of known false friends such as `UTF-8` |

A session is attributed to the last ticket key seen in a prompt, in the arguments of a skill, or in the branch name at session start.

## Pricing, and Amazon Bedrock

Cost is tokens multiplied by the price table of the provider that served them. `scripts/pricing.json` carries one table per provider:

| Provider | Table | Source |
|---|---|---|
| `anthropic` | One price set per model | Anthropic list prices. Also used for Microsoft Foundry, which bills at the same rates |
| `bedrock` | Per region, per model, and per inference-profile scope (`global`, `regional`), with explicit prices for input, output, cache read, 5-minute and 1-hour cache writes | The AWS Price List, fetched by `scripts/update_pricing.py` |
| `vertex` | None bundled; priced with the `anthropic` table and flagged in the report | — |

On Bedrock the price of a token depends on three things, and the report resolves each one:

| What | Why it matters | How it is resolved |
|---|---|---|
| **Provider** | Bedrock's table differs from Anthropic's | Recorded by the hook from `CLAUDE_CODE_USE_BEDROCK`; otherwise recognised from the model id (`anthropic.`, a region prefix, or a Bedrock ARN) |
| **Region** | Not every model is sold in every region | Recorded by the hook from `AWS_REGION` |
| **Scope** | Regional and geographic profiles (`eu.`, `us.`, `apac.` …) cost 10 % more than `global.` profiles on current models | From the model id when it carries the prefix; else `bedrock_scope` from the configuration or `--bedrock-scope`; else what the hook saw in the model variables (`ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_*_MODEL` …); else **regional**, the higher rate, with a note in the report |

Model ids are reduced to their Anthropic name before lookup, so `arn:aws:bedrock:eu-west-1:…:inference-profile/eu.anthropic.claude-sonnet-4-5-20250929-v1:0` is priced as Sonnet 4.5, regional, in `eu-west-1`.

The report has a **Cost by price basis** table showing which table priced each part of the total (for example `bedrock · eu-west-1 · regional`), followed by every assumption it had to make. Read that table first: if it says something other than how the project really runs, fix the configuration and rerun — events store tokens, not money, so history is repriced.

### Setting it up for a Bedrock project

1. Nothing, in the common case: with `CLAUDE_CODE_USE_BEDROCK=1` and `AWS_REGION` set as Claude Code itself needs them, sessions are priced as Bedrock in that region.
2. If the bundled table lacks your region (it ships `us-east-1`, `us-west-2`, `eu-west-1`, `eu-central-1`, `eu-south-2`), or to refresh prices:

   ```
   python3 plugins/ai-enabler-kpi/scripts/update_pricing.py --region eu-west-3
   ```

   It reads AWS's public price list (no credentials) and updates the `bedrock` section. Add `--file <project>/.enabler/kpi/pricing.json` to keep the addition in the project instead. A project price file is layered over the bundled one, so it only needs to contain what it adds or changes.
3. Pin what cannot be detected, in `.enabler/kpi/config.json`:

   ```json
   {
     "provider": "bedrock",
     "bedrock_region": "eu-west-1",
     "bedrock_scope": "global",
     "cost_multiplier": 0.9,
     "model_aliases": {
       "arn:aws:bedrock:eu-west-1:123456789012:application-inference-profile/abc123": "eu.anthropic.claude-sonnet-5-5"
     }
   }
   ```

   - `provider` — needed when sessions reach Bedrock through an LLM gateway (`ANTHROPIC_BASE_URL`), which hides the provider from Claude Code.
   - `bedrock_scope` — when the model id in the transcript does not show the profile.
   - `cost_multiplier` — a private pricing agreement or an enterprise discount, as a factor on every row.
   - `model_aliases` — application inference profiles have opaque ARNs; map each to the model it fronts. Unmapped ones are reported as unpriced, never as zero.

The same three settings exist as report flags (`--provider`, `--bedrock-region`, `--bedrock-scope`) for a what-if run. A scope given this way applies wherever the model id itself does not name the profile.

### What the Bedrock figure does not include

It is on-demand, standard-tier token pricing. It does not know about provisioned or reserved throughput, the priority and flex tiers, batch inference, long-context surcharges on older models, taxes, or credits. For the amount actually billed, use AWS Cost Explorer or the Cost and Usage Report — application inference profiles with cost-allocation tags give a per-team split there — and treat this report as the attribution of that spend to tickets, people and skills. If the two drift apart, `cost_multiplier` calibrates one to the other.

Models missing from a table are listed in the report as unpriced rather than silently counted as zero.

## Limits to keep in mind

- Cost is the provider's published on-demand price, not the invoice: discounts, commitments and taxes are outside it. On a subscription plan the organisation is not billed per token at all; use the figure to compare tickets, people and skills.
- A few small auxiliary requests (session titles, for example) are not written to the transcript, so the total runs slightly under Claude Code's own (under 2 % in a short test session, less in long ones).
- Human time is attention at the keyboard as seen by the session. It does not include reading code in the editor, hand edits, or anything outside Claude Code.
- Pressing Esc while the model is writing text is not exposed to hooks. Interrupted tool calls are counted.
- The report states what happened. It has no baseline, so it does not compute savings or productivity gains.

For organisation-wide dashboards, Claude Code's OpenTelemetry export is the complementary route; this plugin is the zero-infrastructure, per-ticket one.

## Testing

```
python3 plugins/ai-enabler-kpi/tests/test_kpi.py
python3 plugins/ai-enabler-kpi/tests/test_delivery.py
```

`test_delivery.py` runs the four delivery metrics on fixtures (no GitHub or Jira needed) and checks medians, review waits with draft and bot cases, follow-up and revert detection, cycle time across a weekend, backward moves outside the window, blocked time and unknown statuses. `test_kpi.py` replays a short session through the hook with a synthetic transcript, runs the report, and checks interaction counts, waiting time, cost by skill and agent, privacy (no prompt or command text on disk) and the opt-in rule.
