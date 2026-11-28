"""The reading order of a SutonnyMJ PDF as blocks: paragraphs, headings, centred lines,
other lines, pictures and page numbers. Markdown and DOCX output are both built from these.

Each block is a dict with:
    kind     'p' body paragraph, 'h' large centred heading, 's' subheading (bold line
             at the left margin), 'c' centred line, 'l' other line, 'img' picture,
             'num' page number, 'table' table (see find_tables and _table_block)
    page     page index where the block starts
    lines    source lines (dicts from read_lines) for text blocks
    indented first line indented (paragraphs)
    spaced   letter-spaced heading whose spaces must be removed (centred lines)
    picture  dict from save_images (pictures)
"""
import os
import re

from ._common import is_mj, read_lines, save_images, span_text


def plain_line(line):
    return ''.join(span_text(s) for s in line['spans']).strip()


def is_subheading(line, layout):
    """A section heading inside a chapter: SutonnyMJ text in bold, at least body size, set
    at the left margin, as section titles inside a chapter usually are."""
    shown = [s for s in line['spans'] if s['text'].strip()]
    mj = [s for s in shown if is_mj(s['font'])]
    return (bool(mj) and all('Bold' in s['font'] for s in mj)
            and line['mj_size'] >= layout.body_size - 0.2
            and abs(line['x0'] - layout.body_l) < 8
            and len(plain_line(line)) <= 80)


_VIRAMA = '্'


def _clusters(word):
    """Number of letter clusters (a conjunct such as প্র or দ্ধি counts once)."""
    n, prev = 0, ''
    for ch in word:
        if ch.isalnum() and not ('ঁ' <= ch <= 'ঃ' or '়' <= ch <= 'ৗ') and prev != _VIRAMA:
            n += 1
        prev = ch
    return n


def is_letter_spaced(line):
    """A heading set with a space after every letter cluster ("প্র থ ম  প র্ব")."""
    return is_letter_spaced_text(plain_line(line))


def is_letter_spaced_text(text):
    """Text with a space after every letter cluster ("প্র থ ম  প র্ব")."""
    words = text.split()
    if len(words) < 3:
        return False
    single = sum(1 for w in words if _clusters(w) <= 1)
    return single >= 0.7 * len(words)


def despace(text):
    """Undo letter spacing: single spaces sit between letters, wider gaps between words."""
    return ' '.join(w.replace(' ', '') for w in re.split(r' {2,}', text.strip()))


# ---------------------------------------------------------------- tables

def _edges(values, tol=2.0):
    """Sorted positions with near-equal ones (within tol pt) merged."""
    out = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _index(edges, value, tol=2.0):
    return min(range(len(edges)), key=lambda i: abs(edges[i] - value)) if edges else 0


def _text_columns(page, bbox, row_edges):
    """Column starts of a table drawn with unbroken horizontal rules: x positions where
    text lines start in at least a third of the rows (and two of them), and whose lines
    stay inside their column (a paragraph's first-line indent is not a column)."""
    lines = []                                     # (x0, x1, row) of every text line in the table
    for block in page.get_text('dict', clip=bbox)['blocks']:
        for line in block.get('lines', []):
            if not ''.join(s['text'] for s in line['spans']).strip():
                continue
            y = (line['bbox'][1] + line['bbox'][3]) / 2
            row = next((r for r in range(len(row_edges) - 1) if row_edges[r] <= y < row_edges[r + 1]), None)
            if row is not None:
                lines.append((line['bbox'][0], line['bbox'][2], row))
    starts = []
    for x in _edges([x0 for x0, _, _ in lines], tol=4.0):
        rows = {r for x0, _, r in lines if abs(x0 - x) <= 4.0}
        if len(rows) >= max(2, (len(row_edges) - 1) / 3):
            starts.append(x)
    # a start is a column only if the lines starting before it end before it
    columns = starts[:1]
    for x in starts[1:]:
        before = [x1 for x0, x1, _ in lines if x0 < x - 4.0]
        if before and sum(x1 <= x + 2 for x1 in before) >= 0.8 * len(before):
            columns.append(x)
    return columns


