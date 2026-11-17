# Run directory and project configuration

Shared by every `ai-enabler` skill. Read it once at the start of a skill.

## Run directory

Each ticket gets one directory, `.enabler/runs/<KEY>/`, where `<KEY>` is the Jira key (or, for a file source, the file name without extension). `source` in `state.json` says which: with `file` there is no Jira issue, so nothing is read from or written to Jira for that run. Stages talk to each other through these files, not through the conversation, which is what makes a run resumable and lets each subagent start with a clean context.

| File | Written by | Content |
|---|---|---|
| `state.json` | the orchestrating skill | Where the run is (see below) |
| `requirements.json` | `delivery-ticket-analyst`, then `delivery-ticket-refiner`; the planner updates its acceptance criteria when a delta changes them | Normalised ticket and readiness verdict. What refinement added is marked `"refined": true`; the verdicts on the ticket as it arrived are kept under `as_received` |
| `external-context.md` | `delivery-source-scout` | What the project's external sources impose on this ticket: contracts, schemas, rules, components, each with its source and path. Absent when the project has no sources |
| `refinement.md` | `delivery-ticket-refiner` | What refinement added to the ticket and why, and its questions. Absent when refinement was skipped |
| `repo-context.md` | `delivery-repo-scout` | Only what this ticket adds to the repository profile: the existing code closest to it, with the fragments the plan depends on (signatures, routes, wiring, the test to imitate), so the planner opens few files of its own |
| `plan.md` | `delivery-solution-planner` | The implementation plan as it stands now: the approved plan with every approved delta folded in |
| `deltas/delta-NN.md` | `delivery-solution-planner` (delta mode) | One file per change made after the plan was approved: why, what is added, what is removed |
| `deltas/delta-NN.before/` | the orchestrating skill | Copies of `plan.md` and `requirements.json` taken before the planner writes delta NN, so the delta can be revised or cancelled |
| `acceptance-tests.json`, `acceptance-tests.md` | `delivery-test-engineer` (acceptance mode) writes the JSON; `scripts/run_state.py` renders the Markdown from it | The tests written before the code, one row per acceptance criterion |
| `test-report.json`, `test-report.md` | `delivery-test-engineer` (coverage mode) writes the JSON, and adds each `verify` re-run to it; `scripts/run_state.py` renders the Markdown from it | Commands run and how long each took, suite result, coverage against the target and the minimum, acceptance-criteria table, mutation results |
| `review-pack.md` | `scripts/review_scope.py`, before each review pass | What every reviewer of the pass reads first: files changed and their kind, the lenses and why, the criteria in force, the test report, and the diff of the code |
| `review.md` | the orchestrating skill (`delivery-run` or `delivery-review`), in the format the `delivery-review` skill defines | Consolidated findings and what was fixed |
| `delivery-report.md` | the `delivery-run` skill | What the human reads at the ship gate, written after the plugin's pull-request template |
| `pull-request.md` | the ship stage | The pull-request body as it was sent: the report, in the template the person chose |

`state.json`:

```json
{
  "key": "PROJ-123",
  "source": "jira | file",
  "started_at": "2026-10-06T09:30:00Z",
  "base_branch": "main",
  "branch": "feature/PROJ-123-short-slug",
  "stage": "intake | scout | plan | acceptance-tests | implement | coverage | review | ship | done",
  "status": "active | held | stopped",
  "refined": true,
  "test_order": "before | mixed | after",
  "stages_done": ["intake", "scout"],
  "plan_approved": false,
  "fix_rounds": 0,
  "gate_rounds": { "plan": 0, "ship": 0 },
  "deltas": [{ "id": "delta-01", "at": "", "trigger": "ship gate | plan proved wrong | resumed with changes",
               "summary": "", "approved": false, "applied": false }],
  "external_context": { "contracts": "git:4f2a…:9c1e…" },
  "profile_notes": ["the coverage report is in build/reports/jacoco, not target/site"],
  "human_interventions": [{ "at": "", "stage": "plan", "kind": "approval | adjustment | fix | delta | question | takeover | coverage_accepted | hold | local | ship | cancel | stop", "note": "" }],
  "pr_url": ""
}
```

