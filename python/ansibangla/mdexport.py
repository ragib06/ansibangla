"""Markdown that follows a SutonnyMJ PDF's layout: paragraphs with first-line indents,
headings, bold and italic runs, centred lines and pictures."""
import os
import re

from ._common import is_mj, span_text
from .blocks import cell_paragraphs, despace, join_lines, plain_line, read_blocks


def _escape(text):
    """Escape characters Markdown would read as markup (footnote asterisks, underscores)."""
    return re.sub(r'([\\`*_])', r'\\\1', text)


def _md_span(span):
    text = _escape(span_text(span))
    if is_mj(span['font']):
        bold, ital = 'Bold' in span['font'], 'Italic' in span['font']
    else:
        bold, ital = False, 'Italic' in span['font']          # Latin stays as typed
    core = text.strip()
    if not core:
        return text
    lead = text[:len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    if bold and ital:
        core = f'***{core}***'
    elif bold:
        core = f'**{core}**'
    elif ital:
        core = f'*{core}*'
    return lead + core + trail


def _md_line(line):
    return ''.join(_md_span(s) for s in line['spans'] if s['text']).strip()


def _md_table(block):
    """A table as a GFM table, the first row as its header. Markdown has no merged cells:
    a merged cell's text sits in its first cell and the cells it covers stay empty."""
    def cell_text(cell):
        if cell['merged']:
            return ''
        paras = [join_lines(_md_line(line) for line in lines) for lines, _ in cell_paragraphs(cell)]
        return '<br>'.join(p.replace('|', '\\|') for p in paras)

    rows = [[cell_text(c) for c in row] for row in block['rows']]
    lines = ['| ' + ' | '.join(rows[0]) + ' |', '|' + '---|' * len(rows[0])]
    lines += ['| ' + ' | '.join(r) + ' |' for r in rows[1:]]
    return '\n'.join(lines)


def export_markdown(doc, layout, img_dir, img_ref, blocks=None):
    """Markdown text. Pictures are saved to img_dir and linked as img_ref/<file>."""
    os.makedirs(img_dir, exist_ok=True)
    if blocks is None:
        blocks = read_blocks(doc, layout, img_dir)
    out = []
    for block in blocks:
        kind = block['kind']
        if kind == 'p':
            parts = []
            for line in block['lines']:
                text = _md_line(line)
                if parts and not parts[-1].endswith('-'):
                    text = ' ' + text
                parts.append(text)
            out.append(('&emsp;&emsp;' if block['indented'] else '') + ''.join(parts))
        elif kind in ('h', 'c'):
            line = block['lines'][0]
            text = _escape(despace(plain_line(line))) if block['spaced'] else _md_line(line)
            out.append('## ' + text if kind == 'h' else f'<p align="center">{text}</p>')
        elif kind == 's':
            out.append('### ' + _escape(plain_line(block['lines'][0])))
        elif kind == 'l':
            text = _md_line(block['lines'][0])
            if not text:
                continue
            out.append(text)
        elif kind == 'img':
            out.append(f"![]({img_ref}/{os.path.basename(block['picture']['path'])})")
        elif kind == 'table':
            out.append(_md_table(block))
        else:
            continue                    # page number: the page break replaces it
        out.append('')
    return '\n'.join(out).rstrip() + '\n'
