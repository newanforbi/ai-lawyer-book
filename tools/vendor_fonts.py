#!/usr/bin/env python3
"""Vendor the design fonts into tools/fonts/.

This is a ONE-TIME / on-demand step, not part of tools/build.sh -- it needs
network access. The resulting .ttf files are committed to the repo, and
build.sh installs them into fontconfig before calling soffice.

Two jobs:

1. Extract the eight already-correct faces (Montserrat x4, IBM Plex Mono x4)
   plus EB Garamond Regular/Italic from the last known-good EPUB.

2. Repair the EB Garamond bold faces.

   The EBGaramond-Bold.ttf that shipped in the EPUB is a broken subset: 130
   glyphs, Latin-1 only. It has no curly quotes, no em/en dashes, no ellipsis.
   The manuscript uses all of those inside bold runs, so 133 glyph instances
   were silently falling back to whatever substitute font the renderer picked
   (that is where the stray DejaVuSerif subset in the old PDF came from).
   There was also no BoldItalic face at all, so bold-italic runs -- 142 of
   them -- were being synthetically slanted.

   Both are replaced from @fontsource/eb-garamond, which is the same type
   design: its 400 weight matches the EPUB's EBGaramond12-Regular exactly on
   every metric that matters (capHeight 650, xHeight 400, advance widths
   H=810 n=528 o=495 space=200). The shipped bold was the outlier -- capHeight
   662, xHeight 415 -- it did not even match its own regular.

   The replacements are renamed to the family name the manuscript asks for
   ("EB Garamond 12") and have their vertical metrics forced to match
   EBGaramond-Regular, so line spacing stays uniform across weights.
"""

import html
import io
import re
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "tools" / "fonts"
SOURCE_EPUB = ROOT / "exports" / "The_AI_Lawyer_D2D_Ready.epub"

FONTSOURCE_TGZ = (
    "https://registry.npmjs.org/@fontsource/eb-garamond/-/eb-garamond-5.2.5.tgz"
)

# Faces taken verbatim from the EPUB -- these are complete and correct.
FROM_EPUB = [
    "EBGaramond-Regular.ttf",
    "EBGaramond-Italic.ttf",
    "Montserrat-Regular.ttf",
    "Montserrat-Bold.ttf",
    "Montserrat-Italic.ttf",
    "Montserrat-BoldItalic.ttf",
    "IBMPlexMono-Regular.ttf",
    "IBMPlexMono-Bold.ttf",
    "IBMPlexMono-Italic.ttf",
    "IBMPlexMono-BoldItalic.ttf",
]

# Faces rebuilt from fontsource: (member in tarball, output, subfamily, psname)
REBUILD = [
    (
        "package/files/eb-garamond-latin-700-normal.woff",
        "EBGaramond-Bold.ttf",
        "Bold",
        "EBGaramond12-Bold",
    ),
    (
        "package/files/eb-garamond-latin-700-italic.woff",
        "EBGaramond-BoldItalic.ttf",
        "Bold Italic",
        "EBGaramond12-BoldItalic",
    ),
]

FAMILY = "EB Garamond 12"

MANUSCRIPT = ROOT / "manuscript" / "The_AI_Lawyer_D2D_Ready.docx"


def required_chars(bold, italic):
    """Characters the manuscript actually sets in EB Garamond at this weight/style.

    Derived from the DOCX rather than hardcoded, so each rebuilt face is checked
    against real usage. The Google Fonts "latin" subset omits U+2192 -> for
    example, and that is fine precisely because no bold run contains one.
    """
    doc = zipfile.ZipFile(MANUSCRIPT).read("word/document.xml").decode("utf-8")
    used = set()
    for run in re.findall(r"<w:r>(.*?)</w:r>", doc, re.S):
        props = re.search(r"<w:rPr>(.*?)</w:rPr>", run, re.S)
        props = props.group(1) if props else ""
        family = re.search(r'w:ascii="([^"]+)"', props)
        if not family or family.group(1) != FAMILY:
            continue
        if ("<w:b/>" in props) != bold or ("<w:i/>" in props) != italic:
            continue
        for text in re.findall(r"<w:t[^>]*>(.*?)</w:t>", run, re.S):
            used.update(html.unescape(text))
    # Always demand printable ASCII, even where this particular manuscript
    # happens not to use every letter at this weight.
    used.update(chr(c) for c in range(0x20, 0x7F))
    return used - set("\n\t")


def name_records(font, family, subfamily, psname):
    """Rewrite the name table so fontconfig and the DOCX agree on the family."""
    full = f"{family} {subfamily}"
    values = {1: family, 2: subfamily, 3: f"{psname};vendored", 4: full, 6: psname,
              16: family, 17: subfamily}
    name = font["name"]
    for rec in list(name.names):
        if rec.nameID in values:
            rec.string = values[rec.nameID].encode(
                "utf-16-be" if rec.platformID == 3 else "latin-1"
            )
    for nid, value in values.items():
        if not any(r.nameID == nid for r in name.names):
            name.setName(value, nid, 3, 1, 0x409)


def copy_vertical_metrics(dst, src):
    """Force dst to use src's vertical metrics so leading matches across weights."""
    dst["hhea"].ascent = src["hhea"].ascent
    dst["hhea"].descent = src["hhea"].descent
    dst["hhea"].lineGap = src["hhea"].lineGap
    for attr in (
        "sTypoAscender",
        "sTypoDescender",
        "sTypoLineGap",
        "usWinAscent",
        "usWinDescent",
    ):
        setattr(dst["OS/2"], attr, getattr(src["OS/2"], attr))


def main():
    FONT_DIR.mkdir(parents=True, exist_ok=True)

    if not SOURCE_EPUB.exists():
        sys.exit(f"missing {SOURCE_EPUB}")

    with zipfile.ZipFile(SOURCE_EPUB) as z:
        for face in FROM_EPUB:
            (FONT_DIR / face).write_bytes(z.read(f"OEBPS/fonts/{face}"))
            print(f"  from epub   {face}")

    print(f"  fetching    {FONTSOURCE_TGZ}")
    with urllib.request.urlopen(FONTSOURCE_TGZ, timeout=60) as r:
        blob = r.read()

    regular = TTFont(FONT_DIR / "EBGaramond-Regular.ttf")
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
        for member, out, subfamily, psname in REBUILD:
            data = tar.extractfile(member).read()
            font = TTFont(io.BytesIO(data))
            font.flavor = None  # woff -> plain ttf
            name_records(font, FAMILY, subfamily, psname)
            copy_vertical_metrics(font, regular)
            font.save(FONT_DIR / out)
            font.close()

            check = TTFont(FONT_DIR / out, lazy=True)
            cmap = check.getBestCmap()
            check.close()
            needed = required_chars(bold=True, italic=subfamily == "Bold Italic")
            missing = sorted(c for c in needed if ord(c) not in cmap)
            if missing:
                sys.exit(
                    f"{out}: cannot render {len(missing)} required characters: "
                    + " ".join(f"U+{ord(c):04X}" for c in missing)
                )
            print(
                f"  rebuilt     {out}  ({len(cmap)} mapped, "
                f"covers all {len(needed)} characters the manuscript needs)"
            )
    regular.close()

    print(f"\nvendored {len(FROM_EPUB) + len(REBUILD)} faces into {FONT_DIR}")


if __name__ == "__main__":
    main()
