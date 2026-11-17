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
    run_state.py intake <run_dir> [--order auto|after] [--lane S|M|L] [--gates LIST] [--no-refine]
                        [--config PATH]
        Reads requirements.json once and prints what the orchestrator needs from it: the verdicts
        after refinement, the counts, the blocking questions in full, and test_order, which it
        also records in state.json. Also the lane (S, M or L) from the analyst's size and risk
        areas, the settings that lane gives this run (gates, refinement, review, test budget) and
        whether the ticket needs refining; run it after the analyst and again after the refiner.
    run_state.py show   <run_dir>
    run_state.py gate   <run_dir> plan|ship|delta|coverage|blocked
        Records that the run waits for a person (`waiting` in state.json, which the gate notification
        hook reads; the next update that records a decision clears it). For `ship` it also prints the
        ship gate, filled in from the run's files: diff, criteria, tests, review, deltas, lane, and
        what shipping will do.
    run_state.py render <run_dir>
        Writes test-report.md and acceptance-tests.md from the test engineer's test-report.json and
        acceptance-tests.json, for people and for the stages that read Markdown. `update` does it too,
        whenever a JSON file is newer than its Markdown, so the orchestrator rarely calls it.

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
SIZES = ["S", "M", "L"]
# What a run spends, by lane. A key set in .enabler/config.json to something other than its default wins over this.
DEFAULTS = {"gates": ["plan", "ship"], "refine": "always",
            "review": {"select_lenses": True, "group_below_lines": 150},
            "tests": {"full_suite_runs": 2, "mutation": {"enabled": True, "max_mutants": 40}}}
LANES = {
    "S": {"refine": "gaps", "review": {"group_below_lines": 400},
          "tests": {"full_suite_runs": 1, "mutation": {"max_mutants": 10}}},
    "M": {"tests": {"mutation": {"max_mutants": 25}}},
    "L": {"review": {"select_lenses": False, "group_below_lines": 0}},
}
# A risk area sets the lowest lane a ticket may run in.
RISK_LANE = {"authentication": "L", "permissions": "L", "personal_data": "L"}


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
    at = state.get("stage")             # an intervention belongs to the stage it happened at: --done moves on after it
    if args.stage:
        at = args.stage
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
            {"at": now(), "stage": args.at_stage or at, "kind": kind, "note": note})
    if args.intervene or args.done or args.status:
        state.pop("waiting", None)      # a decision was taken, or the run moved on: nobody is waited for
    notes = state.setdefault("profile_notes", [])
    notes.extend(n for n in args.note if n not in notes)
    state["profile_notes"] = [n for n in notes if n not in args.drop_note]
    save(args.run_dir, state)
    written, errors = render(args.run_dir)
    extra = {}
    if written:
        extra["rendered"] = written
    if errors:
        extra["render_errors"] = errors
    return view(state, **extra)


def merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def chosen(config):
    """The settings the person chose in config.json: only the keys whose value differs from the default."""
    picked = {}
    if "gates" in config and config["gates"] != DEFAULTS["gates"]:
        picked["gates"] = config["gates"]
    if (config.get("refine") or {}).get("enabled") is False:
        picked["refine"] = "never"
    for section, keys in (("review", ("select_lenses", "group_below_lines")), ("tests", ("full_suite_runs",))):
        for k in keys:
            v = (config.get(section) or {}).get(k)
            if v is not None and v != DEFAULTS[section][k]:
                picked.setdefault(section, {})[k] = v
    mutation = (config.get("tests") or {}).get("mutation") or {}
    for k in ("enabled", "max_mutants"):
        if k in mutation and mutation[k] != DEFAULTS["tests"]["mutation"][k]:
            picked.setdefault("tests", {}).setdefault("mutation", {})[k] = mutation[k]
    return picked


