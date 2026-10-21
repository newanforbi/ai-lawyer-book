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
SUBTITLE = "A Framework for Modern Self-Representation"
FULL_TITLE = f"{TITLE}: {SUBTITLE}"
COVER_SRC = ROOT / "cover-art" / "The_AI_Lawyer_Front_Cover_1600x2400_upscaled.jpg"
COVER_IMG = "OEBPS/images/cover.jpg"
COVER_XHTML = "OEBPS/cover.xhtml"
# The copyright/disclaimer block starts with this paragraph; it gets its own
# file so it always begins on a new screen after the title page.
COPYRIGHT_MARK = "Copyright \u00a9"
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
    """'CHAPTER 1' + title -> 'Chapter 1: The Access-to-Justice Crisis'."""
    words = label.split()
    if words and words[0].isupper() and len(words[0]) > 1:
        # Title-case the keyword; keep roman numerals / numbers / letters as-is.
        words[0] = words[0].capitalize()
        label = " ".join(words)
    if not title or title.upper() == label.upper():
        return label
    return f"{label}: {title}"


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
        sections[0]["label"] = "Title Page"
        sections[0]["title"] = None
        front = sections[0]["els"]
        cut = next(
            (i for i, el in enumerate(front) if plain(el[3]).startswith(COPYRIGHT_MARK)),
            None,
        )
        if cut:
            sections[0]["els"] = front[:cut]
            sections.insert(
                1, {"els": front[cut:], "label": "Copyright", "title": None}
            )
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
            # Parts and chapters only; subheads would make the TOC
            # hundreds of entries long on a phone.
            "children": [],
        }
        if label == "COPYRIGHT":
            continue  # follows the title page; not a TOC entry
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
    cls = "toc-part" if depth == 1 else "toc-chapter"
    items = []
    for n in nodes:
        inner = f'<a href="{n["href"]}">{html.escape(n["label"])}</a>'
        if n["children"]:
            inner += "\n" + render_nav_ol(n["children"], depth + 1) + pad
        items.append(f'{pad}<li class="{cls}">{inner}</li>')
    return f'<ol class="toc-list toc-depth{depth}">\n' + "\n".join(items) + "\n" + "  " * (depth - 1) + "</ol>"


def render_toc_xhtml(tree):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head>'
        f"<title>{TITLE}</title>"
        '<link href="styles/stylesheet.css" rel="stylesheet" type="text/css"/>'
        "</head><body class=\"toc-page\">"
        '<nav epub:type="toc" id="toc"><h1 class="toc-title">Contents</h1>\n'
        + render_nav_ol(tree)
        + "\n</nav>"
        '<nav epub:type="landmarks" id="landmarks" hidden="hidden"><ol>'
        '<li><a epub:type="cover" href="cover.xhtml">Cover</a></li>'
        '<li><a epub:type="toc" href="toc.xhtml">Contents</a></li>'
        f'<li><a epub:type="bodymatter" href="{tree_first_body(tree)}">Start</a></li>'
        "</ol></nav></body></html>"
    )


def tree_first_body(tree):
    """First real content after the front matter (the Prelude / Part I)."""
    for n in tree:
        if n["label"] not in ("Title Page", "Copyright"):
            return n["href"]
    return tree[0]["href"]


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


TOC_CSS = """
/* Table of contents (nav document) */
body.toc-page { font-family: 'EB Garamond 12', Georgia, serif; }
h1.toc-title {
  font-family: 'Montserrat', sans-serif;
  font-weight: bold;
  font-size: 1.3em;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  text-align: center;
  margin: 1.5em 0 1.2em 0;
}
ol.toc-list { list-style-type: none; margin: 0; padding: 0; }
ol.toc-depth2 { margin: 0.3em 0 0.6em 0; padding: 0; }
li.toc-part {
  list-style-type: none;
  margin: 0.9em 0 0 0;
  font-family: 'Montserrat', sans-serif;
  font-weight: bold;
  font-size: 0.85em;
  letter-spacing: 0.03em;
}
li.toc-chapter {
  list-style-type: none;
  margin: 0.35em 0 0 1.4em;
  text-indent: -0.6em;
  font-family: 'EB Garamond 12', Georgia, serif;
  font-weight: normal;
  font-size: 1.12em;
  letter-spacing: 0;
}
nav#toc a, nav#landmarks a { color: inherit; text-decoration: none; }
/* Cover */
body.cover-page { margin: 0; padding: 0; text-align: center; }
div.cover-wrap { margin: 0; padding: 0; height: 100%; text-align: center; }
div.cover-wrap svg { width: 100%; height: 100%; }
/* Copyright page: its own file; a break is requested for older readers too */
body.copyright-page { page-break-before: always; }
"""

