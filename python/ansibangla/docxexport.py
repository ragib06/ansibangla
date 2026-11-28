"""Word (.docx) output that follows a SutonnyMJ PDF's formatting.

The document gets the source's page size, margins and page colour, the measured body
line spacing, justified paragraphs with first-line indents, centred headings, framed
pictures, bold and italic runs, and a centred page number starting at the source's first
page number. Every source page starts a new page, and blocks keep their vertical
positions on it; a paragraph that runs on to the next page is split there. Within a page
text flows, so it stays editable, and line breaks may differ from the source. The bundled
Noto Serif Bengali fonts are embedded, so the file looks the same on machines without them.

The file is written directly as WordprocessingML; no extra package is needed.
"""
import os
import re
import uuid
import zipfile
from collections import defaultdict
from xml.sax.saxutils import escape

from ._common import is_mj, span_text
from .blocks import despace, plain_line
from .pdfbuild import FONT_FILES, PICTURE_FRAME

BN_FONT = 'Noto Serif Bengali W94'      # family name inside FONT_FILES (see tools/make_fonts.py)
# Word fills page-number fields with the digits 0-9 in any language; SutonnyMJ drew them as
# Bangla digits. This tiny family does the same (0-9 drawn as ০-৯), for page numbers only.
DIGITS_FONT = 'Noto Serif Bengali W94 Digits'
DIGITS_FILES = ('NotoSerifBengaliW94Digits-Regular.ttf', 'NotoSerifBengaliW94Digits-Bold.ttf')
LATIN_FONT = 'Times New Roman'
ASCENT = 0.78           # share of an exact line height above the baseline
EMU = 12700             # EMU per pt

NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
      'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def _tw(pt):
    """pt -> twentieths of a point (twips)."""
    return max(0, round(pt * 20))


# ---------------------------------------------------------------- measuring

