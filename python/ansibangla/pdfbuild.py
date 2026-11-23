"""Rebuild a SutonnyMJ PDF as a Unicode Bengali PDF with the same page layout.

Body text is rebuilt in runs (consecutive body lines form one justified block). A script
in the page shrinks each run's font until it takes no more lines than its source did,
so Unicode's wider glyphs cannot push text into lines placed at their source positions.
Headless Chrome prints the result. The same HTML, with its fonts and pictures embedded,
is the 'html' output: a page any browser can print to PDF without Chrome being installed.
"""
import base64
import html
import mimetypes
import os
import shutil
import subprocess
import tempfile

import pymupdf as fitz

from ._common import is_mj, read_lines, save_images, span_text
from .blocks import despace, is_letter_spaced, plain_line

FONT_FILES = ('NotoSerifBengaliW94-Regular.ttf', 'NotoSerifBengaliW94-Bold.ttf')   # tools/make_fonts.py
PICTURE_FRAME = 2.2         # frame width in pt, a typical frame around book pictures

FIT_SCRIPT = """
<script>
// Each body run must take no more lines than its source. Keep the font size the same
// everywhere: tighten word spacing, then letter spacing, and shrink the font only as a
// last resort (never below 92%). Runs that end up shorter spread their lines to fill
// the source height.
function fitAll() {
document.querySelectorAll('.body').forEach(function (r) {
  var n = +r.dataset.n;
  var lh = parseFloat(r.dataset.lh);                  // pt
  var px = lh * 96 / 72;
  var fs = parseFloat(getComputedStyle(r).fontSize);
  var steps = [[0,0,1],[-.03,0,1],[-.06,0,1],[-.09,0,1],[-.12,0,1],
               [-.12,-.01,1],[-.12,-.02,1],[-.12,-.02,.97],[-.12,-.02,.94],[-.12,-.02,.92]];
  var used = n;
  for (var i = 0; i < steps.length; i++) {
    r.style.wordSpacing = steps[i][0] + 'em';
    r.style.letterSpacing = steps[i][1] + 'em';
    r.style.fontSize = (fs * steps[i][2]) + 'px';
    used = Math.round(r.getBoundingClientRect().height / px);
    if (used <= n) break;
  }
  if (used < n && used > 0) {
    r.style.lineHeight = Math.min(lh * n / used, lh * 1.2) + 'pt';
  }
});
// a paragraph carried on to the next page: justify its last line only if it is already mostly full
document.querySelectorAll('.p.cont').forEach(function (p) {
  var rg = document.createRange(); rg.selectNodeContents(p);
  var rects = Array.prototype.slice.call(rg.getClientRects()).filter(function (q) { return q.width > 1; });
  if (!rects.length) return;
  var top = Math.max.apply(null, rects.map(function (q) { return q.top; }));
  var last = rects.filter(function (q) { return Math.abs(q.top - top) < 4; });
  var w = Math.max.apply(null, last.map(function (q) { return q.right; })) -
          Math.min.apply(null, last.map(function (q) { return q.left; }));
  if (w >= 0.7 * p.parentNode.getBoundingClientRect().width) p.classList.add('full');
});
}
// measure only after the Bengali fonts are loaded, or the fallback font gives wrong line counts
Promise.all([document.fonts.load('400 12px Bn', '\u0985'), document.fonts.load('700 12px Bn', '\u0985')])
  .then(function () { return document.fonts.ready; }).then(fitAll, fitAll)
  .then(function () { document.documentElement.dataset.ready = '1'; });   // safe to print now
</script>
"""

# a page with no fitting script is ready to print once its fonts are loaded
READY_SCRIPT = """
<script>
document.fonts.ready.then(function () { document.documentElement.dataset.ready = '1'; });
</script>
"""


def asset_url(path, embed):
    """URL of a font or picture: a data: URL when embed is true (a page that works on
    its own anywhere), else a file:// URL (for headless Chrome on this machine)."""
    if not embed:
        return 'file://' + os.path.abspath(path)
    ext = os.path.splitext(path)[1].lower()
    mime = {'.ttf': 'font/ttf', '.otf': 'font/otf', '.woff2': 'font/woff2'}.get(ext) \
        or mimetypes.guess_type(path)[0] or 'application/octet-stream'
    with open(path, 'rb') as fh:
        return f'data:{mime};base64,' + base64.b64encode(fh.read()).decode('ascii')


def find_chrome(explicit=None):
    """Path to a Chrome or Chromium binary, or raise RuntimeError."""
    candidates = [explicit, os.environ.get('ANSIBANGLA_CHROME')] + [
        'google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome']
    for c in candidates:
        if c and shutil.which(c):
            return shutil.which(c)
    raise RuntimeError('Chrome or Chromium is needed for PDF output. Install it, or pass '
                       'chrome=... / set ANSIBANGLA_CHROME to its path.')


