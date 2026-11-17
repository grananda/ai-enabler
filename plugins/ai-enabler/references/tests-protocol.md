# Tests: where they run, and when they fail

Shared by the `ai-enabler` skills and agents; split out of `run-and-config.md`, which is read at the start of every skill, because most runs never need it.

**Where.** On this machine, in the working tree, on the feature branch, with the commands the repository profile names — the project's own, never ones assumed from the stack. The pipeline does not run tests in CI, does not wait for CI and does not read its result; what CI says after the push is for the person and the reviewers of the pull request. Nothing is installed or reconfigured to make tests run: a missing tool is reported.

| Stage | Who runs them | What is run | What is expected |
|---|---|---|---|
| 4 acceptance tests | test engineer, `acceptance` | The new acceptance tests | **Red**: they fail because the code does not exist. A test that fails for another reason (typo, broken setup) is fixed here |
| 5 implement | implementer | Build, linter, the acceptance tests | The acceptance tests go **green** without being edited |
| 6 coverage | test engineer, `coverage` | The changed tests; the whole suite at most `tests.full_suite_runs` times (once for regressions, once to measure); mutation testing on the changed code that decides, against the feature's tests | Green; coverage at the target, or at least the minimum; no surviving mutant left without a reason |
| 7 review, fix loop | test engineer, `verify` | The tests of the area a fix touched — never the whole suite when a scope is known | Still green after each fix |
| 8 ship | nobody | Nothing is re-run: the gate reports the last result | — |

**What a brief may ask for.** A skill that launches the test engineer passes it the mode, the configuration values — `tests.coverage_target`, `tests.coverage_minimum`, `tests.levels`, `tests.full_suite_runs`, `tests.mutation` — and the scope of the run. It adds no verification of its own: no extra mutation passes, no extra runs of the whole suite, no repeated runs to check stability, no coverage goals per file. More assurance than the configuration gives is the person's decision, taken at a gate and recorded under `human_interventions` in `state.json`; an agent does not take it because it seems safer. The time it costs is real: on one project, mutation runs against the whole suite and repeated whole-suite runs in every round made the test stage more than half of the whole delivery time.

**When a test runs and does not pass,** the first thing is to say why. Nobody edits a test to make it agree with the code, and nobody weakens, skips or deletes a test to get a green run.

| Cause | Who decides it is that | What happens |
|---|---|---|
| The test is wrong: bad setup, a mistake in the test itself | test engineer | It fixes its own test and runs again |
| The test contradicts the ticket or the plan | the orchestrating skill, against the ticket and the plan — never against the code | The test engineer corrects that test in `repair` mode; the change and its reason go in the delivery report |
| The code is wrong (a defect) | test engineer | The test stays as it is. The implementer fixes the code in `fix` mode, then the test engineer runs it again in `verify` mode |
| It failed before this change | test engineer | Reported as pre-existing. Not fixed, not skipped, not counted against this change |
| The tests could not be run: no command, missing tool, broken environment | whoever tried | Reported as `could not run`, with the reason. The change is stated to be untested; it is not presented as passing |

**How long it goes on.** Fixing is bounded, so that a run cannot loop: one extra implementer pass at stage 5, and `review.max_fix_rounds` (2) rounds shared by the coverage stage and the review. When the budget is spent, the failures are not hidden and the run is not abandoned: it continues to the review, because a review of failing code is still worth having.

**What a failure left open means at the end.** The result is **not ready**:

- the delivery report and the pull-request body list every failing test with its cause;
- the ship gate says so first, and recommends holding or opening the pull request as a draft. The person may still ship: it is their decision, made with the failures in front of them;
- without a person at the gate (`--ship` on an unattended run), nothing is shipped. The run holds and says what blocks it.

Coverage below the minimum follows its own rule: the run stops for the person at stage 6, whatever `gates` says.
