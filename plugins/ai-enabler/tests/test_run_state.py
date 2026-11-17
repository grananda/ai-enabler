#!/usr/bin/env python3
"""Checks run_state.py: the bookkeeping of state.json and the intake summary.

    python3 tests/test_run_state.py
"""

import json
import os
import subprocess
import sys
import tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "run_state.py")


def run(*args, ok=True):
    out = subprocess.run([sys.executable, SCRIPT] + list(args), capture_output=True, text=True, encoding="utf-8")
    assert (out.returncode == 0) == ok, (args, out.stdout, out.stderr)
    assert "Traceback" not in out.stderr, out.stderr
    return json.loads(out.stdout) if ok else out.stderr


def state(run_dir):
    with open(os.path.join(run_dir, "state.json"), encoding="utf-8") as fh:
        return json.load(fh)


def main():
    run_dir = os.path.join(tempfile.mkdtemp(prefix="ai-enabler-run-state-"), "runs", "PROJ-7")

    # A new run, then the same command again: a resume leaves the state untouched.
    out = run("init", run_dir, "--key", "PROJ-7", "--source", "jira", "--base", "main")
    assert out["stage"] == "intake" and out["status"] == "active" and out["resumed"] is False, out
    s = state(run_dir)
    assert s["gate_rounds"] == {"plan": 0, "ship": 0} and s["human_interventions"] == [] and s["started_at"].endswith("Z")
    run("update", run_dir, "--done", "intake")
    assert run("init", run_dir, "--key", "PROJ-7", "--source", "jira")["resumed"] is True
    assert state(run_dir)["stage"] == "scout"

    # One call per transition: stage done, values, counters, an intervention stamped with the stage.
    run("update", run_dir, "--done", "scout")
    out = run("update", run_dir, "--done", "plan", "--set", "plan_approved=true", "--set", "branch=feature/PROJ-7-x",
              "--set", "external_context.contracts=git:abc", "--add", "gate_rounds.plan=1",
              "--intervene", "approval", "Approved — with AC-3 dropped", "--at-stage", "plan")
    s = state(run_dir)
    assert s["stages_done"] == ["intake", "scout", "plan"] and s["stage"] == "acceptance-tests", s
    assert s["plan_approved"] is True and s["branch"] == "feature/PROJ-7-x" and s["gate_rounds"]["plan"] == 1
    assert s["external_context"] == {"contracts": "git:abc"}
    i = s["human_interventions"][0]
    assert i["kind"] == "approval" and i["stage"] == "plan" and i["note"] == "Approved — with AC-3 dropped", i
    assert out["interventions"] == 1 and "human_interventions" not in out          # the view stays compact
    run("update", run_dir, "--done", "plan")                                       # done twice: listed once
    assert state(run_dir)["stages_done"].count("plan") == 1

    # Profile notes in and out; hold at the ship gate.
    run("update", run_dir, "--note", "coverage report is in build/jacoco", "--note", "x")
    run("update", run_dir, "--drop-note", "x", "--stage", "ship", "--status", "held",
        "--intervene", "hold", "not now")
    s = state(run_dir)
    assert s["profile_notes"] == ["coverage report is in build/jacoco"] and s["status"] == "held"
    assert s["human_interventions"][-1]["stage"] == "ship"

    # Deltas: recorded, approved and applied by id, or dropped when cancelled.
    run("update", run_dir, "--append", 'deltas={"id": "delta-01", "trigger": "ship gate", "summary": "add CSV"}')
    run("update", run_dir, "--append", 'deltas={"id": "delta-02", "trigger": "ship gate", "summary": "drop CSV"}')
    out = run("update", run_dir, "--set", "delta:delta-01.approved=true", "--set", "deltas.-1.summary=drop the CSV")
    d = state(run_dir)["deltas"]
    assert [x["id"] for x in d] == ["delta-01", "delta-02"] and d[0]["approved"] is True and d[0]["applied"] is False
    assert d[0]["at"].endswith("Z") and d[1]["summary"] == "drop the CSV", d
    assert out["deltas"] == [{"id": "delta-01", "approved": True, "applied": False},
                             {"id": "delta-02", "approved": False, "applied": False}], out
    run("update", run_dir, "--drop-delta", "delta-02")
    assert [x["id"] for x in state(run_dir)["deltas"]] == ["delta-01"]
    assert "no delta" in run("update", run_dir, "--set", "delta:delta-09.applied=true", ok=False)

    # Mistakes are refused, and the state is not written.
    assert "unknown intervention kind" in run("update", run_dir, "--intervene", "shrug", "x", ok=False)
    assert "PATH=VALUE" in run("update", run_dir, "--set", "plan_approved", ok=False)
    assert "no state.json" in run("show", os.path.join(run_dir, "..", "NOPE"), ok=False)

    # Intake: the verdicts after refinement, counts, blocking questions, test_order recorded.
    with open(os.path.join(run_dir, "requirements.json"), "w", encoding="utf-8") as fh:
        json.dump({"readiness": "blocked", "acceptance_criteria_quality": "scarce",
                   "refinement": {"criteria_added": 1},
                   "requirements": [{"id": "R-1"}, {"id": "R-2", "removed_by": "plan-gate"}],
                   "acceptance_criteria": [{"id": "AC-1", "derived": False}, {"id": "AC-2", "derived": True},
                                           {"id": "AC-3", "refined": True},
                                           {"id": "AC-4", "refined": True, "removed_by": "plan-gate"}],
                   "assumptions": ["a"],
                   "open_questions": [{"question": "Which currency?", "blocking": True, "why_it_matters": "rounding"},
                                      {"question": "Name?", "blocking": False}]}, fh)
    out = run("intake", run_dir)
    assert out["readiness"] == "blocked" and out["test_order"] == "mixed" and out["refined"] is True, out
    assert out["criteria"] == {"in_force": 3, "from_ticket": 1, "derived": 1, "from_refinement": 1, "removed": 1}, out
    assert out["requirements"] == 1 and out["assumptions"] == 1 and out["open_questions"] == 2
    assert [q["question"] for q in out["blocking_questions"]] == ["Which currency?"]
    assert state(run_dir)["test_order"] == "mixed"
    assert run("intake", run_dir, "--order", "after")["test_order"] == "after"
    print("ok — run state: init, resume, transitions, interventions, notes, intake")


if __name__ == "__main__":
    main()
