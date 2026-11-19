# Changelog

Notable changes to the ai-enabler marketplace and its plugins.

Each release is a version of the marketplace (the `VERSION` file). Plugins and their skills and agents carry versions of their own, which move independently; every entry says which plugin it concerns and the version that plugin reached. Plugin, skill and agent versions follow [semantic versioning](https://semver.org): a fix is a patch, new compatible behaviour is a minor, anything that breaks existing use is a major. The marketplace version moves more slowly — a breaking release of one plugin is a minor here, and shows as **Breaking** in the entry. The rules for bumping are in [AGENTS.md](AGENTS.md).

Entries are grouped as **Breaking**, **Added**, **Changed** and **Fixed**, newest release first.

## [1.9.2] — 2026-11-19

`ai-enabler` 1.7.2 · `ai-enabler-metrics` 1.2.3

### Fixed

- **ai-enabler, marketplace:** delivery-doctor on Windows: the permission rules it proposes for the build and test commands come for the PowerShell tool as well as for Bash, since the agents run most commands through PowerShell there, in the current wildcard form and with colon-suffixed scripts covered; and, in auto mode, a new check that the environment description /auto-mode-setup writes names the repository's remote exactly, the Jira host, and that answering ship at the ship gate authorises the commit, push, pull request and Jira comment it lists, with the line to add.

## [1.9.1] — 2026-11-19

`ai-enabler` 1.7.1 · `ai-enabler-metrics` 1.2.3

### Fixed

- **ai-enabler, marketplace:** Fixes from the first real delivery on 1.9.0: intervention notes quote the person's reply as written, since a paraphrase of what a gate approval authorises was refused by Claude Code's auto-mode classifier; run_state.py gate ship takes --no-jira-write and --no-pr, so the ship gate no longer promises a Jira comment or a pull request that cannot happen from here; delivery-ship says so before shipping and reports a push that failed for lack of stored credentials with the one command that fixes it; delivery-doctor checks that the remote accepts a push without a prompt and that the build and test commands of the repository profile will not ask for permission during an unattended run.
- **ai-enabler-metrics, marketplace:** A usage-report test no longer depends on how fast the machine runs it: the wait it uses to tell a mostly-waiting agent is no longer short enough to be overtaken by a slow runner, which made the main pipeline fail intermittently.

## [1.9.0] — 2026-11-17

`ai-enabler` 1.7.0 · `ai-enabler-metrics` 1.2.2

### Added

- **ai-enabler-metrics, marketplace:** A benchmark procedure (docs/benchmark.md) and tools/bench.py measure whether a pipeline change makes a run cheaper or faster without making it worse, comparing runs side by side on cost per agent, time, interactions and quality; the metrics README explains how to price a session behind an LLM gateway and how to cross-check the figures with Claude Code's OpenTelemetry export.
- **ai-enabler, marketplace:** The prompt cache across gates: delivery-doctor reports which cache lifetime applies (subscription, API key, Bedrock or gateway; environment and settings) and, where it helps, suggests promptCacheTtl 1h with its trade-off, since a pause at a gate longer than five minutes otherwise writes the whole conversation to the cache again; the README explains the cost of waiting at a gate and when /compact before a long pause is safe, and delivery-run leaves everything a later turn needs in the run's files before it stops at a gate.
- **ai-enabler, marketplace:** A new hook shows the pipeline's subagents only the failures and the summary of a long test or build run (dotnet, Maven, Gradle, npm, Jest, Vitest, pytest, go test, cargo test): the failing lines with their assertion messages and first stack frames, the summary lines, and the first and last lines, with the full output saved under .enabler/tmp/output/ and named in the text. The command is unchanged, the person's own sessions are never trimmed, and output_trim in .enabler/config.json sets the threshold or turns it off.
- **ai-enabler, marketplace:** Lanes by ticket size and risk: the analyst sizes each ticket (S, M, L) and names its risk areas, and run_state.py intake turns them into the run's lane and settings. An S ticket is refined only when the analyst found gaps and gets two reviewers, one whole-suite run and at most 10 mutants; M at most 25 mutants; L every lens with one reviewer each. Any risk area raises a ticket to at least M; authentication, permissions or personal data to L. Both gates stay by default in every lane; lanes.S.gates set to ship only skips the plan gate on small tickets. The lane is shown at the gates and can be changed with --lane or 'adjust: lane X'; a configuration key that differs from its default still applies to every lane.
- **ai-enabler, marketplace:** The review is proportional to the change: a new script decides which lenses a change needs — correctness, quality and tests always, security whenever the change touches external input, I/O, queries, HTML rendering, authentication, secrets, configuration, dependencies or a sensitive path, and is otherwise left out with the reason in the review report — groups them into two reviewers under 150 changed lines, and writes one review pack (files changed, criteria in force, test report, code diff) that every reviewer reads first instead of gathering the same context on its own. New settings review.select_lenses, review.group_below_lines and review.sensitive_paths.
- **ai-enabler, marketplace:** Shorter gates, and a notification when a run waits at one: the plan gate gives what will be done, in which files and with which risk in three lines, and each criterion with its planned test; run_state.py gate records that a run waits (plan, ship, delta, coverage below the minimum, a blocked ticket) and composes the ship gate from the run's files, so the orchestrator no longer reads them or types it out; a Notification hook raises a desktop notification naming the run and the gate after about a minute idle (notify.gates turns it off); the questions that block a ticket come in one message.

### Changed

- **ai-enabler, marketplace:** The test budget adapts to the change: mutation testing plans about two mutants per decision point changed (capped by tests.mutation.max_mutants) and none when the change decides nothing; the whole suite runs once instead of twice when CI already runs it on every merge request; between runs only the affected tests run, with the project's affected-tests, per-module coverage and incremental or parallel mutation modes when the repository has them configured, which the repository scout now records. Mutants are always made on a copy, never in the working tree.
- **marketplace:** The release procedure ends with a GitLab release for each marketplace version, named Marketplace X.Y.Z on the marketplace tag, with components, changes, update instructions and validation, so every release appears on the project's Releases page and not only as tags.
- **ai-enabler, marketplace:** The orchestrator of delivery-run starts lighter: run-and-config.md keeps the core and four references are read only when their situation occurs (repo-profile.md, external-sources.md, deltas.md, tests-protocol.md), and delivery-run moves going back after a gate and external-source handling into files of its own. The test engineer writes its results as acceptance-tests.json and test-report.json, which run_state.py renders as the Markdown reports (Claude Code tells subagents not to write report Markdown, so the orchestrator used to transcribe them); run_state.py render does it for the stand-alone skills, and the review pack falls back to the JSON.
- **ai-enabler, marketplace:** The orchestrator of delivery-run reads far less, which makes a run cheaper since everything it reads is carried to the end: a new script keeps state.json (one call per transition, times stamped) and summarises requirements.json, the planner returns the plan gate ready to show instead of the orchestrator reading plan.md, the test engineer and the implementer return short reports and the orchestrator no longer rewrites test-report.md, and it loads no skill the pipeline does not name.
- **ai-enabler, marketplace:** The solution planner works from the scout's context instead of exploring the repository again: the repository scout now puts in repo-context.md the fragments a plan depends on (signatures, routes, wiring, the test to imitate, with path:line), and the planner opens at most ten source files of its own, planning on a stated assumption or a question when that does not settle something.
- **ai-enabler, marketplace:** The review of the production code no longer waits for the tests: when a change gets one reviewer per lens, the correctness, security and quality reviewers start in parallel with the coverage stage, and only the tests lens waits for the test report, so the review stops adding its full length to the wall-clock time of a run. Small changes, reviewed in pairs, keep the order. The test engineer mutates copies, never the working tree.
- **ai-enabler, marketplace:** Each pipeline subagent is sized to its job: a maxTurns cap against runaway loops (about twice the most any stage needed on the benchmark tickets), the tools it never uses removed together with their descriptions (skills, to-do lists, web search, subagents, notebooks), and the analyst, refiner, scouts and planner start without the CLAUDE.md files, since they work from their brief and the repository profile.

### Fixed

- **ai-enabler, marketplace:** The repository profile no longer learns from unmerged work: in a git repository repo_profile.py compares the watched files at the merge-base with the base branch instead of the working tree (printing what it compared under against), so a run that edits an ADR or a manifest on its feature branch does not make the profile stale; deltas learned during a run record their branch and are listed as provisional until it is merged, and the scout tells later stages not to rely on them. Profile notes describe only what is true on the base branch. Fingerprints now treat CRLF as LF; existing profile.json files keep reading fresh.
- **ai-enabler-metrics, marketplace:** The usage report's Output table no longer counts Claude Code's own internal agents (prompt suggestions, /btw) as subagent runs, as the "Slow and unfinished steps" section already did.

## [1.8.1] — 2026-11-16

`ai-enabler` 1.6.0 · `ai-enabler-metrics` 1.2.1

### Fixed

- **ai-enabler-metrics, marketplace:** The usage report no longer under-counts cost and over-counts people behind an LLM gateway or with background subagents: cache writes reported as a total without a split by duration are priced as 5-minute writes instead of dropped, and a subagent handing its report back to the session is counted as a system turn, so it no longer adds human prompts, human interactions or human thinking time. Applies to sessions recorded from this version on.

## [1.8.0] — 2026-11-12

`ai-enabler` 1.6.0 · `ai-enabler-metrics` 1.2.0

### Added

- **ai-enabler-metrics, marketplace:** Usage events now record which subagent instance made each tool call and permission prompt, and when calls and subagents start; the usage report gains a "Slow and unfinished steps" section listing, per agent instance, its time, longest calls, calls and agents that never finished, and unanswered permissions.
- **marketplace:** Document how work is tracked on the GitLab board — one issue per change, workflow columns up to "awaiting release", labels that mirror the change fragment, a comment on the issue recording what was done and concluded at each step — and what coding assistants may do with issues.
- **ai-enabler, marketplace:** repo_profile.py check adds a short summary of what changed, grouped by kind and folder when many files changed, which the pipeline hands to the scout instead of hundreds of paths; delivery-doctor reports the permission settings and external sources that would stop an unattended run on a prompt.

### Fixed

- **ai-enabler, marketplace:** The repository and source scouts stay fast on large codebases: they search through git and the search tools instead of walking the tree, bound every git log, open at most ten files for a ticket, and run every command in the foreground, narrowing one that does not return within two minutes; a new always-on hook refuses a background command from either scout.
- **ai-enabler-metrics, marketplace:** On Windows, the usage hook no longer loses the session's ticket, subagent run times or events when the hooks of parallel subagents run at the same time: hook processes take turns through an msvcrt lock, as they already did with fcntl on Linux and macOS, and a state file that cannot be read is never overwritten with an empty one.
- **ai-enabler-metrics, marketplace:** In a project that uses the ai-enabler pipeline, AI usage is attributed to its runs: the ids the pipeline gives acceptance criteria (AC-6), review findings (CR-1) and review lenses no longer pass for tickets, a run started from a requirements file is attributed by its name, branch keys and a configured ticket_pattern still count, and events recorded before are corrected when the report is made.

## [1.7.0] — 2026-11-10

`ai-enabler` 1.5.2 · `ai-enabler-metrics` 1.1.1

### Added

- **ai-enabler, marketplace:** Adopt reviewed change fragments, deterministic offline releases and GitLab validation instead of version bumps in each merge request. Migration: Existing branches must restore published versions and changelog entries and add change fragments before integration.

### Fixed

- **ai-enabler, ai-enabler-metrics, marketplace:** Fix Python discovery for both plugins on supported Bash runtimes, preserve guard denials and block guard startup failures, and check the actual launcher in readiness checks and CI. Migration: Compatibility scope: this patch fixes execution on the supported runtime; it is not support for older Claude Code or PowerShell-only installations. Use Claude Code 2.1.319 or later for onFailure: block, Python 3.8+, and Bash (Git Bash from Git for Windows on Windows, not the Windows/WSL Store alias). Upgrade missing prerequisites through the approved installation process, restart Claude Code, run each plugin's scripts/run-python.sh --check in Bash, then rerun delivery-doctor and metrics-usage-init --status. Do not disable guards, patch installed caches or create a python3 shim. Existing .enabler configuration, state, events and resumable runs need no format migration; guard startup failures now block rather than allowing unguarded execution. Maintainers must confirm this supported-runtime compatibility scope before release.

## [1.6.2] — 2026-10-29

`ai-enabler` 1.5.1 · `ai-enabler-metrics` 1.1.0

### Changed

- **Marketplace:** the history of the marketplace is joined to the AI Transformation Framework repository, whose first commit was an import of version 1.4.0. Nothing in the plugins changes; `.graphify/` is ignored, as in that import.

## [1.6.1] — 2026-10-28

`ai-enabler` 1.5.1 · `ai-enabler-metrics` 1.1.0

### Changed

- **ai-enabler:** `delivery-sources` explains what happens to runs already in progress when a source is added, removed or refreshed — each picks it up when resumed: a plan not yet approved is made with it; after approval, what the source imposes is shown, and a change of behaviour is a delta at the plan gate. The plugin README says the same.

## [1.6.0] — 2026-10-28

`ai-enabler` 1.5.0 · `ai-enabler-metrics` 1.1.0

### Added

- **ai-enabler:** external sources of context. Besides the project, the pipeline can read other repositories (by URL, or already cloned in a folder next to the project), other folders, and documents — Markdown, text, PDF, HTML and Word (`.docx`, converted with the standard library, nothing to install). Each source is learned once by a new agent, `delivery-source-scout`, in parallel with the repository scout: a short profile, a delta when the source changes, and for every ticket `external-context.md` with only what applies. Sources are learned during intake, in parallel with the analyst, so the refiner already has them; the planner implements contracts as the source defines them, the test engineer tests against them, the reviewers check conformance, and the plan gate, the delivery report and the pull request name the sources relied on. What a stage finds wrong about a source becomes a delta of that source. The stand-alone skills (`delivery-test`, `delivery-review`, `delivery-implement`, `delivery-ticket-refine`, `delivery-ticket-create`) use them too.
- **ai-enabler:** adding a source takes one answer. The preflight of `delivery-run` and `delivery-plan` asks once per project whether the work depends on anything else, offering the repositories it finds next to the project; `--context <url|path>` adds one on any run; the new skill `delivery-sources` adds, lists, refreshes, relearns and removes them. A URL whose clone is already next to the project is read there, not cloned again.
- **ai-enabler:** sources are read-only. A new hook, always on, refuses edits inside a registered source — file tools, redirections, `rm`, `mv`, `sed -i`, copies into it, git commands that change it. Copying from a source into the project is allowed.
- **ai-enabler:** `delivery-doctor` reports each source and its status.
- **ai-enabler:** a source changes only when its own part changes: the followed branch or tag of a URL source (matched exactly), the folder and its `paths` in a sibling clone — a commit elsewhere in that repository does not count —, the document itself. `external-context.md` is rewritten when a source changed or was added since it was written, also on resume. A URL given with credentials has them removed before it is stored.

## [1.5.0] — 2026-10-23

`ai-enabler` 1.4.0 · `ai-enabler-metrics` 1.1.0

The test stage was more than half of the delivery time on a real project: the whole suite ran in every round, mutation testing was improvised by the orchestrator and ran against all of it, coverage was chased to 100 % file by file, and long commands were waited for with fixed sleeps. The test engineer now works to a budget. Mutation testing being on by default changes what a delivery does, so it is announced here; it adds tests and does not break anything that worked before, which is why the plugin moves by a minor version.

### Added

- **ai-enabler:** `tests.full_suite_runs` (default 2): the whole suite runs at most that many times per coverage stage — once to catch regressions, once to measure. Between rounds, only the tests the run created or changed.
- **ai-enabler:** mutation testing is part of the coverage stage, on by default. It is limited to the code the ticket changed that decides something (business rules, permissions, validations, calculations, security and privacy), runs each mutant against the feature's tests only, in one pass, up to `tests.mutation.max_mutants` (40). Surviving mutants get a test or a stated reason, and the ship gate shows how many were caught. `tests.mutation.enabled: false` turns it off for a project.
- **ai-enabler:** the scout records how long the whole test suite takes and a faster form of the test command (parallel, or changed files only) when the repository documents them; it runs nothing to find them. The test engineer verifies the faster form the first time it uses it and measures the duration, and what it finds becomes a delta to the profile.
- **ai-enabler:** the test report, the pull-request template and the ship gate give the duration of every whole-suite run and the mutation results.
- **ai-enabler-metrics:** `metrics-delivery-report` passes `--followup-days` to the rework metric.

### Changed

- **ai-enabler:** coverage is judged on the changed code as a whole, and the test engineer stops adding tests once the target is met. Target and minimum are unchanged (80 % and 70 %).
- **ai-enabler:** long test commands are waited for, not polled with fixed sleeps, and never started twice on the same tests at once.
- **ai-enabler:** `verify` mode runs only the tests in its scope; the whole suite only when no scope is given.
- **ai-enabler:** every skill that launches the test engineer (`delivery-run`, `delivery-test`, `delivery-implement`, `delivery-review`) passes it the mode, the configuration and the scope only. More verification than that is the person's decision at a gate, never added to a brief by the orchestrator.

### Fixed

- **ai-enabler:** the test engineer accepts more verification than the configuration gives when the person decided it (more tests below the minimum); before, its budget refused it "whoever asks".
- **ai-enabler:** `--local` was described in the safety rules as lasting one run; it switches the project to local-only until a person deletes the marker.
- **ai-enabler:** the plugin README lists `--local` for `delivery-ship` and `git.local_only` in the configuration; `test-report.md` is described with its durations and mutation results; the root README no longer says usage capture adds a rule to the project's `.gitignore`, and its diagram shows the test budget.
- **ai-enabler:** the remote guard's description names every write it blocks (GitHub, GitLab and Bitbucket as well as Jira and Confluence).
- **ai-enabler:** the frontmatter of `delivery-run`, `delivery-test`, `delivery-review`, `delivery-ship` and `delivery-doctor` is valid YAML; their descriptions were unquoted and contained colons.
- **ai-enabler-metrics:** the delivery skills read and write `.enabler/delivery/` in a project where usage capture was never switched on, as the scripts already did, instead of creating `.enabler/metrics/` and switching capture on by accident.
- **ai-enabler-metrics:** the argument hints of `metrics-usage-init` and `metrics-usage-report` are valid YAML.
- **ai-enabler-metrics:** the example Jira data uses placeholder names (`PROJ-123`, "Jane Doe"); the README documents `delivery.ticket_pattern` and the default key pattern, and both the README and the metrics reference describe every folder under `.enabler/metrics/`.

## [1.4.1] — 2026-10-22

`ai-enabler` 1.3.1 · `ai-enabler-metrics` 1.0.0

### Fixed

- **Marketplace:** the root README's list of skills now includes `delivery-ticket-refine` and `delivery-ticket-create`, says that `delivery-run` and `delivery-plan` accept a Markdown file as well as a key, and its quick start shows how to start without a ticket. The plugin descriptions in the README and in the marketplace catalogue mention ticket refinement.
- **Marketplace:** the `ai-enabler-metrics` README has a table of all its skills, including `metrics-usage-init`, `metrics-usage-report` and `metrics-stale-assets`, which were only mentioned in passing.
- **ai-enabler:** the description of `delivery-ship` says the pull-request body follows the template the person chose, instead of "the delivery report as its body".

## [1.4.0] — 2026-10-09

`ai-enabler` 1.3.0 · `ai-enabler-metrics` 1.0.0

### Added

- **ai-enabler:** a pull-request template ships with the plugin (`templates/pull-request.md`). At the ship stage the pipeline asks which template to use — the repository's own, when it has one, or the plugin's — and offers to remember the answer in `git.pr_template` (`"ask"`, `"plugin"`, `"repo"` or a path). The ship gate names the one that will be used, and the body that was sent is kept as `pull-request.md` in the run folder.
- **ai-enabler:** the plan gate lists every file the plan will create or modify, by path, so the change can be reviewed before any code exists.

### Changed

- **ai-enabler:** where tests run and what happens when one fails is now written down in one place ("Tests: where they run, and when they fail" in the run-and-config reference, and in the plugin README): they run locally with the repository's own commands, each failure is first given a cause, fixing is bounded, and a result with failing tests is marked not ready and never shipped unattended. The behaviour is the one the stages already followed; the root README's diagram now shows these loops.
- **ai-enabler:** with a repository template, the pull-request body keeps that template's headings and checklists; failing tests, open findings and the criteria table are added at the end when the template has no place for them.

## [1.3.0] — 2026-10-09

`ai-enabler` 1.2.0 · `ai-enabler-metrics` 1.0.0

Refinement is on by default, so the same ticket now yields a fuller plan than before and one more model call. Nothing has to be changed to keep using the plugin; `refine.enabled: false` restores the previous behaviour.

### Added

- **ai-enabler:** tickets are refined before they are planned. After intake, a new agent, `delivery-ticket-refiner`, looks for what the definition leaves unsaid — unhappy paths, limits, permissions, data, scope — and closes each gap as a marked addition, an assumption or a question it does not answer for you. The planner plans the refined ticket, and the plan gate lists what was added so any of it can be rejected (`adjust: drop AC-7`). `refinement.md` in the run directory says why each addition is there. `--no-refine` on `delivery-run` and `delivery-plan`, or `refine.enabled: false`, takes the ticket as written.
- **ai-enabler:** `delivery-ticket-refine <KEY | file>` writes a more robust version of an existing ticket as a local Markdown file in `.enabler/tickets/`. It never writes to Jira.
- **ai-enabler:** `delivery-ticket-create <a few sentences>` writes a complete ticket from a short brief, also as a local Markdown file. At the end it asks where you want it; a Jira issue is created only if you choose that, after seeing what would be created, and never in local-only mode.
- **ai-enabler:** the files both skills write are sources `delivery-plan` and `delivery-run` accept, and are not refined a second time.
- **ai-enabler:** what makes a ticket ready, and how a gap is closed, is defined once, in `references/ticket-readiness.md`, read by the analyst, the refiner and both skills.

### Changed

- **ai-enabler:** the delivery report says where each acceptance criterion comes from (the ticket, derived, or refinement) and lists what refinement added. In a run without the plan gate, the report and the ship gate state that those additions were not reviewed by anyone.
- **ai-enabler:** a ticket can stop as blocked where it did not before: refinement may find a question only the business can answer. It comes with options and a suggestion.
- **ai-enabler:** `delivery-ship` finds the run by its branch before reading a key out of the branch name, so a run delivered from a local ticket file never writes to Jira, even when the file's name contains a Jira key.
- **ai-enabler:** the test order is decided after refinement. Criteria added by refinement count as stated, so their tests are written before the code; the verdicts on the ticket as it arrived are kept in `requirements.json` under `as_received`.
- **ai-enabler:** `delivery-run` and `delivery-plan` now make one more model call per ticket (the refiner, on Opus). Turn it off with `refine.enabled: false` if you do not want it.
- **ai-enabler:** the acceptance-criteria trace in `plan.md` says where each criterion comes from: the ticket, derived, or refinement.

## [1.2.0] — 2026-10-09

`ai-enabler` 1.1.0 · `ai-enabler-metrics` 1.0.0

### Added

- **ai-enabler:** the repository is learned once. The scout writes a profile to `.enabler/repo-profile/profile.md` — stack, the commands that work here, structure, conventions, rules — and later runs only check that it still holds, by comparing a hash of the build manifests, CI and lint configuration, the root README and the rules files. Only the code closest to the ticket is searched for on every run.
- **ai-enabler:** the profile grows by deltas, not by rewriting. When a watched file changes in a way that matters, or a stage finds the profile wrong, a small `deltas/delta-NNN-*.md` says what no longer holds and what is true now; the base is left as written. A change that affects nothing the profile says leaves no file behind.
- **ai-enabler:** what a run learns about the repository the hard way (a command that did not work, a rule a reviewer had to point out) is noted in `profile_notes` in the run's `state.json` and becomes a delta at the next gate, so it survives an interrupted run.
- **ai-enabler:** `--relearn` on `delivery-run` and `delivery-plan` studies the repository again from scratch and drops the profile and its deltas. It is only ever suggested: when the profile has outgrown its size, when there are more than ten deltas, or when they no longer fit together. `--refresh` keeps its meaning: it re-runs the stages of one ticket.
- **ai-enabler:** a profile written or restored by hand is adopted as it is, never overwritten.
- **ai-enabler:** `delivery-doctor` reports whether the repository has been learned, where the profile is kept, how many deltas it has and whether it is stale.

### Changed

- **ai-enabler:** the run's `repo-context.md` now holds only what the ticket adds to the profile. Planner, implementer, test engineer and reviewers read the profile, its deltas in order, and that file. A run started with an earlier version keeps its full `repo-context.md` and can be resumed.
- **ai-enabler:** `delivery-test` without a ticket no longer writes a `repo-context.md`; it uses the profile and the scope it is given.
- **ai-enabler:** everything under `.enabler/` is treated as local. `.enabler/runs/` and `.enabler/repo-profile/` each hold a `.gitignore` of their own, so the pipeline no longer adds a line to the project's `.gitignore`; nothing under `.enabler/` is ever staged (before, only `.enabler/runs/` was named); nothing from the profile is written into `CLAUDE.md` or `AGENTS.md`; and the configuration file is no longer described as something to commit.
- **Marketplace:** the versioning rules say which changes to files in `.enabler/` are breaking: the ones a person or another tool relies on, and any that would stop a run in progress from being resumed.

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
