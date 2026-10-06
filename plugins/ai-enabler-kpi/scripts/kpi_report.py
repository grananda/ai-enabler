#!/usr/bin/env python3
"""ai-enabler-kpi report.

Reads the events written by hooks/kpi_hook.py and produces the KPI report:

    report.md   report.html   kpi.json
    sessions.csv   tickets.csv   users.csv   daily.csv

Usage
    kpi_report.py [--kpi-dir DIR ...] [--since YYYY-MM-DD] [--until YYYY-MM-DD]
                  [--user U] [--ticket KEY] [--idle-cap SECONDS]
                  [--pricing FILE] [--provider P] [--bedrock-region R]
                  [--bedrock-scope global|regional] [--out-dir DIR] [--quiet]

Everything in the report is measured from hook events, except cost, which is
token counts multiplied by the price table of the provider that served them:
Anthropic list prices, or Amazon Bedrock on-demand prices per region and
inference-profile scope (scripts/pricing.json, overridable with
<kpi-dir>/pricing.json or --pricing). No third-party dependencies.
"""

import argparse
import csv
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN_FIELDS = ("in", "out", "cr", "cw5", "cw1")
NO_TICKET = "(no ticket)"


# ------------------------------------------------------------------ pricing

GEO_PREFIX = re.compile(r"^(global|us-gov|us|eu|apac|jp|au|ca|sa|me|af)\.")


def parse_model(raw):
    """Reduce a model id to its Anthropic name.

    Returns (base, scope, bedrock_shaped). Bedrock ids come decorated:
    'arn:aws:bedrock:eu-west-1:1234:inference-profile/eu.anthropic.claude-sonnet-4-5-20250929-v1:0'
    -> ('claude-sonnet-4-5-20250929', 'regional', True). `scope` is 'global'
    for global. profiles, 'regional' for geographic ones, None when the id
    does not say.
    """
    m = (raw or "").strip().lower()
    m = re.sub(r"\[[^\]]*\]$", "", m)                 # '[1m]' context suffix
    bedrock = m.startswith("arn:aws") or "anthropic." in m
    if m.startswith("arn:"):
        m = m.rsplit("/", 1)[-1]
    scope = None
    geo = GEO_PREFIX.match(m)
    if geo:
        scope = "global" if geo.group(1) == "global" else "regional"
        m = m[geo.end():]
        bedrock = True
    if m.startswith("anthropic."):
        m = m[len("anthropic."):]
    m = re.sub(r"-v\d+(:\d+)?$", "", m)
    return m, scope, bedrock


def longest_prefix(models, base):
    match = None
    for name in models:
        if base.startswith(name) and (match is None or len(name) > len(match)):
            match = name
    return match


