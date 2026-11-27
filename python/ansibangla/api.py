"""Public functions: convert SutonnyMJ PDFs and Word files to Unicode PDF, DOCX, EPUB, Markdown
and printable HTML (the PDF's pages with fonts and pictures embedded, for printing in a browser)."""
import contextlib
import os
import sys
import tempfile

import pymupdf as fitz

from ._common import Layout
from .bijoy import convert as convert_text_string
from .blocks import read_blocks
from .docxexport import export_docx
from .epubexport import export_epub
from .mdexport import export_markdown
from .pdfbuild import build_html, build_pdf

FORMATS = ('pdf', 'docx', 'epub', 'md', 'html')   # any combination can be asked for
DEFAULT_FORMATS = ('pdf',)                 # a PDF gives a PDF unless asked otherwise
DOCX_DEFAULT_FORMATS = ('docx',)           # a .docx gives a .docx unless asked otherwise
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fonts')


def _check_formats(formats):
    formats = tuple(dict.fromkeys(f.strip().lower() for f in formats if f.strip()))
    unknown = set(formats) - set(FORMATS)
    if unknown:
        raise ValueError(f'unknown formats: {sorted(unknown)}; choose from {", ".join(FORMATS)}')
    if not formats:
        raise ValueError(f'no output format; choose one or more of {", ".join(FORMATS)}')
    return formats


def _convert_pdf(src, out_dir='.', *, stem=None, formats=DEFAULT_FORMATS, scale=0.9,
                 font_dir=None, chrome=None, title=None):
    """Convert one SutonnyMJ PDF.

    formats is any combination of 'pdf', 'docx', 'epub', 'md' and 'html', written as
    <stem>_unicode.pdf, .docx, .epub, .md and .html (Markdown pictures go in
    <stem>_unicode_images/). title is the e-book title (default: the first heading).
    Returns {format: path}.
    """
    formats = _check_formats(formats)
    stem = stem or os.path.splitext(os.path.basename(src))[0]
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f'{stem}_unicode')
    font_dir = font_dir or FONT_DIR
    doc = fitz.open(src)
    layout = Layout(doc, scale=scale)
    written = {}

    img_name = f'{stem}_unicode_images'
    with tempfile.TemporaryDirectory(prefix='ansibangla_img_') as tmp:
        # pictures are saved next to the Markdown when it is written, else only for a while
        img_dir = os.path.join(out_dir, img_name) if 'md' in formats else tmp
        blocks = read_blocks(doc, layout, img_dir)
        if 'md' in formats:
            written['md'] = base + '.md'
            with open(written['md'], 'w', encoding='utf-8') as fh:
                fh.write(export_markdown(doc, layout, img_dir, img_name, blocks=blocks))
        if 'docx' in formats:
            written['docx'] = export_docx(doc, layout, blocks, base + '.docx', font_dir)
        if 'epub' in formats:
            written['epub'] = export_epub(doc, layout, blocks, base + '.epub', font_dir, title=title)
    if 'pdf' in formats:
        with tempfile.TemporaryDirectory(prefix='ansibangla_img_') as tmp:
            written['pdf'] = build_pdf(doc, layout, base + '.pdf', font_dir, tmp, chrome=chrome)
    if 'html' in formats:
        with tempfile.TemporaryDirectory(prefix='ansibangla_img_') as tmp:
            written['html'] = build_html(doc, layout, base + '.html', font_dir, tmp)
    return {f: written[f] for f in formats}


