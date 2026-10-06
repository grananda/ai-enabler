---
name: ship
description: Ships a finished change — commits it on its feature branch, pushes, opens a pull request with the delivery report as its body, and updates the Jira issue (comment and optional transition) through the Jira MCP server. Shows exactly what it will do and waits for one confirmation; never forces, never merges, never pushes to the base branch. Use when the user says "ship PROJ-123", "open the PR", "commit and push this ticket", "publish the changes", "create the pull request and update Jira", or after holding at the ship gate of `/ai-enabler:deliver`.
argument-hint: [JIRA-KEY] [--no-pr] [--draft] [--no-jira] [--yes]
---

# ai-enabler:ship — commit, push, pull request, Jira

Runs the last stage of the delivery pipeline. `/ai-enabler:deliver` follows these same steps after its ship gate; invoked directly, this skill finishes a run that was held, or ships a change made outside the pipeline.

Read first, and follow to the letter:

- `${CLAUDE_PLUGIN_ROOT}/references/git-and-jira-safety.md`
- `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md`

## Flow

1. **Establish what is being shipped.**
   - Key from `$ARGUMENTS`, else from the current branch name, else none (a plain commit, push and pull request with no Jira step).
   - The current branch must be a feature branch, not the base branch and not a detached `HEAD`. If it is the base branch, stop: create the branch first.
   - Collect the changes: `git status --porcelain`, `git diff --stat` against the base branch. If there is nothing to commit and nothing unpushed, say so and stop.
2. **Check readiness, and say what you find.** If the run directory has `test-report.md` and `review.md`, read their verdicts. Failing tests, coverage of the changed code below the 70 % minimum without a recorded decision to proceed, coverage not measured, an open `critical` finding, or no test and review stage having run at all, are stated at the top of the confirmation — with a recommendation to hold or to open the pull request as a draft. They do not silently block and are not silently ignored.
3. **Prepare.**
   - The commit message, following the repository's convention or `git.commit_pattern`, with the key.
   - The pull-request title and body. The body is `delivery-report.md` when it exists; otherwise write one from the diff: what changed, why, how to verify.
   - The Jira comment (branch, pull-request link, what was implemented, test result, open items) and the transition target, as configured.
4. **Confirm once.** Unless this skill is being followed from the ship gate of `/ai-enabler:deliver` (which already obtained approval for this exact list) or `--yes` was passed, show the list and wait:

   ```
   SHIP — <KEY>
   Stage   : <n> files (list, or the first ten and a count)
   Commit  : <message>
   Push    : <branch> → origin
   PR      : "<title>" against <base> [draft]
   Jira    : comment on <KEY> [· transition to "<status>"]

   Proceed? (yes / no / edit: <what to change>)
   ```
5. **Execute, in order, stopping at the first failure.**
   1. Stage the run's files by path; verify the staged diff (no secrets, no unrelated files, no `.enabler/runs/`).
   2. Commit.
   3. Push, setting the upstream if needed. On rejection, one `git pull --rebase`; on conflict, abort the rebase and stop.
   4. Open the pull request (`--draft` if requested or recommended), unless `--no-pr` or `git.pull_request` is false. Without an authenticated `gh` or `glab`, print the compare URL instead.
   5. Jira, unless `--no-jira` or no key: add the comment; perform the transition only if it is configured and available from the current status.
6. **Report** what actually happened, step by step: commit hash, branch, pull-request URL, Jira comment and transition (done, skipped and why, or failed and why). Update `state.json` with `pr_url` and the stage.

## Rules

- One confirmation covers the listed actions and nothing else. Anything not on the list needs a new confirmation.
- A failure midway leaves earlier steps in place and is reported precisely — for example "committed and pushed; pull request not created: gh is not authenticated". Do not undo completed steps and do not retry destructively.
- Never merge, never approve, never force-push, never bypass hooks, never push to the base branch.
- If the Jira MCP server is not connected, skip the Jira step and say so; the rest still ships.
