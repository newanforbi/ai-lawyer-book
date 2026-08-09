#!/usr/bin/env python3
"""Force the exported PDF to an exact trim size.

LibreOffice snaps some custom page heights to its nearest named paper format,
measured in whole millimetres. 9in is one of them: 228.6mm becomes 229.0mm, so
a 6x9 interior exports as 432 x 649.162pt instead of 432 x 648pt. (8in is
affected the same way, going to 203mm; 8.5in, 9.5in, 10in and 11in all come out
exact.) KDP checks the PDF trim against the trim you select, so 0.016in of
drift is worth removing.

The page content itself is laid out correctly -- only the box is wrong -- so
the fix is to trim the surplus off the bottom edge and leave the top-anchored
content where it is. On a 6x9 that costs 0.016in of bottom margin, taking it
from 0.75in to 0.734in, still far above KDP's 0.25in minimum.

Uses pikepdf so the cross-reference table is rebuilt properly rather than
byte-patched.
"""

import argparse
import sys
from pathlib import Path

import pikepdf

ROOT = Path(__file__).resolve().parent.parent
PDF = ROOT / "exports" / "The_AI_Lawyer_Complete_Book.pdf"

# Anything larger than this is a real layout difference, not format snapping,
# and should be investigated rather than silently cropped.
MAX_DRIFT_PT = 3.0


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf", nargs="?", type=Path, default=PDF)
    ap.add_argument("--width", type=float, default=432.0, help="points (default 6in)")
    ap.add_argument("--height", type=float, default=648.0, help="points (default 9in)")
    args = ap.parse_args()

    if not args.pdf.exists():
        sys.exit(f"missing {args.pdf}")

    fixed = 0
    with pikepdf.open(args.pdf, allow_overwriting_input=True) as pdf:
        for page in pdf.pages:
            box = [float(v) for v in page.mediabox]
            x0, y0, x1, y1 = box
            width, height = x1 - x0, y1 - y0
            dw, dh = width - args.width, height - args.height
            if abs(dw) < 1e-6 and abs(dh) < 1e-6:
                continue
            if abs(dw) > MAX_DRIFT_PT or abs(dh) > MAX_DRIFT_PT:
                sys.exit(
                    f"page {page.index + 1}: {width:g} x {height:g}pt is "
                    f"{dw:+g} x {dh:+g}pt off the requested "
                    f"{args.width:g} x {args.height:g}pt -- too far to be paper-format "
                    "snapping, not cropping it"
                )
            # Keep the top edge (y1) and the left edge (x0) fixed; the layout is
            # anchored to those.
            new = [x0, y1 - args.height, x0 + args.width, y1]
            page.mediabox = new
            for other in ("cropbox", "trimbox", "bleedbox", "artbox"):
                if other in page:
                    setattr(page, other, new)
            fixed += 1
        pdf.save(args.pdf, linearize=True)

    with pikepdf.open(args.pdf) as pdf:
        sizes = {
            (
                round(float(p.mediabox[2]) - float(p.mediabox[0]), 4),
                round(float(p.mediabox[3]) - float(p.mediabox[1]), 4),
            )
            for p in pdf.pages
        }
        pages = len(pdf.pages)

    print(f"  trim      {sizes} over {pages} pages ({fixed} corrected)")
    if sizes != {(args.width, args.height)}:
        sys.exit(f"trim still wrong: {sizes}")


if __name__ == "__main__":
    main()
