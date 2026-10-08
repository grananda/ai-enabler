#!/usr/bin/env python3
"""Shared pieces of the delivery-flow metrics: statistics, time arithmetic,
configuration, the GitHub CLI wrapper with its on-disk cache, and snapshots.

Everything here is deterministic. The same input gives the same figures, which
is the point of doing the arithmetic in a script and not in a conversation.
"""

import json
import math
import os
import random
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

LOW_N = 20          # fewer observations than this: directional only
MIN_COVERAGE = 0.70
SEED = 42
RESAMPLES = 5000

DEFAULTS = {
    "repo": None,                  # owner/name; default: the repository in the current directory
    "base_branch": None,           # default: the repository's default branch
    "weeks": 6,
    "followup_days": 14,
    "ticket_pattern": None,        # default: the metrics config's ticket_pattern, else [A-Z][A-Z0-9]+-\d+
    "exclude": [],                 # extra glob patterns excluded from PR size
    "area_roots": ["apps", "libs", "packages", "services", "modules"],
    "show_people": True,
    "targets": {},                 # a delivery metric with a target is a KPI; see TARGETS below
    "size_buckets": [100, 500],    # S below the first, L from the second
    "jira": {
        "project": None,
        "sprints": 3,
        "board": None,
        "statuses": {
            "order": [["To Do", "Open", "Backlog", "Ready", "Selected for Development",
                       "In Estimation", "In Definition"],
                      ["In Progress", "In Development"],
                      ["In Review", "Code Review"],
                      ["In Test", "Testing", "QA"],
                      ["In Acceptance", "Acceptance", "UAT"],
                      ["Done", "Closed", "Resolved", "Ready for deployment"]],
            "in_progress": ["In Progress", "In Development"],
            "blocked": ["Blocked", "On Hold", "Impediment"],
        },
    },
}

DEFAULT_EXCLUDES = [
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "npm-shrinkwrap.json", "*.lock",
    "go.sum", "dist/**", ".nx/**", "coverage/**", "node_modules/**",
    "*.min.js", "*.min.css", "*.map", "*.snap", "*.generated.*", "*.pb.go", "*_pb2.py",
]


# Things that look like issue keys and are not (the capture hook has the same list).
NOT_TICKETS = {
    "UTF", "SHA", "ISO", "CVE", "RFC", "HTTP", "TLS", "SSL", "AES", "MD", "RSA", "CWE", "JDK", "JSR",
    "ES", "PEP", "UTC", "GMT", "COVID", "HTTPS", "TCP", "IPV", "BASE", "CP", "WINDOWS", "LATIN",
    "ASCII", "OPUS", "SONNET", "HAIKU", "FABLE", "CLAUDE", "GPT", "PYTHON", "JAVA", "NODE", "OAUTH",
    "HTML", "CSS", "ECMA", "ANGULAR", "REACT", "VUE", "SPRING", "JUNIT", "LOG4J", "X86", "ARM",
    "WCAG", "PCI", "SOC", "GDPR", "IPV4", "IPV6", "H", "V",
}
DEFAULT_TICKET_PATTERN = r"\b[A-Z][A-Z0-9]{1,9}-\d{1,6}\b"


class ConfigError(ValueError):
    pass


# The only metrics that can carry a target, and so become KPIs: the four-number
# delivery baseline. Usage figures (assistant usage, tokens, cost, lines written
# by AI, number of skills) are context and never targets: a team optimises
# whatever becomes a target, and those measure activity, not delivery.
TARGETS = {
    "pr_size_median_lines": ("pr-size", "Pull request size", "median", "lines", 1.0),
    "review_wait_median_hours": ("review-wait", "Review waiting time", "median", "hours", 1.0),
    "rework_rate_percent": ("rework", "Rework rate", "rate", "%", 100.0),
    "cycle_time_median_days": ("cycle-time", "Cycle time", "median", "working days", 1.0),
}


def read_targets(raw):
    """({key: (bound, value)}, [rejected keys]) from the `targets` block of the configuration."""
    if not isinstance(raw, dict):
        raise ConfigError("delivery.targets must be a map, for example "
                          '{"review_wait_median_hours": {"max": 8}}.')
    accepted, rejected = {}, []
    for key, spec in raw.items():
        if key not in TARGETS:
            rejected.append(key)
            continue
        if isinstance(spec, (int, float)) and not isinstance(spec, bool):
            spec = {"max": spec}
        value = next(iter(spec.values())) if isinstance(spec, dict) and len(spec) == 1 else None
        if not (isinstance(spec, dict) and len(spec) == 1 and next(iter(spec)) in ("max", "min")
                and isinstance(value, (int, float)) and not isinstance(value, bool)
                and math.isfinite(value) and value > 0):
            raise ConfigError('delivery.targets.%s must be {"max": number} or {"min": number}, with a number '
                              'greater than zero.' % key)
        accepted[key] = next(iter(spec.items()))
    return accepted, rejected


