#!/usr/bin/env python3
"""ai-enabler-metrics capture hook.

One script handles every hook event the plugin registers. For each event it
appends one JSON line to

    <metrics_dir>/events/<user>/<session_id>.jsonl

`usage_report.py` turns those lines into the usage report.

Properties
- OPT-IN   : does nothing unless the project has a `.enabler/metrics/` directory
             (created by `/ai-enabler-metrics:metrics-usage-init`) or ENABLER_METRICS_DIR is set.
- PASSIVE  : only records. Never blocks, never prints to stdout (on
             UserPromptSubmit and SessionStart stdout would be injected into
             the conversation), always exits 0.
- PRIVATE  : never stores prompt text, model output, file contents or command
             lines. It stores counts, names, durations, token totals, and the
             ticket key it recognises.
- COST     : hook payloads carry no token or cost data, so at the end of each
             turn the script reads the session transcript (and the subagent
             transcripts next to it), totals `message.usage` per model, and
             records the delta since the previous turn.

Event reference: ../README.md and docs/metrics-reference.md in the marketplace.
"""

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone

try:
    import fcntl
except ImportError:  # Windows: no advisory locking, last writer wins
    fcntl = None

SCHEMA = 1
METRICS_REL = os.path.join(".enabler", "metrics")
# Before 1.0.0 the folder was .enabler/kpi and the variables ENABLER_KPI_*. A project
# that has not moved its folder yet keeps being captured.
LEGACY_REL = os.path.join(".enabler", "kpi")


def setting(name):
    """ENABLER_METRICS_<name>, or the pre-1.0.0 ENABLER_KPI_<name>."""
    return os.environ.get("ENABLER_METRICS_" + name) or os.environ.get("ENABLER_KPI_" + name)
DEFAULT_TICKET_PATTERN = r"\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b"
# Things that look like issue keys and are not.
NOT_TICKETS = {
    "UTF", "SHA", "ISO", "CVE", "RFC", "HTTP", "TLS", "SSL", "AES", "MD", "RSA",
    "CWE", "JDK", "JSR", "ES", "PEP", "UTC", "GMT", "COVID", "HTTPS", "TCP",
    "IPV", "BASE", "CP", "WINDOWS", "LATIN", "ASCII", "OPUS",
    "SONNET", "HAIKU", "FABLE", "CLAUDE", "GPT", "PYTHON", "JAVA", "NODE",
}
# A slash command is "/name" or "/plugin:name"; "/home/me/file.py is broken" is not.
SLASH_COMMAND = re.compile(r"^/[A-Za-z][\w-]*(:[\w-]+)*$")
# Prompts the harness submits on its own, not a person.
HARNESS_PROMPT = re.compile(
    r"^<(task-notification|system-reminder|local-command-[a-z]+|command-[a-z]+|bash-[a-z]+)\b")
WRITE_TOOLS = {"write", "edit", "multiedit", "notebookedit"}
QUESTION_TOOLS = {"askuserquestion"}
AGENT_TOOLS = {"agent", "task"}


# ----------------------------------------------------------------- locating

def find_metrics_dir(cwd):
    """Where to write, or None when capture is off for this project."""
    env = setting("DIR")
    if env:
        try:
            os.makedirs(env, exist_ok=True)
            return env
        except OSError:
            return None
    starts = [os.environ.get("CLAUDE_PROJECT_DIR"), cwd, os.getcwd()]
    for start in starts:
        if not start:
            continue
        d = os.path.abspath(start)
        # The project root may be above cwd (a session started in a subfolder).
        for _ in range(12):
            for rel in (METRICS_REL, LEGACY_REL):
                candidate = os.path.join(d, rel)
                if os.path.isdir(candidate):
                    return candidate
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return None


