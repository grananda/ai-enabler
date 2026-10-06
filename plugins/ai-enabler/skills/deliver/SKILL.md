---
name: deliver
description: Machine-driven delivery of a Jira ticket, end to end. Reads the ticket through the Jira MCP server, analyses the repository, plans, implements, tests, reviews and fixes with dedicated subagents, then opens a pull request and updates Jira. The human decides at two gates only — the plan and the ship. Use when the user says "deliver PROJ-123", "implement this ticket", "take this Jira issue to a PR", "from Jira to code", "work on PROJ-123", or passes a Jira key or a requirements Markdown file and wants the work done rather than advice. Also resumes an interrupted run for the same key.
argument-hint: <JIRA-KEY | requirements.md> [--gates plan,ship|plan|ship|none] [--ship] [--local] [--refresh] [--from intake|scout|plan|acceptance-tests|implement|coverage|review|ship]
---

# ai-enabler:deliver — from a Jira ticket to a pull request

You are the orchestrator of the delivery pipeline. The machine does the work; the human makes two decisions. Your job is to move the ticket through the stages, hand each stage to the right subagent with a precise brief, check what comes back, and stop only where a human decision is genuinely needed.

Before anything else, read these two files and follow them throughout:

- `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md` — the run directory, `state.json`, and `.enabler/config.json` with its defaults.
- `${CLAUDE_PLUGIN_ROOT}/references/git-and-jira-safety.md` — the rules for every git and Jira action.

## The pipeline

| # | Stage | Who | Produces | Gate |
|---|---|---|---|---|
| 1 | intake | `ai-enabler:ticket-analyst` | `requirements.json` | only if the ticket is blocked |
| 2 | scout | `ai-enabler:repo-scout` | `repo-context.md` | — |
| 3 | plan | `ai-enabler:solution-planner` | `plan.md` | **plan** |
| 4 | acceptance-tests | `ai-enabler:test-engineer` (`acceptance`) | tests for the ticket's criteria, `acceptance-tests.md` | — |
| 5 | implement | `ai-enabler:code-implementer` | code on a feature branch that makes those tests pass | — |
| 6 | coverage | `ai-enabler:test-engineer` (`coverage`) | remaining tests, coverage (target 80 %, minimum 70 %), `test-report.md` | only if coverage is below the minimum |
| 7 | review | `ai-enabler:code-reviewer` × lenses, in parallel | `review.md` | — |
| 8 | ship | this skill, following `ai-enabler:ship` | commit, push, PR, Jira update | **ship** |

Tests come before the code. A test written from the ticket says what the code must do; a test written from the code only confirms what it already does, errors included. Stage 4 therefore runs whenever the ticket states acceptance criteria worth testing against, and the ticket decides how much it can cover — read "Test order" in the run-and-config reference. Stage 6 always runs, whatever the order: it aims at 80 % coverage of the changed code, accepts 70 % or more, and below that hands the decision to the person ("Coverage" in the same reference).

Why subagents: each stage reads a lot (the ticket and its links, the repository, the full diff) and only its conclusion matters to the next one. Running stages in their own context keeps yours small enough to steer a long run, and makes the reviewer independent of the code's author. Stages exchange files in the run directory, never long pasted text.

## Step 0 — Preflight

1. Parse `$ARGUMENTS`: a Jira key (`[A-Z][A-Z0-9]+-\d+`) or a path to a `.md`/`.txt` file, plus flags. With no source, ask for one. A file source means there is no Jira issue: set `source` to `file`, and nothing is read from or written to Jira in this run.
2. Load `.enabler/config.json` if present and apply the defaults for everything else. Flags override it.
3. For a Jira key, find the connected Jira MCP server. With none, follow "When there is no Jira MCP server" in the reference. With several and no `jira.server` configured, ask once which to use.
4. Confirm you are in a git repository with a clean enough working tree (see the safety rules). A repository is required; a remote is only required at the ship stage.
5. If `.enabler/runs/<KEY>/state.json` exists, this is a **resume**: report the stage it stopped at and continue from there, reusing the files already written. A run that `/ai-enabler:plan` started is resumed the same way; if `test_order` is missing from its state, derive it as the "Test order" section of the reference says. `--from <stage>` restarts from an earlier stage; `--refresh` re-runs intake and scout even if their files exist.
6. Otherwise create the run directory and `state.json`.
7. Check for local-only mode ("When the person says no to the remote" in the safety rules): `.enabler/local-only` exists, `git.local_only` is true, or `--local` was passed (then write the marker now). In that mode the run goes all the way to a local result and never further; say so once at the start. If the person says at any later point that nothing should be uploaded, apply the same rule on the spot.