def load_config(run_dir, path=None):
    path = path or os.path.join(run_dir, os.pardir, os.pardir, "config.json")
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def lane_of(req, config, forced=None):
    """The lane a ticket runs in, and the settings that gives it."""
    size = req.get("size") if req.get("size") in SIZES else "M"
    risks = [r for r in req.get("risk_areas") or [] if isinstance(r, str)]
    minimum = max([RISK_LANE.get(r, "M") for r in risks] or ["S"], key=SIZES.index)
    name = forced if forced in SIZES else max(size, minimum, key=SIZES.index)
    lanes = config.get("lanes") or {}
    settings = dict(DEFAULTS)
    if lanes.get("enabled", True) is not False:
        settings = merge(merge(settings, LANES[name]), lanes.get(name))
    else:
        name = None
    settings = merge(settings, chosen(config))
    lane = {"name": name, "size": size, "risk_areas": risks, "minimum": minimum,
            "forced": bool(forced), "below_minimum": bool(name and SIZES.index(name) < SIZES.index(minimum))}
    return lane, settings


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
    has_state = os.path.isfile(path_of(args.run_dir, "state.json"))
    state = load(args.run_dir) if has_state else {}
    forced = args.lane or ((state.get("lane") or {}).get("name") if (state.get("lane") or {}).get("forced") else None)
    lane, settings = lane_of(req, load_config(args.run_dir, args.config), forced)
    if args.gates is not None:
        settings["gates"] = [g for g in args.gates.split(",") if g and g != "none"]
    if args.no_refine:
        settings["refine"] = "never"
    gaps = (req.get("readiness") != "ready" or quality != "sufficient" or bool(questions)
            or bool(req.get("requirements_without_criteria")))
    out = {
        "readiness": req.get("readiness"),
        "criteria_quality": quality,
        "test_order": order,
        "refined": bool(req.get("refinement")),
        "lane": lane,
        "settings": settings,
        "needs_refinement": settings["refine"] == "always" or (settings["refine"] == "gaps" and gaps),
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
    if has_state:
        state["test_order"] = order
        state["lane"] = {k: lane[k] for k in ("name", "size", "risk_areas", "forced")}
        state["settings"] = settings
        save(args.run_dir, state)
    return out


def cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, list):
        v = ", ".join(cell(x) for x in v)
    elif isinstance(v, dict):
        v = json.dumps(v, ensure_ascii=False)
    return str(v).replace("|", "\\|").replace("\r", "").replace("\n", "<br>")


def table(rows, columns=None):
    """A Markdown table from a list of dicts; the columns are the given ones, then any other key found."""
    rows = [r if isinstance(r, dict) else {"item": r} for r in rows]
    cols = [c for c in (columns or []) if any(c in r for r in rows)]
    for r in rows:
        cols += [k for k in r if k not in cols]
    out = ["| " + " | ".join(c.replace("_", " ").capitalize() for c in cols) + " |",
           "|" + "---|" * len(cols)]
    out += ["| " + " | ".join(cell(r.get(c)) for c in cols) + " |" for r in rows]
    return out


def block(title, value, columns=None):
    """One section of a rendered report, whatever shape the agent gave the value."""
    if value in (None, "", [], {}):
        return []
    out = ["", "## " + title, ""]
    if isinstance(value, list) and all(isinstance(x, dict) for x in value):
        out += table(value, columns)
    elif isinstance(value, list):
        out += ["- " + cell(x) for x in value]
    elif isinstance(value, dict):
        for k, v in value.items():
            if isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
                out += ["", "**%s**" % k.replace("_", " ").capitalize(), ""] + table(v)
            else:
                out.append("- **%s:** %s" % (k.replace("_", " "), cell(v)))
    else:
        out.append(cell(value))
    return out


def pct(v):
    return "n/a" if v is None else ("%s %%" % v if isinstance(v, (int, float)) else str(v))


GENERATED = "<!-- Generated by run_state.py from %s. Edit the JSON, not this file. -->"


