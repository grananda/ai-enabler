#!/usr/bin/env python3
"""ai-enabler scout guard.

A PreToolUse hook. The repository scout and the source scout only inspect, and every
command they run is short and runs in the foreground ("Commands on a large repository"
in their instructions). A command sent to the background and then waited on can hold a
scout for hours, so this refuses a background command when the call comes from either
scout. Every other agent, and the main conversation, is left alone.

Claude Code names the agent a hook fires in with `agent_type`: `ai-enabler:<name>` for
this plugin's agents, the bare name for a copy installed as a project agent.
"""

import json
import sys

SCOUTS = ("delivery-repo-scout", "delivery-source-scout")


def is_scout(agent_type):
    return agent_type in SCOUTS or agent_type in ("ai-enabler:" + s for s in SCOUTS)


def main():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    agent = str(payload.get("agent_type") or "")
    ti = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    if not is_scout(agent) or ti.get("run_in_background") not in (True, "true"):
        return 0
    sys.stderr.write(
        "Blocked by ai-enabler: %s runs commands in the foreground only. Run it again without "
        "run_in_background. If it cannot finish within the default timeout, it is too broad: narrow it "
        "with a path, a pattern or -n, as \"Commands on a large repository\" says.\n" % agent)
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)
