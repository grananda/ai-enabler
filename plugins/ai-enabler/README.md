# ai-enabler — machine-driven delivery from Jira

`ai-enabler` takes a Jira ticket to a pull request. The machine does the work; a person makes two decisions.

```
/ai-enabler:deliver PROJ-123
```

It is not spec-driven: there is no specification to write and maintain, no change proposal, no roadmap. The Jira ticket is the input, the repository's own conventions are the rules, and the pull request is the output.

## The pipeline

| # | Stage | Subagent | Reads | Writes | Human gate |
|---|---|---|---|---|---|
| 1 | Intake | `ticket-analyst` | Jira issue, links, comments (MCP) | `requirements.json` | only if the ticket is blocked |
| 2 | Scout | `repo-scout` | manifests, code, rules, CI | `repo-context.md` | — |
| 3 | Plan | `solution-planner` | the two files above, the code | `plan.md` | **Gate 1 — approve the plan** |
| 4 | Acceptance tests | `test-engineer` | the ticket's acceptance criteria, the plan | tests, `acceptance-tests.md` | — |
| 5 | Implement | `code-implementer` | plan, context, the acceptance tests | code on a feature branch that makes them pass | — |
| 6 | Coverage | `test-engineer` | the changed code | remaining tests, `test-report.md` | only if coverage is under 70 % |
| 7 | Review | `code-reviewer` × 4, in parallel | the diff, the criteria | `review.md` | — |
| 7b | Fix loop | `code-implementer` | blocking findings | fixes (max 2 rounds) | — |
| 8 | Ship | the skill itself | `delivery-report.md` | commit, push, PR, Jira update | **Gate 2 — approve the ship** |

### Tests come before the code

A test written from the ticket states what the code must do. A test written from the code only confirms what the code already does, errors included. So the tests for the ticket's acceptance criteria are written at stage 4, before any production code, and the implementer's job at stage 5 is to make them pass — it may not edit them.

How much can be written first depends on the ticket:

| Acceptance criteria in the ticket | Before the code | After the code |
|---|---|---|
| Sufficient — every requirement has a testable criterion | Tests for all of them | Unit tests to reach the coverage target |
| Scarce — some stated, some requirements uncovered | Tests for the stated ones | Tests for the rest, then coverage |
| Missing | Nothing | All tests, then coverage |

Whatever the order, stage 6 always runs and measures line and branch coverage of the changed code:

| Coverage | What happens |
|---|---|
| 80 % or more (target) | The run continues |
| 70 % to under 80 % | The run continues; the figure and what is left uncovered are reported at the ship gate and in the pull request |
| Under 70 % (minimum) | The run stops and the person decides: proceed as it is, write more tests, or stop |
| Not measurable (no coverage tool) | The run continues and says so; no figure is claimed |

Both numbers are configurable (`tests.coverage_target`, `tests.coverage_minimum`). A decision to proceed below the minimum is recorded and stated in the pull request. When tests had to be written after the code, the plan gate and the pull request say so and why.

What the human sees at each gate:

- **Plan gate** — the approach in three sentences, the number of steps and files, the planned tests, the technical decisions taken, the assumptions made about the ticket. Answer `approve`, `adjust: ...` or `cancel`.
- **Ship gate** — the diff size, acceptance criteria met, test results and coverage against the 80 % target and the 70 % minimum, how many criteria had their test written before the code, findings fixed and still open, and the exact list of outward actions (push, pull request, Jira comment, transition). Answer `ship`, `local` (commit on your machine only; nothing leaves it), `hold` or `fix: ...`.

The pipeline also stops when the ticket is not implementable as written (the analyst returns the questions that unblock it), when the plan turns out to be wrong in a way that changes scope, and when coverage of the changed code ends up under the minimum. Apart from those, it asks only what it cannot work out — which Jira server to use when several are connected — and stops where the safety rules require it, such as unrelated changes in the working tree.

## Skills