def render_test_report(data, key):
    d = dict(data)
    suite = d.pop("suite", None) or {}
    cov = d.pop("coverage", None) or {}
    out = ["# Test report — %s" % (d.pop("key", None) or key), "", GENERATED % "test-report.json", ""]
    head = ["**Verdict:** %s" % d.pop("verdict", "?")]
    if "coverage_verdict" in d:
        head.append("**Coverage:** %s" % d.pop("coverage_verdict"))
    if isinstance(suite, dict) and suite:
        head.append("**Suite:** %s passed, %s failed, %s skipped" % (
            suite.get("passed", "?"), suite.get("failed", "?"), suite.get("skipped", 0)))
    out.append(" · ".join(head))
    d.pop("mode", None)
    if isinstance(cov, dict) and cov:
        files = cov.pop("files", None)
        out += ["", "## Coverage of the changed code", ""]
        if any(k in cov for k in ("line_percent", "branch_percent", "target", "minimum")):
            out.append("Line %s · branch %s (target %s · minimum %s)" % (
                pct(cov.pop("line_percent", None)), pct(cov.pop("branch_percent", None)),
                pct(cov.pop("target", None)), pct(cov.pop("minimum", None))))
        if files:
            out += [""] + table(files, ["file", "line_percent", "branch_percent", "uncovered"])
        for k, v in cov.items():
            out.append("- **%s:** %s" % (k.replace("_", " "), cell(v)))
    elif cov:
        out += block("Coverage of the changed code", cov)
    out += block("Acceptance criteria", d.pop("criteria", None), ["id", "tests", "written", "status"])
    mut = d.pop("mutation", None)
    if isinstance(mut, dict) and mut:
        surviving = mut.pop("surviving", None)
        line = ", ".join("%s %s" % (k.replace("_", " "), cell(mut.pop(k)))
                         for k in ("enabled", "decision_points", "mutants", "killed") if k in mut)
        out += ["", "## Mutation testing", "", line or "—"]
        if surviving:
            out += ["", "**Surviving**", ""] + (table(surviving, ["where", "mutant", "reason"])
                                                if isinstance(surviving, list) else [cell(surviving)])
        for k, v in mut.items():
            out.append("- **%s:** %s" % (k.replace("_", " "), cell(v)))
    else:
        out += block("Mutation testing", mut)
    out += block("Defects", d.pop("defects", None), ["test", "criterion", "expected", "actual", "suspect"])
    out += block("Pre-existing failures", d.pop("pre_existing_failures", None))
    out += block("Test files", d.pop("test_files", None), ["file", "action"])
    out += block("Commands", d.pop("commands", None), ["command", "purpose", "seconds", "exit"])
    out += block("Repository profile findings", d.pop("profile_findings", None))
    out += block("Notes", d.pop("notes", None))
    out += block("Re-runs", d.pop("reruns", None), ["at", "scope", "passed", "failed", "failing"])
    for k, v in d.items():
        out += block(k.replace("_", " ").capitalize(), v)
    return "\n".join(out) + "\n"


def render_acceptance(data, key):
    d = dict(data)
    out = ["# Acceptance tests — %s" % (d.pop("key", None) or key), "", GENERATED % "acceptance-tests.json", "",
           "**Verdict:** %s" % d.pop("verdict", "?")]
    d.pop("mode", None)
    out += block("Tests written before the code", d.pop("tests", None), ["criterion", "file", "tests", "asserts"])
    out += block("Criteria not tested before the code", d.pop("not_tested", None), ["criterion", "reason"])
    out += block("Tests removed by a delta", d.pop("removed", None), ["test", "delta"])
    out += block("Notes", d.pop("notes", None))
    for k, v in d.items():
        out += block(k.replace("_", " ").capitalize(), v)
    return "\n".join(out) + "\n"


RENDERERS = [("test-report", render_test_report), ("acceptance-tests", render_acceptance)]


