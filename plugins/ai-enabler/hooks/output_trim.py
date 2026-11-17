#!/usr/bin/env python3
"""ai-enabler output trim.

A PostToolUse hook for Bash and PowerShell. Test and build runners print thousands of
lines, and the delivery subagents only need the failures and the summary. When one of
the pipeline's subagents (`agent_type` starting with `ai-enabler:delivery-`) runs a
known test or build runner and the output is longer than `max_chars`, this saves the
full output under `.enabler/tmp/output/` and replaces what the model reads with the
lines that matter: failures with a few lines of context and the stack frames after
them, summary lines, the first lines and the last lines. Each omitted run of lines
becomes one marker naming the saved log, so the agent can read more when it needs to.

The command has already run; only what the model reads changes. It never blocks: any
error, unknown input or nothing to do ends with exit 0 and no output.

Configuration, in .enabler/config.json:  "output_trim": {"enabled": true, "max_chars": 6000}
"""

import datetime
import json
import os
import re
import sys

AGENT_PREFIX = "ai-enabler:delivery-"
DEFAULT_MAX_CHARS = 6000
HEAD = 5
TAIL = 40
CONTEXT = 8
MAX_FRAMES = 20
FIELDS = ("stdout", "stderr", "output")

# The executable in command position: at the start, after a separator, or after a
# wrapper such as `timeout 300`, `uv run` or an environment assignment; optionally with a path.
_PRE = (r"(?:^|[;&|(`\n{]+|\$\()\s*"
        r"(?:(?:[A-Za-z_]\w*=\S*|time|exec|env|sudo|command|nice|timeout\s+\S+"
        r"|(?:uv|poetry|pipenv|hatch|pdm)\s+run)\s+)*"
        r"(?:[\w.~:-]*[/\\])*")
_EXE = r"(?:\.(?:exe|cmd|bat))?"
_POST = r"(?=$|[\s;&|)`])"
RUNNER = re.compile(_PRE + r"(?:" + "|".join([
    r"dotnet" + _EXE + r"\s+(?:test|build)",
    r"mvnw?" + _EXE,
    r"gradlew?" + _EXE,
    r"npm" + _EXE + r"\s+(?:test|run\s+test[\w:.-]*)",
    r"npx" + _EXE + r"\s+(?:jest|vitest)",
    r"jest" + _EXE,
    r"vitest" + _EXE,
    r"yarn" + _EXE + r"\s+(?:run\s+)?test[\w:.-]*",
    r"pnpm" + _EXE + r"\s+(?:run\s+)?test[\w:.-]*",
    r"pytest" + _EXE,
    r"(?:python[\d.]*|py)" + _EXE + r"(?:\s+-\d[\d.]*)?\s+-m\s+pytest",
    r"go" + _EXE + r"\s+test",
    r"cargo" + _EXE + r"\s+test",
]) + r")" + _POST, re.IGNORECASE)

# A failure: kept with the lines after it and the stack frames that follow.
FAILURE = re.compile(
    r"error|exception|traceback|panic|\bfail(?:s|ed|ure|ures|ing)?\b|\bassert|\bexpected\b|\bactual\b"
    r"|[\u2717\u2718\u2715\u25cf]", re.IGNORECASE)
# A compiler or analyzer warning is not a failure, even when it mentions "exception".
WARNING = re.compile(r"\bwarn(?:ing)?\b", re.IGNORECASE)
HARD_FAILURE = re.compile(r"\berror\b|\bfail(?:s|ed|ure|ures|ing)?\b", re.IGNORECASE)
# A summary: kept on its own.
SUMMARY = re.compile(
    r"\bpassed\b|\bskipped\b|coverage|total tests|tests run:|build (?:success|failure|succeeded|failed)"
    r"|\d+\s+(?:warning|error)\(s\)|\b\d+\s+warnings?\b|test result:", re.IGNORECASE)
# One passing or skipped test in a verbose listing: not a summary.
PER_TEST = re.compile(
    r"^\s*(?:[\u2713\u2714\u221a]|PASS\s|(?:Passed|Skipped)\s+\S|ok\s+\d)|::\S*\s+(?:PASSED|SKIPPED)\b")
FRAME = re.compile(
    r"^\s+at\s|^\s+File \"|^\s+in\s.+:line\s+\d+|^\s+\S+\.(?:py|cs|fs|vb|java|kt|scala|ts|tsx|js|jsx|mjs"
    r"|go|rs|rb|php):\d+|^\s+\.\.\.\s*\d+\s+more|^\s*at\s+\S+\(.*:\d+\)|^\s+\d+:\s+0x[0-9a-f]+",
    re.IGNORECASE)


