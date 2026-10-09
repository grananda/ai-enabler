<!--
Pull-request template of the ai-enabler plugin.

Used by the ship stage when the repository has no pull-request template of its own, or when the
person prefers this one. Fill every section from the run's files; delete a section marked
"omit when" if it does not apply; remove these comments. Write for a reviewer who has not seen
the session that produced the change.
-->

## <KEY> — <title>

<Link to the Jira issue. For a ticket that came from a local file, one sentence saying what was asked for instead: local paths mean nothing to a reviewer.>

### What changed

<Three to six bullets on the change and the approach.>

### Acceptance criteria

| AC | Criterion | From | Status | Evidence (test or file) |
|---|---|---|---|---|
| AC-1 | <observable behaviour> | <ticket \| derived \| refinement> | <met \| not met \| not verified> | <test name or file> |

<!-- "From" tells what the ticket asked for apart from what was added to it. -->

### What refinement added to the ticket

<!-- Omit when nothing was added. -->
<Each requirement, criterion and assumption added by refinement, one line each with its reason, and whether a person approved them at the plan gate or the run was unattended. Additions rejected at the plan gate, in one line.>

### Tests

- **Result:** <passed> passed, <failed> failed, <skipped> skipped — run locally with `<command>`.
- **Coverage of the changed code:** <x>% line, <y>% branch (target <t>%, minimum <m>%) — <met | acceptable | below minimum, accepted by <who>: <why> | not measured: <why>>.
- **Written before the code:** <n> of <total> acceptance criteria. <Why not all, when not all.>
- **Failing or not run:** <each test that fails, with its cause: a defect left open, or a failure that was there before this change. "None" otherwise.>

### Review

<Lenses run. Findings fixed. Findings left open: severity, location, one line each. "None open" otherwise.>

### Changes after the plan was approved

<!-- Omit when there was none. -->
<One entry per delta, in order: what changed and why, what was added, what was removed (criteria, tests, code).>

### Deviations and assumptions

<Where the implementation departed from the plan without a delta; assumptions made about the ticket. "None" otherwise.>

### How to verify

<The commands or steps a reviewer can run.>