def evaluate_targets(cfg, snapshots):
    """One verdict per target, from the metric snapshots.

    met / not met only when the whole 90 % interval is on one side of the target;
    otherwise inconclusive: with little data the honest answer is "cannot tell yet".
    """
    out = []
    for key, (bound, target) in cfg["_targets"].items():
        metric, label, field, unit, scale = TARGETS[key]
        snap = snapshots.get(metric)
        row = {"key": key, "metric": metric, "label": label, "unit": unit, "bound": bound, "target": target,
               "value": None, "lo": None, "hi": None, "n": 0, "status": "no data",
               "why": "this metric has not been collected"}
        if snap:
            o = snap["overall"]
            value = o.get(field)
            lo, hi = o.get("ci_lo"), o.get("ci_hi")
            row.update({"value": None if value is None else value * scale,
                        "lo": None if lo is None else lo * scale, "hi": None if hi is None else hi * scale,
                        "n": o.get("n") or 0})
            v, lo, hi = row["value"], row["lo"], row["hi"]
            if v is None:
                row["why"] = "nothing to measure in this period"
            elif lo is None or hi is None:
                row.update(status="inconclusive", why="too few observations for an interval")
            elif bound == "max":
                if hi <= target:
                    row.update(status="met", why="the whole interval is at or under the target")
                elif lo > target:
                    row.update(status="not met", why="the whole interval is over the target")
                else:
                    row.update(status="inconclusive", why="the interval straddles the target")
            else:
                if lo >= target:
                    row.update(status="met", why="the whole interval is at or over the target")
                elif hi < target:
                    row.update(status="not met", why="the whole interval is under the target")
                else:
                    row.update(status="inconclusive", why="the interval straddles the target")
        out.append(row)
    return out


def find_ticket(cfg, title, branch):
    """(key, where it was found) for a pull request, or (None, None).

    With a project-specific pattern the branch name is searched in upper case
    too, because branches are usually lower case. With the default pattern —
    which matches anything shaped like ABC-123 — the branch is searched as
    written and known look-alikes (UTF-8, NODE-20, OAUTH-2 ...) are skipped,
    otherwise unrelated pull requests would be grouped as one ticket.
    """
    pattern, default = cfg["_ticket_re"], cfg["_ticket_default"]
    sources = (("title", title or ""),
               ("branch", (branch or "") if default else (branch or "").upper().replace("_", "-")))
    for where, text in sources:
        for m in pattern.finditer(text):
            key = m.group(0)
            if default and key.split("-")[0] in NOT_TICKETS:
                continue
            return key, where
    return None, None


# -------------------------------------------------------------------- config

