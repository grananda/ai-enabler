#!/usr/bin/env python3
"""Decides which review lenses a change needs, how to group them, and writes the review pack.

    review_scope.py --base <branch> [--run-dir DIR] [--out PATH] [--lenses correctness,security,quality,tests]
                    [--no-select] [--group-below 150] [--sensitive GLOB ...] [--max-diff-lines 1500]

Prints JSON on stdout:

    lenses     the lenses to run, a subset of --lenses
    skipped    {lens: reason} for each lens left out, to be stated in the review report
    triggers   up to five "path: reason" examples of why security is in
    groups     one list of lenses per reviewer instance to launch, all in one message
    files, changed_lines, pack

The change is everything between the merge base with --base and the working tree:
committed, staged, unstaged, and untracked files git does not ignore.

Lens selection (--no-select keeps every lens of --lenses):
  correctness, quality, tests  always.
  security                     when a changed file that is not a test or documentation touches
                               external input, I/O, process execution, queries, rendering of HTML,
                               authentication or permissions, secrets, configuration or dependency
                               manifests, or matches --sensitive. Left out only when nothing is found.
Grouping: under --group-below changed lines (0 never groups), two instances: correctness with
tests, security with quality. Otherwise one instance per lens.

The pack (--out, default <run-dir>/review-pack.md) holds the scope with each file's kind, the lenses
and why, the acceptance criteria in force, the test report, what each lens reads beyond it, and the
diff of the code (not tests or documents, which the lenses that need them read per file) when it has
at most --max-diff-lines lines. It is written once; every reviewer reads it first.
No third-party dependencies; no model involved.
"""

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys

ALL_LENSES = ["correctness", "security", "quality", "tests"]
GROUPS_WHEN_SMALL = [["correctness", "tests"], ["security", "quality"]]

DOC = re.compile(r"(^|/)(docs?|documentation)/|\.(md|markdown|rst|adoc|txt)$|(^|/)(LICENSE|CHANGELOG|README)[^/]*$", re.I)
TEST = re.compile(r"(^|/)(tests?|__tests__|spec|specs|e2e|testing)/|(\.|_)(test|spec)s?\.[^/]+$|(^|/)test_[^/]+$"
                  r"|Tests?\.(cs|java|kt|scala|go|ts|tsx|js|jsx|py)$|_test\.go$", re.I)
STYLE = re.compile(r"\.(css|scss|sass|less|styl)$", re.I)

# Paths that put security in, whatever the change inside them.
SENSITIVE_PATHS = [
    ("authentication or permissions", re.compile(
        r"auth|login|logout|password|permission|role|acl|policy|policies|token|session|oauth|jwt|saml|crypto|secret|"
        r"credential|csrf|cors", re.I)),
    ("entry point", re.compile(
        r"controller|endpoint|route|router|handler|middleware|interceptor|filter|resolver|servlet|"
        r"(^|/)(program|startup)\.cs$|(^|/)(server|app|main|index)\.(js|ts|py|go)$|(^|/)api/", re.I)),
    ("configuration", re.compile(
        r"(^|/)(appsettings[^/]*\.json|web\.config|[^/]*\.config|\.env[^/]*|application[^/]*\.(ya?ml|properties)|"
        r"settings\.py|dockerfile[^/]*|docker-compose[^/]*|[^/]*\.tf|\.gitlab-ci\.yml|nginx[^/]*\.conf)$|"
        r"(^|/)(\.github/workflows|k8s|helm|deploy|deployment|config)/", re.I)),
    ("dependencies", re.compile(
        r"(^|/)(package(-lock)?\.json|yarn\.lock|pnpm-lock\.yaml|requirements[^/]*\.txt|pyproject\.toml|pipfile(\.lock)?|"
        r"poetry\.lock|[^/]*\.csproj|packages\.config|directory\.(packages|build)\.props|pom\.xml|build\.gradle(\.kts)?|"
        r"go\.(mod|sum)|cargo\.(toml|lock)|gemfile(\.lock)?|composer\.(json|lock))$", re.I)),
]

