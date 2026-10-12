#!/usr/bin/env python3
"""check_docs.py — the public documentation tree's own gate.

Checks, all mechanical, no box needed:

1. every relative markdown link in README.md, docs/*.md, AGENTS.md and
   llms.txt resolves: the file exists (inside docs/ for docs pages), and
   the #anchor, if any, is a heading in the target;
2. no docs page links outside docs/ by relative path (the hosted site
   cannot follow those; use a full GitHub URL instead);
3. every docs/*.md page appears in mkdocs.yml's nav and in llms.txt;
4. no `§` cites in public text (the section numbers are private-repo
   references a public reader cannot follow);
5. the README stays a landing page, not the whole manual (size cap).

Run from the repo root: python3 tools/check_docs.py
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_CAP = 40 * 1024
errors = []

def slug(t):
    t = t.lower()
    t = re.sub(r"[^\w\s-]", "", t)
    return re.sub(r"\s+", "-", t.strip())

def headings(path):
    """GitHub anchors of the headings in a markdown file, skipping code fences."""
    out, fence = set(), False
    try:
        text = open(path, encoding="utf-8").read()
    except OSError:
        return out
    for ln in text.splitlines():
        if ln.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        m = re.match(r"^(#{1,6}) (.+?)\s*$", ln)
        if m:
            out.add(slug(m.group(2)))
    return out

LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

def check_file(path, in_docs):
    rel = os.path.relpath(path, ROOT)
    text = open(path, encoding="utf-8").read()
    fence = False
    for n, ln in enumerate(text.splitlines(), 1):
        if ln.lstrip().startswith("```"):
            fence = not fence
            continue
        if fence:
            continue
        if "§" in ln:
            errors.append(f"{rel}:{n}: section cite (§) in public text")
        if "—" in ln:
            errors.append(f"{rel}:{n}: em-dash in prose (the rule: none in public text)")
        for target in LINK.findall(ln):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            if target.startswith(("/", "../", "./..")):
                if in_docs:
                    errors.append(f"{rel}:{n}: relative link leaves docs/: {target}")
                continue
            file_part, _, anchor = target.partition("#")
            tgt = os.path.join(os.path.dirname(path), file_part) if file_part else path
            if not os.path.exists(tgt):
                errors.append(f"{rel}:{n}: link to missing file: {target}")
                continue
            if anchor and os.path.isfile(tgt):
                if slug(anchor) not in headings(tgt):
                    errors.append(f"{rel}:{n}: anchor not a heading in {file_part}: {anchor}")

def main():
    pages = sorted(
        f for f in os.listdir(os.path.join(ROOT, "docs"))
        if f.endswith(".md") and f != "halogen.jpg"
    )
    for f in ("README.md", "AGENTS.md", "llms.txt"):
        p = os.path.join(ROOT, f)
        if os.path.exists(p):
            check_file(p, in_docs=False)
    for f in pages:
        check_file(os.path.join(ROOT, "docs", f), in_docs=True)

    # 3. coverage: mkdocs nav and llms.txt must name every docs page
    nav = open(os.path.join(ROOT, "mkdocs.yml")).read()
    llms = open(os.path.join(ROOT, "llms.txt")).read()
    for f in pages:
        if re.search(rf":\s*{re.escape(f)}\s*$", nav, re.M) is None:
            errors.append(f"mkdocs.yml: docs/{f} is not in nav")
        if f"docs/{f})" not in llms:
            errors.append(f"llms.txt: docs/{f} is not listed")

    # 5. README is a landing page
    size = os.path.getsize(os.path.join(ROOT, "README.md"))
    if size > README_CAP:
        errors.append(f"README.md is {size} bytes; cap is {README_CAP} — move prose into docs/")

    if errors:
        print(f"check_docs: FAIL ({len(errors)})")
        for e in errors:
            print("  " + e)
        sys.exit(1)
    print(f"check_docs: OK ({len(pages)} docs pages, README {size} bytes)")

main()
