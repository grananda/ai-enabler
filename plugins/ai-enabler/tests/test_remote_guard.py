#!/usr/bin/env python3
"""Checks the remote guard: what it blocks in local-only mode, and that it
stays out of the way otherwise.

    python3 tests/test_remote_guard.py
"""

import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "remote_guard.py")

BLOCKED = [
    ("Bash", {"command": "git push"}),
    ("Bash", {"command": "git add -A && git commit -m x && git push -u origin feature/X-1"}),
    ("Bash", {"command": "git -C sub push origin main"}),
    ("Bash", {"command": "FOO=1 git push --force"}),
    ("Bash", {"command": "gh pr create --fill"}),
    ("Bash", {"command": "gh pr merge 12 --squash"}),
    ("Bash", {"command": "gh pr comment 12 -b hi"}),
    ("Bash", {"command": "gh issue create -t x"}),
    ("Bash", {"command": "gh api -X POST repos/o/r/pulls -f title=x"}),
    ("Bash", {"command": "gh api repos/o/r/issues -f title=x"}),
    ("Bash", {"command": "glab mr create"}),
    ("Bash", {"command": "rm .enabler/local-only"}),
    ("Bash", {"command": "mv .enabler/local-only /tmp/x"}),
    ("mcp__atlassian__addCommentToJiraIssue", {}),
    ("mcp__atlassian__transitionJiraIssue", {}),
    ("mcp__jira-dc__jira_add_comment", {}),
    ("mcp__jira-dc__jira_update_issue", {}),
    ("mcp__atlassian__createConfluencePage", {}),
]
ALLOWED = [
    ("Bash", {"command": "git status"}),
    ("Bash", {"command": "git commit -m 'do not push this'"}),
    ("Bash", {"command": "git log --grep push"}),
    ("Bash", {"command": "git fetch origin && git diff origin/main...HEAD"}),
    ("Bash", {"command": "git checkout -b feature/X-1"}),
    ("Bash", {"command": "gh pr view 12"}),
    ("Bash", {"command": "gh pr diff 12"}),
    ("Bash", {"command": "gh pr list"}),
    ("Bash", {"command": "gh auth status"}),
    ("Bash", {"command": "gh api repos/o/r/pulls/12"}),
    ("Bash", {"command": "npm test"}),
    ("Bash", {"command": "cat .enabler/local-only"}),
    ("mcp__atlassian__getJiraIssue", {}),
    ("mcp__jira-dc__jira_get_issue", {}),
    ("mcp__jira-dc__jira_search", {}),
    ("mcp__github__create_pull_request_review", {}),  # not a Jira server: left to the shell rules
]


def run(project, tool, tool_input):
    payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
               "cwd": project}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project)
    return subprocess.run([sys.executable, HOOK], input=json.dumps(payload), text=True,
                          capture_output=True, env=env)


def main():
    tmp = tempfile.mkdtemp(prefix="ai-enabler-guard-")
    project = os.path.join(tmp, "p")
    os.makedirs(os.path.join(project, ".enabler"))

    # Not local-only: everything passes.
    for tool, ti in BLOCKED + ALLOWED:
        if "local-only" in str(ti):
            continue
        out = run(project, tool, ti)
        assert out.returncode == 0, ("should pass when not local-only", tool, ti, out.stderr)

    def check():
        for tool, ti in BLOCKED:
            out = run(project, tool, ti)
            assert out.returncode == 2 and "local-only" in out.stderr, ("should block", tool, ti, out.stderr)
            assert out.stdout == "", out.stdout
        for tool, ti in ALLOWED:
            out = run(project, tool, ti)
            assert out.returncode == 0, ("should pass", tool, ti, out.stderr)

    # Local-only by marker.
    marker = os.path.join(project, ".enabler", "local-only")
    open(marker, "w").write("PROJ-1: the person said no to the remote\n")
    check()
    # It also applies from a subdirectory of the project.
    sub = os.path.join(project, "src", "deep")
    os.makedirs(sub)
    out = subprocess.run([sys.executable, HOOK], text=True, capture_output=True,
                         env={k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"},
                         input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}, "cwd": sub}))
    assert out.returncode == 2, out.stderr

    # Local-only by configuration.
    os.remove(marker)
    with open(os.path.join(project, ".enabler", "config.json"), "w") as fh:
        json.dump({"git": {"local_only": True}}, fh)
    check()
    with open(os.path.join(project, ".enabler", "config.json"), "w") as fh:
        json.dump({"git": {"local_only": False}}, fh)
    assert run(project, "Bash", {"command": "git push"}).returncode == 0

    print("ok — %d blocked, %d allowed" % (len(BLOCKED), len(ALLOWED)))


if __name__ == "__main__":
    main()
