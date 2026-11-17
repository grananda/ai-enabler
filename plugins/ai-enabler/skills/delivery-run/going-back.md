# Going back: adjustments, fixes and deltas

Part of `delivery-run`, read when a person sends the work back at a gate or the plan proves wrong. The abbreviated script names mean the launcher form given in `SKILL.md`.

Three situations send the run backwards. Handle each the same way every time.

**1. The plan is adjusted before it is approved** (`adjust` at the plan gate). Nothing exists yet but the plan. The planner revises `plan.md` with the feedback and the gate is shown again. No delta.

**2. A correction that leaves the plan true** (`fix` at the ship gate, when what is asked does not change scope, behaviour or acceptance criteria — a bug, a name, a style point, a missed edge case of an existing criterion). In this order:

1. `ai-enabler:delivery-code-implementer` in `fix` mode with the request as its fix list;
2. `ai-enabler:delivery-test-engineer` in `coverage` mode — the coverage stage again, since code changed: the suite within its budget, any missing tests, mutation testing on what changed, the coverage verdict (and the stop below the minimum, if it comes to that);
3. a new review pass (`fix_rounds` back to 0) as in Step 7, from `review_scope.py`: the lenses the change needs, with a fresh pack, appended to `review.md`;
4. the delivery report rewritten, and back to the ship gate.

**3. A change to what is being built** — to scope, behaviour or acceptance criteria — once the plan has been approved. It comes from a `fix` at the ship gate that asks for something different, from an implementer that found the plan wrong, or from a resumed run whose ticket or instructions changed. This is a **delta**; read "Changing course after approval: deltas" in the run-and-config reference and follow it:

1. Take the next delta number and copy `plan.md` and `requirements.json` into `deltas/delta-NN.before/`. Then launch `ai-enabler:delivery-solution-planner` with `mode: delta`, the run directory, the number and the change. It writes `deltas/delta-NN.md` (what is added **and** what is removed), brings `plan.md` up to date and updates the acceptance criteria. Record the delta in `state.json` with `approved: false`, `applied: false`.
2. Show the delta at the plan gate and wait — a changed plan needs approval like the plan did, **also when `plan` is not in `gates`**: a change of scope is never approved unattended.

   ```
   DELTA NN — <KEY>: <one line>
   Why         : <reason>
   Criteria    : +<added> · ~<changed> · −<removed>
   Tests       : +<to add> · ~<to change> · −<to remove: names>
   Code        : +<files to create> · ~<to modify> · −<to delete: paths>
   Full delta  : .enabler/runs/<KEY>/deltas/delta-NN.md

   Approve this delta? (approve / adjust: <what to change> / cancel)
   ```

   - **adjust** — a round at the plan gate (check the limit, add one to `gate_rounds.plan`). Restore `plan.md` and `requirements.json` from `delta-NN.before/`, then relaunch the planner in delta mode with the same number and the feedback.
   - **cancel** — restore the two files from `delta-NN.before/`, delete `delta-NN.md` and the `.before` folder, remove the delta from `state.json`, and return to where the run was. Code and tests already written stay as they were; only the proposed change is dropped.
   - **approve** — set `approved: true` and `stage` to `acceptance-tests`.
3. Carry it out, in the usual order:
   - `ai-enabler:delivery-test-engineer` in `acceptance` mode with the delta: tests for the added and changed criteria are written, and the tests the delta lists as obsolete are removed. This runs even if the run's `test_order` was `after` for lack of criteria in the ticket; only a configured `tests.order: after` skips it;
   - `ai-enabler:delivery-code-implementer` in `implement` mode with the delta: the new tests are made to pass and the code the delta lists is deleted. Then set the delta's `applied: true`;
   - the coverage stage;
   - a new review pass (`fix_rounds` back to 0) as in Step 7, from `review_scope.py` with a fresh pack, giving the reviewers the run directory so they read `deltas/`;
   - the delivery report, with the delta under "Changes after the plan was approved", and the ship gate.

Criteria marked `removed_by` are no longer in force: leave them out of "criteria met" at the ship gate and show them in the report only under the delta that removed them, or, for the ones marked `plan-gate`, in one line under "What refinement added to the ticket" as rejected at the plan gate.

When you cannot tell a correction from a delta, ask yourself whether an acceptance criterion or a step of `plan.md` becomes false. If one does, it is a delta. When still in doubt, treat it as a delta: an unneeded approval costs a minute, a silent change of scope costs the trust the plan gate exists for.

Do not leave the past lying around. After a delta, no test asserts behaviour that was dropped and no code serves an approach that was abandoned — and both removals are on record in the delta, not just gone.
