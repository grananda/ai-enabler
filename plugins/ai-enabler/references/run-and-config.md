# Run directory and project configuration

Shared by every `ai-enabler` skill. Read it once at the start of a skill.

## Run directory

Each ticket gets one directory, `.enabler/runs/<KEY>/`, where `<KEY>` is the Jira key (or, for a file source, the file name without extension). `source` in `state.json` says which: with `file` there is no Jira issue, so nothing is read from or written to Jira for that run. Stages talk to each other through these files, not through the conversation, which is what makes a run resumable and lets each subagent start with a clean context.

| File | Written by | Content |
|---|---|---|
| `state.json` | the orchestrating skill | Where the run is (see below) |
| `requirements.json` | `ticket-analyst` | Normalised ticket and readiness verdict |
| `repo-context.md` | `repo-scout` | Stack, commands, conventions, hard rules |
| `plan.md` | `solution-planner` | The implementation plan as it stands now: the approved plan with every approved delta folded in |
| `deltas/delta-NN.md` | `solution-planner` (delta mode) | One file per change made after the plan was approved: why, what is added, what is removed |
| `acceptance-tests.md` | `test-engineer` (acceptance mode) | The tests written before the code, one row per acceptance criterion |
| `test-report.md` | `test-engineer` (coverage mode) | Suite result, coverage against the target and the minimum, acceptance-criteria table |
| `review.md` | the orchestrating skill (`deliver` or `review`), in the format the review skill defines | Consolidated findings and what was fixed |
| `delivery-report.md` | the deliver skill | What the human reads at the ship gate; becomes the PR body |

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
  "test_order": "before | mixed | after",
  "stages_done": ["intake", "scout"],
  "plan_approved": false,
  "fix_rounds": 0,
  "gate_rounds": { "plan": 0, "ship": 0 },
  "deltas": [{ "id": "delta-01", "at": "", "trigger": "ship gate | plan proved wrong | resumed with changes",
               "summary": "", "approved": true }],
  "human_interventions": [{ "at": "", "stage": "plan", "kind": "adjustment | question | takeover | coverage_accepted", "note": "" }],
  "pr_url": ""
}
```

`gate_rounds` and `deltas` are explained under "Rounds at a gate" and "Changing course after approval". `stage` is the stage to run next, using exactly the names above; they are also the values `--from` accepts. `status` is `held` when the run waits at the ship gate, `stopped` when a person cancelled or stopped it (the note of the last intervention says where and why), `active` otherwise.

Update `state.json` whenever a stage completes and whenever the human steps in. `human_interventions` is the pipeline's own record of where a person had to act; keep each note to one line.

`.enabler/runs/` holds working files and must stay out of commits. If `.gitignore` does not already exclude it, add the line `.enabler/runs/` before the first commit of a run and say that you did.

## Project configuration

Optional file `.enabler/config.json`, committed with the project. Every key is optional; the defaults below apply when the file or a key is absent. Never ask the human for a value that has a default.

```json
{
  "gates": ["plan", "ship"],
  "max_gate_rounds": 3,
  "git": {
    "base_branch": null,
    "branch_pattern": "feature/{key}-{slug}",
    "commit_pattern": "{type}({key}): {summary}",
    "pull_request": true,
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
    "order": "auto"
  },
  "review": {
    "lenses": ["correctness", "security", "quality", "tests"],
    "min_confidence": 80,
    "auto_fix": ["critical", "high"],
    "max_fix_rounds": 2
  }
}
```

- `gates` — where the pipeline stops for a human decision. `plan` is approval of the plan before any code is written; `ship` is approval before anything leaves the machine (push, pull request, Jira). An empty list runs unattended up to the ship stage, which then still requires an explicit `--ship` flag or the `ship` skill: nothing is pushed on the strength of a config file alone.
- `max_gate_rounds` — how many times a person can send the work back at one gate (`adjust` at the plan gate, `fix` at the ship gate) before the pipeline offers to hand over. Counted per gate, not per run. See "Rounds at a gate" below.
- `git.base_branch: null` — use the base branch `repo-scout` detected (the remote's default branch).
- `git.local_only` — `true` keeps everything on the machine, permanently: no push, no pull request, no Jira write. The same mode is switched on for a project when a person refuses the remote, through the marker file `.enabler/local-only`; see "When the person says no to the remote" in the safety rules. The plugin's hook enforces it.
- `jira.server: null` — use the only connected Jira MCP server. If several are connected, the orchestrating skill asks once, in its preflight, and passes the choice to the analyst.
- `jira.transition_on_ship` — the status to move the issue to once the pull request is open (for example `"In Review"`). `null` means do not transition.
- `tests.coverage_target` and `tests.coverage_minimum` — line and branch coverage of the changed code. The test engineer aims for the target (80); the minimum (70) is the lowest result the pipeline accepts on its own. At or above the target it is `met`. Between the minimum and the target it is `acceptable`: the run continues and the figure is reported. Below the minimum it is `below minimum`, and a person decides whether to proceed. See "Coverage" below.
- `tests.order` — `auto` writes the tests for the ticket's acceptance criteria before the code whenever the ticket states usable criteria, and falls back to writing tests after the code when it does not (see "Test order" below). `after` always writes them after the code. There is no setting that skips the coverage stage.
- `review.auto_fix` — severities `/ai-enabler:deliver` fixes on its own inside its fix loop. Everything else is reported and left for the human. The stand-alone `/ai-enabler:review` ignores this key: there it fixes only with `--fix` or when the person says so.

Command-line flags on a skill override the file for that run.

## Changing course after approval: deltas

Once a plan is approved, it is not rewritten quietly. A change to what is being built — to the scope, the behaviour or the acceptance criteria — is made as a **delta**: a small, approved change to the plan that says what is added and what is removed, and is carried out in the same order as the original work.

A delta is needed when:

- the person asks at the ship gate for something that changes behaviour, scope or acceptance criteria;
- the implementer stops because the plan is wrong in a way that changes scope;
- a run is resumed and the ticket, or the person's instructions, have changed.

A delta is **not** needed for a correction that leaves the plan true: a bug in the implementation, a naming or style point, a review finding. Those are fix lists for the implementer.

What a delta is, on disk — `deltas/delta-NN.md`, numbered from 01:

```markdown
# Delta NN — <KEY>: <what changes, in one line>

