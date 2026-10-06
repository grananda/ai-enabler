# Run directory and project configuration

Shared by every `ai-enabler` skill. Read it once at the start of a skill.

## Run directory

Each ticket gets one directory, `.enabler/runs/<KEY>/`, where `<KEY>` is the Jira key (or, for a Markdown source, the file name without extension). Stages talk to each other through these files, not through the conversation, which is what makes a run resumable and lets each subagent start with a clean context.

| File | Written by | Content |
|---|---|---|
| `state.json` | the orchestrating skill | Where the run is (see below) |
| `requirements.json` | `ticket-analyst` | Normalised ticket and readiness verdict |
| `repo-context.md` | `repo-scout` | Stack, commands, conventions, hard rules |
| `plan.md` | `solution-planner` | Approved implementation plan |
| `acceptance-tests.md` | `test-engineer` (acceptance mode) | The tests written before the code, one row per acceptance criterion |
| `test-report.md` | `test-engineer` (coverage mode) | Suite result, coverage against the target and the minimum, acceptance-criteria table |
| `review.md` | the review skill | Consolidated findings and what was fixed |
| `delivery-report.md` | the deliver skill | What the human reads at the ship gate; becomes the PR body |

`state.json`:

```json
{
  "key": "PROJ-123",
  "source": "jira | file",
  "started_at": "2026-10-06T09:30:00Z",
  "base_branch": "main",
  "branch": "feature/PROJ-123-short-slug",
  "stage": "intake | scout | plan | acceptance-tests | implement | test | review | ship | done",
  "test_order": "before | mixed | after",
  "stages_done": ["intake", "scout"],
  "plan_approved": false,
  "fix_rounds": 0,
  "human_interventions": [{ "at": "", "stage": "plan", "kind": "adjustment | question | takeover", "note": "" }],
  "pr_url": ""
}
```

Update `state.json` whenever a stage completes and whenever the human steps in. `human_interventions` is the pipeline's own record of where a person had to act; keep each note to one line.

`.enabler/runs/` holds working files and must stay out of commits. If `.gitignore` does not already exclude it, add the line `.enabler/runs/` before the first commit of a run and say that you did.

## Project configuration

Optional file `.enabler/config.json`, committed with the project. Every key is optional; the defaults below apply when the file or a key is absent. Never ask the human for a value that has a default.

```json
{
  "gates": ["plan", "ship"],
  "git": {
    "base_branch": null,
    "branch_pattern": "feature/{key}-{slug}",
    "commit_pattern": "{type}({key}): {summary}",
    "pull_request": true
  },
  "jira": {
    "server": null,
    "comment_on_ship": true,
    "transition_on_ship": null
  },
  "tests": {
    "coverage_target": 80,
    "coverage_minimum": 70,
    "levels": ["unit", "integration"],
    "order": "auto"
  },
  "review": {
    "lenses": ["correctness", "security", "quality", "tests"],
    "min_confidence": 80,
    "auto_fix": ["critical", "high"],
    "max_fix_rounds": 2
  }
}
```

- `gates` — where the pipeline stops for a human decision. `plan` is approval of the plan before any code is written; `ship` is approval before anything leaves the machine (push, pull request, Jira). An empty list runs unattended up to the ship stage, which then still requires an explicit `--ship` flag or the `ship` skill: nothing is pushed on the strength of a config file alone.
- `git.base_branch: null` — use the base branch `repo-scout` detected (the remote's default branch).
- `jira.server: null` — use the only connected Jira MCP server; ask once if several are connected.
- `jira.transition_on_ship` — the status to move the issue to once the pull request is open (for example `"In Review"`). `null` means do not transition.
- `tests.coverage_target` and `tests.coverage_minimum` — line and branch coverage of the changed code. The test engineer aims for the target (80); the minimum (70) is the lowest result the pipeline accepts on its own. At or above the target it is `met`. Between the minimum and the target it is `acceptable`: the run continues and the figure is reported. Below the minimum it is `below minimum`, and a person decides whether to proceed. See "Coverage" below.
- `tests.order` — `auto` writes the tests for the ticket's acceptance criteria before the code whenever the ticket states usable criteria, and falls back to writing tests after the code when it does not (see "Test order" below). `after` always writes them after the code. There is no setting that skips the coverage stage.
- `review.auto_fix` — severities the pipeline fixes on its own. Everything else is reported and left for the human.

Command-line flags on a skill override the file for that run.

## Test order

Tests are written before the code so that they encode what the ticket asks for, not what the code happens to do. What the ticket offers decides how far that can go — `acceptance_criteria_quality` in `requirements.json`:

| Criteria in the ticket | `test_order` | Before the code | After the code |
|---|---|---|---|
| `sufficient` | `before` | Tests for every stated criterion | Unit tests needed to reach the coverage target |
| `scarce` | `mixed` | Tests for the criteria that are stated | Tests for the requirements without a criterion, then coverage |
| `missing` | `after` | Nothing | All tests, derived from the requirements and the code, then coverage |

In every case the coverage stage runs after the code. With `tests.order: after` the first column is skipped whatever the ticket offers.

When tests had to be written after the code, the plan gate and the delivery report say so, with the reason: the reviewer should know those tests were not an independent statement of the requirement.

## Coverage

Coverage of the changed code (line and branch) is judged against two numbers: a **target of 80 %** and a **minimum of 70 %**. At or above the target it is `met`. Between the minimum and the target it is `acceptable`: the run continues and the figure is reported. Below the minimum it is `below minimum`, and a person decides whether to proceed.

| Coverage of the changed code | Verdict | What the pipeline does |
|---|---|---|
| ≥ 80 % (target) | `met` | Continues |
| 70 % to under 80 % | `acceptable` | Continues, and reports the figure and what is left uncovered at the ship gate and in the pull request |
| under 70 % (minimum) | `below minimum` | **Stops and asks the person**: proceed as it is, write more tests, or stop the run |
| no coverage tool in the project | `not measured` | Continues, says so at the ship gate; no coverage figure is claimed |

The stop below the minimum happens right after the coverage stage, before the review, and it applies even when no gates are configured: an unattended run does not carry a change under the minimum to a pull request on its own. The decision and the person's reason are recorded in `state.json` under `human_interventions` and shown in the delivery report.

## When there is no Jira MCP server

The pipeline needs to read the ticket. If no connected MCP server exposes a tool that fetches a Jira issue by key, say so and offer the two ways forward: connect one (see `docs/jira-mcp.md` in the marketplace repository; `/ai-enabler:doctor` checks the setup), or pass a Markdown file with the requirements instead of a key. Do not ask the human to paste credentials and do not call the Jira REST API directly.