COVER_DOC = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml" '
    'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>Cover</title>'
    '<link href="styles/stylesheet.css" rel="stylesheet" type="text/css"/>'
    '</head><body class="cover-page" epub:type="cover"><div class="cover-wrap">'
    '<svg xmlns="http://www.w3.org/2000/svg" '
    'xmlns:xlink="http://www.w3.org/1999/xlink" version="1.1" '
    'width="100%" height="100%" viewBox="0 0 {w} {h}" '
    'preserveAspectRatio="xMidYMid meet">'
    '<image width="{w}" height="{h}" xlink:href="images/cover.jpg"/>'
    "</svg></div></body></html>"
)


def add_cover_and_metadata(blob, opf, first_href):
    """Embed the cover (EPUB3 cover-image + EPUB2 meta) and fix the title."""
    from PIL import Image

    with Image.open(COVER_SRC) as im:
        w, h = im.size
    blob[COVER_IMG] = COVER_SRC.read_bytes()
    blob[COVER_XHTML] = COVER_DOC.format(w=w, h=h).encode("utf-8")

    opf = re.sub(r"<dc:title[^>]*>.*?</dc:title>",
                 f"<dc:title>{html.escape(FULL_TITLE)}</dc:title>", opf, flags=re.S)
    opf = re.sub(r'<meta content="cover-image" name="cover"/>', "", opf)
    opf = opf.replace("</metadata>",
                      '<meta content="cover-image" name="cover"/></metadata>')
    opf = re.sub(r'<item href="images/cover\.jpg"[^>]*/>', "", opf)
    opf = re.sub(r'<item href="cover\.xhtml"[^>]*/>', "", opf)
    opf = opf.replace(
        "</manifest>",
        '<item href="images/cover.jpg" id="cover-image" media-type="image/jpeg" '
        'properties="cover-image"/>'
        '<item href="cover.xhtml" id="cover" media-type="application/xhtml+xml" '
        'properties="svg"/></manifest>',
    )
    opf = re.sub(r"(<spine[^>]*>)", r'\1<itemref idref="cover" linear="yes"/>', opf)
    # Printed-style contents page right after the copyright page.
    after = "sec1" if 'idref="sec1"' in opf else "sec0"
    opf = opf.replace(f'<itemref idref="{after}"/>',
                      f'<itemref idref="{after}"/><itemref idref="toc.xhtml"/>', 1)
    # EPUB2 guide for older Kindle tooling
    opf = re.sub(r"<guide>.*?</guide>", "", opf, flags=re.S)
    opf = opf.replace(
        "</package>",
        '<guide><reference href="cover.xhtml" title="Cover" type="cover"/>'
        '<reference href="toc.xhtml" title="Contents" type="toc"/>'
        f'<reference href="{first_href}" title="Start" type="text"/></guide></package>',
    )
    return opf


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
        head = HEAD.format(title=TITLE)
        if s["label"] == "Copyright":
            head = head.replace('class="body0"', 'class="body0 copyright-page"')
        doc = head + s["html"] + TAIL
        blob[SECTION_FMT.format(i + 1)] = doc.encode("utf-8")

    opf_name = next(n for n in blob if n.endswith(".opf"))
    opf, uid = rewrite_opf(blob[opf_name].decode("utf-8"), sections)
    opf = add_cover_and_metadata(blob, opf, tree_first_body(tree))
    blob[opf_name] = opf.encode("utf-8")

    blob["OEBPS/toc.xhtml"] = render_toc_xhtml(tree).encode("utf-8")
    blob["OEBPS/toc.ncx"] = render_ncx(tree, uid).encode("utf-8")

    css = blob[CSS_PATH].decode("utf-8")
    if "font-size: inherit" not in css:
        anchor = css.rfind("@font-face")
        cut = css.find("\n", anchor) + 1 if anchor != -1 else 0
        css = css[:cut] + HEADING_RESET + css[cut:]
    if "body.toc-page" not in css:
        css += TOC_CSS
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
