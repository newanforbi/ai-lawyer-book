#!/usr/bin/env python3
"""Retypeset the manuscript for a 6x9 paperback interior.

The manuscript was set at 13pt EB Garamond on a US Letter page (8.5x11) with a
6-inch text measure -- a letter-sized document, not a book. This rescales the
whole type hierarchy down one step, moves the page to KDP's standard 6x9 trade
trim with mirrored margins, and opens the leading to suit the narrower measure.

Everything is direct run formatting in this document (word/styles.xml defines
almost nothing and only 199 of ~4000 paragraphs carry a pStyle), so the work is
rewriting <w:sz>/<w:szCs> values in word/document.xml rather than editing
styles.

Operates on the .docx in place. Guarded by a TypographyScale property written
into docProps/custom.xml: the size map's source and target sets overlap, so a
second unguarded run would corrupt sizes. Use --force to override, and
`git checkout manuscript/` to get back to the committed state.
"""

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCX = ROOT / "manuscript" / "The_AI_Lawyer_D2D_Ready.docx"

STAMP_NAME = "TypographyScale"
STAMP_VALUE = "11.5pt-6x9-v1"

# --------------------------------------------------------------------------
# Tunables. Everything the design depends on lives in this block.
# --------------------------------------------------------------------------

# Font sizes, in half-points, as OOXML stores them. Body 13pt -> 11.5pt.
# Applied to both w:sz and w:szCs, in document.xml, styles.xml and footer1.xml.
#
#   half-pt  pt            role
#   26  ->   13.0 -> 11.5  body serif, Montserrat subheads   (3472 runs)
#   22  ->   11.0 ->  9.0  IBM Plex Mono prompt blocks       (2291 runs)
#   20  ->   10.0 ->  9.0  fine print, attributions, footer
#   24  ->   12.0 -> 10.5  styles.xml only (docDefaults, H3)
#   28  ->   14.0 -> 12.0  Montserrat chapter titles
#   32  ->   16.0 -> 14.0
#   36  ->   18.0 -> 15.0  title-page byline
#   40  ->   20.0 -> 16.0  part titles
#   56  ->   28.0 -> 22.0  book title
#
# Mono drops proportionally further than the serif on purpose: the 6x9 text
# measure is 4.5in, and indented Plex Mono at 11pt would wrap badly there.
SIZE_MAP = {
    20: 18,
    22: 18,
    24: 21,
    26: 23,
    28: 24,
    32: 28,
    36: 30,
    40: 32,
    56: 44,
}

# 6x9in trim in twips (1440/inch). Inside margin 0.875in satisfies KDP's
# requirement up to 700 pages, so the margins stay legal even if the reflowed
# page count lands above the estimate. Text block ends up 4.5in x 7.5in, which
# is 62-66 characters per line at 11.5pt EB Garamond.
PAGE = {
    "w": 8640,   # 6.0in
    "h": 12960,  # 9.0in
    "top": 1080,     # 0.75in
    "bottom": 1080,  # 0.75in
    "inside": 1260,  # 0.875in  (w:left, mirrored)
    "outside": 900,  # 0.625in  (w:right, mirrored)
    "header": 720,
    "footer": 720,
}

# Body paragraphs currently carry 6pt before/after and no line spacing at all
# (there is not a single w:line in the document). Open the leading to 1.15 and
# pull the paragraph gap back to 4pt, since the leading now supplies part of
# the separation.
BODY_SPACING_OLD = '<w:spacing w:after="120" w:before="120"/>'
BODY_SPACING_NEW = '<w:spacing w:after="80" w:before="80" w:line="276" w:lineRule="auto"/>'

# Monospace/quote blocks are indented 0.5in, which is a lot of the 4.5in
# measure. Half it. Only the plain left indent -- hanging-indent list items
# are left alone so their bullets stay put.
INDENT_OLD = '<w:ind w:left="720"/>'
INDENT_NEW = '<w:ind w:left="360"/>'

# numbering.xml's list definition specifies bullets none of the three design
# fonts actually contain (U+25CF, U+25CB). Nothing references that definition
# today -- the document has zero <w:numPr>, and its visible bullets are literal
# U+2022 characters in the text -- so this is defensive only, to keep the
# definition renderable if a list is ever attached to it.
BULLETS = {"\u25cf": "\u2022", "\u25cb": "\u25e6", "\u25a0": "\u2013"}

