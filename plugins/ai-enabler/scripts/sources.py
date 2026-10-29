#!/usr/bin/env python3
"""External sources of context: other repositories, sibling folders and documents
that the pipeline reads, and never writes to.

    sources.py status                 has the person been asked? which sources are there? (JSON)
    sources.py siblings               git repositories in the folders next to the project (JSON)
    sources.py add LOCATION [--name N] [--about TEXT] [--paths GLOB,GLOB] [--ref REF]
                                      LOCATION is a URL, a folder or a document (.md .txt .pdf .html .docx)
    sources.py none                   the person said no source is needed; do not ask again
    sources.py remove NAME            forget a source and what was learned about it
    sources.py check [NAME]           missing, unrecorded, fresh, stale or unreachable, per source (JSON)
    sources.py fetch NAME             clone or update a repository given by URL (read-only copy)
    sources.py record NAME [--expect PATH] [--keep]
    sources.py next-delta NAME SLUG   path of the next delta for that source
    sources.py reset NAME             forget what was learned, to learn it again
    sources.py text FILE.docx         the document as Markdown, on stdout

Everything lives in .enabler/sources/ next to the runs, kept out of git by a
.gitignore of its own. A repository given by URL is cloned there, shallow; when a
folder next to the project already is a clone of it, that folder is used instead.
Sources are read, never written: the source guard hook refuses edits inside them.
"""

import fnmatch
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import repo_profile as RP              # noqa: E402

SCHEMA = 1
DOC_TYPES = (".md", ".markdown", ".txt", ".pdf", ".html", ".htm", ".docx", ".rst", ".adoc")
URL = re.compile(r"^(https?://|ssh://|git@|git://|file://)|\.git$")
SHA = re.compile(r"^[0-9a-f]{7,40}$")
SKIP_DIRS = {".git", "node_modules", "vendor", "dist", "build", "target", ".venv", "venv", "__pycache__",
             ".nx", "coverage", ".enabler", ".idea", ".gradle"}
MAX_WALK = 20000


def now():
    return datetime.now(timezone.utc).isoformat()


def base(root):
    return os.path.join(root, ".enabler", "sources")


def registry_path(root):
    return os.path.join(base(root), "sources.json")


def load(root):
    try:
        with open(registry_path(root), encoding="utf-8") as fh:
            reg = json.load(fh)
        if isinstance(reg, dict) and isinstance(reg.get("sources"), list):
            return reg
    except (OSError, ValueError):
        pass
    return {"schema": SCHEMA, "asked": False, "sources": []}


def save(root, reg):
    RP.keep_local(root)
    reg["schema"] = SCHEMA
    with open(registry_path(root), "w", encoding="utf-8") as fh:
        json.dump(reg, fh, indent=1)


def git(args, cwd=None, timeout=30):
    try:
        out = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, timeout=timeout)
        return out.returncode, out.stdout.decode("utf-8", "replace").strip(), out.stderr.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", str(exc)


def norm_url(url):
    """Comparable form of a git URL: host/owner/name, lowercase, without .git or credentials."""
    u = url.strip().lower()
    u = re.sub(r"^[a-z+]+://", "", u)
    u = re.sub(r"^[^@/]+@", "", u)
    u = re.sub(r":(\d+)/", "/", u)
    u = u.replace(":", "/")
    return re.sub(r"\.git/?$", "", u).rstrip("/")


def strip_credentials(url):
    """https://user:token@host/x -> https://host/x. A token never goes into a file."""
    return re.sub(r"^([a-z+]+://)[^@/]+@", r"\1", url) if re.match(r"^[a-z+]+://", url) else url


def siblings(root):
    """Git repositories next to the project: the person's own clones."""
    parent = os.path.dirname(root)
    found = []
    try:
        names = sorted(os.listdir(parent))
    except OSError:
        return found
    for name in names:
        path = os.path.join(parent, name)
        if path == root or name.startswith(".") or not os.path.isdir(os.path.join(path, ".git")):
            continue
        _, remote, _ = git(["remote", "get-url", "origin"], cwd=path, timeout=5)
        _, branch, _ = git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=path, timeout=5)
        found.append({"name": name, "path": path, "remote": remote or None, "branch": branch or None})
    return found


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "source"


def resolve(root, src):
    """Where to read a source on this machine."""
    if src["kind"] == "repo":
        return os.path.join(base(root), src["name"], "checkout")
    loc = src["location"]
    return loc if os.path.isabs(loc) else os.path.normpath(os.path.join(root, loc))


