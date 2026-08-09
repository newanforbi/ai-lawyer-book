#!/usr/bin/env python3
"""Post-process the LibreOffice EPUB export into something shippable.

LibreOffice's libepubgen exporter leaves the file in a state that neither
satisfies the EPUB spec nor behaves properly on a Kindle. This script fixes all
of it, idempotently, so it can run after every export instead of being a manual
checklist someone has to remember.

The important one is the font sizes. libepubgen stamps an absolute pt size on
every single run -- 1912 spans of `font-size: 13.0000pt` in the shipped
edition. CSS pt is an absolute length, immune to anything inherited, so the
Kindle reader's "Aa" size control has nothing to act on: readers could not make
the text smaller (or larger) no matter what they picked. That is the bug behind
"the font renders too big on Amazon".

Converting every size to em relative to the body size fixes it. Body text ends
up at exactly 1em -- the reader's own chosen size, no more and no less -- and
the rest of the hierarchy scales in proportion around it. Deliberately *not*
0.9em or similar: pinning body text below the reader's setting would reintroduce
the same class of bug in a milder form.

Also handles the three items the README used to describe as a manual pass:
stripping `direction: ltr` (disallowed in EPUB stylesheets), giving every XHTML
document a <title>, and bundling the fonts with matching @font-face rules and
manifest entries.
"""

import argparse
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EPUB = ROOT / "exports" / "The_AI_Lawyer_D2D_Ready.epub"
FONT_DIR = ROOT / "tools" / "fonts"

TITLE = "The AI Lawyer"

# filename -> (css family, weight, style)
FONT_FACES = {
    "EBGaramond-Regular.ttf": ("EB Garamond 12", "normal", "normal"),
    "EBGaramond-Bold.ttf": ("EB Garamond 12", "bold", "normal"),
    "EBGaramond-Italic.ttf": ("EB Garamond 12", "normal", "italic"),
    "EBGaramond-BoldItalic.ttf": ("EB Garamond 12", "bold", "italic"),
    "Montserrat-Regular.ttf": ("Montserrat", "normal", "normal"),
    "Montserrat-Bold.ttf": ("Montserrat", "bold", "normal"),
    "Montserrat-Italic.ttf": ("Montserrat", "normal", "italic"),
    "Montserrat-BoldItalic.ttf": ("Montserrat", "bold", "italic"),
    "IBMPlexMono-Regular.ttf": ("IBM Plex Mono", "normal", "normal"),
    "IBMPlexMono-Bold.ttf": ("IBM Plex Mono", "bold", "normal"),
    "IBMPlexMono-Italic.ttf": ("IBM Plex Mono", "normal", "italic"),
    "IBMPlexMono-BoldItalic.ttf": ("IBM Plex Mono", "bold", "italic"),
}

CSS_PATH = "OEBPS/styles/stylesheet.css"
FONT_PREFIX = "OEBPS/fonts/"


def detect_base_pt(css, xhtml):
    """The pt size that the most *text* is set in -- i.e. body copy -> 1em.

    Detected rather than hardcoded, because the exported size depends on
    whatever the manuscript is currently set at.

    Weighted by characters, not by number of spans. The monospace prompt blocks
    carry more span elements than the body text does (one per short line), so
    counting elements picks the code font as the baseline and scales the whole
    book up around it.
    """
    sizes = dict(
        re.findall(r"\.(span\d+)\s*\{[^}]*?font-size:\s*([\d.]+)pt", css, re.S)
    )
    if not sizes:
        return None
    weight = {}
    for cls, pt in sizes.items():
        chars = sum(
            len(t) for t in re.findall(
                rf'<span class="{cls}">(.*?)</span>', xhtml, re.S
            )
        )
        weight[float(pt)] = weight.get(float(pt), 0) + chars
    base = max(weight, key=lambda pt: weight[pt])
    share = 100 * weight[base] / max(sum(weight.values()), 1)
    return base, weight[base], share


def rewrite_css(css, base_pt, report):
    # 1. direction: ltr is disallowed in an EPUB stylesheet.
    css, n = re.subn(r"\s*direction:\s*ltr;", "", css)
    report["direction_stripped"] = n

    # 2. Absolute pt sizes -> em, so the reader's font-size control works.
    def to_em(m):
        pt = float(m.group(1))
        em = round(pt / base_pt, 3)
        report["sizes"].setdefault(f"{pt:g}pt", f"{em:g}em")
        return f"font-size: {em:g}em"

    css, n = re.subn(r"font-size:\s*([\d.]+)pt", to_em, css)
    report["sizes_converted"] = n

    # 3. Physical inch margins/indents -> em, so indentation scales with the
    #    text instead of staying pinned at a fixed width on a phone.
    def in_to_em(m):
        inches = float(m.group(2))
        em = round(inches * 72 / base_pt, 3)
        return f"{m.group(1)}{em:g}em"

    css, n = re.subn(r"(-?)([\d.]+)in\b", in_to_em, css)
    report["lengths_converted"] = n

    # 4. Drop the line-height that the manuscript's print leading exports as.
    #    Same reasoning as the font sizes: Kindle has its own line-spacing
    #    control and it should win.
    css, n = re.subn(r"\s*line-height:\s*[\d.]+%;", "", css)
    report["line_heights_stripped"] = n

    # 5. Long prompt/template lines in the monospace blocks have no spaces to
    #    break at and will otherwise run off the side of a narrow screen.
    mono = sorted(
        set(re.findall(r"\.(span\d+)\s*\{[^}]*?font-family:\s*'IBM Plex Mono'", css, re.S))
    )
    for cls in mono:
        block = re.search(rf"\.{cls}\s*\{{[^}}]*\}}", css, re.S)
        if block and "overflow-wrap" in block.group(0):
            continue
        css = re.sub(
            rf"(\.{cls}\s*\{{)",
            r"\1\n  overflow-wrap: break-word;",
            css,
            count=1,
        )
    report["mono_classes"] = mono

    return css


