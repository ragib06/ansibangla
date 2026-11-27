# ansibangla

Convert ANSI Bangla (Bijoy / SutonnyMJ) PDFs and Word documents to Unicode, keeping their
formatting.

Many Bengali books and documents were typed with Bijoy in fonts such as SutonnyMJ. This
"ANSI Bangla" is not Unicode: the file stores Latin key codes, so copied text comes out as
gibberish like `wbwØ©avq` instead of `নির্দ্বিধায়`. This tool reads such a PDF or `.docx`
and writes real Unicode Bengali as PDF, Word, EPUB or Markdown, with the layout kept.

*Bijoy and SutonnyMJ are names of their owners; this project is not affiliated with them.*

You choose the outputs with `-f`/`--formats`: any combination of `pdf`, `docx`, `epub`,
`md` and `html`. Without it you get the same format as the input: a PDF for a PDF, a `.docx` for
a `.docx`.

**Word input.** The `.docx` output is the same document with its SutonnyMJ text in
Unicode. Styles, paragraph spacing, alignment, page setup, tables, pictures, headers and
footers are left as they are; text is set at `--scale` of its size, with exact line
spacing equal to what SutonnyMJ gave, so lines and pages stay where they were (table
cells get a little padding at top and bottom, so the Unicode font's marks clear the cell
borders). PDF output
lays that document out at its page size and margins (printed with Chrome; headers,
footers and footnotes are not drawn). EPUB output follows the document's page breaks
when it has them (a book set in Word puts each part, chapter and picture page after one):
each break starts a new page, titled in the table of contents by the large heading lines it
opens with ("অধ্যায় ৯: ইতিহাসের ইশারা"), with bold headings inside as its sections.
Without page breaks, a chapter starts at each large bold heading, with bold headings at
body size as sections. Page numbers that were in SutonnyMJ
stay in Bangla digits (১, ২, ৩), in Word documents made from PDFs too.

**Already-Unicode Word files.** A `.docx` that is already in Unicode Bangla, such as a
converted file you have since edited, can be made into PDF, HTML, EPUB or Markdown as it
is: `ansibangla book_unicode.docx -f epub` writes `book_unicode.epub`. Asking it for a
`.docx` is an error, as there is nothing to convert.

The outputs, for PDF or Word input:

| File | When | What it is |
|------|------|------------|
| `<name>_unicode.md` | `md` | Markdown following the layout: paragraphs, headings, bold and italic runs, centred lines and pictures (saved in `<name>_unicode_images/`). |
| `<name>_unicode.pdf` | `pdf` | Same page layout in a Unicode Bengali font (Noto Serif Bengali), with pictures and page colour kept. Text is searchable and copyable. |
| `<name>_unicode.docx` | `docx` | Word document with the source's formatting: page size, margins, page colour, line spacing, justified paragraphs with first-line indents, centred headings, framed pictures, bold and italic, page numbers. One page per source page. Fonts are embedded. |
| `<name>_unicode.epub` | `epub` | Reflowable EPUB 3 e-book: chapters split at headings, table of contents, justified paragraphs with indents, bold and italic, pictures, and the printed page numbers as a page list. Fonts are embedded. Pictures are scaled to e-book size (at most 1600 × 2560) and photographs saved as JPEG, so the book stays small (the Word and PDF outputs keep the pictures as they were). |
| `<name>_unicode.html` | `html` | The PDF's pages as one self-contained HTML file (fonts and pictures embedded). Open it in a browser and print to PDF; no Chrome install is needed. Print it once the page has finished loading, at 100% scale with no margins or headers. |

## Requirements