def add(root, location, name=None, about=None, paths=None, ref=None):
    reg = load(root)
    if ref and SHA.match(ref):
        sys.exit("A commit id cannot be followed as a ref; give a branch or a tag.")
    if URL.search(location):
        if strip_credentials(location) != location:
            sys.stderr.write("Credentials removed from the URL: git uses the ones it already has on this machine.\n")
        location = strip_credentials(location)
    elif not os.path.isabs(location) and os.path.exists(os.path.abspath(location)):
        location = os.path.abspath(location)          # relative to where the person is, first
    for s in reg["sources"]:
        same = (URL.search(location) and norm_url(s.get("url") or s["location"]) == norm_url(location)) or \
            s["location"] == (location if os.path.isabs(location) else os.path.normpath(os.path.join(root, location)))
        if same:
            reg["asked"] = True
            save(root, reg)
            return dict(s, note="already a source")
    entry = {"name": None, "kind": None, "location": location, "about": about or "",
             "paths": paths or [], "ref": ref, "added": now()}
    if URL.search(location):
        match = [s for s in siblings(root) if s["remote"] and norm_url(s["remote"]) == norm_url(location)]
        if match:
            # Already cloned next to the project: read that copy, do not clone again.
            entry.update(kind="folder", location=match[0]["path"], url=location)
            if ref and match[0]["branch"] and match[0]["branch"] != ref:
                entry["warning"] = ("the clone at %s has %s checked out, not %s: it is read as it is"
                                    % (match[0]["path"], match[0]["branch"], ref))
        else:
            entry["kind"] = "repo"
        default = os.path.basename(norm_url(location))
    else:
        full = location if os.path.isabs(location) else os.path.normpath(os.path.join(root, location))
        if os.path.isdir(full):
            entry["kind"] = "folder"
        elif os.path.isfile(full):
            if not full.lower().endswith(DOC_TYPES):
                sys.exit("Not a document type the pipeline reads (%s): %s" % (", ".join(DOC_TYPES), location))
            entry["kind"] = "doc"
        else:
            sys.exit("Nothing found at %s. Give a URL, a folder or a document." % location)
        if os.path.commonpath([full, root]) == full:
            sys.exit("%s is the project itself or a folder that contains it; a source is something else." % full)
        if os.path.commonpath([full, root]) == root and os.path.isdir(full):
            entry["inside_project"] = True
        entry["location"] = full
        default = os.path.splitext(os.path.basename(full.rstrip("/")))[0]
    entry["name"] = slug(name or default)
    if any(s["name"] == entry["name"] for s in reg["sources"]):
        sys.exit("A source named %r exists already. Pass --name to choose another." % entry["name"])
    reg["sources"].append(entry)
    reg["asked"] = True
    save(root, reg)
    return entry


def find(reg, name):
    for s in reg["sources"]:
        if s["name"] == name:
            return s
    sys.exit("No source named %r. Known: %s" % (name, ", ".join(s["name"] for s in reg["sources"]) or "none"))


def in_paths(rel, patterns):
    return not patterns or any(fnmatch.fnmatch(rel, p) or rel.startswith(p.rstrip("*").rstrip("/") + "/")
                               for p in patterns)


def remote_head(url, ref):
    """The commit the remote has for exactly this branch or tag (or its default branch)."""
    wanted = ["refs/heads/%s" % ref, "refs/tags/%s^{}" % ref, "refs/tags/%s" % ref] if ref else ["HEAD"]
    rc, out, _ = git(["ls-remote", url] + ([ "refs/heads/%s" % ref, "refs/tags/%s" % ref] if ref else ["HEAD"]),
                     timeout=20)
    if rc != 0:
        return None
    lines = dict(reversed(l.split("\t", 1)) for l in out.splitlines() if "\t" in l)
    for name in wanted:
        if name in lines:
            return lines[name]
    return None


