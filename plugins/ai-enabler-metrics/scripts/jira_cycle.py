#!/usr/bin/env python3
"""Jira cycle time, backward moves and blocking for Scrum or opt-in Kanban.

    jira_cycle.py [--project KEY] [--mode scrum|kanban] [--sprints N]
                  [--board ID | --filter ID] [--since DATE --until DATE]
                  [--group-by week|month] [--input DIR] [--metrics-dir DIR] [--out-dir DIR]

Two ways to get the data, both ending in the same deterministic computation:

1. Directly from Jira's REST API, when the environment has JIRA_URL and either
   JIRA_PERSONAL_TOKEN (Data Center) or JIRA_USERNAME + JIRA_API_TOKEN (Cloud).
   These are the variables the `mcp-atlassian` server uses, so a machine set up
   for it needs nothing more. Read-only; the token is never written anywhere.
2. From files (`--input DIR`): `sprints.json` plus issues with their changelog,
   saved there by whoever can read Jira (for example the metrics-jira-collector agent
   through an MCP server). See references/jira-input.md of the metrics-cycle-time skill.

Writes <metrics-dir>/delivery/cycle-time.json and an HTML report with charts.
"""

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import charts as C                      # noqa: E402
import delivery_lib as L                # noqa: E402

FLAP_SECONDS = 60


# ---------------------------------------------------------------------- REST

class Jira:
    def __init__(self, connection=None, profile=None):
        if profile:
            connection = L.validate_connection(connection) if connection is not None else {}
            self.base = connection.get("url", "")
            token = os.environ.get(connection.get("personal_token_env", ""))
            user = os.environ.get(connection.get("username_env", ""))
            api_token = os.environ.get(connection.get("api_token_env", ""))
        else:
            self.base = (os.environ.get("JIRA_URL") or "").rstrip("/")
            token = os.environ.get("JIRA_PERSONAL_TOKEN")
            user, api_token = os.environ.get("JIRA_USERNAME"), os.environ.get("JIRA_API_TOKEN")
        if token:
            self.auth = "Bearer " + token
        elif user and api_token:
            self.auth = "Basic " + base64.b64encode(("%s:%s" % (user, api_token)).encode()).decode()
        else:
            self.auth = None

    @property
    def available(self):
        return bool(self.base and self.auth)

    def check_url(self):
        u = urllib.parse.urlparse(self.base)
        if u.username or u.password or u.query or u.fragment:
            raise RuntimeError("JIRA_URL must not contain credentials, a query or a fragment.")
        if u.scheme != "https" and u.hostname not in ("localhost", "127.0.0.1", "::1"):
            raise RuntimeError("JIRA_URL must be https (got %s://): the token would travel in clear text."
                               % (u.scheme or "no scheme"))

    def get(self, path, **params):
        url = self.base + path + ("?" + urllib.parse.urlencode(params) if params else "")
        req = urllib.request.Request(url, headers={"Authorization": self.auth, "Accept": "application/json"})
        host = urllib.parse.urlparse(self.base).netloc
        scheme = urllib.parse.urlparse(self.base).scheme

        class SameHost(urllib.request.HTTPRedirectHandler):
            # urllib would resend the Authorization header to wherever a redirect points.
            def redirect_request(self, req_, fp, code, msg, headers, newurl):
                destination = urllib.parse.urlparse(newurl)
                if (destination.netloc != host or destination.scheme != scheme):
                    raise urllib.error.HTTPError(newurl, code, "redirect to another host refused", headers, fp)
                return super().redirect_request(req_, fp, code, msg, headers, newurl)

        try:
            with urllib.request.build_opener(SameHost).open(req, timeout=60) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            raise RuntimeError("Jira answered %s for %s" % (exc.code, path))
        except urllib.error.URLError:
            raise RuntimeError("Jira is not reachable; check its URL, network and TLS configuration.")

    def paged(self, path, key, **params):
        start, out = 0, []
        while True:
            page = self.get(path, startAt=start, maxResults=50, **params)
            items = page.get(key) or []
            if page.get("startAt", start) != start:
                raise RuntimeError("Jira returned an unexpected page offset for %s." % path)
            out += items
            start += len(items)
            total = page.get("total")
            if page.get("isLast") is True and total is not None and start < total:
                raise RuntimeError("Jira ended pagination before the reported total for %s." % path)
            if not items and total is not None and start < total:
                raise RuntimeError("Jira returned an incomplete page for %s." % path)
            if page.get("isLast") is True or (total is not None and start >= total):
                return out
            if not items:
                raise RuntimeError("Jira omitted pagination completeness for %s." % path)

    def complete_history(self, issue):
        """Cloud has paged histories; unsupported DC endpoints remain explicitly incomplete."""
        log = issue.get("changelog") or {}
        histories = log.get("histories") or []
        if log.get("total") is not None and log["total"] == len(histories) and not log.get("startAt"):
            issue["history_complete"] = True
            return issue
        try:
            histories = self.paged("/rest/api/2/issue/%s/changelog" % urllib.parse.quote(issue["key"], safe=""), "values")
            issue["changelog"] = {"histories": histories, "total": len(histories)}
            issue["history_complete"] = True
        except RuntimeError:
            issue["history_complete"] = False
        return issue

    def collect_kanban(self, project, periods, board=None, filter_id=None, group_by="week"):
        self.check_url()
        if not board and not filter_id:
            boards = self.paged("/rest/agile/1.0/board", "values", projectKeyOrId=project, type="kanban")
            if len(boards) != 1:
                raise RuntimeError("Expected one Kanban board for %s, found %d; choose --board or --filter."
                                   % (project, len(boards)))
            board = boards[0]["id"]
        if board:
            # The board's saved filter includes completed tickets hidden by the board UI.
            # Never fall back to a project-wide query if configuration is inaccessible.
            config = self.get("/rest/agile/1.0/board/%s/configuration" % board)
            filter_id = (config.get("filter") or {}).get("id")
            if not filter_id:
                raise RuntimeError("Cannot establish board %s saved-filter scope; collection stopped." % board)
        scope = collection_scope("kanban", project, board, filter_id, periods, group_by)
        # Deliberately broad within the saved filter: no created/resolved LOWER bound.
        # Jira JQL date literals use the account timezone; pad by a day and apply exact
        # UTC overlap in Python. This retains work started long before the window.
        upper = (L.parse_ts(periods[-1]["end"]) + timedelta(days=1)).strftime("%Y-%m-%d")
        jql = 'filter = %s AND created < "%s" ORDER BY key' % (filter_id, upper)
        issues = self.paged("/rest/api/2/search", "issues", jql=jql, expand="changelog",
                            fields="summary,issuetype,status,assignee,created,resolutiondate")
        return [self.complete_history(i) for i in issues], scope

    def collect(self, project, n_sprints, board=None):
        self.check_url()
        if not board:
            boards = self.paged("/rest/agile/1.0/board", "values", projectKeyOrId=project, type="scrum")
            if not boards:
                raise RuntimeError("No scrum board found for project %s; pass --board." % project)
            board = boards[0]["id"]
        closed = self.paged("/rest/agile/1.0/board/%s/sprint" % board, "values", state="closed")
        closed = sorted([s for s in closed if s.get("completeDate") or s.get("endDate")],
                        key=lambda s: s.get("completeDate") or s["endDate"])[-n_sprints:]
        if not closed:
            raise RuntimeError("Board %s has no closed sprint." % board)
        self.scope = {"mode": "scrum", "project": project, "board": str(board), "filter": None,
                      "sprint_ids": [s["id"] for s in closed]}
        issues, seen = [], set()
        for s in closed:
            for it in self.paged("/rest/agile/1.0/board/%s/sprint/%s/issue" % (board, s["id"]), "issues", expand="changelog",
                                 fields="summary,issuetype,status,assignee,created,resolutiondate"):
                if it["key"] not in seen:
                    seen.add(it["key"])
                    issues.append(self.complete_history(it))
        return closed, issues


