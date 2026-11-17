#!/usr/bin/env python3
"""Checks the gate notification hook (dry run, so it is the same on every OS): one
notification per run, gate and wait; nothing for stopped runs, other notifications or
when it is turned off.

    python3 tests/test_gate_notify.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "gate_notify.py")
IDLE = {"hook_event_name": "Notification", "notification_type": "idle_prompt",
        "message": "Claude is waiting for your input"}


class GateNotify(unittest.TestCase):
    def setUp(self):
        self.project = tempfile.mkdtemp(prefix="ai-enabler-notify-")
        os.makedirs(os.path.join(self.project, ".enabler"))
        self.addCleanup(shutil.rmtree, self.project, True)

    def run_hook(self, payload=IDLE, raw=None):
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.project, AI_ENABLER_NOTIFY_DRY_RUN="1")
        data = raw if raw is not None else json.dumps(dict(payload, cwd=self.project)).encode("ascii")
        out = subprocess.run([sys.executable, HOOK], input=data, capture_output=True, env=env, timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(out.stdout) if out.stdout else None

    def run_state(self, key, gate=None, since="2026-11-17T10:00:00Z", status="active"):
        folder = os.path.join(self.project, ".enabler", "runs", key)
        os.makedirs(folder, exist_ok=True)
        state = {"key": key, "stage": "plan", "status": status}
        if gate:
            state["waiting"] = {"gate": gate, "since": since}
        with open(os.path.join(folder, "state.json"), "w") as fh:
            json.dump(state, fh)

    def test_no_runs_nothing(self):
        self.assertIsNone(self.run_hook())
        self.run_state("AI4IT-1")
        self.assertIsNone(self.run_hook())
        self.assertFalse(os.path.exists(os.path.join(self.project, ".enabler", "tmp")))

    def test_waiting_run_notifies_once_per_wait(self):
        self.run_state("AI4IT-36", "plan")
        argv = self.run_hook()
        self.assertIsInstance(argv, list)
        self.assertTrue(all(isinstance(a, str) for a in argv))
        self.assertIn("AI4IT-36 is waiting at the plan gate", " ".join(argv))
        self.assertIn("ai-enabler", " ".join(argv))
        self.assertIsNone(self.run_hook())
        with open(os.path.join(self.project, ".enabler", "tmp", ".gitignore")) as fh:
            self.assertEqual(fh.read().strip(), "*")
        # The next gate, or a new wait at the same gate, notifies again.
        self.run_state("AI4IT-36", "ship")
        self.assertIn("AI4IT-36 is waiting at the ship gate", " ".join(self.run_hook()))
        self.run_state("AI4IT-36", "ship", since="2026-11-17T11:00:00Z")
        self.assertIsNotNone(self.run_hook())
        self.assertIsNone(self.run_hook())

    def test_several_runs_one_notification(self):
        self.run_state("AI4IT-36", "blocked")
        self.run_state("AI4IT-40", "coverage")
        self.run_state("AI4IT-41", "delta")
        text = " ".join(self.run_hook())
        for part in ("AI4IT-36 is blocked and needs an answer", "AI4IT-40 needs a decision on coverage",
                     "AI4IT-41 is waiting at the delta gate"):
            self.assertIn(part, text)
        self.assertIsNone(self.run_hook())

    def test_stopped_run_ignored(self):
        self.run_state("AI4IT-36", "plan", status="stopped")
        self.assertIsNone(self.run_hook())

    def test_disabled_by_config(self):
        self.run_state("AI4IT-36", "plan")
        with open(os.path.join(self.project, ".enabler", "config.json"), "w") as fh:
            json.dump({"notify": {"gates": False}}, fh)
        self.assertIsNone(self.run_hook())
        with open(os.path.join(self.project, ".enabler", "config.json"), "w") as fh:
            json.dump({"notify": {"gates": True}}, fh)
        self.assertIsNotNone(self.run_hook())

    def test_other_notifications_and_bad_input(self):
        self.run_state("AI4IT-36", "plan")
        self.assertIsNone(self.run_hook(dict(IDLE, notification_type="permission_prompt")))
        for raw in (b"not json", b"", b"[1]"):
            self.assertIsNone(self.run_hook(raw=raw))
        bad = os.path.join(self.project, ".enabler", "runs", "AI4IT-9")
        os.makedirs(bad)
        with open(os.path.join(bad, "state.json"), "w") as fh:
            fh.write("{broken")
        os.makedirs(os.path.join(self.project, ".enabler", "tmp"))
        with open(os.path.join(self.project, ".enabler", "tmp", "notified.json"), "w") as fh:
            fh.write("garbage")
        self.assertIn("AI4IT-36", " ".join(self.run_hook()))

    def test_quotes_cannot_break_out(self):
        self.run_state("Q-1", "plan")
        with open(os.path.join(self.project, ".enabler", "runs", "Q-1", "state.json"), "w") as fh:
            json.dump({"key": "O'Brien\"-1", "status": "active", "waiting": {"gate": "plan", "since": "x"}}, fh)
        argv = self.run_hook()
        self.assertIn("Brien", " ".join(argv))
        if "-Command" in argv:
            script = argv[-1]
            self.assertNotIn("O'Brien", script)
            self.assertIn("O''Brien''-1", script)
            self.assertNotIn('"', script)


if __name__ == "__main__":
    unittest.main()
