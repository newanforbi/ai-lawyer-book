#!/usr/bin/env python3
"""Render the EPUB in a phone-sized browser, and prove the text actually scales.

Two modes:

  --shot      screenshot the reading view at a given reader font size, so a
              before/after comparison can be eyeballed the way the book is
              actually read.

  --measure   the important one. Loads the book at several reader font sizes
              and reports the resulting rendered body text size. If the
              stylesheet uses absolute pt, the measurements stay flat no matter
              what the reader picks -- which is exactly the Kindle "Aa" bug
              this repo's fix_epub.py exists to fix. If it uses em, they track
              the reader's setting proportionally.

Kindle's web reader scales text by setting a base font size on a container, so
driving `html { font-size: ... }` here reproduces what the Aa control does.
"""

import argparse
import json
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
EPUB = ROOT / "exports" / "The_AI_Lawyer_D2D_Ready.epub"

# Matches the screenshot the oversized-font report came from.
VIEWPORT = {"width": 390, "height": 844}

CHROMIUM_CANDIDATES = [
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/opt/pw-browsers/chromium/chrome-linux/chrome",
]

# Reader font sizes to sample, in px. 16px is the browser default.
SAMPLES = [12, 16, 20, 26]


def chromium_path():
    for c in CHROMIUM_CANDIDATES:
        if Path(c).exists():
            return c
    found = sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome"))
    if found:
        return str(found[-1])
    sys.exit("no chromium found under /opt/pw-browsers")


def extract(epub, dest, needle=None, index=None):
    """Unpack, and pick the section worth looking at.

    The book is split into one file per chapter, so there is no single document
    to load. --section wins if given; then --find, which uses whichever section
    contains the passage; otherwise the largest section, which is
    representative body text rather than the title page.
    """
    with zipfile.ZipFile(epub) as zf:
        zf.extractall(dest)
    sections = sorted(Path(dest).glob("OEBPS/sections/*.xhtml"))
    if not sections:
        sys.exit("no OEBPS/sections/*.xhtml in the epub")
    if index is not None:
        if not 1 <= index <= len(sections):
            sys.exit(f"--section must be 1..{len(sections)}")
        return sections[index - 1]
    if needle:
        for s in sections:
            if needle in s.read_text(encoding="utf-8"):
                return s
        sys.exit(f"no section contains {needle!r}")
    return max(sections, key=lambda p: p.stat().st_size)


MEASURE_JS = """
() => {
  const counts = new Map();
  for (const el of document.querySelectorAll('span')) {
    const len = (el.textContent || '').length;
    if (!len) continue;
    const size = getComputedStyle(el).fontSize;
    counts.set(size, (counts.get(size) || 0) + len);
  }
  let best = null, bestChars = -1;
  for (const [size, chars] of counts) {
    if (chars > bestChars) { best = size; bestChars = chars; }
  }
  return { bodyFontSize: best, chars: bestChars };
}
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("epub", nargs="?", type=Path, default=EPUB)
    ap.add_argument("--shot", type=Path, help="write a screenshot here")
    ap.add_argument("--measure", action="store_true",
                    help="report rendered body size across reader font sizes")
    ap.add_argument("--font-size", type=int, default=16,
                    help="reader font size in px for --shot (default 16)")
    ap.add_argument("--find", default=None,
                    help="scroll to the first element containing this text")
    ap.add_argument("--section", type=int, default=None,
                    help="render this spine section by number instead of guessing")
    args = ap.parse_args()

    if not args.epub.exists():
        sys.exit(f"missing {args.epub}")
    if not args.shot and not args.measure:
        ap.error("pass --shot and/or --measure")

    tmp = Path(tempfile.mkdtemp(prefix="epub-preview-"))
    try:
        section = extract(args.epub, tmp, args.find, args.section)
        url = section.as_uri()
        print(f"[{section.name}]")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=chromium_path(), args=["--no-sandbox"]
            )
            page = browser.new_page(viewport=VIEWPORT)

            if args.measure:
                print(f"reader size -> rendered body text   [{args.epub.name}]")
                rows = []
                for px in SAMPLES:
                    page.goto(url)
                    page.add_style_tag(content=f"html {{ font-size: {px}px; }}")
                    page.wait_for_timeout(250)
                    r = page.evaluate(MEASURE_JS)
                    rows.append((px, float(r["bodyFontSize"].rstrip("px"))))
                    print(f"  {px:3}px  ->  {r['bodyFontSize']:>8}")
                spread = rows[-1][1] - rows[0][1]
                if spread < 0.5:
                    print("\n  FAIL: body text does not respond to the reader's "
                          "font size (absolute units are overriding it)")
                    sys.exit(1)
                ratio = rows[-1][1] / rows[0][1]
                expected = SAMPLES[-1] / SAMPLES[0]
                print(f"\n  scales {ratio:.2f}x across a {expected:.2f}x range "
                      "in reader setting -- the Aa control works")

            if args.shot:
                page.goto(url)
                page.add_style_tag(
                    content=f"html {{ font-size: {args.font_size}px; }}"
                    "body { margin: 0 16px; }"
                )
                if args.find:
                    page.evaluate(
                        """(needle) => {
                            for (const el of document.querySelectorAll('p')) {
                                if (el.textContent.includes(needle)) {
                                    el.scrollIntoView({block: 'start'});
                                    return true;
                                }
                            }
                            return false;
                        }""",
                        args.find,
                    )
                    page.wait_for_timeout(200)
                page.screenshot(path=str(args.shot))
                print(f"wrote {args.shot} at {args.font_size}px reader size")
            browser.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
