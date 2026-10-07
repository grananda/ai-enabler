---
name: plan
description: Turns a Jira ticket (read through the Jira MCP server) or a requirements Markdown file into a reviewed implementation plan, without writing any code. Runs the intake, scout and plan stages of the ai-enabler pipeline and stops. Use when the user says "plan PROJ-123", "how would we implement this ticket", "give me an implementation plan for this story", "break this ticket down", "is this ticket ready to implement", or wants to see the plan before committing to a delivery.
argument-hint: <JIRA-KEY | requirements.md> [--refresh]
---

# ai-enabler:plan — ticket to implementation plan

Runs the first three stages of the delivery pipeline and stops with a plan on disk. Nothing is changed in the codebase, in git, or in Jira.

Read `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md` first; it defines the run directory, `state.json` and the configuration defaults.

## Flow

1. **Preflight.** Parse `$ARGUMENTS` for a Jira key or a `.md`/`.txt` path; ask for one only if neither is given. Create or reuse `.enabler/runs/<KEY>/`. With `--refresh`, re-run every stage even if its file exists; otherwise reuse `requirements.json` and `repo-context.md` when present and say that you did.
2. **Intake.** Launch `ai-enabler:ticket-analyst` with the source and the run directory. If the verdict is `blocked`, show the blocking questions, and ask whether to stop or to plan on stated assumptions. Set `test_order` in `state.json` from `acceptance_criteria_quality`, as the "Test order" section of the reference says. With no Jira MCP server connected, follow "When there is no Jira MCP server" in the reference.
3. **Scout.** Launch `ai-enabler:repo-scout` with the run directory and the path to `requirements.json`.
4. **Plan.** Launch `ai-enabler:solution-planner` with the run directory and `test_order`.
5. **Present.** Read `plan.md` and show the same compact summary the delivery pipeline uses at its plan gate: approach, number of steps and files, planned tests and how many of them will be written before the code (with the reason when the ticket's criteria are scarce or missing), decisions, assumptions, blocking questions, and the path to the full plan.
6. **Iterate on request.** If the human asks for changes, relaunch the planner with their feedback and present the result again. When they approve, set `plan_approved` in `state.json`, with `stage` at `acceptance-tests` and the three stages done.

Close by naming the next step: `/ai-enabler:deliver <KEY>` continues from the approved plan (it resumes the run at the acceptance tests, then the implementation and the rest), or `/ai-enabler:implement <KEY>` runs only the acceptance tests and the implementation.

## When the run already has an approved plan

Asking for a plan again does not overwrite it. If `plan_approved` is set and the person wants something changed, that is a delta: launch the planner with `mode: delta` and the change, present the delta as `${CLAUDE_PLUGIN_ROOT}/skills/deliver/SKILL.md` describes under "Going back", and on approval record it in `state.json`. Carrying it out — tests first, then code — is for `/ai-enabler:deliver <KEY>` or `/ai-enabler:implement <KEY>`.

## Rules

- No code, no branch, no commit, no Jira write.
- Do not plan in your own context: the planner subagent writes the plan, you present it.
- The ticket's readiness verdict is part of the answer. A plan built on a blocked ticket must say so at the top.
