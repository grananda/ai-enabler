---
name: delivery-run
description: "Machine-driven delivery of a Jira ticket, end to end. Reads the ticket through the Jira MCP server, analyses the repository, plans, implements, tests, reviews and fixes with dedicated subagents, then opens a pull request and updates Jira. The human decides at two gates — the plan and the ship — and is asked again only when a decision is theirs to make: a ticket that cannot be implemented as written, a change to the approved plan, coverage below the minimum. Use when the user says \"deliver PROJ-123\", \"implement this ticket\", \"take this Jira issue to a PR\", \"from Jira to code\", \"work on PROJ-123\", or passes a Jira key or a requirements Markdown file and wants the work done rather than advice. Also resumes an interrupted run for the same key."
argument-hint: "<JIRA-KEY | requirements.md> [--gates plan,ship|plan|ship|none] [--lane S|M|L] [--max-rounds 3] [--ship] [--local] [--context <url|path>] [--no-refine] [--refresh] [--relearn] [--from intake|scout|plan|acceptance-tests|implement|coverage|review|ship]"
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.5.2"
---

# ai-enabler:delivery-run — from a Jira ticket to a pull request

You are the orchestrator of the delivery pipeline. The machine does the work; the human decides at the two gates and at the few other points listed under "Rules for the orchestrator". Your job is to move the ticket through the stages, hand each stage to the right subagent with a precise brief, check what comes back, and stop only where a human decision is genuinely needed.

Before anything else, read these two files and follow them throughout:

- `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md` — the run directory, `state.json`, and `.enabler/config.json` with its defaults. It points to four more references, each read only when a step below says so: `repo-profile.md`, `external-sources.md`, `deltas.md` and `tests-protocol.md`.
- `${CLAUDE_PLUGIN_ROOT}/references/git-and-jira-safety.md` — the rules for every git and Jira action.

## The pipeline

| # | Stage | Who | Produces | Gate |
|---|---|---|---|---|
| 1 | intake | `ai-enabler:delivery-ticket-analyst`, then `ai-enabler:delivery-ticket-refiner` | `requirements.json`, strengthened by refinement, and `refinement.md` | only if the ticket is blocked |
| 2 | scout | `ai-enabler:delivery-repo-scout`, and `ai-enabler:delivery-source-scout` in parallel when the project has external sources (it learns the sources during intake) | the repository profile (once) or a delta to it, and `repo-context.md` for this ticket | — |
| 3 | plan | `ai-enabler:delivery-solution-planner` | `plan.md` | **plan** |
| 4 | acceptance-tests | `ai-enabler:delivery-test-engineer` (`acceptance`) | tests for the ticket's criteria, `acceptance-tests.json` (rendered as `acceptance-tests.md`) | — |
| 5 | implement | `ai-enabler:delivery-code-implementer` | code on a feature branch that makes those tests pass | — |
| 6 | coverage | `ai-enabler:delivery-test-engineer` (`coverage`), and beside it, when the review has one reviewer per lens, the correctness, security and quality reviewers | remaining tests, coverage (target 80 %, minimum 70 %), `test-report.json` (rendered as `test-report.md`) | only if coverage is below the minimum |
| 7 | review | `ai-enabler:delivery-code-reviewer`, one instance per lens or group of lenses the change needs, in parallel — only the tests lens when the others ran in stage 6 | `review-pack.md`, `review.md` | — |
| 8 | ship | this skill, following `ai-enabler:delivery-ship` | commit, push, PR, Jira update | **ship** |

Tests come before the code. A test written from the ticket says what the code must do; a test written from the code only confirms what it already does, errors included. Stage 4 therefore runs whenever the ticket states acceptance criteria worth testing against, and the ticket decides how much it can cover — read "Test order" in the run-and-config reference. Stage 6 always runs, whatever the order: it aims at 80 % coverage of the changed code, accepts 70 % or more, and below that hands the decision to the person ("Coverage" in the same reference).

The stages run forward, but a person can send the work back at either gate, and the plan can prove wrong on the way. Those loops are part of the pipeline, not exceptions to it — see "Going back: adjustments, fixes and deltas" below.