def load_config(metrics_dir):
    try:
        with open(os.path.join(metrics_dir, "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
            return cfg if isinstance(cfg, dict) else {}
    except (OSError, ValueError):
        return {}


def safe_name(value, fallback="unknown"):
    s = re.sub(r"[^A-Za-z0-9._@-]", "_", str(value or ""))[:80].strip("._")
    return s or fallback


def git(args, cwd):
    try:
        out = subprocess.run(
            ["git"] + args, cwd=cwd or None, capture_output=True, text=True, timeout=3
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def resolve_user(cfg, cwd):
    user = setting("USER") or git(["config", "user.email"], cwd)
    if not user:
        user = os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"
    if cfg.get("anonymize_users"):
        user = "u-" + hashlib.sha256(user.lower().encode("utf-8")).hexdigest()[:10]
    return safe_name(user)


def detect_platform():
    """Which API serves this session, from the environment Claude Code runs in.

    Prices differ per provider, and on Bedrock per region and per kind of
    inference profile, and the transcript does not always say: recorded here so
    the report prices each session with the right table.
    """
    env = os.environ
    on = lambda name: env.get(name, "").strip().lower() not in ("", "0", "false", "no")
    info = {}
    if on("CLAUDE_CODE_USE_BEDROCK"):
        info["provider"] = "bedrock"
        info["region"] = env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION")
        scopes = set()
        for var in ("ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_SMALL_FAST_MODEL",
                    "CLAUDE_CODE_SUBAGENT_MODEL"):
            value = env.get(var, "").lower().rsplit("/", 1)[-1]
            if value.startswith("global."):
                scopes.add("global")
            elif re.match(r"^(us-gov|us|eu|apac|jp|au|ca|sa|me|af)\.", value):
                scopes.add("regional")
        if len(scopes) == 1:
            info["scope"] = scopes.pop()
    elif on("CLAUDE_CODE_USE_VERTEX"):
        info["provider"] = "vertex"
        info["region"] = env.get("CLOUD_ML_REGION")
    elif on("CLAUDE_CODE_USE_FOUNDRY"):
        info["provider"] = "foundry"
    elif env.get("ANTHROPIC_BASE_URL") and "anthropic.com" not in env["ANTHROPIC_BASE_URL"]:
        info["provider"] = "gateway"
    return {k: v for k, v in info.items() if v}


# -------------------------------------------------------------------- state

class Session:
    """Per-session state, shared by concurrent hook processes through a lock."""

    def __init__(self, metrics_dir, sid):
        self.dir = os.path.join(metrics_dir, ".state")
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, safe_name(sid) + ".json")
        self.lock = None
        self.data = {}

    def __enter__(self):
        self.lock = open(self.path + ".lock", "a+")
        if fcntl:
            fcntl.flock(self.lock, fcntl.LOCK_EX)
        try:
            with open(self.path, encoding="utf-8") as fh:
                self.data = json.load(fh)
        except (OSError, ValueError):
            self.data = {}
        return self

    def __exit__(self, *exc):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh)
            os.replace(tmp, self.path)
        finally:
            if fcntl:
                fcntl.flock(self.lock, fcntl.LOCK_UN)
            self.lock.close()
        return False


# ------------------------------------------------------------------ tickets

def find_ticket(text, cfg):
    if not text:
        return None
    pattern = cfg.get("ticket_pattern") or DEFAULT_TICKET_PATTERN
    try:
        for m in re.finditer(pattern, text):
            key = m.group(0)
            if cfg.get("ticket_pattern") or key.split("-")[0] not in NOT_TICKETS:
                return key
    except re.error:
        pass
    return None


# -------------------------------------------------------------------- usage

USAGE_FIELDS = ("in", "out", "cr", "cw5", "cw1", "web")


def _usage_of(message):
    u = message.get("usage") or {}
    cc = u.get("cache_creation") or {}
    cw5 = cc.get("ephemeral_5m_input_tokens")
    cw1 = cc.get("ephemeral_1h_input_tokens")
    if cw5 is None and cw1 is None:
        # Older transcripts only carry the total; price it as the 5-minute tier.
        cw5, cw1 = u.get("cache_creation_input_tokens") or 0, 0
    stu = u.get("server_tool_use") or {}
    return {
        "in": u.get("input_tokens") or 0,
        "out": u.get("output_tokens") or 0,
        "cr": u.get("cache_read_input_tokens") or 0,
        "cw5": cw5 or 0,
        "cw1": cw1 or 0,
        "web": stu.get("web_search_requests") or 0,
    }, ("fast" if u.get("speed") == "fast" else "std")


def _scan_transcript(path, agent, seen):
    """Collect per-message usage from one transcript file into `seen`."""
    try:
        fh = open(path, encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            if '"usage"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") != "assistant":
                continue
            msg = d.get("message") or {}
            model = msg.get("model") or ""
            if not model or model.startswith("<"):  # "<synthetic>" carries no usage
                continue
            mid = msg.get("id") or d.get("uuid")
            if not mid:
                continue
            usage, speed = _usage_of(msg)
            skill = d.get("attributionSkill") or "-"
            prev = seen.get(mid)
            if prev:
                # One API message is written as several lines (one per content
                # block) and the counters grow while it streams: keep the max.
                for f in USAGE_FIELDS:
                    if usage[f] > prev["u"][f]:
                        prev["u"][f] = usage[f]
                if skill != "-":
                    prev["skill"] = skill
            else:
                seen[mid] = {"model": model, "speed": speed, "skill": skill,
                             "agent": agent, "u": usage}


def cumulative_usage(transcript_path, sid):
    """Totals so far for the session, keyed by 'model|speed|skill|agent'."""
    if not transcript_path:
        return {}
    seen = {}
    _scan_transcript(transcript_path, "main", seen)
    sub_dir = os.path.join(os.path.dirname(transcript_path), sid, "subagents")
    try:
        names = sorted(os.listdir(sub_dir))
    except OSError:
        names = []
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        agent = "subagent"
        try:
            with open(os.path.join(sub_dir, name[:-6] + ".meta.json"), encoding="utf-8") as fh:
                agent = json.load(fh).get("agentType") or agent
        except (OSError, ValueError):
            pass
        _scan_transcript(os.path.join(sub_dir, name), agent, seen)
    totals = {}
    for rec in seen.values():
        key = "|".join((rec["model"], rec["speed"], rec["skill"], rec["agent"]))
        t = totals.setdefault(key, dict.fromkeys(USAGE_FIELDS, 0))
        for f in USAGE_FIELDS:
            t[f] += rec["u"][f]
    return totals


def usage_delta(state, payload, sid):
    """Rows of usage added since the last snapshot; advances the snapshot."""
    cum = cumulative_usage(payload.get("transcript_path"), sid)
    if "usage" not in state:
        # No baseline yet: capture was switched on in the middle of this
        # session. What the transcript already holds was spent before that,
        # so it becomes the baseline instead of being billed to this turn.
        state["usage"] = cum
        return []
    prev = state["usage"] or {}
    rows = []
    for key, tot in cum.items():
        before = prev.get(key) or {}
        d = {f: tot[f] - (before.get(f) or 0) for f in USAGE_FIELDS}
        if any(v > 0 for v in d.values()):
            model, speed, skill, agent = key.split("|", 3)
            row = {"model": model, "skill": skill, "agent": agent}
            if speed != "std":
                row["speed"] = speed
            row.update({f: v for f, v in d.items() if v > 0})
            row.update(state.get("platform") or {})
            rows.append(row)
    if cum:
        state["usage"] = cum
    return rows


# ---------------------------------------------------------------- tool info

def line_delta(tool_input):
    """Lines the AI added and removed, from the edit payload alone."""
    def n(text):
        return len(text.splitlines()) if isinstance(text, str) and text else 0

    added = removed = 0
    if isinstance(tool_input.get("content"), str):
        added += n(tool_input["content"])
    edits = tool_input.get("edits")
    if not isinstance(edits, list):
        edits = [tool_input]
    for e in edits:
        if isinstance(e, dict) and ("new_string" in e or "old_string" in e):
            added += n(e.get("new_string"))
            removed += n(e.get("old_string"))
    if isinstance(tool_input.get("new_source"), str):
        added += n(tool_input["new_source"])
    return added, removed


def bash_summary(command):
    """Program name and, for git/gh, the subcommand. Never the full command."""
    info = {}
    if not isinstance(command, str):
        return info
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:  # unbalanced quotes: fall back to a plain split
        tokens = command.split()
    # One simple command per segment, split on shell operators.
    segments, current = [], []
    for tok in tokens:
        if tok and set(tok) <= set(";&|()<>"):
            if current:
                segments.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)
    git_ops = []
    for words in segments:
        # Skip leading VAR=value assignments and wrappers.
        while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0])
                         or words[0] in ("sudo", "env", "time", "nohup")):
            words = words[1:]
        if not words:
            continue
        prog = os.path.basename(words[0])
        if "cmd" not in info and prog != "cd":
            info["cmd"] = prog[:32]
        args = words[1:]
        if prog == "git":
            # The subcommand is the first word that is not a global option.
            while args and args[0].startswith("-"):
                args = args[2:] if args[0] in ("-C", "-c", "--git-dir", "--work-tree") else args[1:]
            if args and args[0] in ("commit", "push") and args[0] not in git_ops:
                git_ops.append(args[0])
        elif prog in ("gh", "glab") and args[:2] in (["pr", "create"], ["mr", "create"]):
            if "--help" not in args and "-h" not in args:
                info["pr"] = True
    if git_ops:
        info["git"] = "+".join(git_ops)
    return info


