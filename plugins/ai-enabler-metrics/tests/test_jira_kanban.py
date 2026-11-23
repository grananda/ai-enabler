#!/usr/bin/env python3
"""Offline and mocked REST regressions; no credentials or network needed."""
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import delivery_lib as L
import jira_cycle as J

NOW = datetime(2026, 10, 20, tzinfo=timezone.utc)


def config():
    cfg = L.load_config(None)
    cfg["jira"] = L.merge(cfg["jira"], {"mode": "kanban", "project": "T", "board": "7",
                                         "since": "2026-09-28", "until": "2026-10-12"})
    return cfg


def issue(key, resolved=None, moves=(), created="2026-09-01", status=None):
    return {"key": key, "created": created, "resolved": resolved, "type": "Story", "assignee": "Alice",
            "status": status or (moves[-1][2] if moves else "To Do"), "history_complete": True,
            "transitions": [{"at": at, "from": a, "to": b} for at, a, b in moves]}


class PeriodTests(unittest.TestCase):
    def test_defaults_and_months(self):
        cfg = config()["jira"]
        cfg.update(since=None, until=None)
        p = L.jira_periods(cfg, NOW)
        self.assertEqual(len(p), 6)
        self.assertEqual(p[-1]["end"], "2026-10-19T00:00:00+00:00")
        cfg.update(since="2026-09-28", until="2026-11-03", group_by="month")
        p = L.jira_periods(cfg, NOW)
        self.assertEqual([x["name"] for x in p], ["2026-09", "2026-10", "2026-11"])
        self.assertEqual(p[-1]["end"], "2026-11-03T00:00:00+00:00")

    def test_invalid_config(self):
        for override in ({"mode": "oops"}, {"group_by": "day"}, {"since": "oops"},
                         {"until": None}, {"until": "2026-09-01"}, {"weeks": 0},
                         {"sprints": -1}, {"board": "7 OR project=T"}, {"filter": 2}):
            with self.subTest(override=override), self.assertRaises(L.ConfigError):
                L.validate_jira(L.merge(config()["jira"], override))

    def test_resolution_boundaries_and_earlier_start(self):
        cfg = config()
        moves = [("2026-09-21", "To Do", "In Progress")]
        r = J.analyse([], [issue("START", "2026-09-28", moves),
                           issue("MID", "2026-10-05T02:00:00+0200", moves),
                           issue("END", "2026-10-12", moves)], cfg, NOW)
        self.assertEqual(r["overall"]["total"], 2)
        self.assertEqual(r["by_period"]["2026-W40"]["total"], 1)
        self.assertEqual(r["by_period"]["2026-W41"]["total"], 1)
        self.assertEqual(r["overall"]["median"], 7.5)  # lifetime 5 and 10 working days
        self.assertEqual(r["resolved_outside"], ["END"])
        self.assertNotIn("sprints", r)
        self.assertNotIn("by_sprint", r)

    def test_historical_and_current_blocking(self):
        records = [
            issue("OPEN", moves=[("2026-09-10", "To Do", "In Progress"),
                                  ("2026-09-20", "In Progress", "Blocked")]),
            issue("LATER", "2026-10-15", [("2026-09-20", "To Do", "Blocked"),
                                            ("2026-10-15", "Blocked", "Done")]),
            issue("CURRENT", moves=[("2026-10-13", "In Progress", "Blocked")]),
            issue("OLD", "2026-09-10", [("2026-09-01", "To Do", "Blocked"),
                                          ("2026-09-10", "Blocked", "Done")]),
            issue("FUTURE", created="2026-10-12", status="Blocked"),
            issue("INITIAL", status="Blocked"),
        ]
        r = J.analyse([], records, config(), NOW)
        self.assertEqual(r["issues"], 4)
        self.assertEqual(r["overall"]["n"], 0)
        self.assertIsNone(r["overall"]["median"])
        self.assertEqual({x["key"]: x["days"] for x in r["blocked"]},
                         {"OPEN": 14, "LATER": 14, "INITIAL": 14})
        self.assertEqual({x["key"] for x in r["blocked_now"]}, {"OPEN", "CURRENT", "INITIAL"})
        page = J.render(r, "T", config())
        self.assertIn("Historical blocking still covers open tickets", page)
        self.assertIn("Per week", page)

    def test_backward_boundary_and_missing_history(self):
        records = [issue("A", "2026-10-10", [("2026-09-20", "To Do", "In Progress"),
                                              ("2026-09-27", "In Progress", "In Review"),
                                              ("2026-09-28", "In Review", "In Progress"),
                                              ("2026-10-11", "In Progress", "In Review"),
                                              ("2026-10-12", "In Review", "In Progress")])]
        records[0]["history_complete"] = False
        r = J.analyse([], records, config(), NOW)
        self.assertEqual(len(r["reverted"][0]["moves"]), 1)
        self.assertEqual(r["truncated_changelogs"], ["A"])
        self.assertEqual(r["unverified_changelogs"], ["A"])

    def test_empty_and_scrum_compatibility(self):
        r = J.analyse([], [], config(), NOW)
        self.assertEqual(len(r["periods"]), 2)
        self.assertEqual(r["blocked_now"], [])
        self.assertIn("No ticket was resolved", J.render(r, "T", config()))
        sprints = [{"name": "S1", "start": "2026-09-28", "end": "2026-10-12"}]
        old = J.analyse(sprints, [issue("A", "2026-10-12", [("2026-09-21", "To Do", "In Progress")])],
                        L.load_config(None), NOW)
        self.assertEqual(old["by_sprint"]["S1"]["total"], 1)  # legacy inclusive end remains
        self.assertEqual(L.cycle_periods(old), (old["sprints"], old["by_sprint"], "sprint"))