def font_face_block(names):
    lines = []
    for name in sorted(names):
        family, weight, style = FONT_FACES[name]
        lines.append(
            f"@font-face {{ font-family: '{family}'; "
            f"src: url('../fonts/{name}'); "
            f"font-weight: {weight}; font-style: {style}; }}"
        )
    return "\n".join(lines) + "\n"


def ensure_title(xhtml):
    """Give the document a <title>. Required by EPUB, and epubcheck flags it.

    The nav document ships with a self-closing <head/>, so that form has to be
    opened up rather than just appended to.
    """
    if re.search(r"<title>.*?</title>", xhtml, re.S):
        return xhtml, False
    opened, n = re.subn(
        r"<head\s*/>", f"<head><title>{TITLE}</title></head>", xhtml, count=1
    )
    if n:
        return opened, True
    head = re.search(r"<head\b[^>]*>", xhtml)
    if not head:
        return xhtml, False
    return xhtml[: head.end()] + f"<title>{TITLE}</title>" + xhtml[head.end() :], True


def add_manifest_items(opf, names):
    added = []
    items = []
    for i, name in enumerate(sorted(names)):
        if f"fonts/{name}" in opf:
            continue
        items.append(
            f'<item href="fonts/{name}" id="vendored-font-{i}" media-type="font/ttf"/>'
        )
        added.append(name)
    if items:
        opf = opf.replace("</manifest>", "".join(items) + "</manifest>")
    return opf, added


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("epub", nargs="?", type=Path, default=EPUB)
    ap.add_argument("--base-pt", type=float, default=None,
                    help="override the detected body size used as the 1em baseline")
    args = ap.parse_args()

    if not args.epub.exists():
        sys.exit(f"missing {args.epub}")
    fonts = {p.name: p.read_bytes() for p in sorted(FONT_DIR.glob("*.ttf"))}
    unknown = set(fonts) - set(FONT_FACES)
    if unknown:
        sys.exit(f"{FONT_DIR} has faces with no @font-face mapping: {sorted(unknown)}")
    if not fonts:
        sys.exit(f"no fonts in {FONT_DIR}; run tools/vendor_fonts.py first")

    with zipfile.ZipFile(args.epub) as zf:
        entries = [(i.filename, zf.read(i.filename)) for i in zf.infolist()]

    blob = dict(entries)
    css = blob[CSS_PATH].decode("utf-8")
    xhtml_names = [n for n in blob if n.startswith("OEBPS/sections/")]
    sections = "".join(blob[n].decode("utf-8") for n in xhtml_names)

    report = {"sizes": {}}
    detected = detect_base_pt(css, sections)
    if args.base_pt:
        base_pt = args.base_pt
        report["base"] = f"{base_pt:g}pt (forced)"
    elif detected:
        base_pt, chars, share = detected
        report["base"] = f"{base_pt:g}pt ({chars:,} chars, {share:.0f}% of the text)"
    else:
        base_pt = None
        report["base"] = "already relative, nothing to rebase"

    if base_pt:
        css = rewrite_css(css, base_pt, report)
    else:
        css = rewrite_css(css, 1.0, report)  # still strips ltr / line-height

    missing_faces = [n for n in fonts if f"../fonts/{n}" not in css]
    if missing_faces:
        css = font_face_block(missing_faces) + css
    report["font_faces_added"] = missing_faces
    blob[CSS_PATH] = css.encode("utf-8")

    titled = []
    for name in [n for n in blob if n.endswith((".xhtml", ".html"))]:
        text, changed = ensure_title(blob[name].decode("utf-8"))
        if changed:
            blob[name] = text.encode("utf-8")
            titled.append(name)
    report["titles_added"] = titled

    opf_name = next(n for n in blob if n.endswith(".opf"))
    opf, added = add_manifest_items(blob[opf_name].decode("utf-8"), fonts)
    blob[opf_name] = opf.encode("utf-8")
    report["manifest_added"] = added

    for name, data in fonts.items():
        blob[FONT_PREFIX + name] = data

    # Repack. mimetype must be the first entry and stored uncompressed.
    order = ["mimetype"] + [n for n, _ in entries if n != "mimetype"]
    order += [n for n in blob if n not in order]
    tmp = args.epub.with_suffix(".epub.tmp")
    with zipfile.ZipFile(tmp, "w") as zf:
        for name in order:
            if name == "mimetype":
                zf.writestr("mimetype", blob[name], zipfile.ZIP_STORED)
            else:
                zf.writestr(name, blob[name], zipfile.ZIP_DEFLATED)
    shutil.move(tmp, args.epub)

    print(f"fixed {args.epub.name}")
    print(f"  baseline  {report['base']} -> 1em")
    if report["sizes"]:
        print("  sizes     " + ", ".join(
            f"{k}->{v}" for k, v in sorted(
                report["sizes"].items(), key=lambda kv: float(kv[0][:-2]))))
    print(f"  converted {report['sizes_converted']} font-size, "
          f"{report['lengths_converted']} length declarations")
    print(f"  stripped  {report['direction_stripped']} direction:ltr, "
          f"{report['line_heights_stripped']} line-height")
    print(f"  wrapping  overflow-wrap on {', '.join(report['mono_classes']) or 'nothing'}")
    print(f"  fonts     {len(fonts)} embedded "
          f"({len(report['font_faces_added'])} @font-face, "
          f"{len(report['manifest_added'])} manifest entries added)")
    print(f"  titles    {len(report['titles_added'])} added")


if __name__ == "__main__":
    main()
