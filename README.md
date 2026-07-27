# The AI Lawyer

**A Framework for Modern Self-Representation**, by Brendan Ngwa Nforbi.

A nonfiction guide for pro se (self-represented) civil litigants on using a
multi-model AI workflow — research, drafting, discovery, depositions,
settlement — to build and run a case without a licensed attorney. The author
is not an attorney; the book says so repeatedly and by design.

## Repo structure

```
manuscript/    The editable source of truth (.docx). Every fix, section,
               and layout change is made here first.
exports/       Generated deliverables (PDF, EPUB), rendered from the
               manuscript. Never edited directly — always regenerated.
cover-art/     Front and back cover art (PNG originals, JPG front cover
               for platforms that require it).
```

## Regenerating the exports

The PDF and EPUB are both produced from `manuscript/The_AI_Lawyer_D2D_Ready.docx`
via LibreOffice headless conversion:

```
soffice --headless --convert-to pdf  --outdir exports manuscript/The_AI_Lawyer_D2D_Ready.docx
soffice --headless --convert-to epub --outdir exports manuscript/The_AI_Lawyer_D2D_Ready.docx
```

The EPUB needs one additional pass after conversion: LibreOffice's exporter
doesn't embed the custom fonts (EB Garamond, Montserrat, IBM Plex Mono) or
fully satisfy the EPUB 3.2 spec on its own. Before shipping an EPUB, it must
be post-processed to:
1. Strip the `direction: ltr` CSS rule LibreOffice adds (disallowed in EPUB stylesheets)
2. Add a `<title>` element to any XHTML file missing one
3. Bundle the actual font files and add `@font-face` declarations + manifest entries

Validate with `epubcheck` before publishing — it should report 0 errors / 0 warnings.

## Production notes

This edition went through a full editorial and production pass:
- Structural fix: promoted 143+ run-in subheadings from plain text to real
  heading styles, enabling working tables of contents/navigation in every format
- Added chapter-end Key Takeaways to all 20 chapters, a Sources & Further
  Reading section (citations independently verified, not just recalled), an
  About the Author section, and a closing review request
- Corrected epigraph misattributions, embedded file metadata, and
  straight-quote/number-style inconsistencies
- Full typography redesign: EB Garamond (body) / Montserrat (headings) /
  IBM Plex Mono (prompt/template blocks), with a gold/navy two-color
  hierarchy sampled directly from the cover art
- Removed hardcoded AI model version numbers (e.g. specific point releases)
  throughout, since those go stale fast — model/product names are kept,
  version numbers are not

## Distribution status

| Channel | Status |
|---|---|
| Amazon KDP (Kindle) | Submitted, in review |
| Draft2Digital (Apple Books, Kobo, B&N, Everand, library services, etc.) | Submitted, pending payment/tax verification |
| Direct sale (Gumroad/Payhip) | Not yet started |
| Print (KDP Print / IngramSpark) | Deferred — needs a wraparound cover with spine width calculated from final page count |

No ISBN has been purchased. Ebook distribution uses each platform's free
ISBN/ASIN; a self-owned ISBN would only be needed if/when print distribution
expands beyond Amazon (IngramSpark requires a supplied ISBN; KDP Print does not).

## Cost-benefit vs. a freelance/Fiverr-style production process

This entire production pass — full editorial review, structural rewrites,
new chapter content grounded in the existing text, citation verification,
a typography redesign, EPUB spec compliance and font embedding, cover
touch-ups, and live platform submission support — was done in a single
continuous AI-assisted session rather than commissioned piecemeal from
freelancers. Worth being honest about where that helped and where it didn't:

**Where it likely beat a freelance/Fiverr route:**
- **Speed and cost.** Comparable scope — editor, typesetter, ebook
  formatter, and some design/image work — realistically runs
  $1,500–3,000+ across multiple freelancers over 1–3 weeks, with revision
  rounds adding lag each time. This happened in one session.
- **Verification rigor.** Every edit was diffed against the prior version,
  the EPUB was validated against the actual spec (`epubcheck`), citations
  were checked against real sources rather than trusted from memory, and
  pages were rendered and visually inspected rather than assumed correct.
- **Continuity.** Full context of the entire ~300-page book and every
  prior decision was available throughout — no re-briefing a new
  collaborator partway through, no lost context between revision rounds.

**Where a good freelancer would likely beat this:**
- **Editorial taste.** A skilled human editor brings lived judgment about
  voice, pacing, and "this doesn't land yet" that pattern-matching against
  convention only approximates.
- **Original design.** Cover art here was cleaned up (barcode/ISBN and a
  decorative graphic removed), not designed from scratch by an illustrator
  working from a brief.
- **Domain accountability.** A litigator-editor reviewing the legal
  strategy content directly would catch substantive issues that citation
  verification alone doesn't cover, and carries professional accountability
  that an AI collaborator does not.

**Net take:** strong for speed, cost, and mechanical rigor across a large
surface area; a human professional pass — especially a legal-practice read
on the substantive advice — is still a reasonable step before betting fully
on this at wide print scale.
