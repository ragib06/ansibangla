# Web app

Converts ANSI Bangla (SutonnyMJ / Bijoy) PDFs and Word documents to Unicode in the
browser. Nothing is uploaded: the `ansibangla` Python package runs on the visitor's
device in [Pyodide](https://pyodide.org) (Python compiled to WebAssembly), inside a Web
Worker. The site is static files only, so any static host works.

## How it works

| Output | How it is made |
|--------|----------------|
| Pasted text | The **Paste text** tab converts as you type with `py/webtext.py`, which loads only `bijoy.py` (no PyMuPDF), so it works within a few seconds of the page opening, before PyMuPDF has loaded. |
| Word, EPUB, Markdown | The package writes them in Pyodide; the page offers them as downloads. Markdown with pictures comes as a `.zip`. |
| PDF | The package writes its `html` output (the PDF's pages with fonts and pictures embedded). The page loads it in a hidden frame, waits until its text is fitted, and opens the print dialog, where **Save as PDF** gives the file. In Chrome this is the same engine the command-line tool prints with, and the pages match it. |

On the first visit the browser downloads Pyodide and PyMuPDF (about 22 MB, from
cdn.jsdelivr.net) and keeps them in its cache. The converter itself is
`public/ansibangla.zip`, built from `../python/ansibangla` plus `py/webconvert.py` by
`scripts/pack-python.mjs` before every `dev` and `build`.

## Run and build

```bash
npm install
npm run dev        # http://localhost:5173
npm run build      # static site in dist/
npm run preview    # serve dist/
```

## Deploy

Upload `dist/` to any static host (Cloudflare Pages, GitHub Pages, Netlify). Asset
paths are relative, so the site also works from a sub-folder. Build command
`npm run build`, root directory `web`, output directory `dist`. The build needs the
`python/` folder next to `web/`, so deploy from the whole repository.

## Files

```
index.html               the converter page
how-it-works/index.html  "how it works" page, in Bangla (served at /how-it-works/)
src/main.ts              form, results, downloads
src/worker.ts            loads Pyodide + PyMuPDF + the package, runs conversions
src/print.ts             prints the html output through a hidden frame
src/protocol.ts          messages between page and worker
py/webconvert.py         Python side for files: bytes in, output files as bytes out
py/webtext.py            Python side for pasted text (bijoy.py only)
scripts/pack-python.mjs  zips the package into public/ansibangla.zip
scripts/indexnow.mjs     tells Bing and other IndexNow engines the pages changed (npm run indexnow, after a deploy)
scripts/og-card.*        the social preview card, public/og.png
public/llms.txt          a plain summary of the site for AI tools
```

## Limits

- Large books take a while: about 1.5 times as long as the command-line tool (a
  600-page book about 20 s), and the PDF page for such a book can be 50 MB or more
  because its pictures are embedded.
- Safari and Firefox print with their own engines, so line breaks in the PDF can differ
  slightly from Chrome's. Word, EPUB and Markdown outputs are the same in every browser.
