#!/usr/bin/env python3
"""ai-enabler remote guard.

A PreToolUse hook. When the project is in local-only mode it blocks every tool
call that would send work out of the machine:

  - git push (and git send-pack / git request-pull style uploads)
  - gh / glab commands that write: pr create, pr merge, pr comment, issue
    create, release create, repo create, api with a write method, ...
  - curl / wget write requests to GitHub, GitLab, Bitbucket or Atlassian hosts
  - MCP tools of GitHub, GitLab, Bitbucket, Jira or Confluence, unless the
    action clearly only reads
  - any attempt to remove the marker or edit the configuration that holds the flag

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
              "clone", "browse", "ls", "show", "checkout"}
READ_GROUPS = {"auth", "config", "help", "version", "completion", "extension", "status",
               "browse", "search"}
GH_VALUE_FLAGS = {"-R", "--repo", "--hostname"}
# MCP servers that front a remote system of record. In local-only mode their
# tools are refused unless the action clearly only reads.
MCP_REMOTE = re.compile(r"(jira|atlassian|confluence|github|gitlab|bitbucket|azure.?devops|\bado\b|\bgit\b)", re.I)
MCP_READ = re.compile(r"^(get|list|search|read|fetch|download|lookup|find|view|describe|query|count|"
                      r"export|whoami|me$|check|show|compare|diff)", re.I)
MCP_PREFIX = re.compile(r"^(jira|confluence|github|gitlab|bitbucket|atlassian)[_-]", re.I)
REMOTE_HOSTS = re.compile(r"(github|gitlab|bitbucket|atlassian|jira|confluence|dev\.azure)", re.I)
KEYWORDS = {"then", "do", "else", "elif", "if", "while", "until", "!", "{", "}", "fi", "done"}
WRAPPERS = {"sudo", "env", "time", "nohup", "command", "exec", "nice", "ionice", "timeout",
            "stdbuf", "xargs", "setsid", "chronic", "caffeinate", "watch"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish", "eval", "su", "ssh"}
INTERPRETERS = re.compile(r"^(python[\d.]*|node|perl|ruby|php|deno|bun)$")
DESTRUCTIVE = {"rm", "mv", "unlink", "truncate", "shred", "rmdir", "cp", "tee", "dd", "install", "ln",
               "sed", "perl", "chmod"}
PROTECTED = re.compile(r"(^|/)\.enabler(/(local-only|config\.json|\*|\.\*)?)?/?$")


def local_only(cwd):
    """(True, why) when the project must not send anything out.

    Every directory from the working directory up to the filesystem root is
    checked, so a nested `.enabler/` (a monorepo package, a tool's own folder)
    cannot hide a marker placed at the repository root.
    """
    seen = set()
    for start in (os.environ.get("CLAUDE_PROJECT_DIR"), cwd, os.getcwd()):
        if not start:
            continue
        d = os.path.abspath(start)
        while d not in seen:
            seen.add(d)
            if os.path.exists(os.path.join(d, MARKER)):
                return True, "%s exists" % MARKER
            try:
                with open(os.path.join(d, CONFIG), encoding="utf-8") as fh:
                    if (json.load(fh).get("git") or {}).get("local_only") is True:
                        return True, "git.local_only is true in %s" % CONFIG
            except (OSError, ValueError, AttributeError):
                pass
            parent = os.path.dirname(d)
            if parent == d:
                break
            d = parent
    return False, ""


def tokens_of(command):
    # Newlines and backticks separate commands just as ';' does.
    command = command.replace("\n", " ; ").replace("`", " ; ")
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return command.split()


def is_operator(tok):
    return bool(tok) and set(tok) <= set(";&|()<>")


def segments(tokens):
    """The simple commands of a shell line, as word lists."""
    out, current = [], []
    for tok in tokens:
        if is_operator(tok):
            if current:
                out.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        out.append(current)
    return out


def protected_path(arg):
    return bool(PROTECTED.search(arg.strip("'\"")))


def git_violation(args):
    while args and args[0].startswith("-"):
        args = args[2:] if args[0] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace") else args[1:]
    if not args:
        return None
    sub, rest = args[0], args[1:]
    if sub in ("push", "send-pack", "send-email"):
        return "`git %s` sends commits to a remote" % sub
    if sub in ("subtree", "lfs", "svn", "p4", "annex") and any(a in ("push", "dcommit", "submit", "sync", "copy")
                                                             for a in rest[:4]):
        return "`git %s` here sends commits to a remote" % sub
    if sub == "config" and any("alias." in a for a in rest) and any("push" in a for a in rest):
        return "it defines a git alias that pushes"
    if sub == "clean" and any(a.startswith("-") and "f" in a and not a.startswith("--") for a in rest) \
            and not any(a in ("-n", "--dry-run") or (a.startswith("-") and not a.startswith("--") and "n" in a)
                        for a in rest):
        return "`git clean` would delete untracked files, the local-only marker among them"
    if sub == "stash" and any(a in ("-u", "-a", "--include-untracked", "--all") for a in rest):
        return "`git stash` with untracked files would put the local-only marker away"
    if sub == "rm" and any(protected_path(a) or "local-only" in a for a in rest):
        return "it would remove the local-only marker"
    return None


def gh_violation(prog, args):
    cleaned, skip = [], False
    for a in args:
        if skip:
            skip = False
            continue
        if a in GH_VALUE_FLAGS:
            skip = True
            continue
        cleaned.append(a)
    plain = [a for a in cleaned if not a.startswith("-")]
    if not plain or (plain[0] in READ_GROUPS and plain[0] != "alias"):
        return None
    if plain[0] == "api":
        method, fields = None, False
        for i, a in enumerate(cleaned):
            if a in ("-X", "--method") and i + 1 < len(cleaned):
                method = cleaned[i + 1].upper()
            elif a.startswith("--method="):
                method = a.split("=", 1)[1].upper()
            elif a.startswith("-X") and len(a) > 2:
                method = a[2:].upper()
            if re.match(r"^(-f|-F)", a) or re.match(r"^--(field|raw-field|input)(=|$)", a):
                fields = True
        if "graphql" in plain[1:2]:
            return ("`%s api graphql` with a mutation changes the remote" % prog
                    if any("mutation" in a for a in cleaned) else None)
        if (method and method != "GET") or (fields and method != "GET"):
            return "`%s api` with a write request changes the remote" % prog
        return None
    verb = plain[1] if len(plain) > 1 else ""
    if verb not in READ_VERBS:
        return "`%s %s` writes to the remote" % (prog, " ".join(plain[:2]))
    return None


def curl_violation(args):
    joined = " ".join(args)
    if not REMOTE_HOSTS.search(joined):
        return None
    for i, a in enumerate(args):
        if re.match(r"^(-X|--request)", a):
            method = a.split("=", 1)[1] if "=" in a else (a[2:] if a.startswith("-X") and len(a) > 2
                                                          else (args[i + 1] if i + 1 < len(args) else ""))
            if method.upper() not in ("GET", "HEAD", ""):
                return "it sends a write request to a remote system"
        if re.match(r"^(-d|--data|-F|--form|-T|--upload-file|--json)", a):
            return "it sends data to a remote system"
    return None


def bash_violation(command, depth=0):
    """Why this shell command would leave the machine or lift local-only mode, or None."""
    if not isinstance(command, str) or depth > 3:
        return None
    tokens = tokens_of(command)
    # Redirections that overwrite the marker or the configuration.
    for i, tok in enumerate(tokens[:-1]):
        target = tokens[i + 1]
        if tok in (">", ">|", "&>") and protected_path(target):
            return "it would overwrite %s; only a person may lift local-only mode" % target
        if tok == ">>" and target.strip("'\"").endswith("config.json") and protected_path(target):
            return "it would change .enabler/config.json; only a person may lift local-only mode"
    for words in segments(tokens):
        # Shell keywords, VAR=value assignments and wrappers in front of the real program.
        while words:
            w = os.path.basename(words[0])
            if words[0] in KEYWORDS or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
                words = words[1:]
            elif w in WRAPPERS:
                words = words[1:]
                # The wrapper's own options and numeric arguments (timeout 60, nice -n 5, env -u X).
                while words and (words[0].startswith("-") or re.match(r"^[\d.]+[smhd]?$", words[0])
                                 or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0])):
                    flag = words[0]
                    words = words[1:]
                    if flag in ("-u", "-n", "-k", "-s", "-I", "-c", "-P", "-L") and words \
                            and not words[0].startswith("-"):
                        words = words[1:]
            else:
                break
        if not words:
            continue
        prog, args = os.path.basename(words[0]), words[1:]
        reason = None
        if prog == "git":
            reason = git_violation(args)
        elif prog in ("gh", "glab"):
            reason = gh_violation(prog, args)
        elif prog == "hub":
            plain = [a for a in args if not a.startswith("-")]
            if plain and plain[0] in ("push", "pull-request", "pr", "fork", "create", "release", "api",
                                      "merge", "issue", "sync", "delete"):
                reason = "`hub %s` writes to the remote" % plain[0]
        elif prog in ("curl", "wget", "http", "https", "xh"):
            reason = curl_violation(args)
        elif prog in SHELLS:
            # bash -c "…", eval "…", ssh host "…": look inside the quoted command.
            for a in args:
                if " " in a or prog == "eval":
                    reason = bash_violation(a, depth + 1)
                    if reason:
                        break
            if not reason and prog == "eval":
                reason = bash_violation(" ".join(args), depth + 1)
        elif INTERPRETERS.match(prog):
            code = " ".join(a for a in args if " " in a or "(" in a)
            if re.search(r"local-only|\.enabler[/\\'\"]", code) or \
                    re.search(r"\bgit\b[^\n]{0,40}\bpush\b|['\"]push['\"]", code):
                reason = "the inline script touches the local-only marker or pushes"
        if not reason and prog in DESTRUCTIVE:
            hit = [a for a in args if protected_path(a)]
            in_place = prog not in ("sed", "perl") or any(re.match(r"^-[a-zA-Z]*i", a) for a in args)
            read_only_copy = prog in ("cp", "ln", "install") and hit and not protected_path(args[-1])
            if hit and in_place and not read_only_copy and not (prog == "chmod"):
                reason = "it would remove or change %s; only a person may lift local-only mode" % hit[0]
        if not reason and prog == "find" and any(a in ("-delete", "-exec", "-execdir", "-ok") for a in args):
            if any(re.search(r"local-only|\.enabler|config\.json", a) for a in args) \
                    or not any(a in ("-name", "-iname", "-path", "-regex") for a in args):
                reason = "the find command could delete the local-only marker"
        if reason:
            return reason
    # Backstop: a push that the parsing above did not recognise as a command.
    stripped = re.sub(r"'[^']*'|\"[^\"]*\"", "''", command)
    if re.search(r"(^|[\s;&|({`!/])(git|hub)(\s+-{1,2}[\w-]+(=\S+)?(\s+[^\s-]\S*)?)*?\s+"
                 r"(push|send-pack|svn\s+dcommit|subtree\s+push|lfs\s+push)(\s|$)", stripped):
        return "it contains a git push"
    return None


def mcp_violation(tool):
    parts = tool.split("__")
    server, action = "__".join(parts[1:-1]), parts[-1]
    if not MCP_REMOTE.search(server) and not MCP_REMOTE.search(action):
        return None
    name = MCP_PREFIX.sub("", action)
    if MCP_READ.match(name):
        return None
    return "`%s` is not a read-only call to a remote system" % tool


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
    elif tool.startswith("mcp__"):
        reason = mcp_violation(tool)
    elif tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        # The marker may be written (that is how it is created); the configuration
        # may not be edited while local-only, or the flag could be switched off.
        path = str(tool_input.get("file_path") or "").replace("\\", "/")
        if path.endswith(".enabler/config.json"):
            reason = "it edits .enabler/config.json, which could switch local-only mode off"
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