# --------------------------------------------------------------------- input

def collection_scope(mode, project, board, filter_id, periods, group_by=None):
    return {"mode": mode, "project": project, "board": str(board) if board else None,
            "filter": str(filter_id) if filter_id else None,
            "window": [periods[0]["start"], periods[-1]["end"]],
            "group_by": group_by, "timezone": "UTC", "boundary": "[start,end)",
            "selection": "saved-filter-membership-at-collection; lifetime-overlap"}


def load_collection(path, jira, periods, profile=None, connection=None):
    """Validate the same scope contract for REST exports and MCP/offline data."""
    try:
        with open(os.path.join(path, "collection.json"), encoding="utf-8") as fh:
            meta = json.load(fh)
    except FileNotFoundError:
        if jira["mode"] == "kanban" or profile:
            raise ValueError("collection.json is required for Kanban or a named profile; recollect with scope metadata.")
        return {"mode": "scrum", "project": jira.get("project"), "board": None,
                "requested_board": str(jira["board"]) if jira.get("board") else None,
                "scope_verified": False}, None
    scope = meta.get("scope") or {}
    if scope.get("profile") != profile:
        raise ValueError("collection.json profile does not match the requested profile.")
    if profile:
        if not connection or scope.get("connection_url") != connection["url"]:
            raise ValueError("Profile collection must match the configured connection URL (including context path).")
    for key in ("mode", "project"):
        if scope.get(key) != jira.get(key):
            raise ValueError("collection.json %s does not match the requested scope." % key)
    for key in ("board", "filter"):
        if jira.get(key) and str(scope.get(key)) != str(jira[key]):
            raise ValueError("collection.json %s does not match the requested scope." % key)
    collected = L.parse_ts(meta.get("collected_at"))
    if not collected or meta.get("issues_complete") is not True:
        raise ValueError("collection.json needs collected_at and issues_complete: true; finish collection first.")
    clean = {k: scope[k] for k in ("mode", "project", "board", "filter", "sprint_ids") if k in scope}
    if scope.get("board") is not None and not str(scope["board"]).isdigit():
        raise ValueError("collection.json board must be a numeric ID.")
    if jira["mode"] == "scrum" and (not scope.get("board") or not scope.get("sprint_ids")):
        raise ValueError("Scrum collection metadata needs a board and sprint_ids.")
    if jira["mode"] == "kanban":
        expected = collection_scope("kanban", jira.get("project"), scope.get("board"), scope.get("filter"),
                                    periods, jira["group_by"])
        if not str(scope.get("filter") or "").isdigit():
            raise ValueError("Kanban collection scope needs the resolved saved-filter ID.")
        for key in ("window", "group_by", "timezone", "boundary", "selection"):
            if scope.get(key) != expected[key]:
                raise ValueError("collection.json %s does not match the requested scope." % key)
        clean = expected
    if profile:
        clean.update(profile=profile, connection_url=connection["url"])
    return clean, collected


