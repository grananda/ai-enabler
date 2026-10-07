---
name: implement
description: Implements an already approved ai-enabler plan — creates the feature branch, has the test-engineer subagent write the acceptance tests first, then has the code-implementer subagent write the code described in `.enabler/runs/<KEY>/plan.md` so that those tests pass, keeping the build green. No coverage stage, review or shipping. Use when the user says "implement the plan for PROJ-123", "generate the code for this plan", "execute the plan", or wants the implementation stage on its own after `/ai-enabler:plan`.
argument-hint: <JIRA-KEY> [--steps 1,2,3]
---

# ai-enabler:implement — execute an approved plan

Runs the implementation stages of the delivery pipeline on their own: the acceptance tests first, then the code that makes them pass. Use `/ai-enabler:deliver` when the whole flow is wanted.

Read first:

- `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md`
- `${CLAUDE_PLUGIN_ROOT}/references/git-and-jira-safety.md`

## Flow

1. **Preflight.** `$ARGUMENTS` gives the key. `.enabler/runs/<KEY>/plan.md` must exist; if it does not, say so and point to `/ai-enabler:plan <KEY>`. If `plan_approved` is not set in `state.json`, show the plan summary and ask for approval once — code is not written from a plan nobody approved.
2. **Branch.** Create the feature branch from the base branch, or stay on it if it already exists, following the git safety rules. Record it in `state.json`.
3. **Acceptance tests first.** Unless `acceptance-tests.md` already exists in the run directory, or `test_order` is `after` (see "Test order" in the run-and-config reference; derive it from `requirements.json` if the state does not have it), launch `ai-enabler:test-engineer` with `mode: acceptance` so the tests for the ticket's criteria exist before the code. When the order is `after`, say why in one line.
4. **Implement.** Launch `ai-enabler:code-implementer` in `implement` mode with the run directory, and with the step subset if `--steps` was given. Tell it the acceptance tests are there to be passed, not edited. For a plan organised in slices, launch once per slice, in order.
5. **Check.** Read the report, including the state of each acceptance test. Confirm with `git status` and `git diff --stat` that the files it names exist and changed. If its verification failed, give it one more pass in `fix` mode with the failing output. If it stopped because the plan is wrong in scope, relay its explanation and stop.
6. **Report.** Acceptance tests written and how many pass, files created and modified, deviations from the plan, the verification commands and their result, and anything not done. Update `state.json`.

If `state.json` holds an approved delta that has not been carried out, pass it to both agents: the test engineer adds and removes tests as the delta says, then the implementer writes and deletes code as it says.

Close by naming the next steps: `/ai-enabler:test <KEY>` (remaining tests and the coverage check), then `/ai-enabler:review <KEY>`, then `/ai-enabler:ship <KEY>` — or `/ai-enabler:deliver <KEY>` to run the rest in one go.

## Rules

- You do not write the code or the tests; the subagents do. The implementer never edits an acceptance test: a disputed test is settled against the ticket and corrected, if at all, by the test engineer.
- Nothing is committed or pushed here.
- Report what the implementer's verification actually showed. "Not verified" is an acceptable result; "builds" without a command behind it is not.