Why subagents: each stage reads a lot (the ticket and its links, the repository, the full diff) and only its conclusion matters to the next one. Running stages in their own context keeps yours small enough to steer a long run, and makes the reviewer independent of the code's author. Stages exchange files in the run directory, never long pasted text. What is true of the repository whatever the ticket is kept apart, in the repository profile, so it is learned once.

## Step 0 — Preflight

1. Parse `$ARGUMENTS`: a Jira key (`[A-Z][A-Z0-9]+-\d+`) or a path to a `.md`/`.txt` file, plus flags. With no source, ask for one. A file source means there is no Jira issue: set `source` to `file`, and nothing is read from or written to Jira in this run.
2. Load `.enabler/config.json` if present and apply the defaults for everything else. Flags override it.
3. For a Jira key, find the connected Jira MCP server. With none, follow "When there is no Jira MCP server" in the reference. With several and no `jira.server` configured, ask once which to use.
4. Confirm you are in a git repository with a clean enough working tree (see the safety rules). A repository is required; a remote is only required at the ship stage.
5. Run `/bin/bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/run_state.py" init .enabler/runs/<KEY> --key <KEY> --source jira|file --base <base branch>`. It creates the run directory and `state.json`, or, when they exist, leaves them as they are and says `"resumed": true`. On a **resume**, report the stage it stopped at and continue from there, reusing the files already written. Look at `deltas` first: one that is written but not approved goes back to its gate, and one that is approved but not applied is carried out before anything else ("Going back", situation 3). A run that `/ai-enabler:delivery-plan` started is resumed the same way; if `test_order` or `settings` is missing from its state (a run started by an earlier version, or by `delivery-plan`), `run_state.py intake` derives them. `--from <stage>` restarts from an earlier stage; `--refresh` re-runs intake and scout even if their files exist; `--relearn` also studies the repository again from scratch ("Repository profile" in the reference). A run with `profile_notes` left in its state turns them into deltas first. A run whose `repo-context.md` was written before the repository profile existed keeps that file: at Step 2 run the check as usual, without the `ticket` task.
6. **Bookkeeping goes through the script.** Every change to `state.json` in this skill — a stage done, a value set, a counter added to, an intervention recorded, a profile note — is one call to `run_state.py update .enabler/runs/<KEY>` with all of that transition's changes together (`--done <stage>`, `--set path=value`, `--add gate_rounds.plan=1`, `--intervene <kind> "<note>"`, `--note`, `--status`). It stamps the time and prints the state back. Never edit, write or reread `state.json` yourself.
7. Check for local-only mode ("When the person says no to the remote" in the safety rules): `.enabler/local-only` exists, `git.local_only` is true, or `--local` was passed (then write the marker now). In that mode the run goes all the way to a local result and never further; say so once at the start. If the person says at any later point that nothing should be uploaded, apply the same rule on the spot.
8. **External sources** — other repositories, sibling folders or documents the work depends on. Run `/bin/bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/sources.py" status`. When it lists sources, when `asked` is false and a person is there (`gates` is not empty), or when `--context` was passed, read `external-sources.md` next to this file and follow it here and at Steps 1 and 2. Otherwise the project has none and was already asked: skip everything about sources in this run.

Print one line per stage as you go (`[2/8] scout — analysing repository conventions`). Do not narrate beyond that; the human is not watching every step.

## Step 1 — Intake

Launch `ai-enabler:delivery-ticket-analyst` with the source and the run directory. For a Jira key, tell it which Jira MCP server to use (the one found in preflight).

**When the project has sources**, learn them in parallel with the analyst, as `external-sources.md` says, and wait for that before refining: the refiner reads the source profiles.

