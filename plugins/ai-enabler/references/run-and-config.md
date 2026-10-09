# Run directory and project configuration

Shared by every `ai-enabler` skill. Read it once at the start of a skill.

## Run directory

Each ticket gets one directory, `.enabler/runs/<KEY>/`, where `<KEY>` is the Jira key (or, for a file source, the file name without extension). `source` in `state.json` says which: with `file` there is no Jira issue, so nothing is read from or written to Jira for that run. Stages talk to each other through these files, not through the conversation, which is what makes a run resumable and lets each subagent start with a clean context.

| File | Written by | Content |
|---|---|---|
| `state.json` | the orchestrating skill | Where the run is (see below) |
| `requirements.json` | `delivery-ticket-analyst`; the planner updates its acceptance criteria when a delta changes them | Normalised ticket and readiness verdict |
| `repo-context.md` | `delivery-repo-scout` | Only what this ticket adds to the repository profile: the existing code closest to it |
| `plan.md` | `delivery-solution-planner` | The implementation plan as it stands now: the approved plan with every approved delta folded in |
| `deltas/delta-NN.md` | `delivery-solution-planner` (delta mode) | One file per change made after the plan was approved: why, what is added, what is removed |
| `deltas/delta-NN.before/` | the orchestrating skill | Copies of `plan.md` and `requirements.json` taken before the planner writes delta NN, so the delta can be revised or cancelled |
| `acceptance-tests.md` | `delivery-test-engineer` (acceptance mode) | The tests written before the code, one row per acceptance criterion |
| `test-report.md` | `delivery-test-engineer` (coverage mode) | Suite result, coverage against the target and the minimum, acceptance-criteria table |
| `review.md` | the orchestrating skill (`delivery-run` or `delivery-review`), in the format the `delivery-review` skill defines | Consolidated findings and what was fixed |
| `delivery-report.md` | the `delivery-run` skill | What the human reads at the ship gate; becomes the PR body |

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
               "summary": "", "approved": false, "applied": false }],
  "profile_notes": ["the coverage report is in build/reports/jacoco, not target/site"],
  "human_interventions": [{ "at": "", "stage": "plan", "kind": "adjustment | fix | delta | question | takeover | coverage_accepted", "note": "" }],
  "pr_url": ""
}
```

`gate_rounds` and `deltas` are explained under "Rounds at a gate" and "Changing course after approval"; `profile_notes` (absent or empty most of the time) under "Repository profile". `stage` is the stage to run next, using exactly the names above; they are also the values `--from` accepts. `status` is `held` when the run waits at the ship gate, `stopped` when a person cancelled or stopped it (the note of the last intervention says where and why), `active` otherwise.

Update `state.json` whenever a stage completes and whenever the human steps in. `human_interventions` is the pipeline's own record of where a person had to act; keep each note to one line.

`.enabler/runs/` and `.enabler/repo-profile/` hold working files and stay out of commits. `repo_profile.py check` sees to it without touching any file of the project: it puts a `.gitignore` containing `*` inside each of the two folders. Do not add lines to the project's own `.gitignore` for them. A skill that writes a run directory without going through the scout stage runs `check` once for the same reason.

## Repository profile

A repository is learned once, not once per ticket. What the pipeline knows about it lives outside the runs, in `.enabler/repo-profile/`, and stays on this machine:

| File | Content |
|---|---|
| `profile.md` | What the repository is: stack, the commands that work here, structure, conventions, hard rules, git conventions. Written once by the scout, about 150 lines at most, and not rewritten by the pipeline afterwards |
| `deltas/delta-NNN-<slug>.md` | One small complement each: what changed, or what was learned. About 30 lines at most. A later delta overrides an earlier one and the profile |
| `profile.json`, `pending.json` | Fingerprints of the files the profile was derived from. Written by the script, never by an agent |

The profile grows by complements, never by rewriting: a document that is extended on every run becomes too long to read, and then it is skimmed and trusted less. The base says what the repository is; each delta says what is different now.

At the scout stage, ask the script whether the profile still holds — it compares a hash of each build manifest, CI and lint configuration file, the root README and the rules files (`CLAUDE.md`, `AGENTS.md`, contribution guides, ADRs) with what it recorded; lock files and source code are not watched:

```
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repo_profile.py" check
```

It prints JSON. `root` is the folder whose `.enabler/` is in use, and `profile` the absolute path of `profile.md`; the run directories belong under the same `root`. Pass the scout the absolute paths the script prints, never a relative one.

| `status` | Meaning | Scout `tasks` | Then |
|---|---|---|---|
| `missing` | The repository has not been learned yet | `profile`, `ticket` | `record --expect <profile path>` |
| `unrecorded` | There is a `profile.md` but no usable fingerprints: written or restored by hand | `ticket` | `record`. Never overwrite that profile |
| `fresh` | Nothing the profile was derived from has changed | `ticket` | — |
| `stale` | Some watched files changed, appeared or disappeared (the script lists them) | `delta`, `ticket` | see below |

**When the profile is stale.** Get the delta's path with `repo_profile.py next-delta "<a few words on what changed>"` (they only become a file name: two or three nouns such as `"test runner"`, not a sentence and not the name of a command) and pass it to the scout with the files the check listed. The scout answers one of two things:

- it wrote the delta — run `repo_profile.py record --expect <delta path>`. The script refuses if that file is not there, so a change is never marked as seen with nothing describing it;
- nothing the profile or its deltas say is affected (a dependency bump, a reformat) and it wrote no file — run `repo_profile.py record`. No empty delta is kept.

`record` stores the files as they were when `check` saw them, so a watched file edited in the meantime is found by the next check instead of being swallowed.

**When something was learned.** A later stage may report that the profile was wrong or incomplete: a command that does not work here, a convention the code does not follow, a rule nobody had written down. Append it at once to `profile_notes` in `state.json`, one line each, so it survives a resume. At the next pause — a gate, or the end of the run, never the middle of a stage — and for each note: `next-delta`, launch the scout with the task `delta` and the note as its `learned` reason, `record --expect <delta path> --keep`, and remove the note from `state.json`. `--keep` leaves the fingerprints alone: a learned delta says nothing about which files changed.

**Starting again: `--relearn`.** Run `repo_profile.py reset` and treat the profile as `missing`: the repository is studied from scratch and every delta is dropped, learned ones included, so the scout reads the old profile and deltas *before* the reset and carries over what still holds. Never do it unasked. Suggest it, once, when `suggest_relearn` in the check is not empty (the profile has outgrown its size, there are more than ten deltas, or deltas run long), or when the scout says the profile and its deltas no longer fit together. `--refresh` does not touch the profile: it re-runs the stages of one ticket.

The person may correct `profile.md` or add a delta by hand; the pipeline itself never edits what is written. Nothing in `.enabler/repo-profile/` is committed, and none of it is copied into `CLAUDE.md`, `AGENTS.md` or any other project file.

**A run started before the profile existed** has a `repo-context.md` that holds everything, written by an earlier version. On resume, run `check` like any other run (Step 2), but do not ask for the `ticket` task: keep that file as it is. Agents read the profile, the deltas and it together.

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

- `gates` — where the pipeline stops for a human decision. `plan` is approval of the plan before any code is written; `ship` is approval before anything leaves the machine (push, pull request, Jira). An empty list runs unattended up to the ship stage, which then still requires an explicit `--ship` flag or the `delivery-ship` skill: nothing is pushed on the strength of a config file alone.
- `max_gate_rounds` — how many times a person can send the work back at one gate (`adjust` at the plan gate, `fix` at the ship gate) before the pipeline offers to hand over. Counted per gate, not per run. See "Rounds at a gate" below.
- `git.base_branch: null` — use the base branch `delivery-repo-scout` detected (the remote's default branch).
- `git.local_only` — `true` keeps everything on the machine, permanently: no push, no pull request, no Jira write. The same mode is switched on for a project when a person refuses the remote, through the marker file `.enabler/local-only`; see "When the person says no to the remote" in the safety rules. The plugin's hook enforces it.
- `jira.server: null` — use the only connected Jira MCP server. If several are connected, the orchestrating skill asks once, in its preflight, and passes the choice to the analyst.
- `jira.transition_on_ship` — the status to move the issue to once the pull request is open (for example `"In Review"`). `null` means do not transition.
- `tests.coverage_target` and `tests.coverage_minimum` — line and branch coverage of the changed code. The test engineer aims for the target (80); the minimum (70) is the lowest result the pipeline accepts on its own. At or above the target it is `met`. Between the minimum and the target it is `acceptable`: the run continues and the figure is reported. Below the minimum it is `below minimum`, and a person decides whether to proceed. See "Coverage" below.
- `tests.order` — `auto` writes the tests for the ticket's acceptance criteria before the code whenever the ticket states usable criteria, and falls back to writing tests after the code when it does not (see "Test order" below). `after` always writes them after the code. There is no setting that skips the coverage stage.
- `review.auto_fix` — severities `/ai-enabler:delivery-run` fixes on its own inside its fix loop. Everything else is reported and left for the human. The stand-alone `/ai-enabler:delivery-review` ignores this key: there it fixes only with `--fix` or when the person says so.

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

1. **Safety copy.** Before the planner runs, the orchestrating skill copies `plan.md` and `requirements.json` into `deltas/delta-NN.before/`. The planner is about to overwrite both, and the run directory is not under version control, so this copy is the only way back.
2. **Plan.** The planner, in `delta` mode, writes `deltas/delta-NN.md`, updates `plan.md` so that it describes the work as it now stands (with a "Change history" table at the top, one row per delta), and updates the acceptance criteria in `requirements.json`: new ones get new ids, a removed one is kept and marked `"removed_by": "delta-NN"`, ids are never reused. The skill records the delta in `state.json` with `approved: false`, `applied: false`.
3. **Approval.** The delta is shown at the plan gate, in the same compact form as a plan, and needs the same approval — **always**, whatever `gates` says: an unattended run does not approve a change of scope by itself. No test or code changes before that.
   - *adjust* — restore the two files from `delta-NN.before/` and relaunch the planner in delta mode with the feedback; it rewrites the same `delta-NN.md`, it does not open a new number.
   - *cancel* — restore the two files from `delta-NN.before/`, delete `delta-NN.md` and the `.before` folder, and remove the delta from `state.json`. The run is back where it was.
   - *approve* — set `approved: true` and set `stage` to `acceptance-tests`.
4. **Acceptance tests.** The test engineer, in `acceptance` mode with the delta, writes the tests for added and changed criteria and removes the tests the delta lists as obsolete — those and no others — then updates `acceptance-tests.md` (creating it if the run had none). This step runs even when the run's `test_order` was `after` because the ticket stated no criteria: the criteria of a delta come from a person's request, so they can be tested first. It is skipped only when `tests.order: after` is configured.
5. **Implementation.** The implementer makes the new tests pass and deletes the code the delta lists for deletion. When it returns, set `applied: true`.
6. **Coverage, then review** of the lenses the change touches, and back to the ship gate.

A delta that is approved but not applied is unfinished work. Any skill that resumes a run looks for one first and carries it out before anything else; a delta that is written but not approved is shown at its gate again.

**Removed criteria are not in force.** A criterion marked `removed_by` is kept for the record only: no test is written for it, the review does not count it as unmet, and totals such as "criteria met" leave it out. A test removal that a delta lists is not a "deleted test" finding.

`state.json` records each delta. The delivery report lists them under "Changes after the plan was approved", so the pull request shows not only the result but how it got there.

## Rounds at a gate

Each gate counts how many times the person has sent the work back: `adjust` (and a delta that is adjusted) at the plan gate, `fix` at the ship gate. The two counters are separate (`gate_rounds.plan`, `gate_rounds.ship`).

The first `max_gate_rounds` rounds at a gate (3 by default) run normally. When the person sends the work back once more — a fourth time, with the default — do not start that round on your own. Say that three rounds have already been made at this gate, summarise what changed in each, and offer the choice: take over by hand (the run stays resumable), go another round, or stop. The person decides; this is an offer, not a limit on them. Repeated rounds usually mean the ticket or the plan is unclear, and saying so is more useful than another attempt. `--max-rounds N` on `delivery-run` overrides `max_gate_rounds` for one run.

The automatic fix loop of the review is a different budget: `review.max_fix_rounds` applies to each review pass. `fix_rounds` in `state.json` counts the rounds of the current pass and goes back to 0 when a new pass starts — after a correction or a delta has changed the code.

## Test order

Tests are written before the code so that they encode what the ticket asks for, not what the code happens to do. What the ticket offers decides how far that can go — `acceptance_criteria_quality` in `requirements.json`:

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