def load_dir(path):
    sprints, issues = [], []
    for name in sorted(os.listdir(path)):
        if not name.endswith(".json") or name == "collection.json":
            continue
        with open(os.path.join(path, name), encoding="utf-8") as fh:
            data = json.load(fh)
        if name == "sprints.json":
            sprints = data.get("values", data) if isinstance(data, dict) else data
        elif isinstance(data, list):
            issues += data
        elif isinstance(data, dict) and "issues" in data:
            issues += data["issues"]
        elif isinstance(data, dict):
            issues.append(data)
    # The same ticket in two files (overlapping batches, a leftover from an earlier
    # collection) must count once: keep the record with the longest history.
    best = {}
    for it in issues:
        if not isinstance(it, dict) or not it.get("key"):
            raise ValueError("Every issue record needs a nonempty key.")
        key = it["key"]
        size = len(it.get("transitions") or (it.get("changelog") or {}).get("histories") or [])
        if key not in best or size > best[key][0]:
            best[key] = (size, it)
    return sprints, [v[1] for v in best.values()], len(issues) - len(best)


def normalize(issue):
    """One issue, from Jira's REST shape or the compact shape, to plain fields."""
    truncated = False
    if "fields" not in issue:       # compact shape (Jira's own shape always has `fields`)
        trans = [{"at": L.parse_ts(t.get("at")), "from": t.get("from"), "to": t.get("to")}
                 for t in issue["transitions"]]
        out = {"key": issue.get("key"), "type": issue.get("type") or "Unknown",
               "assignee": issue.get("assignee") or "(unassigned)", "status": issue.get("status"),
               "created": L.parse_ts(issue.get("created")), "resolved": L.parse_ts(issue.get("resolved")),
               "summary": issue.get("summary") or ""}
    else:
        f = issue.get("fields") or {}
        trans = []
        log = issue.get("changelog") or {}
        truncated = bool(log.get("startAt") or (log.get("total") and log["total"] > len(log.get("histories") or [])))
        for h in log.get("histories") or []:
            for item in h.get("items") or []:
                if item.get("field") == "status":
                    trans.append({"at": L.parse_ts(h.get("created")), "from": item.get("fromString"),
                                  "to": item.get("toString")})
        out = {"key": issue.get("key"), "type": (f.get("issuetype") or {}).get("name") or "Unknown",
               "assignee": (f.get("assignee") or {}).get("displayName") or "(unassigned)",
               "status": (f.get("status") or {}).get("name"), "created": L.parse_ts(f.get("created")),
               "resolved": L.parse_ts(f.get("resolutiondate")), "summary": f.get("summary") or ""}
    out["transitions"] = sorted([t for t in trans if t["at"]], key=lambda t: t["at"])
    out["truncated"] = truncated or issue.get("history_complete") is False
    out["history_unverified"] = issue.get("history_complete") is not True and (
        "fields" not in issue or "total" not in (issue.get("changelog") or {}))
    return out


# ------------------------------------------------------------------- compute