def _horizontal_rules(page):
    """Horizontal rules drawn on a page, as (y, x0, x1, joints): thin rectangles or lines,
    with pieces drawn end to end on one level (a rule drawn cell by cell) joined into one
    and the places where they meet kept as joints. Only rules at least 30 pt long count. A
    table has at least three; most pages have none, so counting them first spares those
    pages the table finder, which is slow (about 50 ms a page)."""
    import pymupdf as fitz
    pieces = []
    for drawing in page.get_cdrawings():
        for item in drawing['items']:
            if item[0] == 're':
                r = fitz.Rect(item[1])
                if r.height <= 2.5 and r.width >= 3:
                    pieces.append(((r.y0 + r.y1) / 2, r.x0, r.x1))
            elif item[0] == 'l':
                a, b = fitz.Point(item[1]), fitz.Point(item[2])
                if abs(a.y - b.y) <= 1 and abs(a.x - b.x) >= 3:
                    pieces.append(((a.y + b.y) / 2, min(a.x, b.x), max(a.x, b.x)))
    rules = []
    for y, x0, x1 in sorted(pieces, key=lambda p: (round(p[0], 1), p[1])):
        last = rules[-1] if rules else None
        if last and abs(last[0] - y) <= 0.8 and -1 <= x0 - last[2] <= 3:
            last[3].append((last[2] + x0) / 2)
            last[2] = max(last[2], x1)
        else:
            rules.append([y, x0, x1, []])
    return [tuple(r) for r in rules if r[2] - r[1] >= 30]


def _underlines(rules, page):
    """Rules drawn as underlines: less than 2.8 pt below the baseline of text above them
    (underlines sit about 1.4 pt below; a table's rules leave room for the descenders,
    4 pt or more)."""
    bases = [(s['origin'][1], line['bbox']) for b in page.get_text('dict')['blocks']
             for line in b.get('lines', []) for s in line['spans'] if s['text'].strip()]
    out = set()
    for k, (y, x0, x1, _) in enumerate(rules):
        for base, (tx0, _, tx1, _) in bases:
            if 0 <= y - base < 2.8 and min(x1, tx1) - max(x0, tx0) > 0.3 * (x1 - x0):
                out.add(k)
                break
    return out


def _ruled_rows(rules, avoid, max_gap=300.0):
    """Stacks of three or more rules with the same left and right ends, none further than
    max_gap below the one above, outside the areas in avoid: the rows of tables drawn with
    horizontal rules only. Returns [(x0, x1, [y, ...], joints)], joints being the places
    where the stacked rules' pieces meet in at least half of them (column boundaries)."""
    import pymupdf as fitz
    free = [r for r in rules if not any(b.contains(fitz.Point((r[1] + r[2]) / 2, r[0])) for b in avoid)]
    stacks = []
    for rule in sorted(free):
        y, x0, x1, _ = rule
        for s in stacks:
            if abs(s[0] - x0) <= 3 and abs(s[1] - x1) <= 3 and 0 < y - s[2][-1][0] <= max_gap:
                s[2].append(rule)
                break
        else:
            stacks.append((x0, x1, [rule]))
    out = []
    for x0, x1, members in stacks:
        ys = _edges([r[0] for r in members])
        if len(ys) < 3:
            continue
        joints = [j for j in _edges([j for r in members for j in r[3]], tol=3.0)
                  if sum(any(abs(j - k) <= 3 for k in r[3]) for r in members) >= 0.5 * len(members)]
        out.append((x0, x1, ys, joints))
    return out