- Python 3.9 or newer
- [PyMuPDF](https://pymupdf.readthedocs.io/) (installed automatically)
- Google Chrome or Chromium, **only for PDF output**. Markdown, DOCX, EPUB and HTML output need no browser.

## Install

From PyPI, into a virtual environment:

```sh
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install ansibangla
```

Or as a stand-alone command with [pipx](https://pipx.pypa.io/) or [uv](https://docs.astral.sh/uv/):
`pipx install ansibangla` or `uv tool install ansibangla`.

No install at all: the web app at <https://ansibangla.cc/> runs the same converter
in your browser.

For development, from the `python/` folder of a checkout (code changes take effect
without reinstalling):

```sh
pip install -e . pytest
```

### Chrome / Chromium

The PDF output is laid out as HTML and printed with headless Chrome. The tool looks for,
in order:

1. the `--chrome` option (or `chrome=` argument in Python),
2. the `ANSIBANGLA_CHROME` environment variable,
3. `google-chrome`, `google-chrome-stable`, `chromium`, `chromium-browser` or `chrome` on your `PATH`.

On macOS and Windows Chrome is usually not on `PATH`, so point to it:

```sh
# macOS
export ANSIBANGLA_CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# Windows (PowerShell)
$env:ANSIBANGLA_CHROME = "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

On Debian/Ubuntu, `sudo apt install chromium` (or install Google Chrome) is enough.

## Command line usage

```sh
ansibangla book.pdf                          # Unicode PDF into the current folder
ansibangla book.pdf -o out/                  # into out/
ansibangla book.pdf -f docx                  # Word only (no Chrome needed)
ansibangla book.pdf -f pdf docx epub md      # all four
ansibangla book.pdf -f pdf,docx              # commas work too, as does -f pdf -f docx
ansibangla book.pdf -f epub --title 'বইয়ের নাম'   # e-book with a title
ansibangla a.pdf b.pdf -f md                 # several files, Markdown only
ansibangla story.docx -o out/                # Word input: Unicode .docx
ansibangla story.docx -f pdf epub            # Word input: PDF + e-book
ansibangla story_unicode.docx -f epub        # an edited Unicode .docx: e-book
ansibangla book.pdf --scale 0.85
ansibangla book.pdf --chrome /path/to/chrome
python -m ansibangla book.pdf                # same, without the installed script
```

Options:

| Option | Default | Meaning |
|--------|---------|---------|
| `-o`, `--out-dir` | `.` | Output folder (created if missing). |
| `-f`, `--formats` | the input's format | Outputs: any of `pdf`, `docx`, `epub`, `md`, `html`, separated by spaces or commas, or by repeating `-f`. Without it: `pdf` for PDFs, `docx` for `.docx` files. |
| `--scale` | `0.9` | Font-size factor for the Unicode PDF and DOCX (also for `.docx` input). Lower it if text looks crowded. |
| `--chrome` | auto | Path to Chrome or Chromium. |
| `--title` | first heading | Title of the EPUB. |
| `--keep-latin` | none | File listing English words typed in the SutonnyMJ font that stay as typed (one per line or space-separated; `#` starts a comment). Bijoy reads Latin letters as Bengali, so such words otherwise come out as Bengali gibberish. |

The command prints each written file's path. If one input fails, it reports the error,
carries on with the rest, and exits with status 1.

## Python usage

```python
from ansibangla import convert_file, convert_pdf, convert_text

paths = convert_pdf('book.pdf', 'out/')
# {'pdf': 'out/book_unicode.pdf'}

convert_pdf('book.pdf', 'out/', formats=('docx', 'md'), stem='chapter1')
# {'docx': 'out/chapter1_unicode.docx', 'md': 'out/chapter1_unicode.md'}

convert_file('story.docx', 'out/', formats=('pdf', 'epub'))   # picks by extension

convert_text('wbwØ©avq')        # 'নির্দ্বিধায়'
```

`convert_pdf(src, out_dir='.', *, stem=None, formats=('pdf',), scale=0.9, font_dir=None, chrome=None, title=None)`

- `stem`: base name for the output files (default: input file name).
- `formats`: any combination of `'pdf'`, `'docx'`, `'epub'`, `'md'`, `'html'`.
- `scale`: font-size factor for the PDF and DOCX.
- `font_dir`: folder with replacement fonts (default: the bundled Noto Serif Bengali).
- `chrome`: path to Chrome or Chromium.
- `title`: EPUB title (default: the first heading).
- `keep_latin`: English words typed in the SutonnyMJ font that stay as typed.

`convert_docx(src, out_dir='.', *, stem=None, formats=('docx',), font_dir=None, scale=0.9, chrome=None, title=None)`
converts a Word document; `convert_file(src, out_dir, ...)` picks `convert_pdf` or
`convert_docx` by the file extension.

`convert_text(text)` converts a single SutonnyMJ string, as extracted from a PDF, to
Unicode. Useful for text you copied out of a Bijoy-typed document.

## How it works

- **Character mapping.** SutonnyMJ key codes are mapped to Unicode, pre-base vowel signs
  (ি ে ৈ) and reph (র্) are moved into logical order, and glyphs that PDF extraction
  mis-codes are fixed. English words typed in the same font are kept as typed when listed
  with `--keep-latin`.
- **Layout measurement.** Body font size, left and right text edges, the page-number zone
  and pictures are measured from the PDF itself. Nothing is hard-coded for one book.
- **PDF rebuild.** Body text is rebuilt as justified paragraphs. Each block is fitted in
  Chrome to the same number of lines as its source, so text does not collide with
  headings or English lines. Page breaks are kept.
- **DOCX rebuild.** The document is written directly as WordprocessingML, with no extra
  package. Each source page starts a new page, and blocks keep their vertical positions
  through measured spacing. A paragraph that runs on to the next page is split there.
  The bundled fonts are embedded, so Word and LibreOffice show them even where they are
  not installed.
- **EPUB build.** The e-book is reflowable: the reader's device breaks lines and pages,
  so there is no line-breaking mismatch to manage. It keeps the structure: a chapter
  starts at each large heading, with the centred line above it (such as "অধ্যায় ১") as its
  opening. Bold subheadings at the left margin become section headings in the table of
  contents. Extra vertical space in the source, such as the blank line above a subheading,
  is measured from the line positions and kept. Each source page gets an invisible page marker, so readers that support page
  lists can go to a printed page number. It is written directly with `zipfile` and
  passes EPUBCheck.
- **Word input.** Word splits text into many runs (spell-check marks alone cut it every
  few words). Runs with the same formatting are merged, and a word still split across
  differently formatted runs is moved to one side, so the reordering sees whole words.
  Only SutonnyMJ runs change: they get the Unicode font, and Word's complex-script size,
  bold and italic (which Bengali Unicode is laid out with) are set to match. Zero-width
  joiners typed into the Bijoy text are dropped, since they change how Unicode conjuncts
  are drawn.

## Project layout

```
ansibangla/
  bijoy.py        SutonnyMJ -> Unicode mapping (MAP, PDF_FIXUPS) and reordering
  _common.py      reading PDF spans, lines, pictures and measuring page layout
  blocks.py       reading order as blocks (paragraphs, headings, pictures) for MD, DOCX, EPUB
  mdexport.py     Markdown output
  docxexport.py   Word (.docx) output
  epubexport.py   EPUB 3 e-book output
  pdfbuild.py     HTML layout -> printable HTML, or headless Chrome -> PDF output
  docxinput.py    Word (.docx) input: SutonnyMJ runs converted in place
  docxrender.py   PDF, HTML and EPUB from a converted Word document
  api.py          convert_file / convert_pdf / convert_docx / convert_text
  cli.py          command line
  fonts/          Noto Serif Bengali W94 (OFL), sized to match SutonnyMJ
tests/            pytest suite
tools/
  make_fonts.py   rebuilds the bundled fonts from the variable Noto Serif Bengali
```

## Limits

- Line breaks in body text differ from the source, because Unicode Bengali is wider.
  Page breaks are kept.
- Glyph mappings were checked against real SutonnyMJ books, not against the publisher's font.
  **Proofread the output.**
- Only text set in a font whose name contains `MJ` is converted; other fonts pass through unchanged.
- Scanned PDFs (images of pages, no text layer) are not supported; use OCR for those.
- The Markdown has no justification or page numbers; it is for reading and editing.
- In the DOCX, text flows within each page, so line breaks differ from the source and a
  page may end a line or two early. The last line before a paragraph splits across pages
  is not justified. Page numbers use Latin digits (Word has no Bengali page-number format).
  If a page overflows on to an extra page, lower `--scale`.
- The EPUB does not keep the page colour or exact positions, because e-readers apply their
  own theme and layout. Readers that let you choose a font replace the embedded one.

### Fixing a wrong character

If some word comes out wrong, the fix is usually one entry in `ansibangla/bijoy.py`:

- `PDF_FIXUPS`: characters the PDF extractor reports wrongly, replaced before mapping.
- `MAP`: SutonnyMJ sequences and their Unicode output. Longer sequences must come first.

Find the raw text with PyMuPDF (`page.get_text('rawdict')`), add the entry, and add a
case to `tests/test_convert.py`.

## Tests

```sh
pip install -e . pytest
pytest
```

The sample-book tests run only when PDF or `.docx` files are present in `sample/` at the
top of the repository. That folder is ignored by git, because sample books are usually
copyrighted; put your own test files there.

## Fonts and licence

`ansibangla/fonts/` holds Noto Serif Bengali W94 (Regular and Bold), static instances of
Noto Serif Bengali, © The Noto Project Authors, licensed under the SIL Open Font
License 1.1. See `ansibangla/fonts/OFL.txt`.

They are cut to match SutonnyMJ's proportions. SutonnyMJ draws its letters about 11%
smaller than Unicode Bengali fonts at the same point size, so text is set at 0.9 of the
source size (`--scale`). At that size, Noto Serif Bengali's width axis at 94 gives the
same line widths as SutonnyMJ: 0.997 of the source width, measured on SutonnyMJ books.
For comparison, the regular width gives 1.036 and SemiCondensed gives 0.957. The
instances have their own family name, so an installed Noto Serif Bengali of another
width is never used in their place. One placement rule is also changed. With া, ো or
ৌ, Noto puts chandrabindu far left (দাঁ) or past the syllable (পৌঁ). The bundled fonts
centre it over the join between the letter and its vowel stroke, as SutonnyMJ does.
Everywhere else Noto's placement is kept.

Noto Serif Bengali W94 Digits (Regular and Bold, about 4 KB each) holds only the Bangla
digits, drawn for both ০-৯ and 0-9. Word fills page-number fields with 0-9 in any
language, and SutonnyMJ drew those as Bangla digits; Word output sets page numbers in this
font so they stay Bangla. It is embedded in the `.docx` like the main fonts.

To rebuild the fonts: `pip install fonttools && python tools/make_fonts.py`
(`python tools/make_fonts.py --digits` rebuilds only the digits fonts from the bundled ones).
