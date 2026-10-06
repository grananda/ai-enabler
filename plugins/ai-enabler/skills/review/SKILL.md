---
name: review
description: Independent multi-lens code review with a severity-ranked report and optional auto-fix. Launches read-only code-reviewer subagents in parallel (correctness, security, quality, tests), consolidates and filters their findings, writes a Markdown report, and fixes findings only when asked: with `--fix`, or when the person says so after reading the report. Works on an ai-enabler run, a branch against its base, a pull request, or paths. Use when the user says "review my changes", "code review", "review PROJ-123", "review PR 42", "security review of this branch", "is this ready to merge", or "review and fix".
argument-hint: [JIRA-KEY | PR number or URL | path ...] [--base <branch>] [--lenses correctness,security,quality,tests] [--fix] [--min-confidence 80]
---

# ai-enabler:review — independent review, optional fix

Runs the review stage of the delivery pipeline on its own, or as a stand-alone reviewer for any change.

Read `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md` for the run directory and the `review` defaults.

## Flow

1. **Scope.** From `$ARGUMENTS`:
   - a Jira key with a run directory — the run's branch against its base, with the ticket's acceptance criteria as the yardstick;
   - a pull-request number or URL — that pull request (`gh pr view`, `gh pr diff`);
   - paths — those files;
   - nothing — the current branch against the base branch (`--base`, else the remote's default), plus uncommitted changes. If there is nothing to review, say so and stop.
2. **Review in parallel.** Launch one `ai-enabler:code-reviewer` per lens, **all in one message**. Each gets its lens, the scope, the run directory if there is one, and the path `${CLAUDE_PLUGIN_ROOT}/references/review-checklist.md`. The reviewers have no edit tools; they cannot change the code they judge.
3. **Consolidate.** Merge findings that share a location and a cause, keeping the highest severity. Drop findings below the confidence floor (`--min-confidence`, else `review.min_confidence`). Open the cited code for every `critical` and `high` finding and confirm it; move anything you cannot confirm to a "to validate" list rather than deleting it. Renumber as `CR-1`, `CR-2`, ... by severity.
4. **Write the report** to `.enabler/runs/<KEY>/review.md` in pipeline mode, otherwise to `.enabler/runs/adhoc/review-<YYYY-MM-DD>.md`:

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
   ```
5. **Present** the verdict, the counts, and the critical and high findings in full; give the path for the rest.
6. **Fix, only if asked.** Fixing happens when `--fix` was passed or when the human says so after seeing the report — never by default. (`review.auto_fix` in the configuration belongs to `/ai-enabler:deliver`, whose fix loop runs inside an approved pipeline; it does not authorise this skill.) With `--fix` and no further instruction, fix `critical` and `high`. Then:
   - send the selected findings to `ai-enabler:code-implementer` in `fix` mode;
   - run the affected tests (launch `ai-enabler:test-engineer` in `verify` mode on them);
   - re-run only the lenses that had findings, on the files that changed;
   - append a "Fix round" section to the report: fixed, disputed by the implementer (with its reason), still open.

   At most `review.max_fix_rounds` rounds. Without authorisation, the report is the deliverable and the code is untouched.

## Rules

- You do not review the diff in your own context and you do not edit code yourself; reviewers review, the implementer fixes. Your part is consolidation and verification of blockers.
- Never post review comments to a pull request, approve it, or request changes on it unless the human asks for exactly that.
- Do not pad the report. No findings is a valid result; say what was checked.
- A finding is not downgraded or dropped to reach a clean verdict.
