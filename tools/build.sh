#!/usr/bin/env bash
# Regenerate exports/ from manuscript/.
#
#   tools/build.sh            restyle the manuscript, then rebuild both exports
#   tools/build.sh --exports  rebuild the exports only, leaving the docx alone
#
# The restyle step is guarded by a property stamped into the docx, so running
# the full build twice will not double-apply it.
#
# Every step that used to be a manual instruction in the README is a script
# here: font installation, the 6x9 retypeset, the exact-trim correction the
# PDF export needs, and the EPUB post-processing (fonts, <title>, direction,
# and the pt -> em conversion that makes the Kindle font-size control work).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DOCX="manuscript/The_AI_Lawyer_D2D_Ready.docx"
PDF="exports/The_AI_Lawyer_Complete_Book.pdf"
EPUB="exports/The_AI_Lawyer_D2D_Ready.epub"
PROFILE="file:///tmp/lo-profile-ailawyer"

RESTYLE=1
[[ "${1:-}" == "--exports" ]] && RESTYLE=0

step() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

step "Installing the design fonts"
# word/fontTable.xml is empty, so LibreOffice resolves fonts purely through
# fontconfig. Without this the export silently substitutes something else.
mkdir -p ~/.local/share/fonts
cp tools/fonts/*.ttf ~/.local/share/fonts/
fc-cache -f >/dev/null 2>&1
# Captured once rather than piped per family: `fc-list | grep -q` closes the
# pipe early, which trips SIGPIPE and pipefail non-deterministically.
INSTALLED="$(fc-list)"
for family in "EB Garamond 12" "Montserrat" "IBM Plex Mono"; do
    if ! grep -qi "$family" <<<"$INSTALLED"; then
        echo "  FAIL: $family did not register with fontconfig" >&2
        exit 1
    fi
    echo "  ok  $family"
done

if [[ $RESTYLE -eq 1 ]]; then
    step "Retypesetting the manuscript"
    python3 tools/restyle_docx.py
else
    step "Skipping the manuscript restyle (--exports)"
fi

step "Exporting PDF"
rm -f "$PDF"
soffice --headless -env:UserInstallation="$PROFILE" \
        --convert-to pdf --outdir exports "$DOCX" 2>&1 | grep -v javaldx || true
mv -f "exports/$(basename "${DOCX%.docx}").pdf" "$PDF"
python3 tools/fix_pdf_trim.py "$PDF"

step "Exporting EPUB"
rm -f "$EPUB"
soffice --headless -env:UserInstallation="$PROFILE" \
        --convert-to epub --outdir exports "$DOCX" 2>&1 | grep -v javaldx || true
python3 tools/fix_epub.py "$EPUB"
python3 tools/split_epub.py "$EPUB"

step "Result"
python3 - "$PDF" "$EPUB" <<'PY'
import sys, zipfile, pikepdf
pdf, epub = sys.argv[1], sys.argv[2]
with pikepdf.open(pdf) as d:
    w = float(d.pages[0].mediabox[2]) - float(d.pages[0].mediabox[0])
    h = float(d.pages[0].mediabox[3]) - float(d.pages[0].mediabox[1])
    print(f"  {pdf}")
    print(f"      {w:g} x {h:g}pt  ({w/72:g}in x {h/72:g}in), {len(d.pages)} pages")
z = zipfile.ZipFile(epub)
css = z.read("OEBPS/styles/stylesheet.css").decode()
fonts = [n for n in z.namelist() if n.endswith(".ttf")]
opf = z.read("OEBPS/content.opf").decode()
ncx = z.read("OEBPS/toc.ncx").decode()
print(f"  {epub}")
print(f"      {len(fonts)} fonts embedded, "
      f"{css.count('em;')} relative sizes, {css.count('pt;')} absolute")
print(f"      {opf.count('<itemref')} spine items, "
      f"{ncx.count('<navPoint')} navigation entries")
PY

echo
echo "Next: verify with"
echo "  python3 tools/preview_epub.py --measure"
echo "  python3 tools/preview_epub.py --shot /tmp/after.png --find 'is the code that governs'"
echo "and run epubcheck before uploading to KDP or D2D (not installed here)."