def find_metrics_dir(start=None):
    """The project's .enabler/metrics (or the pre-1.0.0 .enabler/kpi), or None."""
    env = os.environ.get("ENABLER_METRICS_DIR") or os.environ.get("ENABLER_KPI_DIR")
    if env:
        return env
    d = os.path.abspath(start or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    while True:
        for rel in ("metrics", "kpi"):
            cand = os.path.join(d, ".enabler", rel)
            if os.path.isdir(cand):
                return cand
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(metrics_dir):
    """The `delivery` block of .enabler/metrics/config.json over the defaults."""
    raw = {}
    if metrics_dir:
        try:
            with open(os.path.join(metrics_dir, "config.json"), encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            raw = {}
    cfg = merge(DEFAULTS, raw.get("delivery") or {})
    custom = cfg.get("ticket_pattern") or raw.get("ticket_pattern")
    cfg["ticket_pattern"] = custom or DEFAULT_TICKET_PATTERN
    cfg["_ticket_default"] = not custom
    # Fail with a sentence, not a traceback, on a configuration that cannot work.
    try:
        cfg["_ticket_re"] = re.compile(cfg["ticket_pattern"])
    except re.error as exc:
        raise ConfigError("ticket_pattern is not a valid regular expression: %s" % exc)
    if not isinstance(cfg["exclude"], list) or not all(isinstance(x, str) for x in cfg["exclude"]):
        raise ConfigError('delivery.exclude must be a list of glob patterns, for example ["*.md"].')
    b = cfg["size_buckets"]
    if not (isinstance(b, list) and len(b) == 2 and all(isinstance(x, (int, float)) for x in b) and b[0] < b[1]):
        raise ConfigError("delivery.size_buckets must be two increasing numbers, for example [100, 500].")
    cfg["_targets"], cfg["_rejected_targets"] = read_targets(cfg.get("targets") or {})
    if not isinstance(cfg["area_roots"], list):
        raise ConfigError("delivery.area_roots must be a list of directory names.")
    return cfg


def project_root():
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return os.getcwd()


def output_dirs(metrics_dir, out_dir=None, create=True):
    """(snapshot dir, report dir).

    Without a metrics directory the files go to <repository root>/.enabler/delivery/
    and never to .enabler/metrics/: that directory is what switches the usage hooks
    on, and running a report must not opt a project into capture.
    """
    if metrics_dir:
        snap = os.path.join(metrics_dir, "delivery")
        base = os.path.join(metrics_dir, "reports")
    else:
        snap = os.path.join(project_root(), ".enabler", "delivery")
        base = os.path.join(snap, "reports")
    rep = out_dir or os.path.join(base, datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    if create:
        os.makedirs(snap, exist_ok=True)
        os.makedirs(rep, exist_ok=True)
    return snap, rep


def save_snapshot(snap_dir, name, data):
    path = os.path.join(snap_dir, name + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1)
    return path


def load_snapshot(snap_dir, name):
    try:
        with open(os.path.join(snap_dir, name + ".json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------------- time

def parse_ts(value):
    """ISO 8601 from GitHub ('...Z') or Jira ('...+0200', '.000+0000') to aware UTC."""
    if not value:
        return None
    s = str(value).strip()
    s = re.sub(r"Z$", "+00:00", s)
    s = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", s)
    s = re.sub(r"\.(\d{1,6})\d*", lambda m: "." + m.group(1).ljust(6, "0"), s)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_week(dt):
    y, w, _ = dt.isocalendar()
    return "%d-W%02d" % (y, w)


def working_seconds(start, end):
    """Seconds between two instants counting Monday to Friday only (UTC, no holidays)."""
    if not start or not end or end <= start:
        return 0.0
    total, cur = 0.0, start
    while cur < end:
        nxt = min(end, (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
        if cur.weekday() < 5:
            total += (nxt - cur).total_seconds()
        cur = nxt
    return total


def business_days(start, end):
    return working_seconds(start, end) / 86400.0


# --------------------------------------------------------------------- stats

def median(values):
    v = sorted(values)
    if not v:
        return None
    m = len(v) // 2
    return float(v[m]) if len(v) % 2 else (v[m - 1] + v[m]) / 2.0


def mean(values):
    return sum(values) / float(len(values)) if values else None


def bootstrap_ci(values, level=0.90):
    """Percentile bootstrap interval for the median; None for fewer than 2 values."""
    v = list(values)
    if len(v) < 2:
        return None, None
    rng = random.Random(SEED)
    n = len(v)
    meds = sorted(median([v[rng.randrange(n)] for _ in range(n)]) for _ in range(RESAMPLES))
    lo = meds[int((1 - level) / 2 * RESAMPLES)]
    hi = meds[min(RESAMPLES - 1, int((1 + level) / 2 * RESAMPLES))]
    return lo, hi


def wilson_ci(k, n, z=1.6449):
    """90 % Wilson interval for a proportion."""
    if not n:
        return None, None
    p = k / float(n)
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - r) / d), min(1.0, (c + r) / d)


def summarize(values, total=None):
    """The standard description of one bucket of durations or sizes."""
    v = [x for x in values if x is not None]
    lo, hi = bootstrap_ci(v)
    med, avg = median(v), mean(v)
    n = len(v)
    total = n if total is None else total
    coverage = (n / float(total)) if total else None
    flags = []
    if n < LOW_N:
        flags.append("low n")
    if coverage is not None and coverage < MIN_COVERAGE:
        flags.append("low coverage")
    if med and avg and avg > 2 * med:
        flags.append("skewed")
    return {"n": n, "total": total, "coverage": coverage, "median": med, "mean": avg,
            "ci_lo": lo, "ci_hi": hi, "flags": flags, "low": n < LOW_N or "low coverage" in flags}


def share(values, predicate):
    v = [x for x in values if x is not None]
    return (sum(1 for x in v if predicate(x)) / float(len(v))) if v else None


def group_by(items, key):
    out = {}
    for it in items:
        k = key(it)
        if k is None:
            continue
        out.setdefault(k, []).append(it)
    return out


# ------------------------------------------------------------------- GitHub

class GhError(RuntimeError):
    pass


def run(cmd, cwd=None, timeout=180):
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise GhError("`%s` is not installed" % cmd[0])
    except subprocess.TimeoutExpired:
        raise GhError("timed out: %s" % " ".join(cmd[:4]))
    if out.returncode != 0:
        raise GhError((out.stderr or out.stdout).strip()[:400] or "command failed: %s" % " ".join(cmd[:4]))
    return out.stdout


GH_HELP = (
    "The GitHub CLI is needed for the pull-request metrics. Install it from https://cli.github.com "
    "and sign in with `gh auth login` (for GitHub Enterprise: `gh auth login --hostname <host>`). "
    "It is the recommended way to read pull requests: it uses your own access, needs no token in "
    "any file, and gives the same result on every run."
)


def gh_check():
    try:
        run(["gh", "--version"])
        run(["gh", "auth", "status"])
    except GhError as exc:
        raise GhError("%s\n\n%s" % (exc, GH_HELP))


def gh_repo(repo=None, cwd=None):
    """(owner/name, default branch, host) of the repository to analyse."""
    cmd = ["gh", "repo", "view"] + ([repo] if repo else []) + ["--json", "nameWithOwner,defaultBranchRef,url"]
    d = json.loads(run(cmd, cwd=cwd))
    host = re.sub(r"^https?://([^/]+)/.*$", r"\1", d.get("url") or "") or "github.com"
    return d["nameWithOwner"], (d.get("defaultBranchRef") or {}).get("name"), host


class Gh:
    """Reads through `gh api`, caching what cannot change (data of merged pull requests)."""

    def __init__(self, repo, host, cache_dir, refresh=False):
        self.repo, self.host, self.refresh = repo, host, refresh
        self.cache = os.path.join(cache_dir, re.sub(r"[^A-Za-z0-9._-]", "_", "%s_%s" % (host, repo)))
        os.makedirs(self.cache, exist_ok=True)
        self.calls = self.hits = 0

    def api(self, path, cache_key=None, paginate=True):
        file = os.path.join(self.cache, cache_key + ".json") if cache_key else None
        if file and not self.refresh and os.path.isfile(file):
            self.hits += 1
            with open(file, encoding="utf-8") as fh:
                return json.load(fh)
        cmd = ["gh", "api", "--hostname", self.host, "-H", "Accept: application/vnd.github+json", path]
        if paginate:
            cmd += ["--paginate", "--slurp"]
        self.calls += 1
        data = json.loads(run(cmd) or "null")
        if paginate and isinstance(data, list) and data and all(isinstance(p, list) for p in data):
            data = [item for page_ in data for item in page_]
        if file:
            with open(file, "w", encoding="utf-8") as fh:
                json.dump(data, fh)
        return data

    def merged_prs(self, base, since):
        """Merged pull requests into `base` since a date, newest first, with line totals."""
        fields = ("number,title,author,createdAt,mergedAt,additions,deletions,changedFiles,"
                  "headRefName,isDraft,mergeCommit,url")
        cmd = ["gh", "pr", "list", "--repo", "%s/%s" % (self.host, self.repo) if self.host != "github.com"
               else self.repo, "--state", "merged", "--base", base, "--limit", "2000",
               "--search", "merged:>=%s" % since.strftime("%Y-%m-%d"), "--json", fields]
        self.calls += 1
        prs = json.loads(run(cmd, timeout=600))
        if len(prs) >= 2000:
            sys.stderr.write("warning: GitHub returned 2,000 pull requests, the most this report reads; "
                             "older ones in the window are missing. Use a shorter --weeks.\n")
        out = []
        for p in prs:
            author = p.get("author") or {}
            login = author.get("login") or "unknown"
            out.append({
                "number": p["number"], "title": p.get("title") or "", "url": p.get("url"),
                "author": login,
                "bot": bool(author.get("is_bot")) or login.endswith("[bot]") or login.startswith("app/"),
                "created_at": p.get("createdAt"), "merged_at": p.get("mergedAt"),
                "additions": p.get("additions") or 0, "deletions": p.get("deletions") or 0,
                "changed_files": p.get("changedFiles") or 0, "head_ref": p.get("headRefName") or "",
                "merge_sha": (p.get("mergeCommit") or {}).get("oid"),
            })
        return out

    def files(self, number):
        return self.api("repos/%s/pulls/%d/files?per_page=100" % (self.repo, number), "pr-%d-files" % number)

    def reviews(self, number):
        return self.api("repos/%s/pulls/%d/reviews?per_page=100" % (self.repo, number), "pr-%d-reviews" % number)

    def timeline(self, number):
        return self.api("repos/%s/issues/%d/timeline?per_page=100" % (self.repo, number), "pr-%d-timeline" % number)


def parallel(fn, items, workers=8):
    """fn over items on a few threads; returns {item: result}, raising the first error."""
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(zip(items, pool.map(fn, items)))


def die(message):
    sys.stderr.write(message.rstrip() + "\n")
    sys.exit(1)
