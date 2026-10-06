# Design: how ai-enabler was put together

This document records the analysis behind the marketplace and the decisions taken, so that someone extending it knows what is deliberate.

## The goal

Work with AI without spec-driven development, with the machine doing the delivery work from a Jira ticket, using MCP for the ticket and subagents where they pay off, and with hooks collecting KPIs — how much the person interacts with the machine, how long the AI works, and what it costs — that can be extracted as a report.

## The two starting points

Two existing marketplaces cover the ground between them, with the split of work reversed.

| | AI Enablement (`ai-enablement-use-cases`) | AIAD (`aidd-marketplace`, plugin `aiad`) |
|---|---|---|
| Who writes the code | The AI, once the human confirms the plan | The human; the AI writes only tests |
| How work starts | Phased pipelines with confirmation gates | The human invokes a skill when needed |
| Where the story comes from | Jira and Confluence, through MCP | Local documents in the repository |
| Deliverables | Code, tests, plans and reports in Markdown | Advice, tests, a teaching review report |
| Size | 11 plugins, 25 skills, 1 agent | 1 plugin, 11 skills, 1 subagent, 2 hooks |
| Measurement | None | An authorship journal and an activity log, by hook |

Of 25 functions compared across the two, only 6 overlap (planning, design options, unit tests, code review, branch or PR review, commit). AI Enablement alone has code generation, the coverage threshold, auto-fix, SonarQube, Jira and Confluence access, documentation and log analysis. AIAD alone has explaining, reasoning aloud, TDD, end-to-end tests, pairing, performance review, triage, the engine switch and authorship tracking.

The goal above is AI Enablement's model — the AI executes — so that is the base. AIAD contributes wherever the base has a gap.

## What was taken from AI Enablement

| Idea | Source | In ai-enabler |
|---|---|---|
| Jira ticket (or Markdown file) as the input, read through MCP | `code-generator`, `jira-ticket-retriever` | `ticket-analyst` agent, used by `deliver` and `plan` |
| Four-step pipeline: read requirements, analyse the repository, plan files, write code | `generate-code` and its four internal skills | Stages 1–3 and 5, each a real subagent |
| Structured requirements with feature type, criteria and open questions | `requirements-reader` | `requirements.json`, plus a readiness verdict |
| Repository conventions and project rules as hard constraints | `repo-analyzer` | `repo-scout`, which also finds the working build, test and coverage commands |
| File-level blueprint approved before code is written | `code-planner`, `story-to-plan` | `plan.md` and the plan gate |
| Unit tests with a coverage threshold on changed code (70 % there) | `generate-tests` | `test-engineer` in coverage mode, with a target of 80 % and a minimum of 70 % |
| Parallel review agents by focus, findings filtered by confidence ≥ 80, severity-ranked Markdown report, optional auto-fix | `smart-review` | `code-reviewer` × lenses, `review.md`, the fix loop |
| Commit and push after confirmation | `release-doc` | `ship`, extended to the pull request and Jira |

## What was taken from AIAD

| Gap in the base | AIAD idea | In ai-enabler |
|---|---|---|
| No measurement at all | Passive, opt-in hooks that log activity and turn duration (`aidd-activity-hook`), consumed by a metrics script (`aiba-metrics`) | The `ai-enabler-kpi` plugin |
| The "agents" of the pipeline are skills sharing one context | A real subagent with an isolated context and no edit tools (`aiad-reviewer`) | All six agents; reviewers are read-only by construction |
| Review checklist is generic | Comprehensive per-layer checklist (backend, API, frontend), evidence with `file:line`, "needs a test" per finding, acceptance-criteria coverage | `references/review-checklist.md` and the reviewer's output format |
| Tests are written only after the code, from the code | Tests first, derived from acceptance criteria (`aiad-tdd`); end-to-end level (`aiad-test e2e`) | Stage 4: `test-engineer` writes the acceptance tests before the code, and the implementer has to make them pass; `e2e` level optional |
| Push is a bare `git commit && git push` | Non-destructive rules: never force, never reset, abort a conflicting rebase, stop and report (`aiad-save`) | `references/git-and-jira-safety.md` |
| No way to hand work between machine and human mid-ticket | The engine switch (`aiad-bridge`) | Takeover and resume: the run directory holds the state, and `deliver` treats a person's edits as part of the change |
| No record of who did what | The authorship journal | `human_interventions` in `state.json`, and the interaction KPIs |
| Performance is not reviewed | `aiad-review perf` | Evident performance problems are part of the quality lens |