def _line_heights(blocks):
    """Body line spacing per font size: the median gap between consecutive lines of a paragraph."""
    gaps = defaultdict(list)
    for b in blocks:
        if b['kind'] != 'p':
            continue
        for a, c in zip(b['lines'], b['lines'][1:]):
            if a['page'] == c['page'] and abs(a['mj_size'] - c['mj_size']) < .1:
                gap = c['base'] - a['base']
                if 0 < gap < 2 * a['mj_size']:
                    gaps[round(a['mj_size'], 1)].append(gap)
    return {size: sorted(g)[len(g) // 2] for size, g in gaps.items()}


def _line_height(block, heights, layout):
    if block['kind'] in ('img', 'table'):
        return None
    line = block['lines'][0]
    size = line['mj_size'] or line['size']
    if block['kind'] == 'p' and round(size, 1) in heights:
        return heights[round(size, 1)]
    return size * layout.scale * 1.3


def _extent(block, lh):
    """(page, top, end page, bottom) of a text or picture block, in source pt."""
    if block['kind'] == 'img':
        x0, y0, x1, y1 = block['picture']['bbox']
        return block['page'], y0 - PICTURE_FRAME, block['page'], y1 + PICTURE_FRAME
    if block['kind'] == 'table':
        x0, y0, x1, y1 = block['bbox']
        return block['page'], y0, block['page'], y1
    first, last = block['lines'][0], block['lines'][-1]
    return (first['page'], first['base'] - ASCENT * lh,
            last['page'], last['base'] + (1 - ASCENT) * lh)


# ---------------------------------------------------------------- runs

def embedded_fonts(font_dir):
    """The font families to embed in a .docx: [(family, [regular file, bold file])], the
    Bengali text font and, when font_dir has it, the page-number digits font."""
    fonts = [(BN_FONT, list(FONT_FILES))]
    if all(os.path.exists(os.path.join(font_dir, f)) for f in DIGITS_FILES):
        fonts.append((DIGITS_FONT, list(DIGITS_FILES)))
    return fonts


def _rpr(bengali, size, bold=False, italic=False, spacing=0, font=None):
    return '<w:rPr>' + _rpr_inner(bengali, size, bold, italic, spacing, font) + '</w:rPr>'


def _rpr_inner(bengali, size, bold=False, italic=False, spacing=0, font=None):
    font = font or (BN_FONT if bengali else LATIN_FONT)
    hp = max(2, int(size * 2 + 1e-6))             # half-points, rounded down: never wider than the source
    out = [f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}" w:eastAsia="{font}"/>']
    if bold:
        out.append('<w:b/><w:bCs/>')
    if italic:
        out.append('<w:i/><w:iCs/>')
    if spacing:
        out.append(f'<w:spacing w:val="{_tw(spacing)}"/>')
    out.append(f'<w:sz w:val="{hp}"/><w:szCs w:val="{hp}"/>')
    return ''.join(out)


def _run(text, rpr):
    return f'<w:r>{rpr}<w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _span_run(span, layout, text=None):
    text = span_text(span) if text is None else text
    bengali = is_mj(span['font'])
    size = span['size'] * layout.scale if bengali else span['size']    # as in the PDF output
    bold = bengali and 'Bold' in span['font']
    return _run(text, _rpr(bengali, size, bold, 'Italic' in span['font']))


def _line_runs(line, layout, first=True):
    """Runs of one source line. Repeated spaces (justification gaps) become one space."""
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
        out.append(_span_run(span, layout, text))
    return out


def _text_of(line):
    return re.sub(r'\s+', ' ', plain_line(line))


# ---------------------------------------------------------------- paragraphs

def _ppr(*, jc='left', before=0.0, lh=None, first_indent=0.0, left=0.0, page_break=False):
    out = []
    if page_break:
        out.append('<w:pageBreakBefore/>')
    out.append('<w:widowControl w:val="0"/>')
    spacing = f'<w:spacing w:before="{_tw(before)}" w:after="0"'
    if lh:
        spacing += f' w:line="{_tw(lh)}" w:lineRule="exact"'
    out.append(spacing + '/>')
    if first_indent or left:
        out.append(f'<w:ind w:left="{_tw(left)}" w:firstLine="{_tw(first_indent)}"/>')
    out.append(f'<w:jc w:val="{jc}"/>')
    return '<w:pPr>' + ''.join(out) + '</w:pPr>'


def _body_para(block, layout, ppr):
    runs = []
    for k, line in enumerate(block['lines']):
        line_runs = _line_runs(line, layout, first=(k == 0))
        if k and line_runs and not _text_of(block['lines'][k - 1]).endswith('-'):
            span = next(s for s in line['spans'] if s['text'].strip())
            bengali = is_mj(span['font'])
            runs.append(_run(' ', _rpr(bengali, span['size'] * (layout.scale if bengali else 1))))
        runs.extend(line_runs)
    return f'<w:p>{ppr}{"".join(runs)}</w:p>'


def _table_xml(block, layout, left):
    """A table found in the PDF as a Word table: the source's column widths and line
    spacing, merged cells (gridSpan / vMerge), borders all round for a ruled table or rules
    between rows for one drawn with horizontal rules only. Cells get a little padding at top
    and bottom, as Noto's marks reach past an exact line (see docxinput.CELL_PAD)."""
    from .blocks import cell_paragraphs
    lines = block['lines']
    gaps = sorted(b['base'] - a['base'] for a, b in zip(lines, lines[1:])
                  if 0 < b['base'] - a['base'] < 2.5 * (a['mj_size'] or a['size']))
    size = max((l['mj_size'] or l['size'] for l in lines), default=layout.body_size)
    lh = gaps[len(gaps) // 2] if gaps else size * 1.3 * layout.scale
    pad = 0.2 * size * layout.scale
    on, off = 'w:val="single" w:sz="4" w:space="0" w:color="000000"', 'w:val="nil"'
    sides = dict(top=on, left=on, bottom=on, right=on, insideH=on, insideV=on) if block['ruled'] else \
        dict(top=on, left=off, bottom=on, right=off, insideH=on, insideV=off)
    borders = ''.join(f'<w:{s} {v}/>' for s, v in sides.items())
    widths = [_tw(w) for w in block['widths']]
    out = [f'<w:tbl><w:tblPr><w:tblW w:w="{sum(widths)}" w:type="dxa"/>'
           f'<w:tblInd w:w="{_tw(left)}" w:type="dxa"/><w:tblBorders>{borders}</w:tblBorders>'
           f'<w:tblLayout w:type="fixed"/><w:tblCellMar><w:top w:w="{_tw(pad)}" w:type="dxa"/>'
           f'<w:left w:w="{_tw(3)}" w:type="dxa"/><w:bottom w:w="{_tw(pad)}" w:type="dxa"/>'
           f'<w:right w:w="{_tw(3)}" w:type="dxa"/></w:tblCellMar></w:tblPr>'
           '<w:tblGrid>' + ''.join(f'<w:gridCol w:w="{w}"/>' for w in widths) + '</w:tblGrid>']
    for row in block['rows']:
        cells = []
        for c, cell in enumerate(row):
            if cell['merged'] == 'col':
                continue                          # inside the gridSpan of the cell to its left
            if cell['merged'] == 'row':           # below a cell merged downwards
                cells.append(f'<w:tc><w:tcPr><w:tcW w:w="{widths[c]}" w:type="dxa"/><w:vMerge/></w:tcPr><w:p/></w:tc>')
                continue
            span = cell['colspan']
            pr = f'<w:tcW w:w="{sum(widths[c:c + span])}" w:type="dxa"/>'
            if span > 1:
                pr += f'<w:gridSpan w:val="{span}"/>'
            if cell['rowspan'] > 1:
                pr += '<w:vMerge w:val="restart"/>'
            paras = [_body_para(dict(lines=lines), layout, _ppr(jc=align, lh=lh))
                     for lines, align in cell_paragraphs(cell)] or ['<w:p/>']
            cells.append(f'<w:tc><w:tcPr>{pr}</w:tcPr>{"".join(paras)}</w:tc>')
        out.append('<w:tr><w:trPr><w:cantSplit/></w:trPr>' + ''.join(cells) + '</w:tr>')
    return ''.join(out) + '</w:tbl>'


def _same_row(block, other):
    """Two pictures on one page whose vertical extents mostly overlap (side by side)."""
    if block['kind'] != 'img' or block['picture']['cover'] or block['page'] != other['page']:
        return False
    _, a0, _, a1 = block['picture']['bbox']
    _, b0, _, b1 = other['picture']['bbox']
    overlap = min(a1, b1) - max(a0, b0)
    return overlap > 0.5 * min(a1 - a0, b1 - b0)


def _split_at_pages(blocks):
    """Split body paragraphs that run on to the next page, so every source page can start
    a page of its own. (The last line before the split is left unjustified: Unicode text
    wraps differently, and a short line spread across the column looks worse.)"""
    out = []
    for b in blocks:
        if b['kind'] != 'p':
            out.append(b)
            continue
        groups = []
        for line in b['lines']:
            if groups and groups[-1][0]['page'] == line['page']:
                groups[-1].append(line)
            else:
                groups.append([line])
        for k, group in enumerate(groups):
            out.append(dict(b, lines=group, page=group[0]['page'], indented=b['indented'] and k == 0))
    return out


def _spaced_para(line, layout, ppr):
    """A letter-spaced heading (spaced-out letters): one word set with tracking."""
    span = next(s for s in line['spans'] if s['text'].strip())
    bengali = is_mj(span['font'])
    size = line['size'] * layout.scale
    word = despace(plain_line(line))
    return f'<w:p>{ppr}{_run(word, _rpr(bengali, size, spacing=0.35 * size))}</w:p>'


def _picture_xml(pid, rid, name, w_pt, h_pt, framed, anchor=None):
    cx, cy = round(w_pt * EMU), round(h_pt * EMU)
    line = (f'<a:ln w="{round(PICTURE_FRAME * EMU)}"><a:solidFill><a:srgbClr val="000000"/>'
            '</a:solidFill></a:ln>') if framed else ''
    graphic = (
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{pid}" name="{escape(name)}"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{line}</pic:spPr></pic:pic>'
        '</a:graphicData></a:graphic>')
    doc_pr = f'<wp:docPr id="{pid}" name="Picture {pid}"/>'
    if anchor is None:
        return (f'<w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
                f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/>'
                f'{doc_pr}{graphic}</wp:inline></w:drawing>')
    x, y = anchor
    return (f'<w:drawing><wp:anchor distT="0" distB="0" distL="0" distR="0" simplePos="0" '
            f'relativeHeight="0" behindDoc="1" locked="1" layoutInCell="1" allowOverlap="1">'
            '<wp:simplePos x="0" y="0"/>'
            f'<wp:positionH relativeFrom="page"><wp:posOffset>{round(x * EMU)}</wp:posOffset></wp:positionH>'
            f'<wp:positionV relativeFrom="page"><wp:posOffset>{round(y * EMU)}</wp:posOffset></wp:positionV>'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:wrapNone/>'
            f'{doc_pr}{graphic}</wp:anchor></w:drawing>')


# ---------------------------------------------------------------- package parts

def _obfuscate(data, key):
    """Embedded-font obfuscation (ECMA-376 Part 1, 17.8.1): XOR the first 32 bytes with the GUID."""
    hexkey = key.strip('{}').replace('-', '')
    kb = bytes(int(hexkey[i:i + 2], 16) for i in range(30, -2, -2))
    head = bytes(data[i] ^ kb[i % 16] for i in range(32))
    return head + data[32:]


def _styles(layout, body_size):
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:styles {NS}>'
            f'<w:docDefaults><w:rPrDefault><w:rPr>{_rpr_inner(True, body_size * layout.scale)}'
            '<w:lang w:val="bn-BD" w:eastAsia="bn-BD" w:bidi="bn-BD"/></w:rPr></w:rPrDefault>'
            '<w:pPrDefault><w:pPr><w:spacing w:after="0"/></w:pPr></w:pPrDefault></w:docDefaults>'
            '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
            '</w:styles>')


def _settings():
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings {NS}>'
            '<w:embedTrueTypeFonts/><w:displayBackgroundShape/>'
            '<w:defaultTabStop w:val="720"/><w:compat><w:compatSetting w:name="compatibilityMode" '
            'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat></w:settings>')


def font_entries(fonts, keys, rid_prefix):
    """<w:font> entries for the fonts table, each family with its regular and bold files
    embedded. keys: one obfuscation key per file, in order; relationship ids are
    rid_prefix + 1, 2, ... in the same order."""
    out, k = [], 0
    for family, names in fonts:
        embeds = ''
        for tag in ('embedRegular', 'embedBold')[:len(names)]:
            k += 1
            embeds += f'<w:{tag} r:id="{rid_prefix}{k}" w:fontKey="{keys[k - 1]}"/>'
        out.append(f'<w:font w:name="{family}"><w:charset w:val="00"/><w:family w:val="roman"/>'
                   f'<w:pitch w:val="variable"/>{embeds}</w:font>')
    return ''.join(out)


def _font_table(fonts, keys):
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:fonts {NS}>'
            + font_entries(fonts, keys, 'rIdFont') +
            f'<w:font w:name="{LATIN_FONT}"><w:charset w:val="00"/><w:family w:val="roman"/>'
            '<w:pitch w:val="variable"/></w:font></w:fonts>')


