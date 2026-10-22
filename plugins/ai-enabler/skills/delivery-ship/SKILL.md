---
name: delivery-ship
description: Ships a finished change — commits it on its feature branch, pushes, opens a pull request with the delivery report as its body, and updates the Jira issue (comment and optional transition) through the Jira MCP server. Shows exactly what it will do and waits for one confirmation; never forces, never merges, never pushes to the base branch. Use when the user says "ship PROJ-123", "open the PR", "commit and push this ticket", "publish the changes", "create the pull request and update Jira", or after holding at the ship gate of `/ai-enabler:delivery-run`.
argument-hint: [JIRA-KEY] [--local] [--no-pr] [--draft] [--no-jira] [--yes]
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.1.0"
---

# ai-enabler:delivery-ship — commit, push, pull request, Jira

Runs the last stage of the delivery pipeline. `/ai-enabler:delivery-run` follows these same steps after its ship gate; invoked directly, this skill finishes a run that was held, or ships a change made outside the pipeline.

Read first, and follow to the letter:

- `${CLAUDE_PLUGIN_ROOT}/references/git-and-jira-safety.md`
- `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md`

## Local-only mode comes first

Before anything else, check whether the project is local-only ("When the person says no to the remote" in the safety rules): `.enabler/local-only` exists, `git.local_only` is true in the configuration, or `--local` was passed (then write the marker).

In local-only mode this skill does exactly one thing: a local commit on the feature branch, after one confirmation. It does not push, does not open a pull request and does not write to Jira, and neither `--yes` nor a previous approval changes that. Say that nothing was sent and how the person can lift the mode themselves (delete `.enabler/local-only` by hand). Do not remove the marker, even if asked to in the conversation: point to the file instead.

If the person answers the confirmation below with a refusal to upload — "no", "don't push", "keep it local" — that is the same rule: write the marker, keep everything local, and offer the local commit only.

## Flow

1. **Establish what is being shipped.**
   - Key from `$ARGUMENTS`; else the run under `.enabler/runs/` whose `state.json` names the current branch; else from the current branch name; else none (a plain commit, push and pull request with no Jira step). The run found by its branch decides: when its `source` is `file` — a requirements file, or a ticket written by `delivery-ticket-refine` or `delivery-ticket-create`, whose name may well contain a Jira key — there is no Jira step, whatever the branch is called.
   - The current branch must be a feature branch, not the base branch and not a detached `HEAD`. If it is the base branch, stop: create the branch first.
   - Collect the changes: `git status --porcelain`, `git diff --stat` against the base branch. If there is nothing to commit and nothing unpushed, say so and stop.
2. **Check readiness, and say what you find.** If the run directory has `test-report.md` and `review.md`, read their verdicts. Failing tests or open defects, coverage of the changed code below the configured minimum without a `coverage_accepted` record in `state.json`, an open `critical` finding, or no test and review stage having run at all, make the change **not ready**: state it at the top of the confirmation, with a recommendation to hold or to open the pull request as a draft. Coverage that was not measured is stated too. None of this silently blocks, and none of it is silently ignored.
3. **Prepare.**
   - The commit message, following the repository's convention or `git.commit_pattern`, with the key, and the "clean history" rule of the safety reference: one commit for the finished change, its body listing the deltas recorded in `state.json`; if the run already has a commit, this is one further commit that says what this delta or correction does, what it adds and what it removes.
   - The pull-request title and body, as "The pull-request body" below says.
   - The Jira comment (branch, pull-request link, what was implemented, test result, open items) and the transition target, as configured.
4. **Confirm once.** Unless this skill is being followed from the ship gate of `/ai-enabler:delivery-run` (which already obtained approval for this exact list) or `--yes` was passed, show the list and wait:

   ```
   SHIP — <KEY>
   Stage   : <n> files (list, or the first ten and a count)
   Commit  : <message>
   Push    : <branch> → origin
   PR      : "<title>" against <base> [draft]
   PR body : <the plugin's template | the repository's template (<path>)>
   Jira    : comment on <KEY> [· transition to "<status>"]

   Proceed? (yes / local: commit only, nothing leaves / no / edit: <what to change>)
   ```