**The lane.** Once the analyst has written `requirements.json`, run `run_state.py intake .enabler/runs/<KEY>`, adding `--lane`, `--gates` and `--no-refine` when they were passed and `--order after` when `tests.order` is `after`. Besides the verdicts it prints the **lane** — `S`, `M` or `L`, from the analyst's `size` and `risk_areas`: any risk area makes a ticket at least `M`, authentication, permissions or personal data make it `L` — and the **settings** that lane gives this run: `gates`, `refine`, `review.select_lenses`, `review.group_below_lines`, `tests.full_suite_runs` and `tests.mutation`. It records both in `state.json`. **From here on use those settings, not the configuration file**, wherever this skill names one of those keys: the script has already applied the configuration and the flags to them ("Lanes" in the run-and-config reference). A small ticket then gets a lighter run — no plan gate (the plan is shown at the ship gate instead), refinement only when the analyst found gaps, two reviewers, one whole-suite run, fewer mutants — and a risky one the full treatment.

**Refine** when the intake says `needs_refinement`. A ticket is usually clear about the happy path and silent about the rest, and the machine implements exactly what the definition says. So launch `ai-enabler:delivery-ticket-refiner` with `mode: pipeline` and the run directory. It closes the gaps in the definition — each as a marked addition, an assumption or a question — updates `requirements.json` and writes `refinement.md`. Record `"refined": true` in `state.json`. Skip this step, and record `"refined": false`, when the intake says `needs_refinement: false` — `--no-refine`, `refine.enabled` false, or an `S` ticket the analyst found ready with sufficient criteria and no open question — or when:

- the source is a file that was already refined (`source.refined` is true in `requirements.json`: it came from `/ai-enabler:delivery-ticket-refine` or `/ai-enabler:delivery-ticket-create`);
- the run is resumed and intake was already done: `requirements.json` is reused as it is, with whatever refinement and plan-gate rejections it holds.

When intake is run again on purpose (`--refresh`, or `--from intake`), the analyst rewrites `requirements.json` from the source, so refinement runs again too. Before the analyst starts, note the text of every item marked `"removed_by": "plan-gate"` and delete `refinement.md`; pass those texts to the refiner as `rejected`, so that what the person turned down does not come back.

If the refiner fails, go on with the analyst's `requirements.json` and say so in the final report: refinement improves a ticket, it is not a condition for delivering it.

Then run `run_state.py intake` again, with the same flags, instead of reading `requirements.json`: it prints the verdicts after refinement, the lane again (refinement may have raised it), the counts, the blocking questions in full, and `test_order`, which it records — `sufficient` → `before`, `scarce` → `mixed`, `missing` → `after`, as the "Test order" table in the reference says. Then act on `readiness`:

- `ready` — continue.
- `ready_with_assumptions` — continue; the assumptions will be shown at the plan gate.
- `blocked` — stop the pipeline here. Run `run_state.py gate .enabler/runs/<KEY> blocked`, then show **all** the blocking questions in one message, numbered, each with the options and the suggestion the refiner gave when there are any, so that the person answers them together, and ask the human to answer them, or to confirm you should proceed on stated assumptions. Record the intervention in `state.json`. If they answer, add the answers to `requirements.json` (as requirements or assumptions) and continue. Offer to post the questions as a Jira comment only if they ask for it.

If no Jira MCP server is connected, follow "When there is no Jira MCP server" in the run-and-config reference.

## Step 2 — Scout

The repository is learned once and then only kept up to date; read `${CLAUDE_PLUGIN_ROOT}/references/repo-profile.md` and follow it.

1. Ask whether the profile still holds: `/bin/bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/repo_profile.py" check`. It prints `root` and the absolute path of the profile; the run directory lives under the same `root`. With `--relearn`, have the scout read the existing profile and deltas, run `repo_profile.py reset`, and go on as `missing`.
2. Launch `ai-enabler:delivery-repo-scout` once, with the tasks the status calls for and absolute paths:
   - `missing` — `profile` and `ticket`, then `repo_profile.py record --expect <profile path>`;
   - `unrecorded` — `ticket`, then `repo_profile.py record`. The profile that is there was written by hand: it is adopted, never overwritten;
   - `fresh` — `ticket` only;
   - `stale` — `delta` and `ticket`. Get the delta's path with `repo_profile.py next-delta "<what changed>"` and pass it with the `summary` lines of the check — never the full `changed`, `added` and `removed` lists, which after a large merge run to hundreds of paths. If the scout wrote the delta, `repo_profile.py record --expect <delta path>`; if it reports that nothing in the profile is affected and wrote no file, `repo_profile.py record`.

   The `ticket` task always gets the run directory and the path to `requirements.json`, and the `provisional` list of the check when it is not empty.
