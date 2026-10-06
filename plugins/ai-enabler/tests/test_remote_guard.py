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
    ("Bash", {"command": "git -c x=y push"}),
    ("Bash", {"command": "FOO=1 git push --force"}),
    ("Bash", {"command": "/usr/bin/git push"}),
    ("Bash", {"command": "command git push"}),
    # Shapes a simple parser misses.
    ("Bash", {"command": "git status\ngit push"}),
    ("Bash", {"command": "cd repo\ngit push origin HEAD"}),
    ("Bash", {"command": "if true; then git push; fi"}),
    ("Bash", {"command": "for r in origin; do git push $r; done"}),
    ("Bash", {"command": "timeout 60 git push"}),
    ("Bash", {"command": "nice -n 5 git push"}),
    ("Bash", {"command": "! git push"}),
    ("Bash", {"command": "{ git push; }"}),
    ("Bash", {"command": "echo `git push`"}),
    ("Bash", {"command": 'bash -c "git push"'}),
    ("Bash", {"command": "sh -c 'cd x && git push origin main'"}),
    ("Bash", {"command": "xargs git push"}),
    ("Bash", {"command": 'eval "git push"'}),
    ("Bash", {"command": "env -u GIT_DIR git push"}),
    ("Bash", {"command": "git subtree push --prefix=a origin b"}),
    ("Bash", {"command": "git lfs push origin main"}),
    ("Bash", {"command": "git svn dcommit"}),
    ("Bash", {"command": "git config alias.p push && git p"}),
    ("Bash", {"command": "hub push"}),
    ("Bash", {"command": "hub pull-request"}),
    ("Bash", {"command": "curl -X POST https://api.github.com/repos/o/r/pulls -d '{}'"}),
    ("Bash", {"command": "python3 -c \"import subprocess; subprocess.run(['git','push'])\""}),
    # gh / glab writes.
    ("Bash", {"command": "gh pr create --fill"}),
    ("Bash", {"command": "gh pr merge 12 --squash"}),
    ("Bash", {"command": "gh pr comment 12 -b hi"}),
    ("Bash", {"command": "gh pr ready 12"}),
    ("Bash", {"command": "gh pr review 12 --approve"}),
    ("Bash", {"command": "gh pr edit 12 -t x"}),
    ("Bash", {"command": "gh issue create -t x"}),
    ("Bash", {"command": "gh release create v1"}),
    ("Bash", {"command": "gh workflow run ci.yml"}),
    ("Bash", {"command": "gh repo sync"}),
    ("Bash", {"command": "gh alias set shipit 'pr create --fill'"}),
    ("Bash", {"command": "gh api -X POST repos/o/r/pulls -f title=x"}),
    ("Bash", {"command": "gh api -XDELETE repos/o/r/git/refs/heads/x"}),
    ("Bash", {"command": "gh api --method=POST repos/o/r/pulls/1/merge"}),
    ("Bash", {"command": "gh api repos/o/r/issues -f title=x"}),
    ("Bash", {"command": "gh api repos/o/r/issues/1/comments -fbody=x"}),
    ("Bash", {"command": "gh api repos/o/r/issues/1/comments --field=body=x"}),
    ("Bash", {"command": "gh api repos/o/r/pulls --input=pr.json"}),
    ("Bash", {"command": "gh api graphql -f query='mutation { addStar(input:{}) { clientMutationId } }'"}),
    ("Bash", {"command": "glab mr create"}),
    # Lifting local-only mode is not the agent's to do.
    ("Bash", {"command": "rm .enabler/local-only"}),
    ("Bash", {"command": "mv .enabler/local-only /tmp/x"}),
    ("Bash", {"command": "rm -rf .enabler"}),
    ("Bash", {"command": "mv .enabler .enabler.bak"}),
    ("Bash", {"command": "find . -name local-only -delete"}),
    ("Bash", {"command": "git clean -fdx"}),
    ("Bash", {"command": "git stash -u"}),
    ("Bash", {"command": "git rm -f .enabler/local-only"}),
    ("Bash", {"command": ": > .enabler/local-only"}),
    ("Bash", {"command": "python3 -c \"import os; os.remove('.enabler/local-only')\""}),
    ("Bash", {"command": "sed -i 's/true/false/' .enabler/config.json"}),
    ("Bash", {"command": "echo '{}' > .enabler/config.json"}),
    ("Bash", {"command": "rm .enabler/config.json"}),
    ("Edit", {"file_path": "/work/p/.enabler/config.json", "old_string": "true", "new_string": "false"}),
    ("Write", {"file_path": ".enabler/config.json", "content": "{}"}),
    # MCP: anything that is not clearly a read, on a remote system of record.
    ("mcp__atlassian__addCommentToJiraIssue", {}),
    ("mcp__atlassian__transitionJiraIssue", {}),
    ("mcp__atlassian__editJiraIssue", {}),
    ("mcp__atlassian__createConfluencePage", {}),
    ("mcp__jira-dc__jira_add_comment", {}),
    ("mcp__jira-dc__jira_update_issue", {}),
    ("mcp__jira-dc__jira_log_work", {}),
    ("mcp__plugin_x_jira__jira_create_issue", {}),
    ("mcp__github__create_pull_request", {}),
    ("mcp__github__push_files", {}),
    ("mcp__github__create_or_update_file", {}),
    ("mcp__github__merge_pull_request", {}),
    ("mcp__github__add_issue_comment", {}),
    ("mcp__github__create_pull_request_review", {}),
    ("mcp__gitlab__create_merge_request", {}),
    ("mcp__bitbucket__create_pull_request", {}),
]
ALLOWED = [
    ("Bash", {"command": "git status"}),
    ("Bash", {"command": "git commit -m 'do not push this'"}),
    ("Bash", {"command": "git commit -m 'docs: rm note about local-only mode'"}),
    ("Bash", {"command": "git log --grep push"}),
    ("Bash", {"command": "git fetch origin && git diff origin/main...HEAD"}),
    ("Bash", {"command": "git pull --rebase"}),
    ("Bash", {"command": "git remote update"}),
    ("Bash", {"command": "git checkout -b feature/X-1"}),
    ("Bash", {"command": "git stash"}),
    ("Bash", {"command": "git clean -nfd"}),
    ("Bash", {"command": "gh pr view 12"}),
    ("Bash", {"command": "gh pr diff 12"}),
    ("Bash", {"command": "gh pr list"}),
    ("Bash", {"command": "gh pr checkout 12"}),
    ("Bash", {"command": "gh -R o/r pr view 12"}),
    ("Bash", {"command": "gh status"}),
    ("Bash", {"command": "gh search prs foo"}),
    ("Bash", {"command": "gh auth status"}),
    ("Bash", {"command": "gh api repos/o/r/pulls/12"}),
    ("Bash", {"command": "gh api graphql -f query='query { viewer { login } }'"}),
    ("Bash", {"command": "npm test"}),
    ("Bash", {"command": "timeout 300 npm test"}),
    ("Bash", {"command": "cat .enabler/local-only"}),
    ("Bash", {"command": "echo more >> .enabler/local-only"}),
    ("Bash", {"command": "grep -rn local-only docs && rm /tmp/x"}),
    ("Bash", {"command": "rm -rf .enabler/runs/PROJ-1"}),
    ("Bash", {"command": "cp .enabler/config.json /tmp/config-copy.json"}),
    ("Bash", {"command": "curl https://api.github.com/repos/o/r/pulls"}),
    ("Bash", {"command": "curl -X POST http://localhost:8080/api/orders -d '{}'"}),
    ("Bash", {"command": "python3 -c \"print('hello')\""}),
    ("Write", {"file_path": "src/app.py", "content": "x"}),
    ("Edit", {"file_path": ".enabler/runs/PROJ-1/state.json", "old_string": "a", "new_string": "b"}),
    ("mcp__atlassian__getJiraIssue", {}),
    ("mcp__atlassian__getTransitionsForJiraIssue", {}),
    ("mcp__atlassian__getJiraIssueRemoteIssueLinks", {}),
    ("mcp__atlassian__searchJiraIssuesUsingJql", {}),
    ("mcp__jira-dc__jira_get_issue", {}),
    ("mcp__jira-dc__jira_search", {}),
    ("mcp__jira-dc__jira_get_transitions", {}),
    ("mcp__jira-dc__jira_get_worklog", {}),
    ("mcp__jira-dc__jira_download_attachments", {}),
    ("mcp__jira-dc__confluence_get_comments", {}),
    ("mcp__github__get_pull_request", {}),
    ("mcp__github__list_commits", {}),
    ("mcp__dynatrace__execute_dql", {}),          # not a system the guard covers
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

    # A nested .enabler/ without a marker does not hide the one at the root.
    os.makedirs(os.path.join(project, "apps", "web", ".enabler"))
    nested = os.path.join(project, "apps", "web")
    out = subprocess.run([sys.executable, HOOK], text=True, capture_output=True,
                         env=dict(os.environ, CLAUDE_PROJECT_DIR=nested),
                         input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}, "cwd": nested}))
    assert out.returncode == 2, "nested .enabler hid the root marker"

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