# Changed lines that put security in.
SENSITIVE_LINES = [
    ("external input", re.compile(
        r"\bRequest\.|HttpContext|\[From(Body|Query|Route|Form|Header)\]|\[Http(Get|Post|Put|Patch|Delete)\b|"
        r"\bMap(Get|Post|Put|Patch|Delete|Methods)\s*\(|@(Get|Post|Put|Patch|Delete|Request)Mapping|@RequestParam|"
        r"@PathVariable|@RequestBody|\breq\.(body|query|params|headers|cookies)|\brequest\.(args|form|json|files|GET|POST)|"
        r"\bapp\.(get|post|put|patch|delete)\s*\(|\brouter\.(get|post|put|patch|delete)\s*\(|"
        r"\bwindow\.location|\bURLSearchParams|\bprocess\.argv|\bsys\.argv|\binput\s*\(")),
    ("outbound calls", re.compile(
        r"\bfetch\s*\(|\baxios\b|XMLHttpRequest|\bHttpClient\b|\bWebClient\b|RestTemplate|\burllib\b|"
        r"\brequests\.(get|post|put|patch|delete|request)\b|\bhttp\.(get|request)\s*\(")),
    ("process execution", re.compile(
        r"Process\.Start|\bsubprocess\b|\bos\.(system|popen)|\bchild_process\b|Runtime\.getRuntime|\bexec(Sync|File)?\s*\(|"
        r"\beval\s*\(|new Function\s*\(")),
    ("file system", re.compile(
        r"\bFile\.(Read|Write|Open|Delete|Copy|Move|Create)|\bDirectory\.(Delete|Create|Move)|Path\.Combine|"
        r"\bfs\.(read|write|unlink|rm|mkdir|createReadStream|createWriteStream)|\bopen\s*\(|\bshutil\.|\bos\.(remove|unlink|rmdir)")),
    ("queries", re.compile(
        r"SqlCommand|ExecuteSql|FromSqlRaw|FromSqlInterpolated|\.raw\s*\(|cursor\.execute|createQuery|createNativeQuery|"
        r"\bSELECT\b.+\bFROM\b|\bINSERT\s+INTO\b|\bUPDATE\b.+\bSET\b|\bDELETE\s+FROM\b", re.I)),
    ("HTML rendering", re.compile(
        r"innerHTML|outerHTML|dangerouslySetInnerHTML|document\.write|v-html|\|\s*safe\b|Html\.Raw|bypassSecurityTrust")),
    ("deserialisation", re.compile(
        r"\bpickle\.|yaml\.load\s*\(|BinaryFormatter|TypeNameHandling|ObjectInputStream|\bunserialize\s*\(|"
        r"JsonConvert\.DeserializeObject")),
    ("authentication or secrets", re.compile(
        r"password|passwd|secret|api[_-]?key|token|credential|\[Authorize|\[AllowAnonymous|ClaimsPrincipal|"
        r"@PreAuthorize|@Secured|\bjwt\b|cookie|localStorage|sessionStorage|\bcors\b|csrf", re.I)),
    ("redirects", re.compile(r"\bRedirect\s*\(|\bres\.redirect\s*\(|\bredirect\s*\(")),
]
CANCELLATION = re.compile(r"cancellation_?token", re.I)


