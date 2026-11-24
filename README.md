# ANSI Bangla

Convert ANSI Bangla (Bijoy / SutonnyMJ) text, PDFs and Word documents to Unicode, keeping
their formatting.

- **Web app:** <https://ansibangla.cc/> converts in your browser; nothing is uploaded.
  Paste text, or convert a whole PDF or `.docx` to Unicode PDF, Word, EPUB or Markdown.
- **Python package and command-line tool:** [`ansibangla` on PyPI](https://pypi.org/project/ansibangla/),
  `pip install ansibangla`.

| Folder | What it is |
|--------|------------|
| [`python/`](python/) | The `ansibangla` Python package and command-line tool: PDF or `.docx` in, Unicode PDF, Word, EPUB, Markdown or printable HTML out. See its [README](python/README.md). |
| [`web/`](web/) | A static web app that runs the same package in the browser (Pyodide); PDFs come from the browser's print dialog. See its [README](web/README.md). |
| `sample/` | Your own test files (ignored by git; sample books are usually copyrighted). The Python tests use them when present. |

## Licence

The code is under the [MIT License](LICENSE). The bundled fonts in
`python/ansibangla/fonts/` are derived from Noto Serif Bengali and are under the
[SIL Open Font License 1.1](python/ansibangla/fonts/OFL.txt).

*Bijoy and SutonnyMJ are names of their owners; this project is not affiliated with them.*