Deliberately left out, because they belong to the human-first model and not to this one: explaining code, the rubber duck, pairing, and triage for someone who is stuck. Teams that want them can install AIAD alongside; nothing here conflicts with it. Also left out for now: SonarQube, onboarding documentation and Dynatrace log analysis from AI Enablement, which are independent of the delivery flow and can be installed from that marketplace.

## Decisions

### Two plugins, not one and not eleven

AI Enablement ships one plugin per skill, which makes a coherent flow hard to install and version. AIAD ships one plugin. Here the split follows a real boundary: delivery and measurement are independent. `ai-enabler-kpi` has to work for teams that do not use the pipeline, and must be removable where measurement is not wanted. Everything else is one plugin, because the stages share agents, references and a run directory.

### Real subagents, exchanging files

In AI Enablement the orchestrator invokes four skills in sequence and passes JSON between them as arguments, all in one context. That context fills with the ticket, the repository scan and every generated file. Here each stage is a subagent with its own context that writes a file in `.enabler/runs/<KEY>/`. This gives three things: the orchestrator stays small enough to steer a long run; a run can be resumed, or one stage re-run, from the files; and the reviewer has not seen the implementer's reasoning, only its code.

Subagents are used where a stage reads much and returns little, or where independence matters. Orchestration, consolidation of findings and the gates stay in the main conversation, where the human is.

### A model per stage

Agents do not all inherit the session's model. Planning and review run on Opus at high effort: the plan is the brief for everything downstream, and the reviewer has to be at least as capable as the author it checks. Intake, scout, implementation and tests run on Sonnet: they work from explicit material and account for most of the tokens. The choice is expressed as family aliases so it survives model releases and resolves through `ANTHROPIC_DEFAULT_*_MODEL` on Bedrock. It is a starting point to be tuned with the per-agent cost table of the KPI report, not a fixed rule.

### Two gates instead of a gate per phase

`smart-review` alone has five confirmation gates; `generate-tests` has three. That is appropriate when the AI is being supervised step by step, and it is exactly the human interaction this project wants to reduce and measure. The pipeline keeps the two decisions that are worth a person's attention: what will be built, before it is built, and what will leave the machine, before it does. Everything else is bounded by rules rather than by confirmations, and both gates are configurable.

Three conditional stops remain, where proceeding is not the machine's call: a ticket that is not implementable as written, a plan that proved wrong in scope, and coverage of the changed code under the minimum.

### Tests before the code, coverage after it

In AI Enablement the tests are generated from the finished code, so they inherit its mistakes: a wrong status code gets a test asserting the wrong status code. Here the tests for the ticket's acceptance criteria are written before the implementation, by a different agent from the one that writes the code, and the implementer is not allowed to edit them. A disputed test is settled against the ticket, not against the code.

This only works when the ticket gives something to test against, so the analyst grades the stated criteria as sufficient, scarce or missing, and the pipeline degrades in step: all acceptance tests first, the stated ones first and the rest after, or everything after. It never blocks on a ticket without criteria, but it says in the plan gate and in the pull request that those tests are not an independent statement of the requirement.

Coverage is a separate obligation, judged after the code whichever order the tests were written in, against a target of 80 % and a minimum of 70 % of the changed code. Reaching the band is enough for the run to continue on its own. Below the minimum the pipeline does not decide: it stops, shows what is uncovered and why, and the person chooses to proceed, to have more tests written, or to stop. That is a third, conditional stop, and it holds even in an unattended configuration — a change under the minimum reaches a pull request only because someone said so, and the pull request says who and why.

### Readiness is part of intake

A machine-driven flow fails quietly when the ticket is vague: it produces plausible code for the wrong behaviour. The analyst therefore returns a verdict — ready, ready with assumptions, or blocked — grades the acceptance criteria, and rewrites every acceptance criterion as an observable behaviour with an id. Those ids are traced through the plan, the tests, the review and the pull-request body.