def _footer(layout, size, digits_font=None):
    """A centred page-number field. With digits_font (when the source printed its page
    numbers in SutonnyMJ, as Bangla digits) the numbers stay Bangla in Word too."""
    rpr = _rpr(True, size * layout.scale, font=digits_font)
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {NS}>'
            f'<w:p><w:pPr><w:spacing w:before="0" w:after="0"/><w:jc w:val="center"/></w:pPr>'
            f'<w:r>{rpr}<w:fldChar w:fldCharType="begin"/></w:r>'
            f'<w:r>{rpr}<w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>'
            f'<w:r>{rpr}<w:fldChar w:fldCharType="separate"/></w:r>'
            f'<w:r>{rpr}<w:t>1</w:t></w:r>'
            f'<w:r>{rpr}<w:fldChar w:fldCharType="end"/></w:r></w:p></w:ftr>')


def _bn_number(text):
    digits = ''.join(str('০১২৩৪৫৬৭৮৯'.index(ch)) if ch in '০১২৩৪৫৬৭৮৯' else ch
                     for ch in text if ch.isdigit())
    return int(digits) if digits.isdigit() else None


# ---------------------------------------------------------------- document

def export_docx(doc, layout, blocks, out_path, font_dir):
    """Write the .docx file. blocks come from read_blocks (pictures already saved)."""
    for name in FONT_FILES:
        if not os.path.exists(os.path.join(font_dir, name)):
            raise FileNotFoundError(f'missing font {name} in {font_dir}')
    heights = _line_heights(blocks)
    body_lh = heights.get(round(layout.body_size, 1), layout.body_size * 1.2)
    text_blocks = _split_at_pages(b for b in blocks if b['kind'] != 'num')

    # margins: the text column and the highest / lowest text on the pages
    extents = [_extent(b, _line_height(b, heights, layout)) for b in text_blocks
               if not (b['kind'] == 'img' and b['picture']['cover'])]
    top_margin = min(e[1] for e in extents) if extents else 56.0
    bottom_text = max(e[3] for e in extents) if extents else layout.foot_y
    left_margin, right_margin = layout.body_l, layout.page_w - layout.body_r

    fonts = embedded_fonts(font_dir)
    nums = [b for b in blocks if b['kind'] == 'num']
    first_num, num_size, footer_dist = None, layout.body_size * 0.8, layout.page_h - layout.foot_y
    digits_font = None
    if nums:
        line = nums[0]['lines'][0]
        n = _bn_number(plain_line(line))
        if n is not None:
            first_num = n - nums[0]['page']           # number the source would give page 1
        num_size = line['mj_size'] or line['size']
        if line['mj_size'] and any(f == DIGITS_FONT for f, _ in fonts):
            digits_font = DIGITS_FONT                 # printed in SutonnyMJ: Bangla digits
        footer_dist = layout.page_h - line['base'] - 0.3 * num_size
    # Let text run down to just above the page number: about a line of room to spare, so
    # a page whose Unicode text wraps to one more line than its source still fits.
    footer_top = footer_dist + 1.3 * num_size * layout.scale
    bottom_margin = max(min(layout.page_h - bottom_text - 2 - body_lh, footer_top), 18.0)

    media, body = [], []
    prev = None                     # extent of the previous block (+ last baseline and line height)
    skip = set()

    def add_media(pic):
        name = os.path.basename(pic['path'])
        rid = f'rIdImg{len(media) + 1}'
        media.append((rid, name, pic['path']))
        return len(media), rid, name

    for k, b in enumerate(text_blocks):
        if k in skip:
            continue
        kind = b['kind']
        lh = None if kind == 'img' else _line_height(b, heights, layout)
        if kind in ('h', 'c', 'l', 's') and prev is not None and prev[4] is not None \
                and b['page'] == prev[2]:
            # single lines set closer than a standard line height (contents, bibliography):
            # shrink the line so its baseline lands where the source has it
            line = b['lines'][0]
            size = (line['mj_size'] or line['size']) * (layout.scale if line['mj_size'] else 1.0)
            fit = (line['base'] - prev[4] - (1 - ASCENT) * prev[5]) / ASCENT
            if fit < lh:
                lh = max(fit, 1.05 * size)
        page, top, end_page, bottom = _extent(b, lh or body_lh)
        page_break = prev is not None and page > prev[2]      # each source page starts a page
        before = max(top - (top_margin if prev is None or page_break else prev[3]), 0.0)

        if kind == 'table':
            # a table takes no spacing of its own: a tiny paragraph carries the space above
            # it and the start of a new page
            if page_break or before > 1:
                body.append(f'<w:p>{_ppr(before=max(before - 1, 0), lh=1, page_break=page_break)}</w:p>')
            body.append(_table_xml(b, layout, b['bbox'][0] - left_margin))
            prev = (page, top, end_page, bottom, None, None)
            continue

        if kind == 'img':
            pic = b['picture']
            if pic['cover']:
                x0, y0, x1, y1 = pic['bbox']
                x0, y0 = max(x0, 0.0), max(y0, 0.0)          # keep it on the page, or it moves on
                x1, y1 = min(x1, layout.page_w), min(y1, layout.page_h)
                drawing = _picture_xml(*add_media(pic), x1 - x0, y1 - y0, False, anchor=(x0, y0))
                ppr = _ppr(page_break=page_break, lh=1)
                body.append(f'<w:p>{ppr}<w:r>{drawing}</w:r></w:p>')
                prev = (page, top_margin, page, top_margin, None, None)   # no room in the text flow
                continue
            # pictures side by side in the source share one paragraph
            row = [b]
            j = k + 1
            while j < len(text_blocks) and _same_row(text_blocks[j], row[-1]):
                row.append(text_blocks[j])
                skip.add(j)
                j += 1
            row.sort(key=lambda r: r['picture']['bbox'][0])
            runs, right = [], None
            for item in row:
                x0, y0, x1, y1 = item['picture']['bbox']
                if right is not None and x0 - right > 0.5:
                    runs.append(f'<w:r><w:rPr><w:spacing w:val="{_tw(x0 - right - 2.75)}"/>'
                                f'<w:sz w:val="22"/></w:rPr><w:t xml:space="preserve"> </w:t></w:r>')
                runs.append(f'<w:r>{_picture_xml(*add_media(item["picture"]), x1 - x0, y1 - y0, True)}</w:r>')
                right = x1
            x0 = row[0]['picture']['bbox'][0]
            top = min(r['picture']['bbox'][1] for r in row) - PICTURE_FRAME
            bottom = max(r['picture']['bbox'][3] for r in row) + PICTURE_FRAME
            before = max(top - (top_margin if prev is None or page_break else prev[3]), 0.0)
            ppr = _ppr(jc='left', before=before, left=max(x0 - left_margin, 0), page_break=page_break)
            body.append(f'<w:p>{ppr}{"".join(runs)}</w:p>')
            prev = (page, top, page, bottom, None, None)
            continue

        if kind == 'p':
            ppr = _ppr(jc='both', before=before, lh=lh, page_break=page_break,
                       first_indent=18.0 if b['indented'] else 0.0)
            body.append(_body_para(b, layout, ppr))
        elif kind in ('h', 'c'):
            line = b['lines'][0]
            ppr = _ppr(jc='center', before=before, lh=lh, page_break=page_break)
            if b['spaced']:
                body.append(_spaced_para(line, layout, ppr))
            else:
                body.append(f'<w:p>{ppr}{"".join(_line_runs(line, layout))}</w:p>')
        else:                        # 'l' or 's': a line placed at its own left edge
            line = b['lines'][0]
            runs = _line_runs(line, layout)
            if not runs:
                continue
            ppr = _ppr(jc='left', before=before, lh=lh, page_break=page_break,
                       left=max(line['x0'] - left_margin, 0))
            body.append(f'<w:p>{ppr}{"".join(runs)}</w:p>')
        prev = (page, top, end_page, bottom, b['lines'][-1]['base'], lh)

    pg_num = f'<w:pgNumType w:start="{first_num}"/>' if first_num and first_num > 0 else ''
    footer_ref = '<w:footerReference w:type="default" r:id="rIdFooter"/>' if nums else ''  # only if the source has page numbers
    sect = (f'<w:sectPr>{footer_ref}'
            f'<w:pgSz w:w="{_tw(layout.page_w)}" w:h="{_tw(layout.page_h)}"/>'
            f'<w:pgMar w:top="{_tw(top_margin)}" w:right="{_tw(right_margin)}" '
            f'w:bottom="{_tw(bottom_margin)}" w:left="{_tw(left_margin)}" w:header="0" '
            f'w:footer="{_tw(max(footer_dist, 0))}" w:gutter="0"/>{pg_num}</w:sectPr>')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {NS}>'
                + (f'<w:background w:color="{layout.page_bg.lstrip("#")}"/>' if layout.page_bg != '#FFFFFF' else '') +
                f'<w:body>{"".join(body)}{"<w:p/>" if body and body[-1].endswith("</w:tbl>") else ""}'
                f'{sect}</w:body></w:document>')       # Word wants a paragraph after a last table

    font_files = [name for _, names in fonts for name in names]
    keys = ['{' + str(uuid.uuid4()).upper() + '}' for _ in font_files]
    rels = [f'<Relationship Id="rIdStyles" Type="{REL}/styles" Target="styles.xml"/>',
            f'<Relationship Id="rIdSettings" Type="{REL}/settings" Target="settings.xml"/>',
            f'<Relationship Id="rIdFonts" Type="{REL}/fontTable" Target="fontTable.xml"/>',
            f'<Relationship Id="rIdFooter" Type="{REL}/footer" Target="footer1.xml"/>']
    rels += [f'<Relationship Id="{rid}" Type="{REL}/image" Target="media/{escape(name)}"/>'
             for rid, name, _ in media]
    font_rels = ''.join(f'<Relationship Id="rIdFont{k}" Type="{REL}/font" Target="fonts/font{k}.odttf"/>'
                        for k in range(1, len(font_files) + 1))
    ct_main = 'application/vnd.openxmlformats-officedocument.wordprocessingml'
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Default Extension="jpg" ContentType="image/jpeg"/>'
        '<Default Extension="odttf" ContentType="application/vnd.openxmlformats-officedocument.obfuscatedFont"/>'
        f'<Override PartName="/word/document.xml" ContentType="{ct_main}.document.main+xml"/>'
        f'<Override PartName="/word/styles.xml" ContentType="{ct_main}.styles+xml"/>'
        f'<Override PartName="/word/settings.xml" ContentType="{ct_main}.settings+xml"/>'
        f'<Override PartName="/word/fontTable.xml" ContentType="{ct_main}.fontTable+xml"/>'
        f'<Override PartName="/word/footer1.xml" ContentType="{ct_main}.footer+xml"/>'
        '</Types>')
    package_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    f'<Relationship Id="rId1" Type="{REL}/officeDocument" Target="word/document.xml"/>'
                    '</Relationships>')

    def relationships(items):
        return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                + ''.join(items) + '</Relationships>')

    with zipfile.ZipFile(out_path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', content_types)
        z.writestr('_rels/.rels', package_rels)
        z.writestr('word/document.xml', document)
        z.writestr('word/styles.xml', _styles(layout, layout.body_size))
        z.writestr('word/settings.xml', _settings())
        z.writestr('word/fontTable.xml', _font_table(fonts, keys))
        z.writestr('word/footer1.xml', _footer(layout, num_size, digits_font))
        z.writestr('word/_rels/document.xml.rels', relationships(rels))
        z.writestr('word/_rels/fontTable.xml.rels', relationships([font_rels]))
        for rid, name, path in media:
            z.write(path, f'word/media/{name}')
        for k, (fname, key) in enumerate(zip(font_files, keys), 1):
            with open(os.path.join(font_dir, fname), 'rb') as fh:
                z.writestr(f'word/fonts/font{k}.odttf', _obfuscate(fh.read(), key))
    return out_path