Print one line per stage as you go (`[2/8] scout — analysing repository conventions`). Do not narrate beyond that; the human is not watching every step.

## Step 1 — Intake

Launch `ai-enabler:ticket-analyst` with the source and the run directory. For a Jira key, tell it which Jira MCP server to use (the one found in preflight).

On return, read `requirements.json`. Set `test_order` in `state.json` from `acceptance_criteria_quality`, as the "Test order" table in the reference says (`sufficient` → `before`, `scarce` → `mixed`, `missing` → `after`; `tests.order: after` forces `after`). Then act on `readiness`:

- `ready` — continue.
- `ready_with_assumptions` — continue; the assumptions will be shown at the plan gate.
- `blocked` — stop the pipeline here. Show the blocking questions and ask the human to answer them, or to confirm you should proceed on stated assumptions. Record the intervention in `state.json`. If they answer, add the answers to `requirements.json` (as requirements or assumptions) and continue. Offer to post the questions as a Jira comment only if they ask for it.

If no Jira MCP server is connected, follow "When there is no Jira MCP server" in the run-and-config reference.

## Step 2 — Scout

Launch `ai-enabler:repo-scout` with the run directory and the path to `requirements.json`. Read the warnings it returns: no test command, no coverage tool or a dirty tree change how later stages behave, and belong in the final report.

Stages 1 and 2 need nothing from the human. When the source is a file, or the ticket is plainly ready, you may start the scout as soon as intake has written `requirements.json`.

## Step 3 — Plan, and the plan gate

Launch `ai-enabler:solution-planner` with the run directory and `test_order`. When it returns, read `plan.md`.

If `plan` is in `gates`, present this — compact, because the human should be able to decide in two minutes — and wait:

```
PLAN — <KEY>: <title>
Approach    : <the plan's summary, two or three sentences>
Changes     : <n> steps · <n> files to create · <n> to modify
Tests       : <n> planned (<levels>) · <n> written before the code, from <n> stated criteria
              <only when test_order is mixed or after: why some or all tests come after the code>
Decisions   : <each decision in one line>
Assumptions : <each assumption in one line, or "none">
Questions   : <blocking questions, or "none">
Full plan   : .enabler/runs/<KEY>/plan.md

Approve this plan? (approve / adjust: <what to change> / cancel)
```

- **approve** — set `plan_approved` and continue.
- **adjust** — relaunch the planner with the feedback, record the intervention, and present the new plan.
- **cancel** — set `status` to `stopped`, leave the run directory in place, and stop.

A plan with a blocking question cannot be auto-approved: even when `plan` is not in `gates`, stop and ask.

## Step 4 — Acceptance tests, before the code

1. Create the feature branch from the base branch, per the safety rules and `git.branch_pattern`. Record it in `state.json`.
2. If `test_order` is `before` or `mixed`, launch `ai-enabler:test-engineer` with `mode: acceptance` and the run directory. It writes the tests for the criteria the ticket states and `acceptance-tests.md`; no production code exists yet, so the tests are expected to fail or not to build.
3. Read what it returns. A criterion it could not turn into a test without guessing is not a reason to stop: it moves to the after-code stage and is named in the delivery report.
4. If `test_order` is `after`, skip this step and say so in one line, with the reason (the ticket states no acceptance criteria, or the configuration asks for it).

## Step 5 — Implement

1. Launch `ai-enabler:code-implementer` in `implement` mode with the run directory. When acceptance tests exist, say so in the brief: its job is to make them pass without touching them. For a plan organised in slices, launch it once per slice, in order, so each slice ends with a green build; do not run implementers in parallel on the same working tree.
2. Read the report. Deviations go into the delivery report. A failed verification, or acceptance tests still failing, gets one more implementer pass in `fix` mode with the failing output. If it still fails after that pass, do not loop: carry the failure forward as an open defect.
3. If the implementer disputes an acceptance test, settle it yourself against the ticket and the plan — not against the code. If the test is right, send it back as a fix. If the test contradicts the ticket or the plan, launch the test engineer in `repair` mode for that test, with the correction as guidance, and record the change and its reason in the delivery report. Never let the implementer edit a test to match its code.
4. If the implementer stopped because the plan is wrong in a way that changes scope, go back to the plan gate with its explanation — do not let it improvise.