### Jira through MCP, by capability, with no bundled server

AI Enablement hard-codes one server's tool names (`mcp__jira-*__jira_get_issue`). Tool names differ between Atlassian's remote server and `mcp-atlassian`, so the agents look for a tool that fetches an issue by key rather than for a name. No server is bundled, since the right one depends on Cloud versus Data Center. Jira writes are limited to a comment and an optional transition at the ship stage; ticket creation, editing and deletion stay with AI Enablement's dedicated plugins.

### KPIs by hook, cost from the transcript

Hook payloads were captured from a real session to see what they contain. They carry session, prompt and tool identifiers, the tool input, and a duration on `PostToolUse` — but no tokens and no cost. The session transcript does carry `usage` on every assistant message, with the model and the active skill, and subagents have their own transcripts beside it. So the hook totals usage from the transcripts at the end of each turn and records the delta. The result agreed with the cost Claude Code reports for the same session.

Three choices follow AIAD's hook closely: opt-in per project by the existence of a directory, passive (never blocks, always exits 0), and private (no prompt text, no code). Three differ:

- Events are JSON lines, one file per user and session, instead of one shared Markdown log — no merge conflicts, and a script can read them without parsing prose.
- Tokens are stored, not money, so a corrected price table reprices history.
- The script is Python rather than Bash with a `jq` fallback, because it has to parse transcripts and keep per-session state under a lock.

### Cost priced per provider, Bedrock first

The marketplace is expected to run mostly on Amazon Bedrock, where a token's price depends on the region and on whether the inference profile is global or regional, and where model ids arrive wrapped in prefixes and ARNs. Pricing is therefore per provider: the hook records provider, region and profile scope from the session's environment, the report reduces each model id to its Anthropic name and picks the matching table, and the Bedrock table is generated from AWS's public price list by `update_pricing.py` rather than typed in. Whatever the report has to assume is printed next to the total, and the default when the scope is unknown is the higher, regional rate.

The report states what was measured and does not compute savings. A saving needs a baseline the tool does not have; AIAD's metrics skill takes the same position.

### English artefacts

All skills, agents, scripts and documents are in English. Skills answer in the language the user writes in.

## What was verified

- Both plugin manifests and the marketplace manifest pass `claude plugin validate`.
- A headless session with both plugins loaded ran `/ai-enabler:doctor` and captured events through the hooks; the report's cost matched Claude Code's own figure for that session.
- `plugins/ai-enabler-kpi/tests/test_kpi.py` replays a session through the hook and checks counts, waiting time, cost attribution, privacy and opt-in, and prices a Bedrock session (geographic, global and unprefixed model ids) against the AWS prices for `eu-west-1`.

Not yet verified on a live Bedrock session: which form of model id Claude Code writes to the transcript there. The pricing handles every form (prefixed id, ARN, bare name plus the recorded environment), but the first real Bedrock report should be checked against its "Cost by price basis" table.

- `/ai-enabler:deliver` was run end to end, unattended (`--gates none`), on a small Node.js project from a Markdown requirements file with six acceptance criteria. All eight stages ran: the acceptance tests were written before the code, the implementation made them pass, coverage of the changed code reached 100 % line and branch, four reviewers ran in parallel, and the run held before shipping as the rules require. Each subagent ran on the model its frontmatter names (Opus for planning and review, Sonnet for the rest). The KPI report's cost for the run matched Claude Code's own figure.

Not yet exercised: a ticket read from a real Jira instance through MCP, the ship stage against a real remote (push, pull request, Jira comment), the fix loop with real blocking findings, the stop below the coverage minimum, and a large codebase. The first runs on a real ticket are where the instructions should be tuned — the plan gate's summary, the fix-loop budget and the review confidence floor are the likely candidates.

## Possible next steps

- A `SessionStart` hook in `ai-enabler` that reminds the session of an unfinished run for the current branch.
- A baseline input for the KPI report (estimated or logged hours per ticket from Jira, read through MCP) to turn cost and time into a comparison.
- A SonarQube stage after review, as AI Enablement's `smart-review` has.
- Export of KPI events to OpenTelemetry for organisation-wide dashboards.
