---
name: delivery-review
description: "Independent multi-lens code review with a severity-ranked report and optional auto-fix. Decides which lenses the change needs (correctness, quality and tests always, security when the change touches it), launches read-only delivery-code-reviewer subagents in parallel with one shared review pack, consolidates and filters their findings, writes a Markdown report, and fixes findings only when asked: with `--fix`, or when the person says so after reading the report. Works on an ai-enabler run, a branch against its base, a pull request, or paths. Use when the user says \"review my changes\", \"code review\", \"review PROJ-123\", \"review PR 42\", \"security review of this branch\", \"is this ready to merge\", or \"review and fix\"."
argument-hint: "[JIRA-KEY | PR number or URL | path ...] [--base <branch>] [--lenses correctness,security,quality,tests] [--fix] [--min-confidence 80]"
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.3.0"
---

# ai-enabler:delivery-review — independent review, optional fix

Runs the review stage of the delivery pipeline on its own, or as a stand-alone reviewer for any change.

Read `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md` for the run directory and the `review` defaults.

## Flow

1. **Scope.** From `$ARGUMENTS`:
   - a Jira key with a run directory — the run's branch against its base, with the ticket's acceptance criteria as the yardstick;
   - a pull-request number or URL — that pull request (`gh pr view`, `gh pr diff`);
   - paths — those files;
   - nothing — the current branch against the base branch (`--base`, else the remote's default), plus uncommitted changes. If there is nothing to review, say so and stop.
   - **External sources.** When the project has external sources (`/bin/bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/sources.py" status`), bring them up to date as Step 1 of `${CLAUDE_PLUGIN_ROOT}/skills/delivery-run/SKILL.md` says under "Learn the external sources at the same time"; in pipeline mode the run's `external-context.md` is used, and outside one the subagents read the source profiles.
2. **Lenses and pack.** Run `/bin/bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/review_scope.py"` as Step 7 of `${CLAUDE_PLUGIN_ROOT}/skills/delivery-run/SKILL.md` says: `--base` the base of the scope, `--run-dir` the run directory in pipeline mode, otherwise `--out .enabler/runs/adhoc/review-pack-<YYYY-MM-DD>.md`, and the `review` settings. With `--lenses` given by the person, pass them with `--no-select`: they are run as asked. For a pull request, check out its branch first or review it without a pack, one reviewer per lens. The script prints the reviewer groups, any lens left out and why, and the path of the pack.
3. **Review in parallel.** Launch one `ai-enabler:delivery-code-reviewer` per group, **all in one message**. Each gets its lenses, the pack, the scope, the run directory if there is one, and the path `${CLAUDE_PLUGIN_ROOT}/references/review-checklist.md`. The reviewers have no edit tools; they cannot change the code they judge.
4. **Consolidate.** Merge findings that share a location and a cause, keeping the highest severity. Drop findings below the confidence floor (`--min-confidence`, else `review.min_confidence`). Open the cited code for every `critical` and `high` finding and confirm it; move anything you cannot confirm to a "to validate" list rather than deleting it. Renumber as `CR-1`, `CR-2`, ... by severity.
5. **Write the report** to `.enabler/runs/<KEY>/review.md` in pipeline mode, otherwise to `.enabler/runs/adhoc/review-<YYYY-MM-DD>.md`:

   ```markdown
   # Code review — <scope>
   **Verdict:** ready | ready with findings | not ready · <n> critical, <n> high, <n> medium, <n> low

   ## Findings
   ### [CR-1] <title> — <severity>
   `file:line` · lens · confidence
   Problem, why it matters, fix direction, test needed.

   ## Acceptance criteria
   | AC | Status | Evidence |

   ## To validate
   ## Checked and found sound
   Which lenses ran, in which reviewer; any lens left out and why.
   ```
6. **Present** the verdict, the counts, and the critical and high findings in full; give the path for the rest.
7. **Fix, only if asked.** Fixing happens when `--fix` was passed or when the human says so after seeing the report — never by default. (`review.auto_fix` in the configuration belongs to `/ai-enabler:delivery-run`, whose fix loop runs inside an approved pipeline; it does not authorise this skill.) With `--fix` and no further instruction, fix `critical` and `high`. Then:
   - send the selected findings to `ai-enabler:delivery-code-implementer` in `fix` mode;
   - run the affected tests (launch `ai-enabler:delivery-test-engineer` in `verify` mode on them; it adds the result to `test-report.json`, and `/bin/bash "${CLAUDE_PLUGIN_ROOT}/scripts/run-python.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/run_state.py" render <run directory>` brings `test-report.md` up to date);
   - re-run only the lenses that had findings: `review_scope.py` again with `--lenses <those lenses> --no-select` for a fresh pack, and the reviewers told which files the fix changed;
   - append a "Fix round" section to the report: fixed, disputed by the implementer (with its reason), still open.

   At most `review.max_fix_rounds` rounds. Without authorisation, the report is the deliverable and the code is untouched.

## Rules

- **The test engineer gets the configuration and the scope, nothing more.** No extra mutation passes, whole-suite runs beyond `tests.full_suite_runs`, or stability re-runs ("What a brief may ask for" in `${CLAUDE_PLUGIN_ROOT}/references/tests-protocol.md`).
- **What was learned about the repository is kept.** When a subagent reports that the repository profile was wrong or incomplete (a command that does not work here, a convention the code does not follow, a rule nobody had written down), append one line to `profile_notes` in the run's `state.json` in pipeline mode, or turn it into a delta at the end in stand-alone mode; "When something was learned" in `${CLAUDE_PLUGIN_ROOT}/references/repo-profile.md` says how it becomes a delta to the profile. Never edit `profile.md` for it.
- You do not review the diff in your own context and you do not edit code yourself; reviewers review, the implementer fixes. Your part is consolidation and verification of blockers.
- Never post review comments to a pull request, approve it, or request changes on it unless the human asks for exactly that.
- Do not pad the report. No findings is a valid result; say what was checked.
- A finding is not downgraded or dropped to reach a clean verdict.
