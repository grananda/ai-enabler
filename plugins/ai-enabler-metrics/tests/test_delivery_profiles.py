#!/usr/bin/env python3
"""Named delivery profiles: configuration, credential isolation and offline CLI checks."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import delivery_lib as L
import jira_cycle as J


class Profiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.write("config.json", {"delivery": {"weeks": 9, "show_people": False,
                    "jira": {"project": "LEGACY", "board": 99, "statuses": {"blocked": ["Paused"]}}}})

    def write(self, name, value):
        path = os.path.join(self.root, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(value, fh)
        return path

    def profile(self, name="alpha", mode="kanban"):
        jira = {"mode": mode, "project": "TEAM", "board": 7}
        if mode == "kanban":
            jira.update(since="2026-09-28", until="2026-10-12", group_by="week")
        data = {"connection": {"url": "https://%s.example.test/jira" % name,
                               "personal_token_env": "TOKEN_" + name.upper()},
                "delivery": {"repo": "example/" + name, "base_branch": "main", "weeks": 4, "jira": jira}}
        self.write("profiles/%s.json" % name, data)
        return data

    def test_precedence_and_context_reset(self):
        self.profile()
        cfg = L.load_config(self.root, "alpha")
        self.assertEqual(cfg["weeks"], 4)
        self.assertFalse(cfg["show_people"])
        self.assertEqual(cfg["jira"]["board"], 7)
        self.assertEqual(cfg["jira"]["statuses"]["blocked"], L.DEFAULTS["jira"]["statuses"]["blocked"])
        over = L.jira_overlay(cfg["jira"], {"filter": 8, "since": "2026-01-01", "until": "2026-02-01"})
        self.assertIsNone(over["board"])
        self.assertEqual(over["mode"], "kanban")
        self.assertEqual(over["project"], "TEAM")
        self.assertEqual(over["since"], "2026-01-01")
        other = L.jira_overlay(cfg["jira"], {"mode": "scrum"})
        self.assertIsNone(other["board"])
        self.assertIsNone(other["since"])
        same = L.jira_overlay(cfg["jira"], {"since": "2026-09-01"})
        self.assertEqual(same["board"], 7)
        self.assertEqual(same["until"], "2026-10-12")
        self.assertEqual(L.load_config(self.root)["jira"]["board"], 99)

    def test_invalid_names_and_files(self):
        for name in ("con", "nul", "com1", "lpt9", "", "../alpha", "a/b", "a\\b", "..", "UPPER", "a" * 65, "missing"):
            with self.subTest(name=name), self.assertRaises(L.ConfigError):
                L.load_config(self.root, name)
        for data in ([], {"token": "secret"}, {"delivery": []}, {"delivery": {"jira": []}}):
            self.write("profiles/bad.json", data)
            with self.assertRaises(L.ConfigError):
                L.load_config(self.root, "bad")

    def test_connection_security_and_no_environment_mutation(self):
        self.profile()
        with patch.dict(os.environ, {"JIRA_URL": "https://other.example.test", "JIRA_PERSONAL_TOKEN": "WRONG",
                                     "TOKEN_ALPHA": "PRIVATE_VALUE"}, clear=True):
            before = dict(os.environ)
            cfg = L.load_config(self.root, "alpha")
            client = J.Jira(cfg["_connection"], "alpha")
            self.assertEqual(client.base, "https://alpha.example.test/jira")
            self.assertEqual(client.auth, "Bearer PRIVATE_VALUE")
            self.assertNotIn("PRIVATE_VALUE", json.dumps(cfg, default=str))
            self.assertFalse(J.Jira(None, "alpha").available)
            del os.environ["TOKEN_ALPHA"]
            self.assertFalse(J.Jira(cfg["_connection"], "alpha").available)
            os.environ["TOKEN_ALPHA"] = "PRIVATE_VALUE"
            self.assertEqual(before, dict(os.environ))
        for connection in ({"url": "http://a.test", "personal_token_env": "A"},
                           {"url": "https://user:SECRET@a.test", "personal_token_env": "A"},
                           {"url": "https://a.test?token=SECRET", "personal_token_env": "A"},
                           {"url": "https://a.test"},
                           {"url": "https://a.test", "token": "SECRET"},
                           {"url": "https://a.test", "personal_token_env": "not a variable"}):
            with self.assertRaises(L.ConfigError) as cm:
                L.validate_connection(connection)
            self.assertNotIn("SECRET", str(cm.exception))

    def run_cli(self, script, *args, ok=True):
        run = subprocess.run([sys.executable, os.path.join(ROOT, "scripts", script), *args,
                              "--metrics-dir", self.root], capture_output=True, text=True)
        self.assertEqual(run.returncode == 0, ok, run.stderr)
        self.assertNotIn("Traceback", run.stderr)
        return run

    def test_two_profiles_full_offline_and_dashboard(self):
        for name, mode in (("alpha", "kanban"), ("beta", "scrum")):
            profile = self.profile(name, mode)
            cfg = L.load_config(self.root, name)
            inp = os.path.join(self.root, "input-" + name)
            if mode == "kanban":
                periods = L.jira_periods(cfg["jira"])
                scope = J.collection_scope(mode, "TEAM", 7, 8, periods, "week")
            else:
                scope = {"mode": mode, "project": "TEAM", "board": "7", "filter": None, "sprint_ids": [1]}
                self.write("input-%s/sprints.json" % name,
                           [{"id": 1, "name": "S", "start": "2026-09-28", "end": "2026-10-12"}])
            scope.update(profile=name, connection_url=profile["connection"]["url"])
            meta = {"scope": scope, "collected_at": "2026-10-13T00:00:00Z", "issues_complete": True}
            self.write("input-%s/collection.json" % name, meta)
            self.write("input-%s/issues.json" % name, [])
            self.run_cli("jira_cycle.py", "--profile", name, "--input", inp)
            data = {"profile": name, "repo": "example/" + name, "host": "github.com", "base": "main",
                    "weeks": 4, "followup_days": 14, "window_start": "2026-09-01T00:00:00Z",
                    "window_end": "2026-10-01T00:00:00Z", "lookback_start": "2026-08-18T00:00:00Z",
                    "prs": [], "files": {}, "reviews": {}, "timeline": {}}
            path = self.write("prs-%s.json" % name, data)
            self.run_cli("pr_metrics.py", "all", "--profile", name, "--input", path)
            _, report_dir = L.output_dirs(self.root, profile=name)
            self.write(os.path.relpath(os.path.join(report_dir, "usage.json"), self.root),
                       {"overall": {"cost_usd": 999, "ai_seconds": 0, "human_interactions": 0, "lines_added": 0}})
            result = self.run_cli("delivery_report.py", "--profile", name)
            with open(result.stdout.strip(), encoding="utf-8") as fh:
                page = fh.read()
            self.assertNotIn("999", page)
            self.assertNotIn("AI cost", page)
            self.assertIn("profile " + name, page)
            self.assertIn("example/" + name, page)
            self.assertNotIn("example/" + ("beta" if name == "alpha" else "alpha"), page)
            with open(os.path.join(self.root, "profiles-data", name, "delivery", "cycle-time.json")) as fh:
                snapshot = json.load(fh)
            self.assertEqual(snapshot["profile"], name)
            self.assertEqual(snapshot["scope"]["connection_url"], profile["connection"]["url"])
            self.assertNotIn("personal_token_env", json.dumps(snapshot))
            other = "beta" if name == "alpha" else "alpha"
            self.profile(other, "scrum")
            self.run_cli("jira_cycle.py", "--profile", other, "--input", inp, ok=False)
            self.run_cli("pr_metrics.py", "all", "--profile", other, "--input", path, ok=False)
        self.assertFalse(os.path.exists(os.path.join(self.root, "delivery")))

    def test_cli_window_override_and_wrong_server(self):
        profile = self.profile()
        cfg = L.load_config(self.root, "alpha")
        changed = L.jira_overlay(cfg["jira"], {"since": "2026-08-01", "until": "2026-09-01", "group_by": "month"})
        scope = J.collection_scope("kanban", "TEAM", 7, 8, L.jira_periods(changed), "month")
        scope.update(profile="alpha", connection_url=profile["connection"]["url"])
        meta = {"scope": scope, "collected_at": "2026-10-13T00:00:00Z", "issues_complete": True}
        self.write("input/collection.json", meta)
        self.write("input/issues.json", [])
        inp = os.path.join(self.root, "input")
        flags = ("--profile", "alpha", "--input", inp, "--since", "2026-08-01", "--until", "2026-09-01", "--group-by", "month")
        self.run_cli("jira_cycle.py", *flags)
        scope["connection_url"] = "https://different.example.test"
        self.write("input/collection.json", meta)
        self.run_cli("jira_cycle.py", *flags, ok=False)

    def test_redirect_never_forwards_to_other_origin(self):
        import urllib.request
        import urllib.error
        self.profile()
        connection = L.load_config(self.root, "alpha")["_connection"]
        client = J.Jira(connection, "alpha")
        def opener(handler):
            request = urllib.request.Request(client.base + "/api", headers={"Authorization": "Bearer PRIVATE"})
            for target in ("https://other.example.test/path", "http://alpha.example.test/path"):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    handler().redirect_request(request, None, 302, "redirect", {}, target)
                error.exception.close()
            raise urllib.error.URLError("PRIVATE")
        with patch("urllib.request.build_opener", side_effect=opener), self.assertRaises(RuntimeError) as cm:
            client.get("/api")
        self.assertNotIn("PRIVATE", str(cm.exception))

    def test_explicit_output_directory_ownership(self):
        self.profile()
        self.profile("beta")
        out = os.path.join(self.root, "custom")
        a, report = L.output_dirs(self.root, out, profile="alpha")
        self.assertIn("profiles-data", a)
        self.assertEqual(report, out)
        with self.assertRaises(L.ConfigError):
            L.output_dirs(self.root, out, profile="beta")
        with self.assertRaises(L.ConfigError):
            L.output_dirs(self.root, out)
        self.assertEqual(L.output_dirs(self.root, out, profile="alpha"), (a, report))
        with tempfile.TemporaryDirectory() as other_root, self.assertRaises(L.ConfigError):
            L.output_dirs(other_root, out, profile="alpha")
        self.write("custom/.delivery-profile.json", {"profile": "alpha"})
        with self.assertRaises(L.ConfigError):
            L.output_dirs(self.root, out, profile="alpha")


if __name__ == "__main__":
    unittest.main()