def analyse(sprints, raw_issues, cfg, now=None):
    now = now or datetime.now(timezone.utc)
    kanban = cfg["jira"].get("mode", "scrum") == "kanban"
    if kanban:
        sprints = L.jira_periods(cfg["jira"], now)
    st = cfg["jira"]["statuses"]
    rank = {}
    for i, group in enumerate(st["order"]):
        for name in ([group] if isinstance(group, str) else group):
            rank[name.lower()] = i
    in_progress = {s.lower() for s in st["in_progress"]}
    blocked = {s.lower() for s in st["blocked"]}
    # "Late" stages are everything after the last in-progress step: a move back from
    # there means finished work was rejected, not that planning changed.
    late_from = max([rank[s] for s in in_progress if s in rank] or [0]) + 1
    parsed, undated = [], []
    for s in sprints:
        start = L.parse_ts(s.get("startDate") or s.get("start"))
        # A sprint is usually closed after its planned end; completeDate is when it really ended.
        end = L.parse_ts(s.get("completeDate") or s.get("endDate") or s.get("end"))
        if not start or not end:
            undated.append(str(s.get("name")))
        else:
            parsed.append({"name": s.get("name") or "sprint", "start": start, "end": end})
    if undated or not parsed:
        raise ValueError("These sprints have no start or end date: %s. Every sprint in sprints.json needs "
                         "startDate and endDate." % (", ".join(undated) or "(none given)"))
    sprints = sorted(parsed, key=lambda s: s["end"])
    seen_names = {}
    for s in sprints:                       # two sprints with one name must not share a bucket
        seen_names[s["name"]] = seen_names.get(s["name"], 0) + 1
        if seen_names[s["name"]] > 1:
            s["name"] = "%s (%d)" % (s["name"], seen_names[s["name"]])
    period_start, period_end = sprints[0]["start"], sprints[-1]["end"]
    unknown = set()
    issues = [normalize(i) for i in raw_issues]
    if kanban:
        # Include all lifetime-overlap candidates, even unresolved or resolved later.
        # A post-window transition retains reopened issues whose old resolution is stale.
        issues = [i for i in issues if (not i["created"] or i["created"] < period_end) and (
            not i["resolved"] or i["resolved"] >= period_start or
            any(t["at"] >= period_start for t in i["transitions"]))]
    for it in issues:
        tr = it["transitions"]
        for t in tr:
            for name in (t["from"], t["to"]):
                if name and name.lower() not in rank and name.lower() not in blocked:
                    unknown.add(name)
        started = next((t["at"] for t in tr if (t["to"] or "").lower() in in_progress), None)
        it["started"] = started
        it["cycle"] = L.business_days(started, it["resolved"]) if started and it["resolved"] and it["resolved"] > started else None
        # Blocked time inside the analysed period: every visit to a blocked status,
        # an open visit running until resolution or now. Time blocked years ago is not this report's.
        days = 0.0
        visits = tr
        if kanban and it["created"]:
            initial = tr[0]["from"] if tr else it["status"]
            visits = [{"at": it["created"], "to": initial}] + tr
        for i, t in enumerate(visits):
            if (t["to"] or "").lower() in blocked:
                until = visits[i + 1]["at"] if i + 1 < len(visits) else (it["resolved"] or now)
                if kanban:
                    until = min(until, period_end, now)
                since = max(t["at"], period_start)
                days += max(0.0, (until - since).total_seconds() / 86400.0)
        it["blocked_days"] = days
        it["still_blocked"] = (it["status"] or "").lower() in blocked
        # Backward moves inside the analysed period. A move undone within a minute — in
        # either direction — is a slip of the hand. A ticket that goes back by way of
        # Blocked (In Test -> Blocked -> In Progress) moved backward too.
        back, last_ranked = [], None
        for i, t in enumerate(tr):
            frm, to = (t["from"] or "").lower(), (t["to"] or "").lower()
            if frm in rank:
                last_ranked = t["from"]
            origin = t["from"] if frm in rank else last_ranked
            a, b = rank.get((origin or "").lower()), rank.get(to)
            in_window = period_start <= t["at"] and (t["at"] < period_end if kanban else t["at"] <= period_end)
            if a is None or b is None or b >= a or not in_window:
                continue
            nxt = tr[i + 1] if i + 1 < len(tr) else None
            prv = tr[i - 1] if i > 0 else None
            if nxt and nxt["to"] == t["from"] and (nxt["at"] - t["at"]).total_seconds() <= FLAP_SECONDS:
                continue
            if prv and prv["from"] == t["to"] and prv["to"] == t["from"] \
                    and (t["at"] - prv["at"]).total_seconds() <= FLAP_SECONDS:
                continue
            back.append({"at": t["at"].isoformat(), "from": origin, "to": t["to"],
                         "via_blocked": frm not in rank, "from_late_stage": a >= late_from})
        it["backward"] = back
        # A ticket resolved between two sprints (after one ended, before the next began)
        # belongs to the sprint that had just ended: that is where the work was done.
        it["sprint"] = None
        if kanban:
            inside = [s for s in sprints if it["resolved"] and s["start"] <= it["resolved"] < s["end"]]
            it["sprint"] = inside[0]["name"] if inside else None
        elif it["resolved"] and period_start <= it["resolved"] <= period_end:
            inside = [s for s in sprints if s["start"] <= it["resolved"] <= s["end"]]
            ended = [s for s in sprints if s["end"] < it["resolved"]]
            it["sprint"] = (inside[0] if inside else ended[-1])["name"]
    resolved = [i for i in issues if i["sprint"]]

    def stats(items):
        s = L.summarize([i["cycle"] for i in items if i["cycle"] is not None], total=len(items))
        rev = sum(1 for i in items if i["backward"])
        lo, hi = L.wilson_ci(rev, len(items))
        s.update({"reverted": rev, "revert_rate": rev / float(len(items)) if items else None,
                  "revert_lo": lo, "revert_hi": hi,
                  "blocked_days": sum(i["blocked_days"] for i in items),
                  "blocked_tickets": sum(1 for i in items if i["blocked_days"] > 0)})
        return s

    names = [s["name"] for s in sprints]
    by_sprint = {n: stats([i for i in resolved if i["sprint"] == n]) for n in names}
    by_type = {k: stats(v) for k, v in L.group_by(resolved, lambda i: i["type"]).items()}
    by_assignee = {k: stats(v) for k, v in L.group_by(resolved, lambda i: i["assignee"]).items()}
    blocked_rank = sorted([i for i in issues if i["blocked_days"] > 0], key=lambda i: -i["blocked_days"])
    result = {
        "sprints": [{"name": s["name"], "start": s["start"].isoformat(), "end": s["end"].isoformat()} for s in sprints],
        "issues": len(issues), "resolved_in_window": len(resolved),
        "overall": stats(resolved), "by_sprint": by_sprint, "by_type": by_type, "by_assignee": by_assignee,
        "unknown_statuses": sorted(unknown),
        "resolved_outside": sorted(i["key"] for i in issues if i["resolved"] and not i["sprint"]),
        "truncated_changelogs": sorted(i["key"] for i in issues if i.get("truncated")),
        "no_cycle": [i["key"] for i in resolved if i["cycle"] is None],
        "reverted": [{"key": i["key"], "type": i["type"], "sprint": i["sprint"], "assignee": i["assignee"],
                      "moves": i["backward"]} for i in resolved if i["backward"]],
        "blocked": [{"key": i["key"], "type": i["type"], "status": i["status"], "assignee": i["assignee"],
                     "days": i["blocked_days"], "still_blocked": i["still_blocked"],
                     "bucket": i["sprint"] or "open"} for i in blocked_rank],
        "longest": [{"key": i["key"], "type": i["type"], "assignee": i["assignee"], "cycle": i["cycle"],
                     "sprint": i["sprint"]} for i in sorted([i for i in resolved if i["cycle"] is not None],
                                                             key=lambda i: -i["cycle"])[:10]],
    }
    if kanban:
        result.update({"mode": "kanban", "period_kind": cfg["jira"]["group_by"],
                       "periods": result.pop("sprints"), "by_period": result.pop("by_sprint"),
                       "window": [period_start.isoformat(), period_end.isoformat()],
                       "boundary": "[start,end)", "timezone": "UTC",
                       "unverified_changelogs": sorted(i["key"] for i in issues if i["history_unverified"]),
                       "blocked_now": [{"key": i["key"], "status": i["status"]} for i in issues if i["still_blocked"]],
                       "blocking_observed_at": now.isoformat()})
        for key in ("reverted", "longest"):
            for item in result[key]:
                item["period"] = item.pop("sprint")
    return result