def fingerprint(root, src):
    """A short string that changes when the source changes, or None when it cannot be read."""
    if src["kind"] == "repo":
        sha = remote_head(src["location"], src.get("ref"))
        return "remote:" + sha if sha else None
    path = resolve(root, src)
    if src["kind"] == "doc":
        try:
            with open(path, "rb") as fh:
                return "file:" + hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            return None
    if not os.path.isdir(path):
        return None
    pats = src.get("paths") or []
    if git(["rev-parse", "--git-dir"], cwd=path, timeout=5)[0] == 0:
        # Only this folder, and only its `paths`, even inside a larger repository: a commit
        # elsewhere in the repository is not a change of this source.
        spec = [":(glob)%s" % p for p in pats] or ["."]
        _, last, _ = git(["log", "-1", "--format=%H", "--"] + spec, cwd=path, timeout=30)
        _, dirty, _ = git(["status", "--porcelain", "--untracked-files=all", "--"] + spec, cwd=path, timeout=30)
        _, diff, _ = git(["diff", "HEAD", "--"] + spec, cwd=path, timeout=60)
        h = hashlib.sha256((dirty + "\n" + diff).encode())
        for line in dirty.splitlines()[:500]:
            if line.startswith("??"):
                try:
                    with open(os.path.join(path, line[3:].strip().strip('"')), "rb") as fh:
                        h.update(fh.read())
                except OSError:
                    pass
        return "git:%s:%s" % (last or "none", h.hexdigest()[:16])
    h, n = hashlib.sha256(), 0
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for f in sorted(filenames):
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, path).replace(os.sep, "/")
            if not in_paths(rel, pats):
                continue
            try:
                st = os.stat(full)
            except OSError:
                continue
            h.update(("%s|%d|%d\n" % (rel, st.st_size, st.st_mtime_ns)).encode())
            n += 1
        if n >= MAX_WALK:
            break
    return "walk:%s" % h.hexdigest()


def commit_of(fp):
    """The commit inside a fingerprint, for `git diff <old>..HEAD`."""
    if fp and fp.startswith(("remote:", "git:")):
        c = fp.split(":")[1]
        return c if SHA.match(c) else None
    return None


def src_dir(root, name):
    return os.path.join(base(root), name)


def state(root, name):
    try:
        with open(os.path.join(src_dir(root, name), "state.json"), encoding="utf-8") as fh:
            st = json.load(fh)
        return st if isinstance(st, dict) and st.get("fingerprint") else None
    except (OSError, ValueError):
        return None


def deltas(root, name):
    d = os.path.join(src_dir(root, name), "deltas")
    if not os.path.isdir(d):
        return []
    names = [f for f in os.listdir(d) if f.endswith(".md")]
    return sorted(names, key=lambda n: (RP.delta_number(n) is None, RP.delta_number(n) or 0, n))


def check_one(root, src):
    d = src_dir(root, src["name"])
    profile = os.path.join(d, "profile.md")
    out = {"name": src["name"], "kind": src["kind"], "about": src.get("about", ""), "paths": src.get("paths") or [],
           "read_at": resolve(root, src), "profile": profile, "deltas": len(deltas(root, src["name"])),
           # How to name it to someone else: a URL or a document name, never a local path.
           "cite_as": src.get("url") or (src["location"] if src["kind"] == "repo" else os.path.basename(src["location"]))}
    fp = fingerprint(root, src)
    readable = os.path.exists(out["read_at"])
    if fp is None:
        out["status"] = "unreachable"
        out["usable"] = readable and os.path.isfile(profile)
        return out
    out["fingerprint"] = fp
    if src["kind"] == "repo" and not os.path.isdir(os.path.join(out["read_at"], ".git")):
        out["needs_fetch"] = True
    os.makedirs(d, exist_ok=True)
    st = state(root, src["name"])
    if not os.path.isfile(profile):
        out["status"] = "missing"
    elif st is None:
        out["status"] = "unrecorded"
    else:
        out["status"] = "fresh" if st["fingerprint"] == fp else "stale"
        out["fingerprint"] = fp
        out["recorded_commit"] = commit_of(st["fingerprint"])
        if out["status"] == "stale" and src["kind"] == "repo":
            out["needs_fetch"] = True
    if out["status"] != "fresh":
        with open(os.path.join(d, "pending.json"), "w", encoding="utf-8") as fh:
            json.dump({"fingerprint": fp}, fh)
    return out


def check(root, name=None):
    RP.keep_local(root)
    reg = load(root)
    chosen = [find(reg, name)] if name else reg["sources"]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:          # URL sources ask their remote at the same time
        results = list(pool.map(lambda s: check_one(root, s), chosen))
    return {"root": root, "asked": reg.get("asked", False), "sources": results}


