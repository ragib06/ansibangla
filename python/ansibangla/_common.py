"""Shared reading of SutonnyMJ PDFs: text lines, pictures and the measured page layout."""
import os
from collections import Counter

import pymupdf as fitz

from .bijoy import convert as bijoy_convert


def is_mj(font):
    """True for spans set in the SutonnyMJ (Bijoy) font."""
    return 'MJ' in font


def span_text(span):
    """Span text as Unicode Bengali (SutonnyMJ spans) or unchanged (other fonts).
    A | in another font is a danda typed after an English word, as in "(DNA)|"."""
    if is_mj(span['font']):
        return bijoy_convert(span['text'])
    return span['text'].replace('|', '।')


_PRE_KEYS = None


def _needs_join(prev, nxt):
    """True when two spans of one line must be shaped as one piece of text: the next span
    starts with a vowel sign, chandrabindu or halant, or the previous one ends with a
    pre-base vowel sign (their Unicode order only works inside one run)."""
    if not (is_mj(prev['font']) and is_mj(nxt['font'])):
        return False
    first = bijoy_convert(nxt['text'][:1]) if nxt['text'] else ''
    last = bijoy_convert(prev['text'][-1:]) if prev['text'] else ''
    signs = '\u09be\u09bf\u09c0\u09c1\u09c2\u09c3\u09c7\u09c8\u09cb\u09cc\u09d7\u0981\u0982\u0983\u09cd'
    return (first[:1] in signs and first[:1] != '') or (last[-1:] in '\u09bf\u09c7\u09c8' and last != '')


def _merge_spans(spans):
    """Join spans that must shape together; the joined span keeps the first span's font."""
    out = []
    for sp in spans:
        if out and _needs_join(out[-1], sp):
            out[-1] = dict(out[-1], text=out[-1]['text'] + sp['text'])
        else:
            out.append(dict(sp))
    return out


def read_lines(page, clip=None):
    """Text lines of a page (or of the rectangle clip on it), top to bottom, with their spans.

    PyMuPDF splits a justified line with wide word gaps into several fragments on one
    baseline; they are merged back into one line here."""
    raw = []
    for block in page.get_text('dict', clip=clip)['blocks']:
        for line in block.get('lines', []):
            spans = [s for s in line['spans'] if s['text'].strip() or s['text']]
            if not any(s['text'].strip() for s in spans):
                continue
            raw.append(dict(
                base=max(s['origin'][1] for s in spans if s['text'].strip()),
                x0=line['bbox'][0], x1=line['bbox'][2], spans=spans))
    raw.sort(key=lambda d: (round(d['base'] / 2.0), d['x0']))
    merged = []
    for r in raw:
        prev = merged[-1] if merged else None
        if prev and abs(prev['base'] - r['base']) < 1.5 and r['x0'] >= prev['x1'] - 1:
            gap = dict(prev['spans'][-1], text=' ')
            prev['spans'] = prev['spans'] + [gap] + r['spans']
            prev['x1'] = max(prev['x1'], r['x1'])
        else:
            merged.append(dict(r))
    lines = []
    for r in merged:
        spans = _merge_spans(r['spans'])
        shown = [s for s in spans if s['text'].strip()]
        mj_sizes = [s['size'] for s in shown if is_mj(s['font'])]
        lines.append(dict(
            x0=r['x0'], x1=r['x1'], base=r['base'],
            size=max(s['size'] for s in shown),
            mj_size=max(mj_sizes) if mj_sizes else 0.0,
            spans=spans))
    lines.sort(key=lambda d: d['base'])
    return lines


class Layout:
    """Page geometry and body-text metrics measured from the whole document."""

    def __init__(self, doc, scale=0.9):
        self.scale = scale                         # font-size factor for the Unicode PDF
        self.page_w = doc[0].rect.width
        self.page_h = doc[0].rect.height

        self.page_bg = _page_colour(doc)
        all_lines = [l for page in doc for l in read_lines(page)]
        self.foot_y = self._footer_line(all_lines)
        mj_lines = [l for l in all_lines if any(is_mj(s['font']) for s in l['spans'])]
        if not mj_lines:
            raise ValueError('no SutonnyMJ (Bijoy) text found: the file may be in Unicode '
                             'already, set in another font, or a scan with no text')
        # Left edge of the body column: the most common left edge of SutonnyMJ lines
        self.body_l = Counter(round(l['x0']) for l in mj_lines).most_common(1)[0][0]
        at_margin = [l for l in mj_lines if abs(l['x0'] - self.body_l) < 3]
        # Body size: the most common size at the left margin
        self.body_size = Counter(round(l['mj_size'], 2) for l in at_margin).most_common(1)[0][0]
        # Right edge of justified lines: the most common right edge of body lines
        wide = [l for l in at_margin if abs(l['mj_size'] - self.body_size) < .1 and l['x1'] > self.body_l + 150]
        self.body_r = Counter(round(l['x1']) for l in wide).most_common(1)[0][0]

    def _footer_line(self, lines):
        """Baseline below which only page numbers sit.

        Page numbers are lines of digits alone in the bottom quarter of the page; the
        footer zone starts just above the highest common page-number baseline. Body text
        can run close to it, so a fixed share of the page height is not safe. Without
        page numbers nothing is treated as footer."""
        bases = []
        for line in lines:
            if line['base'] < self.page_h * 0.75:
                continue
            text = ''.join(span_text(s) for s in line['spans']).strip()
            if text and all(ch in '০১২৩৪৫৬৭৮৯0123456789' for ch in text):
                bases.append((round(line['base']), line['size']))
        if not bases:
            return self.page_h
        counts = Counter(b for b, _ in bases)
        common = [b for b, n in counts.items() if n >= max(2, 0.2 * len(bases))] or [counts.most_common(1)[0][0]]
        top = min(common)
        size = max(s for b, s in bases if b == top)
        return top - 0.8 * size

    def is_body(self, line):
        """Running text: not bold, at the left margin, up to body size (notes are smaller)."""
        return (9.0 < line['mj_size'] <= self.body_size + 0.2
                and line['x0'] < self.body_l + 23
                and any(is_mj(s['font']) for s in line['spans'])
                and not any('Bold' in s['font'] for s in line['spans'] if s['text'].strip()))

    def is_indented(self, line):
        return line['x0'] > self.body_l + 8

    def is_short(self, line):
        """A line that ends its paragraph (it does not reach the right edge)."""
        return line['x1'] < self.body_r - 7

    def is_centred(self, line):
        """Centred on the page: short centred lines, or headings in a larger size however
        long (a long chapter title can start near the margin)."""
        mid = (line['x0'] + line['x1']) / 2
        if abs(mid - self.page_w / 2) >= 10:
            return False
        return line['x0'] > self.page_w * 0.25 or line['mj_size'] > self.body_size + 1.5