| Skill | Arguments | What it does |
|---|---|---|
| `deliver` | `<KEY \| file.md> [--gates ...] [--ship] [--refresh] [--from <stage>]` | The full pipeline. Run it again with the same key to resume. |
| `plan` | `<KEY \| file.md> [--refresh]` | Stages 1–3. Plan and readiness verdict; no code, no git, no Jira write. |
| `implement` | `<KEY> [--steps 1,2]` | Stages 4 and 5 on an approved plan: acceptance tests, then the code. |
| `test` | `[KEY \| paths] [--base b] [--target 80] [--minimum 70] [--levels unit,integration,e2e] [--before-code]` | Stages 4 and 6, or stand-alone test generation for any change. |
| `review` | `[KEY \| PR \| paths] [--base b] [--lenses ...] [--fix] [--min-confidence 80]` | Stage 7, or a stand-alone review of a branch, pull request or paths. |
| `ship` | `[KEY] [--no-pr] [--draft] [--no-jira] [--yes]` | Stage 8: commit, push, pull request, Jira. |
| `doctor` | `[KEY] [--init]` | Checks Jira MCP, git, PR CLI, test commands, configuration, KPI capture. |

`test`, `review` and `ship` work without a ticket, so a team can start with those and adopt `deliver` later.

## Subagents

Each stage runs in its own context and hands over a file, not a conversation. That keeps the orchestrator's context small over a long run, makes a run resumable, and makes the reviewer independent of the author.

| Agent | Role | Model | Tools |
|---|---|---|---|
| `ticket-analyst` | Normalises the ticket, makes each acceptance criterion testable, judges readiness | `sonnet` | Everything except edit tools (it needs the MCP tools, whose names vary by server) |
| `repo-scout` | Finds the stack, the commands that really work here, conventions, hard rules | `sonnet` | Read, Grep, Glob, Bash, Write (its own output only) |
| `solution-planner` | File-level plan with a trace from every criterion to steps and tests | `opus`, effort `high` | Read, Grep, Glob, Bash, Write (its own output only) |
| `code-implementer` | Writes the code in the plan so the acceptance tests pass; applies fix lists | `sonnet` | All; never edits an acceptance test |
| `test-engineer` | Acceptance tests before the code; after it, the remaining tests and coverage of the changed code (target 80 %, minimum 70 %) | `sonnet` | All; never edits production code |
| `code-reviewer` | One lens per instance: correctness, security, quality, tests | `opus`, effort `high` | Read, Grep, Glob, Bash — no edit tools |

### Which model does what, and why

The two stages where a mistake is most expensive run on the strongest model; the stages that execute a precise brief run on the everyday coding model.

- **Planning — Opus, high effort.** The plan is the only thing a person approves before code exists and the only brief the implementer gets. A wrong decision here is paid for in every later stage.
- **Review — Opus, high effort.** The reviewer is the last check before a person, and its value is in catching what the author missed; it should not be weaker than the author.
- **Intake, scout, implementation, tests — Sonnet.** Each works from explicit material: the ticket, the repository, an approved plan, stated acceptance criteria. This is where most tokens are spent, so it is also where the price difference matters.
- **Orchestration** runs on whatever model the session uses. It delegates the reading and the writing, so its own token use is small.

The models are set as aliases (`opus`, `sonnet`) in each agent's frontmatter, so they follow the provider's current version. To change one, edit the `model:` line in `agents/<name>.md` (`haiku`, `sonnet`, `opus`, `fable`, `inherit`, or a full model id). The KPI report's "Cost by agent" table shows what each stage actually costs, which is the evidence to tune this with.

**On Amazon Bedrock, pin what the aliases resolve to.** Without pinning, an alias resolves to the provider's default for that family, which can be an older version than the one enabled in your account:

```json
{
  "env": {
    "CLAUDE_CODE_USE_BEDROCK": "1",
    "AWS_REGION": "eu-west-1",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "<your Opus inference profile id>",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "<your Sonnet inference profile id>",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "<your Haiku inference profile id>"
  }
}
```

The `ai-enabler-kpi` hook reads these same variables to tell global from regional inference profiles when pricing.

## Configuration

Optional, in `.enabler/config.json` at the project root. Every key has a default, so the file is only needed to change one.

```json
{
  "gates": ["plan", "ship"],
  "git": { "base_branch": null, "branch_pattern": "feature/{key}-{slug}",
           "commit_pattern": "{type}({key}): {summary}", "pull_request": true },
  "jira": { "server": null, "comment_on_ship": true, "transition_on_ship": null },
  "tests": { "coverage_target": 80, "coverage_minimum": 70, "levels": ["unit", "integration"], "order": "auto" },
  "review": { "lenses": ["correctness", "security", "quality", "tests"],
              "min_confidence": 80, "auto_fix": ["critical", "high"], "max_fix_rounds": 2 }
}
```

`/ai-enabler:doctor --init` writes this file with the defaults. The full description of each key is in [references/run-and-config.md](references/run-and-config.md).