class RestTests(unittest.TestCase):
    def client(self):
        jira = J.Jira()
        jira.base = "https://jira.example.test"
        return jira

    def test_board_scope_and_issue_pagination(self):
        jira = self.client()
        calls = []
        def get(path, **params):
            calls.append((path, params))
            if path.endswith("/configuration"):
                return {"filter": {"id": 99}}
            if path.endswith("/search"):
                self.assertIn("filter = 99", params["jql"])
                self.assertNotIn("project =", params["jql"])
                self.assertNotIn("resolved", params["jql"])
                self.assertNotIn("created >=", params["jql"])
                n = params["startAt"]
                return {"total": 2, "issues": [{"key": "T-%d" % n, "fields": {},
                                               "changelog": {"histories": [], "total": 0}}]}
            raise AssertionError(path)
        with patch.object(jira, "get", side_effect=get):
            issues, scope = jira.collect_kanban("T", L.jira_periods(config()["jira"], NOW), "7")
        self.assertEqual(len(issues), 2)
        self.assertEqual(scope["board"], "7")
        self.assertEqual(scope["filter"], "99")
        self.assertEqual(len(calls), 3)

    def test_auto_selection_and_no_scope_fallback(self):
        jira = self.client()
        periods = L.jira_periods(config()["jira"], NOW)
        for boards in ([], [{"id": 1}, {"id": 2}]):
            with patch.object(jira, "paged", return_value=boards), self.assertRaises(RuntimeError):
                jira.collect_kanban("T", periods)
        with patch.object(jira, "get", return_value={}) as get, self.assertRaises(RuntimeError):
            jira.collect_kanban("T", periods, "7")
        self.assertEqual(get.call_count, 1)
        with patch.object(jira, "paged", return_value=[]) as paged:
            _, scope = jira.collect_kanban("T", periods, filter_id="99")
        self.assertEqual(scope["filter"], "99")
        self.assertEqual(paged.call_count, 1)
        with patch.object(jira, "paged", side_effect=[[{"id": 7}], []]) as paged, \
                patch.object(jira, "get", return_value={"filter": {"id": 99}}):
            _, scope = jira.collect_kanban("T", periods)
        self.assertEqual(scope["board"], "7")
        self.assertEqual(paged.call_args_list[0].kwargs["type"], "kanban")

    def test_history_pages_and_failure_flag(self):
        jira = self.client()
        raw = {"key": "T-1", "fields": {}, "changelog": {"total": 3, "histories": []}}
        pages = [{"total": 3, "values": [{"id": 1}, {"id": 2}]}, {"total": 3, "values": [{"id": 3}]}]
        with patch.object(jira, "get", side_effect=pages) as get:
            result = jira.complete_history(copy.deepcopy(raw))
        self.assertTrue(result["history_complete"])
        self.assertEqual(len(result["changelog"]["histories"]), 3)
        self.assertEqual(get.call_args_list[1].kwargs["startAt"], 2)
        with patch.object(jira, "get", side_effect=RuntimeError("unsupported")):
            self.assertTrue(J.normalize(jira.complete_history(copy.deepcopy(raw)))["truncated"])
        with patch.object(jira, "get", return_value={"total": 3, "values": []}), self.assertRaises(RuntimeError):
            jira.paged("/x", "values")

    def test_scrum_explicit_board_is_not_global_sprint(self):
        jira = self.client()
        with patch.object(jira, "paged", side_effect=[[
                {"id": 5, "name": "S", "startDate": "2026-09-01", "endDate": "2026-09-15"}], []]) as paged:
            jira.collect("T", 3, "7")
        self.assertEqual(paged.call_args_list[1].args[0], "/rest/agile/1.0/board/7/sprint/5/issue")

    def test_credentials_not_in_errors(self):
        jira = self.client()
        jira.base = "https://user:SECRET@jira.example.test?token=SECRET"
        with self.assertRaises(RuntimeError) as cm:
            jira.check_url()
        self.assertNotIn("SECRET", str(cm.exception))


