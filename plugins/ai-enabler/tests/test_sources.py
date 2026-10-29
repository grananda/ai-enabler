#!/usr/bin/env python3
"""Checks external sources: adding them (URL, sibling clone, folder, document), the change
detection, recording, deltas, .docx reading, and the guard that keeps them read-only.

    python3 tests/test_sources.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "sources.py")
GUARD = os.path.join(ROOT, "hooks", "source_guard.py")


def sh(args, cwd, ok=True):
    out = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                         env=dict(os.environ, CLAUDE_PROJECT_DIR=cwd, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                                  GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t"))
    assert (out.returncode == 0) == ok, (args, out.stdout, out.stderr)
    assert "Traceback" not in out.stderr, out.stderr
    return out.stdout.strip()


def src(project, *args, ok=True):
    return sh([sys.executable, SCRIPT] + list(args), project, ok=ok)


def guard(project, tool, tool_input, cwd=None):
    payload = {"tool_name": tool, "tool_input": tool_input, "cwd": cwd or project}
    out = subprocess.run([sys.executable, GUARD], input=json.dumps(payload), text=True, capture_output=True,
                         env=dict(os.environ, CLAUDE_PROJECT_DIR=project))
    return out.returncode


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def make_docx(path):
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = ('<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Billing rules</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Invoices are issued monthly.</w:t></w:r></w:p>'
            '<w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>Only admins may void one.</w:t></w:r></w:p>'
            '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Code</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Meaning</w:t></w:r></w:p></w:tc></w:tr>'
            '<w:tr><w:tc><w:p><w:r><w:t>E1</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Late</w:t></w:r></w:p></w:tc></w:tr></w:tbl>')
    body += ('<w:p><w:pPr><w:pStyle w:val="berschrift2"/></w:pPr><w:r><w:t>Ausnahmen</w:t></w:r></w:p>'
             '<w:sdt><w:sdtContent><w:p><w:r><w:t>Inside a content control.</w:t></w:r></w:p></w:sdtContent></w:sdt>'
             '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>A</w:t><w:br/><w:t>B</w:t></w:r></w:p></w:tc>'
             '<w:tc><w:tbl><w:tr><w:tc><w:p><w:r><w:t>nested</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:tc></w:tr></w:tbl>')
    styles = ('<w:styles xmlns:w="%s"><w:style w:styleId="berschrift2"><w:name w:val="heading 2"/></w:style></w:styles>' % w)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", '<w:document xmlns:w="%s"><w:body>%s</w:body></w:document>' % (w, body))
        z.writestr("word/styles.xml", styles)


def main():
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="ai-enabler-sources-"))
    try:
        project = os.path.join(tmp, "service")
        sibling = os.path.join(tmp, "contracts")            # already cloned next to the project
        upstream = os.path.join(tmp, "upstream.git")        # a remote reachable by URL
        for d in (project, sibling):
            os.makedirs(d)
            sh(["git", "init", "-q"], d)
        write(os.path.join(sibling, "openapi", "orders.yaml"), "paths: {}\n")
        sh(["git", "add", "-A"], sibling)
        sh(["git", "commit", "-qm", "init"], sibling)
        sh(["git", "remote", "add", "origin", "https://git.example.com/team/contracts.git"], sibling)
        seed = os.path.join(tmp, "seed")
        os.makedirs(seed)
        sh(["git", "init", "-q"], seed)
        write(os.path.join(seed, "README.md"), "design system\n")
        sh(["git", "add", "-A"], seed)
        sh(["git", "commit", "-qm", "init"], seed)
        sh(["git", "clone", "-q", "--bare", seed, upstream], tmp)

        # Nothing asked yet; the siblings are offered.
        st = json.loads(src(project, "status"))
        assert st["asked"] is False and st["sources"] == []
        sib = json.loads(src(project, "siblings"))
        assert [s["name"] for s in sib] == ["contracts", "seed"], sib

        # A URL whose clone is already next to the project: that folder is used, nothing is cloned.
        e = json.loads(src(project, "add", "git@git.example.com:team/contracts.git", "--about", "API contracts",
                           "--paths", "openapi/**"))
        assert e["kind"] == "folder" and e["location"] == sibling and e["name"] == "contracts", e
        # A URL with no local clone: a private, read-only copy.
        e = json.loads(src(project, "add", "file://" + upstream, "--name", "design-system"))
        assert e["kind"] == "repo", e
        # A document, including .docx.
        make_docx(os.path.join(tmp, "rules.docx"))
        e = json.loads(src(project, "add", os.path.join(tmp, "rules.docx")))
        assert e["kind"] == "doc" and e["name"] == "rules", e
        src(project, "add", os.path.join(tmp, "nothing-here"), ok=False)
        src(project, "add", ".", ok=False)                               # the project is not its own source
        src(project, "add", "..", ok=False)
        again = json.loads(src(project, "add", os.path.join(tmp, "rules.docx")))
        assert again.get("note") == "already a source"                    # adding twice is harmless
        src(project, "add", "https://git.example.com/x/y.git", "--ref", "a1b2c3d4", ok=False)
        cred = json.loads(src(project, "add", "https://bob:s3cret@git.example.com/team/secret-thing.git"))
        assert "s3cret" not in open(os.path.join(project, ".enabler/sources/sources.json")).read(), cred
        src(project, "remove", cred["name"])
        assert json.loads(src(project, "status"))["asked"] is True

        md = src(project, "text", os.path.join(tmp, "rules.docx"))
        assert md.splitlines()[0] == "# Billing rules" and "- Only admins may void one." in md, md
        assert "| Code | Meaning |" in md and "| E1 | Late |" in md, md
        assert "## Ausnahmen" in md and "Inside a content control." in md, md
        assert "| A<br>B | nested |" in md, md
        bad = os.path.join(tmp, "bad.docx")
        with zipfile.ZipFile(bad, "w") as z:
            z.writestr("word/document.xml", "<w:document")
        src(project, "text", bad, ok=False)                              # an error, not a traceback

        # Check: all missing; the URL one needs fetching first.
        c = {s["name"]: s for s in json.loads(src(project, "check"))["sources"]}
        assert all(s["status"] == "missing" for s in c.values()), c
        assert c["design-system"].get("needs_fetch") and not c["contracts"].get("needs_fetch")
        f = json.loads(src(project, "fetch", "design-system"))
        assert os.path.isfile(os.path.join(f["read_at"], "README.md")), f
        src(project, "fetch", "contracts", ok=False)                     # a folder is read where it is

        # Learn each once, record, and they are fresh.
        for name in c:
            prof = c[name]["profile"]
            src(project, "record", name, "--expect", prof, ok=False)     # not written yet
            write(prof, "# %s\n" % name)
            src(project, "record", name, "--expect", prof)
        c = {s["name"]: s for s in json.loads(src(project, "check"))["sources"]}
        assert all(s["status"] == "fresh" for s in c.values()), c

        # The sibling clone changes (a commit, or an uncommitted edit inside the watched paths): stale.
        write(os.path.join(sibling, "openapi", "orders.yaml"), "paths: {/orders: {}}\n")
        assert json.loads(src(project, "check", "contracts"))["sources"][0]["status"] == "stale"
        # Edits and commits outside the watched paths do not matter.
        src(project, "record", "contracts")
        write(os.path.join(sibling, "notes.txt"), "scratch\n")
        assert json.loads(src(project, "check", "contracts"))["sources"][0]["status"] == "fresh"
        write(os.path.join(sibling, "README.md"), "readme\n")
        sh(["git", "add", "README.md"], sibling)
        sh(["git", "commit", "-qm", "docs"], sibling)
        assert json.loads(src(project, "check", "contracts"))["sources"][0]["status"] == "fresh"
        # A new untracked file inside the paths does, and so does a change to its content.
        write(os.path.join(sibling, "openapi", "users.yaml"), "a\n")
        assert json.loads(src(project, "check", "contracts"))["sources"][0]["status"] == "stale"
        src(project, "record", "contracts")
        write(os.path.join(sibling, "openapi", "users.yaml"), "b\n")
        c2 = json.loads(src(project, "check", "contracts"))["sources"][0]
        assert c2["status"] == "stale" and c2["recorded_commit"], c2
        # The remote moves on: stale, and the private copy must be fetched again.
        sh(["git", "commit", "-q", "--allow-empty", "-m", "next"], seed)
        sh(["git", "push", "-q", upstream, "HEAD:refs/heads/" + sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], seed)], seed)
        d = json.loads(src(project, "check", "design-system"))["sources"][0]
        assert d["status"] == "stale" and d.get("needs_fetch"), d
        assert d["recorded_commit"] and d["cite_as"] == "file://" + upstream, d
        sh(["git", "push", "-q", upstream, "HEAD:refs/heads/feature/" + sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], seed)], seed)
        # A ref is followed exactly: feature/<branch> on the remote is not <branch>.
        branch = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], seed)
        sh(["git", "commit", "-q", "--allow-empty", "-m", "elsewhere"], seed)
        sh(["git", "push", "-q", upstream, "HEAD:refs/heads/feature/" + branch], seed)
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import sources as S
        assert S.remote_head("file://" + upstream, branch) == sh(["git", "rev-parse", "HEAD~1"], seed)
        assert S.remote_head("file://" + upstream, "feature/" + branch) == sh(["git", "rev-parse", "HEAD"], seed)
        delta = src(project, "next-delta", "design-system", "New buttons")
        assert delta.endswith("deltas/delta-001-new-buttons.md"), delta
        write(delta, "# Delta 001\n")
        src(project, "fetch", "design-system")
        src(project, "record", "design-system", "--expect", delta)
        assert json.loads(src(project, "check", "design-system"))["sources"][0]["status"] == "fresh"

        # An unreachable source is reported, and what was learned stays usable.
        src(project, "add", "https://invalid.invalid/nobody/nothing.git", "--name", "gone")
        g = json.loads(src(project, "check", "gone"))["sources"][0]
        assert g["status"] == "unreachable" and g["usable"] is False, g

        # Nothing of this is committed in the project.
        status = sh(["git", "status", "--porcelain", "-uall"], project)
        assert ".enabler" not in status, status

        # The guard: sources are read-only, the project is not.
        assert guard(project, "Write", {"file_path": os.path.join(sibling, "openapi", "orders.yaml")}) == 2
        assert guard(project, "Edit", {"file_path": "../contracts/openapi/orders.yaml"}) == 2
        co = os.path.join(project, ".enabler", "sources", "design-system", "checkout")
        assert guard(project, "Write", {"file_path": os.path.join(co, "README.md")}) == 2
        assert guard(project, "Write", {"file_path": os.path.join(tmp, "rules.docx")}) == 2
        assert guard(project, "Write", {"file_path": os.path.join(project, "src", "a.py")}) == 0
        C = "../contracts"
        blocked = ["echo x > %s/openapi/orders.yaml" % C, "rm -rf %s/openapi" % C,
                   "git -C %s commit -am x" % C, "cd %s && git checkout -b feature" % C,
                   "sed -i s/a/b/ %s/openapi/orders.yaml" % C, "cp src/a.py %s/openapi/" % C,
                   "mv %s/openapi/orders.yaml src/" % C, "FOO=1 touch %s/x" % co,
                   "cd %s && git pull" % sibling,
                   "git --work-tree=%s --git-dir=%s/.git checkout ." % (C, C),
                   "git --work-tree %s --git-dir %s/.git checkout ." % (C, C),
                   "python3 -c \"open('%s/x','w').write('y')\"" % C, "cp -t %s src/a.py" % C,
                   "find %s -name '*.yaml' -delete" % C, "ls %s | xargs rm" % C,
                   "bash -c 'rm %s/openapi/orders.yaml'" % C, "dd if=/dev/zero of=%s/x count=1" % C,
                   "sed --in-place=.bak s/a/b/ %s/openapi/orders.yaml" % C, "pushd %s; rm openapi/orders.yaml" % C,
                   "D=%s; rm $D/openapi/orders.yaml" % C, "git -C %s config user.name x" % C,
                   "git -C %s remote set-url origin x" % C, "git -C %s branch newb" % C,
                   "echo sources.py fetch x; rm %s/openapi/orders.yaml" % C, "git -C %s fetch" % C]
        allowed = ["cat %s/openapi/orders.yaml" % C, "cp %s/openapi/orders.yaml src/" % C,
                   "git -C %s log --oneline -5" % C, "git -C %s diff" % C, "grep -r orders %s" % C,
                   "cd %s && git status && cd ../service && git commit -m x" % C,
                   "python3 /x/scripts/sources.py fetch design-system", "echo hi > src/out.txt",
                   "git commit -am 'touch ../contracts later'", "rsync -a %s/openapi/ ./openapi/" % C,
                   "install %s/openapi/orders.yaml ./orders.yaml" % C, "ln -s %s/openapi ./openapi" % C,
                   "cat > notes.md <<EOF\nrm %s/openapi/orders.yaml\nEOF" % C,
                   "git -C %s branch -a" % C, "git -C %s config --get remote.origin.url" % C,
                   "python3 -c \"print(open('%s/openapi/orders.yaml').read())\"" % C]
        for c_ in blocked:
            assert guard(project, "Bash", {"command": c_}) == 2, ("should block", c_)
        for c_ in allowed:
            assert guard(project, "Bash", {"command": c_}) == 0, ("should allow", c_)

        # Removing a source forgets what was learned and our own copy, never the person's folder.
        src(project, "remove", "contracts")
        assert os.path.isdir(sibling) and not os.path.isdir(os.path.join(project, ".enabler", "sources", "contracts"))
        assert guard(project, "Write", {"file_path": os.path.join(sibling, "openapi", "orders.yaml")}) == 0
        src(project, "reset", "design-system")
        assert json.loads(src(project, "check", "design-system"))["sources"][0]["status"] == "missing"

        # "None needed" is remembered, so the preflight does not ask again.
        other = os.path.join(tmp, "other")
        os.makedirs(other)
        src(other, "none")
        assert json.loads(src(other, "status")) ["asked"] is True
        # Without sources the guard stays out of the way.
        assert guard(other, "Bash", {"command": "rm -rf ../contracts"}) == 0
        print("ok — external sources: %d blocked, %d allowed by the guard" % (len(blocked), len(allowed)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