`gate_rounds` is explained under "Rounds at a gate", `deltas` in `deltas.md` and `profile_notes` (absent or empty most of the time) in `repo-profile.md`, both next to this file. `refined` says whether the ticket went through refinement in this run; a run started before refinement existed has no such key and is resumed as it is. `stage` is the stage to run next, using exactly the names above; they are also the values `--from` accepts. `status` is `held` when the run waits at the ship gate, `stopped` when a person cancelled or stopped it (the note of the last intervention says where and why), `active` otherwise.

Update `state.json` whenever a stage completes and whenever the human steps in, through `scripts/run_state.py` (`init`, `update`, `intake`, `show`), never by editing the file: one call per transition records every change of that transition and stamps the time. The same calls render `test-report.md` and `acceptance-tests.md` from the test engineer's JSON whenever it is newer (`run_state.py render` does only that, for a skill that keeps no `state.json`). Subagents are told not to write report or summary Markdown files, so the test engineer's results are data that a script turns into Markdown, not documents it writes. `human_interventions` is the pipeline's own record of where a person had to act; keep each note to one line. Its kinds are `approval`, `adjustment`, `fix`, `delta`, `question`, `takeover`, `coverage_accepted`, `hold`, `local`, `ship`, `cancel` and `stop`.

`.enabler/runs/`, `.enabler/repo-profile/`, `.enabler/tickets/` and `.enabler/sources/` hold working files and stay out of commits. `repo_profile.py check` sees to it without touching any file of the project: it puts a `.gitignore` containing `*` inside each of them. Do not add lines to the project's own `.gitignore` for them. A skill that writes a run directory without going through the scout stage runs `check` once for the same reason.

## Repository profile

In `repo-profile.md`, next to this file. How the repository is learned once and kept current: `repo_profile.py check`, its statuses, deltas when it is stale or when a stage learned something, and `--relearn`. Read it at the scout stage, and when a run has `profile_notes` to turn into deltas.

## External sources

In `external-sources.md`, next to this file. Other repositories, sibling folders and documents the project depends on: how they are added, learned, kept current and read. Read it only when the project has sources (`sources.py status` lists any) or the person adds one.

## Project configuration

Optional file `.enabler/config.json`. Like the rest of `.enabler/`, it is a local file: the plugin is used by one person on one machine for now, and nothing it writes has to be shared. Every key is optional; the defaults below apply when the file or a key is absent. Never ask the human for a value that has a default.

```json
{
  "gates": ["plan", "ship"],
  "max_gate_rounds": 3,
  "git": {
    "base_branch": null,
    "branch_pattern": "feature/{key}-{slug}",
    "commit_pattern": "{type}({key}): {summary}",
    "pull_request": true,
    "pr_template": "ask",
    "local_only": false
  },
  "jira": {
    "server": null,
    "comment_on_ship": true,
    "transition_on_ship": null
  },
  "tests": {
    "coverage_target": 80,
    "coverage_minimum": 70,
    "levels": ["unit", "integration"],
    "order": "auto",
    "full_suite_runs": 2,
    "mutation": { "enabled": true, "max_mutants": 40 }
  },
  "refine": {
    "enabled": true
  },
  "review": {
    "lenses": ["correctness", "security", "quality", "tests"],
    "select_lenses": true,
    "group_below_lines": 150,
    "sensitive_paths": [],
    "min_confidence": 80,
    "auto_fix": ["critical", "high"],
    "max_fix_rounds": 2
  }
}
```

