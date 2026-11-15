"""The reading order of a SutonnyMJ PDF as blocks: paragraphs, headings, centred lines,
other lines, pictures and page numbers. Markdown and DOCX output are both built from these.

Each block is a dict with:
    kind     'p' body paragraph, 'h' large centred heading, 's' subheading (bold line
             at the left margin), 'c' centred line, 'l' other line, 'img' picture,
             'num' page number
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


def read_blocks(doc, layout, img_dir):
    """Blocks of the whole document in reading order. Pictures are saved to img_dir."""
    os.makedirs(img_dir, exist_ok=True)
    blocks = []
    open_para = None        # a body paragraph may continue on the next line or page
    prev_line = None

    for page_no, page in enumerate(doc):
        items = [dict(line=dict(l, page=page_no), y=l['base']) for l in read_lines(page)]
        for pic in save_images(doc, page, page_no, img_dir, layout):
            items.append(dict(picture=pic, y=pic['bbox'][1]))
        items.sort(key=lambda d: d['y'])

        for item in items:
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