# The 217 empty divider paragraphs inherit the document default, which was
# Georgia -- a leftover from a Google Docs round-trip, not a design choice.
DEFAULT_FONT_OLD = 'w:ascii="Georgia" w:cs="Georgia" w:eastAsia="Georgia" w:hAnsi="Georgia"'
DEFAULT_FONT_NEW = (
    'w:ascii="EB Garamond 12" w:cs="EB Garamond 12" '
    'w:eastAsia="EB Garamond 12" w:hAnsi="EB Garamond 12"'
)

# Element form only. The attribute form w:sz="1" appears 217 times inside
# <w:pBdr><w:bottom .../></w:pBdr> as a border *width* and must not be touched;
# this pattern cannot match it.
SIZE_RE = re.compile(r'<w:(sz|szCs) w:val="(\d+)"\s*/>')


def remap_sizes(xml, counter):
    """Rewrite every w:sz/w:szCs in one pass, so overlapping map entries are safe."""

    def repl(m):
        tag, val = m.group(1), int(m.group(2))
        if val not in SIZE_MAP:
            return m.group(0)
        counter[val] = counter.get(val, 0) + 1
        return f'<w:{tag} w:val="{SIZE_MAP[val]}"/>'

    return SIZE_RE.sub(repl, xml)


def restyle_document(xml, report):
    before_attr = len(re.findall(r'w:sz="\d+"', xml))

    counter = {}
    xml = remap_sizes(xml, counter)
    report["sizes"] = counter

    report["body_paragraphs"] = xml.count(BODY_SPACING_OLD)
    xml = xml.replace(BODY_SPACING_OLD, BODY_SPACING_NEW)

    report["indents"] = xml.count(INDENT_OLD)
    xml = xml.replace(INDENT_OLD, INDENT_NEW)

    old_sect = re.search(r"<w:pgSz [^/]*/><w:pgMar [^/]*/>", xml)
    if not old_sect:
        sys.exit("could not locate <w:pgSz>/<w:pgMar> in the section properties")
    new_sect = (
        f'<w:pgSz w:w="{PAGE["w"]}" w:h="{PAGE["h"]}" w:orient="portrait"/>'
        f'<w:pgMar w:top="{PAGE["top"]}" w:right="{PAGE["outside"]}" '
        f'w:bottom="{PAGE["bottom"]}" w:left="{PAGE["inside"]}" '
        f'w:header="{PAGE["header"]}" w:footer="{PAGE["footer"]}" w:gutter="0"/>'
    )
    report["sectPr"] = (old_sect.group(0), new_sect)
    xml = xml[: old_sect.start()] + new_sect + xml[old_sect.end() :]

    after_attr = len(re.findall(r'w:sz="\d+"', xml))
    assert before_attr == after_attr, (
        f"border widths were modified ({before_attr} -> {after_attr}); "
        "the w:sz element regex leaked into the attribute form"
    )
    return xml


def restyle_styles(xml, report):
    counter = {}
    xml = remap_sizes(xml, counter)
    report["style_sizes"] = counter

    # docDefaults should match body text, not the 10.5pt the generic map lands
    # on, and should not be Georgia.
    def fix_defaults(m):
        block = m.group(0)
        block = re.sub(r'<w:sz w:val="\d+"/>', '<w:sz w:val="23"/>', block)
        block = re.sub(r'<w:szCs w:val="\d+"/>', '<w:szCs w:val="23"/>', block)
        block = block.replace(DEFAULT_FONT_OLD, DEFAULT_FONT_NEW)
        return block

    xml, n = re.subn(r"<w:docDefaults>.*?</w:docDefaults>", fix_defaults, xml, flags=re.S)
    report["docDefaults"] = n
    return xml


def restyle_settings(xml, report):
    """Mirror margins so the wider inside margin lands on the binding edge."""
    if "<w:mirrorMargins/>" in xml:
        report["mirrorMargins"] = "already present"
        return xml
    m = re.search(r"(<w:settings\b[^>]*>)", xml)
    xml = xml[: m.end()] + "<w:mirrorMargins/>" + xml[m.end() :]
    report["mirrorMargins"] = "added"
    return xml