def fetch(root, name):
    src = find(load(root), name)
    if src["kind"] != "repo":
        sys.exit("%s is a %s: it is read where it is, there is nothing to fetch." % (name, src["kind"]))
    dest = resolve(root, src)
    ref = src.get("ref")
    if not os.path.isdir(os.path.join(dest, ".git")):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        args = ["clone", "--depth", "1", "--quiet"] + (["--branch", ref] if ref else []) + [src["location"], dest]
        rc, _, err = git(args, timeout=600)
        if rc != 0:
            sys.exit("Could not clone %s: %s" % (src["location"], err.splitlines()[-1] if err else "unknown error"))
    else:
        rc, _, err = git(["fetch", "--depth", "1", "--quiet", "origin", ref or "HEAD"], cwd=dest, timeout=600)
        if rc != 0:
            sys.exit("Could not update %s: %s" % (name, err.splitlines()[-1] if err else "unknown error"))
        # The copy is ours and read-only: it always matches the remote exactly.
        git(["reset", "--hard", "--quiet", "FETCH_HEAD"], cwd=dest, timeout=60)
        git(["clean", "-fdq"], cwd=dest, timeout=60)
    _, head, _ = git(["rev-parse", "HEAD"], cwd=dest)
    return {"name": name, "read_at": dest, "commit": head}


def record(root, name, expect=None, keep=False):
    src = find(load(root), name)
    d = src_dir(root, name)
    if not os.path.isfile(os.path.join(d, "profile.md")):
        sys.exit("There is no profile for %s to record." % name)
    if expect and (not os.path.isfile(expect) or os.path.getsize(expect) == 0):
        sys.exit("Not recorded: %s was not written." % expect)
    previous = state(root, name)
    pending = os.path.join(d, "pending.json")
    if keep and previous:
        fp = previous["fingerprint"]
    else:
        try:
            with open(pending, encoding="utf-8") as fh:
                fp = json.load(fh)["fingerprint"]
        except (OSError, ValueError, KeyError):
            fp = fingerprint(root, src)
        if fp is None:
            sys.exit("%s cannot be read now; nothing recorded." % name)
    if not keep and os.path.isfile(pending):
        os.remove(pending)
    with open(os.path.join(d, "state.json"), "w", encoding="utf-8") as fh:
        json.dump({"schema": SCHEMA, "fingerprint": fp, "recorded": now(), "deltas": len(deltas(root, name))}, fh)
    return {"name": name, "recorded": fp}


def next_delta(root, name, text):
    find(load(root), name)
    d = os.path.join(src_dir(root, name), "deltas")
    os.makedirs(d, exist_ok=True)
    nums = [n for n in (RP.delta_number(x) for x in deltas(root, name)) if n is not None]
    return os.path.join(d, "delta-%03d-%s.md" % (max(nums) + 1 if nums else 1, slug(text)))


def reset(root, name):
    find(load(root), name)
    d = src_dir(root, name)
    removed = 0
    for rel in ("profile.md", "state.json", "pending.json"):
        p = os.path.join(d, rel)
        if os.path.isfile(p):
            os.remove(p)
            removed += 1
    dd = os.path.join(d, "deltas")
    if os.path.isdir(dd):
        removed += len(os.listdir(dd))
        shutil.rmtree(dd)
    return {"name": name, "removed": removed}


def remove(root, name):
    reg = load(root)
    find(reg, name)
    reg["sources"] = [s for s in reg["sources"] if s["name"] != name]
    save(root, reg)
    d = src_dir(root, name)
    if os.path.isdir(d):
        shutil.rmtree(d)          # what was learned and our own clone; never the person's folder
    return {"removed": name}


# --- .docx to Markdown, with the standard library only ---------------------------------------

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _styles(z):
    """styleId -> heading level (0 for a title), from word/styles.xml. Style ids are translated
    in each language (Heading1, berschrift1, Titre1, Titolo2...); the style *name* is not."""
    levels = {}
    try:
        root = ElementTree.fromstring(z.read("word/styles.xml"))
    except (KeyError, ElementTree.ParseError):
        return levels
    for st in root.iter(W + "style"):
        sid = st.get(W + "styleId") or ""
        name_el = st.find(W + "name")
        name = (name_el.get(W + "val") if name_el is not None else "") or ""
        m = re.match(r"(?i)^heading\s*(\d)$", name.strip())
        lvl = st.find("%spPr/%soutlineLvl" % (W, W))
        if m:
            levels[sid] = int(m.group(1))
        elif name.strip().lower() == "title":
            levels[sid] = 0
        elif lvl is not None and (lvl.get(W + "val") or "").isdigit() and int(lvl.get(W + "val")) < 9:
            levels[sid] = int(lvl.get(W + "val")) + 1
    return levels


def _runs_text(node, cell=False):
    parts = []
    for el in node.iter():
        if el.tag == W + "t":
            parts.append(el.text or "")
        elif el.tag == W + "tab":
            parts.append("\t")
        elif el.tag in (W + "br", W + "cr"):
            parts.append("<br>" if cell else "\n")
    return "".join(parts).strip()