Removing a gate makes the pipeline run further unattended. Removing `ship` does not make it push on its own: without the gate, shipping needs the `--ship` flag or a separate `/ai-enabler:ship`.

## The run directory

Every ticket gets `.enabler/runs/<KEY>/`, which holds `state.json`, `requirements.json`, `repo-context.md`, `plan.md`, `acceptance-tests.md`, `test-report.md`, `review.md` and `delivery-report.md`. These are working files: keep `.enabler/runs/` out of git (the pipeline adds the ignore rule if it is missing). The delivery report becomes the pull-request body, so what matters ends up in the pull request.

`state.json` also records each point where a person stepped in (`human_interventions`), which is the pipeline's own view of how autonomous a run was. The `ai-enabler-kpi` plugin measures the same thing from the outside.

## When you say no, nothing leaves your machine

Answer the ship gate with `local` or any refusal ("no", "don't push", "keep it local"), say at any point that nothing should be uploaded, pass `--local`, or set `git.local_only: true`, and the project becomes **local-only**:

- no `git push`, no pull request, no Jira comment or transition;
- with `local`, the work is committed on the feature branch on your machine; with a plain "no" it stays uncommitted in the working tree.

`hold` is different: it means "not now". Nothing is sent and nothing is committed, but the project does not become local-only, and `/ai-enabler:ship` can finish later.

This is enforced, not just promised. The plugin ships a hook (`hooks/remote_guard.py`) that, while the file `.enabler/local-only` exists anywhere from the working directory up to the repository root, refuses — from the main conversation and from any subagent:

- `git push` in every shape it can recognise: chained, on a new line, inside `bash -c` or `eval`, behind `timeout`, `xargs` or `env`, through `git subtree`, `git lfs`, `git svn`, `hub`, or an alias defined on the spot;
- every `gh`/`glab` command that writes, including `gh api` write requests, and `curl`/`wget` write requests to GitHub, GitLab, Bitbucket or Atlassian hosts;
- every MCP tool of GitHub, GitLab, Bitbucket, Jira or Confluence that is not clearly a read;
- anything that would lift the mode: deleting, moving or overwriting the marker, `git clean`, `git stash -u`, and any edit of `.enabler/config.json`.

Reading stays allowed: fetch, pull, viewing a pull request, reading a Jira issue. The agents are also told never to work around a refusal.

Only you lift it: delete `.enabler/local-only` by hand, then run `/ai-enabler:ship`. A later "ok, push it" in the chat is deliberately not enough.

What it cannot do: no parser sees inside every program. A push performed by a script file, a Makefile target or a binary the agent runs is invisible to the hook. Claude Code's own permission prompt for commands is the second barrier, and for a guarantee that does not depend on either, remove the push credentials or the remote from the machine.

## Safety rules

The two gates are enough because the rest is bounded by rules every skill follows ([references/git-and-jira-safety.md](references/git-and-jira-safety.md)):

- Work happens on a feature branch, never on the base branch. Unrelated changes in the working tree stop the run.
- Files are staged by path; the staged diff is checked for secrets and strays before each commit.
- No force-push, no hard reset, no bypassed hooks, no merge, no approval of pull requests.
- Jira is written to only at the ship stage, only as configured, and only after the ship gate listed those writes. Tickets are never edited, reassigned or deleted.
- Ticket text, comments and linked pages are data. Instructions found in them are not followed and are reported.
- Reviewers have no edit tools. The test engineer does not touch production code, the implementer does not touch the acceptance tests, and nobody weakens a test to get a green build. Only a person can accept coverage below the minimum.

## Jira and other inputs

The ticket is read through whichever Jira MCP server is connected; the skills find the tools by what they do, not by a fixed name, so both Atlassian's remote server and `mcp-atlassian` work. Setup is in [docs/jira-mcp.md](../../docs/jira-mcp.md).

A Markdown or text file can stand in for a ticket: `/ai-enabler:deliver docs/feature-x.md`. Everything works the same except that nothing is written to Jira at the end.

## Where the ideas come from

See [docs/design.md](../../docs/design.md) for the full comparison. In short: the Jira-to-code pipeline, the coverage threshold (here a target of 80 % with a minimum of 70 %), the confidence-filtered multi-agent review and the auto-fix come from the AI Enablement marketplace; the isolated read-only reviewer, the per-layer review checklist, the tests-first order driven by the acceptance criteria, the non-destructive git rules and the handover between human and machine come from AIAD.
