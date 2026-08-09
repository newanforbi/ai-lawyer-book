#!/usr/bin/env python3
"""Give the EPUB real headings, real chapter files, and real navigation.

LibreOffice exports the entire 350-page book as one 955KB `section0001.xhtml`
in which every line -- chapter titles included -- is an anonymous
`<p class="paraN"><span class="spanN">`. There are no heading elements at all,
and both `toc.xhtml` and `toc.ncx` contain a single flat entry labelled
"Section 1". So the book ships with no working table of contents and one
enormous spine item, which is also the usual cause of sluggish page turns and
position drift on-device.

This rebuilds the structure that was always implicit in the markup:

  * the empty `para1` paragraphs are the manuscript's page-break markers, one
    before each part, chapter and back-matter section;
  * the `para2` paragraph right after each is the label ("PART I", "CHAPTER 7",
    "APPENDIX A"), and the paragraph after that is the title;
  * `para5` paragraphs are the subheads within a chapter.

Those become `<h1>`/`<h2>` elements, the book is split into one file per
section, and both navigation documents are regenerated with parts containing
their chapters and chapters containing their subheads.

Rendering is unchanged. The headings keep the same class names, and a reset is
added to the stylesheet so the browser's default heading sizes and margins do
not disturb the design -- in particular so the `em` font sizes on the inner
spans still resolve against body text rather than an `h1`'s 2em.

Re-entrant: it reads whatever section files exist, concatenates them and
re-derives everything, so running it twice is a no-op rather than a corruption.
"""

import argparse
import html
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EPUB = ROOT / "exports" / "The_AI_Lawyer_D2D_Ready.epub"

TITLE = "The AI Lawyer"
SECTION_FMT = "OEBPS/sections/section{:04d}.xhtml"
CSS_PATH = "OEBPS/styles/stylesheet.css"

HEAD = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title>'
    '<meta content="text/html; charset=UTF-8" http-equiv="content-type"/>'
    '<link href="../styles/stylesheet.css" rel="stylesheet" type="text/css"/>'
    '</head><body class="body0" xmlns:epub="http://www.idpf.org/2007/ops">'
)
TAIL = "</body></html>"

# Browser defaults for h1-h6 would otherwise override the design: the margins
# come from the .paraN classes, and an h1's default 2em would rescale the
# relative font-size on the span inside it.
HEADING_RESET = (
    "h1, h2, h3, h4, h5, h6 {\n"
    "  font-size: inherit;\n"
    "  font-weight: inherit;\n"
    "  font-style: inherit;\n"
    "  margin: 0;\n"
    "  padding: 0;\n"
    "}\n"
)

BREAK_CLASS = "para1"   # empty paragraph carrying the page break
LABEL_CLASS = "para2"   # "PART I" / "CHAPTER 7" / "APPENDIX A"
SUBHEAD_CLASS = "para5"  # subheads within a section

ELEMENT_RE = re.compile(r"<(p|h[1-6]) class=\"(para\d+)\"([^>]*)>(.*?)</\1>", re.S)


def plain(markup):
    return html.unescape(re.sub(r"<[^>]+>", "", markup)).strip()


def read_body(xhtml):
    m = re.search(r"<body[^>]*>(.*)</body>", xhtml, re.S)
    return m.group(1) if m else ""


def parse(body):
    """Flat list of (tag, class, attrs, inner). Asserts nothing else is present."""
    els = ELEMENT_RE.findall(body)
    stripped = ELEMENT_RE.sub("", body).strip()
    if stripped:
        sys.exit(f"unexpected non-paragraph content in body: {stripped[:200]!r}")
    return els


def nav_label(label, title):
    if not title or title.upper() == label.upper():
        return label
    return f"{label} — {title}"