def project_root(payload):
    return os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()


def settings(root):
    enabled, max_chars = True, DEFAULT_MAX_CHARS
    try:
        with open(os.path.join(root, ".enabler", "config.json"), encoding="utf-8") as fh:
            section = json.load(fh).get("output_trim")
    except (OSError, ValueError, AttributeError):
        section = None
    if isinstance(section, dict):
        if isinstance(section.get("enabled"), bool):
            enabled = section["enabled"]
        value = section.get("max_chars")
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            max_chars = value
    return enabled, max_chars


def texts(response):
    if isinstance(response, str):
        return [response]
    return [response[f] for f in FIELDS if isinstance(response.get(f), str)]


def keep_mask(lines):
    n = len(lines)
    keep = [False] * n
    for i in range(min(HEAD, n)):
        keep[i] = True
    for i in range(max(0, n - TAIL), n):
        keep[i] = True
    for i, line in enumerate(lines):
        failure = FAILURE.search(line)
        if failure and WARNING.search(line) and not HARD_FAILURE.search(line):
            failure = None
        if PER_TEST.search(line) and not failure:
            continue
        if failure:
            end = min(n, i + CONTEXT + 1)
            for j in range(i, end):
                keep[j] = True
            frames = 0
            while end < n and frames < MAX_FRAMES and FRAME.search(lines[end]):
                keep[end] = True
                end += 1
                frames += 1
        elif SUMMARY.search(line):
            keep[i] = True
    return keep


def trim(text, log_path):
    lines = text.splitlines()
    keep = keep_mask(lines)
    out, omitted = [], 0
    for line, kept in zip(lines, keep):
        if kept:
            if omitted:
                out.append("[\u2026 %d lines omitted by ai-enabler output_trim \u2014 full output: %s]"
                           % (omitted, log_path))
                omitted = 0
            out.append(line)
        else:
            omitted += 1
    if omitted:
        out.append("[\u2026 %d lines omitted by ai-enabler output_trim \u2014 full output: %s]"
                   % (omitted, log_path))
    result = "\n".join(out)
    if text.endswith(("\n", "\r")):
        result += "\n"
    return result if len(result) < len(text) else text


def save_full(root, payload, response):
    tmp = os.path.join(root, ".enabler", "tmp")
    folder = os.path.join(tmp, "output")
    os.makedirs(folder, exist_ok=True)
    ignore = os.path.join(tmp, ".gitignore")
    if not os.path.exists(ignore):
        with open(ignore, "w", encoding="utf-8") as fh:
            fh.write("*\n")
    name = re.sub(r"[^A-Za-z0-9_.-]", "_", str(payload.get("tool_use_id") or ""))[:120].strip(".")
    if not name:
        name = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-%d" % os.getpid()
    path = os.path.abspath(os.path.join(folder, name + ".log"))
    if isinstance(response, str):
        body = response
    else:
        parts = []
        for f in FIELDS:
            if isinstance(response.get(f), str) and response[f]:
                parts.append("----- %s -----\n%s" % (f, response[f]))
        body = "\n".join(parts)
    with open(path, "w", encoding="utf-8", errors="replace", newline="\n") as fh:
        fh.write(body)
    return path


def main():
    raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    try:
        payload = json.loads(raw or "{}")
    except ValueError:
        return 0
    if not isinstance(payload, dict):
        return 0
    if not str(payload.get("agent_type") or "").startswith(AGENT_PREFIX):
        return 0
    if payload.get("tool_name") not in ("Bash", "PowerShell"):
        return 0
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    command = ti.get("command")
    if not isinstance(command, str) or not RUNNER.search(command):
        return 0
    response = payload.get("tool_response")
    if isinstance(response, dict):
        if response.get("isImage") is True:
            return 0
    elif not isinstance(response, str):
        return 0
    root = project_root(payload)
    enabled, max_chars = settings(root)
    if not enabled or sum(len(t) for t in texts(response)) <= max_chars:
        return 0
    try:
        log_path = save_full(root, payload, response)
    except OSError:
        return 0
    if isinstance(response, str):
        updated = trim(response, log_path)
        changed = updated != response
    else:
        updated, changed = dict(response), False
        for f in FIELDS:
            if isinstance(response.get(f), str):
                updated[f] = trim(response[f], log_path)
                changed = changed or updated[f] != response[f]
    if not changed:
        try:
            os.remove(log_path)
        except OSError:
            pass
        return 0
    out = {"hookSpecificOutput": {"hookEventName": "PostToolUse", "updatedToolOutput": updated}}
    sys.stdout.buffer.write(json.dumps(out).encode("ascii"))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
