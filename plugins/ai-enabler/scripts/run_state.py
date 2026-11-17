#!/usr/bin/env python3
"""The bookkeeping of a delivery run, so the orchestrator does not edit state.json by hand.

    run_state.py init   <run_dir> --key KEY --source jira|file [--base BRANCH]
        Creates state.json with its defaults, or leaves an existing one as it is (a resume).
    run_state.py update <run_dir> [--done STAGE] [--stage STAGE] [--status active|held|stopped]
                        [--set PATH=VALUE ...] [--add PATH=N ...] [--append PATH=JSON ...]
                        [--intervene KIND NOTE ...] [--note TEXT ...] [--drop-note TEXT ...] [--drop-delta ID ...]
        One call per transition. --done adds the stage to stages_done and moves `stage` to the next
        one. --set takes a dotted path and a JSON value (a bare word is a string); a number in the
        path indexes a list, and `delta:<id>.<field>` names a delta (`delta:delta-01.approved=true`).
        --add adds N to a number (gate_rounds.plan=1). --append adds to a list; a new delta
        (`deltas={"id": "delta-01", "trigger": "...", "summary": "..."}`) gets its time and
        approved/applied false. --drop-delta removes a cancelled one. --intervene appends to
        human_interventions, stamped with the time and the current stage. --note / --drop-note
        keep profile_notes.
    run_state.py intake <run_dir> [--order auto|after]
        Reads requirements.json once and prints what the orchestrator needs from it: the verdicts
        after refinement, the counts, the blocking questions in full, and test_order, which it
        also records in state.json.
    run_state.py show   <run_dir>

Every command prints a compact JSON view of the state (or of the intake). Times are UTC.
No third-party dependencies; no model involved.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

STAGES = ["intake", "scout", "plan", "acceptance-tests", "implement", "coverage", "review", "ship", "done"]
STATUSES = ["active", "held", "stopped"]
KINDS = ["approval", "adjustment", "fix", "delta", "question", "takeover", "coverage_accepted", "hold", "local",
         "ship", "cancel", "stop"]
ORDER = {"sufficient": "before", "scarce": "mixed", "missing": "after"}
VIEW = ["key", "stage", "status", "stages_done", "plan_approved", "test_order", "refined", "branch",
        "gate_rounds", "fix_rounds", "deltas", "profile_notes", "pr_url"]


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def path_of(run_dir, name):
    return os.path.join(run_dir, name)


def load(run_dir):
    p = path_of(run_dir, "state.json")
    if not os.path.isfile(p):
        sys.exit("run_state: no state.json in %s; run `init` first." % run_dir)
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def save(run_dir, state):
    p = path_of(run_dir, "state.json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(state, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    os.replace(tmp, p)


def view(state, **extra):
    out = {k: state[k] for k in VIEW if k in state}
    out["interventions"] = len(state.get("human_interventions") or [])
    if out.get("deltas"):
        out["deltas"] = [{k: d.get(k) for k in ("id", "approved", "applied")} for d in out["deltas"]]
    out.update(extra)
    return out


def value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def walk(state, dotted, create=True):
    """(container, key) for a dotted path; a numeric segment indexes a list (-1 is the last item)."""
    keys = dotted.split(".")
    node = state
    for k in keys[:-1]:
        if isinstance(node, list):
            try:
                node = node[int(k)]
            except (ValueError, IndexError):
                sys.exit("run_state: no item %s in %s" % (k, dotted))
            continue
        if not isinstance(node.get(k), (dict, list)):
            if not create:
                return None, None
            node[k] = {}
        node = node[k]
    last = keys[-1]
    if isinstance(node, list):
        try:
            return node, int(last) if int(last) >= 0 else len(node) + int(last)
        except ValueError:
            sys.exit("run_state: %s is a list; index it by number" % dotted)
    return node, last


def find_delta(state, ident):
    for i, d in enumerate(state.get("deltas") or []):
        if d.get("id") == ident:
            return i
    sys.exit("run_state: no delta %s" % ident)


def cmd_init(args):
    os.makedirs(args.run_dir, exist_ok=True)
    p = path_of(args.run_dir, "state.json")
    if os.path.isfile(p):
        return view(load(args.run_dir), resumed=True)
    state = {"key": args.key, "source": args.source, "started_at": now(), "base_branch": args.base,
             "branch": None, "stage": "intake", "status": "active", "stages_done": [], "plan_approved": False,
             "fix_rounds": 0, "gate_rounds": {"plan": 0, "ship": 0}, "deltas": [], "external_context": {},
             "profile_notes": [], "human_interventions": [], "pr_url": ""}
    save(args.run_dir, state)
    return view(state, resumed=False)


def cmd_update(args):
    state = load(args.run_dir)
    if args.done:
        done = state.setdefault("stages_done", [])
        if args.done not in done:
            done.append(args.done)
        state["stage"] = STAGES[min(STAGES.index(args.done) + 1, len(STAGES) - 1)]
    if args.stage:
        state["stage"] = args.stage
    if args.status:
        state["status"] = args.status
    for item in args.set:
        if "=" not in item:
            sys.exit("run_state: --set takes PATH=VALUE, got %r" % item)
        dotted, raw = item.split("=", 1)
        if dotted.startswith("delta:"):          # delta:<id>.<field>=value
            ident, _, field = dotted[6:].partition(".")
            dotted = "deltas.%d.%s" % (find_delta(state, ident), field)
        node, key = walk(state, dotted)
        node[key] = value(raw)
    for item in args.append:
        dotted, _, raw = item.partition("=")
        node, key = walk(state, dotted)
        items = node.get(key) if isinstance(node, dict) else None
        if items is None:
            items = node[key] = []
        if not isinstance(items, list):
            sys.exit("run_state: --append needs a list at %s" % dotted)
        entry = value(raw)
        if isinstance(entry, dict) and dotted == "deltas":
            entry = dict({"at": now(), "approved": False, "applied": False}, **entry)
        items.append(entry)
    for ident in args.drop_delta:
        state["deltas"].pop(find_delta(state, ident))
    for item in args.add:
        dotted, _, raw = item.partition("=")
        node, key = walk(state, dotted)
        try:
            node[key] = (node.get(key) or 0) + int(raw or 1)
        except (TypeError, ValueError):
            sys.exit("run_state: --add takes PATH=N on a number, got %r" % item)
    for kind, note in args.intervene:
        if kind not in KINDS:
            sys.exit("run_state: unknown intervention kind %r (one of %s)" % (kind, ", ".join(KINDS)))
        state.setdefault("human_interventions", []).append(
            {"at": now(), "stage": args.at_stage or state.get("stage"), "kind": kind, "note": note})
    notes = state.setdefault("profile_notes", [])
    notes.extend(n for n in args.note if n not in notes)
    state["profile_notes"] = [n for n in notes if n not in args.drop_note]
    save(args.run_dir, state)
    return view(state)


def cmd_intake(args):
    p = path_of(args.run_dir, "requirements.json")
    if not os.path.isfile(p):
        sys.exit("run_state: no requirements.json in %s" % args.run_dir)
    with open(p, encoding="utf-8") as fh:
        req = json.load(fh)
    crit = [c for c in req.get("acceptance_criteria") or [] if isinstance(c, dict)]
    in_force = [c for c in crit if not c.get("removed_by")]
    quality = req.get("acceptance_criteria_quality")
    order = "after" if args.order == "after" else ORDER.get(quality, "after")
    questions = [q for q in req.get("open_questions") or [] if isinstance(q, dict)]
    out = {
        "readiness": req.get("readiness"),
        "criteria_quality": quality,
        "test_order": order,
        "refined": bool(req.get("refinement")),
        "requirements": len([r for r in req.get("requirements") or [] if not (isinstance(r, dict) and r.get("removed_by"))]),
        "criteria": {"in_force": len(in_force),
                     "from_ticket": len([c for c in in_force if not c.get("derived") and not c.get("refined")]),
                     "derived": len([c for c in in_force if c.get("derived")]),
                     "from_refinement": len([c for c in in_force if c.get("refined")]),
                     "removed": len(crit) - len(in_force)},
        "assumptions": len(req.get("assumptions") or []),
        "open_questions": len(questions),
        "blocking_questions": [q for q in questions if q.get("blocking")],
    }
    if os.path.isfile(path_of(args.run_dir, "state.json")):
        state = load(args.run_dir)
        state["test_order"] = order
        save(args.run_dir, state)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init")
    p.add_argument("run_dir")
    p.add_argument("--key", required=True)
    p.add_argument("--source", choices=["jira", "file"], required=True)
    p.add_argument("--base")
    p = sub.add_parser("update")
    p.add_argument("run_dir")
    p.add_argument("--done", choices=STAGES[:-1])
    p.add_argument("--stage", choices=STAGES)
    p.add_argument("--status", choices=STATUSES)
    p.add_argument("--set", action="append", default=[], metavar="PATH=VALUE",
                   help="A dotted path (a number indexes a list; delta:<id>.<field> names a delta) and a JSON value.")
    p.add_argument("--append", action="append", default=[], metavar="PATH=JSON",
                   help="Append to a list; a delta gets at/approved/applied defaults.")
    p.add_argument("--drop-delta", action="append", default=[], metavar="ID")
    p.add_argument("--add", action="append", default=[], metavar="PATH=N")
    p.add_argument("--intervene", nargs=2, action="append", default=[], metavar=("KIND", "NOTE"))
    p.add_argument("--at-stage", choices=STAGES, help="Stage the intervention happened at (default: the current one).")
    p.add_argument("--note", action="append", default=[], metavar="TEXT")
    p.add_argument("--drop-note", action="append", default=[], metavar="TEXT")
    p = sub.add_parser("intake")
    p.add_argument("run_dir")
    p.add_argument("--order", choices=["auto", "after"], default="auto", help="tests.order")
    p = sub.add_parser("show")
    p.add_argument("run_dir")
    args = ap.parse_args(argv)
    if args.cmd == "init":
        out = cmd_init(args)
    elif args.cmd == "update":
        out = cmd_update(args)
    elif args.cmd == "intake":
        out = cmd_intake(args)
    else:
        out = view(load(args.run_dir))
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