def rel_path(path, cwd):
    if not isinstance(path, str) or not path:
        return None
    for base in (os.environ.get("CLAUDE_PROJECT_DIR"), cwd):
        if base and path.startswith(base.rstrip("/\\") + os.sep):
            return path[len(base.rstrip("/\\")) + 1:]
    return path


# --------------------------------------------------------------------- main

def norm(name):
    return re.sub(r"[-_ ]", "", str(name or "")).lower()


def handle(payload):
    event = norm(payload.get("hook_event_name"))
    sid = payload.get("session_id")
    if not event or not sid:
        return
    cwd = payload.get("cwd") or os.getcwd()
    metrics_dir = find_metrics_dir(cwd)
    if not metrics_dir:
        return
    cfg = load_config(metrics_dir)
    now = time.time()
    out = []

    def emit(ev, **fields):
        rec = {"v": SCHEMA, "ts": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "t": round(now, 3), "ev": ev, "sid": sid}
        rec.update({k: v for k, v in fields.items() if v not in (None, "", [], {})})
        out.append(rec)

    with Session(metrics_dir, sid) as session:
        st = session.data
        if "user" not in st:
            st["user"] = resolve_user(cfg, cwd)
            st["platform"] = detect_platform()
            st["project"] = os.path.basename(
                (os.environ.get("CLAUDE_PROJECT_DIR") or cwd).rstrip("/\\"))
        tool = payload.get("tool_name")
        tool_n = norm(tool)
        ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
        tuid = payload.get("tool_use_id")
        pre = st.setdefault("pre", {})

        if event == "sessionstart":
            branch = git(["symbolic-ref", "--short", "-q", "HEAD"], cwd)
            if not st.get("ticket"):
                st["ticket"] = find_ticket(branch, cfg)
            if "usage" not in st:
                # A resumed session starts with history already in its
                # transcript: take it as the baseline, do not bill it twice.
                st["usage"] = cumulative_usage(payload.get("transcript_path"), sid)
            emit("session_start", source=payload.get("source"), model=payload.get("model"),
                 project=st.get("project"), branch=branch, **(st.get("platform") or {}))

        elif event == "userpromptsubmit":
            prompt = payload.get("prompt") if isinstance(payload.get("prompt"), str) else ""
            head = prompt.lstrip()
            first = head.split(None, 1)[0] if head else ""
            if HARNESS_PROMPT.match(head):
                kind = "system"  # task notifications and other harness messages
            elif SLASH_COMMAND.match(first):
                kind = "command"
            else:
                kind = "human"   # includes text that merely starts with a path or a tag
            fields = {"kind": kind, "chars": len(prompt)}
            if kind == "command":
                fields["command"] = first[1:80]
            if kind != "system":
                ticket = find_ticket(prompt, cfg)
                if ticket:
                    st["ticket"] = ticket
                if st.get("last_stop"):
                    fields["idle_s"] = round(now - st["last_stop"], 1)
            st["turn"] = {"start": now, "kind": kind, "tools": 0, "wait_ms": 0,
                          "pid": payload.get("prompt_id")}
            emit("prompt", **fields)

        elif event == "pretooluse":
            if tuid:
                pre[tuid] = now
                # Bounded: entries normally leave on PostToolUse.
                for k in sorted(pre, key=pre.get)[:-200]:
                    pre.pop(k, None)

        elif event == "permissionrequest":
            st.setdefault("perm", []).append(tuid or tool)
            emit("permission", tool=tool)

        elif event == "permissiondenied":
            emit("permission_denied", tool=tool)

        elif event in ("posttooluse", "posttoolusefailure"):
            failed = event == "posttoolusefailure"
            dur = payload.get("duration_ms")
            fields = {"tool": tool, "dur_ms": dur if isinstance(dur, (int, float)) else None}
            started = pre.pop(tuid, None) if tuid else None
            perm = st.get("perm") or []
            asked = (tuid in perm) or (tool in perm)
            if asked:
                st["perm"] = [p for p in perm if p not in (tuid, tool)]
                fields["perm"] = True
            if started:
                gap_ms = (now - started) * 1000.0
                if tool_n in QUESTION_TOOLS:
                    wait = gap_ms
                elif asked:
                    wait = gap_ms - (dur if isinstance(dur, (int, float)) else 0)
                else:
                    wait = 0
                if wait > 500:
                    fields["wait_ms"] = int(wait)
                    if st.get("turn"):
                        st["turn"]["wait_ms"] = st["turn"].get("wait_ms", 0) + int(wait)
            if failed:
                fields["failed"] = True
                if payload.get("is_interrupt"):
                    fields["interrupt"] = True
            if tool_n == "skill":
                fields["skill"] = ti.get("skill")
                ticket = find_ticket(str(ti.get("args") or ""), cfg)
                if ticket:
                    st["ticket"] = ticket
            elif tool_n in AGENT_TOOLS:
                fields["agent"] = ti.get("subagent_type") or "general-purpose"
            elif tool_n in WRITE_TOOLS:
                path = ti.get("file_path") or ti.get("notebook_path")
                if cfg.get("record_paths", True):
                    fields["file"] = rel_path(path, cwd)
                added, removed = line_delta(ti)
                fields["added"], fields["removed"] = added or None, removed or None
            elif tool_n == "bash":
                fields.update(bash_summary(ti.get("command")))
            elif tool_n.startswith("mcp"):
                parts = str(tool).split("__")
                if len(parts) >= 3:
                    fields["mcp"] = parts[1]
            if tool_n in QUESTION_TOOLS:
                fields["question"] = True
            if st.get("turn"):
                st["turn"]["tools"] = st["turn"].get("tools", 0) + 1
            emit("tool", **fields)

        elif event == "notification":
            emit("notification", kind=payload.get("notification_type"))

        elif event == "subagentstart":
            st.setdefault("agents", {})[str(payload.get("agent_id"))] = now

        elif event == "subagentstop":
            started = (st.get("agents") or {}).pop(str(payload.get("agent_id")), None)
            emit("subagent", agent=payload.get("agent_type"),
                 dur_s=round(now - started, 1) if started else None)

        elif event == "precompact":
            emit("compact", trigger=payload.get("trigger"))

        elif event in ("stop", "stopfailure"):
            turn = st.pop("turn", None)
            if turn:
                dur = now - turn["start"]
                wait = turn.get("wait_ms", 0) / 1000.0
                emit("turn", kind=turn.get("kind"), dur_s=round(dur, 1),
                     ai_s=round(max(0.0, dur - wait), 1), wait_s=round(wait, 1) or None,
                     tools=turn.get("tools"), failed=True if event == "stopfailure" else None)
            st["last_stop"] = now
            rows = usage_delta(st, payload, sid)
            if rows:
                emit("usage", rows=rows)

        elif event == "sessionend":
            rows = usage_delta(st, payload, sid)
            if rows:
                emit("usage", rows=rows)
            emit("session_end", reason=payload.get("reason"))

        else:
            return

        for rec in out:
            rec["user"] = st.get("user")
            if st.get("ticket"):
                rec["ticket"] = st["ticket"]
            pid = payload.get("prompt_id")
            if pid:
                rec["pid"] = pid

        if out:
            folder = os.path.join(metrics_dir, "events", st.get("user") or "unknown")
            os.makedirs(folder, exist_ok=True)
            with open(os.path.join(folder, safe_name(sid) + ".jsonl"), "a", encoding="utf-8") as fh:
                for rec in out:
                    fh.write(json.dumps(rec, separators=(",", ":")) + "\n")


def main():
    try:
        raw = sys.stdin.read()
        if raw.strip():
            payload = json.loads(raw)
            if isinstance(payload, dict):
                handle(payload)
    except Exception:  # a usage hook must never disturb the session
        if setting("DEBUG"):
            import traceback
            traceback.print_exc(file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main()