def _para(p, levels):
    text = _runs_text(p)
    if not text:
        return ""
    ppr = p.find(W + "pPr")
    sval = ""
    if ppr is not None:
        st = ppr.find(W + "pStyle")
        sval = (st.get(W + "val") if st is not None else "") or ""
        ol = ppr.find(W + "outlineLvl")
        if ol is not None and (ol.get(W + "val") or "").isdigit() and int(ol.get(W + "val")) < 9:
            return "#" * min(int(ol.get(W + "val")) + 1, 6) + " " + text
    if sval in levels:
        return "#" * max(1, min(levels[sval], 6)) + " " + text
    m = re.match(r"(?i)^heading(\d)$", sval)
    if m:
        return "#" * min(int(m.group(1)), 6) + " " + text
    if (ppr is not None and ppr.find(W + "numPr") is not None) or sval.lower().startswith("list"):
        return "- " + text
    return text


def _cell_text(tc):
    bits = []
    for el in tc:
        if el.tag == W + "p":
            bits.append(_runs_text(el, cell=True))
        elif el.tag == W + "tbl":                      # a table inside a cell: its rows, flattened
            for tr in el.iter(W + "tr"):
                bits.append(" / ".join(_runs_text(c, cell=True) for c in tr.findall(W + "tc")))
        elif el.tag == W + "sdt":
            bits.append(_runs_text(el, cell=True))
    return "<br>".join(b for b in bits if b).replace("|", "\\|").strip()


def _table(tbl):
    rows = [[_cell_text(tc) for tc in tr.findall(W + "tc")] for tr in tbl.findall(W + "tr")]
    rows = [r for r in rows if r]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _blocks(parent, levels):
    out = []
    for child in list(parent):
        if child.tag == W + "p":
            out.append(_para(child, levels))
        elif child.tag == W + "tbl":
            out.append(_table(child))
        elif child.tag == W + "sdt":                   # content controls, common in templates
            content = child.find(W + "sdtContent")
            if content is not None:
                out.extend(_blocks(content, levels))
    return out


def docx_text(path):
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml")
            levels = _styles(z)
        body = ElementTree.fromstring(xml).find(W + "body")
    except (OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        sys.exit("Cannot read %s as a .docx file: %s" % (path, exc))
    blocks = _blocks(body, levels) if body is not None else []
    return "\n\n".join(b for b in blocks if b) + "\n"


def opt(args, flag):
    if flag in args:
        i = args.index(flag)
        if i + 1 < len(args):
            return args[i + 1]
    return None


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "status"
    root = RP.project_root()
    if cmd == "status":
        reg = load(root)
        print(json.dumps({"root": root, "asked": reg.get("asked", False),
                          "sources": [{"name": s["name"], "kind": s["kind"], "about": s.get("about", ""),
                                       "read_at": resolve(root, s),
                                       "cite_as": s.get("url") or (s["location"] if s["kind"] == "repo"
                                                                   else os.path.basename(s["location"]))}
                                      for s in reg["sources"]]}, indent=1))
    elif cmd == "siblings":
        known = {s["location"] for s in load(root)["sources"]}
        print(json.dumps([dict(s, already_a_source=s["path"] in known) for s in siblings(root)], indent=1))
    elif cmd == "add" and len(args) > 1:
        paths = opt(args, "--paths")
        print(json.dumps(add(root, args[1], name=opt(args, "--name"), about=opt(args, "--about"),
                             paths=[p.strip() for p in paths.split(",") if p.strip()] if paths else None,
                             ref=opt(args, "--ref")), indent=1))
    elif cmd == "none":
        reg = load(root)
        reg["asked"] = True
        save(root, reg)
        print(json.dumps({"asked": True, "sources": len(reg["sources"])}))
    elif cmd == "remove" and len(args) > 1:
        print(json.dumps(remove(root, args[1])))
    elif cmd == "check":
        print(json.dumps(check(root, args[1] if len(args) > 1 else None), indent=1))
    elif cmd == "fetch" and len(args) > 1:
        print(json.dumps(fetch(root, args[1])))
    elif cmd == "record" and len(args) > 1:
        print(json.dumps(record(root, args[1], expect=opt(args, "--expect"), keep="--keep" in args)))
    elif cmd == "next-delta" and len(args) > 2:
        print(next_delta(root, args[1], args[2]))
    elif cmd == "reset" and len(args) > 1:
        print(json.dumps(reset(root, args[1])))
    elif cmd == "text" and len(args) > 1:
        sys.stdout.write(docx_text(args[1]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
