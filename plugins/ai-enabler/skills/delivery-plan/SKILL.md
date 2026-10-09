---
name: delivery-plan
description: Turns a Jira ticket (read through the Jira MCP server) or a requirements Markdown file into a reviewed implementation plan, without writing any code. Runs the intake, scout and plan stages of the ai-enabler pipeline and stops. Use when the user says "plan PROJ-123", "how would we implement this ticket", "give me an implementation plan for this story", "break this ticket down", "is this ticket ready to implement", or wants to see the plan before committing to a delivery.
argument-hint: <JIRA-KEY | requirements.md> [--no-refine] [--refresh] [--relearn]
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.2.1"
---

# ai-enabler:delivery-plan — ticket to implementation plan

Runs the first three stages of the delivery pipeline and stops with a plan on disk. Nothing is changed in the codebase, in git, or in Jira.

Read `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md` first; it defines the run directory, `state.json` and the configuration defaults.

## Flow

1. **Preflight.** Parse `$ARGUMENTS` for a Jira key or a `.md`/`.txt` path; ask for one only if neither is given. Create or reuse `.enabler/runs/<KEY>/`. With `--refresh`, re-run every stage even if its file exists; with `--relearn`, also study the repository again from scratch (it drops the repository profile and its deltas); otherwise reuse `requirements.json` and `repo-context.md` when present and say that you did.
2. **Intake.** Skip this step when `requirements.json` is being reused. Otherwise launch `ai-enabler:delivery-ticket-analyst` with the source and the run directory, then refine the ticket exactly as Step 1 of `${CLAUDE_PLUGIN_ROOT}/skills/delivery-run/SKILL.md` says under "Refine", with the same cases in which it is skipped and the same handling of `--refresh`: `ai-enabler:delivery-ticket-refiner` in `mode: pipeline`, and `refined` recorded in `state.json`. If the verdict after that is `blocked`, show the blocking questions with their options, and ask whether to stop or to plan on stated assumptions. Set `test_order` in `state.json` from `acceptance_criteria_quality`, as the "Test order" section of the reference says. With no Jira MCP server connected, follow "When there is no Jira MCP server" in the reference.
3. **Scout.** Follow Step 2 of `${CLAUDE_PLUGIN_ROOT}/skills/delivery-run/SKILL.md`: ask `repo_profile.py check`, launch `ai-enabler:delivery-repo-scout` with the tasks the status calls for (`profile`, `delta`, `ticket`) and the absolute paths the script prints, and `record` as that step says for each status. A `repo-context.md` reused from an earlier run is not rewritten, but the check still runs: the profile may have gone stale since.
4. **Plan.** Launch `ai-enabler:delivery-solution-planner` with the run directory and `test_order`.
5. **Present.** Read `plan.md` and show the same compact summary the delivery pipeline uses at its plan gate: approach, number of steps, the files to create and to modify by path, planned tests and how many of them will be written before the code (with the reason when the ticket's criteria are scarce or missing), what refinement added to the ticket, decisions, assumptions, blocking questions, and the path to the full plan.
6. **Iterate on request.** If the human asks for changes, that is a round at the plan gate: check "Rounds at a gate" in the reference, add one to `gate_rounds.plan`, relaunch the planner with their feedback and present the result again (when the feedback rejects something refinement added, mark it in `requirements.json` first, as the plan gate of `delivery-run` says). When they approve, set `plan_approved` in `state.json`, with `stage` at `acceptance-tests` and the three stages done.

Close by naming the next step: `/ai-enabler:delivery-run <KEY>` continues from the approved plan (it resumes the run at the acceptance tests, then the implementation and the rest), or `/ai-enabler:delivery-implement <KEY>` runs only the acceptance tests and the implementation.

## When the run already has an approved plan

Asking for a plan again does not overwrite it. If `plan_approved` is set and the person wants something changed, that is a delta: follow steps 1 and 2 of situation 3 under "Going back" in `${CLAUDE_PLUGIN_ROOT}/skills/delivery-run/SKILL.md` — the safety copy, the planner in `mode: delta`, the record in `state.json`, the gate with its adjust and cancel paths. On approval the delta is `approved: true`, `applied: false` and `stage` is `acceptance-tests`, which is what tells the next skill there is work to do. Carrying it out — tests first, then code — is for `/ai-enabler:delivery-run <KEY>` or `/ai-enabler:delivery-implement <KEY>`.

## Rules

- No code, no branch, no commit, no Jira write.
- Do not plan in your own context: the planner subagent writes the plan, you present it.
- The ticket's readiness verdict is part of the answer. A plan built on a blocked ticket must say so at the top.