# -------------------------------------------------------------------- render

def fmt(v, unit, digits=1):
    return "–" if v is None else ("%s %s" % (C.fmt_num(v, digits), unit)).strip()


def pct(v):
    return "–" if v is None else "%d %%" % round(v * 100)


def render(r, project, cfg):
    o = r["overall"]
    show = cfg["show_people"]
    periods, by_period, kind = L.cycle_periods(r)
    kanban = r.get("mode") == "kanban"
    names = [s["name"] for s in periods]
    now_blocked = len(r.get("blocked_now", [])) if kanban else sum(1 for b in r["blocked"] if b["still_blocked"])
    scope_note = ("Kanban · %s buckets · [start, end), UTC · board %s · filter %s"
                  % (kind, r.get("scope", {}).get("board") or "—", r.get("scope", {}).get("filter") or "—")) if kanban else "%d closed sprints: %s" % (len(names), ", ".join(names))

    def row(name, s):
        ci = "–" if s["ci_lo"] is None else "%s – %s days" % (C.fmt_num(s["ci_lo"], 1), C.fmt_num(s["ci_hi"], 1))
        return [name, "%d tickets" % s["total"], "%d tickets" % s["n"], pct(s["coverage"]),
                fmt(s["median"], "days"), fmt(s["mean"], "days"), ci,
                "%d tickets" % s["reverted"], pct(s["revert_rate"]), fmt(s["blocked_days"], "days"),
                ", ".join(s["flags"])]

    cols = ["", "Resolved", "With cycle time", "Coverage", "Median cycle time", "Mean", "90 % CI of median",
            "Moved backward", "Backward rate", "Blocked time", "Flags"]
    num = tuple(range(1, 10))

    def pts(order, table_, value="median", lo="ci_lo", hi="ci_hi", scale=1.0):
        return [{"label": k, "value": None if table_[k][value] is None else table_[k][value] * scale,
                 "lo": None if table_[k][lo] is None else table_[k][lo] * scale,
                 "hi": None if table_[k][hi] is None else table_[k][hi] * scale,
                 "low": table_[k]["low"], "n": "n=%d" % (table_[k]["n"] if value == "median" else table_[k]["total"])}
                for k in order]

    types = sorted(r["by_type"], key=lambda k: -r["by_type"][k]["n"])
    people = sorted(r["by_assignee"], key=lambda k: -(r["by_assignee"][k]["median"] or 0))
    late = sum(1 for t in r["reverted"] if any(m["from_late_stage"] for m in t["moves"]))
    blocked_total = sum(b["days"] for b in r["blocked"])
    if not o["total"]:
        bottom = ["No ticket was resolved in this window; cycle time and backward rate have no observations."]
        if kanban:
            bottom.append("Historical blocking still covers open tickets: %s; %d tickets blocked at collection."
                          % (fmt(blocked_total, "days"), now_blocked))
    else:
        bottom = [
            ("Median cycle time is %s over %d tickets (90 %% CI %s – %s days); %s of resolved tickets have one."
             % (fmt(o["median"], "working days"), o["n"], C.fmt_num(o["ci_lo"], 1), C.fmt_num(o["ci_hi"], 1),
                pct(o["coverage"]))) if o["ci_lo"] is not None else
            "Median cycle time is %s over %d tickets — too few for an interval." % (fmt(o["median"], "working days"), o["n"]),
            "%s of resolved tickets (%d of %d) moved backward in the workflow during these sprints; %d of them "
            "were sent back from a stage after in progress (review, test, acceptance or done), the rest were "
            "re-planned." % (pct(o["revert_rate"]), o["reverted"], o["total"], late),
            "%d tickets spent time blocked during these sprints, %s in total; %d are blocked now."
            % (len(r["blocked"]), fmt(blocked_total, "days"), now_blocked),
        ]
    if "skewed" in o["flags"]:
        bottom.append("The mean (%s) is far above the median: a few long-running tickets pull it up."
                      % fmt(o["mean"], "days"))
    if kanban:
        bottom = [line.replace("these sprints", "this window").replace("blocked now", "blocked at collection") for line in bottom]
    return C.page(
        "Cycle time — %s" % project,
        (["profile %s" % r["profile"]] if r.get("profile") else []) +
        ["%s to %s" % (periods[0]["start"], periods[-1]["end"]),
         scope_note,
         "%d tickets, %d resolved in window" % (r["issues"], r["resolved_in_window"]),
         "generated %s UTC" % datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")],
        C.bullets(bottom),
        C.tiles([("Median cycle time", fmt(o["median"], "days"), "working days, in progress to done"),
                 ("Backward rate", pct(o["revert_rate"]), "%d of %d tickets" % (o["reverted"], o["total"])),
                 ("Blocked time", fmt(blocked_total, "days"), "%d tickets, open ones included" % len(r["blocked"])),
                 ("Blocked at collection" if kanban else "Blocked now", "%d tickets" % now_blocked,
                  r.get("blocking_observed_at")),
                 ("Coverage", pct(o["coverage"]), "%d of %d resolved tickets" % (o["n"], o["total"]))]),
        C.definitions([
            ("Cycle time", "Working days (Monday to Friday, no holiday calendar) from a ticket's first entry "
                           "into %s to its resolution, for tickets resolved inside the window. It includes "
                           "time spent blocked or reworked." % " / ".join(cfg["jira"]["statuses"]["in_progress"])),
            ("Period" if kanban else "Sprint", ("Resolution belongs to exactly one UTC [start,end) week/month bucket. "
                       "Cycle time uses the first in-progress transition in the full history, even before the window. "
                       "A reopened ticket is measured to its latest recorded resolution.") if kanban else
                       "A ticket belongs to the sprint during which it was resolved, not to every sprint it"
                       "was planned in. A resolution between two sprints counts for the one that was ending. "
                       "A reopened ticket is measured to its final resolution."),
            ("Moved backward", "A move to an earlier status in the configured order, dated inside the analysed "
                               "window. A move undone within a minute is ignored. Blocked is neither forward "
                               "nor backward, but a ticket that returns from Blocked to an earlier status "
                               "than it left has moved backward."),
            ("Status order", " < ".join("/".join([g] if isinstance(g, str) else g)
                                        for g in cfg["jira"]["statuses"]["order"])),
            ("Blocked time", ("Historical calendar days clipped to [start,end) and the collection time, all "
                             "visits added up, including unresolved and later-resolved tickets. Tables by period "
                             "cover only the resolved cohort. Blocked at collection is a separate current-status "
                             "count among window candidates, not historical blocked duration.") if kanban else
                             "Calendar days in %s from the start of the first sprint on, all visits added up;"
                             "a ticket blocked now is counted until today. The headline covers every ticket "
                             "of these sprints, open ones included; the tables per sprint cover resolved ones."
                             % " / ".join(cfg["jira"]["statuses"]["blocked"])),
            ("Coverage", "Resolved tickets that have a cycle time, out of all resolved tickets. A ticket that "
                         "never entered an in-progress status has none."),
            ("Flags", "low n: fewer than %d tickets. skewed: mean more than twice the median." % L.LOW_N),
        ]),
        C.section("Per " + kind,
                  C.grid(C.card("Median cycle time per " + kind, C.columns(pts(names, by_period), "days", digits=1),
                                "working days · whisker = 90 % CI · faded = little data"),
                         C.card("Tickets moved backward per " + kind, C.columns(
                             pts(names, by_period, "revert_rate", "revert_lo", "revert_hi", 100.0), "%",
                             color_index=1), "% of resolved tickets · whisker = 90 % CI")),
                  C.table(cols, [row(n, by_period[n]) for n in names] + [row("All periods", o)], num)),
        C.section("Per issue type",
                  C.card("Median cycle time per type", C.hbars(
                      [{"label": t, "value": r["by_type"][t]["median"], "low": r["by_type"][t]["low"],
                        "note": "%d tickets" % r["by_type"][t]["n"]} for t in types], "days", digits=1)),
                  C.table(cols, [row(t, r["by_type"][t]) for t in types], num)),
        C.section("Per developer",
                  (C.card("Median cycle time per assignee", C.hbars(
                      [{"label": p, "value": r["by_assignee"][p]["median"], "low": r["by_assignee"][p]["low"],
                        "note": "%d tickets" % r["by_assignee"][p]["n"]} for p in people], "days", digits=1))
                   + C.table(cols, [row(p, r["by_assignee"][p]) for p in people], num)) if show
                  else "<p class='note'>Per-person figures are switched off (delivery.show_people).</p>",
                  note="The assignee is whoever holds the ticket when it is resolved, which is not always who "
                       "did the work. Ticket size and type differ between people; the numbers describe the "
                       "tickets as much as the person."),
        C.section("Blocked time",
                  C.card("Days blocked per ticket", C.hbars(
                      [{"label": b["key"], "value": b["days"],
                        "note": ("blocked now" if b["still_blocked"] else b["status"] or "") + " · " + b["type"]}
                       for b in r["blocked"]], "days", color_index=7, digits=1)),
                  C.table(["Ticket", "Type", "Status now", "Assignee", "Days blocked", "Resolved in"],
                          [[b["key"], b["type"], ("Blocked (still)" if b["still_blocked"] else b["status"] or "–"),
                            b["assignee"] if show else "–", fmt(b["days"], "days"), b["bucket"]] for b in r["blocked"]],
                          numeric=(4,))),
        C.section("Tickets that moved backward", C.table(
            ["Ticket", "Type", "Period" if kanban else "Sprint", "Assignee", "Moves"],
            [[t["key"], t["type"], t.get("period", t.get("sprint")), t["assignee"] if show else "–",
              "; ".join("%s → %s%s (%s)" % (m["from"], m["to"], " via blocked" if m.get("via_blocked") else "",
                                           m["at"][:10]) for m in t["moves"])]
             for t in r["reverted"]])),
        C.section("Longest cycle times", C.table(
            ["Ticket", "Type", "Period" if kanban else "Sprint", "Assignee", "Cycle time"],
            [[t["key"], t["type"], t.get("period", t.get("sprint")), t["assignee"] if show else "–", fmt(t["cycle"], "days")]
             for t in r["longest"]], numeric=(4,))),
        C.section("Data quality", C.bullets([
            ("Statuses not in the configured order, ignored when looking for backward moves: %s. Add them to "
             "delivery.jira.statuses.order to have them counted." % ", ".join(r["unknown_statuses"]))
            if r["unknown_statuses"] else "Every status seen is in the configured order.",
            ("Resolved without entering an in-progress status first, so without a cycle time: %s."
             % ", ".join(r["no_cycle"])) if r["no_cycle"] else "Every resolved ticket has a cycle time.",
            ("Resolved outside the analysed window and "
             "therefore in no bucket: %s." % ", ".join(r["resolved_outside"])) if r.get("resolved_outside") else "",
            ("Jira returned only part of the history of: %s. Their figures may be wrong; collect them one "
             "by one." % ", ".join(r["truncated_changelogs"])) if r.get("truncated_changelogs") else "",
            ("%d duplicate ticket records in the input were dropped." % r["duplicates_dropped"])
            if r.get("duplicates_dropped") else "",
            ("History completeness was not verified for: %s." % ", ".join(r["unverified_changelogs"]))
            if r.get("unverified_changelogs") else "",
            "Board/filter membership is evaluated at collection, not reconstructed historically." if kanban else "",
            "Legacy input has no collection metadata: board scope and freshness are unverified; recollect to verify."
            if r.get("scope", {}).get("scope_verified") is False else "",
            "Source: " + r.get("source", "files"),
        ])),
        footer="Computed by jira_cycle.py.")


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Jira cycle time for Scrum sprints or Kanban date windows.")
    ap.add_argument("--profile", help="Named delivery profile in <metrics-dir>/profiles/NAME.json.")
    ap.add_argument("--project")
    ap.add_argument("--sprints", type=int)
    ap.add_argument("--board")
    ap.add_argument("--mode", choices=("scrum", "kanban"))
    ap.add_argument("--filter", dest="filter_id", help="Kanban saved-filter ID, instead of a board.")
    ap.add_argument("--since", help="Kanban inclusive ISO 8601 start (UTC).")
    ap.add_argument("--until", help="Kanban exclusive ISO 8601 end (UTC).")
    ap.add_argument("--group-by", choices=("week", "month"))
    ap.add_argument("--input", help="Directory with scope metadata and issue files (plus sprints.json for Scrum).")
    ap.add_argument("--metrics-dir", "--kpi-dir", dest="metrics_dir")
    ap.add_argument("--out-dir")
    args = ap.parse_args()

    metrics_dir = args.metrics_dir or L.find_metrics_dir()
    try:
        cfg = L.load_config(metrics_dir, args.profile)
    except L.ConfigError as exc:
        L.die("Configuration problem in %s: %s" % (os.path.join(metrics_dir or ".enabler/metrics", "config.json"), exc))
    overrides = {key: getattr(args, key) for key in
                 ("project", "sprints", "board", "mode", "since", "until", "group_by")
                 if getattr(args, key) is not None}
    if args.filter_id is not None:
        overrides["filter"] = args.filter_id
    # Profile context switches reset inherited selectors. Legacy CLI merge stays compatible.
    cfg["jira"] = L.jira_overlay(cfg["jira"], overrides) if args.profile else L.merge(cfg["jira"], overrides)
    jcfg = cfg["jira"]
    try:
        L.validate_jira(jcfg)
    except L.ConfigError as exc:
        L.die(str(exc))
    project = jcfg["project"]
    kanban = jcfg["mode"] == "kanban"
    collected = datetime.now(timezone.utc)
    periods = L.jira_periods(jcfg, collected) if kanban else []
    dropped = 0
    if args.input:
        try:
            scope, observed = load_collection(args.input, jcfg, periods, args.profile, cfg.get("_connection"))
            sprints, issues, dropped = load_dir(args.input)
        except (OSError, ValueError) as exc:
            L.die("Invalid Jira input: %s" % exc)
        collected = observed or collected
        source = "offline collection"
        if not kanban and not sprints:
            L.die("Expected sprints.json in %s." % args.input)
        if not kanban and scope.get("sprint_ids") and (
                {str(s.get("id")) for s in sprints} != {str(i) for i in scope["sprint_ids"]}):
            L.die("sprints.json IDs do not match collection.json sprint_ids.")
    else:
        jira = Jira(cfg.get("_connection"), args.profile)
        if not jira.available and args.profile:
            L.die("NO_JIRA_ACCESS: profile connection or its referenced environment variables are missing; "
                  "configure this profile's connection or collect matching MCP data with --input. No default credentials were used.")
        if not jira.available:
            L.die("NO_JIRA_ACCESS: set JIRA_URL and JIRA_PERSONAL_TOKEN (or JIRA_USERNAME and "
                  "JIRA_API_TOKEN) in the environment, or collect the data to a directory and pass --input.")
        if not project:
            L.die("Which Jira project? Pass --project KEY or set delivery.jira.project in the metrics config.")
        try:
            if kanban:
                issues, scope = jira.collect_kanban(project, periods, jcfg["board"], jcfg["filter"], jcfg["group_by"])
                sprints = []
            else:
                sprints, issues = jira.collect(project, jcfg["sprints"], jcfg["board"])
                scope = jira.scope
        except RuntimeError as exc:
            L.die(str(exc))
        source = "Jira REST API"
        collected = datetime.now(timezone.utc)
    if kanban:
        # Freeze rolling defaults before using the observation timestamp of an offline collection.
        jcfg["since"], jcfg["until"] = periods[0]["start"], periods[-1]["end"]
    try:
        result = analyse(sprints, issues, cfg, now=collected)
    except ValueError as exc:
        L.die(str(exc))
    if args.profile:
        scope.update(profile=args.profile, connection_url=cfg["_connection"]["url"])
        result["profile"] = args.profile
    result["scope"] = scope
    result["workflow_statuses"] = cfg["jira"]["statuses"]
    result["collected_at"] = collected.isoformat()
    result["duplicates_dropped"] = dropped
    result.update({"metric": "cycle-time", "unit": "working days", "project": project, "source": source,
                   "generated": datetime.now(timezone.utc).isoformat()})
    snap_dir, rep_dir = L.output_dirs(metrics_dir, args.out_dir, profile=args.profile)
    page = render(result, project or "Jira", cfg)
    if not cfg["show_people"]:
        # The snapshot can end up committed: hiding names only in the HTML is not enough.
        result = {k: v for k, v in result.items() if k != "by_assignee"}
        for key in ("reverted", "blocked", "longest"):
            result[key] = [{f: v for f, v in item.items() if f != "assignee"} for item in result[key]]
    L.save_snapshot(snap_dir, "cycle-time", result)
    path = os.path.join(rep_dir, "cycle-time.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)
    print(path)


if __name__ == "__main__":
    try:
        main()
    except L.ConfigError as exc:
        L.die("Configuration problem: %s" % exc)