def restyle_numbering(xml, report):
    swapped = {}
    for old, new in BULLETS.items():
        n = xml.count(f'<w:lvlText w:val="{old}"/>')
        if n:
            swapped[f"{old} -> {new}"] = n
            xml = xml.replace(
                f'<w:lvlText w:val="{old}"/>', f'<w:lvlText w:val="{new}"/>'
            )
    report["bullets"] = swapped
    return xml


def restyle_footer(xml, report):
    counter = {}
    xml = remap_sizes(xml, counter)
    xml = xml.replace(DEFAULT_FONT_OLD, DEFAULT_FONT_NEW)
    xml = re.sub(r'w:(ascii|cs|eastAsia|hAnsi)="Georgia"', r'w:\1="EB Garamond 12"', xml)
    report["footer_sizes"] = counter
    return xml


def stamped(zf):
    props = zf.read("docProps/custom.xml").decode("utf-8")
    return STAMP_NAME in props


def add_stamp(xml):
    entry = (
        f'<property fmtid="{{D5CDD505-2E9C-101B-9397-08002B2CF9AE}}" pid="2" '
        f'name="{STAMP_NAME}"><vt:lpwstr>{STAMP_VALUE}</vt:lpwstr></property>'
    )
    # The stub ships as a self-closing <Properties .../> with no children, so
    # opening it up is the common case rather than the exception.
    opened, n = re.subn(r"<Properties\b([^>]*?)\s*/>", r"<Properties\1>", xml, count=1)
    if n:
        return opened + entry + "</Properties>"
    if "</Properties>" not in xml:
        sys.exit("docProps/custom.xml: no <Properties> element to stamp")
    return xml.replace("</Properties>", entry + "</Properties>")


HANDLERS = {
    "word/document.xml": restyle_document,
    "word/styles.xml": restyle_styles,
    "word/settings.xml": restyle_settings,
    "word/numbering.xml": restyle_numbering,
    "word/footer1.xml": restyle_footer,
    "docProps/custom.xml": lambda xml, report: add_stamp(xml),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("docx", nargs="?", type=Path, default=DOCX)
    ap.add_argument("--force", action="store_true",
                    help="restyle again even if already stamped (will double-apply)")
    args = ap.parse_args()

    if not args.docx.exists():
        sys.exit(f"missing {args.docx}")

    with zipfile.ZipFile(args.docx) as zf:
        if stamped(zf) and not args.force:
            print(f"{args.docx.name} already carries {STAMP_NAME}={STAMP_VALUE}; "
                  "nothing to do (use --force to re-apply)")
            return
        items = [(i, zf.read(i.filename)) for i in zf.infolist()]

    report = {}
    out = []
    for info, data in items:
        handler = HANDLERS.get(info.filename)
        if handler:
            xml = handler(data.decode("utf-8"), report)
            data = xml.encode("utf-8")
        out.append((info, data))

    tmp = args.docx.with_suffix(".docx.tmp")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for info, data in out:
            zf.writestr(info, data)
    shutil.move(tmp, args.docx)

    print(f"restyled {args.docx.name}")
    print(f"  page      {PAGE['w']/1440:g}in x {PAGE['h']/1440:g}in, "
          f"inside {PAGE['inside']/1440:g}in / outside {PAGE['outside']/1440:g}in, "
          f"mirrored ({report['mirrorMargins']})")
    text_w = (PAGE["w"] - PAGE["inside"] - PAGE["outside"]) / 1440
    text_h = (PAGE["h"] - PAGE["top"] - PAGE["bottom"]) / 1440
    print(f"  measure   {text_w:g}in x {text_h:g}in")
    print("  sizes     " + ", ".join(
        f"{k/2:g}->{SIZE_MAP[k]/2:g}pt x{v}" for k, v in sorted(report["sizes"].items())))
    print(f"  leading   1.15 on {report['body_paragraphs']} body paragraphs "
          "(was unset), gap 6pt -> 4pt")
    print(f"  indents   0.5in -> 0.25in on {report['indents']} blocks")
    print("  bullets   " + (", ".join(f"{k} x{v}" for k, v in report["bullets"].items())
                            or "none"))
    print(f"  stamped   {STAMP_NAME}={STAMP_VALUE}")


if __name__ == "__main__":
    main()
