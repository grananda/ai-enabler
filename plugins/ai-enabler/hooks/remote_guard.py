#!/usr/bin/env python3
"""ai-enabler remote guard.

A PreToolUse hook. When the project is in local-only mode it blocks every tool
call that would send work out of the machine:

  - git push (and git send-pack / git request-pull style uploads)
  - gh / glab commands that write: pr create, pr merge, pr comment, issue
    create, release create, repo create, api with a write method, ...
  - MCP tools of Jira / Atlassian / Confluence that create, edit, comment,
    transition, assign, link or delete
  - any attempt to remove the local-only marker itself

A project is local-only when either
  - `.enabler/local-only` exists (written when the person says no to the
    remote; only a person lifts it, by deleting the file by hand), or
  - `.enabler/config.json` has  "git": { "local_only": true }.

Outside local-only mode the hook does nothing and costs one stat() call.
It blocks by exiting 2 with the reason on stderr, which Claude Code shows to
the model instead of running the tool.
"""

import json
import os
import re
import shlex
import sys

MARKER = os.path.join(".enabler", "local-only")
CONFIG = os.path.join(".enabler", "config.json")

# gh / glab verbs that only read.
READ_VERBS = {"view", "list", "status", "diff", "checks", "search", "watch", "download",
              "clone", "browse", "ls", "show"}
READ_GROUPS = {"auth", "config", "help", "version", "completion", "alias", "extension"}
MCP_REMOTE = re.compile(r"(jira|atlassian|confluence)", re.I)
MCP_WRITE = re.compile(
    r"(create|add|update|edit|transition|delete|remove|comment|assign|link|move|post|put|"
    r"worklog|attach|upload|publish)", re.I)


def find_root(start):
    d = os.path.abspath(start)
    for _ in range(12):
        if os.path.isdir(os.path.join(d, ".enabler")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def local_only(cwd):
    """(True, why) when the project must not send anything out."""
    for start in (os.environ.get("CLAUDE_PROJECT_DIR"), cwd):
        root = find_root(start) if start else None
        if not root:
            continue
        marker = os.path.join(root, MARKER)
        if os.path.exists(marker):
            return True, "%s exists" % MARKER
        try:
            with open(os.path.join(root, CONFIG), encoding="utf-8") as fh:
                if (json.load(fh).get("git") or {}).get("local_only") is True:
                    return True, 'git.local_only is true in %s' % CONFIG
        except (OSError, ValueError, AttributeError):
            pass
    return False, ""


def segments(command):
    """The simple commands of a shell line, as word lists."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.split()
    out, current = [], []
    for tok in tokens:
        if tok and set(tok) <= set(";&|()<>"):
            if current:
                out.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        out.append(current)
    return out


def bash_violation(command):
    """Why this shell command would leave the machine, or None."""
    if not isinstance(command, str):
        return None
    # Removing or renaming the marker is the one local action that is refused:
    # only a person lifts local-only mode.
    if "local-only" in command and re.search(r"\b(rm|mv|unlink|truncate|shred)\b|>\s*\S*local-only", command):
        return "it would remove the local-only marker; only a person may lift local-only mode"
    for words in segments(command):
        while words and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0])
                         or words[0] in ("sudo", "env", "time", "nohup", "command", "exec")):
            words = words[1:]
        if not words:
            continue
        prog, args = os.path.basename(words[0]), words[1:]
        if prog == "git":
            while args and args[0].startswith("-"):
                args = args[2:] if args[0] in ("-C", "-c", "--git-dir", "--work-tree") else args[1:]
            if args and args[0] in ("push", "send-pack", "send-email"):
                return "`git %s` sends commits to a remote" % args[0]
        elif prog in ("gh", "glab"):
            plain = [a for a in args if not a.startswith("-")]
            if not plain or plain[0] in READ_GROUPS:
                continue
            if plain[0] == "api":
                method = None
                for i, a in enumerate(args):
                    if a in ("-X", "--method") and i + 1 < len(args):
                        method = args[i + 1].upper()
                    elif a.startswith("--method="):
                        method = a.split("=", 1)[1].upper()
                fields = any(a in ("-f", "-F", "--field", "--raw-field", "--input") for a in args)
                if (method and method != "GET") or (fields and method != "GET"):
                    return "`%s api` with a write request changes the remote" % prog
                continue
            verb = plain[1] if len(plain) > 1 else ""
            if verb not in READ_VERBS:
                return "`%s %s` writes to the remote" % (prog, " ".join(plain[:2]))
    return None


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    tool = str(payload.get("tool_name") or "")
    active, why = local_only(payload.get("cwd") or os.getcwd())
    if not active:
        return 0
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    reason = None
    if tool == "Bash":
        reason = bash_violation(tool_input.get("command"))
    elif tool.startswith("mcp__") and MCP_REMOTE.search(tool):
        action = tool.split("__")[-1]
        if MCP_WRITE.search(action):
            reason = "`%s` writes to Jira or Confluence" % tool
    elif tool in ("Write", "Edit", "MultiEdit"):
        path = str(tool_input.get("file_path") or "")
        if path.replace("\\", "/").endswith(".enabler/local-only"):
            return 0  # creating or annotating the marker is fine; removing it is not possible this way
    if not reason:
        return 0
    sys.stderr.write(
        "Blocked by ai-enabler: this project is local-only (%s) and %s. "
        "The person said nothing leaves this machine. Do not retry, do not look for another "
        "way to send it, and do not remove the marker: keep the work local and tell the person "
        "it stays local. Only they can lift this, by deleting .enabler/local-only by hand "
        "(or setting git.local_only to false).\n" % (why, reason))
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # A guard that crashes must not take the session down, and must not
        # silently allow either when the marker is there.
        try:
            if local_only(os.getcwd())[0]:
                sys.stderr.write("Blocked by ai-enabler: local-only guard failed to evaluate this call.\n")
                sys.exit(2)
        except Exception:
            pass
        sys.exit(0)