3. Read the warnings the scout returns: no test command, no coverage tool or a dirty tree change how later stages behave, and belong in the final report. If `suggest_relearn` in the check is not empty, or the scout says the profile and its deltas no longer fit together, mention once that `--relearn` would rebuild it; do not do it unasked.

**When the project has sources**, the source scout runs in the same message as the repository scout, and `external-context.md` is kept current before each later stage, as `external-sources.md` says.

Stages 1 and 2 need nothing from the human. When the source is a file, or the ticket is plainly ready, you may start the scout as soon as intake has written `requirements.json`.

When a later stage reports that the profile was wrong or incomplete — the implementer's build command failed because the profile named the wrong one, the test engineer found the coverage report elsewhere, a reviewer cited a rule the profile did not have — append one line to `profile_notes` in `state.json` straight away; when the finding is about an external source rather than the project, start the line with `source <name>: `. At the next gate, or at the end of the run, turn each note into a delta: `repo_profile.py next-delta "<a few words>"`, the scout with the task `delta` and the note as its `learned` reason, `repo_profile.py record --expect <delta path> --keep`, and remove the note. A note that starts with `source <name>: ` becomes a delta of that source instead: `sources.py next-delta <name> "<a few words>"`, `ai-enabler:delivery-source-scout` with the task `delta` and the note as the reason, `sources.py record <name> --expect <delta path> --keep`. A profile is never edited; it is complemented.

## Step 3 — Plan, and the plan gate

Launch `ai-enabler:delivery-solution-planner` with the run directory and `test_order`. It returns the plan gate ready to show; do not read `plan.md` to build it.

If `plan` is in `gates`, run `run_state.py gate .enabler/runs/<KEY> plan` (it records that the run waits, so a notification can reach a person who stepped away), then show the block the planner returned — compact, because the human should be able to decide in two minutes — add the lane in one line — `Lane        : <S|M|L> (size <size>; risks: <risk areas, or none>) — adjust: lane S|M|L to change it`, and, when the person chose a lane below the one the risk areas call for, say so in the same line — and, when `refinement.md` exists, `What was added to the ticket, and why: .enabler/runs/<KEY>/refinement.md`, end with `Approve this plan? (approve / adjust: <what to change> / cancel)`, and wait. Read `plan.md`, or the part of it the person asks about, only when they ask about a step, or when the planner's block is missing one of its lines (Approach, Changes, Criteria, Tests, Decisions, Refinement, Sources, Assumptions, Questions).

This gate is the review of the change before it exists: what will be built, in which files, with which tests. The person can ask about any step, read or edit `plan.md` directly, and adjust as often as the round limit allows; nothing has been written outside the run directory yet. After approval the plan only changes through a delta.

- **approve** — `run_state.py update` with `--done plan --set plan_approved=true --intervene approval "<one line>"`, and continue.
- **adjust: lane S|M|L** — not a round and no new plan: run `run_state.py intake --lane <lane>` and use its settings for the stages still to come; when the new lane is below the one the risk areas call for, say so once and go on, it is the person's call. Show the gate again with the new lane.
- **adjust** — the plan is not approved yet, so it is simply revised. Check "Rounds at a gate" in the reference first (`--max-rounds` overrides the limit for this run); then relaunch the planner with the feedback, record the intervention, add one to `gate_rounds.plan`, and present the new plan.
- **adjust that rejects something refinement added** ("drop AC-7", "no pagination") — the same round, with one more thing to do first: in `requirements.json`, mark each rejected requirement or criterion `"removed_by": "plan-gate"` (never delete or renumber) — a rejected requirement takes with it the criteria that cover only that requirement — and pass the rejection to the planner as feedback. If no refined criterion is left in force and `as_received` exists, set `acceptance_criteria_quality` and `test_order` again from `as_received.acceptance_criteria_quality`.
- **cancel** — set `status` to `stopped`, leave the run directory in place, and stop. Nothing was written outside the run directory, so there is nothing to undo.