def _convert_docx(src, out_dir='.', *, stem=None, formats=DOCX_DEFAULT_FORMATS, font_dir=None,
                  scale=0.9, chrome=None, title=None):
    """Convert one Word document typed in SutonnyMJ.

    formats is any combination of 'docx' (the same document with its SutonnyMJ text in
    Unicode and the bundled fonts embedded), 'pdf' (that document laid out at its page
    size and printed with Chrome), 'html' (that layout as one printable HTML file), 'epub'
    and 'md', written as <stem>_unicode.docx, .pdf, .html, .epub and .md. Returns {format: path}.

    A document already in Unicode Bangla (say a converted file edited afterwards) can be
    made into pdf, html, epub and md as it is; asking for docx from it is an error, as
    there is nothing to convert.
    """
    formats = _check_formats(formats)
    from .docxinput import NoSutonnyMJText, has_unicode_bangla, read_package
    from .docxinput import convert_docx as _convert
    given_stem = stem
    stem = stem or os.path.splitext(os.path.basename(src))[0]
    os.makedirs(out_dir, exist_ok=True)
    base = os.path.join(out_dir, f'{stem}_unicode')
    img_name = f'{stem}_unicode_images'
    out_docx = base + '.docx'
    if os.path.abspath(out_docx) == os.path.abspath(src):
        raise ValueError(f'output would overwrite the input {src}; choose another --out-dir')
    written = {}
    tmp_docx = None
    if 'docx' not in formats:                     # the other outputs are built from the converted file
        tmp = tempfile.NamedTemporaryFile(suffix='.docx', delete=False)
        tmp.close()
        out_docx = tmp_docx = tmp.name
    font_dir = font_dir or FONT_DIR
    try:
        files = _convert(src, out_docx, font_dir, scale=scale)
    except NoSutonnyMJText:
        files = read_package(src)
        if not has_unicode_bangla(files):
            raise ValueError('no SutonnyMJ or Unicode Bangla text found in this document') from None
        if 'docx' in formats:
            others = ', '.join(f for f in FORMATS if f != 'docx')
            raise ValueError(f'this document is already in Unicode, so there is nothing to convert '
                             f'to .docx; ask for {others} instead') from None
        if not given_stem and stem.endswith('_unicode'):
            # an earlier output, edited: book_unicode.docx gives book_unicode.epub
            base = os.path.join(out_dir, stem)
            img_name = f'{stem}_images'
    finally:
        if tmp_docx:
            os.remove(tmp_docx)
    if 'docx' in formats:
        written['docx'] = out_docx

    others = [f for f in formats if f != 'docx']
    if others:
        # Markdown, PDF and EPUB come from one model of the converted document; its
        # pictures are saved next to the Markdown when it is written, else only for a while
        from . import docxrender
        with tempfile.TemporaryDirectory(prefix='ansibangla_media_') as tmp:
            media = os.path.join(out_dir, img_name) if 'md' in formats else tmp
            model = docxrender.build_model(files, media)
            for ext, n in model['skipped'].items():
                print(f'note: {src}: {n} picture(s) in {ext} format are left out of the '
                      f'{"/".join(others)} (browsers and e-readers cannot show them)', file=sys.stderr)
            if 'md' in formats:
                written['md'] = base + '.md'
                with open(written['md'], 'w', encoding='utf-8') as fh:
                    fh.write(docxrender.export_markdown(model, img_name))
            if 'epub' in formats:
                written['epub'] = docxrender.export_epub(model, base + '.epub', font_dir, title=title)
            if 'pdf' in formats:
                written['pdf'] = docxrender.export_pdf(model, base + '.pdf', font_dir, chrome=chrome)
            if 'html' in formats:
                written['html'] = docxrender.export_html(model, base + '.html', font_dir)
    return {f: written[f] for f in formats}


@contextlib.contextmanager
def _keep_latin(words):
    """Use a list of English words to keep for one conversion, then restore the previous one."""
    from . import bijoy
    previous = list(bijoy.LATIN_KEEP)
    if words is not None:
        bijoy.set_latin_keep(words)
    try:
        yield
    finally:
        bijoy.set_latin_keep(previous)


def convert_pdf(src, out_dir='.', *, keep_latin=None, **options):
    """Convert one SutonnyMJ PDF. Options: stem, formats (any of 'pdf', 'docx', 'epub',
    'md', 'html'; default 'pdf'), scale, font_dir, chrome, title; keep_latin lists English words
    typed in the SutonnyMJ font that stay as typed. Returns {format: path}."""
    with _keep_latin(keep_latin):
        return _convert_pdf(src, out_dir, **options)


def convert_docx(src, out_dir='.', *, keep_latin=None, **options):
    """Convert one Word document typed in SutonnyMJ. Options as for convert_pdf; formats
    defaults to 'docx'. Returns {format: path}."""
    with _keep_latin(keep_latin):
        return _convert_docx(src, out_dir, **options)


def convert_file(src, out_dir='.', *, formats=None, **options):
    """Convert a SutonnyMJ PDF or .docx, choosing by the file extension. formats is any
    combination of 'pdf', 'docx', 'epub', 'md' and 'html'; None gives the same format as the
    input (pdf for PDFs, docx for Word files)."""
    if src.lower().endswith('.docx'):
        options = {k: v for k, v in options.items()
                   if k in ('stem', 'font_dir', 'scale', 'chrome', 'title', 'keep_latin')}
        return convert_docx(src, out_dir, formats=DOCX_DEFAULT_FORMATS if formats is None else formats,
                            **options)
    return convert_pdf(src, out_dir, formats=DEFAULT_FORMATS if formats is None else formats, **options)


def convert_text(text):
    """Convert a SutonnyMJ string (as extracted from a PDF) to Unicode Bengali."""
    return convert_text_string(text)
