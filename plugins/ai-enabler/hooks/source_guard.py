#!/usr/bin/env python3
"""ai-enabler source guard.

A PreToolUse hook. External sources of context — other repositories, sibling
folders, documents, registered in .enabler/sources/sources.json — are read and
never written. This refuses a tool call that would change one:

  - Write, Edit, MultiEdit, NotebookEdit on a file inside a source;
  - a shell command that writes into a source: a redirection into it, `rm`, `touch`,
    `tee`, `sed -i`, `dd of=`, `find -delete`, a copy, move, link or sync *into* it, a
    move *out of* it, an inline script that writes there, or a git command that changes
    its working tree, index, branches, tags, remotes or configuration — whether the
    source is named directly, through `cd`/`pushd`, `git -C`, `--work-tree`, a shell
    variable set in the same command, or `bash -c`.

Reading a source, and copying, linking or syncing *from* it into the project, are
allowed. This is a best-effort check of what the command line shows, like the remote
guard: it stops mistakes, not someone determined to get around it. Without registered
sources it does nothing.
"""

import json
import os
import re
import shlex
import sys

GIT_READ = {"status", "log", "show", "diff", "rev-parse", "ls-files", "ls-tree", "blame", "grep", "describe",
            "cat-file", "shortlog", "for-each-ref", "name-rev", "ls-remote", "help", "version", "rev-list",
            "merge-base", "whatchanged", "show-ref", "check-ignore", "count-objects", "var"}
WRITERS = {"rm", "rmdir", "touch", "truncate", "tee", "chmod", "chown", "chgrp", "shred", "unlink", "mkdir",
           "patch", "setfacl", "chattr"}