A plan with a blocking question cannot be auto-approved: even when `plan` is not in `gates`, stop and ask.

When `plan` is not in `gates`, what refinement added goes in unreviewed. That is the choice the person made by removing the gate — or the lane made for a small ticket — but it must stay visible: the delivery report and the ship gate say which criteria came from refinement and that nobody approved them. In that case record `plan_approved` without an intervention, keep the planner's `Approach` and `Changes` lines to show above the ship gate, and go on.

## Step 4 — Acceptance tests, before the code

Stages 4 to 7 all run tests. Where they run, what a brief to the test engineer may contain, and what is done with a test that runs and does not pass, is one protocol for all of them, in `${CLAUDE_PLUGIN_ROOT}/references/tests-protocol.md`. The steps below apply it; read that file when a test fails for a reason the steps do not settle. A brief to the test engineer carries the configuration values and the scope only.

1. Create the feature branch from the base branch, per the safety rules and `git.branch_pattern`. Record it in `state.json`.
2. If `test_order` is `before` or `mixed`, launch `ai-enabler:delivery-test-engineer` with `mode: acceptance` and the run directory. It writes the tests for the criteria the ticket states and `acceptance-tests.json` (your next `run_state.py update` renders `acceptance-tests.md` from it); no production code exists yet, so the tests are expected to fail or not to build.
3. Read what it returns. A criterion it could not turn into a test without guessing is not a reason to stop: it moves to the after-code stage and is named in the delivery report.
4. If `test_order` is `after`, the branch is still created but no tests are written yet: skip items 2 and 3 and say so in one line, with the reason (the ticket states no acceptance criteria, or the configuration asks for it).

## Step 5 — Implement

1. Launch `ai-enabler:delivery-code-implementer` in `implement` mode with the run directory. When acceptance tests exist, say so in the brief: its job is to make them pass without touching them. For a plan organised in slices, launch it once per slice, in order, so each slice ends with a green build; do not run implementers in parallel on the same working tree.
2. Read the report. Deviations go into the delivery report. A failed verification, or acceptance tests still failing, gets one more implementer pass in `fix` mode with the failing output. If it still fails after that pass, do not loop: carry the failure forward as an open defect.
3. If the implementer disputes an acceptance test, settle it yourself against the ticket and the plan — not against the code. If the test is right, send it back as a fix. If the test contradicts the ticket or the plan, launch the test engineer in `repair` mode for that test, with the correction as guidance, and record the change and its reason in the delivery report. Never let the implementer edit a test to match its code.
4. If the implementer stopped because the plan is wrong in a way that changes scope, do not let it improvise and do not patch the plan in place: the plan was approved, so the change is a **delta**. Follow "Going back" below, with the implementer's explanation as the change.

## Step 6 — Coverage, after the code, and the review of the production code beside it

**First, see whether the review can start now.** Run `review_scope.py` as in Step 7, item 1. When every entry of `groups` holds one lens — the change is at or above `review.group_below_lines`, or the lane reviews one lens per reviewer — the review of the production code does not have to wait for the tests: launch the test engineer below and, **in the same message**, one reviewer per group except `tests`, as Step 7, item 2 says, with the pack just written. They read the code while the tests are written and run; the test engineer mutates copies, never the working tree, so what they read stays the code under review. When the groups pair lenses (a small change), launch the test engineer alone: the review runs after coverage, as Step 7 says, because splitting the tests lens off would add a reviewer to a review that is quick anyway.

Launch `ai-enabler:delivery-test-engineer` with `mode: coverage`, the run directory, `tests.coverage_target`, `tests.coverage_minimum`, `tests.levels`, `tests.full_suite_runs` and `tests.mutation` — those values and nothing else: no extra verification of your own ("What a brief may ask for" in `tests-protocol.md`). It runs the acceptance tests and the whole suite (at most `tests.full_suite_runs` times), writes the tests still missing — for derived criteria, for requirements that had no criterion, and for uncovered lines and branches — measures coverage of the changed code, and, unless `tests.mutation.enabled` is false, runs mutation testing on the changed code that decides something, adding tests for the mutants that survive. It writes `test-report.json` itself — your next `run_state.py update` renders `test-report.md` from it — and returns the figures: act on its return, and do not read, write or rewrite either file.

