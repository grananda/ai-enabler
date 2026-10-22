#!/usr/bin/env python3
"""End-to-end check of the capture hook and the report, without Claude Code.

Feeds the hook the payloads Claude Code sends for a short session (a prompt, a
permission-gated edit, a commit, a subagent, a question), with a fake
transcript for the token counts, then runs the report and checks the figures.

    python3 tests/test_usage.py
"""

import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, "hooks", "usage_hook.py")
REPORT = os.path.join(ROOT, "scripts", "usage_report.py")
SID = "11111111-2222-3333-4444-555555555555"
PLATFORM_VARS = ("ENABLER_METRICS_DIR", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
                 "CLAUDE_CODE_USE_FOUNDRY", "ANTHROPIC_BASE_URL", "AWS_REGION", "AWS_DEFAULT_REGION",
                 "ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                 "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_SMALL_FAST_MODEL",
                 "CLAUDE_CODE_SUBAGENT_MODEL")


def assistant(mid, model, usage, skill=None):
    line = {"type": "assistant", "uuid": mid + "-u", "message": {"id": mid, "model": model, "usage": usage}}
    if skill:
        line["attributionSkill"] = skill
    return json.dumps(line) + "\n"


def main():
    tmp = tempfile.mkdtemp(prefix="ai-enabler-metrics-test-")
    project = os.path.join(tmp, "project")
    os.makedirs(os.path.join(project, ".enabler", "metrics"))
    transcript = os.path.join(tmp, "transcripts", SID + ".jsonl")
    sub_dir = os.path.join(tmp, "transcripts", SID, "subagents")
    os.makedirs(sub_dir)
    open(transcript, "w").close()

    env = dict(os.environ, CLAUDE_PROJECT_DIR=project, ENABLER_METRICS_USER="dev@example.com",
               ENABLER_METRICS_DEBUG="1")
    for var in PLATFORM_VARS:
        env.pop(var, None)

    def fire(event, **fields):
        payload = {"hook_event_name": event, "session_id": SID, "cwd": project,
                   "transcript_path": transcript, "prompt_id": "p1"}
        payload.update(fields)
        out = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), text=True,
                             capture_output=True, env=env)
        assert out.returncode == 0 and out.stdout == "", (event, out.stdout, out.stderr)
        assert out.stderr == "", (event, out.stderr)

    fire("SessionStart", source="startup")
    fire("UserPromptSubmit", prompt="/ai-enabler:delivery-run PROJ-7 please, and mind UTF-8")
    # An edit that needed approval: 1.2 s between request and result.
    fire("PreToolUse", tool_name="Edit", tool_use_id="t1", tool_input={})
    fire("PermissionRequest", tool_name="Edit", tool_use_id="t1")
    time.sleep(1.2)
    fire("PostToolUse", tool_name="Edit", tool_use_id="t1", duration_ms=10,
         tool_input={"file_path": os.path.join(project, "src", "a.py"),
                     "old_string": "x = 1", "new_string": "x = 2\ny = 3\nz = 4"})
    fire("PostToolUse", tool_name="Bash", tool_use_id="t2", duration_ms=50,
         tool_input={"command": "git commit -m 'secret message that must not be stored'"})
    fire("SubagentStart", agent_id="a1", agent_type="ai-enabler:delivery-code-reviewer")
    fire("PostToolUse", tool_name="Agent", tool_use_id="t3", duration_ms=5,
         tool_input={"subagent_type": "ai-enabler:delivery-code-reviewer", "prompt": "do not store me"})
    fire("SubagentStop", agent_id="a1", agent_type="ai-enabler:delivery-code-reviewer")
    fire("PostToolUseFailure", tool_name="Bash", tool_use_id="t4", is_interrupt=True,
         tool_input={"command": "mvn test"})

    # Opus message written twice while streaming (the larger count must win),
    # plus one subagent message on another model.
    with open(transcript, "a") as fh:
        fh.write(assistant("m1", "claude-opus-5-5", {"input_tokens": 1000, "output_tokens": 10}))
        fh.write(assistant("m1", "claude-opus-5-5", {
            "input_tokens": 1000, "output_tokens": 2000, "cache_read_input_tokens": 100000,
            "cache_creation": {"ephemeral_5m_input_tokens": 10000, "ephemeral_1h_input_tokens": 5000}},
            skill="ai-enabler:delivery-run"))
    with open(os.path.join(sub_dir, "agent-a1.jsonl"), "w") as fh:
        fh.write(assistant("m2", "claude-haiku-4-5-20251001", {"input_tokens": 500, "output_tokens": 100}))
    with open(os.path.join(sub_dir, "agent-a1.meta.json"), "w") as fh:
        json.dump({"agentType": "ai-enabler:delivery-code-reviewer"}, fh)

    fire("Stop")
    time.sleep(1.1)
    fire("UserPromptSubmit", prompt="looks good, ship it", prompt_id="p2")
    fire("Stop", prompt_id="p2")
    fire("SessionEnd", reason="other", prompt_id="p2")

    events_file = os.path.join(project, ".enabler", "metrics", "events", "dev@example.com", SID + ".jsonl")
    raw = open(events_file).read()
    events = [json.loads(line) for line in raw.splitlines()]
    kinds = [e["ev"] for e in events]

    # Privacy: no prompt text, no command line, no subagent prompt.
    for leaked in ("please", "secret message", "do not store me", "ship it"):
        assert leaked not in raw, "leaked: " + leaked
    assert all(e.get("ticket") == "PROJ-7" for e in events[1:]), "ticket key not attributed (or UTF-8 taken as a key)"
    assert kinds.count("usage") == 1, kinds  # second Stop and SessionEnd add nothing new
    edit = next(e for e in events if e["ev"] == "tool" and e["tool"] == "Edit")
    assert edit["file"] == os.path.join("src", "a.py") and edit["added"] == 3 and edit["removed"] == 1
    assert edit.get("perm") and edit["wait_ms"] >= 1000, edit
    turn = next(e for e in events if e["ev"] == "turn")
    assert turn["wait_s"] >= 1.0 and turn["ai_s"] < turn["dur_s"], turn

    out_dir = os.path.join(tmp, "report")
    run = subprocess.run([sys.executable, REPORT, "--metrics-dir", os.path.join(project, ".enabler", "metrics"),
                          "--out-dir", out_dir, "--quiet"], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    md = open(os.path.join(out_dir, "report.md")).read()
    assert "## Skills and agents in use" in md and "ai-enabler:delivery-run" in md
    filtered = subprocess.run([sys.executable, REPORT, "--metrics-dir", os.path.join(project, ".enabler", "metrics"),
                               "--out-dir", os.path.join(tmp, "report-filtered"), "--quiet", "--user", "nobody@x.org",
                               "--until", "2030-01-01"], capture_output=True, text=True)
    assert filtered.returncode != 0 and "No events" in filtered.stderr       # the filter excludes everything
    one = subprocess.run([sys.executable, REPORT, "--metrics-dir", os.path.join(project, ".enabler", "metrics"),
                          "--out-dir", os.path.join(tmp, "report-ticket"), "--quiet", "--ticket", "PROJ-7"],
                         capture_output=True, text=True)
    assert one.returncode == 0, one.stderr
    in_use = json.load(open(os.path.join(tmp, "report-ticket", "usage.json")))["assets"]
    assert in_use["covered_days"] >= 0 and any(a["name"] == "ai-enabler:delivery-run" and a["uses"] >= 1
                                               for a in in_use["assets"]), in_use["assets"][:3]
    for name in ("report.md", "report.html", "usage.json", "sessions.csv", "tickets.csv",
                 "users.csv", "daily.csv"):
        assert os.path.getsize(os.path.join(out_dir, name)) > 0, name
    metrics_out = json.load(open(os.path.join(out_dir, "usage.json")))
    o = metrics_out["overall"]

    # Opus 5.5: 1000*4 + 2000*20 + 100000*0.20 + 10000*4*1.25 + 5000*4*2 = 154000 -> $0.154
    # Haiku 4.5: 500*1 + 100*5 = 1000 -> $0.001
    assert abs(o["cost_usd"] - 0.155) < 1e-6, o["cost_usd"]
    assert abs(metrics_out["cost_by"]["skill"]["ai-enabler:delivery-run"] - 0.154) < 1e-6
    assert abs(metrics_out["cost_by"]["agent"]["ai-enabler:delivery-code-reviewer"] - 0.001) < 1e-6
    assert o["tokens_output"] == 2100 and o["tokens_cache_read"] == 100000
    assert o["commands"] == 1 and o["human_prompts"] == 1 and o["permission_prompts"] == 1
    assert o["interrupts"] == 1 and o["tool_failures"] == 1 and o["tool_calls"] == 4
    assert o["human_interactions"] == 4  # command + prompt + permission + interrupt
    assert o["commits"] == 1 and o["lines_added"] == 3 and o["files_touched"] == 1
    assert o["subagent_runs"] == 1 and o["tickets"] == 1
    assert o["human_wait_seconds"] >= 1 and o["human_think_seconds"] >= 1
    assert o["ai_seconds"] <= 3, o["ai_seconds"]       # turn and subagent overlap, counted once
    assert list(metrics_out["by_ticket"]) == ["PROJ-7"]

    # Skills and agents in use: stale after 90 days without use, never judged on too little data.
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import assets as A
    day = 86400.0
    now = 1_800_000_000.0
    inv = [{"kind": "skill", "name": "team:api-add-endpoint", "owner": "A. Owner <a@x.org>", "version": "1.2.0"},
           {"kind": "skill", "name": "team:old-thing", "owner": None, "version": None},
           {"kind": "skill", "name": "team:never-used", "owner": "A. Owner <a@x.org>", "version": "1.0.0"},
           {"kind": "agent", "name": "team:reviewer", "owner": "A. Owner <a@x.org>", "version": "1.0.0"}]
    evs = [{"ev": "session_start", "t": now - 200 * day},
           {"ev": "tool", "skill": "team:old-thing", "t": now - 120 * day},
           {"ev": "prompt", "kind": "command", "command": "team:api-add-endpoint", "t": now - 3 * day},
           {"ev": "tool", "skill": "team:api-add-endpoint", "t": now - 10 * day},
           {"ev": "subagent", "agent": "team:reviewer", "t": now - 1 * day}]
    res = A.classify(inv, evs, 90, now)
    status = {r["name"]: (r["status"], r["uses"]) for r in res["assets"]}
    assert status == {"team:api-add-endpoint": ("in use", 2), "team:old-thing": ("stale", 1),
                      "team:never-used": ("stale", 0), "team:reviewer": ("in use", 1)}, status
    young = A.classify(inv, [{"ev": "session_start", "t": now - 5 * day}], 90, now)
    assert all(r["status"] == "not seen yet" for r in young["assets"])       # five days of data prove nothing
    # A plugin skill recorded without its prefix still counts, when the short name is unambiguous.
    bare = A.classify(inv, [{"ev": "session_start", "t": now - 200 * day},
                            {"ev": "tool", "skill": "never-used", "t": now - 2 * day}], 90, now)
    assert {r["name"]: r["status"] for r in bare["assets"]}["team:never-used"] == "in use"
    # An asset created today cannot have gone unused for 200 days.
    fresh = os.path.join(tmp, "fresh-skill.md")
    open(fresh, "w").write("x")
    young_asset = A.classify([{"kind": "skill", "name": "team:brand-new", "owner": None, "version": None,
                               "path": fresh}], [{"ev": "session_start", "t": __import__("time").time() - 200 * day}])
    assert young_asset["assets"][0]["status"] == "not seen yet", young_asset["assets"][0]

    # Installed from the cache, plugins sit as <marketplace>/<plugin>/<version>/: every plugin is found, newest version.
    cache = os.path.join(tmp, "cache", "market")
    import shutil
    shutil.copytree(ROOT, os.path.join(cache, "ai-enabler-metrics", "1.0.0"), ignore=shutil.ignore_patterns("__pycache__"))
    for ver in ("0.9.0", "1.0.1"):
        d = os.path.join(cache, "ai-enabler", ver)
        os.makedirs(os.path.join(d, ".claude-plugin"))
        os.makedirs(os.path.join(d, "skills", "delivery-run"))
        json.dump({"name": "ai-enabler"}, open(os.path.join(d, ".claude-plugin", "plugin.json"), "w"))
        open(os.path.join(d, "skills", "delivery-run", "SKILL.md"), "w").write(
            '---\nname: delivery-run\nmetadata:\n  owner: "A <a@x.org>"\n  version: "%s"\n---\n' % ver)
    probe = subprocess.run([sys.executable, "-c",
                            "import sys, json; sys.path.insert(0, 'scripts'); import assets as A; "
                            "print(json.dumps([[a['name'], a['version']] for a in A.installed(project='/nonexistent')]))"],
                           cwd=os.path.join(cache, "ai-enabler-metrics", "1.0.0"), capture_output=True, text=True)
    found = dict(json.loads(probe.stdout))
    assert found.get("ai-enabler:delivery-run") == "1.0.1", (found, probe.stderr)
    assert "ai-enabler-metrics:metrics-usage-report" in found and len(found) == 10, found

    mine = A.installed()
    assert any(a["name"] == "ai-enabler-metrics:metrics-usage-report" and a["owner"] and a["version"] for a in mine)
    assert any(a["name"] == "ai-enabler:delivery-code-reviewer" and a["kind"] == "agent" for a in mine)

    # A project still on the pre-1.0.0 folder and variable names keeps being captured.
    legacy = os.path.join(tmp, "legacy")
    os.makedirs(os.path.join(legacy, ".enabler", "kpi"))
    old_env = dict(env, CLAUDE_PROJECT_DIR=legacy, ENABLER_KPI_USER="old@example.com")
    old_env.pop("ENABLER_METRICS_USER", None)
    subprocess.run([sys.executable, HOOK], text=True, env=old_env, check=True,
                   input=json.dumps({"hook_event_name": "SessionStart", "session_id": "legacy-1", "cwd": legacy}))
    assert os.path.isfile(os.path.join(legacy, ".enabler", "kpi", "events", "old@example.com", "legacy-1.jsonl"))
    assert not os.path.exists(os.path.join(legacy, ".enabler", "metrics"))

    # Old folder and new folder side by side: both are read, so no history disappears.
    both = os.path.join(tmp, "both")
    for rel, sid_, who in (("kpi", "s-old", "old@x.org"), ("metrics", "s-new", "new@x.org")):
        d = os.path.join(both, ".enabler", rel, "events", who)
        os.makedirs(d)
        with open(os.path.join(d, sid_ + ".jsonl"), "w") as fh:
            fh.write(json.dumps({"v": 1, "ts": "2026-10-01T10:00:00Z", "t": 1790848800.0, "ev": "prompt",
                                 "kind": "human", "sid": sid_, "user": who}) + "\n")
    run = subprocess.run([sys.executable, REPORT, "--quiet", "--out-dir", os.path.join(tmp, "both-report")],
                         capture_output=True, text=True, env=dict(env, CLAUDE_PROJECT_DIR=both))
    assert run.returncode == 0 and "both" in run.stderr, run.stderr
    assert json.load(open(os.path.join(tmp, "both-report", "usage.json")))["overall"]["sessions"] == 2

    # A project that did not opt in records nothing.
    other = os.path.join(tmp, "other")
    os.makedirs(other)
    subprocess.run([sys.executable, HOOK], text=True, env=dict(env, CLAUDE_PROJECT_DIR=other),
                   input=json.dumps({"hook_event_name": "SessionStart", "session_id": "x", "cwd": other}))
    assert not os.path.exists(os.path.join(other, ".enabler")), "hook wrote without opt-in"

    bedrock(tmp, env)
    regressions(tmp, env)
    print("ok — %d events, cost $%.3f, report in %s" % (len(events), o["cost_usd"], out_dir))


def bedrock(tmp, base_env):
    """A session served by Amazon Bedrock is priced with Bedrock's table:
    by region, and by global versus regional inference profile."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from usage_report import parse_model

    assert parse_model("arn:aws:bedrock:eu-west-1:123456789012:inference-profile/"
                       "eu.anthropic.claude-sonnet-4-5-20250929-v1:0") == \
        ("claude-sonnet-4-5-20250929", "regional", True)
    assert parse_model("global.anthropic.claude-opus-5-5") == ("claude-opus-5-5", "global", True)
    assert parse_model("anthropic.claude-haiku-4-5-20251001-v1:0") == \
        ("claude-haiku-4-5-20251001", None, True)
    assert parse_model("claude-opus-5-5[1m]") == ("claude-opus-5-5", None, False)

    sid = "99999999-2222-3333-4444-555555555555"
    project = os.path.join(tmp, "bedrock-project")
    metrics_dir = os.path.join(project, ".enabler", "metrics")
    os.makedirs(metrics_dir)
    transcript = os.path.join(tmp, "transcripts", sid + ".jsonl")
    million = {"input_tokens": 1000000, "output_tokens": 1000000}
    with open(transcript, "w") as fh:
        # A geographic profile, a global profile, and an id that names no profile.
        fh.write(assistant("b1", "eu.anthropic.claude-sonnet-4-5-20250929-v1:0", million))
        fh.write(assistant("b2", "global.anthropic.claude-opus-5-5", dict(
            million, cache_read_input_tokens=1000000,
            cache_creation={"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": 1000000})))
        fh.write(assistant("b3", "claude-haiku-4-5-20251001", million))
    env = dict(base_env, CLAUDE_PROJECT_DIR=project, CLAUDE_CODE_USE_BEDROCK="1",
               AWS_REGION="eu-west-1")
    # The session starts before anything is spent (an empty transcript is the baseline).
    start = {"hook_event_name": "SessionStart", "session_id": sid, "cwd": project,
             "transcript_path": transcript + ".not-yet"}
    subprocess.run([sys.executable, HOOK], input=json.dumps(start), text=True, env=env, check=True)
    for event in ("UserPromptSubmit", "Stop"):
        payload = {"hook_event_name": event, "session_id": sid, "cwd": project,
                   "transcript_path": transcript, "prompt": "PROJ-9"}
        out = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), text=True,
                             capture_output=True, env=env)
        assert out.returncode == 0 and out.stderr == "", out.stderr

    def report(*extra):
        out_dir = os.path.join(tmp, "bedrock-report")
        run = subprocess.run([sys.executable, REPORT, "--metrics-dir", metrics_dir, "--out-dir", out_dir,
                              "--quiet"] + list(extra), capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        return json.load(open(os.path.join(out_dir, "usage.json")))

    metrics_out = report()
    by = metrics_out["cost_by"]["pricing"]
    # eu-west-1 on-demand prices per million tokens (AWS Price List):
    #   Sonnet 4.5 regional 3.30 + 16.50                     = 19.80
    #   Opus 5.5 global     4 + 20 + 0.20 read + 8 write-1h  = 32.20
    #   Haiku 4.5, scope unknown -> regional 1.10 + 5.50     =  6.60
    assert abs(by["bedrock · eu-west-1 · regional"] - 26.40) < 1e-6, by
    assert abs(by["bedrock · eu-west-1 · global"] - 32.20) < 1e-6, by
    assert any("global or a regional" in a for a in metrics_out["pricing"]["assumptions"]), metrics_out["pricing"]
    # Telling the report the project uses global profiles reprices only the undecided row.
    metrics_out = report("--bedrock-scope", "global")
    assert abs(metrics_out["overall"]["cost_usd"] - (19.80 + 32.20 + 6.00)) < 1e-6, metrics_out["overall"]["cost_usd"]
    # Forced to the Anthropic list table: 32.2 + 6, and the model that table
    # does not carry is reported as unpriced instead of counted as zero.
    metrics_out = report("--provider", "anthropic")
    assert abs(metrics_out["overall"]["cost_usd"] - 38.20) < 1e-6, metrics_out["overall"]["cost_usd"]
    assert list(metrics_out["pricing"]["unpriced_tokens"].values()) == [2000000], metrics_out["pricing"]


def regressions(tmp, base_env):
    """Cases found in review."""
    sys.path.insert(0, os.path.join(ROOT, "hooks"))
    from usage_hook import bash_summary, SLASH_COMMAND, HARNESS_PROMPT

    assert bash_summary("git commit -m 'a && b' && git push origin x")["git"] == "commit+push"
    assert "git" not in bash_summary("git log --grep commit")
    assert "git" not in bash_summary("git status # before commit")
    assert bash_summary("git -C repo commit -m x")["git"] == "commit"
    assert "pr" not in bash_summary("gh pr create --help")
    assert bash_summary("FOO=1 gh pr create --fill").get("pr") is True
    assert bash_summary("cd app && mvn -q test")["cmd"] == "mvn"
    assert SLASH_COMMAND.match("/ai-enabler:delivery-run") and SLASH_COMMAND.match("/clear")
    assert not SLASH_COMMAND.match("/home/acme/payroll.py")
    assert HARNESS_PROMPT.match("<task-notification>") and not HARNESS_PROMPT.match("<div class='x'> why")

    # Opting in mid-session: what was spent before is the baseline, not this turn's cost.
    sid = "77777777-2222-3333-4444-555555555555"
    project = os.path.join(tmp, "late-project")
    metrics_dir = os.path.join(project, ".enabler", "metrics")
    os.makedirs(metrics_dir)
    transcript = os.path.join(tmp, "transcripts", sid + ".jsonl")
    with open(transcript, "w") as fh:
        for n in range(50):
            fh.write(assistant("old%d" % n, "claude-opus-5-5", {"input_tokens": 1000, "output_tokens": 1000}))
    env = dict(base_env, CLAUDE_PROJECT_DIR=project)

    def fire(event, **fields):
        payload = dict({"hook_event_name": event, "session_id": sid, "cwd": project,
                        "transcript_path": transcript}, **fields)
        out = subprocess.run([sys.executable, HOOK], input=json.dumps(payload), text=True,
                             capture_output=True, env=env)
        assert out.returncode == 0 and out.stderr == "", out.stderr

    fire("UserPromptSubmit", prompt="/home/acme/secret-client/payroll.py crashes on PROJ-1")
    fire("Stop")
    with open(transcript, "a") as fh:
        fh.write(assistant("new1", "claude-opus-5-5", {"input_tokens": 1000, "output_tokens": 1000}))
    fire("UserPromptSubmit", prompt="go on")
    fire("PostToolUseFailure", tool_name="Bash", tool_use_id="x1", tool_input={"command": "git commit -m x"})
    fire("Stop")
    raw = open(os.path.join(metrics_dir, "events", "dev@example.com", sid + ".jsonl")).read()
    events = [json.loads(line) for line in raw.splitlines()]
    assert "secret-client" not in raw and events[0]["kind"] == "human", events[0]
    usage = [e for e in events if e["ev"] == "usage"]
    assert len(usage) == 1 and usage[0]["rows"][0]["in"] == 1000, usage

    # Events recorded before the 1.0.0 rename are reported under the current names.
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from usage_report import current_names
    old = current_names({"ev": "usage", "rows": [{"skill": "ai-enabler:deliver", "agent": "ai-enabler:code-reviewer"}]})
    assert old["rows"][0] == {"skill": "ai-enabler:delivery-run", "agent": "ai-enabler:delivery-code-reviewer"}
    assert current_names({"ev": "prompt", "command": "ai-enabler:plan"})["command"] == "ai-enabler:delivery-plan"
    assert current_names({"ev": "tool", "skill": "ai-enabler-kpi:kpi-report"})["skill"] == "ai-enabler-metrics:metrics-usage-report"

    # A project price file that only adds one Bedrock region keeps the bundled prices.
    with open(os.path.join(metrics_dir, "pricing.json"), "w") as fh:
        json.dump({"providers": {"bedrock": {"regions": {"xx-test-1": {"models": {
            "claude-opus-5-5": {"regional": {"input": 1.0, "output": 1.0}}}}}}}}, fh)
    out_dir = os.path.join(tmp, "late-report")
    run = subprocess.run([sys.executable, REPORT, "--metrics-dir", metrics_dir, "--out-dir", out_dir, "--quiet",
                          "--ticket", "PROJ-1"], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    metrics_out = json.load(open(os.path.join(out_dir, "usage.json")))
    assert abs(metrics_out["overall"]["cost_usd"] - 0.024) < 1e-6, metrics_out["overall"]   # 1000*4 + 1000*20, list price
    assert metrics_out["overall"]["commits"] == 0 and metrics_out["overall"]["tool_failures"] == 1
    assert metrics_out["overall"]["human_prompts"] == 2, metrics_out["overall"]             # --ticket keeps the whole session


if __name__ == "__main__":
    main()
