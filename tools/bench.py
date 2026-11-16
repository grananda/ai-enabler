#!/usr/bin/env python3
"""Compare benchmark runs of the delivery pipeline, side by side.

Each case is one run: the usage.json written by ai-enabler-metrics'
usage_report.py for that run's events, and optionally the run's directory
(.enabler/runs/<KEY>) for the quality side. The output is a Markdown table
with one column per case and, from two cases on, the change of the last case
against the first.

    python tools/bench.py --case "1.8.0 run 1" report-1/usage.json runs-1/AI4IT-35 \\
                          --case "1.8.1 run 2" report-2/usage.json runs-2/AI4IT-35 [--out bench.md]

The procedure that produces the inputs is in docs/benchmark.md. Standard
library only.
"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime

AC_ROW = re.compile(r"^\|\s*AC-?\d+\s*\|")


def duration(seconds):
    if seconds is None:
        return "–"
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return "%dh %02dm" % (h, m) if h else "%dm %02ds" % (m, s)


def wall_clock(overall):
    try:
        first = datetime.fromisoformat(overall["first_event"].replace("Z", "+00:00"))
        last = datetime.fromisoformat(overall["last_event"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError):
        return None
    return (last - first).total_seconds()


def criteria(run_dir):
    """(met, total) from the acceptance-criteria table of delivery-report.md."""
    path = os.path.join(run_dir, "delivery-report.md")
    if not os.path.isfile(path):
        return None
    met = total = 0
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not AC_ROW.match(line):
                continue
            cells = [c.strip().lower() for c in line.strip().strip("|").split("|")]
            total += 1
            met += any(re.match(r"met\b", c) for c in cells)
    return (met, total) if total else None


def load_case(label, usage_path, run_dir=None):
    with open(usage_path, encoding="utf-8") as fh:
        usage = json.load(fh)
    o = usage.get("overall") or {}
    case = {
        "label": label,
        "cost": o.get("cost_usd"),
        "agents": (usage.get("cost_by") or {}).get("agent") or {},
        "tokens_input": o.get("tokens_input"),
        "tokens_output": o.get("tokens_output"),
        "tokens_cache_read": o.get("tokens_cache_read"),
        "tokens_cache_write": o.get("tokens_cache_write"),
        "ai_seconds": o.get("ai_seconds"),
        "human_seconds": o.get("human_seconds"),
        "wall_seconds": wall_clock(o),
        "human_interactions": o.get("human_interactions"),
        "tool_calls": o.get("tool_calls"),
        "subagent_runs": o.get("subagent_runs"),
        "compactions": o.get("compactions"),
        "unpriced": sum(((usage.get("pricing") or {}).get("unpriced_tokens") or {}).values()),
    }
    if run_dir:
        state = {}
        state_path = os.path.join(run_dir, "state.json")
        if os.path.isfile(state_path):
            with open(state_path, encoding="utf-8") as fh:
                state = json.load(fh)
        rounds = state.get("gate_rounds") or {}
        kinds = Counter(i.get("kind") for i in state.get("human_interventions") or [] if i.get("kind"))
        case.update({
            "criteria": criteria(run_dir),
            "plan_rounds": rounds.get("plan"),
            "ship_rounds": rounds.get("ship"),
            "interventions": ", ".join("%s %d" % kv for kv in sorted(kinds.items())) or None,
        })
    return case


def num(value, fmt="{:,.0f}"):
    return "–" if value is None else fmt.format(value)


def change(first, last):
    if not isinstance(first, (int, float)) or not isinstance(last, (int, float)) or not first:
        return ""
    return "%+.0f %%" % ((last - first) * 100.0 / first)


def table(cases):
    rows = []

    def row(name, key, show, numeric=True):
        values = [c.get(key) for c in cases]
        delta = change(values[0], values[-1]) if numeric and len(cases) > 1 else ""
        rows.append([name] + [show(v) for v in values] + ([delta] if len(cases) > 1 else []))

    money = lambda v: num(v, "${:,.2f}")
    rows.append(["**Efficiency**"] + [""] * (len(cases) + (len(cases) > 1)))
    row("Cost", "cost", money)
    for agent in sorted({a for c in cases for a in c["agents"]},
                        key=lambda a: -max(c["agents"].get(a, 0) for c in cases)):
        values = [c["agents"].get(agent) for c in cases]
        rows.append(["· " + agent] + [money(v) for v in values]
                    + ([change(values[0], values[-1])] if len(cases) > 1 else []))
    row("Cache read tokens", "tokens_cache_read", num)
    row("Cache write tokens", "tokens_cache_write", num)
    row("Output tokens", "tokens_output", num)
    row("Input tokens (uncached)", "tokens_input", num)
    row("AI working time", "ai_seconds", duration)
    row("Human time", "human_seconds", duration)
    row("Wall clock", "wall_seconds", duration)
    row("Human interactions", "human_interactions", num)
    row("Tool calls", "tool_calls", num)
    row("Subagent runs", "subagent_runs", num)
    row("Compactions", "compactions", num)
    if any("criteria" in c for c in cases):
        rows.append(["**Quality**"] + [""] * (len(cases) + (len(cases) > 1)))
        row("Acceptance criteria met", "criteria", lambda v: "%d / %d" % v if v else "–", numeric=False)
        row("Plan gate rounds", "plan_rounds", num)
        row("Ship gate rounds", "ship_rounds", num)
        row("Human interventions", "interventions", lambda v: v or "–", numeric=False)
    header = ["Indicator"] + [c["label"] for c in cases] + (["Last vs first"] if len(cases) > 1 else [])
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    notes = [c["label"] for c in cases if c["unpriced"]]
    if notes:
        lines += ["", "Unpriced tokens in: %s — their cost is understated." % ", ".join(notes)]
    return "\n".join(lines) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--case", nargs="+", action="append", required=True,
                    metavar="LABEL USAGE_JSON [RUN_DIR]",
                    help="A label, the run's usage.json and, optionally, its .enabler/runs/<KEY> directory.")
    ap.add_argument("--out", help="Write the table to this file instead of standard output.")
    args = ap.parse_args(argv)
    cases = []
    for spec in args.case:
        if len(spec) not in (2, 3):
            ap.error("--case takes LABEL USAGE_JSON [RUN_DIR]; got %r" % spec)
        cases.append(load_case(*spec))
    text = table(cases)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