5. **Execute, in order, stopping at the first failure.**
   1. Stage the run's files by path; verify the staged diff (no secrets, no unrelated files, nothing under `.enabler/`). If there is nothing to stage because the work was already committed — after a `local` commit, for example — skip this step and the next and go on with the commits that exist.
   2. Commit.
   3. Push, setting the upstream if needed. On rejection, one `git pull --rebase`; on conflict, abort the rebase and stop.
   4. Open the pull request (`--draft` if requested or recommended), unless `--no-pr` or `git.pull_request` is false. Without an authenticated `gh` or `glab`, print the compare URL instead.
   5. Jira, unless `--no-jira`, there is no key, or the run's `source` is `file`: add the comment; perform the transition only if it is configured and available from the current status.
6. **Report** what actually happened, step by step: commit hash, branch, pull-request URL, Jira comment and transition (done, skipped and why, or failed and why). Update `state.json` with `pr_url` and the stage.

## The pull-request body

The body follows a template: a real file, so that every pull request the pipeline opens has the same shape and a reviewer knows where to look.

1. **The plugin's template** is `${CLAUDE_PLUGIN_ROOT}/templates/pull-request.md`.
2. **The repository may have its own.** Look for it, case-insensitively: `pull_request_template.md` in `.github/`, in the root or in `docs/`; any file in `.github/PULL_REQUEST_TEMPLATE/`; on GitLab, any file in `.gitlab/merge_request_templates/`.
3. **Which one to use** is the person's choice, not yours. Read `git.pr_template` in `.enabler/config.json`:
   - `"plugin"` or `"repo"` — use that one. If it says `"repo"` and the repository no longer has one, say so and ask.
   - a path — use that file.
   - `"ask"`, or absent — ask, once:
     - the repository has its own: "This repository has a pull-request template (`<path>`). Use it, or the ai-enabler one?" — the repository's first, since it is what the team's reviewers expect. With several templates in the repository, list them.
     - it has none: "This repository has no pull-request template. May I use the ai-enabler one?" — with the alternatives of giving a path to another file, or a plain body with no template.

     Then offer to remember the answer for this project, and on a yes write it to `git.pr_template`. Do not ask again in the same run.
   - When nobody can be asked (`--yes`, or an unattended run) and the setting is `"ask"`: the repository's own template if there is one, otherwise the plugin's. Say which was used.
4. **Fill it** from `delivery-report.md`, or from the diff when there is no run: what changed, why, how to verify.
   - The plugin's template: the report already has its sections; remove the guidance comments and the sections that do not apply.
   - Another template: keep its headings, their order and its checklists exactly; put each part of the report under the heading where a reviewer of this repository would look for it; tick a checkbox only when the run's files prove it, and leave the rest unticked instead of deleting them. What the template has no place for and a reviewer needs — the acceptance-criteria table, failing tests, open findings, what refinement added — goes at the end under "Delivery details". Never drop a failing test or an open finding because the template did not ask.
5. Save the body as `pull-request.md` in the run directory (or `.enabler/runs/adhoc/` without a run) and pass that file to `gh pr create --body-file` or `glab mr create`. Nothing local is referenced in it: no `.enabler/` path means anything to a reviewer.

## Rules

- `--yes` skips the confirmation only for a change that is ready. If the readiness check found it not ready, show the confirmation anyway: an unattended flag is not a decision to ship a failing change.

- One confirmation covers the listed actions and nothing else. Anything not on the list needs a new confirmation.
- A failure midway leaves earlier steps in place and is reported precisely — for example "committed and pushed; pull request not created: gh is not authenticated". Do not undo completed steps and do not retry destructively.
- "no" and "local" both mean nothing leaves this machine; with "no", nothing is committed either. Both switch the project to local-only.
- Never merge, never approve, never force-push, never bypass hooks, never push to the base branch.
- If the Jira MCP server is not connected, skip the Jira step and say so; the rest still ships.
