# KPI reference

The event schema written by `plugins/ai-enabler-kpi/hooks/kpi_hook.py`, and the definition of every KPI computed by `scripts/kpi_report.py`.

## Storage layout

```
.enabler/kpi/
  config.json                      capture and report settings
  pricing.json                     optional price table override
  events/<user>/<session_id>.jsonl one JSON object per line, append-only
  reports/<YYYY-MM-DD>/            report output
  .state/                          per-session working state of the hook (never committed)
```

## Events

Fields on every event:

| Field | Meaning |
|---|---|
| `v` | Schema version (`1`) |
| `ts`, `t` | Time, ISO 8601 UTC and epoch seconds |
| `ev` | Event type, below |
| `sid` | Claude Code session id |
| `user` | User id (git e-mail, OS user, or hash) |
| `ticket` | Ticket key active at that moment, when one is known |
| `pid` | Prompt id: groups the events of one turn |

| `ev` | Extra fields | Written on |
|---|---|---|
| `session_start` | `source` (startup, resume, clear, compact), `project`, `branch`, `model`, `provider`, `region`, `scope` | `SessionStart` |
| `prompt` | `kind` (`human`, `command`, `system`), `chars`, `command`, `idle_s` | `UserPromptSubmit` |
| `tool` | `tool`, `dur_ms`, `wait_ms`, `perm`, `failed`, `interrupt`, `question`; and by tool: `skill`; `agent`; `file`, `added`, `removed`; `cmd`, `git` (`commit`, `push` or `commit+push`), `pr`; `mcp` | `PostToolUse`, `PostToolUseFailure` |
| `permission` | `tool` | `PermissionRequest` |
| `permission_denied` | `tool` | `PermissionDenied` |
| `notification` | `kind` | `Notification` |
| `subagent` | `agent`, `dur_s` | `SubagentStop` |
| `compact` | `trigger` | `PreCompact` |
| `turn` | `kind`, `dur_s`, `ai_s`, `wait_s`, `tools`, `failed` | `Stop`, `StopFailure` |
| `usage` | `rows`: list of `{model, skill, agent, speed, provider, region, scope, in, out, cr, cw5, cw1, web}` | `Stop`, `StopFailure`, `SessionEnd` |
| `session_end` | `reason` | `SessionEnd` |

Notes:

- `prompt.kind` is `command` only when the first word is a slash command name (`/name` or `/plugin:name`); a prompt that merely begins with a path is `human`. It is `system` when the turn was started by the harness, not a person — for example the notification that a background subagent finished. These are not counted as human interaction.
- `prompt.idle_s` is the time since the previous turn of the session ended.
- `tool.wait_ms` is time the tool call spent blocked on a person. For a tool that raised a permission prompt it is the time between `PreToolUse` and `PostToolUse` minus the tool's own `duration_ms`; for `AskUserQuestion` it is the whole interval.
- `usage.rows` holds the tokens added since the previous `usage` event of the session: `in` input, `out` output, `cr` cache read, `cw5` and `cw1` cache writes with 5-minute and 1-hour lifetime, `web` web-search requests. `skill` is the skill active when the tokens were spent (`-` for none). `agent` is `main` or the subagent type. `speed` is present only for fast mode. `provider` (`bedrock`, `vertex`, `foundry`, `gateway`), `region` and `scope` are present when the session did not run on Anthropic's own API: the hook takes them from `CLAUDE_CODE_USE_BEDROCK`, `AWS_REGION` and the configured model ids.

## KPI definitions

### Human interaction

| KPI | Definition |
|---|---|
| Free-text prompts | `prompt` events with `kind = human` |
| Slash commands | `prompt` events with `kind = command` |
| Permission prompts | `permission` events |
| Permission denials | `permission_denied` events |
| Questions answered | `tool` events with `question` |
| Interrupted tool calls | `tool` events with `interrupt` |
| **Human interactions** | prompts + commands + permission prompts + questions + interrupts |
| **Tool calls per human prompt** | `tool` events ÷ (prompts + commands). The autonomy indicator: how much the machine does per human input |

### Time

| KPI | Definition |
|---|---|
| **AI working time** | The time the AI was busy in each session: the union of turn intervals (`turn`: `t − dur_s` to `t`) and subagent runs (`subagent`: `t − dur_s` to `t`), minus Σ `turn.wait_s`. A union, because subagents launched in the background keep working after the turn that started them ends, and parallel subagents overlap |
| Human waiting time | Σ `turn.wait_s`: time inside turns spent blocked on an approval or a question |
| Human thinking time | Σ `min(prompt.idle_s, idle cap)` over human and command prompts |
| Away gaps | Number of prompts whose `idle_s` exceeded the idle cap |
| **Human time** | waiting + thinking |
| Engaged time | AI working + human time |
| Subagent run time | Σ `subagent.dur_s`. Runs inside AI working time; parallel subagents overlap, so it can exceed it |
| Wall clock (per session) | Last event − first event, pauses included |