- `defects found` — each defect is a failing test that exposes wrong production code. Send the list to `ai-enabler:delivery-code-implementer` in `fix` mode, then launch the test engineer in `verify` mode on the affected tests. This shares the `review.max_fix_rounds` budget. Settle defects before looking at coverage. Defects still failing when the budget is spent are not hidden and do not stop the run: continue to the review, list them as open in the delivery report, and treat the result as not ready to ship.
- coverage `met` (at or above the target) — continue.
- coverage `acceptable` (between the minimum and the target) — continue without asking. Carry the figure and what is left uncovered into the delivery report.
- coverage `below minimum` — **stop and let the person decide.** This is not yours to wave through, whatever `gates` says. Run `run_state.py gate .enabler/runs/<KEY> coverage`, then show the figure, the files that fall short and why, and wait:

  ```
  COVERAGE BELOW MINIMUM — <KEY>
  Changed code : <x>% line · <y>% branch   (minimum <min>% · target <target>%)
  Falls short  : <file — %, what is uncovered and why>
  Tests        : <passed> passed, <failed> failed

  Proceed with this coverage? (proceed / more-tests: <optional guidance> / stop)
  ```

  - **proceed** — continue to the review. Record a `coverage_accepted` intervention with the reason the person gives; the ship gate and the pull request will state that the change goes out below the minimum by their decision.
  - **more-tests** — relaunch the test engineer in `coverage` mode with the uncovered files as `scope` and what the person said as `guidance`, then come back to this same check. It is a new coverage stage with its own budget of whole-suite runs; it runs mutation testing only on decision code it had not mutated yet, unless the person asks for more.
  - **stop** — set `status` to `stopped` and stop, leaving the branch and the run directory in place.
- coverage `not measured` (the project has no coverage tool) — continue, and say so at the ship gate: no coverage figure can be claimed.
- `could not run` — continue to review, and state clearly in the report that the change is untested and why.

## Step 7 — Review and fix loop

**When correctness, security and quality were reviewed during the coverage stage**, only the tests lens is left. Run `review_scope.py` with `--lenses tests --no-select` — a fresh pack, which now has the test report — and launch one reviewer with it; if a defect fix in Step 6 changed production code after the first reviewers had read it, add the lenses that reviewed that code to the same launch (`--lenses <those>,tests --no-select`), told which files the fix changed. Then consolidate its findings with those of the first reviewers, from item 3 on. Otherwise, start at item 1.

1. Decide the lenses and write the review pack, with no model involved:

   ```
   /bin/bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/review_scope.py" --base <base branch> --run-dir .enabler/runs/<KEY> --lenses <review.lenses, comma-separated> --group-below <review.group_below_lines> [--sensitive <glob> for each of review.sensitive_paths] [--no-select when review.select_lenses is false]
   ```

   It prints JSON: `groups` (one list of lenses per reviewer to launch), `skipped` (a lens left out and why), `triggers`, and `pack`, the path of `review-pack.md` in the run directory. Correctness, quality and tests always run; security runs whenever the change touches external input, I/O, queries, HTML rendering, authentication, secrets, configuration, dependencies or a sensitive path, and is left out only when nothing of the kind is found. Small changes (under `review.group_below_lines` changed lines) get two reviewers carrying two lenses each instead of one per lens. If the script fails, launch one reviewer per lens in `review.lenses` without a pack, as before, and say so in `review.md`.
