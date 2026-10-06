---
name: test
description: Generates and runs the tests for a change and checks coverage of the changed code against an 80 % target and a 70 % minimum, using the test-engineer subagent. Works on an ai-enabler run (tests derived from the ticket's acceptance criteria) or on any branch, diff or path without a ticket. Use when the user says "generate tests", "add unit tests for my changes", "cover this with tests", "check coverage", "write e2e tests for this flow", "tests for PROJ-123", or "increase coverage".
argument-hint: [JIRA-KEY | path ...] [--base <branch>] [--target 80] [--minimum 70] [--levels unit,integration,e2e] [--before-code]
---

# ai-enabler:test — tests and coverage for a change

Runs the test stages of the delivery pipeline on their own, or as a stand-alone test generator when there is no ticket. By default it is the after-code stage: run everything, add what is missing, reach the coverage target. With `--before-code` it is the acceptance stage: write the tests for the ticket's criteria before the implementation exists.

Read `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md` for the run directory and the `tests` defaults.

## Flow

1. **Scope.** From `$ARGUMENTS`:
   - a Jira key with an existing run directory — pipeline mode: the scope is the run's changes, and the acceptance criteria come from `requirements.json`;
   - paths — those files;
   - nothing — the changes on the current branch against the base branch (`--base`, else the remote's default branch), plus the working tree. If there are no changes at all, say so and ask which paths to cover.
2. **Context.** The test engineer needs the repository's framework and commands. In pipeline mode `repo-context.md` already exists. Otherwise launch `ai-enabler:repo-scout` once into `.enabler/runs/adhoc/` (reuse its output on later calls unless the manifests changed).
3. **Generate and run.** Launch `ai-enabler:test-engineer` with the run directory or the explicit scope, the levels, and the mode: `acceptance` with `--before-code` (pipeline mode only — it needs the ticket's criteria and the plan), otherwise `coverage` with the coverage target and minimum. The target and the minimum are `--target` and `--minimum`, else `tests.coverage_target` and `tests.coverage_minimum` (80 and 70).
4. **Act on the verdict.**
   - `green` — report, then apply the coverage rule in "Rules" below.
   - `defects found` — the tests expose wrong production code. Show each defect. In pipeline mode, offer to send them to `ai-enabler:code-implementer` in `fix` mode and re-run; outside a pipeline run, the code is the human's and you only report.
   - `could not run` — report the reason and what is needed to run the suite.
5. **Report.** Tests added, suite totals, coverage on the changed code against the target and the minimum, the acceptance-criteria table when there is one, defects, pre-existing failures, and the path to `test-report.md`.

## Rules

- You do not write the tests yourself; the test engineer does, in its own context.
- Production code is never changed to make a test pass, and existing tests are never weakened or skipped.
- Coverage is `met` at 80 % or more, `acceptable` from 70 % up to 80 %, and `below minimum` under 70 % (line and branch, changed code). Report the verdict as it is, with the files and lines that fall short. Below the minimum, ask the person whether to proceed as it is, write more tests, or stop — "Coverage" in the run-and-config reference — and do what they choose; never round the figure up or decide for them.
- In a pipeline run, say for each acceptance criterion whether its test was written before or after the code.
- Do not add a test framework or a coverage tool to a project that has none; report the gap instead.