def find_tables(page, layout):
    """Tables on a page, as dicts: bbox, ruled (borders all round, or only rules between
    rows), x and y cell edges, and cells [(row, col, rowspan, colspan, rect)].

    Ruled tables come from PyMuPDF's table finder with their merged cells. A table drawn
    with horizontal rules only (a timeline, a comparison) is a stack of rules of the same
    length: its rows lie between them and its columns where its text lines start. Both must
    have two rows and two columns and be at least half the text width, so a rule under a
    heading or above the footnotes is not taken for a table."""
    import pymupdf as fitz
    rules = _horizontal_rules(page)
    if len(rules) < 3:
        return []
    min_w = 0.5 * (layout.body_r - layout.body_l)
    found = []
    try:
        ruled = page.find_tables().tables
    except Exception:                             # an odd drawing PyMuPDF cannot analyse
        ruled = []
    for t in ruled:
        rects = [(r, c, cell) for r, row in enumerate(t.rows) for c, cell in enumerate(row.cells) if cell]
        xs = _edges([v for _, _, cell in rects for v in (cell[0], cell[2])])
        ys = _edges([v for _, _, cell in rects for v in (cell[1], cell[3])])
        if len(xs) < 3 or len(ys) < 3 or t.bbox[2] - t.bbox[0] < min_w:
            continue
        cells = []
        for _, _, (x0, y0, x1, y1) in rects:
            r, c = _index(ys, y0), _index(xs, x0)
            cells.append((r, c, max(1, _index(ys, y1) - r), max(1, _index(xs, x1) - c), fitz.Rect(x0, y0, x1, y1)))
        found.append(dict(bbox=fitz.Rect(t.bbox), ruled=True, xs=xs, ys=ys, cells=cells))
    # rules-only tables, from the rules outside the ruled tables (not underlines); the
    # columns lie where the rules' pieces meet, or else where the text lines start
    ruled_boxes = [fitz.Rect(f['bbox']) + (-2, -2, 2, 2) for f in found]
    under = _underlines(rules, page)
    rules = [r for k, r in enumerate(rules) if k not in under]
    for x0, x1, ys, joints in _ruled_rows(rules, ruled_boxes):
        bbox = fitz.Rect(x0, ys[0], x1, ys[-1])
        if bbox.width < min_w:
            continue
        if joints:
            xs = [bbox.x0] + joints + [bbox.x1]
        else:
            starts = _text_columns(page, bbox, ys)
            if len(starts) < 2:
                continue
            xs = [bbox.x0] + [x - 1 for x in starts[1:]] + [bbox.x1]
        cells = [(r, c, 1, 1, fitz.Rect(xs[c], ys[r], xs[c + 1], ys[r + 1]))
                 for r in range(len(ys) - 1) for c in range(len(xs) - 1)]
        found.append(dict(bbox=bbox, ruled=False, xs=xs, ys=ys, cells=cells))
    return found


def _table_block(page, page_no, table):
    """A 'table' block: rows of cells {lines, colspan, rowspan, merged}, read cell by cell
    so text from neighbouring columns never mixes; lines lists them all in reading order."""
    n_rows, n_cols = len(table['ys']) - 1, len(table['xs']) - 1
    grid = [[None] * n_cols for _ in range(n_rows)]
    for r, c, rs, cs, rect in table['cells']:
        if r >= n_rows or c >= n_cols or grid[r][c] is not None:
            continue
        cell = dict(lines=[dict(l, page=page_no) for l in read_lines(page, clip=rect)],
                    rowspan=min(rs, n_rows - r), colspan=min(cs, n_cols - c), merged=False,
                    x0=rect.x0, x1=rect.x1)
        grid[r][c] = cell
        for rr in range(r, r + cell['rowspan']):
            for cc in range(c, c + cell['colspan']):
                if (rr, cc) != (r, c) and grid[rr][cc] is None:
                    # covered by the merged cell: 'col' beside it in its own row, 'row' below
                    # it (Word marks these two differently)
                    grid[rr][cc] = dict(lines=[], rowspan=1, colspan=1, merged='col' if rr == r else 'row',
                                        start=c)
    rows = [[cell or dict(lines=[], rowspan=1, colspan=1, merged=False) for cell in row] for row in grid]
    lines = [l for row in rows for cell in row for l in cell['lines']]
    return dict(kind='table', page=page_no, rows=rows, lines=lines, ruled=table['ruled'],
                bbox=tuple(table['bbox']), widths=[b - a for a, b in zip(table['xs'], table['xs'][1:])])


