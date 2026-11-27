"""PDF and EPUB from a converted Word document.

The converted .docx is read into a small document model (paragraphs with alignment,
spacing, indents, line spacing and runs; pictures; tables; page size and margins), which
is then

- laid out as HTML at the document's page size and margins and printed with headless
  Chrome (the same tool the PDF route uses), or
- packed as a reflowable EPUB 3: chapters start at large bold headings, bold headings at
  body size become sections in the table of contents.

Word itself lays out pages, so page breaks in the PDF can differ from Word's where a
paragraph sits near the bottom of a page. Headers, footers, footnotes and floating
shapes are not drawn.
"""
import html
import os
import re
import xml.etree.ElementTree as ET
from collections import Counter

from .blocks import despace, is_letter_spaced_text
from .docxinput import A, R, Styles, _local, q
from .mdexport import _escape
from .pdfbuild import READY_SCRIPT, asset_url, find_chrome, font_face_css, print_html

EMU = 12700                      # EMU per pt
WP = 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'
VML = 'urn:schemas-microsoft-com:vml'
WEB_IMAGES = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg')     # shown by browsers and e-readers
_UNITS = {'pt': 1.0, 'in': 72.0, 'cm': 72 / 2.54, 'mm': 72 / 25.4, 'px': 0.75, 'pc': 12.0}


def _css_pt(value):
    """A VML length ('346.75pt', '2.25in', '120px') in points."""
    m = re.match(r'\s*(-?[\d.]+)\s*([a-z]*)', value or '')
    if not m:
        return 0.0
    return float(m.group(1)) * _UNITS.get(m.group(2) or 'px', 0.75)
LATIN = "'Times New Roman', 'Liberation Serif', serif"


def _pt(twips, default=0.0):
    try:
        return int(twips) / 20.0
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------- model