def _span_html(span, layout, run_size=None):
    """One span. Inside body runs sizes are em of the run, so the run can be fitted."""
    font = span['font']
    text = span_text(span)
    if is_mj(font):
        cls = (['b'] if 'Bold' in font else []) + (['i'] if 'Italic' in font else [])
        size = f"{span['size'] / run_size:.4f}em" if run_size else f"{span['size'] * layout.scale:.2f}pt"
    else:
        cls = ['latin'] + (['i'] if 'Italic' in font else [])
        size = (f"{span['size'] / (run_size * layout.scale):.4f}em" if run_size
                else f"{span['size']:.2f}pt")
    return f'<span class="{" ".join(cls)}" style="font-size:{size}">{html.escape(text)}</span>'


def _body_runs(layout, lines):
    """Consecutive body lines of one size; any other line between them, or extra space
    (books that separate paragraphs by space instead of an indent), starts a new run.
    Each run is placed at its source position, so the space is kept."""
    body = [l for l in lines if layout.is_body(l)]
    gaps = sorted(b['base'] - a['base'] for a, b in zip(body, body[1:])
                  if abs(a['mj_size'] - b['mj_size']) < .1 and b['base'] > a['base'])
    normal = gaps[len(gaps) // 2] if gaps else None
    runs, current = [], []
    for line in lines:
        if layout.is_body(line) and (not current or abs(current[0]['mj_size'] - line['mj_size']) < .1) \
                and not (current and normal and line['base'] - current[-1]['base'] > 1.25 * normal):
            current.append(line)
            continue
        if current:
            runs.append(current)
            current = []
        if layout.is_body(line):
            current.append(line)
    if current:
        runs.append(current)
    return runs


def _run_html(layout, run, lh):
    size = run[0]['mj_size']
    paras = []
    for k, line in enumerate(run):
        if not paras or layout.is_indented(line) or layout.is_short(run[k - 1]):
            paras.append(dict(indented=layout.is_indented(line), parts=[]))
        seg = ''.join(_span_html(sp, layout, size) for sp in line['spans'] if sp['text']).rstrip()
        if paras[-1]['parts'] and not paras[-1]['parts'][-1].endswith('-</span>'):
            seg = ' ' + seg
        paras[-1]['parts'].append(seg)
    # a paragraph that carries on to the next page ends on a full line: justify that last line too
    runs_on = not layout.is_short(run[-1])
    top = run[0]['base'] - lh * 0.74
    items = []
    for k, p in enumerate(paras):
        cls = 'p' + (' ind' if p['indented'] else '') + (' cont' if runs_on and k == len(paras) - 1 else '')
        items.append(f'<p class="{cls}">' + ''.join(p['parts']) + '</p>')
    return (f'<div class="body" data-n="{len(run)}" data-lh="{lh:.2f}" '
            f'style="top:{top:.2f}pt;line-height:{lh:.2f}pt;font-size:{size * layout.scale:.2f}pt">'
            + ''.join(items) + '</div>')


def _page_html(doc, page, page_no, layout, img_dir, embed=False):
    lines = read_lines(page)
    # line spacing of the body text: median gap between consecutive body lines
    out, body_ids = [], set()
    for run in _body_runs(layout, lines):
        gaps = sorted(b['base'] - a['base'] for a, b in zip(run, run[1:]))
        lh = gaps[len(gaps) // 2] if gaps else run[0]['mj_size'] * 1.1
        out.append(_run_html(layout, run, lh))
        body_ids.update(id(l) for l in run)

    for line in lines:
        if id(line) in body_ids:
            continue
        inner = ''.join(_span_html(s, layout) for s in line['spans'] if s['text']).rstrip()
        base = line['base'] - 0.26 * line['size'] * (layout.scale if line['mj_size'] else 1.0)
        if line['base'] > layout.foot_y:
            out.append(f'<div class="ln center" style="top:{base:.2f}pt">{inner}</div>')
        elif layout.is_centred(line):
            if is_letter_spaced(line):
                # letter-spaced headings are real words set with tracking
                word = despace(plain_line(line))
                inner = (f'<span style="font-size:{line["size"] * layout.scale:.2f}pt;letter-spacing:.35em;'
                         f'margin-right:-.35em">{html.escape(word)}</span>')
            out.append(f'<div class="ln center" style="top:{base:.2f}pt">{inner}</div>')
        else:
            out.append(f'<div class="ln left" style="top:{base:.2f}pt;left:{line["x0"]:.1f}pt;'
                       f'width:{layout.body_r - line["x0"]:.1f}pt">{inner}</div>')

    for pic in save_images(doc, page, page_no, img_dir, layout):
        x0, y0, x1, y1 = pic['bbox']
        if not pic['cover']:
            B = PICTURE_FRAME
            out.append(f'<div class="frame" style="left:{x0 - B:.2f}pt;top:{y0 - B:.2f}pt;'
                       f'width:{x1 - x0 + 2 * B:.2f}pt;height:{y1 - y0 + 2 * B:.2f}pt"></div>')
        out.append(f'<img class="pic" src="{asset_url(pic["path"], embed)}" '
                   f'style="left:{x0:.2f}pt;top:{y0:.2f}pt;width:{x1 - x0:.2f}pt;height:{y1 - y0:.2f}pt">')
    return '<section class="page">' + '\n'.join(out) + '</section>'


def build_pdf(doc, layout, out_pdf, font_dir, img_dir, chrome=None):
    """Write the Unicode PDF. Returns the output path."""
    chrome = find_chrome(chrome)
    return print_html(page_html(doc, layout, font_dir, img_dir), out_pdf, chrome)


def build_html(doc, layout, out_html, font_dir, img_dir):
    """Write the printable HTML (fonts and pictures embedded). Returns the output path."""
    with open(out_html, 'w', encoding='utf-8') as fh:
        fh.write(page_html(doc, layout, font_dir, img_dir, embed=True))
    return out_html


def page_html(doc, layout, font_dir, img_dir, embed=False):
    """The rebuilt pages as one HTML document, sized for printing."""
    for name in FONT_FILES:
        if not os.path.exists(os.path.join(font_dir, name)):
            raise FileNotFoundError(f'missing font {name} in {font_dir}')
    os.makedirs(img_dir, exist_ok=True)
    pages = [_page_html(doc, page, n, layout, img_dir, embed) for n, page in enumerate(doc)]

    css = font_face_css(font_dir, embed) + f"""
@page {{ size: {layout.page_w}pt {layout.page_h}pt; margin: 0; }}
html, body {{ margin: 0; padding: 0; }}
body {{ font-family: 'Bn', serif; color: #000; }}
* {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
.page {{ position: relative; width: {layout.page_w}pt; height: {layout.page_h}pt; page-break-after: always; overflow: hidden; background: {layout.page_bg}; }}
.page:last-child {{ page-break-after: auto; }}
.pic {{ position: absolute; }}
.frame {{ position: absolute; border: {PICTURE_FRAME}pt solid #000; box-sizing: border-box; }}
.ln {{ position: absolute; white-space: nowrap; line-height: 0; height: 0; }}
.ln.center {{ left: 0; width: {layout.page_w}pt; text-align: center; }}
.ln.left {{ text-align: left; }}
.body {{ position: absolute; left: {layout.body_l}pt; width: {layout.body_r - layout.body_l}pt;  }}
.p {{ margin: 0; text-align: justify; hyphens: none; }}
.p.ind {{ text-indent: 18pt; }}
.p.cont.full {{ text-align-last: justify; }}
.b {{ font-weight: 700; }}
.i {{ font-style: italic; }}
.latin {{ font-family: 'Times New Roman', 'Liberation Serif', serif; }}
"""
    return ('<!DOCTYPE html><html lang="bn"><head><meta charset="utf-8"><style>' + css +
            '</style></head><body>' + '\n'.join(pages) + FIT_SCRIPT + '</body></html>')


def font_face_css(font_dir, embed=False):
    """@font-face rules for the bundled fonts as family 'Bn' (regular and bold)."""
    return ''.join(
        f"@font-face {{ font-family: 'Bn'; src: url('{asset_url(os.path.join(font_dir, name), embed)}'); "
        f"font-weight: {weight}; }}\n" for name, weight in zip(FONT_FILES, (400, 700)))


def print_html(html, out_pdf, chrome):
    """Print an HTML document to PDF with headless Chrome. Returns out_pdf."""
    work = tempfile.mkdtemp(prefix='ansibangla_')
    html_path = os.path.join(work, 'document.html')
    with open(html_path, 'w', encoding='utf-8') as fh:
        fh.write(html)
    if os.path.exists(out_pdf):
        os.remove(out_pdf)
    subprocess.run([chrome, '--headless=new', '--no-sandbox', '--disable-gpu', '--allow-file-access-from-files',
                    '--no-pdf-header-footer', '--virtual-time-budget=5000',
                    f'--print-to-pdf={os.path.abspath(out_pdf)}', html_path],
                   capture_output=True, check=False)
    shutil.rmtree(work, ignore_errors=True)
    if not os.path.exists(out_pdf):
        raise RuntimeError('Chrome did not write the PDF; check the Chrome path.')
    return out_pdf
