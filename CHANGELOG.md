# Changelog

Notable changes to the ai-enabler marketplace and its plugins.

Each release is a version of the marketplace (the `VERSION` file). Plugins and their skills and agents carry versions of their own, which move independently; every entry says which plugin it concerns and the version that plugin reached. Plugin, skill and agent versions follow [semantic versioning](https://semver.org): a fix is a patch, new compatible behaviour is a minor, anything that breaks existing use is a major. The marketplace version moves more slowly — a breaking release of one plugin is a minor here, and shows as **Breaking** in the entry. The rules for bumping are in [AGENTS.md](AGENTS.md).

Entries are grouped as **Breaking**, **Added**, **Changed** and **Fixed**, newest release first.

## [1.1.0] — 2026-10-08

`ai-enabler` 1.0.1 · `ai-enabler-metrics` 1.0.0 (was `ai-enabler-kpi` 0.2.1)

### Breaking

- **ai-enabler-metrics:** the plugin `ai-enabler-kpi` is renamed `ai-enabler-metrics`, because most of what it measures are metrics, not KPIs, and its skills and agent take area-first names. Install `ai-enabler-metrics` and uninstall `ai-enabler-kpi`.

  | Before | From this release |
  |---|---|
  | `/ai-enabler-kpi:kpi-init` | `/ai-enabler-metrics:metrics-usage-init` |
  | `/ai-enabler-kpi:kpi-report` | `/ai-enabler-metrics:metrics-usage-report` |
  | `/ai-enabler-kpi:delivery-report` | `/ai-enabler-metrics:metrics-delivery-report` |
  | `/ai-enabler-kpi:pr-size` | `/ai-enabler-metrics:metrics-pr-size` |
  | `/ai-enabler-kpi:review-wait` | `/ai-enabler-metrics:metrics-review-wait` |
  | `/ai-enabler-kpi:rework` | `/ai-enabler-metrics:metrics-rework` |
  | `/ai-enabler-kpi:cycle-time` | `/ai-enabler-metrics:metrics-cycle-time` |
  | agent `jira-collector` | `metrics-jira-collector` |

- **ai-enabler-metrics:** the project folder is `.enabler/metrics/` instead of `.enabler/kpi/`, the variables are `ENABLER_METRICS_DIR` and `ENABLER_METRICS_USER`, the usage report writes `usage.json` instead of `kpi.json`, and the script flag is `--metrics-dir`. Nothing recorded is lost and nothing has to be done at once: a project that still has `.enabler/kpi/` keeps being captured and reported from there, the old variables and `--kpi-dir` are still accepted, and `metrics-usage-init` offers to rename the folder. A tool that reads `kpi.json` has to read `usage.json`. `ENABLER_KPI_DEBUG` becomes `ENABLER_METRICS_DEBUG`, also still accepted.
- **ai-enabler-metrics:** file paths change with the plugin name: the scripts are under `plugins/ai-enabler-metrics/scripts/` and `kpi_report.py` is `usage_report.py`, the hook `kpi_hook.py` is `usage_hook.py`, and `docs/kpi-reference.md` is `docs/metrics-reference.md`. A job that runs the report script by its path has to be updated.

### Added

- **ai-enabler-metrics:** KPIs in the strict sense. A delivery metric becomes a KPI when the team sets a target for it under `delivery.targets` (pull request size, review waiting time, rework rate, cycle time). The dashboard gives a verdict per target — met or not met only when the whole 90 % interval is on one side of it, inconclusive otherwise.
- **ai-enabler-metrics:** `metrics-stale-assets` lists every installed skill and agent with its owner, version, last use and number of uses, and marks the ones unused for 90 days or without an owner, for the quarterly pruning. The same table closes the usage report, always computed on everything recorded (`--assets-dir` adds another plugin or folder to it).
- **ai-enabler-metrics:** the dashboard writes its verdicts to `delivery/kpis.json`.
- **ai-enabler-metrics:** every skill and the agent carry `metadata.owner` and `metadata.version`.

### Changed

- **ai-enabler-metrics:** usage figures — cost, tokens, AI time, prompts, lines written by AI — are presented as context, never as targets. A target written on one of them is ignored and the dashboard says so.
- **ai-enabler-metrics:** events recorded under the old skill and agent names of this plugin are reported under the new ones.
- **ai-enabler-metrics:** a project that has both `.enabler/metrics/` and the old `.enabler/kpi/` is reported from both, with a note, so no history disappears.
- **ai-enabler:** `delivery-doctor` names the metrics plugin and its folder by their new names, and still recognises the old folder.
- **Marketplace:** both plugins now follow the naming and metadata convention; `tools/check_conventions.py` no longer treats one as pending.

## [1.0.0] — 2026-10-08

`ai-enabler` 1.0.0 · `ai-enabler-kpi` 0.2.1

### Breaking

- **ai-enabler:** every skill and agent is renamed to put the area first. Commands change as follows; nothing changes in a project's `.enabler/` folder, so a run started before the rename resumes after it.

  | Before | From 1.0.0 |
  |---|---|
  | `/ai-enabler:deliver` | `/ai-enabler:delivery-run` |
  | `/ai-enabler:plan` | `/ai-enabler:delivery-plan` |
  | `/ai-enabler:implement` | `/ai-enabler:delivery-implement` |
  | `/ai-enabler:test` | `/ai-enabler:delivery-test` |
  | `/ai-enabler:review` | `/ai-enabler:delivery-review` |
  | `/ai-enabler:ship` | `/ai-enabler:delivery-ship` |
  | `/ai-enabler:doctor` | `/ai-enabler:delivery-doctor` |

  The six agents take the same prefix: `ticket-analyst` becomes `delivery-ticket-analyst`, and likewise `repo-scout`, `solution-planner`, `code-implementer`, `test-engineer` and `code-reviewer`.

### Added

- **ai-enabler:** every skill and agent carries `metadata.owner` (`Name <email>`) and `metadata.version` in its frontmatter.
- **Marketplace:** a `VERSION` file, this changelog, and `AGENTS.md` with the rules for changing the repository: three independent version levels (marketplace, plugin, skill or agent), bumped in the same commit as the change.
- **Marketplace:** `tools/check_versions.py` fails when a change does not carry its version bump or its changelog entry; `tools/check_conventions.py` checks name, owner and version of every skill and agent. The `ai-enabler-kpi` plugin has not adopted the naming and metadata yet and is reported as pending.
- **Marketplace:** the AI4IT SWAT framework manual the marketplace follows is kept in `docs/reference/`, with a page mapping each of its standards to where it is implemented.
- **ai-enabler:** the README documents every file of the `.enabler/` folder, and the pipeline diagram shows the loops at both gates.

### Changed

- **ai-enabler:** a delta is copied aside before it is written (`deltas/delta-NN.before/`), so `adjust` revises the same delta and `cancel` restores the plan and the acceptance criteria exactly.
- **ai-enabler:** each delta records whether it is approved and whether it is applied; approving one sets the run back to the acceptance-tests stage, and `delivery-run` and `delivery-implement` carry out a pending delta before anything else.
- **ai-enabler:** a delta always needs approval, also in a run configured without gates, and its acceptance step runs even when the ticket itself stated no criteria.
- **ai-enabler:** three rounds at a gate run normally and the hand-over is offered when a fourth is asked; `--max-rounds` overrides the limit for one run. The review's automatic fix budget applies per review pass.
- **ai-enabler:** git history is never rewritten, pushed or not.
- **ai-enabler-kpi:** the usage report shows events recorded under the old skill and agent names under the new ones, so the rename does not split the history.

### Fixed

- **ai-enabler:** acceptance criteria removed by a delta are no longer treated as in force: no test is written for them, the review does not report them as unmet, and test removals a delta lists are not review findings.
- **ai-enabler:** `delivery-ship` no longer fails when the work was already committed locally and only the push is left.

## [0.4.0] — 2026-10-07

`ai-enabler` 0.2.0 · `ai-enabler-kpi` 0.2.0

### Added

- **ai-enabler:** deltas. A change of scope, behaviour or acceptance criteria after the plan is approved is written as `deltas/delta-NN.md`, listing what is added and what is removed, approved at the plan gate and carried out acceptance tests first — obsolete tests deleted — then code, with dead code deleted. The pull request gets a "Changes after the plan was approved" section.
- **ai-enabler:** rounds are counted per gate (`adjust` at the plan gate, `fix` at the ship gate), with a configurable limit (`max_gate_rounds`, 3) after which the pipeline offers to hand over.
- **ai-enabler:** a correction at the ship gate that leaves the plan true runs implementer, coverage and the affected review lenses before returning to the gate.

### Changed

- **ai-enabler:** nothing is committed during a run; the ship stage makes one commit for the finished change and a later delta is one further commit.

## [0.3.0] — 2026-10-06

`ai-enabler` 0.2.0 · `ai-enabler-kpi` 0.2.0

### Added

- **ai-enabler-kpi:** delivery-flow metrics, each a skill over a bundled script: `pr-size`, `review-wait` and `rework` (GitHub, read with the GitHub CLI) and `cycle-time` (Jira), plus `delivery-report`, which runs them all and builds one dashboard. Per week or sprint, per area or issue type, and per developer.
- **ai-enabler-kpi:** reports are self-contained HTML with charts, including the AI usage report.
- **ai-enabler:** local-only mode. When a person refuses to upload, a marker file switches the project to local-only and a hook blocks pushes, pull-request and API writes, and MCP writes to GitHub, GitLab, Bitbucket, Jira and Confluence, until the person removes the marker by hand.

### Fixed

- **ai-enabler:** the local-only hook recognises pushes on a new line, inside `bash -c` or `eval`, behind wrappers and through `git subtree`, `git lfs` and `hub`, and no longer lets the marker or the configuration be removed or edited. It stops blocking read-only commands.
- **ai-enabler-kpi:** review waiting time counts dismissed reviews and ignores reviews submitted after the merge.
- **ai-enabler-kpi:** rework no longer takes look-alikes such as `UTF-8` for ticket keys, and a pull request is classified the same whatever the window.
- **ai-enabler-kpi:** cycle time keeps tickets resolved between two sprints, drops duplicate records and counts a return through a blocked status as a backward move.
- **ai-enabler-kpi:** running a delivery report no longer switches usage capture on, and `show_people: false` removes people from the snapshot files as well as from the HTML.

## [0.2.0] — 2026-10-06

`ai-enabler` 0.1.0 · `ai-enabler-kpi` 0.1.0

### Added

- **ai-enabler:** acceptance tests are written from the ticket's criteria before the code; the implementer makes them pass and may not edit them. Coverage of the changed code is judged against an 80 % target and a 70 % minimum, and below the minimum a person decides whether to proceed.
- **ai-enabler:** each subagent names its model: Opus at high effort for planning and review, Sonnet for intake, scout, implementation and tests.
- **ai-enabler-kpi:** cost is priced per provider, with Amazon Bedrock rates by region and inference-profile scope read from the AWS Price List (`update_pricing.py`).

### Fixed

- **ai-enabler-kpi:** AI working time counts subagents that run in the background; switching capture on in the middle of a session no longer bills what was spent before; a project price file is layered over the bundled table instead of replacing it.
- **ai-enabler:** the stand-alone review fixes code only when asked, and an unattended run never ships a result that is not ready.

## [0.1.0] — 2026-10-06

`ai-enabler` 0.1.0 · `ai-enabler-kpi` 0.1.0

### Added

- **ai-enabler:** the delivery pipeline. A Jira ticket, read through MCP, or a requirements file is taken to a pull request by dedicated subagents — intake, repository scout, planner, implementer, test engineer and parallel read-only reviewers — with two human gates, the plan and the ship.
- **ai-enabler-kpi:** opt-in hooks that record human interaction, AI working time and token usage, and a report with cost in USD per session, user, ticket, skill, agent and model.
