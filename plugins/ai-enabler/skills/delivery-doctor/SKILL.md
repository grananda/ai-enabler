---
name: delivery-doctor
description: Checks that a project is ready for the ai-enabler delivery pipeline and helps set it up — Jira MCP connection, git remote and pull-request CLI, test and coverage commands, project configuration, and whether usage capture is active. Read-only unless asked to write the configuration. Use when the user says "set up ai-enabler", "check my ai-enabler setup", "why can't it read my Jira ticket", "is Jira connected", "ai-enabler doctor", or before the first `/ai-enabler:delivery-run` in a repository.
argument-hint: [JIRA-KEY to test with] [--init]
metadata:
  owner: "Julio Fernandez <jfejimen@nttdata.com>"
  version: "1.1.0"
---

# ai-enabler:delivery-doctor — is this project ready?

A quick preflight for a repository. It reports; it changes nothing unless `--init` is passed or the human asks.

## Checks

Run them all, then print one table: check, status (`ok`, `warn`, `missing`), and what to do about it.

1. **Git.** Inside a repository; a remote exists; the base branch can be determined; the working tree state.
2. **Pull requests.** `gh` (or `glab`) installed and authenticated (`gh auth status`). Missing is a warning: the pipeline can still push and print a compare URL.
3. **Jira MCP.** Look through the tools available in this session for one that fetches a Jira issue by key (for example `getJiraIssue` on Atlassian's remote server, or `jira_get_issue` on `mcp-atlassian`). Report which server provides it, or that none is connected. If a key was given in `$ARGUMENTS`, fetch it and report the title and status as proof that reading works. Also note whether tools for adding a comment and for transitioning an issue are present, since the ship stage uses them.
4. **Confluence MCP (optional).** Present or not; only needed when tickets point to Confluence pages for their specification.
5. **Build and tests.** From the manifests and the project's docs, identify the build, test and coverage commands. Do not run the suite; report what was found and what is missing (no tests, no coverage tool).
6. **Project rules.** Whether `CLAUDE.md`, `AGENTS.md` or contribution guidelines exist for the agents to follow.
7. **Repository profile.** Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/repo_profile.py" check` and report whether the repository has been learned (`missing`, `unrecorded`, `fresh`, `stale` with the files that changed), where it is kept (`root`), how many deltas it has, how long the profile is, and anything under `suggest_relearn`. Do not build, record or rebuild it here.
8. **Configuration.** Whether `.enabler/config.json` exists and parses; list any key that differs from the defaults in `${CLAUDE_PLUGIN_ROOT}/references/run-and-config.md`. Whether `.enabler/runs/` and `.enabler/repo-profile/` are kept out of git: `git check-ignore -q .enabler/runs/x .enabler/repo-profile/x` (the check in step 7 has just put a `.gitignore` inside each).
9. **Local-only mode.** Whether `.enabler/local-only` exists (show its line) or `git.local_only` is true. If so, say that pushes, pull requests and Jira writes are blocked for this project, and that only the person lifts it by deleting the file.
10. **Usage capture.** Whether the `ai-enabler-metrics` plugin is installed (its skills are listed in this session) and whether `.enabler/metrics/` — or `.enabler/kpi/`, its name before the metrics plugin's 1.0.0 — exists in the project, which is what switches capture on.

## When something is missing

- **No Jira MCP server.** Explain that the pipeline reads tickets only through MCP, and point to `docs/jira-mcp.md` in the marketplace repository, which has ready-to-copy configurations for Jira Cloud (Atlassian's remote MCP server, OAuth in the browser) and for Jira Data Center (`mcp-atlassian` with a personal access token kept in the environment). Do not ask for credentials in the chat and do not write tokens into any file.
- **No configuration.** The defaults work. With `--init`, or if the human wants one, write `.enabler/config.json` with the defaults, filling in the detected base branch. Nothing is added to the project's `.gitignore`: the two working folders ignore themselves. Ask only for what cannot be detected and matters: the Jira status name for the optional transition at ship.
- **Usage capture off.** Mention `/ai-enabler-metrics:metrics-usage-init`.

Close with the verdict in one line: ready, ready with warnings, or not ready and the one thing to fix first.