2. Launch one `ai-enabler:delivery-code-reviewer` per entry of `groups`, **all in a single message so they run in parallel**. Give each: its lenses, the pack, the scope (the base branch), the run directory, and the path `${CLAUDE_PLUGIN_ROOT}/references/review-checklist.md`.
3. Consolidate. Merge findings that point at the same line and cause, keep the highest severity, drop findings whose confidence is below `review.min_confidence`, and renumber. Before accepting a `critical` or `high` finding, open the cited code and check it yourself: a false blocker costs a fix round.
4. Write `review.md` in the format `${CLAUDE_PLUGIN_ROOT}/skills/delivery-review/SKILL.md` defines (verdict, findings numbered `CR-n` by severity, acceptance-criteria table, "To validate", "Checked and found sound"). Under "Checked and found sound", say which lenses ran in which reviewer, and any lens left out with the reason the script gave: the person must see at the ship gate that security was not reviewed, and why.
5. Fix loop, while there are findings whose severity is in `review.auto_fix` and `fix_rounds < review.max_fix_rounds` (the budget is per review pass; see "Rounds at a gate" in the reference):
   - send those findings to `ai-enabler:delivery-code-implementer` in `fix` mode;
   - launch the test engineer in `verify` mode on the affected area;
   - re-run only the lenses that had findings: `review_scope.py` again with `--lenses <those lenses> --no-select` for a fresh pack, and the reviewers told which files the fix changed;
   - increment `fix_rounds` and append the outcome to `review.md`.
6. Whatever remains — lower severities, findings the implementer disputed, anything left when the budget ran out — is listed as open in the delivery report. Do not keep looping, and do not downgrade a finding to make the report look clean.

## Step 8 — Delivery report, and the ship gate

Write `.enabler/runs/<KEY>/delivery-report.md`, following `${CLAUDE_PLUGIN_ROOT}/templates/pull-request.md` section by section. It is what the person reads at the ship gate, and the material the pull-request body is made from, so write it for a reviewer who has not seen this session. In it, `From` in the criteria table is `ticket`, `derived` or `refinement`: a reviewer must be able to tell what the ticket asked for from what the pipeline added to it.

Then settle which pull-request template the body will follow — "The pull-request body" in `${CLAUDE_PLUGIN_ROOT}/skills/delivery-ship/SKILL.md` — so that the gate can name it. Skip this when no pull request will be opened (local-only mode, `git.pull_request` false).

Then present the ship gate and wait. Record the review's outcome and the template first — `run_state.py update` with `--set review_result={"fixed": n, "open": n, "highest_open": "<severity or null>", "criteria_met": n}` and `--set pr_template="<the plugin's template | the repository's template (<path>)>"` — then run `run_state.py gate .enabler/runs/<KEY> ship`: it records that the run waits and prints the gate below, filled in from the run's files (diff, criteria, tests, mutants, deltas, lane, and what shipping will do, local-only included). Show it as printed; fill in only a line it marks `?`, and put any not-ready reason it did not see first. Approval covers exactly the list it shows:

```
READY TO SHIP — <KEY>
Diff      : <n> files changed, +<added> −<removed>, on <branch>
Criteria  : <met>/<total> met · <n> of them added by refinement <"approved at the plan gate" | "NOT REVIEWED: no plan gate in this run">
Tests     : <passed> passed, <failed> failed · coverage <x>% (target <t>% · minimum <m>%) — met | acceptable | BELOW MINIMUM, accepted by <who> | not measured
            acceptance tests written before the code: <n> of <total criteria>
            mutants: <killed> of <n> killed · <surviving> surviving, each with its reason — or "mutation testing off"
Review    : <n> fixed · <n> open (<highest open severity>)
Deltas    : <n> since the plan was approved (<one line each>, or "none")
Will do   : commit → push <branch> → open PR against <base> [→ comment on <KEY>] [→ transition to "<status>"]
            <the Jira steps appear only when the source is a Jira issue>
PR body   : <the plugin's template | the repository's template (<path>)>
Report    : .enabler/runs/<KEY>/delivery-report.md

Ship it? (ship / local / hold / fix: <what to change>)
```

In local-only mode the gate does not offer to ship. Replace the `Will do` line with `Will do   : nothing leaves this machine (local-only) — local commit on <branch> only`, and ask `Commit locally? (local / hold / fix: <what to change>)`.