**Trigger:** who asked for it or what revealed it, and when.
**Why:** the reason, in two or three sentences.

## Acceptance criteria
| AC | Change (added / changed / removed) | Before | After |

## Tests
| Test | Action (add / change / remove) | File | Covers | Why |

## Code
| File | Action (create / modify / delete) | What |

## Plan steps affected
Which steps of plan.md change, are added, or are dropped.

## Risks and impact
```

Both sides are always written down: what the delta adds and what it takes away. A test that no longer describes wanted behaviour is listed under "remove"; so is code that the new approach makes dead. Nothing is deleted that the delta does not name.

How a delta is carried out — the same order as the pipeline, acceptance criteria first:

1. **Plan.** The planner, in `delta` mode, writes `deltas/delta-NN.md`, updates `plan.md` so that it describes the work as it now stands (with a "Change history" table at the top, one row per delta), and updates the acceptance criteria in `requirements.json`: new ones get new ids, a removed one is kept and marked `"removed_by": "delta-NN"`, ids are never reused.
2. **Approval.** The delta is shown at the plan gate, in the same compact form as a plan, and needs the same approval. No test or code changes before that.
3. **Acceptance tests.** The test engineer, in `acceptance` mode with the delta, writes the tests for added and changed criteria and removes the tests the delta lists as obsolete — those and no others — then updates `acceptance-tests.md`.
4. **Implementation.** The implementer makes the new tests pass and deletes the code the delta lists for deletion.
5. **Coverage, then review** of the lenses the change touches, and back to the ship gate.

`state.json` records each delta. The delivery report lists them under "Changes after the plan was approved", so the pull request shows not only the result but how it got there.

## Rounds at a gate

Each gate counts how many times the person has sent the work back: `adjust` (and a delta that is adjusted) at the plan gate, `fix` at the ship gate. The two counters are separate (`gate_rounds.plan`, `gate_rounds.ship`).

When a counter reaches `max_gate_rounds` (3 by default), do not start another round on your own. Say that this is the third time round, summarise what has changed each time, and offer the choice: take over by hand (the run stays resumable), continue with another round, or stop. The person decides; this is an offer, not a limit on them. Repeated rounds usually mean the ticket or the plan is unclear, and saying so is more useful than a fourth attempt.

## Test order

Tests are written before the code so that they encode what the ticket asks for, not what the code happens to do. What the ticket offers decides how far that can go — `acceptance_criteria_quality` in `requirements.json`:

| Criteria in the ticket | `test_order` | Before the code | After the code |
|---|---|---|---|
| `sufficient` | `before` | Tests for every stated criterion | Unit tests needed to reach the coverage target |
| `scarce` | `mixed` | Tests for the criteria that are stated | Tests for the requirements without a criterion, then coverage |
| `missing` | `after` | Nothing | All tests, derived from the requirements and the code, then coverage |

`test_order` is written to `state.json` by whichever skill runs the intake (`deliver` or `plan`). A skill that finds it missing derives it from `requirements.json` with this table before going on.

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

The pipeline needs to read the ticket. If no connected MCP server exposes a tool that fetches a Jira issue by key, say so and offer the two ways forward: connect one (see `docs/jira-mcp.md` in the marketplace repository; `/ai-enabler:doctor` checks the setup), or pass a Markdown file with the requirements instead of a key. Do not ask the human to paste credentials and do not call the Jira REST API directly.
