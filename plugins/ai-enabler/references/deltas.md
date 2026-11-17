# Changing course after approval: deltas

Shared by the `ai-enabler` skills and agents; split out of `run-and-config.md`, which is read at the start of every skill, because most runs never need it.

Once a plan is approved, it is not rewritten quietly. A change to what is being built — to the scope, the behaviour or the acceptance criteria — is made as a **delta**: a small, approved change to the plan that says what is added and what is removed, and is carried out in the same order as the original work.

A delta is needed when:

- the person asks at the ship gate for something that changes behaviour, scope or acceptance criteria;
- the implementer stops because the plan is wrong in a way that changes scope;
- a run is resumed and the ticket, or the person's instructions, have changed.

A delta is **not** needed for a correction that leaves the plan true: a bug in the implementation, a naming or style point, a review finding. Those are fix lists for the implementer.

What a delta is, on disk — `deltas/delta-NN.md`, numbered from 01:

```markdown
# Delta NN — <KEY>: <what changes, in one line>

**Trigger:** who asked for it or what revealed it, and when.
**Why:** the reason, in two or three sentences.

## Acceptance criteria
| AC | Change (added / changed / removed) | Before | After |

## Tests
| Test | Action (add / change / remove) | File | Covers | Why |

## Code
| File | Action (create / modify / delete) | What |

## Plan steps affected
Which steps of plan.md change, are added, or are dropped.

## Risks and impact
```

Both sides are always written down: what the delta adds and what it takes away. A test that no longer describes wanted behaviour is listed under "remove"; so is code that the new approach makes dead. Nothing is deleted that the delta does not name.

How a delta is carried out — the same order as the pipeline, acceptance criteria first:

1. **Safety copy.** Before the planner runs, the orchestrating skill copies `plan.md` and `requirements.json` into `deltas/delta-NN.before/`. The planner is about to overwrite both, and the run directory is not under version control, so this copy is the only way back.
2. **Plan.** The planner, in `delta` mode, writes `deltas/delta-NN.md`, updates `plan.md` so that it describes the work as it now stands (with a "Change history" table at the top, one row per delta), and updates the acceptance criteria in `requirements.json`: new ones get new ids, a removed one is kept and marked `"removed_by": "delta-NN"`, ids are never reused. The skill records the delta in `state.json` with `approved: false`, `applied: false`.
3. **Approval.** The delta is shown at the plan gate, in the same compact form as a plan, and needs the same approval — **always**, whatever `gates` says: an unattended run does not approve a change of scope by itself. No test or code changes before that.
   - *adjust* — restore the two files from `delta-NN.before/` and relaunch the planner in delta mode with the feedback; it rewrites the same `delta-NN.md`, it does not open a new number.
   - *cancel* — restore the two files from `delta-NN.before/`, delete `delta-NN.md` and the `.before` folder, and remove the delta from `state.json`. The run is back where it was.
   - *approve* — set `approved: true` and set `stage` to `acceptance-tests`.
4. **Acceptance tests.** The test engineer, in `acceptance` mode with the delta, writes the tests for added and changed criteria and removes the tests the delta lists as obsolete — those and no others — then updates `acceptance-tests.md` (creating it if the run had none). This step runs even when the run's `test_order` was `after` because the ticket stated no criteria: the criteria of a delta come from a person's request, so they can be tested first. It is skipped only when `tests.order: after` is configured.
5. **Implementation.** The implementer makes the new tests pass and deletes the code the delta lists for deletion. When it returns, set `applied: true`.
6. **Coverage, then review** of the lenses the change touches, and back to the ship gate.

A delta that is approved but not applied is unfinished work. Any skill that resumes a run looks for one first and carries it out before anything else; a delta that is written but not approved is shown at its gate again.

**Removed criteria are not in force.** A criterion marked `removed_by` is kept for the record only: no test is written for it, the review does not count it as unmet, and totals such as "criteria met" leave it out. A test removal that a delta lists is not a "deleted test" finding.

`state.json` records each delta. The delivery report lists them under "Changes after the plan was approved", so the pull request shows not only the result but how it got there.