class OfflineTests(unittest.TestCase):
    def test_legacy_scrum_with_board_still_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = L.load_config(None)
            cfg["jira"].update(project="T", board="7")
            scope, collected = J.load_collection(tmp, cfg["jira"], [])
            self.assertFalse(scope["scope_verified"])
            self.assertIsNone(scope["board"])
            self.assertEqual(scope["requested_board"], "7")
            self.assertIsNone(collected)
            with open(os.path.join(tmp, "sprints.json"), "w") as fh:
                json.dump([{"name": "S", "start": "2026-09-01", "end": "2026-09-15"}], fh)
            with open(os.path.join(tmp, "issues.json"), "w") as fh:
                json.dump([], fh)
            mdir, out = os.path.join(tmp, "metrics"), os.path.join(tmp, "out")
            run = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "jira_cycle.py"),
                                  "--project", "T", "--board", "7", "--input", tmp,
                                  "--metrics-dir", mdir, "--out-dir", out], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            with open(os.path.join(out, "cycle-time.html"), encoding="utf-8") as fh:
                self.assertIn("scope and freshness are unverified", fh.read())

    def test_contract_cli_dashboard_and_privacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp, mdir, out = [os.path.join(tmp, p) for p in ("input", "metrics", "out")]
            os.makedirs(inp)
            os.makedirs(mdir)
            cfg = config()
            cfg["show_people"] = False
            with open(os.path.join(mdir, "config.json"), "w") as fh:
                json.dump({"delivery": {"jira": cfg["jira"], "show_people": False}}, fh)
            periods = L.jira_periods(cfg["jira"], NOW)
            scope = J.collection_scope("kanban", "T", "7", "99", periods, "week")
            meta = {"scope": scope, "collected_at": NOW.isoformat(), "issues_complete": True}
            with self.assertRaises(ValueError):
                J.load_collection(inp, cfg["jira"], periods)
            def write_meta():
                with open(os.path.join(inp, "collection.json"), "w") as fh:
                    json.dump(meta, fh)
            write_meta()
            got, observed = J.load_collection(inp, cfg["jira"], periods)
            self.assertEqual(got, scope)
            self.assertEqual(observed, NOW)
            for key, value in (("board", "8"), ("mode", "scrum"), ("window", []), ("group_by", "month")):
                saved = scope[key]
                scope[key] = value
                write_meta()
                with self.assertRaises(ValueError):
                    J.load_collection(inp, cfg["jira"], periods)
                scope[key] = saved
            write_meta()
            command = [sys.executable, os.path.join(ROOT, "scripts", "jira_cycle.py"), "--input", inp,
                       "--metrics-dir", mdir, "--out-dir", out]
            for records in ([], [issue("T-1", "2026-10-01", [("2026-09-20", "To Do", "In Progress")])]):
                with open(os.path.join(inp, "issues.json"), "w") as fh:
                    json.dump(records, fh)
                run = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)
                with open(os.path.join(mdir, "delivery", "cycle-time.json")) as fh:
                    snap = json.load(fh)
                self.assertEqual(snap["scope"], scope)
                self.assertNotIn("Alice", json.dumps(snap))
                dash = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "delivery_report.py"),
                                       "--metrics-dir", mdir, "--out-dir", out], capture_output=True, text=True)
                self.assertEqual(dash.returncode, 0, dash.stderr)
                with open(os.path.join(out, "delivery.html"), encoding="utf-8") as fh:
                    page = fh.read()
                self.assertIn("Kanban", page)
                self.assertIn("Median cycle time per week", page)
                self.assertNotIn("closed sprints", page)
                self.assertIn("filter 99", page)


if __name__ == "__main__":
    unittest.main()