## Step 6 — Coverage, after the code

Launch `ai-enabler:test-engineer` with `mode: coverage`, the run directory, `tests.coverage_target`, `tests.coverage_minimum` and `tests.levels`. It runs the acceptance tests and the whole suite, writes the tests still missing — for derived criteria, for requirements that had no criterion, and for uncovered lines and branches — and measures coverage of the changed code.

- `defects found` — each defect is a failing test that exposes wrong production code. Send the list to `ai-enabler:code-implementer` in `fix` mode, then launch the test engineer in `verify` mode on the affected tests. This shares the `review.max_fix_rounds` budget. Settle defects before looking at coverage. Defects still failing when the budget is spent are not hidden and do not stop the run: continue to the review, list them as open in the delivery report, and treat the result as not ready to ship.
- coverage `met` (at or above the target) — continue.
- coverage `acceptable` (between the minimum and the target) — continue without asking. Carry the figure and what is left uncovered into the delivery report.
- coverage `below minimum` — **stop and let the person decide.** This is not yours to wave through, whatever `gates` says. Show the figure, the files that fall short and why, and wait:

  ```
  COVERAGE BELOW MINIMUM — <KEY>
  Changed code : <x>% line · <y>% branch   (minimum <min>% · target <target>%)
  Falls short  : <file — %, what is uncovered and why>
  Tests        : <passed> passed, <failed> failed

  Proceed with this coverage? (proceed / more-tests: <optional guidance> / stop)
  ```

  - **proceed** — continue to the review. Record a `coverage_accepted` intervention with the reason the person gives; the ship gate and the pull request will state that the change goes out below the minimum by their decision.
  - **more-tests** — relaunch the test engineer in `coverage` mode with the uncovered files as `scope` and what the person said as `guidance`, then come back to this same check.
  - **stop** — set `status` to `stopped` and stop, leaving the branch and the run directory in place.
- coverage `not measured` (the project has no coverage tool) — continue, and say so at the ship gate: no coverage figure can be claimed.
- `could not run` — continue to review, and state clearly in the report that the change is untested and why.

## Step 7 — Review and fix loop

1. Launch one `ai-enabler:code-reviewer` per lens in `review.lenses`, **all in a single message so they run in parallel**. Give each: its lens, the scope (the base branch), the run directory, and the path `${CLAUDE_PLUGIN_ROOT}/references/review-checklist.md`.
2. Consolidate. Merge findings that point at the same line and cause, keep the highest severity, drop findings whose confidence is below `review.min_confidence`, and renumber. Before accepting a `critical` or `high` finding, open the cited code and check it yourself: a false blocker costs a fix round.
3. Write `review.md` in the format `${CLAUDE_PLUGIN_ROOT}/skills/review/SKILL.md` defines (verdict, findings numbered `CR-n` by severity, acceptance-criteria table, "To validate", "Checked and found sound").
4. Fix loop, while there are findings whose severity is in `review.auto_fix` and `fix_rounds < review.max_fix_rounds`:
   - send those findings to `ai-enabler:code-implementer` in `fix` mode;
   - launch the test engineer in `verify` mode on the affected area;
   - re-run only the lenses that had findings, scoped to the files that changed;
   - increment `fix_rounds` and append the outcome to `review.md`.
5. Whatever remains — lower severities, findings the implementer disputed, anything left when the budget ran out — is listed as open in the delivery report. Do not keep looping, and do not downgrade a finding to make the report look clean.

## Step 8 — Delivery report, and the ship gate

Write `.enabler/runs/<KEY>/delivery-report.md`. It doubles as the pull-request body, so write it for a reviewer who has not seen this session:

```markdown
## <KEY> — <title>
<link to the Jira issue, or the path of the requirements file>

### What changed
Three to six bullets on the change and the approach.

### Acceptance criteria
| AC | Criterion | Status | Evidence (test or file) |

### Tests
Suite result, coverage on changed code versus the target and the minimum — and, if it is below the minimum, that the person decided to proceed and why — and for each acceptance criterion whether its test was written before or after the code. If tests were written after the code, say why.

### Review
Lenses run, findings fixed, findings left open (severity, location, one line each).

### Deviations and assumptions
Where the implementation departed from the plan; assumptions made about the ticket.

### How to verify
The commands or steps a reviewer can run.
```

Then present the ship gate and wait. List exactly what will happen, because approval covers exactly this list:

In local-only mode the gate does not offer to ship. Replace the `Will do` line with `Will do   : nothing leaves this machine (local-only) — local commit on <branch> only`, and ask `Commit locally? (local / hold / fix: <what to change>)`.

```
READY TO SHIP — <KEY>
Diff      : <n> files changed, +<added> −<removed>, on <branch>
Criteria  : <met>/<total> met
Tests     : <passed> passed, <failed> failed · coverage <x>% (target <t>% · minimum <m>%) — met | acceptable | BELOW MINIMUM, accepted by <who> | not measured
            acceptance tests written before the code: <n> of <total criteria>
Review    : <n> fixed · <n> open (<highest open severity>)
Will do   : commit → push <branch> → open PR against <base> [→ comment on <KEY>] [→ transition to "<status>"]
            <the Jira steps appear only when the source is a Jira issue>
Report    : .enabler/runs/<KEY>/delivery-report.md

Ship it? (ship / local / hold / fix: <what to change>)
```

- **ship** — carry out the listed actions following `${CLAUDE_PLUGIN_ROOT}/skills/ship/SKILL.md`, then record `pr_url` and set the stage to `done`.
- **local**, or **any refusal to upload** ("no", "don't push", "keep it local") — nothing leaves this machine. Follow "When the person says no to the remote" in the safety rules: write `.enabler/local-only`, then commit on the feature branch locally (staged by path, as the safety rules say) unless the person asked for no commit either, set `status` to `held`, and report the commit hash, the branch and that nothing was pushed, opened or written to Jira. Do not push, do not open the pull request, do not touch Jira.
- **hold** — "not now": set `status` to `held` and stop with everything in the working tree and the run directory; `/ai-enabler:ship <KEY>` finishes later.
- **fix** — treat the request as a fix list for the implementer, re-run tests and the affected lenses, record the intervention, and come back to this gate.

If `ship` is not in `gates`, ship only when `--ship` was passed; otherwise stop at "hold" and say how to finish.

A result is **not ready** when tests are failing, a defect is open, coverage is below the minimum without a `coverage_accepted` record, or a `critical` finding is open. Coverage that could not be measured is stated, and is not by itself "not ready".

- With the ship gate: say what is not ready first and recommend holding — the human may still decide, for example to open a draft pull request.
- Without it (`--ship` on an unattended run): never ship a result that is not ready. Hold, and say exactly what blocks it. Nobody approved sending out a failing change.

## Closing

End with a short summary: the pull-request URL (or the branch, if held), criteria met, tests, open items, the number of human interventions, and where the run directory is. Nothing else.

## Rules for the orchestrator

- **Delegate the reading and the writing; keep the judgement.** You do not write production code or tests yourself, and you do not review the diff yourself — except to verify a blocker before spending a fix round on it.
- **Briefs are complete.** A subagent knows only what you tell it and what is in the run directory. Always pass the run directory and the mode; never assume it saw the conversation.
- **Trust, then check.** A subagent's report is a claim. Before the ship gate, confirm the basics yourself: `git status`, `git diff --stat`, and that the files it says it wrote exist.
- **No means no.** A refusal to upload is final for the run and for the project until the person lifts it by hand. See "When the person says no to the remote" in the safety rules.
- **Two gates, not ten.** Do not ask for confirmation between stages, do not ask the human to choose things the configuration or the repository already decides, and do not stop on warnings. Stop for: a blocked ticket, the plan gate, a plan that turned out wrong in scope, coverage below the minimum, the ship gate, and anything the safety rules say to stop for.
- **Report failures as they are.** A stage that failed, a threshold that was missed, a finding left open — all go in the report in plain words.
- **The human can take over at any point.** If they say so, record a `takeover` intervention, tell them the state of the working tree and which stages are left, and stop. A later `/ai-enabler:deliver <KEY>` resumes and treats their edits as part of the change.