The idle cap (`idle_cap_seconds`, default 600) separates "reading the answer and deciding what to ask next" from "went to a meeting". A gap longer than the cap contributes the cap, not its full length.

### Output

| KPI | Definition |
|---|---|
| Files touched | Distinct `tool.file` values |
| Lines added / removed | Σ `tool.added`, Σ `tool.removed`: line counts of the content the AI wrote and replaced through its edit tools. A measure of volume written, not a net diff of the repository |
| Commits, pushes, pull requests | `tool` events that did not fail, whose shell command ran `git commit`, `git push` (both when chained), or `gh pr create` / `glab mr create` |
| Skill runs, subagent runs | `tool.skill` counts (skills the model invoked), `subagent` events by type. Skills a person invoked as a slash command appear under slash commands |

### Cost

Each usage row is priced with the table of the provider that served it. The prices of a row are looked up as follows:

1. **Model.** The id is reduced to its Anthropic name: a Bedrock ARN keeps only its last segment, then the region prefix (`global.`, `eu.`, `us.` …), `anthropic.`, a `-v1:0` suffix and a `[1m]` suffix are removed. `model_aliases` from the configuration is applied first. The result is matched against the table by longest prefix, so `claude-haiku-4-5-20251001` resolves to `claude-haiku-4-5`.
2. **Provider.** `provider` from the configuration or `--provider`; else the row's `provider` (recorded by the hook); else `bedrock` when the id is Bedrock-shaped; else the table's `default_provider`.
3. **For Bedrock, region.** `bedrock_region` from the configuration; else the row's `region`; else the table's `default_region`. A model not sold in that region takes the price from another region, with a note.
4. **For Bedrock, scope.** `global` or `regional` from the id's prefix; else `bedrock_scope` from the configuration or `--bedrock-scope`; else the row's `scope`, which the hook inferred from the environment; else `regional`, with a note.

```
cost = ( in  × input
       + out × output
       + cr  × cache_read
       + cw5 × cache_write_5m
       + cw1 × cache_write_1h ) / 1,000,000
       × fast_multiplier        (Anthropic fast-mode rows only)
       × cost_multiplier        (from the configuration, default 1)
```

The Bedrock table carries all five prices explicitly, as published by AWS. Where a table omits a cache price, it defaults to 0.1 × input for reads, 1.25 × input for 5-minute writes and 2 × input for 1-hour writes.

| KPI | Definition |
|---|---|
| **Total cost** | Σ row cost |
| Cost by price basis | The same sum grouped by the table used: `anthropic`, `bedrock · <region> · <scope>`, `<provider> (priced as anthropic)`, `<provider> · unpriced` |
| Cost by model, skill, agent | The same sum grouped by the row's field |
| Cost by ticket, user, day, session | The same sum grouped by the event's field |
| Cost per ticket | Total cost ÷ distinct tickets |
| Cost per AI hour | Total cost ÷ AI working hours |

`kpi.json` lists under `pricing.assumptions` every fallback taken, and under `pricing.unpriced_tokens` every model that had no price.

## Attribution to tickets

The hook keeps one "current ticket" per session. It is set from, in order of arrival: the branch name at session start, any human prompt or slash command containing a key, and the arguments of an invoked skill. Every later event carries that key until another key appears. Events recorded before the first key of a session are attributed to that first key at report time.

One session working on two tickets is split at the prompt where the second key appears. Work with no key at all is reported under `(no ticket)`.

## Known limits

- **Opting in mid-session.** The first usage snapshot of a session is a baseline. What a session spent before capture was switched on is not counted.

- **Cost is the published on-demand price**, not an invoice: no discounts, commitments, service tiers or taxes. See "Pricing, and Amazon Bedrock" in the plugin README.
- **LLM gateways** hide the provider. Sessions that reach Bedrock through one are recorded as `gateway` and priced with the Anthropic table until `provider` is set in the configuration.
- **Slight under-count of tokens.** Requests the harness makes outside the conversation are not in the transcript.
- **Resumed sessions.** When a session starts with history already in its transcript, that history is taken as the baseline and not counted again.
- **Asynchronous hooks.** Most events are recorded by hooks that run in the background, so their timestamps can lag the event by a few milliseconds; durations reported by Claude Code itself (`dur_ms`) are exact.
- **Esc during generation** is not visible to hooks.
- **Hand edits** are invisible: only what the AI writes through its tools is counted as output.
- **Windows.** The hook needs `python3` on the `PATH`; file locking is skipped there, which is harmless for a single session.