def build_sections(els):
    """Split the paragraph stream into sections at the page-break markers."""
    starts = [
        i
        for i, (tag, cls, attrs, inner) in enumerate(els)
        if cls == BREAK_CLASS
        and not plain(inner)
        and i + 1 < len(els)
        and els[i + 1][1] == LABEL_CLASS
    ]
    if not starts:
        sys.exit("found no chapter breaks; the export format must have changed")

    bounds = [0] + starts + [len(els)]
    sections = []
    for n in range(len(bounds) - 1):
        chunk = els[bounds[n] : bounds[n + 1]]
        if not chunk:
            continue
        label = title = None
        for i, (tag, cls, attrs, inner) in enumerate(chunk):
            if cls == LABEL_CLASS:
                label = plain(inner)
                if i + 1 < len(chunk):
                    title = plain(chunk[i + 1][3])
                break
        sections.append({"els": chunk, "label": label, "title": title})

    # Everything before the first break is front matter and has no label.
    if sections and sections[0]["label"] is None:
        sections[0]["label"] = "Front Matter"
        sections[0]["title"] = None
    return sections


def mark_headings(section, index):
    """Rewrite the label paragraph to <h1> and subheads to <h2>, adding ids."""
    out = []
    sub = 0
    section["subheads"] = []
    for tag, cls, attrs, inner in section["els"]:
        attrs = re.sub(r'\s*id="[^"]*"', "", attrs)
        if cls == LABEL_CLASS:
            out.append(f'<h1 class="{cls}" id="sec{index}"{attrs}>{inner}</h1>')
        elif cls == SUBHEAD_CLASS:
            hid = f"sec{index}-{sub}"
            section["subheads"].append({"id": hid, "text": plain(inner)})
            sub += 1
            out.append(f'<h2 class="{cls}" id="{hid}"{attrs}>{inner}</h2>')
        else:
            out.append(f'<p class="{cls}"{attrs}>{inner}</p>')
    section["html"] = "".join(out)
    section["href"] = SECTION_FMT.format(index + 1).replace("OEBPS/", "")
    section["id"] = f"sec{index}"
    return section


def build_tree(sections):
    """Parts contain their chapters; everything else stays top level."""
    tree = []
    current_part = None
    for s in sections:
        label = (s["label"] or "").upper()
        node = {
            "label": nav_label(s["label"], s["title"]),
            "href": s["href"],
            "anchor": s["id"],
            "children": [
                {"label": h["text"], "href": f"{s['href']}#{h['id']}", "children": []}
                for h in s["subheads"]
            ],
        }
        if label.startswith("PART "):
            current_part = node
            tree.append(node)
        elif label.startswith("CHAPTER ") and current_part is not None:
            current_part["children"].append(node)
        else:
            current_part = None
            tree.append(node)
    return tree


def render_nav_ol(nodes, depth=1):
    pad = "  " * depth
    items = []
    for n in nodes:
        inner = f'<a href="{n["href"]}">{html.escape(n["label"])}</a>'
        if n["children"]:
            inner += "\n" + render_nav_ol(n["children"], depth + 1) + pad
        items.append(f"{pad}<li>{inner}</li>")
    return "<ol>\n" + "\n".join(items) + "\n" + "  " * (depth - 1) + "</ol>"


def render_toc_xhtml(tree):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
        f"<title>{TITLE}</title>"
        '<link href="styles/stylesheet.css" rel="stylesheet" type="text/css"/>'
        "</head><body>"
        '<nav epub:type="toc" id="toc"><h1>Contents</h1>\n'
        + render_nav_ol(tree)
        + "\n</nav></body></html>"
    )


def tree_depth(nodes):
    return 1 + max((tree_depth(n["children"]) for n in nodes if n["children"]), default=0)


def render_ncx(tree, uid):
    counter = [0]

    def points(nodes, depth):
        out = []
        for n in nodes:
            counter[0] += 1
            order = counter[0]
            kids = points(n["children"], depth + 1) if n["children"] else ""
            out.append(
                f'<navPoint class="section" id="nav{order}" playOrder="{order}">'
                f"<navLabel><text>{html.escape(n['label'])}</text></navLabel>"
                f'<content src="{n["href"]}"/>{kids}</navPoint>'
            )
        return "".join(out)

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<ncx version="2005-1" xmlns="http://www.daisy.org/z3986/2005/ncx/"><head>'
        f'<meta content="{uid}" name="dtb:uid"/>'
        f'<meta content="{tree_depth(tree)}" name="dtb:depth"/>'
        '<meta content="0" name="dtb:totalPageCount"/>'
        '<meta content="0" name="dtb:maxPageNumber"/>'
        "</head>"
        f"<docTitle><text>{TITLE}</text></docTitle>"
        "<navMap>" + points(tree, 1) + "</navMap></ncx>"
    )