TO_DEST = {"cp", "install", "rsync", "ln", "scp"}   # only the destination is written
WRAPPERS = {"sudo", "env", "command", "nohup", "time", "timeout", "nice", "ionice", "stdbuf", "exec", "setsid",
            "builtin"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish"}
INTERPRETERS = re.compile(r"^(python[\d.]*|node|perl|ruby|php|deno|bun)$")
WRITE_CODE = re.compile(r"(open\([^)]*['\"][wax+]|write|remove|unlink|rmtree|rename|replace\(|mkdir|makedirs|"
                        r"truncate|chmod|copy|move|writeFile|appendFile|rmSync|rmdir|symlink)", re.I)


def project_root(start):
    d = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(d, ".enabler", "sources", "sources.json")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def protected(root):
    try:
        with open(os.path.join(root, ".enabler", "sources", "sources.json"), encoding="utf-8") as fh:
            reg = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for s in reg.get("sources") or []:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        if s.get("kind") == "repo":
            path = os.path.join(root, ".enabler", "sources", s["name"], "checkout")
        else:
            loc = str(s.get("location") or "")
            if not loc:
                continue
            path = loc if os.path.isabs(loc) else os.path.join(root, loc)
        out.append((s["name"], os.path.realpath(path)))
    return out


class Judge:
    def __init__(self, sources, cwd):
        self.sources = sources
        self.cwd = cwd
        self.vars = {}

    def inside(self, path, here=None):
        if not path or path.startswith("-"):
            return None
        path = os.path.expanduser(self.expand(path.strip("'\"")))
        full = os.path.realpath(path if os.path.isabs(path) else os.path.join(here or self.cwd, path))
        for name, src in self.sources:
            if full == src or full.startswith(src.rstrip(os.sep) + os.sep):
                return name
        return None

    def expand(self, word):
        return re.sub(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?", lambda m: self.vars.get(m.group(1), m.group(0)), word)

    def mentions(self, text, here):
        """A source named anywhere in a piece of text (inline code, a sub-shell)."""
        for word in re.findall(r"[^\s'\"(),;]+", text):
            n = self.inside(word, here) if ("/" in word or word.startswith((".", "~"))) else None
            if n:
                return n
        return None

    def git(self, args, here):
        target, i = here, 0
        while i < len(args) and args[i].startswith("-"):
            a = args[i]
            if a in ("-C", "--work-tree", "--git-dir") and i + 1 < len(args):
                if a != "--git-dir":
                    target = self.expand(args[i + 1])
                    target = target if os.path.isabs(target) else os.path.join(here, target)
                elif self.inside(args[i + 1], here):
                    target = os.path.dirname(os.path.join(here, self.expand(args[i + 1])).rstrip("/"))
                i += 2
            elif a.startswith(("--work-tree=", "--git-dir=")):
                val = self.expand(a.split("=", 1)[1])
                val = val if os.path.isabs(val) else os.path.join(here, val)
                target = val if a.startswith("--work-tree=") else os.path.dirname(val.rstrip("/"))
                i += 1
            elif a == "-c" and i + 1 < len(args):
                i += 2
            else:
                i += 1
        n = self.inside(target, here)
        if not n or i >= len(args):
            return None
        sub, rest = args[i], args[i + 1:]
        if sub in GIT_READ:
            return None
        if sub == "branch" and all(r in ("-a", "-r", "-v", "-vv", "--list", "-l", "--show-current", "--all",
                                         "--remotes", "--contains", "--merged", "--no-merged") or r.startswith("--format")
                                   for r in rest):
            return None
        if sub == "tag" and (not rest or rest[0] in ("-l", "--list", "-n")):
            return None
        if sub == "remote" and (not rest or rest[0] in ("-v", "show", "get-url")):
            return None
        if sub == "config" and any(r in ("--get", "--get-all", "--get-regexp", "--list", "-l") for r in rest):
            return None
        if sub == "stash" and rest and rest[0] in ("list", "show"):
            return None
        return "`git %s` would change the source %r" % (sub, n)

    def segment(self, words, here, depth):
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            k, v = words[0].split("=", 1)
            if len(words) == 1:
                self.vars[k] = self.expand(v)   # D=../contracts on its own: remember it
            words = words[1:]
        while words and os.path.basename(words[0]) in WRAPPERS:
            words = words[1:]
            while words and (words[0].startswith("-") or words[0].isdigit() or "=" in words[0]):
                words = words[1:]
        if not words:
            return None
        prog = os.path.basename(words[0])
        args = [self.expand(a) for a in words[1:]]
        if prog == "xargs":
            # The arguments come from the pipe; judge the command with the whole line's mentions.
            inner = [a for a in args if not a.startswith("-")]
            if inner and (os.path.basename(inner[0]) in WRITERS | {"mv"} or inner[0] in ("sed", "perl")) \
                    and self.line_mentions:
                return "`xargs %s` on files of the source %r" % (inner[0], self.line_mentions)
            return self.segment(inner, here, depth) if inner else None
        if prog in SHELLS or prog == "eval":
            code = " ".join(args[args.index("-c") + 1:]) if "-c" in args else (" ".join(args) if prog == "eval" else "")
            return self.line(code, here, depth + 1) if code and depth < 3 else None
        if INTERPRETERS.match(prog):
            flag = "-c" if prog.startswith("python") else "-e"
            if flag in args or "-e" in args:
                code = " ".join(args)
                n = self.mentions(code, here)
                if n and WRITE_CODE.search(code):
                    return "an inline %s script would write into the source %r" % (prog, n)
            return None
        if prog == "git":
            return self.git(args, here)
        if prog in WRITERS:
            for a in args:
                n = self.inside(a, here)
                if n:
                    return "`%s` would change the source %r" % (prog, n)
        if prog == "dd":
            for a in args:
                if a.startswith("of="):
                    n = self.inside(a[3:], here)
                    if n:
                        return "`dd` would write into the source %r" % n
        if prog == "find":
            starts = [a for a in args if not a.startswith(("-", "(", "!", ")"))]
            starts = starts[:1] if starts else ["."]
            n = self.inside(starts[0], here)
            if n and any(a in ("-delete", "-exec", "-execdir", "-ok", "-fprint", "-fprintf", "-fls") for a in args):
                execs = " ".join(args)
                if "-delete" in args or re.search(r"-(exec|execdir|ok)\s+(rm|mv|sed|truncate|chmod|tee|touch|cp)\b", execs):
                    return "`find` would change files of the source %r" % n
        if prog in ("sed", "perl") and any(a == "-i" or a.startswith(("-i", "--in-place")) for a in args):
            for a in args:
                n = self.inside(a, here)
                if n:
                    return "an in-place edit would change the source %r" % n
        if prog in TO_DEST or prog == "mv":
            dest = None
            for k, a in enumerate(args):
                if a in ("-t", "--target-directory") and k + 1 < len(args):
                    dest = args[k + 1]
                elif a.startswith("--target-directory="):
                    dest = a.split("=", 1)[1]
            plain = [a for a in args if not a.startswith("-")]
            if dest is None and plain:
                dest = plain[-1]
            n = self.inside(dest, here) if dest else None
            if n:
                return "`%s` would write into the source %r" % (prog, n)
            if prog == "mv" or (prog == "rsync" and "--remove-source-files" in args):
                for a in plain:
                    if a != dest:
                        n = self.inside(a, here)
                        if n:
                            return "`%s` would remove files from the source %r" % (prog, n)
        return None

    def line(self, command, here, depth=0):
        command = strip_heredocs(command)
        self.line_mentions = self.line_mentions if depth else self.mentions(command, here)
        toks = tokens_of(command)
        seg, i = [], 0
        while i <= len(toks):
            tok = toks[i] if i < len(toks) else ";"
            if tok in (">", ">>", ">|", "&>", "&>>", "1>", "2>") and i + 1 < len(toks):
                n = self.inside(toks[i + 1], here)
                if n:
                    return "a redirection would write into the source %r" % n
                i += 2
                continue
            if tok and set(tok) <= set(";&|()<>"):
                if seg:
                    if seg[0] in ("cd", "pushd") and len(seg) > 1:
                        d = self.expand(seg[1])
                        here = d if os.path.isabs(d) else os.path.normpath(os.path.join(here, d))
                    elif seg[0] == "popd":
                        pass
                    else:
                        why = self.segment(seg, here, depth)
                        if why:
                            return why
                seg = []
            else:
                seg.append(tok)
            i += 1
        return None


def strip_heredocs(command):
    """Drop the bodies of here-documents: their lines are text, not commands."""
    lines, out, end = command.split("\n"), [], None
    for line in lines:
        if end is not None:
            if line.strip() == end:
                end = None
            continue
        out.append(line)
        m = re.search(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line)
        if m:
            end = m.group(1)
    return "\n".join(out)


def tokens_of(command):
    command = command.replace("\n", " ; ").replace("`", " ; ").replace("$(", " ; ")
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return command.split()


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    cwd = payload.get("cwd") or os.getcwd()
    root = project_root(os.environ.get("CLAUDE_PROJECT_DIR") or cwd) or project_root(cwd)
    if not root:
        return 0
    sources = protected(root)
    if not sources:
        return 0
    tool = str(payload.get("tool_name") or "")
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    judge = Judge(sources, cwd)
    judge.line_mentions = None
    reason = None
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        n = judge.inside(str(ti.get("file_path") or ti.get("notebook_path") or ""))
        if n:
            reason = "it edits a file of the source %r" % n
    elif tool == "Bash":
        reason = judge.line(str(ti.get("command") or ""), cwd)
    if not reason:
        return 0
    sys.stderr.write(
        "Blocked by ai-enabler: %s. External sources are read-only: the pipeline consults them and never "
        "changes them. Make the change in the project instead, or, if the ticket needs a change in that "
        "source, stop and report it as out of scope.\n" % reason)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
