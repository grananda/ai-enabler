---
name: delivery-implement
description: Implements an already approved ai-enabler plan — creates the feature branch, has the delivery-test-engineer subagent write the acceptance tests first, then has the delivery-code-implementer subagent write the code described in `.enabler/runs/<KEY>/plan.md` so that those tests pass, keeping the build green. No coverage stage, review or shipping. Use when the user says "implement the plan for PROJ-123", "generate the code for this plan", "execute the plan", or wants the implementation stage on its own after `/ai-enabler:delivery-plan`.
argument-hint: <JIRA-KEY> [--steps 1,2,3]
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.0.0"
---

# ai-enabler:delivery-implement — execute an approved plan

Runs the implementation stages of the delivery pipeline on their own: the acceptance tests first, then the code that makes them pass. Use `/ai-enabler:delivery-run` when the whole flow is wanted.

Read first:

- `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md`
- `${CLAUDE_PLUGIN_ROOT}/references/git-and-jira-safety.md`

## Flow

1. **Preflight.** `$ARGUMENTS` gives the key. `.enabler/runs/<KEY>/plan.md` must exist; if it does not, say so and point to `/ai-enabler:delivery-plan <KEY>`. If `plan_approved` is not set in `state.json`, show the plan summary and ask for approval once — code is not written from a plan nobody approved.
2. **Branch.** Create the feature branch from the base branch, or stay on it if it already exists, following the git safety rules. Record it in `state.json`.
3. **Acceptance tests first.** If `state.json` holds a delta that is approved and not applied, this run is about that delta: launch `ai-enabler:delivery-test-engineer` in `acceptance` mode with the delta, whatever else is true. Otherwise, unless `acceptance-tests.md` already exists in the run directory, or `test_order` is `after` (see "Test order" in the run-and-config reference; derive it from `requirements.json` if the state does not have it), launch `ai-enabler:delivery-test-engineer` with `mode: acceptance` so the tests for the ticket's criteria exist before the code. When the order is `after`, say why in one line.
4. **Implement.** Launch `ai-enabler:delivery-code-implementer` in `implement` mode with the run directory, and with the step subset if `--steps` was given. Tell it the acceptance tests are there to be passed, not edited. For a plan organised in slices, launch once per slice, in order.
5. **Check.** Read the report, including the state of each acceptance test. Confirm with `git status` and `git diff --stat` that the files it names exist and changed. If its verification failed, give it one more pass in `fix` mode with the failing output. If it stopped because the plan is wrong in scope, relay its explanation and stop: changing an approved plan is a delta, made with `/ai-enabler:delivery-plan <KEY>`.
6. **Report.** Acceptance tests written and how many pass, files created and modified, deviations from the plan, the verification commands and their result, and anything not done. Update `state.json`.

With an approved, unapplied delta, the implementer is launched with that delta too — it writes and deletes code as the delta says — and when it returns the delta is marked `applied: true`.

Close by naming the next steps: `/ai-enabler:delivery-test <KEY>` (remaining tests and the coverage check), then `/ai-enabler:delivery-review <KEY>`, then `/ai-enabler:delivery-ship <KEY>` — or `/ai-enabler:delivery-run <KEY>` to run the rest in one go.

## Rules

- You do not write the code or the tests; the subagents do. The implementer never edits an acceptance test: a disputed test is settled against the ticket and corrected, if at all, by the test engineer.
- Nothing is committed or pushed here.
- Report what the implementer's verification actually showed. "Not verified" is an acceptable result; "builds" without a command behind it is not.
