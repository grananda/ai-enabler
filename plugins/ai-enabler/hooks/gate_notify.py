#!/usr/bin/env python3
"""ai-enabler gate notification.

A Notification hook for `idle_prompt`, which Claude Code fires about a minute after it
finished responding with no input since. A delivery run stops at its gates (plan and
ship approval, a delta to approve, coverage below the minimum, a blocked ticket) and
the person may be away. When a run in this project is waiting at one, this raises an
operating-system notification, once per run, gate and wait.

A run is waiting when its .enabler/runs/<KEY>/state.json has
"waiting": {"gate": "...", "since": "..."} and its status is not "stopped". What was
notified is remembered in .enabler/tmp/notified.json.

It never blocks and never fails: the notifier is launched detached and not waited on.
AI_ENABLER_NOTIFY_DRY_RUN=1 prints the command as JSON instead of launching it.

Configuration, in .enabler/config.json:  "notify": {"gates": true}
"""

import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys

TITLE = "ai-enabler"


def project_root(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def enabled(root):
    try:
        with open(os.path.join(root, ".enabler", "config.json"), encoding="utf-8") as fh:
            section = json.load(fh).get("notify")
    except (OSError, ValueError, AttributeError):
        return True
    return not (isinstance(section, dict) and section.get("gates") is False)


def waiting_runs(root):
    found = []
    for path in sorted(glob.glob(os.path.join(root, ".enabler", "runs", "*", "state.json"))):
        try:
            with open(path, encoding="utf-8") as fh:
                state = json.load(fh)
        except (OSError, ValueError):
            continue
        if not isinstance(state, dict) or state.get("status") == "stopped":
            continue
        waiting = state.get("waiting")
        if not isinstance(waiting, dict) or not isinstance(waiting.get("gate"), str) or not waiting["gate"]:
            continue
        key = state.get("key") if isinstance(state.get("key"), str) and state.get("key") else \
            os.path.basename(os.path.dirname(path))
        found.append((key, waiting["gate"], str(waiting.get("since") or "")))
    return found


def describe(key, gate):
    if gate == "blocked":
        return "%s is blocked and needs an answer" % key
    if gate == "coverage":
        return "%s needs a decision on coverage" % key
    return "%s is waiting at the %s gate" % (key, gate)


def load_notified(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return set(x for x in data.get("notified", []) if isinstance(x, str))
    except (OSError, ValueError, AttributeError, TypeError):
        return set()


def save_notified(path, ids):
    tmp = os.path.dirname(path)
    os.makedirs(tmp, exist_ok=True)
    ignore = os.path.join(tmp, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8") as fh:
            fh.write("*\n")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"notified": sorted(ids)}, fh, indent=2)
        fh.write("\n")


def clean(message):
    return re.sub(r"[\x00-\x1f\x7f]+", " ", message)[:250]


def is_wsl():
    return sys.platform.startswith("linux") and "microsoft" in platform.release().lower()


def command(message, dry_run):
    message = clean(message)
    if sys.platform in ("win32", "cygwin", "msys") or (is_wsl() and shutil.which("powershell.exe")):
        text = re.sub("[\"'\u2018\u2019\u201a\u201b]", "''", message)
        script = ("Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
                  "$n = New-Object System.Windows.Forms.NotifyIcon; "
                  "$n.Icon = [System.Drawing.SystemIcons]::Information; "
                  "$n.BalloonTipTitle = '%s'; $n.BalloonTipText = '%s'; $n.Visible = $true; "
                  "$n.ShowBalloonTip(10000); Start-Sleep -Seconds 10; $n.Dispose()" % (TITLE, text))
        exe = shutil.which("powershell") or shutil.which("powershell.exe") or "powershell"
        return [exe, "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden", "-Command", script]
    if sys.platform == "darwin":
        text = message.replace("\\", "\\\\").replace('"', '\\"')
        return ["osascript", "-e", 'display notification "%s" with title "%s"' % (text, TITLE)]
    exe = shutil.which("notify-send")
    if exe or dry_run:
        return [exe or "notify-send", TITLE, message]
    return None


def launch(argv):
    common = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                  close_fds=True)
    if os.name == "nt":
        flags = 0x00000200 | 0x08000000  # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        try:
            # Outlive the hook even when Claude Code runs hooks inside a job object.
            subprocess.Popen(argv, creationflags=flags | 0x01000000, **common)  # CREATE_BREAKAWAY_FROM_JOB
        except OSError:
            subprocess.Popen(argv, creationflags=flags, **common)
    else:
        subprocess.Popen(argv, start_new_session=True, **common)


def main():
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    try:
        payload = json.loads(raw)
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    if payload.get("notification_type") not in (None, "idle_prompt"):
        return 0
    root = project_root(payload)
    if not enabled(root):
        return 0
    runs = waiting_runs(root)
    path = os.path.join(root, ".enabler", "tmp", "notified.json")
    notified = load_notified(path)
    current = set("%s|%s|%s" % run for run in runs)
    if not current - notified:
        if notified - current:
            try:
                save_notified(path, notified & current)
            except OSError:
                pass
        return 0
    try:
        save_notified(path, current)
    except OSError:
        pass
    message = "; ".join(describe(key, gate) for key, gate, _ in runs)
    dry_run = os.environ.get("AI_ENABLER_NOTIFY_DRY_RUN") == "1"
    argv = command(message, dry_run)
    if argv is None:
        return 0
    if dry_run:
        sys.stdout.buffer.write(json.dumps(argv).encode("ascii"))
        sys.stdout.buffer.flush()
        return 0
    launch(argv)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