def _page_colour(doc, pages=8):
    """Page background as '#RRGGBB': the most common colour of the page margins (the outer
    tenth of each side) on a few pages, skipping the first page (often a cover)."""
    counts = Counter()
    picks = list(range(1, len(doc)))[:pages] or [0]
    for n in picks:
        pix = doc[n].get_pixmap(dpi=12, alpha=False, colorspace=fitz.csRGB)
        w, h = pix.width, pix.height
        mx, my = max(1, w // 10), max(1, h // 10)
        for y in range(h):
            for x in range(w):
                if x < mx or x >= w - mx or y < my or y >= h - my:
                    counts[pix.pixel(x, y)[:3]] += 1
    r, g, b = counts.most_common(1)[0][0] if counts else (255, 255, 255)
    return f'#{r:02X}{g:02X}{b:02X}'


def _with_soft_mask(doc, xref):
    """An image with its soft mask (/SMask) applied as its alpha channel. PyMuPDF loads such
    an image without its mask: a diagram drawn as black ink through a mask (the colour
    plane all black, the drawing in the mask) would come out as a black square."""
    pix = fitz.Pixmap(doc, xref)
    kind, value = doc.xref_get_key(xref, 'SMask')
    if kind != 'xref':
        return pix
    try:
        mask = fitz.Pixmap(doc, int(value.split()[0]))
        base = fitz.Pixmap(pix, 0) if pix.alpha else pix         # colour planes only
        if mask.n != 1 or (mask.width, mask.height) != (base.width, base.height):
            mask = fitz.Pixmap(fitz.csGRAY, mask) if mask.n != 1 else mask
            if (mask.width, mask.height) != (base.width, base.height):
                mask = fitz.Pixmap(mask, base.width, base.height, None)
        return fitz.Pixmap(base, mask)
    except Exception:                                  # an odd mask: keep the image as it was
        return pix


def save_images(doc, page, page_no, img_dir, layout):
    """Save the pictures of one page. Returns dicts with bbox, path and cover flag."""
    saved = []
    inline = None
    infos = page.get_image_info(xrefs=True)            # in drawing order
    for k, info in enumerate(infos):
        x0, y0, x1, y1 = info['bbox']
        if _hidden(info, infos[k + 1:]):
            continue                                   # a backdrop under a later picture
        if info['xref']:
            pix = _with_soft_mask(doc, info['xref'])
            name = f'p{page_no + 1}_{info["xref"]}'
        else:
            # an inline image (inside the page's content stream) has no xref
            if inline is None:
                inline = _inline_images(page)
            data = _match_inline(inline, info['bbox'])
            if data is None:
                continue
            pix = fitz.Pixmap(data)
            name = f'p{page_no + 1}_inline{k}'
        if pix.n - pix.alpha >= 4:                     # CMYK -> RGB
            pix = fitz.Pixmap(fitz.csRGB, pix)
        cover = (x1 - x0) * (y1 - y0) > 0.5 * layout.page_w * layout.page_h
        path = os.path.join(img_dir, f'{name}.' + ('jpg' if cover else 'png'))
        if cover:
            with open(path, 'wb') as fh:
                fh.write(pix.tobytes('jpeg', 88))
        else:
            pix.save(path)
        saved.append(dict(bbox=info['bbox'], path=path, cover=cover))
    return saved


def _area(rect):
    """Area of a rectangle; 0 when empty (works on every PyMuPDF version)."""
    return max(rect.width, 0) * max(rect.height, 0) if not rect.is_empty else 0.0


def _hidden(info, later):
    """True when a picture drawn later covers at least 90% of this one."""
    rect = fitz.Rect(info['bbox'])
    area = _area(rect)
    return area > 0 and any(_area(rect & fitz.Rect(o['bbox'])) >= 0.9 * area for o in later)


def _inline_images(page):
    """(bbox, image bytes) of the page's image blocks; these include inline images."""
    blocks = page.get_text('dict', flags=fitz.TEXT_PRESERVE_IMAGES)['blocks']
    return [(fitz.Rect(b['bbox']), b['image']) for b in blocks if b.get('type') == 1 and b.get('image')]


def _match_inline(inline, bbox):
    """Bytes of the image block that covers the same area as bbox, or None."""
    target = fitz.Rect(bbox)
    best, best_area = None, 0.0
    for rect, data in inline:
        area = _area(rect & target)
        if area > best_area:
            best, best_area = data, area
    return best if best_area > 0.5 * max(_area(target), 1e-6) else None