_NUMBERED = re.compile(r'^\s*[০-৯0-9]+\s*[.)।]')


def cell_paragraphs(cell):
    """A table cell's lines as paragraphs: [(lines, align)], align 'center' or 'left'.
    Lines run together into one paragraph; a numbered item ("১.", "২.") starts a new one.
    A paragraph is centred when its lines sit in the middle of the cell."""
    paras = []
    for line in cell['lines']:
        if not plain_line(line):
            continue
        if not paras or _NUMBERED.match(plain_line(line)):
            paras.append([])
        paras[-1].append(line)
    out = []
    for lines in paras:
        gaps = [(l['x0'] - cell['x0'], cell['x1'] - l['x1']) for l in lines]
        centred = all(left > 6 and abs(left - right) < 5 for left, right in gaps)
        out.append((lines, 'center' if centred else 'left'))
    return out


def join_lines(texts):
    """Lines of one paragraph as one string: a space between lines, none after a line that
    ends in a hyphen (a word or compound broken at the line end, "আচার-" + "প্রথার")."""
    out = ''
    for text in texts:
        if not text:
            continue
        out += text if not out or out.endswith('-') else ' ' + text
    return out


def _inside(line, bbox):
    """A line starts inside a table's area."""
    x0, y0, x1, y1 = bbox
    return x0 - 1 <= line['x0'] <= x1 and y0 - 1 <= line['base'] <= y1 + 1


def read_blocks(doc, layout, img_dir):
    """Blocks of the whole document in reading order. Pictures are saved to img_dir."""
    os.makedirs(img_dir, exist_ok=True)
    blocks = []
    open_para = None        # a body paragraph may continue on the next line or page
    prev_line = None

    for page_no, page in enumerate(doc):
        tables = find_tables(page, layout)
        items = [dict(line=dict(l, page=page_no), y=l['base']) for l in read_lines(page)
                 if not any(_inside(l, t['bbox']) for t in tables)]
        for t in tables:
            items.append(dict(table=_table_block(page, page_no, t), y=t['bbox'][1]))
        for pic in save_images(doc, page, page_no, img_dir, layout):
            items.append(dict(picture=pic, y=pic['bbox'][1]))
        items.sort(key=lambda d: d['y'])

        for item in items:
            if 'table' in item:
                blocks.append(item['table'])
                open_para = None
                continue
            if 'picture' in item:
                blocks.append(dict(kind='img', page=page_no, picture=item['picture']))
                open_para = None
                continue
            line = item['line']
            if line['base'] > layout.foot_y:
                blocks.append(dict(kind='num', page=page_no, lines=[line]))
                continue
            if layout.is_body(line):
                if not open_para or layout.is_indented(line) or (prev_line and layout.is_short(prev_line)):
                    open_para = dict(kind='p', page=page_no, lines=[], indented=layout.is_indented(line))
                    blocks.append(open_para)
                open_para['lines'].append(line)     # page-number blocks may sit in between
                prev_line = line
            elif layout.is_centred(line):
                open_para = None
                large = line['mj_size'] > layout.body_size + 1.5
                blocks.append(dict(kind='h' if large else 'c', page=page_no, lines=[line],
                                   spaced=is_letter_spaced(line)))
            else:
                open_para = None
                kind = 's' if is_subheading(line, layout) else 'l'
                blocks.append(dict(kind=kind, page=page_no, lines=[line]))
    return blocks