def render(run_dir, force=False):
    """Renders each JSON report newer than its Markdown; returns the Markdown files written, and any error."""
    key = os.path.basename(os.path.normpath(run_dir))
    written, errors = [], []
    for name, fn in RENDERERS:
        src, dst = path_of(run_dir, name + ".json"), path_of(run_dir, name + ".md")
        if not os.path.isfile(src):
            continue
        if not force and os.path.isfile(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            continue
        try:
            with open(src, encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                raise ValueError("not a JSON object")
            text = fn(data, key)
        except (ValueError, OSError) as e:
            errors.append("%s.json: %s" % (name, e))
            continue
        with open(dst, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        written.append(name + ".md")
    return written, errors


def read_json(run_dir, name):
    try:
        with open(path_of(run_dir, name), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def git(root, *args):
    import subprocess
    try:
        out = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True, encoding="utf-8",
                             errors="replace", timeout=30)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def ship_gate(run_dir, state):
    """The ship gate, filled in from the run's files. A line it cannot fill says `?` and what to put there."""
    root = os.path.abspath(os.path.join(run_dir, os.pardir, os.pardir, os.pardir))
    config = load_config(run_dir)
    key, base, branch = state.get("key", "?"), state.get("base_branch") or "main", state.get("branch") or "?"
    req, rep, acc = read_json(run_dir, "requirements.json"), read_json(run_dir, "test-report.json"), \
        read_json(run_dir, "acceptance-tests.json")
    review = state.get("review_result") or {}
    blockers = []

    stat = git(root, "diff", "--shortstat", base)
    untracked = [p for p in git(root, "ls-files", "--others", "--exclude-standard").splitlines()
                 if p and not p.startswith(".enabler/")]
    diff = stat or "no change against %s" % base
    if untracked:
        diff += " · %d new file%s not yet tracked" % (len(untracked), "" if len(untracked) == 1 else "s")

    crit = [c for c in req.get("acceptance_criteria") or [] if isinstance(c, dict) and not c.get("removed_by")]
    refined = [c for c in crit if c.get("refined")]
    status = {c.get("id"): c.get("status") for c in rep.get("criteria") or [] if isinstance(c, dict)}
    met = review.get("criteria_met")
    if met is None and status:
        met = len([c for c in crit if status.get(c.get("id")) == "covered"])
    approved = "approved at the plan gate" if any(i.get("kind") == "approval" and i.get("stage") in ("plan", "acceptance-tests")
                                                  for i in state.get("human_interventions") or []) \
        else "NOT REVIEWED: no plan gate in this run"
    criteria = "%s/%d met" % ("?" if met is None else met, len(crit))
    if refined:
        criteria += " · %d of them added by refinement, %s" % (len(refined), approved)

    suite = rep.get("suite") or {}
    cov = rep.get("coverage") or {}
    verdict = rep.get("coverage_verdict") or "?"
    accepted = any(i.get("kind") == "coverage_accepted" for i in state.get("human_interventions") or [])
    if verdict == "below minimum":
        verdict = "BELOW MINIMUM, accepted by the person" if accepted else "BELOW MINIMUM"
        if not accepted:
            blockers.append("coverage below the minimum, not accepted")
    if suite.get("failed"):
        blockers.append("%s failing tests" % suite["failed"])
    if rep.get("defects"):
        blockers.append("%d open defects" % len(rep["defects"]))
    tests = "%s passed, %s failed · coverage %s line (target %s · minimum %s) — %s" % (
        suite.get("passed", "?"), suite.get("failed", "?"), pct(cov.get("line_percent")),
        pct(cov.get("target", 80)), pct(cov.get("minimum", 70)), verdict) if rep else "? — no test-report.json"
    before = len(acc.get("tests") or [])
    mut = rep.get("mutation") or {}
    if mut.get("enabled") is False:
        mutation = "mutation testing off"
    elif not mut.get("mutants"):
        mutation = "no mutants: no decision logic changed" if mut else "?"
    else:
        surviving = mut.get("surviving") or []
        mutation = "%s of %s killed · %d surviving%s" % (
            mut.get("killed", "?"), mut.get("mutants"), len(surviving),
            "".join("\n              %s — %s" % (cell(s.get("where")), cell(s.get("reason")))
                    for s in surviving if isinstance(s, dict)))

    if review:
        rv = "%s fixed · %s open" % (review.get("fixed", 0), review.get("open", 0))
        if review.get("highest_open"):
            rv += " (%s)" % review["highest_open"]
        if review.get("highest_open") == "critical":
            blockers.append("a critical finding is open")
    else:
        rv = "? — set review_result first"
    deltas = state.get("deltas") or []
    dl = "%d since the plan was approved (%s)" % (len(deltas), "; ".join(d.get("summary", "") for d in deltas)) \
        if deltas else "none"

    lane = state.get("lane") or {}
    git_cfg, jira_cfg = config.get("git") or {}, config.get("jira") or {}
    local = os.path.isfile(os.path.join(root, ".enabler", "local-only")) or git_cfg.get("local_only") is True
    if local:
        will = "nothing leaves this machine (local-only) — local commit on %s only" % branch
        question = "Commit locally? (local / hold / fix: <what to change>)"
    else:
        will = "commit → push %s" % branch
        if git_cfg.get("pull_request", True) is not False:
            will += " → open PR against %s" % base
        if state.get("source") == "jira":
            if jira_cfg.get("comment_on_ship", True) is not False:
                will += " → comment on %s" % key
            if jira_cfg.get("transition_on_ship"):
                will += ' → transition to "%s"' % jira_cfg["transition_on_ship"]
        question = "Ship it? (ship / local / hold / fix: <what to change>)"

    lines = []
    if blockers:
        lines.append("NOT READY — %s. Holding, or a draft pull request, is recommended." % "; ".join(blockers))
    lines += ["READY TO SHIP — %s" % key,
              "Diff      : %s, on %s" % (diff, branch),
              "Criteria  : %s" % criteria,
              "Tests     : %s" % tests,
              "            acceptance tests written before the code: %d of %d criteria" % (before, len(crit)),
              "            mutants: %s" % mutation,
              "Review    : %s" % rv,
              "Deltas    : %s" % dl]
    if lane.get("name"):
        lines.append("Lane      : %s (size %s; risks: %s)" % (lane["name"], lane.get("size"),
                                                           ", ".join(lane.get("risk_areas") or []) or "none"))
    if "plan" not in ((state.get("settings") or {}).get("gates") or ["plan"]):
        lines.append("Plan      : not reviewed before the code — .enabler/runs/%s/plan.md" % key)
    lines.append("Will do   : %s" % will)
    if not local and git_cfg.get("pull_request", True) is not False:
        lines.append("PR body   : %s" % (state.get("pr_template") or "? — the template settled for this run"))
    lines += ["Report    : .enabler/runs/%s/delivery-report.md" % key, "", question]
    return "\n".join(lines)


def cmd_gate(args):
    state = load(args.run_dir)
    state["waiting"] = {"gate": args.gate, "since": now()}
    save(args.run_dir, state)
    if args.gate == "ship":
        return ship_gate(args.run_dir, state)
    return None


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
    p.add_argument("--lane", choices=SIZES, help="The lane the person chose (--lane, or adjust: lane X).")
    p.add_argument("--gates", help="--gates of delivery-run: plan,ship | plan | ship | none.")
    p.add_argument("--no-refine", action="store_true")
    p.add_argument("--config", help="Default: .enabler/config.json above the run directory.")
    p = sub.add_parser("show")
    p.add_argument("run_dir")
    p = sub.add_parser("gate")
    p.add_argument("run_dir")
    p.add_argument("gate", choices=["plan", "ship", "delta", "coverage", "blocked"])
    p = sub.add_parser("render")
    p.add_argument("run_dir")
    p.add_argument("--force", action="store_true", help="Render even when the Markdown is newer.")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")    # the gates print arrows and dashes; Windows consoles default to cp1252
    if args.cmd == "init":
        out = cmd_init(args)
    elif args.cmd == "update":
        out = cmd_update(args)
    elif args.cmd == "intake":
        out = cmd_intake(args)
    elif args.cmd == "render":
        written, errors = render(args.run_dir, force=args.force)
        out = {"rendered": written, "errors": errors}
    elif args.cmd == "gate":
        text = cmd_gate(args)
        if text is not None:
            sys.stdout.write(text + "\n")
            return 0
        out = view(load(args.run_dir), waiting=args.gate)
    else:
        out = view(load(args.run_dir))
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