class Pricing:
    """Prices a usage row with the table of the provider that served it.

    Provider, region and scope come from, in order: the project's KPI config
    (an explicit override), what the hook recorded for the session, and the
    shape of the model id. Every assumption made on the way is collected in
    `self.assumptions` and printed in the report.
    """

    def __init__(self, paths, cfg=None):
        self.data, self.source = {}, None
        for p in paths:
            if p and os.path.isfile(p):
                with open(p, encoding="utf-8") as fh:
                    self.data = json.load(fh)
                self.source = p
                break
        if "providers" not in self.data and "models" in self.data:
            # Flat table from an earlier version: treat it as the anthropic one.
            self.data = {"providers": {"anthropic": self.data}}
        self.providers = self.data.get("providers") or {}
        self.cfg = cfg or {}
        self.unpriced = Counter()
        self.assumptions = set()

    def _rates(self, entry, table):
        inp, out = entry.get("input", 0.0), entry.get("output", 0.0)
        return {
            "in": inp, "out": out,
            "cr": entry.get("cache_read", inp * table.get("cache_read_multiplier", 0.1)),
            "cw5": entry.get("cache_write_5m", inp * table.get("cache_write_5m_multiplier", 1.25)),
            "cw1": entry.get("cache_write_1h", inp * table.get("cache_write_1h_multiplier", 2.0)),
        }

    def _bedrock(self, base, scope, row):
        table = self.providers.get("bedrock") or {}
        regions = table.get("regions") or {}
        wanted = self.cfg.get("bedrock_region") or row.get("region") or table.get("default_region")
        order = [wanted] if wanted in regions else []
        if wanted not in regions:
            self.assumptions.add(
                "No Bedrock prices for region %s; used %s. Add it with update_pricing.py --region."
                % (wanted or "(not recorded)", table.get("default_region")))
        order += [r for r in [table.get("default_region")] + sorted(regions) if r in regions and r not in order]
        for region in order:
            models = regions[region].get("models") or {}
            name = longest_prefix(models, base)
            if not name:
                continue
            if region != order[0] and wanted in regions:
                self.assumptions.add("%s is not priced in %s; used the %s price." % (name, wanted, region))
            scope = scope or row.get("scope") or self.cfg.get("bedrock_scope")
            if not scope:
                scope = "regional"
                self.assumptions.add(
                    "Some Bedrock usage did not say whether it ran on a global or a regional "
                    "inference profile; priced as regional (the higher rate). Set bedrock_scope "
                    "in .enabler/kpi/config.json if the project uses global profiles.")
            entry = models[name].get(scope)
            if entry is None:
                other = "global" if scope == "regional" else "regional"
                entry = models[name].get(other)
                self.assumptions.add("%s has no %s price in %s; used its %s price."
                                     % (name, scope, region, other))
                scope = other
            if entry is None:
                continue
            return self._rates(entry, table), "bedrock · %s · %s" % (order[0], scope), 1.0
        return None

    def _flat(self, provider, base, row):
        table = self.providers.get(provider) or {}
        label = provider
        if not table.get("models"):
            fallback = table.get("fallback") or self.data.get("default_provider") or "anthropic"
            if provider != fallback:
                label = "%s (priced as %s)" % (provider, fallback)
                self.assumptions.add("No price table for provider '%s'; priced with the %s table."
                                     % (provider, fallback))
            table = self.providers.get(fallback) or {}
        models = table.get("models") or {}
        name = longest_prefix(models, base)
        if not name:
            return None
        fast = 1.0
        if row.get("speed") == "fast":
            fast = models[name].get("fast_multiplier", table.get("fast_multiplier", 1.0))
        return self._rates(models[name], table), label, fast

    def cost(self, row):
        """(usd, price basis) for one usage row; (None, basis) when unpriced."""
        raw = row.get("model") or ""
        raw = (self.cfg.get("model_aliases") or {}).get(raw, raw)
        base, scope, bedrock_shaped = parse_model(raw)
        provider = (self.cfg.get("provider") or row.get("provider")
                    or ("bedrock" if bedrock_shaped else None)
                    or self.data.get("default_provider") or "anthropic")
        if provider == "foundry":
            provider = "anthropic"   # Foundry bills at Anthropic list prices
        found = self._bedrock(base, scope, row) if provider == "bedrock" else self._flat(provider, base, row)
        if not found:
            self.unpriced[raw] += sum(row.get(f, 0) for f in TOKEN_FIELDS)
            return None, provider + " · unpriced"
        rates, label, factor = found
        usd = sum(row.get(f, 0) * rates[f] for f in TOKEN_FIELDS) / 1e6
        return usd * factor * float(self.cfg.get("cost_multiplier", 1.0)), label

    def describe(self):
        parts = []
        for name, table in sorted(self.providers.items()):
            if table.get("updated"):
                parts.append("%s prices dated %s" % (name, table["updated"]))
        return "; ".join(parts) or "undated prices"


# ------------------------------------------------------------------ loading

def find_default_kpi_dir():
    d = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    while True:
        cand = os.path.join(d, ".enabler", "kpi")
        if os.path.isdir(cand):
            return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def parse_day(value, end=False):
    if not value:
        return None
    dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return dt.timestamp() + (86400 if end else 0)


