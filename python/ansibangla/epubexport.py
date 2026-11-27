"""EPUB 3 output: a reflowable e-book built from the same blocks as the Markdown.

E-readers break lines and pages themselves (screen size, the reader's font size), so the
book keeps the structure rather than the page geometry: chapters split at headings with
a table of contents, justified paragraphs with first-line indents, centred lines, bold
and italic runs, smaller notes, framed pictures, and the source's page numbers as an
EPUB page list (readers can jump to a printed page). The bundled Noto Serif Bengali
fonts are embedded. Written directly with zipfile; no extra package is needed.
"""
import datetime
import html
import os
import re
import uuid
import zipfile

import pymupdf as fitz

from ._common import is_mj, span_text
from .blocks import despace, plain_line
from .docxexport import _bn_number, _line_heights
from .pdfbuild import FONT_FILES

CSS = """@font-face { font-family: 'Bn'; font-weight: normal; font-style: normal; src: url(fonts/%(regular)s); }
@font-face { font-family: 'Bn'; font-weight: bold; font-style: normal; src: url(fonts/%(bold)s); }
html { font-family: 'Bn', serif; }
body { margin: 0 1em; line-height: %(lh).2f; }
p { margin: 0; text-align: justify; hyphens: none; -webkit-hyphens: none; }
p.ind { text-indent: 1.45em; }
p.c, h1 { text-align: center; text-indent: 0; }
h1 { font-size: 1.28em; font-weight: normal; line-height: 1.4; margin: 0 0 1em;
     page-break-after: avoid; break-after: avoid; }
p.c { margin: 0.6em 0; }
h2 { font-size: 1.16em; font-weight: bold; text-align: left; line-height: 1.4; margin: 0;
     page-break-after: avoid; break-after: avoid; }
p.chapno { font-size: 1.12em; margin: 3em 0 0.3em; page-break-after: avoid; break-after: avoid; }
.small { font-size: 0.8em; }
.latin { font-family: 'Times New Roman', 'Liberation Serif', serif; font-size: 0.87em; }
.b { font-weight: bold; }
.i { font-style: italic; }
.spaced { letter-spacing: 0.35em; }
figure { margin: 1em 0; text-align: center; page-break-inside: avoid; break-inside: avoid; }
figure img { max-width: 100%%; border: 2px solid #000; box-sizing: border-box; }
figure.cover img { border: 0; max-height: 100%%; }
figcaption { font-size: 0.8em; line-height: 1.45; text-align: center; margin: 0.6em 1em 0; }
table { border-collapse: collapse; width: 100%%; margin: 1em 0; }
td { vertical-align: top; padding: 0.2em 0.4em; }
table.grid td { border: 1px solid currentColor; }
td p, td p.c { margin: 0; text-indent: 0; }
p.l { text-align: left; }
p.r { text-align: right; }
sup, sub { line-height: 0; }
"""

XHTML = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html>\n'
         '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
         'lang="bn" xml:lang="bn"><head><meta charset="UTF-8"/><title>{title}</title>'
         '<link rel="stylesheet" type="text/css" href="../style.css"/></head><body{cls}>\n{body}\n</body></html>')


def _esc(text):
    return html.escape(text, quote=False)


def _span_html(span, text):
    font = span['font']
    if is_mj(font):
        cls = (['b'] if 'Bold' in font else []) + (['i'] if 'Italic' in font else [])
    else:
        cls = ['latin'] + (['i'] if 'Italic' in font else [])
    if not cls or not text.strip():
        return _esc(text)
    lang = ' lang="en" xml:lang="en"' if 'latin' in cls else ''
    lead, core, trail = re.match(r'(\s*)(.*?)(\s*)$', text, re.S).groups()
    return f'{_esc(lead)}<span class="{" ".join(cls)}"{lang}>{_esc(core)}</span>{_esc(trail)}'


def _line_html(line, layout, first=True):
    """One source line; repeated spaces (justification gaps) become one space."""
    out, prev_space = [], not first
    for span in line['spans']:
        if not span['text']:
            continue
        text = re.sub(r'\s+', ' ', span_text(span))
        if prev_space:
            text = text.lstrip(' ')
        if not text:
            continue
        prev_space = text.endswith(' ')
        out.append(_span_html(span, text))
    return ''.join(out).strip()