def git(args, cwd, check=True):
    out = subprocess.run(["git", "-c", "core.quotePath=false"] + args, cwd=cwd, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if check and out.returncode != 0:
        sys.exit("review_scope: git %s failed: %s" % (" ".join(args), out.stderr.strip()))
    return out.stdout


def is_text(path):
    try:
        with open(path, "rb") as fh:
            return b"\0" not in fh.read(8192)
    except OSError:
        return False


def kind(path):
    if DOC.search(path):
        return "doc"
    if TEST.search(path):
        return "test"
    return "code"


def change(cwd, base):
    """(merge base, files, chunks): files = {path: {"added", "removed", "lines"}}, chunks = {path: diff text}."""
    merge_base = git(["merge-base", base, "HEAD"], cwd).strip()
    files, chunks = {}, {}
    for line in git(["diff", "--numstat", "--no-renames", merge_base], cwd).splitlines():
        added, removed, path = line.split("\t", 2)
        files[path] = {"added": int(added) if added.isdigit() else 0,
                       "removed": int(removed) if removed.isdigit() else 0, "lines": []}
    diff = git(["diff", "--no-color", "--no-renames", merge_base], cwd)
    current = old = None
    block = []

    def flush():
        if current in files and block:
            chunks[current] = "\n".join(block)

    for line in diff.splitlines():
        if line.startswith("diff --git "):
            flush()
            current = old = None
            block = [line]
            continue
        block.append(line)
        if line.startswith("--- ") and current is None:
            old = line[6:] if line.startswith("--- a/") else None
        elif line.startswith("+++ ") and current is None:
            current = line[6:] if line.startswith("+++ b/") else old   # a deleted file: its old path
        elif current in files and line and line[0] in "+-":
            files[current]["lines"].append(line[1:])
    flush()
    for path in git(["ls-files", "--others", "--exclude-standard"], cwd).splitlines():
        full = os.path.join(cwd, path)
        if path.startswith(".enabler/") or not is_text(full):
            continue
        with open(full, encoding="utf-8", errors="replace") as fh:
            text = fh.read().splitlines()
        files[path] = {"added": len(text), "removed": 0, "lines": text}
        chunks[path] = "diff --git a/%s b/%s\nnew file (untracked)\n--- /dev/null\n+++ b/%s\n@@ -0,0 +1,%d @@\n%s" % (
            path, path, path, len(text), "\n".join("+" + t for t in text))
    return merge_base, files, chunks


def security_triggers(files, sensitive_globs):
    found = []
    for path, info in sorted(files.items()):
        if any(fnmatch.fnmatch(path, g) for g in sensitive_globs):
            found.append("%s: configured as sensitive" % path)
            continue
        if DOC.search(path) or TEST.search(path) or STYLE.search(path):
            continue
        reason = next((why for why, rx in SENSITIVE_PATHS if rx.search(path)), None)
        if not reason:
            # A cancellation token is plumbing, not a credential.
            lines = [CANCELLATION.sub("", l) for l in info["lines"]]
            reason = next((why for why, rx in SENSITIVE_LINES if any(rx.search(l) for l in lines)), None)
        if reason:
            found.append("%s: %s" % (path, reason))
    return found


def criteria(run_dir):
    path = os.path.join(run_dir, "requirements.json") if run_dir else None
    if not path or not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as fh:
        req = json.load(fh)
    return [c for c in req.get("acceptance_criteria") or [] if isinstance(c, dict) and not c.get("removed_by")]


def write_pack(path, args, merge_base, files, chunks, result, run_dir):
    changed = result["changed_lines"]
    untracked = {p for p, c in chunks.items() if "\nnew file (untracked)\n" in c}
    out = ["# Review pack", "",
           "Written once for every reviewer of this pass. Read it before anything else: it replaces running the "
           "whole diff yourself and rereading the run files it quotes. Then read around the change as usual — callers, "
           "callees, tests, files that should have changed — and open anything you need to confirm a finding.", "",
           "## Scope", "",
           "- Base: `%s` (merge base `%s`), compared with the working tree, untracked files included" % (args.base, merge_base[:12]),
           "- %d files, %d changed lines" % (len(files), changed), "",
           "| File | Kind | + | − |", "|---|---|---|---|"]
    out += ["| `%s` | %s%s | %d | %d |" % (p, kind(p), " (untracked)" if p in untracked else "", f["added"], f["removed"])
            for p, f in sorted(files.items())]
    out += ["", "## Lenses", ""]
    out += ["- Instance %d: %s" % (i + 1, ", ".join(g)) for i, g in enumerate(result["groups"])]
    for lens, why in result["skipped"].items():
        out.append("- Not run: %s — %s" % (lens, why))
    if result["triggers"]:
        out.append("- Security is in because of: " + "; ".join(result["triggers"]))
    crit = criteria(run_dir)
    if crit:
        out += ["", "## Acceptance criteria in force", ""]
        out += ["- **%s** %s" % (c.get("id", "?"), c.get("text", "").strip()) for c in crit]
    report = os.path.join(run_dir, "test-report.md") if run_dir else None
    data = os.path.join(run_dir, "test-report.json") if run_dir else None
    if report and os.path.isfile(report):
        with open(report, encoding="utf-8", errors="replace") as fh:
            text = re.sub(r"(?m)^(#+) ", r"\1## ", fh.read().strip())
        out += ["", "## Test results (`test-report.md`)", "", text]
    elif data and os.path.isfile(data):
        # Not rendered yet (run_state.py renders it): the test engineer's data as it is.
        with open(data, encoding="utf-8", errors="replace") as fh:
            text = fh.read().strip()
        out += ["", "## Test results (`test-report.json`)", "", "```json", text, "```"]
    tests_docs = [p for p in sorted(files) if kind(p) != "code"]
    out += ["", "## What each lens reads beyond this pack", "",
            "- **correctness** — the code diff below; the tests and documents below when a criterion depends on them.",
            "- **security** — the code diff below; configuration and dependency files are in it.",
            "- **quality** — the code diff below; the documents below, for fit with the contracts and the architecture; "
            "the repository profile.",
            "- **tests** — the tests below, whole or by diff, against the criteria and the code diff."]
    if tests_docs:
        out += ["", "Tests and documents changed (not copied here): `git --no-pager diff %s -- <path>`; "
                "untracked files are new, read them whole." % merge_base[:12], ""]
        out += ["- `%s` (%s%s)" % (p, kind(p), ", untracked" if p in untracked else "") for p in tests_docs]
    if run_dir:
        out += ["", "## Where the rest is", "",
                "- `plan.md` — the approved plan; read the steps your lenses need.",
                "- `repo-context.md` and the repository profile (`.enabler/repo-profile/profile.md` and its `deltas/`) — "
                "the quality lens reads them; the other lenses read them when the pack and the code leave a question open.",
                "- `external-context.md` and `deltas/`, when they exist in the run directory — read them."]
    code = "\n".join(chunks[p] for p in sorted(chunks) if kind(p) == "code")
    out += ["", "## Diff of the code", ""]
    if not code:
        out.append("No code changed: only tests or documents.")
        result["diff_in_pack"] = True
    elif code.count("\n") + 1 <= args.max_diff_lines:
        out += ["```diff", code, "```"]
        result["diff_in_pack"] = True
    else:
        out.append("The code diff has more than %d lines and is not copied here. Read it per file: "
                   "`git --no-pager diff %s -- <path>`; untracked files are new, read them whole."
                   % (args.max_diff_lines, merge_base[:12]))
        result["diff_in_pack"] = False
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(out) + "\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", required=True, help="Branch or commit the change is compared with.")
    ap.add_argument("--run-dir", help="The run directory (.enabler/runs/<KEY>): criteria, test report, pack location.")
    ap.add_argument("--out", help="Where to write the pack (default <run-dir>/review-pack.md).")
    ap.add_argument("--lenses", default=",".join(ALL_LENSES), help="The lenses allowed (review.lenses).")
    ap.add_argument("--no-select", action="store_true", help="Run every lens of --lenses, whatever the change.")
    ap.add_argument("--group-below", type=int, default=150, help="Group lenses under this many changed lines; 0 never.")
    ap.add_argument("--sensitive", action="append", default=[], metavar="GLOB",
                    help="A path pattern that always brings the security lens (review.sensitive_paths).")
    ap.add_argument("--max-diff-lines", type=int, default=1500, help="Largest diff copied into the pack.")
    args = ap.parse_args(argv)

    allowed = [l.strip() for l in args.lenses.split(",") if l.strip()]
    unknown = [l for l in allowed if l not in ALL_LENSES]
    if unknown or not allowed:
        ap.error("unknown lens: %s" % ", ".join(unknown) if unknown else "no lens given")
    cwd = git(["rev-parse", "--show-toplevel"], os.getcwd()).strip()
    merge_base, files, chunks = change(cwd, args.base)
    changed = sum(f["added"] + f["removed"] for f in files.values())
    triggers = security_triggers(files, args.sensitive)
    lenses, skipped = list(allowed), {}
    if not args.no_select and "security" in lenses and not triggers:
        lenses.remove("security")
        skipped["security"] = ("no change to external input, I/O, process execution, queries, HTML rendering, "
                               "authentication, secrets, configuration or dependencies in %d files" % len(files))
    if args.group_below and changed < args.group_below and len(lenses) > 2:
        groups = [[l for l in g if l in lenses] for g in GROUPS_WHEN_SMALL]
        groups = [g for g in groups if g]
    else:
        groups = [[l] for l in lenses]
    result = {"base": args.base, "merge_base": merge_base, "files": len(files), "changed_lines": changed,
              "lenses": lenses, "skipped": skipped, "triggers": triggers[:5], "groups": groups}
    pack = args.out or (os.path.join(args.run_dir, "review-pack.md") if args.run_dir else None)
    if pack:
        write_pack(pack, args, merge_base, files, chunks, result, args.run_dir)
        result["pack"] = os.path.abspath(pack)
    json.dump(result, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