def build_model(files, media_dir):
    """Document model of a converted .docx (files: {part name: bytes}). Pictures are
    written to media_dir."""
    styles = Styles(files.get('word/styles.xml'), files.get('word/theme/theme1.xml'))
    root = ET.fromstring(files['word/document.xml'])
    rels_xml = files.get('word/_rels/document.xml.rels', b'').decode('utf-8')
    rels = dict(re.findall(r'Id="([^"]+)"[^>]*Target="([^"]+)"', rels_xml))
    body = root.find(q('body'))
    sect = body.find(q('sectPr'))
    page = dict(w=595.3, h=841.9, top=72, right=72, bottom=72, left=72)
    if sect is not None:
        size, mar = sect.find(q('pgSz')), sect.find(q('pgMar'))
        if size is not None:
            page.update(w=_pt(size.get(q('w')), page['w']), h=_pt(size.get(q('h')), page['h']))
        if mar is not None:
            for k in ('top', 'right', 'bottom', 'left'):
                page[k] = _pt(mar.get(q(k)), page[k])
    bg = root.find(q('background'))
    if bg is not None and re.fullmatch(r'[0-9A-Fa-f]{6}', bg.get(q('color'), '')):
        page['bg'] = '#' + bg.get(q('color'))
    os.makedirs(media_dir, exist_ok=True)
    saved = {}

    skipped = Counter()                            # pictures in formats browsers cannot show

    def picture(rid, w, h, frame=0.0):
        target = rels.get(rid)
        part = os.path.normpath(f'word/{target}').replace(os.sep, '/') if target else None
        if not part or part not in files:
            return None
        ext = os.path.splitext(part)[1].lower()
        if ext not in WEB_IMAGES:
            skipped[ext] += 1
            return None
        if part not in saved:
            name = f'{len(saved) + 1:03d}_{os.path.basename(target)}'
            path = os.path.join(media_dir, name)
            with open(path, 'wb') as fh:
                fh.write(files[part])
            saved[part] = (name, path)
        name, path = saved[part]
        cover = w * h > 0.5 * page['w'] * page['h']
        return dict(name=name, path=path, w=w, h=h, frame=frame, cover=cover)

    def pictures_in(el):
        """Pictures inside a run child: DrawingML (w:drawing) or VML (w:pict, w:object)."""
        found = []
        if _local(el) == 'drawing':
            ext = next(el.iter(f'{{{WP}}}extent'), None)
            w = int(ext.get('cx', 0)) / EMU if ext is not None else 0
            h = int(ext.get('cy', 0)) / EMU if ext is not None else 0
            for blip in el.iter(q('blip', A)):
                found.append(picture(blip.get(q('embed', R)), w, h))
        else:
            for shape in el.iter():
                data = shape.find(f'{{{VML}}}imagedata')
                if _local(shape) not in ('shape', 'rect', 'image') or data is None:
                    continue
                style = dict(kv.split(':', 1) for kv in (shape.get('style') or '').split(';') if ':' in kv)
                frame = 0.0
                if shape.get('stroked') in ('t', 'true'):
                    frame = _css_pt(shape.get('strokeweight') or '0.75pt')
                found.append(picture(data.get(q('id', R)), _css_pt(style.get('width')),
                                     _css_pt(style.get('height')), frame))
        return [f for f in found if f]

    # footnote marks: Word's 'chicago' format is * † ‡ §, restarting for each paragraph here
    # (the book restarts them on each page); otherwise numbers
    fmt = root.find(f'.//{q("footnotePr")}/{q("numFmt")}')
    chicago = fmt is not None and fmt.get(q('val')) == 'chicago'
    counter = [0]

    def footnote_mark(n_in_para):
        if chicago:
            symbols = '*†‡§'
            return symbols[n_in_para % 4] * (n_in_para // 4 + 1)
        counter[0] += 1
        return str(counter[0])

    notes = {}                                    # footnote id -> its paragraphs

    def paragraph(p):
        ppr = p.find(q('pPr'))
        spacing = styles.para_attrs(p, 'spacing')
        ind = styles.para_attrs(p, 'ind')
        jc = styles.para_attrs(p, 'jc').get('val', 'left')
        line, rule = styles.line_spacing(p)
        first = _pt(ind.get('firstLine')) - _pt(ind.get('hanging'))
        para = dict(kind='p', runs=[], align=jc, before=_pt(spacing.get('before')),
                    after=_pt(spacing.get('after')), line=line, rule=rule,
                    left=_pt(ind.get('left', ind.get('start'))), right=_pt(ind.get('right', ind.get('end'))),
                    first=first, break_before='present' in styles.para_attrs(p, 'pageBreakBefore'),
                    break_after=False, mark_size=None, notes=[])
        mark = ppr.find(q('rPr')) if ppr is not None else None
        if mark is not None and mark.find(q('sz')) is not None:
            para['mark_size'] = int(mark.find(q('sz')).get(q('val')))
        for r in p.iter(q('r')):
            props = styles.resolve(r.find(q('rPr')), p)
            for c in r:
                tag = _local(c)
                if tag == 't':
                    para['runs'].append(dict(text=c.text or '', **props))
                elif tag == 'tab':
                    para['runs'].append(dict(text='\t', **props))
                elif tag in ('br', 'cr'):
                    if c.get(q('type')) == 'page':
                        # a page break before anything else in the paragraph starts it on a new page
                        if any(x.get('text', '').strip() or 'picture' in x for x in para['runs']):
                            para['break_after'] = True
                        else:
                            para['break_before'] = True
                    else:
                        para['runs'].append(dict(text='\n', **props))
                elif tag in ('drawing', 'pict', 'object'):
                    for pic in pictures_in(c):
                        para['runs'].append(dict(picture=pic, **props))
                elif tag in ('footnoteReference', 'endnoteReference'):
                    mark = footnote_mark(len(para['notes']))
                    para['runs'].append(dict(text=mark, sup=True, **props))
                    para['notes'].append(dict(mark=mark, paras=notes.get(c.get(q('id')), [])))
        # a heading set letter by letter ("প্র থ ম  প র্ব") is one word per gap
        shown = [x for x in para['runs'] if x.get('text', '').strip()]
        text = ''.join(x.get('text', '') for x in para['runs'] if 'picture' not in x)
        if shown and (all(x['bold'] for x in shown) or jc == 'center') and is_letter_spaced_text(text):
            para['runs'] = [dict(shown[0], text=despace(' '.join(text.split('\t'))))] + \
                [x for x in para['runs'] if 'picture' in x]
        return para

    # footnotes first, so references can carry their text
    notes_xml = files.get('word/footnotes.xml')
    if notes_xml:
        for fn in ET.fromstring(notes_xml).findall(q('footnote')):
            if fn.get(q('type')) in ('separator', 'continuationSeparator', 'continuationNotice'):
                continue
            paras = [paragraph(p) for p in fn.findall(q('p'))]
            for fp in paras:                      # drop the space Word puts after the mark
                while fp['runs'] and not fp['runs'][0].get('text', 'x').strip():
                    fp['runs'].pop(0)
            notes[fn.get(q('id'))] = [fp for fp in paras if fp['runs']]

    def table(tbl):
        """A table block: rows of cells {blocks, span (columns), rowspan, merged (covered
        by the cell above)}, and whether the table draws borders."""
        rows, starts = [], {}                    # starts: grid column -> cell a vertical merge started at
        for tr in tbl.findall(q('tr')):
            before = tr.find(f'{q("trPr")}/{q("gridBefore")}')
            col = int(before.get(q('val'), 0)) if before is not None else 0
            row = []
            for tc in tr.findall(q('tc')):
                tcpr = tc.find(q('tcPr'))
                span_el = tcpr.find(q('gridSpan')) if tcpr is not None else None
                span = int(span_el.get(q('val'), 1)) if span_el is not None else 1
                vm = tcpr.find(q('vMerge')) if tcpr is not None else None
                cell = dict(blocks=blocks_of(tc), span=span, rowspan=1, merged=False)
                if vm is not None and vm.get(q('val')) != 'restart' and col in starts:
                    cell['merged'] = True           # <w:vMerge/> carries on the cell above
                    starts[col]['rowspan'] += 1
                elif vm is not None and vm.get(q('val')) == 'restart':
                    starts[col] = cell
                else:
                    starts.pop(col, None)
                row.append(cell)
                col += span
            rows.append(row)
        return dict(kind='table', rows=rows, borders=_has_borders(tbl))

    def blocks_of(container):
        out = []
        for child in container:
            tag = _local(child)
            if tag == 'p':
                out.append(paragraph(child))
            elif tag == 'tbl':
                out.append(table(child))
            elif tag in ('sdt', 'customXml', 'sdtContent'):
                inner = child.find(q('sdtContent')) if tag == 'sdt' else child
                out.extend(blocks_of(inner if inner is not None else child))
        return out

    blocks = blocks_of(body)
    sizes = Counter()
    for b in _paragraphs(blocks):
        for r in b['runs']:
            if r.get('text', '').strip():
                sizes[r['size']] += len(r['text'])
    body_size = sizes.most_common(1)[0][0] if sizes else 22
    return dict(page=page, blocks=blocks, body_size=body_size, skipped=dict(skipped))


def _paragraphs(blocks):
    for b in blocks:
        if b['kind'] == 'p':
            yield b
        else:
            for row in b['rows']:
                for cell in row:
                    yield from _paragraphs(cell['blocks'])


def _has_borders(tbl):
    """Whether a table draws cell borders: set on the table itself, or by a grid table
    style (Word's own "Table Grid" and the like)."""
    tblpr = tbl.find(q('tblPr'))
    if tblpr is None:
        return False
    borders = tblpr.find(q('tblBorders'))
    if borders is not None:
        return any(b.get(q('val')) not in (None, 'nil', 'none') for b in borders)
    style = tblpr.find(q('tblStyle'))
    return style is not None and 'grid' in (style.get(q('val')) or '').lower()


def _table_html(table, cell_html):
    """HTML for a table block; cell_html(blocks) gives a cell's contents. Merged cells
    become colspan / rowspan, and class "grid" marks a table with borders."""
    rows = []
    for row in table['rows']:
        cells = []
        for cell in row:
            if cell['merged']:
                continue
            attrs = (f' colspan="{cell["span"]}"' if cell['span'] > 1 else '') + \
                    (f' rowspan="{cell["rowspan"]}"' if cell['rowspan'] > 1 else '')
            cells.append(f'<td{attrs}>{cell_html(cell["blocks"])}</td>')
        rows.append('<tr>' + ''.join(cells) + '</tr>')
    grid = ' class="grid"' if table['borders'] else ''
    return f'<table{grid}>' + ''.join(rows) + '</table>'


def _heading_level(para, body_size):
    """1 for a large bold heading, 2 for a bold heading at body size, else 0."""
    shown = [r for r in para['runs'] if r.get('text', '').strip()]
    if not shown or not all(r['bold'] for r in shown) or len(''.join(r['text'] for r in shown)) > 120:
        return 0
    size = max(r['size'] for r in shown)
    if size >= body_size + 3:
        return 1
    return 2 if size >= body_size else 0


# ---------------------------------------------------------------- runs as HTML

def _runs_html(runs, size_unit):
    """Runs as HTML. size_unit(half_points) gives the CSS font size."""
    out = []
    for r in runs:
        if 'picture' in r:
            pic = r['picture']
            out.append(f'\0PIC{id(pic)}\0')
            continue
        text = html.escape(r['text'], quote=False).replace('\t', '&#8195;').replace('\n', '<br/>')
        cls = (['b'] if r['bold'] else []) + (['i'] if r['italic'] else [])
        latin = r['font'] and not r['font'].startswith('Noto Serif Bengali') and not re.search('[ঀ-৿]', r['text'])
        style = f'font-size:{size_unit(r["size"])}'
        if latin:
            style += f';font-family:{LATIN}'
        attr = f' class="{" ".join(cls)}"' if cls else ''
        span = f'<span{attr} style="{style}">{text}</span>'
        out.append(f'<sup>{span}</sup>' if r.get('sup') else span)
    return ''.join(out)


def _notes(para):
    """The footnotes referenced in a paragraph, each as (mark, [paragraphs])."""
    return [(n['mark'], n['paras']) for n in para.get('notes', []) if n['paras']]


def _pictures(runs):
    return [r['picture'] for r in runs if 'picture' in r]


# ---------------------------------------------------------------- PDF

def _line_height_css(para, size_pt):
    if para['rule'] == 'exact':
        return f'{para["line"] / 20:.2f}pt'
    if para['rule'] == 'atLeast':
        return f'max({para["line"] / 20:.2f}pt, 1.3em)'
    return f'{para["line"] / 240 * 1.3:.3f}'          # 'auto': a multiple of the font's height


def _para_html_pdf(para, img_src):
    sizes = [r['size'] for r in para['runs'] if 'picture' not in r] or [para['mark_size'] or 22]
    size_pt = max(sizes) / 2
    align = {'both': 'justify', 'distribute': 'justify', 'center': 'center', 'right': 'right',
             'end': 'right'}.get(para['align'], 'left')
    style = [f'padding:{para["before"]:.1f}pt {para["right"]:.1f}pt {para["after"]:.1f}pt {para["left"]:.1f}pt',
             f'text-indent:{para["first"]:.1f}pt', f'text-align:{align}',
             f'line-height:{_line_height_css(para, size_pt)}', f'font-size:{size_pt:.2f}pt']
    if para['break_before']:
        style.append('break-before:page')
    inner = _runs_html(para['runs'], lambda hp: f'{hp / 2:.2f}pt')
    covers = []
    for pic in _pictures(para['runs']):
        if pic['cover']:                          # a page-sized picture gets a page of its own
            covers.append(f'<div class="cover"><img src="{img_src(pic)}"/></div>')
            inner = inner.replace(f'\0PIC{id(pic)}\0', '')
            continue
        frame = f'border:{pic["frame"]:.2f}pt solid #000;' if pic['frame'] else ''
        inner = inner.replace(f'\0PIC{id(pic)}\0', f'<img src="{img_src(pic)}" style="{frame}width:'
                                                   f'{pic["w"]:.1f}pt;max-width:100%;height:auto;'
                                                   f'vertical-align:bottom"/>')
    if covers and not re.sub(r'<[^>]+>|&#8203;', '', inner).strip():
        return ''.join(covers)                    # the paragraph only held the cover
    if not inner.strip():
        inner = '&#8203;'                         # an empty line keeps its height
    out = ''.join(covers) + f'<p style="{";".join(style)}">{inner}</p>'
    for mark, paras in _notes(para):              # footnotes follow their paragraph
        for k, fp in enumerate(paras):
            lead = f'<span>{html.escape(mark, quote=False)} </span>' if k == 0 else ''
            note = dict(fp, before=fp['before'] + (4 if k == 0 else 0), first=0.0, break_before=False,
                        break_after=False, notes=[])
            out += _para_html_pdf(note, img_src).replace('">', f'">{lead}', 1)
    if para['break_after']:
        out += '<div style="break-after:page"></div>'
    return out


def _blocks_html_pdf(blocks, img_src):
    out = []
    for b in blocks:
        if b['kind'] == 'p':
            out.append(_para_html_pdf(b, img_src))
        else:
            out.append(_table_html(b, lambda cell: _blocks_html_pdf(cell, img_src)))
    return '\n'.join(out)


def export_pdf(model, out_pdf, font_dir, chrome=None):
    """Lay the model out at its page size and margins and print it with Chrome."""
    chrome = find_chrome(chrome)
    return print_html(page_html(model, font_dir), out_pdf, chrome)


def export_html(model, out_html, font_dir):
    """The page layout as one HTML file, fonts and pictures embedded, for printing in a browser."""
    with open(out_html, 'w', encoding='utf-8') as fh:
        fh.write(page_html(model, font_dir, embed=True))
    return out_html


def page_html(model, font_dir, embed=False):
    """The model laid out at its page size and margins, as HTML for printing."""
    page = model['page']
    css = (font_face_css(font_dir, embed) +
           f"@page {{ size: {page['w']:.1f}pt {page['h']:.1f}pt; margin: {page['top']:.1f}pt "
           f"{page['right']:.1f}pt {page['bottom']:.1f}pt {page['left']:.1f}pt; "
           f"background: {page.get('bg', '#fff')}; }}\n"        # the page colour reaches the margins
           "@page cover { margin: 0; }\n"                       # a cover fills its page
           f"html, body {{ margin: 0; padding: 0; background: {page.get('bg', '#fff')}; }}\n"
           "* { -webkit-print-color-adjust: exact; print-color-adjust: exact; }\n"
           # anything wider than the page (a long URL in the notes) would make Chrome shrink
           # every page to fit, so long words wrap as in Word
           "body { font-family: 'Bn', serif; color: #000; overflow-wrap: anywhere; }\n"
           "p { margin: 0; hyphens: none; orphans: 1; widows: 1; }\n"
           "img { max-width: 100%; }\n"
           f".cover {{ page: cover; break-before: page; break-after: page; height: {page['h'] - 1:.1f}pt; "
           "display: flex; align-items: center; justify-content: center; overflow: hidden; }\n"
           ".cover img { max-width: 100%; max-height: 100%; }\n"
           ".b { font-weight: 700; } .i { font-style: italic; }\n"
           "table { border-collapse: collapse; width: 100%; table-layout: fixed; } "
           "td { vertical-align: top; padding: 2pt 4pt; } table.grid td { border: 0.5pt solid #000; }\n")
    body = _blocks_html_pdf(model['blocks'], lambda pic: asset_url(pic['path'], embed))
    return ('<!DOCTYPE html><html lang="bn"><head><meta charset="utf-8"><style>' + css +
            '</style></head><body>' + body + READY_SCRIPT + '</body></html>')


# ---------------------------------------------------------------- EPUB

def export_epub(model, out_epub, font_dir, title=None):
    """A reflowable EPUB: chapters at large bold headings, sections at bold body-size
    headings, spacing and indents relative to the body text."""
    from .epubexport import _Book, _write_package

    body = model['body_size']
    em = body / 2                                 # pt per em of body text

    def size_em(hp):
        return f'{hp / body:.3f}em'

    book = _Book(None, {})
    book.chapter()
    images, n_sec, cover = [], 0, None
    page = model['page']
    text_width = max(page['w'] - page['left'] - page['right'], 1.0)
    blocks = model['blocks']

    def head_size(p):
        return max(r['size'] for r in p['runs'] if r.get('text', '').strip())

    def text_of(p):
        return ' '.join(''.join(r.get('text', '') for r in p['runs']).split())

    # the size shared by most large headings is the chapter level ("এক.", "দুই."); larger
    # ones (title, author) open the book on a title page of their own
    big = [b for b in blocks if b['kind'] == 'p' and _heading_level(b, body) == 1]
    chapter_size = Counter(head_size(b) for b in big).most_common(1)[0][0] if big else None

    k = 0
    while k < len(blocks):
        b = blocks[k]
        if b['kind'] == 'table':
            def cell_html(cell):
                # cell text keeps its alignment; left otherwise, as justifying a narrow
                # column only opens gaps between words
                return ''.join(
                    f'<p class="{"c" if p["align"] == "center" else "r" if p["align"] in ("right", "end") else "l"}">'
                    f'{_runs_html(p["runs"], size_em)}</p>' for p in _paragraphs(cell))
            book.add(_table_html(b, cell_html))
            k += 1
            continue
        level = _heading_level(b, body)
        if level == 1:
            if head_size(b) > chapter_size:
                # title page: the run of headings larger than the chapter headings
                group = [b]
                while k + len(group) < len(blocks) and blocks[k + len(group)]['kind'] == 'p' \
                        and _heading_level(blocks[k + len(group)], body) == 1 \
                        and head_size(blocks[k + len(group)]) > chapter_size:
                    group.append(blocks[k + len(group)])
                title_text = text_of(max(group, key=head_size))
            else:
                group, title_text = [b], text_of(b)
            if book.chapters[-1]['parts'] or book.chapters[-1]['title']:
                book.chapter()
            parts = []
            for h in group:
                tag = 'h1' if h is group[0] else 'p'
                align = 'center' if h['align'] == 'center' else 'left'
                parts.append(f'<{tag} style="font-size:{size_em(head_size(h))};font-weight:bold;'
                             f'text-align:{align};margin:{h["before"] / em:.2f}em 0 {h["after"] / em:.2f}em">'
                             f'{html.escape(text_of(h), quote=False)}</{tag}>')
            book.add(''.join(parts))
            book.chapters[-1]['title'] = title_text
            k += len(group)
            continue
        if level == 2:
            n_sec += 1
            sid = f'sec{n_sec}'
            text = ''.join(r.get('text', '') for r in b['runs']).strip()
            book.chapters[-1]['subs'].append((sid, text))
            book.add(f'<h2 id="{sid}" style="margin:{b["before"] / em:.2f}em 0 {b["after"] / em:.2f}em">'
                     f'{html.escape(text, quote=False)}</h2>')
            k += 1
            continue
        inner = _runs_html(b['runs'], size_em)
        for pic in _pictures(b['runs']):
            if (pic['name'], pic['path']) not in images:
                images.append((pic['name'], pic['path']))
            if pic['cover']:
                cover = cover or pic['name']
                fig = f'<figure class="cover"><img src="../images/{pic["name"]}" alt=""/></figure>'
            else:
                frame = f'{pic["frame"] * 96 / 72:.1f}px solid #000' if pic['frame'] else '0'
                width = min(100.0, 100.0 * pic['w'] / text_width) if pic['w'] else 100.0
                fig = (f'<figure><img src="../images/{pic["name"]}" alt="" '
                       f'style="border:{frame};width:{width:.0f}%"/></figure>')
            inner = inner.replace(f'\0PIC{id(pic)}\0', f'</p>{fig}<p>')
        if not re.sub(r'<[^>]+>', '', inner).strip() and not _pictures(b['runs']):
            k += 1                                # empty lines: readers space paragraphs themselves
            continue
        align = {'center': 'c'}.get(b['align'], '')
        style = []
        if b['first']:
            style.append(f'text-indent:{b["first"] / em:.2f}em')
        if b['left']:
            style.append(f'margin-left:{b["left"] / em:.2f}em')
        if b['before'] or b['after']:
            style.append(f'margin-top:{b["before"] / em:.2f}em;margin-bottom:{b["after"] / em:.2f}em')
        if b['align'] in ('left', 'start'):
            style.append('text-align:left')
        elif b['align'] in ('right', 'end'):
            style.append('text-align:right')
        attr = (f' class="{align}"' if align else '') + (f' style="{";".join(style)}"' if style else '')
        book.add(re.sub(r'<p>\s*</p>', '', f'<p{attr}>{inner}</p>'))
        for mark, paras in _notes(b):             # footnotes follow their paragraph
            for n, fp in enumerate(paras):
                lead = html.escape(mark, quote=False) + ' ' if n == 0 else ''
                book.add(f'<p class="small" style="margin-top:{0.4 if n == 0 else 0}em">'
                         f'{lead}{_runs_html(fp["runs"], size_em)}</p>')
        k += 1

    book.chapters = [c for c in book.chapters if c['parts']]
    if not book.chapters:
        book.chapter()
        book.add('<p></p>')
    title = title or next((c['title'] for c in book.chapters if c['title']), None) or 'Untitled'
    for n, c in enumerate(book.chapters, 1):
        c['title'] = c['title'] or (title if n == 1 else f'{n}')
    # line height of the body text, relative to its size (the body text's exact spacing)
    ratios = Counter(round(b['line'] / 20 / (body / 2), 2) for b in _paragraphs(model['blocks'])
                     if b['rule'] == 'exact' and any(r.get('size') == body for r in b['runs']))
    line_height = ratios.most_common(1)[0][0] if ratios else 1.5
    _write_package(out_epub, book, images, cover, title, font_dir, max(line_height, 1.3))
    return out_epub


# ---------------------------------------------------------------- Markdown

def _md_runs(runs, all_bold):
    parts = []
    for r in runs:
        if 'picture' in r or not r.get('text'):
            continue
        core = _escape(r['text'].replace('\t', ' '))
        bold = r['bold'] and not all_bold
        if bold or r['italic']:
            mark = ('**' if bold else '') + ('*' if r['italic'] else '')
            lead, mid, trail = re.match(r'(\s*)(.*?)(\s*)$', core, re.S).groups()
            core = f'{lead}{mark}{mid}{mark[::-1]}{trail}' if mid else core
        parts.append(core)
    return re.sub(r'\s+', ' ', ''.join(parts)).strip()


def export_markdown(model, img_ref):
    """Markdown of the model: bold and italic runs, centred paragraphs, bold paragraphs at
    body size or larger as headings, pictures (already saved where the model put them),
    footnotes after the paragraph that refers to them."""
    body = model['body_size']
    out = []
    for b in _paragraphs(model['blocks']):
        for pic in _pictures(b['runs']):
            out += [f'![]({img_ref}/{pic["name"]})', '']
        shown = [r for r in b['runs'] if r.get('text', '').strip()]
        if not shown:
            continue
        all_bold = all(r['bold'] for r in shown)
        line = _md_runs(b['runs'], all_bold)
        big = max(r['size'] for r in shown)
        centred = b['align'] == 'center'
        if all_bold and big >= body:              # as for PDFs: centred '##', at the margin '###'
            out.append(('## ' if centred and big >= body + 4 else '### ') + line)
        elif centred:
            out.append(f'<p align="center">{line}</p>')
        else:
            out.append(line)
        out.append('')
        for mark, paras in _notes(b):
            for n, fp in enumerate(paras):
                text = _md_runs(fp['runs'], False)
                out += [(_escape(mark) + ' ' if n == 0 else '') + text, '']
    return '\n'.join(out).rstrip() + '\n'
