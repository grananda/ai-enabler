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

    # Reports: the test engineer writes JSON, the script writes the Markdown people and later stages read.
    report = {"mode": "coverage", "verdict": "defects found", "coverage_verdict": "acceptable",
              "suite": {"passed": 40, "failed": 1, "skipped": 0},
              "coverage": {"line_percent": 75, "branch_percent": 70, "target": 80, "minimum": 70,
                           "files": [{"file": "src/a.py", "line_percent": 75, "uncovered": "l. 9 | 12"}]},
              "criteria": [{"id": "AC-1", "tests": ["test_ac1"], "written": "before code", "status": "failing"}],
              "mutation": {"decision_points": 3, "mutants": 6, "killed": 5,
                           "surviving": [{"where": "src/a.py:9", "mutant": "< to <=", "reason": "equivalent"}]},
              "defects": [{"test": "test_ac1", "expected": "422", "actual": "500", "suspect": "src/a.py:9"}],
              "an_unplanned_field": {"kept": True}}
    with open(os.path.join(run_dir, "test-report.json"), "w", encoding="utf-8") as fh:
        json.dump(report, fh)
    out = run("update", run_dir, "--add", "fix_rounds=1")
    assert out["rendered"] == ["test-report.md"], out
    with open(os.path.join(run_dir, "test-report.md"), encoding="utf-8") as fh:
        md = fh.read()
    for expected in ("**Verdict:** defects found", "**Coverage:** acceptable", "40 passed, 1 failed",
                     "Line 75 % · branch 70 % (target 80 % · minimum 70 %)", "l. 9 \\| 12", "| AC-1 | test_ac1 |",
                     "< to <=", "| test_ac1 |", "An unplanned field", "Edit the JSON"):
        assert expected in md, (expected, md)
    assert "rendered" not in run("update", run_dir, "--add", "fix_rounds=1")      # up to date: not written again
    with open(os.path.join(run_dir, "acceptance-tests.json"), "w", encoding="utf-8") as fh:
        json.dump({"verdict": "written", "tests": [{"criterion": "AC-1", "file": "t.py", "tests": ["a", "b"]}],
                   "not_tested": [{"criterion": "AC-2", "reason": "needs a browser"}]}, fh)
    out = run("render", run_dir)
    assert out == {"rendered": ["acceptance-tests.md"], "errors": []}, out
    with open(os.path.join(run_dir, "acceptance-tests.md"), encoding="utf-8") as fh:
        md = fh.read()
    assert "| AC-1 | t.py | a, b |" in md and "needs a browser" in md, md
    with open(os.path.join(run_dir, "test-report.json"), "w", encoding="utf-8") as fh:
        fh.write("[1, 2")
    out = run("render", run_dir, "--force")
    assert out["errors"] and out["errors"][0].startswith("test-report.json"), out   # reported, not raised

    # Lanes: the size and risk areas decide what the run spends; a person's choice wins.
    def lane_case(size, risks, readiness="ready", quality="sufficient", config=None, *extra):
        with open(os.path.join(run_dir, "requirements.json"), "w", encoding="utf-8") as fh:
            json.dump({"readiness": readiness, "acceptance_criteria_quality": quality, "size": size,
                       "risk_areas": risks, "acceptance_criteria": [{"id": "AC-1"}]}, fh)
        cfg = os.path.join(os.path.dirname(os.path.dirname(run_dir)), "config.json")
        if config is None:
            if os.path.exists(cfg):
                os.remove(cfg)
        else:
            with open(cfg, "w", encoding="utf-8") as fh:
                json.dump(config, fh)
        return run("intake", run_dir, *extra)

    run("update", run_dir, "--set", "lane=null")
    out = lane_case("S", [])
    assert out["lane"]["name"] == "S" and out["settings"]["gates"] == ["plan", "ship"] and out["needs_refinement"] is False, out
    assert out["settings"]["tests"]["full_suite_runs"] == 1 and out["settings"]["tests"]["mutation"]["max_mutants"] == 10
    assert state(run_dir)["lane"]["name"] == "S" and state(run_dir)["settings"]["review"]["group_below_lines"] == 400
    assert lane_case("S", [], "ready_with_assumptions")["needs_refinement"] is True        # S refines only gaps
    out = lane_case("S", ["external_input"])
    assert out["lane"]["name"] == "M" and out["settings"]["gates"] == ["plan", "ship"] and out["needs_refinement"], out
    out = lane_case("M", ["personal_data"])
    assert out["lane"]["name"] == "L" and out["settings"]["review"] == {"select_lenses": False, "group_below_lines": 0}
    out = lane_case("M", ["personal_data"], "ready", "sufficient", None, "--lane", "S")
    assert out["lane"]["name"] == "S" and out["lane"]["below_minimum"] is True and out["lane"]["forced"] is True
    assert lane_case("M", ["personal_data"])["lane"]["name"] == "S"                      # the choice is kept on resume
    run("update", run_dir, "--set", "lane=null")
    defaults_file = {"gates": ["plan", "ship"], "refine": {"enabled": True},
                     "tests": {"full_suite_runs": 2, "mutation": {"enabled": True, "max_mutants": 40}}}
    assert lane_case("S", [], "ready", "sufficient", defaults_file)["settings"]["tests"]["full_suite_runs"] == 1   # defaults don't pin
    out = lane_case("S", [], "ready", "sufficient", {"lanes": {"S": {"gates": ["ship"]}}})                # opt out of the plan gate
    assert out["settings"]["gates"] == ["ship"], out
    out = lane_case("S", [], "ready", "sufficient", {"tests": {"mutation": {"max_mutants": 5}}, "refine": {"enabled": False}})
    assert out["settings"]["tests"]["mutation"]["max_mutants"] == 5 and out["settings"]["refine"] == "never", out
    out = lane_case("S", [], "ready", "sufficient", {"lanes": {"enabled": False}})
    assert out["lane"]["name"] is None and out["settings"]["gates"] == ["plan", "ship"], out
    out = lane_case("S", [], "ready", "sufficient", {"lanes": {"S": {"gates": ["ship"]}}}, "--gates", "none")
    assert out["settings"]["gates"] == [], out
    assert lane_case("L", [], "ready", "sufficient", {"lanes": {"S": {"gates": ["ship"]}}})["settings"]["gates"] == ["plan", "ship"]

    # Gates: waiting is recorded for the notification hook and cleared by the decision; the ship gate is composed.
    out = run("gate", run_dir, "plan")
    assert out["waiting"] == "plan" and state(run_dir)["waiting"]["gate"] == "plan", out
    run("update", run_dir, "--stage", "plan")
    run("update", run_dir, "--done", "plan", "--intervene", "approval", "ok")
    assert "waiting" not in state(run_dir)
    assert state(run_dir)["human_interventions"][-1]["stage"] == "plan"    # stamped before --done moves on
    with open(os.path.join(run_dir, "requirements.json"), "w", encoding="utf-8") as fh:
        json.dump({"acceptance_criteria": [{"id": "AC-1"}, {"id": "AC-2", "refined": True},
                                           {"id": "AC-3", "removed_by": "delta-01"}]}, fh)
    with open(os.path.join(run_dir, "test-report.json"), "w", encoding="utf-8") as fh:
        json.dump({"verdict": "green", "coverage_verdict": "below minimum",
                   "suite": {"passed": 12, "failed": 0}, "coverage": {"line_percent": 60},
                   "criteria": [{"id": "AC-1", "status": "covered"}, {"id": "AC-2", "status": "covered"}],
                   "mutation": {"mutants": 4, "killed": 3,
                                "surviving": [{"where": "a.py:3", "reason": "equivalent"}]}}, fh)
    run("update", run_dir, "--set", 'review_result={"fixed": 1, "open": 0}', "--set", "pr_template=the plugin's",
        "--set", "source=file")
    proc = subprocess.run([sys.executable, SCRIPT, "gate", run_dir, "ship"], capture_output=True,
                          env=dict(os.environ, PYTHONIOENCODING="cp1252"))      # a Windows console
    assert proc.returncode == 0, proc.stderr
    gate = proc.stdout.decode("utf-8")
    for expected in ("NOT READY — coverage below the minimum, not accepted", "READY TO SHIP — PROJ-7",
                     "Criteria  : 2/2 met · 1 of them added by refinement", "12 passed, 0 failed",
                     "coverage 60 % line (target 80 % · minimum 70 %) — BELOW MINIMUM",
                     "mutants: 3 of 4 killed · 1 surviving", "a.py:3 — equivalent", "Review    : 1 fixed · 0 open",
                     "Deltas    : 1 since the plan was approved", "PR body   : the plugin's", "Ship it?"):
        assert expected in gate, (expected, gate)
    assert "comment on" not in gate and state(run_dir)["waiting"]["gate"] == "ship"    # a file source: no Jira
    print("ok — run state: init, resume, transitions, interventions, notes, intake, reports, lanes, gates")


if __name__ == "__main__":
    main()