- **ship** — carry out the listed actions following `${CLAUDE_PLUGIN_ROOT}/skills/delivery-ship/SKILL.md`, then record `pr_url` and set the stage to `done`.
- **local** — nothing leaves this machine, and the work is committed here. Follow "When the person says no to the remote" in the safety rules: write `.enabler/local-only`, commit on the feature branch locally (staged by path, as the safety rules say), set `status` to `held`, and report the commit hash, the branch and that nothing was pushed, opened or written to Jira.
- **any other refusal to upload** ("no", "don't push", "keep it local") — the same, without the commit: write `.enabler/local-only`, leave the changes in the working tree, set `status` to `held`, and offer `local` if they want it committed. Do not push, do not open the pull request, do not touch Jira.
- **hold** — "not now", which is not a refusal: no marker is written. Set `status` to `held` and stop with everything in the working tree and the run directory; `/ai-enabler:delivery-ship <KEY>` finishes later.
- **fix** — check "Rounds at a gate" in the reference first; then record the intervention (kind `fix`, or `delta` if it turns out to be one), add one to `gate_rounds.ship`, and decide which kind of change it is, as "Going back" below describes: a correction goes to the implementer and returns here through coverage and review; a change to what is being built is a delta and goes through the plan gate first.

If `ship` is not in `gates`, ship only when `--ship` was passed; otherwise stop at "hold" and say how to finish.

A result is **not ready** when tests are failing, a defect is open, coverage is below the minimum without a `coverage_accepted` record, or a `critical` finding is open. Coverage that could not be measured is stated, and is not by itself "not ready".

- With the ship gate: say what is not ready first and recommend holding — the human may still decide, for example to open a draft pull request.
- Without it (`--ship` on an unattended run): never ship a result that is not ready. Hold, and say exactly what blocks it. Nobody approved sending out a failing change.

## Going back: adjustments, fixes and deltas

Three situations send the run backwards: an `adjust` at the plan gate before approval, a `fix` at the ship gate that leaves the plan true (a correction), and a change to what is being built after the plan was approved (a **delta**, whatever asked for it). When one happens — or a resumed run has a delta pending — read `going-back.md` next to this file and follow it. When you cannot tell a correction from a delta, ask whether an acceptance criterion or a step of `plan.md` becomes false; if one does, or you are still in doubt, it is a delta.

## Closing

End with a short summary: the pull-request URL (or the branch, if held), criteria met, tests, open items, the number of human interventions, and where the run directory is. Nothing else.

## Rules for the orchestrator

- **Your context is the costliest part of the run.** Everything you read stays in it, and is read again on every later turn. Read a run file only when a step tells you to, or when a subagent's return lacks a figure you need — and then the part you need. The returns carry what the next decision needs; the files hold the detail for the person and for the next subagent. Do not load skills, references or templates this file does not name: no other plugin's skills and no artifact or page publishing — a skill, once loaded, is carried to the end of the run.
- **Delegate the reading and the writing; keep the judgement.** You do not write production code or tests yourself, and you do not review the diff yourself — except to verify a blocker before spending a fix round on it.
- **Briefs are complete.** A subagent knows only what you tell it and what is in the run directory. Always pass the run directory and the mode; never assume it saw the conversation.
- **Trust, then check.** A subagent's report is a claim. Before the ship gate, confirm the basics yourself: `git status`, `git diff --stat`, and that the files it says it wrote exist.
- **No means no.** A refusal to upload is final for the run and for the project until the person lifts it by hand. See "When the person says no to the remote" in the safety rules.
- **A change to an approved plan is a delta.** It is written down, approved, and carried out tests first; it says what is removed as well as what is added. Never rewrite an approved plan in place, and never let a "fix" change scope unannounced.
- **Two gates, not ten.** Do not ask for confirmation between stages, do not ask the human to choose things the configuration or the repository already decides, and do not stop on warnings. Stop for: a blocked ticket, the plan gate (for the plan, and for every delta whatever `gates` says), coverage below the minimum, the ship gate, the round limit at a gate, and anything the safety rules say to stop for.
- **Report failures as they are.** A stage that failed, a threshold that was missed, a finding left open — all go in the report in plain words.
- **The human can take over at any point.** If they say so, record a `takeover` intervention, tell them the state of the working tree and which stages are left, and stop. A later `/ai-enabler:delivery-run <KEY>` resumes and treats their edits as part of the change.