def load_events(kpi_dirs, since, until, user, ticket):
    events, files = [], 0
    for kd in kpi_dirs:
        root = os.path.join(kd, "events")
        for dirpath, _dirs, names in os.walk(root):
            for name in sorted(names):
                if not name.endswith(".jsonl"):
                    continue
                files += 1
                with open(os.path.join(dirpath, name), encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        try:
                            e = json.loads(line)
                        except ValueError:
                            continue
                        t = e.get("t")
                        if not isinstance(t, (int, float)):
                            continue
                        if since and t < since or until and t >= until:
                            continue
                        if user and e.get("user") != user:
                            continue
                        if ticket and e.get("ticket") != ticket:
                            continue
                        events.append(e)
    events.sort(key=lambda e: e["t"])
    return events, files


# ---------------------------------------------------------------- aggregate

class Group:
    """KPI accumulator for one slice (overall, a user, a ticket, a day...)."""

    def __init__(self):
        self.sessions, self.users, self.tickets, self.days = set(), set(), set(), set()
        self.files = set()
        self.n = Counter()          # plain counters
        self.sec = Counter()        # durations in seconds
        self.tok = Counter()        # token counters
        self.cost = 0.0
        self.cost_by = defaultdict(Counter)   # dimension -> name -> usd
        self.tok_by = defaultdict(lambda: defaultdict(Counter))
        self.skills, self.agents, self.commands = Counter(), Counter(), Counter()
        self.first = self.last = None

    def touch(self, e):
        self.sessions.add(e.get("sid"))
        if e.get("user"):
            self.users.add(e["user"])
        if e.get("ticket"):
            self.tickets.add(e["ticket"])
        self.days.add(e["ts"][:10])
        t = e["t"]
        self.first = t if self.first is None else min(self.first, t)
        self.last = t if self.last is None else max(self.last, t)

    # Derived figures ---------------------------------------------------

    @property
    def human_prompts(self):
        return self.n["prompt_human"] + self.n["prompt_command"]

    @property
    def interactions(self):
        return (self.human_prompts + self.n["permissions"] + self.n["questions"]
                + self.n["interrupts"])

    @property
    def human_s(self):
        return self.sec["wait"] + self.sec["think"]

    @property
    def engaged_s(self):
        return self.sec["ai"] + self.human_s

    def ratio(self, a, b):
        return (a / b) if b else None

    def summary(self):
        tokens = sum(self.tok[f] for f in TOKEN_FIELDS)
        return {
            "sessions": len(self.sessions), "users": len(self.users),
            "tickets": len(self.tickets), "active_days": len(self.days),
            "first_event": iso(self.first), "last_event": iso(self.last),
            "human_prompts": self.n["prompt_human"], "commands": self.n["prompt_command"],
            "system_turns": self.n["prompt_system"], "turns": self.n["turns"],
            "permission_prompts": self.n["permissions"], "permission_denials": self.n["denials"],
            "questions_answered": self.n["questions"], "interrupts": self.n["interrupts"],
            "human_interactions": self.interactions,
            "ai_seconds": round(self.sec["ai"]), "human_wait_seconds": round(self.sec["wait"]),
            "human_think_seconds": round(self.sec["think"]),
            "human_seconds": round(self.human_s), "engaged_seconds": round(self.engaged_s),
            "away_gaps": self.n["away_gaps"],
            "ai_share_of_engaged_time": self.ratio(self.sec["ai"], self.engaged_s),
            "tool_calls": self.n["tools"], "tool_failures": self.n["tool_failures"],
            "tool_calls_per_human_prompt": self.ratio(self.n["tools"], self.human_prompts),
            "ai_seconds_per_human_prompt": self.ratio(self.sec["ai"], self.human_prompts),
            "skill_runs": sum(self.skills.values()), "subagent_runs": sum(self.agents.values()),
            "subagent_seconds": round(self.sec["subagent"]), "compactions": self.n["compactions"],
            "files_touched": len(self.files), "lines_added": self.n["added"],
            "lines_removed": self.n["removed"], "commits": self.n["commits"],
            "pushes": self.n["pushes"], "pull_requests": self.n["prs"],
            "tokens_input": self.tok["in"], "tokens_output": self.tok["out"],
            "tokens_cache_read": self.tok["cr"],
            "tokens_cache_write": self.tok["cw5"] + self.tok["cw1"],
            "tokens_total": tokens, "cost_usd": round(self.cost, 4),
            "cost_usd_per_ticket": self.ratio(self.cost, len(self.tickets)),
            "cost_usd_per_ai_hour": self.ratio(self.cost, self.sec["ai"] / 3600.0),
        }


def aggregate(events, pricing, idle_cap):
    overall = Group()
    dims = {k: defaultdict(Group) for k in ("user", "ticket", "day", "session")}
    session_meta = {}

    def groups(e):
        return (overall, dims["user"][e.get("user") or "unknown"],
                dims["ticket"][e.get("ticket") or NO_TICKET],
                dims["day"][e["ts"][:10]], dims["session"][e.get("sid")])

    # The ticket is often named only in the first prompt: what a session did
    # before that (its start, a first question) belongs to the same ticket.
    first_ticket = {}
    for e in events:
        if e.get("ticket"):
            first_ticket.setdefault(e.get("sid"), e["ticket"])
    for e in events:
        if not e.get("ticket") and e.get("sid") in first_ticket:
            e["ticket"] = first_ticket[e["sid"]]

    for e in events:
        ev = e.get("ev")
        gs = groups(e)
        for g in gs:
            g.touch(e)
        meta = session_meta.setdefault(e.get("sid"), {"user": e.get("user"), "tickets": set()})
        if e.get("ticket"):
            meta["tickets"].add(e["ticket"])
        if ev == "session_start":
            meta.setdefault("project", e.get("project"))
            meta.setdefault("branch", e.get("branch"))
        costs = [pricing.cost(row) for row in e.get("rows") or []] if ev == "usage" else []
        for g in gs:
            if ev == "prompt":
                kind = e.get("kind") or "human"
                g.n["prompt_" + kind] += 1
                if kind == "command" and e.get("command"):
                    g.commands[e["command"]] += 1
                idle = e.get("idle_s")
                if kind != "system" and isinstance(idle, (int, float)):
                    if idle <= idle_cap:
                        g.sec["think"] += idle
                    else:
                        # The person was away; count the cap, not the absence.
                        g.sec["think"] += idle_cap
                        g.n["away_gaps"] += 1
            elif ev == "turn":
                g.n["turns"] += 1
                g.sec["ai"] += e.get("ai_s") or 0
                g.sec["wait"] += e.get("wait_s") or 0
            elif ev == "tool":
                g.n["tools"] += 1
                if e.get("failed"):
                    g.n["tool_failures"] += 1
                if e.get("interrupt"):
                    g.n["interrupts"] += 1
                if e.get("question"):
                    g.n["questions"] += 1
                if e.get("skill"):
                    g.skills[e["skill"]] += 1
                if e.get("file"):
                    g.files.add(e["file"])
                g.n["added"] += e.get("added") or 0
                g.n["removed"] += e.get("removed") or 0
                if e.get("git") == "commit":
                    g.n["commits"] += 1
                elif e.get("git") == "push":
                    g.n["pushes"] += 1
                if e.get("pr"):
                    g.n["prs"] += 1
            elif ev == "permission":
                g.n["permissions"] += 1
            elif ev == "permission_denied":
                g.n["denials"] += 1
            elif ev == "subagent":
                g.agents[e.get("agent") or "subagent"] += 1
                g.sec["subagent"] += e.get("dur_s") or 0
            elif ev == "compact":
                g.n["compactions"] += 1
            elif ev == "usage":
                for row, (usd, basis) in zip(e.get("rows") or [], costs):
                    for f in TOKEN_FIELDS:
                        g.tok[f] += row.get(f, 0)
                    scope = "main session" if row.get("agent") == "main" else "subagents"
                    for dim, name in (("model", row.get("model")), ("skill", row.get("skill")),
                                      ("agent", row.get("agent")), ("scope", scope),
                                      ("pricing", basis)):
                        for f in TOKEN_FIELDS:
                            g.tok_by[dim][name][f] += row.get(f, 0)
                        if usd is not None:
                            g.cost_by[dim][name] += usd
                    if usd is not None:
                        g.cost += usd
    return overall, dims, session_meta


# --------------------------------------------------------------- formatting

def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def dur(seconds):
    s = int(round(seconds or 0))
    if s < 60:
        return "%ds" % s
    if s < 3600:
        return "%dm %02ds" % (s // 60, s % 60)
    return "%dh %02dm" % (s // 3600, (s % 3600) // 60)


def money(v):
    if v is None:
        return "–"
    return "$%.2f" % v if v >= 0.995 or v == 0 else "$%.3f" % v


def num(v, digits=0):
    if v is None:
        return "–"
    if isinstance(v, float) and digits:
        return ("%." + str(digits) + "f") % v
    return "{:,}".format(int(round(v)))


def pct(v):
    return "–" if v is None else "%d%%" % round(v * 100)


def build_sections(overall, dims, session_meta, pricing, args, n_files):
    """The report as data: a list of sections, each a table. Both the Markdown
    and the HTML renderer print this same structure."""
    s = overall.summary()
    sections = []

    def table(title, note, headers, rows, bar=None):
        sections.append({"title": title, "note": note, "headers": headers, "rows": rows,
                         "bar": bar})

    table("Headline", "One row per KPI family. Details follow.", ["KPI", "Value"], [
        ["Sessions · users · tickets · active days",
         "%s · %s · %s · %s" % (s["sessions"], s["users"], s["tickets"], s["active_days"])],
        ["AI working time", dur(s["ai_seconds"])],
        ["Human time (waiting on approvals and questions + thinking between turns)",
         dur(s["human_seconds"])],
        ["Human interactions", num(s["human_interactions"])],
        ["Tool calls per human prompt (autonomy)", num(s["tool_calls_per_human_prompt"], 1)],
        ["Lines written by the AI (added / removed)",
         "+%s / −%s in %s files" % (num(s["lines_added"]), num(s["lines_removed"]),
                                    num(s["files_touched"]))],
        ["Total cost (published prices)", money(overall.cost)],
        ["Cost per ticket", money(s["cost_usd_per_ticket"])],
    ])

    table("Time",
          "AI working time is the sum of turn durations minus the time a turn spent blocked on "
          "a person. Human waiting is that blocked time. Human thinking is the gap between the "
          "end of a turn and the next prompt, counted up to the idle cap (%s); longer gaps are "
          "treated as the person being away." % dur(args.idle_cap),
          ["Measure", "Value", "Share of engaged time"], [
              ["AI working", dur(overall.sec["ai"]), pct(overall.ratio(overall.sec["ai"], overall.engaged_s))],
              ["Human waiting (approvals, questions)", dur(overall.sec["wait"]),
               pct(overall.ratio(overall.sec["wait"], overall.engaged_s))],
              ["Human thinking (between turns, capped)", dur(overall.sec["think"]),
               pct(overall.ratio(overall.sec["think"], overall.engaged_s))],
              ["Engaged time (sum of the above)", dur(overall.engaged_s), "100%"],
              ["Gaps longer than the idle cap", num(s["away_gaps"]), ""],
              ["Subagent run time (inside AI working time, may overlap)",
               dur(overall.sec["subagent"]), ""],
              ["AI working time per human prompt", dur(s["ai_seconds_per_human_prompt"] or 0), ""],
          ])

    table("Human interaction",
          "Every point where a person acted. Fewer interactions per ticket and more tool calls "
          "per prompt mean the machine is doing more of the work unattended.",
          ["Interaction", "Count"], [
              ["Free-text prompts", num(s["human_prompts"])],
              ["Slash commands", num(s["commands"])],
              ["Permission prompts answered", num(s["permission_prompts"])],
              ["Permission denials", num(s["permission_denials"])],
              ["Questions answered (AskUserQuestion)", num(s["questions_answered"])],
              ["Tool calls interrupted", num(s["interrupts"])],
              ["Total human interactions", num(s["human_interactions"])],
              ["Turns started by the system (background task notifications)", num(s["system_turns"])],
              ["Tool calls", num(s["tool_calls"])],
              ["Tool failures", num(s["tool_failures"])],
              ["Context compactions", num(s["compactions"])],
          ])

    def cost_rows(dim):
        rows = []
        names = set(overall.tok_by[dim]) | set(overall.cost_by[dim])
        for name in sorted(names, key=lambda k: -overall.cost_by[dim].get(k, 0)):
            t = overall.tok_by[dim][name]
            usd = overall.cost_by[dim].get(name)
            rows.append([name or "-", num(t["in"]), num(t["out"]), num(t["cr"]),
                         num(t["cw5"] + t["cw1"]), money(usd),
                         overall.ratio(usd or 0, overall.cost) or 0])
        return rows

    tok_headers = ["", "Input", "Output", "Cache read", "Cache write", "Cost", "Share"]
    price_note = ("Tokens are read from the session transcripts; cost is tokens × the price "
                  "table %s (%s; %s per million tokens)."
                  % (os.path.basename(pricing.source or "?"), pricing.describe(),
                     pricing.data.get("currency", "USD")))
    mult = float(pricing.cfg.get("cost_multiplier", 1.0))
    if mult != 1.0:
        price_note += " A cost multiplier of %s from the project configuration is applied." % mult
    if pricing.unpriced:
        price_note += (" Not priced, model missing from the table: "
                       + ", ".join("%s (%s tokens)" % (m, num(n)) for m, n in pricing.unpriced.items())
                       + ".")
    table("Cost by price basis",
          "Which price table each part of the cost was computed with. "
          + (" ".join(sorted(pricing.assumptions)) or "No assumptions were needed."),
          ["Provider · region · scope"] + tok_headers[1:], cost_rows("pricing"), bar=6)
    table("Cost by model", price_note, ["Model"] + tok_headers[1:], cost_rows("model"), bar=6)
    table("Cost by skill",
          "Usage attributed to the skill that was active when the tokens were spent; "
          "'-' is work outside any skill.", ["Skill"] + tok_headers[1:], cost_rows("skill"), bar=6)
    table("Cost by agent", "The main conversation versus each subagent type.",
          ["Agent"] + tok_headers[1:], cost_rows("agent"), bar=6)

    def dim_rows(groups, order):
        rows = []
        for name in order:
            g = groups[name]
            rows.append([name, num(len(g.sessions)), num(g.human_prompts), num(g.interactions),
                         dur(g.sec["ai"]), dur(g.human_s), num(g.n["tools"]),
                         "+%s/−%s" % (num(g.n["added"]), num(g.n["removed"])),
                         money(g.cost), overall.ratio(g.cost, overall.cost) or 0])
        return rows

    dim_headers = ["Sessions", "Prompts", "Interactions", "AI time", "Human time", "Tool calls",
                   "Lines", "Cost", "Share"]
    by_cost = lambda groups: sorted(groups, key=lambda k: -groups[k].cost)
    table("By ticket", "A session is attributed to the last ticket key seen in a prompt, a "
          "skill argument or the branch name.",
          ["Ticket"] + dim_headers, dim_rows(dims["ticket"], by_cost(dims["ticket"])), bar=9)
    table("By user", None, ["User"] + dim_headers,
          dim_rows(dims["user"], by_cost(dims["user"])), bar=9)
    table("By day", "Days are UTC.", ["Day"] + dim_headers,
          dim_rows(dims["day"], sorted(dims["day"])), bar=9)

    table("Output", "Counted from the AI's own tool calls: what a person typed in their "
          "editor is not seen and not counted.", ["Measure", "Value"], [
              ["Files written or edited by the AI", num(s["files_touched"])],
              ["Lines added / removed", "+%s / −%s" % (num(s["lines_added"]), num(s["lines_removed"]))],
              ["Commits · pushes · pull requests",
               "%s · %s · %s" % (s["commits"], s["pushes"], s["pull_requests"])],
              ["Skill runs", ", ".join("%s ×%d" % kv for kv in overall.skills.most_common(12)) or "–"],
              ["Slash commands", ", ".join("/%s ×%d" % kv for kv in overall.commands.most_common(12)) or "–"],
              ["Subagent runs", ", ".join("%s ×%d" % kv for kv in overall.agents.most_common(12)) or "–"],
          ])

    top = sorted(dims["session"], key=lambda k: -dims["session"][k].cost)[:25]
    rows = []
    for sid in top:
        g, meta = dims["session"][sid], session_meta.get(sid, {})
        rows.append([(iso(g.first) or "")[:16].replace("T", " "), meta.get("user") or "",
                     ", ".join(sorted(meta.get("tickets") or [])) or "–", num(g.human_prompts),
                     dur(g.sec["ai"]), dur((g.last or 0) - (g.first or 0)), money(g.cost),
                     str(sid)[:8]])
    table("Sessions (top 25 by cost)", "Wall clock is first to last event, pauses included.",
          ["Started (UTC)", "User", "Tickets", "Prompts", "AI time", "Wall clock", "Cost",
           "Session"], rows)
    return sections


def render_md(sections, header):
    out = ["# AI usage KPI report", ""]
    out += ["%s: %s  " % kv for kv in header] + [""]
    for sec in sections:
        out += ["## " + sec["title"], ""]
        if sec["note"]:
            out += [sec["note"], ""]
        if not sec["rows"]:
            out += ["_No data._", ""]
            continue
        out.append("| " + " | ".join(h or " " for h in sec["headers"]) + " |")
        out.append("|" + "|".join(["---"] * len(sec["headers"])) + "|")
        for row in sec["rows"]:
            cells = [pct(c) if i == sec["bar"] else str(c) for i, c in enumerate(row)]
            out.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
        out.append("")
    out += ["## How to read this report", "",
            "- Everything except cost is measured from hook events; nothing is self-reported.",
            "- Cost is tokens at the provider's published on-demand price (see 'Cost by price "
            "basis' for the table used and the assumptions made). It is not the invoice: "
            "discounts, commitments, service tiers and taxes are outside it.",
            "- Human time is an estimate of attention, not of effort: it does not see reading "
            "code in the editor, meetings about the ticket, or manual edits.",
            "- Interruptions with Esc while the model is generating text are not exposed to "
            "hooks; only interrupted tool calls are counted.",
            "- No prompt text, model output, file content or command line is stored.", ""]
    return "\n".join(out)


CSS = """
:root{--bg:#fbfaf7;--fg:#1d1c1a;--muted:#6b6862;--line:#e3e0d8;--card:#ffffff;--bar:#3f6fb5}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#17171a;--fg:#ecebe7;
--muted:#a09d96;--line:#2e2e33;--card:#1f1f23;--bar:#7ea6e0}}
:root[data-theme="dark"]{--bg:#17171a;--fg:#ecebe7;--muted:#a09d96;--line:#2e2e33;--card:#1f1f23;--bar:#7ea6e0}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1080px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:18px;margin:36px 0 6px}
.meta,.note{color:var(--muted);font-size:13px;max-width:75ch}.note{margin:0 0 10px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:24px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:14px}
.tile b{display:block;font-size:24px;font-variant-numeric:tabular-nums}
.tile span{color:var(--muted);font-size:12px}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{padding:7px 10px;text-align:left;border-bottom:1px solid var(--line);white-space:nowrap}
td:first-child{white-space:normal}th{color:var(--muted);font-weight:600;font-size:12px}
tr:last-child td{border-bottom:0}.bar{display:inline-block;height:8px;border-radius:4px;
background:var(--bar);vertical-align:middle;margin-right:6px}
"""


def render_html(sections, header, tiles):
    e = html.escape
    out = ["<!doctype html><html lang='en'><head><meta charset='utf-8'>",
           "<meta name='viewport' content='width=device-width,initial-scale=1'>",
           "<title>AI usage KPIs</title><style>%s</style></head><body><main>" % CSS,
           "<h1>AI usage KPI report</h1>",
           "<p class='meta'>%s</p>" % " · ".join("%s: %s" % (e(k), e(str(v))) for k, v in header),
           "<div class='tiles'>"]
    out += ["<div class='tile'><b>%s</b><span>%s</span></div>" % (e(v), e(k)) for k, v in tiles]
    out.append("</div>")
    for sec in sections:
        out.append("<h2>%s</h2>" % e(sec["title"]))
        if sec["note"]:
            out.append("<p class='note'>%s</p>" % e(sec["note"]))
        if not sec["rows"]:
            out.append("<p class='note'>No data.</p>")
            continue
        out.append("<div class='wrap'><table><thead><tr>%s</tr></thead><tbody>"
                   % "".join("<th>%s</th>" % e(h) for h in sec["headers"]))
        for row in sec["rows"]:
            cells = []
            for i, c in enumerate(row):
                if i == sec["bar"]:
                    cells.append("<td><span class='bar' style='width:%dpx'></span>%s</td>"
                                 % (max(1, round(c * 90)), pct(c)))
                else:
                    cells.append("<td>%s</td>" % e(str(c)))
            out.append("<tr>%s</tr>" % "".join(cells))
        out.append("</tbody></table></div>")
    out.append("</main></body></html>")
    return "\n".join(out)


def write_csv(path, groups, key_name, extra=None):
    names = sorted(groups)
    if not names:
        return
    fields = [key_name] + (list(extra(names[0])) if extra else []) + list(groups[names[0]].summary())
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for name in names:
            row = {key_name: name}
            if extra:
                row.update(extra(name))
            row.update(groups[name].summary())
            w.writerow(row)


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="KPI report from ai-enabler-kpi hook events.")
    ap.add_argument("--kpi-dir", action="append",
                    help="KPI directory (.enabler/kpi). Repeat to merge several projects.")
    ap.add_argument("--since", help="First day to include, YYYY-MM-DD (UTC).")
    ap.add_argument("--until", help="Last day to include, YYYY-MM-DD (UTC).")
    ap.add_argument("--user")
    ap.add_argument("--ticket")
    ap.add_argument("--idle-cap", type=int, default=None,
                    help="Longest gap between turns counted as thinking, in seconds (default 600).")
    ap.add_argument("--pricing", help="Price table JSON; overrides the bundled one.")
    ap.add_argument("--provider", choices=["anthropic", "bedrock", "vertex", "foundry"],
                    help="Price every row as this provider, whatever was recorded.")
    ap.add_argument("--bedrock-region", help="Region whose Bedrock prices to use.")
    ap.add_argument("--bedrock-scope", choices=["global", "regional"],
                    help="Inference profile scope to assume when the model id does not say.")
    ap.add_argument("--out-dir", help="Where to write the report files.")
    ap.add_argument("--quiet", action="store_true", help="Do not print the Markdown report.")
    args = ap.parse_args()

    kpi_dirs = args.kpi_dir or [d for d in [os.environ.get("ENABLER_KPI_DIR"),
                                             find_default_kpi_dir()] if d][:1]
    if not kpi_dirs:
        sys.exit("No KPI directory found. Run /ai-enabler-kpi:kpi-init in the project, "
                 "or pass --kpi-dir.")
    cfg = {}
    try:
        with open(os.path.join(kpi_dirs[0], "config.json"), encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        pass
    if args.idle_cap is None:
        args.idle_cap = int(cfg.get("idle_cap_seconds", 600))

    for key, value in (("provider", args.provider), ("bedrock_region", args.bedrock_region),
                       ("bedrock_scope", args.bedrock_scope)):
        if value:
            cfg[key] = value
    pricing = Pricing([args.pricing, os.path.join(kpi_dirs[0], "pricing.json"),
                       os.path.join(HERE, "pricing.json")], cfg)
    events, n_files = load_events(kpi_dirs, parse_day(args.since),
                                  parse_day(args.until, end=True), args.user, args.ticket)
    if not events:
        sys.exit("No events in %s for the selected filters (%d session files read). "
                 "Capture starts with the first session after kpi-init." %
                 (", ".join(kpi_dirs), n_files))

    overall, dims, session_meta = aggregate(events, pricing, args.idle_cap)
    s = overall.summary()
    period = "%s to %s" % (s["first_event"][:10], s["last_event"][:10])
    filters = ", ".join("%s=%s" % (k, v) for k, v in
                        (("user", args.user), ("ticket", args.ticket)) if v) or "none"
    header = [("Period", period), ("Filters", filters),
              ("Source", ", ".join(kpi_dirs)),
              ("Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))]
    sections = build_sections(overall, dims, session_meta, pricing, args, n_files)
    tiles = [("Total cost (published prices)", money(overall.cost)),
             ("AI working time", dur(overall.sec["ai"])),
             ("Human time", dur(overall.human_s)),
             ("Human interactions", num(s["human_interactions"])),
             ("Tool calls per prompt", num(s["tool_calls_per_human_prompt"], 1)),
             ("Tickets", num(s["tickets"])),
             ("Cost per ticket", money(s["cost_usd_per_ticket"])),
             ("Lines added by AI", num(s["lines_added"]))]

    out_dir = args.out_dir or os.path.join(
        kpi_dirs[0], "reports", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    os.makedirs(out_dir, exist_ok=True)
    md = render_md(sections, header)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as fh:
        fh.write(md)
    with open(os.path.join(out_dir, "report.html"), "w", encoding="utf-8") as fh:
        fh.write(render_html(sections, header, tiles))
    with open(os.path.join(out_dir, "kpi.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "period": period, "filters": {"user": args.user, "ticket": args.ticket},
            "idle_cap_seconds": args.idle_cap,
            "pricing": {"source": pricing.source, "tables": pricing.describe(),
                        "assumptions": sorted(pricing.assumptions),
                        "cost_multiplier": float(cfg.get("cost_multiplier", 1.0)),
                        "unpriced_tokens": dict(pricing.unpriced)},
            "overall": s,
            "cost_by": {d: {k: round(v, 4) for k, v in c.items()}
                        for d, c in overall.cost_by.items()},
            "by_ticket": {k: g.summary() for k, g in dims["ticket"].items()},
            "by_user": {k: g.summary() for k, g in dims["user"].items()},
            "by_day": {k: g.summary() for k, g in dims["day"].items()},
        }, fh, indent=2)
    write_csv(os.path.join(out_dir, "tickets.csv"), dims["ticket"], "ticket")
    write_csv(os.path.join(out_dir, "users.csv"), dims["user"], "user")
    write_csv(os.path.join(out_dir, "daily.csv"), dims["day"], "day")
    write_csv(os.path.join(out_dir, "sessions.csv"), dims["session"], "session",
              extra=lambda sid: {"user": session_meta.get(sid, {}).get("user"),
                                 "ticket_keys": " ".join(sorted(session_meta.get(sid, {}).get("tickets") or []))})
    if not args.quiet:
        print(md)
    print("Report files written to %s" % out_dir, file=sys.stderr)


if __name__ == "__main__":
    main()