- `gates` — where the pipeline stops for a human decision. `plan` is approval of the plan before any code is written; `ship` is approval before anything leaves the machine (push, pull request, Jira). An empty list runs unattended up to the ship stage, which then still requires an explicit `--ship` flag or the `delivery-ship` skill: nothing is pushed on the strength of a config file alone.
- `max_gate_rounds` — how many times a person can send the work back at one gate (`adjust` at the plan gate, `fix` at the ship gate) before the pipeline offers to hand over. Counted per gate, not per run. See "Rounds at a gate" below.
- `git.base_branch: null` — use the base branch `delivery-repo-scout` detected (the remote's default branch).
- `git.pr_template` — which template the pull-request body follows: `"ask"` (the ship stage asks once and offers to remember the answer), `"plugin"` (the one shipped with the plugin), `"repo"` (the repository's own), or the path of a file.
- `git.local_only` — `true` keeps everything on the machine, permanently: no push, no pull request, no Jira write. The same mode is switched on for a project when a person refuses the remote, through the marker file `.enabler/local-only`; see "When the person says no to the remote" in the safety rules. The plugin's hook enforces it.
- `jira.server: null` — use the only connected Jira MCP server. If several are connected, the orchestrating skill asks once, in its preflight, and passes the choice to the analyst.
- `jira.transition_on_ship` — the status to move the issue to once the pull request is open (for example `"In Review"`). `null` means do not transition.
- `tests.coverage_target` and `tests.coverage_minimum` — line and branch coverage of the changed code. The test engineer aims for the target (80); the minimum (70) is the lowest result the pipeline accepts on its own. At or above the target it is `met`. Between the minimum and the target it is `acceptable`: the run continues and the figure is reported. Below the minimum it is `below minimum`, and a person decides whether to proceed. See "Coverage" below.
- `tests.order` — `auto` writes the tests for the ticket's acceptance criteria before the code whenever the ticket states usable criteria, and falls back to writing tests after the code when it does not (see "Test order" below). `after` always writes them after the code. There is no setting that skips the coverage stage.
- `refine.enabled` — after intake, the ticket refiner closes the gaps in the definition before anything is planned (see "Ticket refinement" below). `false`, or `--no-refine` for one run, takes the ticket as written.
- `tests.full_suite_runs` — how many times the test engineer may run the whole suite in one coverage stage: once to surface regressions, once to measure. Default 2. In between it runs only the tests the change affects. When the repository profile says CI runs the whole suite on every merge request, it runs it once, whatever this allows. See "Effort budget" in the test engineer.
- `tests.mutation` — mutation testing, **on by default**: it is what shows whether the tests would notice a wrong decision. It is kept to the code the ticket changed that decides something (business rules, permissions, validations, calculations, security and privacy), each mutant runs against the feature's tests only, in one pass: about two per decision point changed (condition, comparison, branch, validation, boundary), at most `max_mutants` (40), and none when the change decides nothing. `enabled: false` turns it off for the project. See "Mutation testing" in the test engineer.
- `review.lenses` — the lenses a review may use. Within them, `scripts/review_scope.py` decides what each change needs.
- `review.select_lenses` — `true` leaves the security lens out when the change touches no external input, I/O, process execution, query, HTML rendering, authentication, secret, configuration, dependency or sensitive path; correctness, quality and tests always run. The review report says when security was left out and why. `false` runs every lens of `review.lenses` on every change.
- `review.group_below_lines` — under this many changed lines (150), two reviewers carry two lenses each (correctness with tests, security with quality) instead of one reviewer per lens. `0` always launches one per lens.
- `review.sensitive_paths` — path patterns (`src/billing/*`, `**/Payments/**`) whose change always brings the security lens, whatever is in it.
- `review.auto_fix` — severities `/ai-enabler:delivery-run` fixes on its own inside its fix loop. Everything else is reported and left for the human. The stand-alone `/ai-enabler:delivery-review` ignores this key: there it fixes only with `--fix` or when the person says so.

Command-line flags on a skill override the file for that run.

## Changing course after approval: deltas

In `deltas.md`, next to this file. When a change to an approved plan is a delta, its file format, and how it is approved and carried out. Read it only when a delta is needed or one is pending in `state.json`.

## Rounds at a gate

Each gate counts how many times the person has sent the work back: `adjust` (and a delta that is adjusted) at the plan gate, `fix` at the ship gate. The two counters are separate (`gate_rounds.plan`, `gate_rounds.ship`).

The first `max_gate_rounds` rounds at a gate (3 by default) run normally. When the person sends the work back once more — a fourth time, with the default — do not start that round on your own. Say that three rounds have already been made at this gate, summarise what changed in each, and offer the choice: take over by hand (the run stays resumable), go another round, or stop. The person decides; this is an offer, not a limit on them. Repeated rounds usually mean the ticket or the plan is unclear, and saying so is more useful than another attempt. `--max-rounds N` on `delivery-run` overrides `max_gate_rounds` for one run.

The automatic fix loop of the review is a different budget: `review.max_fix_rounds` applies to each review pass. `fix_rounds` in `state.json` counts the rounds of the current pass and goes back to 0 when a new pass starts — after a correction or a delta has changed the code.

## Ticket refinement

A ticket is usually clear about the happy path and silent about the rest. Refinement is the stage-1 step that closes those gaps before planning, the way a product owner and a business analyst would; what makes a ticket ready and how a gap is closed is defined once, in `ticket-readiness.md` next to this file.

- **In the pipeline** it runs right after the analyst, in `delivery-run` and `delivery-plan`. The refiner adds to `requirements.json` — every addition marked `"refined": true`, the verdicts on the ticket as it arrived kept under `as_received` — and writes `refinement.md`. The planner plans the refined ticket, and the plan gate lists what was added so the person can reject any of it.
- **On its own**, `/ai-enabler:delivery-ticket-refine <KEY | file>` writes the improved ticket as a Markdown file, and `/ai-enabler:delivery-ticket-create <a few sentences>` writes one from a short brief. Both go to `.enabler/tickets/`, a local folder kept out of git like the others, and the file is a source `delivery-plan` and `delivery-run` accept. A run from such a file is not refined a second time.
- **Nothing here writes to Jira.** The only exception is `delivery-ticket-create` creating one issue when the person chose that in the same run; see the safety rules.

Two things keep this honest. In a run without the plan gate nobody reviews the additions, so the delivery report and the ship gate say which criteria came from refinement. And what a person rejected at the plan gate stays rejected: it is kept in `requirements.json` marked `"removed_by": "plan-gate"`, is not in force for tests or review, and is not added again when intake is re-run with `--refresh`.

Refined criteria count as stated for the test order: once the plan is approved they are part of the definition, and their tests are written before the code.

## Tests: where they run, and when they fail

In `tests-protocol.md`, next to this file. Where tests run at each stage, what a brief to the test engineer may contain, and what is done with a test that does not pass. Read it when a stage's tests fail, or before briefing the test engineer outside `delivery-run`.

## Test order

Tests are written before the code so that they encode what the ticket asks for, not what the code happens to do. What the ticket offers, once refined, decides how far that can go — `acceptance_criteria_quality` in `requirements.json`:

| Criteria in the ticket | `test_order` | Before the code | After the code |
|---|---|---|---|
| `sufficient` | `before` | Tests for every stated criterion | Unit tests needed to reach the coverage target |
| `scarce` | `mixed` | Tests for the criteria that are stated | Tests for the requirements without a criterion, then coverage |
| `missing` | `after` | Nothing | All tests, derived from the requirements and the code, then coverage |

`test_order` is written to `state.json` by whichever skill runs the intake (`delivery-run` or `delivery-plan`). A skill that finds it missing derives it from `requirements.json` with this table before going on.

In every case the coverage stage runs after the code. With `tests.order: after` the first column is skipped whatever the ticket offers.

When tests had to be written after the code, the plan gate and the delivery report say so, with the reason: the reviewer should know those tests were not an independent statement of the requirement.

## Coverage

Coverage of the changed code (line and branch) is judged against two numbers: a **target of 80 %** and a **minimum of 70 %**. At or above the target it is `met`. Between the minimum and the target it is `acceptable`: the run continues and the figure is reported. Below the minimum it is `below minimum`, and a person decides whether to proceed.

| Coverage of the changed code | Verdict | What the pipeline does |
|---|---|---|
| ≥ 80 % (target) | `met` | Continues |
| 70 % to under 80 % | `acceptable` | Continues, and reports the figure and what is left uncovered at the ship gate and in the pull request |
| under 70 % (minimum) | `below minimum` | **Stops and asks the person**: proceed as it is, write more tests, or stop the run |
| no coverage tool in the project | `not measured` | Continues, says so at the ship gate; no coverage figure is claimed |

The stop below the minimum happens right after the coverage stage, before the review, and it applies even when no gates are configured: an unattended run does not carry a change under the minimum to a pull request on its own. A decision to proceed is recorded in `state.json` under `human_interventions` with kind `coverage_accepted` and the person's reason, and shown in the delivery report. That record is what the ship stage looks for.

## When there is no Jira MCP server

The pipeline needs to read the ticket. If no connected MCP server exposes a tool that fetches a Jira issue by key, say so and offer the two ways forward: connect one (see `docs/jira-mcp.md` in the marketplace repository; `/ai-enabler:delivery-doctor` checks the setup), or pass a Markdown file with the requirements instead of a key. Do not ask the human to paste credentials and do not call the Jira REST API directly.