class _Book:
    def __init__(self, layout, page_numbers):
        self.layout = layout
        self.page_numbers = page_numbers     # source page index -> printed number text
        self.marked = set()                  # pages whose marker is placed
        self.chapters = []                   # dicts: file, title, parts
        self.pages = []                      # (label, file, id) for the page list

    def chapter(self, title=None):
        n = len(self.chapters) + 1
        self.chapters.append(dict(file=f'ch{n:03d}.xhtml', title=title, parts=[], subs=[]))

    def marker(self, page):
        """A page-break marker for a source page, once, where its content starts."""
        if page in self.marked or page not in self.page_numbers:
            return ''
        self.marked.add(page)
        label = self.page_numbers[page]
        pid = f'page{page + 1}'
        self.pages.append((label, self.chapters[-1]['file'], pid))
        return (f'<span epub:type="pagebreak" role="doc-pagebreak" id="{pid}" '
                f'aria-label="{_esc(label)}" title="{_esc(label)}"></span>')

    def add(self, html_text):
        self.chapters[-1]['parts'].append(html_text)


def export_epub(doc, layout, blocks, out_path, font_dir, *, title=None):
    """Write the .epub file. blocks come from read_blocks (pictures already saved)."""
    for name in FONT_FILES:
        if not os.path.exists(os.path.join(font_dir, name)):
            raise FileNotFoundError(f'missing font {name} in {font_dir}')

    page_numbers = {}
    for b in blocks:
        if b['kind'] == 'num':
            text = plain_line(b['lines'][0])
            if _bn_number(text) is not None:
                page_numbers[b['page']] = text
    heights = _line_heights(blocks)
    body_lh = heights.get(round(layout.body_size, 1), layout.body_size * 1.2)
    line_height = max(body_lh / (layout.body_size * layout.scale), 1.3)

    book = _Book(layout, page_numbers)
    book.chapter()
    images, cover = [], None
    seq = [b for b in blocks if b['kind'] != 'num']

    em = layout.body_size * layout.scale            # source pt per CSS em of body text
    captions = set()                                # indices of blocks written as figure captions

    def extra_before(k):
        """Space above block k beyond normal line spacing, in source pt, measured from the
        previous text line on the same page; None at a page top or after a picture."""
        if k == 0 or seq[k - 1]['kind'] in ('img', 'h') or k - 1 in captions:
            return None                     # figures and chapter titles have CSS margins
        prev, first = seq[k - 1]['lines'][-1], seq[k]['lines'][0]
        if prev['page'] != first['page']:
            return None
        return first['base'] - prev['base'] - body_lh

    # a subheading at the top of a page gets the space subheadings usually have above them
    sub_gaps = sorted(g for k, b in enumerate(seq) if b['kind'] == 's'
                      for g in [extra_before(k)] if g is not None)
    sub_default = sub_gaps[len(sub_gaps) // 2] if sub_gaps else em

    def space_style(k):
        extra = extra_before(k)
        if extra is None and seq[k]['kind'] == 's':
            extra = sub_default
        if extra is None or extra < 0.25 * body_lh:
            return ''
        return f'margin-top:{extra / em:.2f}em'

    for k, b in enumerate(seq):
        kind = b['kind']
        if kind == 'img':
            pic = b['picture']
            name = os.path.basename(pic['path'])
            images.append((name, pic['path']))
            if pic['cover']:
                if cover is None and not any(c['parts'] for c in book.chapters):
                    cover = name
                book.add(f'{book.marker(b["page"])}<figure class="cover"><img src="../images/{name}" alt=""/></figure>')
                continue
            x0, _, x1, _ = pic['bbox']
            pct = min(100.0, 100.0 * (x1 - x0) / (layout.body_r - layout.body_l))
            # small text right under the picture on the same page is its caption
            j = k + 1
            while j < len(seq) and _is_caption(seq[j], b, layout):
                captions.add(j)
                j += 1
            caption = ''
            if j > k + 1:
                lines = [ln for blk in seq[k + 1:j] for ln in blk['lines']]
                caption = f'<figcaption>{_joined_html(lines, layout)}</figcaption>'
            book.add(f'{book.marker(b["page"])}<figure><img src="../images/{name}" alt="" '
                     f'style="width:{pct:.0f}%"/>{caption}</figure>')
            continue
        if k in captions:
            continue                            # written inside its figure

        line = b['lines'][0]
        small = line['mj_size'] and line['mj_size'] < layout.body_size - 1.0
        if kind == 'h':
            # a large heading opens a chapter, together with the run of centred lines and
            # headings right above it on the same page ("অধ্যায় ১", or a whole title page)
            if k + 1 < len(seq) and _leads(b, seq[k + 1]):
                continue                        # written with the heading at the end of the run
            start = k
            while start > 0 and _leads(seq[start - 1], seq[start]):
                start -= 1
            group = seq[start:k + 1]
            if book.chapters[-1]['parts'] or book.chapters[-1]['title']:
                book.chapter()
            book.add(book.marker(group[0]['page']) + _opening_html(group, layout))
            if len(group) == 2:
                chapter_title = f'{_heading_text(group[0])}: {_heading_text(b)}'
            else:                               # a title page: name it after its largest line
                chapter_title = _heading_text(max(group, key=lambda g: g['lines'][0]['size']))
            book.chapters[-1]['title'] = chapter_title
        elif kind == 'c':
            if k + 1 < len(seq) and _leads(b, seq[k + 1]):
                continue                        # written with the heading below it
            text = _centred_html(b, layout)
            book.add(f'{book.marker(b["page"])}<p class="c{" small" if small else ""}"'
                     f'{_style(space_style(k))}>{text}</p>')
        elif kind == 's':
            sid = f'sec{sum(len(c["subs"]) for c in book.chapters) + 1}'
            book.chapters[-1]['subs'].append((sid, plain_line(line)))
            book.add(f'{book.marker(b["page"])}<h2 id="{sid}"{_style(space_style(k))}>'
                     f'{_esc(plain_line(line))}</h2>')
        elif kind == 'l':
            text = _line_html(line, layout)
            if text:
                indent = max(line['x0'] - layout.body_l, 0) / layout.body_size
                style = '; '.join(s for s in (f'margin-left:{indent:.1f}em', space_style(k)) if s)
                book.add(f'{book.marker(b["page"])}<p class="{"small" if small else ""}"'
                         f'{_style(style)}>{text}</p>')
        else:                                   # body paragraph, maybe across pages
            pieces, prev_line = [book.marker(line['page'])], None
            for line_ in b['lines']:
                if prev_line is not None:
                    if line_['page'] != prev_line['page']:
                        pieces.append(book.marker(line_['page']))
                    if not plain_line(prev_line).endswith('-'):
                        pieces.append(' ')
                pieces.append(_line_html(line_, layout, first=prev_line is None))
                prev_line = line_
            classes = ' '.join(c for c in ('ind' if b['indented'] else '', 'small' if small else '') if c)
            attr = f' class="{classes}"' if classes else ''
            book.add(f'<p{attr}{_style(space_style(k))}>{"".join(pieces)}</p>')

    book.chapters = [c for c in book.chapters if c['parts']]
    if not book.chapters:
        book.chapter()
        book.add('<p></p>')
    first_heading = next((c['title'] for c in book.chapters if c['title']), None)
    title = title or first_heading or 'Untitled'
    for n, c in enumerate(book.chapters, 1):
        if not c['title'] and all('<figure class="cover">' in p for p in c['parts'] if p.strip()):
            c['title'] = 'প্রচ্ছদ'                  # a chapter holding just the cover picture
        c['title'] = c['title'] or (title if n == 1 else f'{n}')

    _write_package(out_path, book, images, cover, title, font_dir, line_height)
    return out_path


def _is_caption(block, picture, layout):
    """Text in a smaller size on the picture's page, below it (the caption)."""
    if block['kind'] not in ('p', 'l', 'c') or block['page'] != picture['page']:
        return False
    line = block['lines'][0]
    return (0 < line['mj_size'] < layout.body_size - 1.0
            and line['base'] > picture['picture']['bbox'][3]
            and all(ln['page'] == picture['page'] for ln in block['lines']))


def _joined_html(lines, layout):
    """Lines joined into one run of text (a space between lines unless one ends with '-')."""
    out = []
    for k, line in enumerate(lines):
        if k and not plain_line(lines[k - 1]).endswith('-'):
            out.append(' ')
        out.append(_line_html(line, layout, first=(k == 0)))
    return ''.join(out)


def _opening_html(group, layout):
    """A chapter opening: centred lines and headings at their source sizes relative to the
    body text, with the source's spacing between them; the last one is the <h1>."""
    out, prev = [], None
    for n, blk in enumerate(group):
        line = blk['lines'][0]
        size = (line['mj_size'] or line['size']) * (layout.scale if line['mj_size'] else 1.0)
        rel = min(size / (layout.body_size * layout.scale), 3.0)
        style = [f'font-size:{rel:.2f}em']
        if prev is not None:                    # source gap beyond this line's own height
            gap = line['base'] - prev['base'] - 1.4 * size
            if gap > 0.15 * size:
                style.append(f'margin-top:{gap / size:.2f}em')
        css = '; '.join(style)
        if n == len(group) - 1:
            out.append(f'<h1 style="{css}">{_line_html(line, layout)}</h1>')
        else:
            cls = 'c chapno' if n == 0 else 'c'
            out.append(f'<p class="{cls}" style="{css}">{_centred_html(blk, layout)}</p>')
        prev = line
    return ''.join(out)


def _heading_text(block):
    """Plain text of a heading block, with letter spacing undone."""
    text = plain_line(block['lines'][0])
    return despace(text) if block.get('spaced') else ' '.join(text.split())


def _style(css):
    return f' style="{css}"' if css else ''


def _leads(block, heading):
    """True when block is a centred line or heading directly above a large heading on the
    same page (such as "অধ্যায় ১" above the chapter title)."""
    return block['kind'] in ('c', 'h') and heading['kind'] == 'h' and block['page'] == heading['page']


def _centred_html(block, layout):
    line = block['lines'][0]
    if block.get('spaced'):
        return f'<span class="spaced">{_esc(despace(plain_line(line)))}</span>'
    return _line_html(line, layout)


# Pictures in an e-book need not be bigger than a tablet screen. Books typeset for print
# carry covers at print resolution (3600 x 6000) and photographs saved losslessly as PNG,
# which make the e-book about as big as the Word file it came from.
EPUB_MAX_W, EPUB_MAX_H = 1600, 2560      # the usual e-book limit, sharp on high-density tablets
JPEG_QUALITY = 85                        # no visible loss at reading size


def _web_image(path):
    """A picture ready for the e-book: (bytes, extension). Scaled down to fit
    EPUB_MAX_W x EPUB_MAX_H; photographs (many colours, nothing transparent) saved as
    JPEG, other pictures as PNG so diagrams and transparency stay exact. Whichever is
    smaller of that and the original file is used; a picture that cannot be read is
    kept as it is."""
    with open(path, 'rb') as fh:
        data = fh.read()
    ext = os.path.splitext(path)[1].lower()
    if ext not in ('.png', '.jpg', '.jpeg'):
        return data, ext                         # gif (may be animated), svg, webp: as they are
    try:
        pix = fitz.Pixmap(data)
        transparent = False
        if pix.alpha:
            transparent = min(pix.samples[pix.n - 1::pix.n]) < 255
            if not transparent:
                pix = fitz.Pixmap(pix, 0)        # an alpha channel that hides nothing
        if pix.colorspace is not None and pix.colorspace.n not in (1, 3):
            pix = fitz.Pixmap(fitz.csRGB, pix)   # CMYK and the like
        scale = min(1.0, EPUB_MAX_W / pix.width, EPUB_MAX_H / pix.height)
        if scale < 1:
            pix = fitz.Pixmap(pix, max(1, round(pix.width * scale)), max(1, round(pix.height * scale)), None)
        if not transparent and pix.color_count() > 256:
            new, new_ext = pix.tobytes('jpg', jpg_quality=JPEG_QUALITY), '.jpg'
        else:
            new, new_ext = pix.tobytes('png'), '.png'
    except Exception:                            # not a picture PyMuPDF can read
        return data, ext
    return (new, new_ext) if len(new) < len(data) else (data, ext)


def _write_package(out_path, book, images, cover, title, font_dir, line_height):
    # pictures first: a photograph saved as PNG becomes a .jpg, so its name changes
    shrunk, renamed, taken = [], {}, set()
    for name, path in images:
        data, ext = _web_image(path)
        stem = os.path.splitext(name)[0]
        new = name if os.path.splitext(name)[1].lower() == ext else stem + ext
        while new in taken:
            new = f'{os.path.splitext(new)[0]}_{len(taken)}{ext}'
        taken.add(new)
        renamed[name] = new
        shrunk.append((new, data))
    if any(old != new for old, new in renamed.items()):
        for c in book.chapters:
            c['parts'] = [re.sub(r'(\.\./images/)([^"]+)"', lambda m: m.group(1) + renamed.get(m.group(2), m.group(2)) + '"', p)
                          for p in c['parts']]
    images = [(new, None) for new, _ in shrunk]
    cover = renamed.get(cover, cover)

    book_id = f'urn:uuid:{uuid.uuid4()}'
    modified = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    media = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.gif': 'image/gif',
             '.svg': 'image/svg+xml', '.webp': 'image/webp'}

    manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
                '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>',
                '<item id="css" href="style.css" media-type="text/css"/>']
    for k, name in enumerate(FONT_FILES, 1):
        manifest.append(f'<item id="font{k}" href="fonts/{name}" media-type="font/ttf"/>')
    for k, (name, _) in enumerate(images, 1):
        props = ' properties="cover-image"' if name == cover else ''
        manifest.append(f'<item id="img{k}" href="images/{name}" '
                        f'media-type="{media[os.path.splitext(name)[1].lower()]}"{props}/>')
    for k, c in enumerate(book.chapters, 1):
        manifest.append(f'<item id="ch{k}" href="text/{c["file"]}" media-type="application/xhtml+xml"/>')
    spine = ''.join(f'<itemref idref="ch{k}"/>' for k in range(1, len(book.chapters) + 1))
    cover_meta = f'<meta name="cover" content="img{[n for n, _ in images].index(cover) + 1}"/>' if cover else ''

    opf = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid" xml:lang="bn">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           f'<dc:identifier id="bookid">{book_id}</dc:identifier><dc:title>{_esc(title)}</dc:title>'
           f'<dc:language>bn</dc:language><meta property="dcterms:modified">{modified}</meta>{cover_meta}'
           f'</metadata><manifest>{"".join(manifest)}</manifest><spine toc="ncx">{spine}</spine></package>')

    # a chapter with toc=False (an untitled page, such as a picture page) has no entry of
    # its own; a section is (id, text) in its chapter's file, or (id, text, file)
    listed = [c for c in book.chapters if c.get('toc', True)]

    def sub_file(c, s):
        return s[2] if len(s) > 2 else c['file']

    def toc_entry(c):
        subs = ''.join(f'<li><a href="text/{sub_file(c, s)}#{s[0]}">{_esc(s[1])}</a></li>' for s in c['subs'])
        return (f'<li><a href="text/{c["file"]}">{_esc(c["title"])}</a>'
                + (f'<ol>{subs}</ol>' if subs else '') + '</li>')

    toc = ''.join(toc_entry(c) for c in listed)
    page_list = ''.join(f'<li><a href="text/{f}#{pid}">{_esc(label)}</a></li>' for label, f, pid in book.pages)
    nav_body = (f'<nav epub:type="toc" id="toc" role="doc-toc"><h1>{_esc(title)}</h1><ol>{toc}</ol></nav>'
                + (f'<nav epub:type="page-list" id="page-list" hidden="hidden"><ol>{page_list}</ol></nav>'
                   if page_list else ''))
    nav = XHTML.format(title=_esc(title), cls='', body=nav_body).replace('../style.css', 'style.css')

    order = 0
    points = []
    for c in listed:
        order += 1
        point = (f'<navPoint id="np{order}" playOrder="{order}"><navLabel><text>{_esc(c["title"])}'
                 f'</text></navLabel><content src="text/{c["file"]}"/>')
        for s in c['subs']:
            order += 1
            point += (f'<navPoint id="np{order}" playOrder="{order}"><navLabel><text>{_esc(s[1])}</text>'
                      f'</navLabel><content src="text/{sub_file(c, s)}#{s[0]}"/></navPoint>')
        points.append(point + '</navPoint>')
    points = ''.join(points)
    page_targets = ''.join(f'<pageTarget id="pt{k}" type="normal" value="{k}"><navLabel><text>{_esc(label)}</text>'
                           f'</navLabel><content src="text/{f}#{pid}"/></pageTarget>'
                           for k, (label, f, pid) in enumerate(book.pages, 1))
    ncx = ('<?xml version="1.0" encoding="UTF-8"?>\n<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
           f'<head><meta name="dtb:uid" content="{book_id}"/></head><docTitle><text>{_esc(title)}</text></docTitle>'
           f'<navMap>{points}</navMap>' + (f'<pageList>{page_targets}</pageList>' if page_targets else '') + '</ncx>')

    css = CSS % dict(regular=FONT_FILES[0], bold=FONT_FILES[1], lh=line_height)
    container = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                 '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                 '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                 '</rootfiles></container>')

    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo('mimetype'), 'application/epub+zip', compress_type=zipfile.ZIP_STORED)
        z.writestr('META-INF/container.xml', container)
        z.writestr('OEBPS/content.opf', opf)
        z.writestr('OEBPS/nav.xhtml', nav)
        z.writestr('OEBPS/toc.ncx', ncx)
        z.writestr('OEBPS/style.css', css)
        for name in FONT_FILES:
            z.write(os.path.join(font_dir, name), f'OEBPS/fonts/{name}')
        for name, data in shrunk:
            # pictures are compressed already; deflating them again only costs time
            z.writestr(f'OEBPS/images/{name}', data, compress_type=zipfile.ZIP_STORED)
        for c in book.chapters:
            z.writestr(f'OEBPS/text/{c["file"]}',
                       XHTML.format(title=_esc(c['title']), cls='', body='\n'.join(c['parts'])))
