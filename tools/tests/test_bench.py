"""Tests for the benchmark comparison table."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bench

REPORT = """### Acceptance criteria

| AC | Criterion | From | Status | Evidence |
|---|---|---|---|---|
| AC-1 | Four hours exactly | ticket | met | test |
| AC-2 | Over four hours | ticket | not met | — |
| AC-10 | Refinement | refinement | met; CR-1 closed | test |
"""


def usage(cost, reviewer, cache_read, first="2026-11-13T12:00:00Z", last="2026-11-13T13:16:00Z"):
    return {"overall": {"cost_usd": cost, "tokens_input": 1000, "tokens_output": 100000,
                        "tokens_cache_read": cache_read, "tokens_cache_write": 50000,
                        "ai_seconds": 3720, "human_seconds": 630, "first_event": first,
                        "last_event": last, "human_interactions": 4, "tool_calls": 873,
                        "subagent_runs": 17, "compactions": 0},
            "cost_by": {"agent": {"main": cost - reviewer, "ai-enabler:delivery-code-reviewer": reviewer}},
            "pricing": {"unpriced_tokens": {}}}


class BenchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="bench-test-"))
        run = self.tmp / "run"
        run.mkdir()
        (run / "delivery-report.md").write_text(REPORT, encoding="utf-8")
        (run / "state.json").write_text(json.dumps({
            "gate_rounds": {"plan": 0, "ship": 1},
            "human_interventions": [{"kind": "approval"}, {"kind": "fix"}, {"kind": "hold"}]}), encoding="utf-8")
        for name, data in (("a.json", usage(8.0, 2.0, 27000000)), ("b.json", usage(4.0, 1.0, 13500000))):
            (self.tmp / name).write_text(json.dumps(data), encoding="utf-8")

    def test_two_cases_with_quality(self):
        out = io.StringIO()
        with redirect_stdout(out):
            bench.main(["--case", "run 1", str(self.tmp / "a.json"), str(self.tmp / "run"),
                        "--case", "run 2", str(self.tmp / "b.json"), str(self.tmp / "run")])
        text = out.getvalue()
        self.assertIn("| Indicator | run 1 | run 2 | Last vs first |", text)
        self.assertIn("| Cost | $8.00 | $4.00 | -50 % |", text)
        self.assertIn("| · ai-enabler:delivery-code-reviewer | $2.00 | $1.00 | -50 % |", text)
        self.assertIn("| AI working time | 1h 02m | 1h 02m | +0 % |", text)
        self.assertIn("| Wall clock | 1h 16m | 1h 16m | +0 % |", text)
        # "not met" is not met; a status with a note after it ("met; CR-1 closed") is.
        self.assertIn("| Acceptance criteria met | 2 / 3 | 2 / 3 |  |", text)
        self.assertIn("| Human interventions | approval 1, fix 1, hold 1 |", text)

    def test_single_case_without_run_dir(self):
        out = self.tmp / "bench.md"
        bench.main(["--case", "only", str(self.tmp / "a.json"), "--out", str(out)])
        text = out.read_text(encoding="utf-8")
        self.assertIn("| Indicator | only |", text)
        self.assertNotIn("Last vs first", text)
        self.assertNotIn("**Quality**", text)


if __name__ == "__main__":
    unittest.main()
