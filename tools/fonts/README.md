# Vendored design fonts

These are committed so the build is reproducible. `word/fontTable.xml` in the
manuscript is empty, which means LibreOffice resolves fonts entirely through
fontconfig — without these installed, an export silently substitutes different
typefaces and the PDF comes out looking nothing like the design.

`tools/build.sh` installs them into `~/.local/share/fonts` before converting.
`tools/vendor_fonts.py` regenerates this directory (needs network).

| Family | Faces | Role |
|---|---|---|
| EB Garamond 12 | Regular, Italic, Bold, Bold Italic | body text |
| Montserrat | Regular, Italic, Bold, Bold Italic | headings |
| IBM Plex Mono | Regular, Italic, Bold, Bold Italic | prompt/template blocks |

## Provenance

Montserrat, IBM Plex Mono, and EB Garamond Regular/Italic are the faces that
shipped inside the previously published EPUB.

The two EB Garamond bold faces are rebuilt from
[`@fontsource/eb-garamond`](https://www.npmjs.com/package/@fontsource/eb-garamond)
5.2.5, renamed to the `EB Garamond 12` family the manuscript asks for and given
the same vertical metrics as the regular face so leading stays uniform. This
was necessary because:

- The bold face that shipped in the EPUB was a broken 130-glyph subset. It had
  no curly quotes, em dashes, ellipsis or accented characters, so 133 glyph
  instances inside bold runs fell back to a substitute font mid-sentence. That
  is where the stray `DejaVuSerif` subset embedded in the old PDF came from.
- There was no bold-italic face at all, so 142 bold-italic runs were being
  synthetically slanted.

The fontsource 400 weight matches the EPUB's `EBGaramond12-Regular` exactly on
capHeight (650), xHeight (400) and advance widths (H=810, n=528, o=495,
space=200) — it is the same type design. The shipped bold was the outlier, at
capHeight 662 / xHeight 415; it did not match its own regular.

## Licensing

All three families are licensed under the
[SIL Open Font License, Version 1.1](https://scripts.sil.org/OFL), which
permits redistribution, embedding and modification.

Copyright strings as they appear in the font files themselves:

- **EB Garamond** — regular/italic: "Copyright 2010-2013, Georg A. Duffner";
  the rebuilt bold faces: "Copyright 2017 The EB Garamond Project Authors
  (https://github.com/octaviopardo/EBGaramond12)"
- **Montserrat** — "Copyright 2011 The Montserrat Project Authors"
- **IBM Plex Mono** — "Copyright 2017 IBM Corp."

The bold faces are modified (renamed, and given the regular face's vertical
metrics), which the OFL permits. Neither the upstream `@fontsource/eb-garamond`
LICENSE nor the font's own name table declares a Reserved Font Name — the
copyright notice carries no "with Reserved Font Name" clause — so renaming them
to `EB Garamond 12` to match the other vendored faces is within the license.
The OFL's remaining condition is that the fonts not be sold on their own; here
they are only embedded in the book's exports.