def rewrite_opf(opf, sections):
    uid = re.search(r"<dc:identifier[^>]*>([^<]*)</dc:identifier>", opf)
    uid = uid.group(1) if uid else TITLE

    manifest = re.search(r"<manifest>(.*?)</manifest>", opf, re.S).group(1)
    kept = [
        item
        for item in re.findall(r"<item\b[^>]*/>", manifest)
        if "sections/section" not in item
    ]
    kept += [
        f'<item href="{s["href"]}" id="{s["id"]}" '
        f'media-type="application/xhtml+xml"/>'
        for s in sections
    ]
    opf = re.sub(
        r"<manifest>.*?</manifest>",
        "<manifest>" + "".join(kept) + "</manifest>",
        opf,
        flags=re.S,
    )
    spine = "".join(f'<itemref idref="{s["id"]}"/>' for s in sections)
    opf = re.sub(
        r"<spine([^>]*)>.*?</spine>", rf"<spine\1>{spine}</spine>", opf, flags=re.S
    )
    return opf, uid


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("epub", nargs="?", type=Path, default=EPUB)
    args = ap.parse_args()
    if not args.epub.exists():
        sys.exit(f"missing {args.epub}")

    with zipfile.ZipFile(args.epub) as zf:
        blob = {i.filename: zf.read(i.filename) for i in zf.infolist()}

    old_sections = sorted(n for n in blob if re.match(r"OEBPS/sections/.*\.xhtml$", n))
    if not old_sections:
        sys.exit("no section files found")

    body = "".join(read_body(blob[n].decode("utf-8")) for n in old_sections)
    els = parse(body)

    sections = build_sections(els)
    sections = [mark_headings(s, i) for i, s in enumerate(sections)]
    tree = build_tree(sections)

    for name in old_sections:
        del blob[name]
    for i, s in enumerate(sections):
        doc = HEAD.format(title=TITLE) + s["html"] + TAIL
        blob[SECTION_FMT.format(i + 1)] = doc.encode("utf-8")

    opf_name = next(n for n in blob if n.endswith(".opf"))
    opf, uid = rewrite_opf(blob[opf_name].decode("utf-8"), sections)
    blob[opf_name] = opf.encode("utf-8")

    blob["OEBPS/toc.xhtml"] = render_toc_xhtml(tree).encode("utf-8")
    blob["OEBPS/toc.ncx"] = render_ncx(tree, uid).encode("utf-8")

    css = blob[CSS_PATH].decode("utf-8")
    if "font-size: inherit" not in css:
        anchor = css.rfind("@font-face")
        cut = css.find("\n", anchor) + 1 if anchor != -1 else 0
        css = css[:cut] + HEADING_RESET + css[cut:]
        blob[CSS_PATH] = css.encode("utf-8")

    order = ["mimetype"] + [n for n in blob if n != "mimetype"]
    tmp = args.epub.with_suffix(".epub.tmp")
    with zipfile.ZipFile(tmp, "w") as zf:
        for name in order:
            zf.writestr(
                name,
                blob[name],
                zipfile.ZIP_STORED if name == "mimetype" else zipfile.ZIP_DEFLATED,
            )
    shutil.move(tmp, args.epub)

    tops = len(tree)
    chapters = sum(
        len(n["children"]) for n in tree if n["label"].upper().startswith("PART ")
    )
    subs = sum(len(s["subheads"]) for s in sections)
    h1s = sum(1 for s in sections if s["label"] != "Front Matter")
    biggest = max(len(blob[SECTION_FMT.format(i + 1)]) for i in range(len(sections)))
    print(f"split {args.epub.name}")
    print(f"  files     1 -> {len(sections)} spine items, largest {biggest/1024:.0f}KB "
          f"(was {len(body)/1024:.0f}KB in one)")
    print(f"  headings  {h1s} h1, {subs} h2")
    print(f"  nav       {tops} top-level entries, {chapters} chapters nested "
          f"under parts, {subs} subheads")
    for n in tree[:4]:
        print(f"              {n['label'][:58]}")
        for c in n["children"][:2]:
            print(f"                 {c['label'][:54]}")
    print("              ...")


if __name__ == "__main__":
    main()
