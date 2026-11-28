import os
import re
import zipfile

import pytest

from ansibangla import convert_pdf, convert_text
from ansibangla.cli import main
from ansibangla.docxexport import _obfuscate

SAMPLE_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'sample')
SAMPLES = sorted(
    os.path.join(SAMPLE_DIR, f) for f in os.listdir(SAMPLE_DIR) if f.endswith('.pdf')
) if os.path.isdir(SAMPLE_DIR) else []
DOCX_SAMPLES = sorted(
    os.path.join(SAMPLE_DIR, f) for f in os.listdir(SAMPLE_DIR) if f.endswith('.docx')
) if os.path.isdir(SAMPLE_DIR) else []


def test_convert_text_conjunct_and_reph():
    assert convert_text('wbwØ©avq') == 'নির্দ্বিধায়'


def test_convert_text_empty():
    assert convert_text('') == ''


@pytest.mark.parametrize('raw, want', [
    ('cu¨vP', 'প্যাঁচ'),              # chandrabindu typed before ্য and া
    ('nu¨v', 'হ্যাঁ'),
    ('Pvu`', 'চাঁদ'),                       # chandrabindu before া (already worked)
    ('bv \\', 'না ॥'),                       # \ is the double danda
    ('AvKv•ÿv', 'আকাঙ্ক্ষা'),       # • before ক্ষ is ঙ্
    ('k•L', 'শঙ্খ'),                # • before খ is ঙ্
    ('•`‡N©¨i', 'দৈর্ঘ্যের'),  # • elsewhere is ৈ; ে after a reph-split ্য
    ('ˆL', 'খৈ'),                       # a real খৈ stays খৈ
    ('†ZRw¯…q', 'তেজস্ক্রিয়'),        # … after স্ is ক্র
    ('ms¯‥…wZ', 'সংস্কৃতি'),         # … after ক is ৃ
    ('Kwú', 'কপি'),                  # ú without a half form is প
    ('m¤úwK©', 'সম্পর্কি'),          # ú after ম্ is ্প
    ('Zxÿè', 'তীক্ষ্ণ'),               # è is the ণ-ফলা
    ('cÖkœ', 'প্রশ্ন'),                # œ is the ন-ফলা
])
def test_convert_text_glyph_cases(raw, want):
    assert convert_text(raw) == want


def test_convert_text_long_input_is_fast_and_line_independent():
    """Pasted text can be a whole chapter: conversion must not slow down quadratically
    (it once rebuilt the string for every vowel sign and reph), and each line converts
    the same on its own as inside the whole text."""
    import time
    lines = ['K‡e mvayi PiYa~wj', 'ivbvNv‡U A‡a©K c¨v‡mÄvi †b‡g †M‡j', 'wbwØ©avq m¤úwK©']
    text = '\n'.join(lines * 4000)                     # about 200 000 characters
    start = time.perf_counter()
    out = convert_text(text)
    assert time.perf_counter() - start < 5
    assert out == '\n'.join(convert_text(l) for l in text.split('\n'))


def test_danda_after_english_word():
    from ansibangla._common import span_text
    assert span_text(dict(font='TimesNewRomanPSMT', text='(DNA)|')) == '(DNA)।'


def test_unknown_format_rejected(tmp_path):
    with pytest.raises(ValueError):
        convert_pdf('missing.pdf', tmp_path, formats=['txt'])


def test_cli_reports_missing_file(tmp_path, capsys):
    assert main([str(tmp_path / 'missing.pdf'), '-o', str(tmp_path)]) == 1
    assert 'error:' in capsys.readouterr().err


def test_font_obfuscation_round_trip():
    data = bytes(range(64))
    key = '{01234567-89AB-CDEF-0123-456789ABCDEF}'
    hidden = _obfuscate(data, key)
    assert hidden[32:] == data[32:] and hidden[:32] != data[:32]
    assert _obfuscate(hidden, key) == data


def _source_lines(src, table_words=None):
    """Plain text of every source line except page numbers (digits alone) and
    letter-spaced headings. Deliberately independent of the converter's footer zone.

    A line inside a table runs across its columns ("১৩৫০ কোটি" + "পদার্থ ও শক্তির"), which
    no output keeps whole once the cells are separated; its words go to table_words (a
    list) instead, for a check word by word."""
    import pymupdf
    from ansibangla._common import Layout, read_lines
    from ansibangla.blocks import find_tables, is_letter_spaced, plain_line
    doc = pymupdf.open(src)
    layout = Layout(doc)
    for page in doc:
        tables = [t['bbox'] for t in find_tables(page, layout)]
        for line in read_lines(page):
            text = ' '.join(plain_line(line).split())
            if not text or is_letter_spaced(line) or re.fullmatch(r'[০-৯0-9]+', text):
                continue
            if any(b.x0 - 1 <= line['x0'] <= b.x1 and b.y0 - 1 <= line['base'] <= b.y1 + 1 for b in tables):
                if table_words is not None:
                    table_words += [(page.number, w) for w in text.split()]
                continue
            yield page.number, text


def _flat(text):
    return ' '.join(text.split())


@pytest.mark.skipif(not SAMPLES, reason='no sample PDFs in sample/')
@pytest.mark.parametrize('src', SAMPLES)
def test_no_text_lost(src, tmp_path):
    """Every source line reaches the Markdown, DOCX and EPUB (a line at the foot of a page
    was once taken for a page number and dropped)."""
    written = convert_pdf(src, tmp_path, formats=('docx', 'epub', 'md'))
    md = open(written['md'], encoding='utf-8').read()
    md = re.sub(r'(?<!\\)\*+|&emsp;|<[^>]+>|^#+ ', '', md, flags=re.M)   # emphasis markup, not \*
    md = _flat(re.sub(r'\\([\\`*_])', r'\1', md))                          # literal characters
    with zipfile.ZipFile(written['docx']) as z:
        xml = z.read('word/document.xml').decode('utf-8')
    paragraphs = re.findall(r'<w:p[ >].*?</w:p>', xml)
    import html as htmllib
    docx = _flat(htmllib.unescape(' '.join(''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', p))
                                           for p in paragraphs)))
    with zipfile.ZipFile(written['epub']) as z:
        html = ' '.join(z.read(n).decode('utf-8') for n in sorted(z.namelist())
                        if n.startswith('OEBPS/text/'))
    import html as htmllib
    epub = _flat(htmllib.unescape(re.sub(r'<[^>]+>', '', html)))
    table_words = []
    lines = list(_source_lines(src, table_words))
    for name, out in (('md', md), ('docx', docx), ('epub', epub)):
        missing = [(p, t) for p, t in lines if t not in out]
        assert not missing, f'{name}: lines missing, e.g. {missing[:3]}'
        missing = [(p, w) for p, w in table_words if w not in out]
        assert not missing, f'{name}: table words missing, e.g. {missing[:3]}'


@pytest.mark.skipif(not SAMPLES, reason='no sample PDFs in sample/')
@pytest.mark.parametrize('src', SAMPLES)
def test_sample_markdown_only(src, tmp_path):
    written = convert_pdf(src, tmp_path, formats=('md',))
    assert set(written) == {'md'}
    text = open(written['md'], encoding='utf-8').read()
    assert any('ঀ' <= ch <= '৿' for ch in text)   # Bengali block


@pytest.mark.skipif(not SAMPLES, reason='no sample PDFs in sample/')
@pytest.mark.parametrize('src', SAMPLES)
def test_sample_docx(src, tmp_path):
    import pymupdf
    written = convert_pdf(src, tmp_path, formats=('docx',))
    assert set(written) == {'docx'}            # only what was asked for
    with zipfile.ZipFile(written['docx']) as z:
        names = set(z.namelist())
        assert {'word/document.xml', 'word/fonts/font1.odttf', 'word/fonts/font2.odttf'} <= names
        xml = z.read('word/document.xml').decode('utf-8')
    text = ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', xml))
    assert any('ঀ' <= ch <= '৿' for ch in text)
    # every source page after the first starts with a page break
    assert xml.count('<w:pageBreakBefore/>') == len(pymupdf.open(src)) - 1


@pytest.mark.skipif(not SAMPLES, reason='no sample PDFs in sample/')
@pytest.mark.parametrize('src', SAMPLES)
def test_sample_epub(src, tmp_path):
    import posixpath
    import xml.dom.minidom
    import pymupdf
    written = convert_pdf(src, tmp_path, formats=('epub',))
    assert set(written) == {'epub'}
    with zipfile.ZipFile(written['epub']) as z:
        first = z.infolist()[0]
        assert first.filename == 'mimetype' and first.compress_type == zipfile.ZIP_STORED
        assert z.read('mimetype') == b'application/epub+zip'
        names = set(z.namelist())
        for name in names:
            if name.endswith(('.xhtml', '.opf', '.ncx', '.xml')):
                xml.dom.minidom.parseString(z.read(name))          # well-formed
        # every file the stylesheet and chapters point to is in the book
        css = z.read('OEBPS/style.css').decode()
        for ref in re.findall(r'url\(([^)]+)\)', css):
            assert posixpath.normpath(posixpath.join('OEBPS', ref)) in names
        chapters = sorted(n for n in names if n.startswith('OEBPS/text/'))
        body = ''.join(z.read(n).decode() for n in chapters)
        for ref in re.findall(r'src="([^"]+)"', body):
            assert posixpath.normpath(posixpath.join('OEBPS/text', ref)) in names
    assert any('ঀ' <= ch <= '৿' for ch in body)
    # one page marker per source page that shows a page number (a line of digits alone)
    from ansibangla._common import read_lines
    from ansibangla.blocks import plain_line
    numbered = sum(1 for page in pymupdf.open(src)
                   if any(re.fullmatch(r'[০-৯0-9]+', plain_line(l)) for l in read_lines(page)))
    assert body.count('epub:type="pagebreak"') == numbered


def _md_words(path):
    t = open(path, encoding='utf-8').read()
    t = re.sub(r'!\[\]\([^)]*\)', ' ', t)                       # picture links
    t = re.sub(r'</?(sup|sub)>', '', t)                         # inline: part of the word
    t = re.sub(r'<[^>]+>|&emsp;|^#+ ', ' ', t, flags=re.M)
    t = re.sub(r'(?<!\\)\*+', '', t)
    return re.sub(r'\\([\\`*_])', r'\1', t).split()


@pytest.mark.skipif(not DOCX_SAMPLES, reason='no sample .docx files in sample/')
@pytest.mark.parametrize('src', DOCX_SAMPLES)
def test_docx_input(src, tmp_path):
    from ansibangla import convert_file
    assert set(convert_file(src, tmp_path / 'default')) == {'docx'}   # .docx input gives a .docx
    written = convert_file(src, tmp_path, formats=('docx', 'md'))
    assert set(written) == {'docx', 'md'}
    with zipfile.ZipFile(written['docx']) as z:
        names = set(z.namelist())
        for name in names:
            if name.endswith(('.xml', '.rels')):
                import xml.dom.minidom
                xml.dom.minidom.parseString(z.read(name))  # well-formed
        doc = z.read('word/document.xml').decode('utf-8')
        assert any(n.endswith('.odttf') for n in names)  # fonts embedded
    text = ''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>', doc))
    assert any('ঀ' <= ch <= '৿' for ch in text)
    assert 'SutonnyMJ' not in re.sub(r'<w:pPr>.*?</w:pPr>', '', doc)   # no run left in SutonnyMJ
    # a paragraph holding a picture never gets an exact line height (it would crop the picture)
    for para in re.findall(r'<w:p[ >].*?</w:p>', doc, re.S):
        if '<w:pict' in para or '<w:drawing' in para:
            assert 'w:lineRule="exact"' not in para
    # the same book as a PDF (name without the _unicode suffix) gives the same words
    pdf = re.sub(r'(_unicode)?\.docx$', '.pdf', src)
    if os.path.exists(pdf):
        import difflib
        from_pdf = convert_pdf(pdf, tmp_path / 'pdf', formats=('md',))
        a, b = _md_words(from_pdf['md']), _md_words(written['md'])
        if len(a) < 20000:                          # a short text: word for word
            assert a == b
        else:                                       # a book: footnotes sit elsewhere, PDF tables interleave
            assert difflib.SequenceMatcher(None, a, b).ratio() > 0.99


def test_docx_input_rejects_unknown_format(tmp_path):
    from ansibangla import convert_docx
    with pytest.raises(ValueError):
        convert_docx('missing.docx', tmp_path, formats=('txt',))


def test_page_field_runs():
    """Runs of PAGE / NUMPAGES fields are found, simple or complex, nested or not; runs
    of other fields and plain text are not."""
    import xml.etree.ElementTree as ET
    from ansibangla.docxinput import W, _page_field_runs

    def r(inner, name):
        return f'<w:r><w:rPr><w:rStyle w:val="{name}"/></w:rPr>{inner}</w:r>'

    begin, sep, end = ('<w:fldChar w:fldCharType="begin"/>', '<w:fldChar w:fldCharType="separate"/>',
                       '<w:fldChar w:fldCharType="end"/>')
    body = (r('<w:t>page </w:t>', 'text')
            + r(begin, 'p1') + r('<w:instrText> PAGE \\* MERGEFORMAT </w:instrText>', 'p2')
            + r(sep, 'p3') + r('<w:t>7</w:t>', 'p4') + r(end, 'p5')
            + r(begin, 'd1') + r('<w:instrText> DATE </w:instrText>', 'd2') + r(sep, 'd3')
            + r('<w:t>today</w:t>', 'd4') + r(end, 'd5')
            + f'<w:fldSimple w:instr=" NUMPAGES ">{r("<w:t>9</w:t>", "s1")}</w:fldSimple>'
            # a PAGE field nested inside an IF field: only the inner field's runs
            + r(begin, 'if1') + r('<w:instrText> IF </w:instrText>', 'if2')
            + r(begin, 'n1') + r('<w:instrText>PAGE</w:instrText>', 'n2') + r(end, 'n3')
            + r('<w:instrText> > 1 "x" </w:instrText>', 'if3') + r(end, 'if4'))
    root = ET.fromstring(f'<w:p xmlns:w="{W}">{body}</w:p>')
    found = [run.find(f'{{{W}}}rPr/{{{W}}}rStyle').get(f'{{{W}}}val') for run in _page_field_runs(root)]
    assert sorted(found) == sorted(['p1', 'p2', 'p3', 'p4', 'p5', 's1', 'n1', 'n2', 'n3'])


@pytest.mark.skipif(not DOCX_SAMPLES, reason='no sample .docx files in sample/')
@pytest.mark.parametrize('src', DOCX_SAMPLES)
def test_docx_page_numbers_stay_bangla(src, tmp_path):
    """Word fills page-number fields with 0-9; in SutonnyMJ those showed as ০-৯. Fields
    that were in SutonnyMJ get the digits font (0-9 drawn as ০-৯), embedded in the file,
    and nothing else does."""
    from ansibangla import convert_docx
    from ansibangla.docxexport import DIGITS_FONT
    out = convert_docx(src, tmp_path, formats=('docx',))['docx']
    with zipfile.ZipFile(out) as z:
        parts = {n: z.read(n).decode('utf-8') for n in z.namelist() if n.endswith('.xml')}
    with zipfile.ZipFile(src) as z:
        mj_page_field = any('SutonnyMJ' in x and re.search(r'instrText[^>]*>\s*PAGE\b', x)
                            for n in z.namelist() if re.match(r'word/(header|footer)\d*\.xml', n)
                            for x in [z.read(n).decode('utf-8')])
    assert f'w:name="{DIGITS_FONT}"' in parts['word/fontTable.xml']          # embedded
    assert DIGITS_FONT not in parts['word/document.xml']                      # body text untouched
    in_footers = any(DIGITS_FONT in x for n, x in parts.items() if re.match(r'word/(header|footer)\d*\.xml', n))
    assert in_footers == mj_page_field


@pytest.mark.skipif(not DOCX_SAMPLES, reason='no sample .docx files in sample/')
@pytest.mark.parametrize('src', DOCX_SAMPLES)
def test_docx_tables_padded_for_exact_lines(src, tmp_path):
    """Cell text set with exact line spacing gets top and bottom cell padding, or Noto's
    marks (ি, reph, ু, ৃ) reach past the line onto the cell borders."""
    import xml.etree.ElementTree as ET
    from ansibangla import convert_docx
    from ansibangla.docxinput import TBLPR_ORDER, W
    out = convert_docx(src, tmp_path, formats=('docx',))['docx']
    with zipfile.ZipFile(out) as z:
        root = ET.fromstring(z.read('word/document.xml'))
    w = lambda tag: f'{{{W}}}{tag}'
    for tbl in root.iter(w('tbl')):
        own = [p for p in tbl.iter(w('p'))]
        if not any(s.get(w('lineRule')) == 'exact' for p in own for s in p.iter(w('spacing'))):
            continue
        tblpr = tbl.find(w('tblPr'))
        mar = tblpr.find(w('tblCellMar'))
        assert mar is not None
        for side in ('top', 'bottom'):
            assert int(mar.find(w(side)).get(w('w'))) > 0
        tags = [c.tag.split('}')[1] for c in tblpr]
        ranks = [TBLPR_ORDER.index(t) for t in tags if t in TBLPR_ORDER]
        assert ranks == sorted(ranks)                     # schema order kept
        sides = [c.tag.split('}')[1] for c in mar]
        assert sides.index('top') < sides.index('bottom')


@pytest.mark.parametrize('borders, grid', [
    ('<w:tblBorders><w:top w:val="single"/></w:tblBorders>', True),
    ('<w:tblStyle w:val="TableGrid"/>', True),
    ('<w:tblBorders><w:top w:val="nil"/><w:insideH w:val="none"/></w:tblBorders>', False),
    ('', False),
])
def test_table_merged_cells_and_borders(borders, grid, tmp_path):
    """Word tables reach the e-book and PDF with merged cells as colspan / rowspan, and
    borders only when the table has them."""
    from ansibangla import docxrender
    W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

    def tc(text, pr=''):
        return f'<w:tc><w:tcPr>{pr}</w:tcPr><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:tc>'
    span2, restart, cont = '<w:gridSpan w:val="2"/>', '<w:vMerge w:val="restart"/>', '<w:vMerge/>'
    doc = (f'<w:document xmlns:w="{W}"><w:body><w:tbl><w:tblPr>{borders}</w:tblPr>'
           f'<w:tr>{tc("A", span2)}{tc("B", restart)}</w:tr>'
           f'<w:tr>{tc("c")}{tc("d")}{tc("", cont)}</w:tr>'
           f'<w:tr>{tc("e")}{tc("f")}{tc("g")}</w:tr></w:tbl><w:p/></w:body></w:document>')
    model = docxrender.build_model({'word/document.xml': doc.encode()}, str(tmp_path))
    html = docxrender._table_html(model['blocks'][0], lambda blocks: ''.join(
        r.get('text', '') for p in docxrender._paragraphs(blocks) for r in p['runs']))
    opening = '<table class="grid">' if grid else '<table>'
    assert html == (opening +
                    '<tr><td colspan="2">A</td><td rowspan="2">B</td></tr>'
                    '<tr><td>c</td><td>d</td></tr>'
                    '<tr><td>e</td><td>f</td><td>g</td></tr></table>')


def test_superscript_and_subscript_runs(tmp_path):
    """Superscript and subscript formatting (note numbers typed as superscript text, set on
    the run or through a character style) reach the e-book, PDF page and Markdown."""
    from ansibangla import docxrender
    W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    styles = (f'<w:styles xmlns:w="{W}"><w:style w:type="character" w:styleId="NoteMark">'
              '<w:rPr><w:vertAlign w:val="superscript"/></w:rPr></w:style></w:styles>')
    doc = (f'<w:document xmlns:w="{W}"><w:body><w:p>'
           '<w:r><w:t>কথা।</w:t></w:r>'
           '<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:t>২</w:t></w:r>'
           '<w:r><w:t> H</w:t></w:r><w:r><w:rPr><w:vertAlign w:val="subscript"/></w:rPr><w:t>2</w:t></w:r>'
           '<w:r><w:t>O আর</w:t></w:r>'
           '<w:r><w:rPr><w:rStyle w:val="NoteMark"/></w:rPr><w:t>৩</w:t></w:r>'
           '</w:p></w:body></w:document>')
    model = docxrender.build_model({'word/document.xml': doc.encode(), 'word/styles.xml': styles.encode()},
                                   str(tmp_path))
    runs = model['blocks'][0]['runs']
    assert [r.get('vert') for r in runs] == [None, 'superscript', None, 'subscript', None, 'superscript']
    html = re.sub(r' style="[^"]*"', '', docxrender._runs_html(runs, lambda hp: f'{hp}'))
    assert html == ('<span>কথা।</span><sup><span>২</span></sup><span> H</span><sub><span>2</span></sub>'
                    '<span>O আর</span><sup><span>৩</span></sup>')
    assert docxrender._md_runs(runs, False) == 'কথা।<sup>২</sup> H<sub>2</sub>O আর<sup>৩</sup>'


def test_epub_footnotes_are_popup_notes(tmp_path):
    """A Word footnote becomes an EPUB 3 pop-up note: the mark links to it, the note sits
    at the end of the chapter (linking back), and the running text is not interrupted."""
    from ansibangla import docxrender
    from ansibangla.api import FONT_DIR
    W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
    notes = (f'<w:footnotes xmlns:w="{W}"><w:footnote w:id="1"><w:p><w:r><w:t>পাদটীকার লেখা</w:t></w:r>'
             '</w:p></w:footnote></w:footnotes>')
    doc = (f'<w:document xmlns:w="{W}"><w:body>'
           '<w:p><w:r><w:t>প্রথম অনুচ্ছেদ</w:t></w:r><w:r><w:footnoteReference w:id="1"/></w:r></w:p>'
           '<w:p><w:r><w:t>দ্বিতীয় অনুচ্ছেদ</w:t></w:r></w:p></w:body></w:document>')
    model = docxrender.build_model({'word/document.xml': doc.encode(), 'word/footnotes.xml': notes.encode()},
                                   str(tmp_path))
    out = docxrender.export_epub(model, str(tmp_path / 'book.epub'), FONT_DIR)
    with zipfile.ZipFile(out) as z:
        x = ''.join(z.read(n).decode('utf-8') for n in z.namelist() if n.startswith('OEBPS/text/'))
    assert re.search(r'<a epub:type="noteref"[^>]*id="fnref1" href="#fn1">', x)
    assert re.search(r'<aside epub:type="footnote"[^>]*id="fn1"[^>]*>.*href="#fnref1".*পাদটীকার লেখা', x)
    # the second paragraph follows the first directly; the note comes after both
    assert x.index('প্রথম অনুচ্ছেদ') < x.index('দ্বিতীয় অনুচ্ছেদ') < x.index('পাদটীকার লেখা')


def test_epub_pictures_are_made_small(tmp_path):
    """Pictures go into the e-book at most EPUB_MAX_W x EPUB_MAX_H: photographs as JPEG,
    diagrams (few colours) and transparent pictures as PNG, never bigger than before."""
    import random
    import pymupdf
    from ansibangla.epubexport import EPUB_MAX_H, EPUB_MAX_W, _web_image
    rnd = random.Random(1)
    # a photograph-like picture at print size, saved losslessly: fine detail everywhere,
    # which PNG cannot compress
    w, h = 3000, 2000
    photo = pymupdf.Pixmap(pymupdf.csRGB, w, h, rnd.randbytes(w * h * 3), False)
    photo.save(str(tmp_path / 'photo.png'))
    diagram = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 600, 400), False)
    diagram.set_rect(diagram.irect, (255, 255, 255))
    diagram.set_rect(pymupdf.IRect(100, 100, 300, 200), (0, 0, 0))
    diagram.save(str(tmp_path / 'diagram.png'))
    glass = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 300, 200), True)
    glass.set_rect(glass.irect, (200, 30, 30, 120))
    glass.save(str(tmp_path / 'glass.png'))

    data, ext = _web_image(str(tmp_path / 'photo.png'))
    pix = pymupdf.Pixmap(data)
    assert ext == '.jpg' and pix.width <= EPUB_MAX_W and pix.height <= EPUB_MAX_H
    assert len(data) < os.path.getsize(tmp_path / 'photo.png') / 5
    data, ext = _web_image(str(tmp_path / 'diagram.png'))
    assert ext == '.png' and len(data) <= os.path.getsize(tmp_path / 'diagram.png')
    data, ext = _web_image(str(tmp_path / 'glass.png'))
    assert ext == '.png' and pymupdf.Pixmap(data).alpha


@pytest.mark.skipif(not DOCX_SAMPLES, reason='no sample .docx files in sample/')
@pytest.mark.parametrize('src', DOCX_SAMPLES)
def test_epub_picture_links_survive_renaming(src, tmp_path):
    """A PNG photograph becomes a .jpg in the e-book; every link and the manifest follow."""
    from ansibangla import convert_docx
    out = convert_docx(src, tmp_path, formats=('epub',))['epub']
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        text = ''.join(z.read(n).decode('utf-8') for n in names if n.endswith('.xhtml'))
        opf = z.read('OEBPS/content.opf').decode('utf-8')
    files = {n[len('OEBPS/images/'):] for n in names if n.startswith('OEBPS/images/')}
    assert set(re.findall(r'\.\./images/([^"]+)"', text)) <= files
    assert set(re.findall(r'href="images/([^"]+)"', opf)) == files


def test_epub_keeps_space_of_empty_lines(tmp_path):
    """Empty paragraphs (how books typed in Word space headings and scene breaks) become
    space above what follows: a line each, at most two, none at the top of a page."""
    from ansibangla import docxrender
    from ansibangla.api import FONT_DIR
    W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

    def p(text, bold=False):
        rpr = f'<w:rPr>{"<w:b/>" if bold else ""}<w:sz w:val="22"/></w:rPr>'
        return f'<w:p><w:r>{rpr}<w:t>{text}</w:t></w:r></w:p>'
    body = ''.join([p(''), p('প্রথম লেখা'), p(''), p('শিরোনাম', bold=True), p('লেখা'),
                    p(''), p(''), p(''), p('দৃশ্য বদল'), p('শেষ')] + [p('লেখা ' * 10)] * 10)
    doc = f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    model = docxrender.build_model({'word/document.xml': doc.encode()}, str(tmp_path))
    out = docxrender.export_epub(model, str(tmp_path / 'book.epub'), FONT_DIR)
    with zipfile.ZipFile(out) as z:
        x = ''.join(z.read(n).decode('utf-8') for n in z.namelist() if n.startswith('OEBPS/text/'))

    def top(text):
        m = re.search(r'<(?:p|h2)\b([^>]*)>(?:<[^>]+>)*' + text, x)
        found = re.search(r'margin(?:-top)?:([\d.]+)em', m.group(1))
        return float(found.group(1)) if found else 0.0
    line = top('শিরোনাম')
    assert top('প্রথম লেখা') == 0                      # page top: no space for the empty line
    assert line >= 1.3                                  # one empty line: one line of space
    assert top('দৃশ্য বদল') == pytest.approx(2 * line)   # three empty lines: two at most
    assert top('শেষ') == 0


def test_epub_pages_follow_word_page_breaks(tmp_path):
    """A Word book laid out with page breaks gets a new page at each break, titled by the
    large lines it opens with (bold or not); a page without such lines gets no entry of its
    own, and bold headings inside become entries under their chapter."""
    from ansibangla import docxrender
    from ansibangla.api import FONT_DIR
    W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

    def p(text, size=22, bold=False, brk=False):
        rpr = f'<w:rPr>{"<w:b/>" if bold else ""}<w:sz w:val="{size}"/></w:rPr>'
        lead = '<w:r><w:br w:type="page"/></w:r>' if brk else ''
        return f'<w:p>{lead}<w:r>{rpr}<w:t>{text}</w:t></w:r></w:p>'
    body = ''.join([
        p('লেখক', 24), p('বইয়ের নাম', 40), p('সাধারণ লেখা ' * 3),
        p('অধ্যায় ১', 25, brk=True), p(''), p('প্রথম কথা', 28), p('লেখা ' * 20), p('উপশিরোনাম', 22, bold=True),
        p('লেখা ' * 20),
        p('ছবির পাতার লেখা', brk=True), p('লেখা ' * 20),
        p('অধ্যায় ২', 25, brk=True), p('দ্বিতীয় কথা', 28), p('লেখা ' * 20),
    ] + [p('লেখা ' * 10)] * 10)
    doc = f'<w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    model = docxrender.build_model({'word/document.xml': doc.encode()}, str(tmp_path))
    out = docxrender.export_epub(model, str(tmp_path / 'book.epub'), FONT_DIR)
    with zipfile.ZipFile(out) as z:
        names = [n for n in z.namelist() if n.startswith('OEBPS/text/')]
        nav = z.read('OEBPS/nav.xhtml').decode('utf-8')
        opf = z.read('OEBPS/content.opf').decode('utf-8')
    assert len(names) == 4                                  # opening + three pages after breaks
    entries = re.findall(r'<a href="text/[^"]+">([^<]+)</a>', nav)
    assert entries == ['বইয়ের নাম', 'অধ্যায় ১: প্রথম কথা', 'উপশিরোনাম', 'অধ্যায় ২: দ্বিতীয় কথা']
    assert '<dc:title>বইয়ের নাম</dc:title>' in opf             # the title page's largest line


@pytest.mark.skipif(not SAMPLES, reason='no sample PDFs in sample/')
@pytest.mark.parametrize('src', SAMPLES)
def test_pdf_to_docx_page_numbers_stay_bangla(src, tmp_path):
    """A source that prints its page numbers in SutonnyMJ gets a page-number footer in the
    digits font, so Word's numbers show as ০, ১, ২ like the source's."""
    from ansibangla.docxexport import DIGITS_FONT
    out = convert_pdf(src, tmp_path, formats=('docx',))['docx']
    with zipfile.ZipFile(out) as z:
        if 'footerReference' not in z.read('word/document.xml').decode('utf-8'):
            pytest.skip('this source prints no page numbers')
        assert DIGITS_FONT in z.read('word/footer1.xml').decode('utf-8')
        assert f'w:name="{DIGITS_FONT}"' in z.read('word/fontTable.xml').decode('utf-8')


@pytest.mark.skipif(not DOCX_SAMPLES, reason='no sample .docx files in sample/')
@pytest.mark.parametrize('src', DOCX_SAMPLES)
def test_unicode_docx_makes_the_same_ebook(src, tmp_path):
    """A converted .docx (say, edited afterwards) can be made into an e-book as it is, and
    gives the same e-book and Markdown as converting the SutonnyMJ original directly. Asking
    it for a .docx is a clear error that writes nothing."""
    from ansibangla import convert_docx, convert_file
    direct = convert_docx(src, tmp_path / 'direct', formats=('epub', 'md'))
    uni = convert_docx(src, tmp_path / 'uni', formats=('docx',))['docx']
    again = convert_docx(uni, tmp_path / 'again', formats=('epub', 'md'))
    assert os.path.basename(again['epub']) == os.path.basename(direct['epub'])   # no _unicode_unicode
    assert open(again['md'], encoding='utf-8').read() == open(direct['md'], encoding='utf-8').read()

    def chapters(path):
        with zipfile.ZipFile(path) as z:
            return [z.read(n) for n in sorted(z.namelist()) if n.startswith('OEBPS/text/')]
    assert chapters(again['epub']) == chapters(direct['epub'])

    before = set(os.listdir(tmp_path / 'again'))
    with pytest.raises(ValueError, match='already in Unicode'):
        convert_file(uni, tmp_path / 'again')                   # default output for .docx is docx
    assert set(os.listdir(tmp_path / 'again')) == before


@pytest.mark.skipif(not DOCX_SAMPLES, reason='no sample .docx files in sample/')
@pytest.mark.parametrize('src', DOCX_SAMPLES)
def test_docx_input_to_pdf_and_epub(src, tmp_path):
    import html as htmllib
    import xml.dom.minidom
    import pymupdf
    from ansibangla import convert_file
    written = convert_file(src, tmp_path, formats=('pdf', 'epub', 'md'))
    assert set(written) == {'md', 'pdf', 'epub'}                  # no docx asked, none written
    assert len(pymupdf.open(written['pdf'])) >= 1
    with zipfile.ZipFile(written['epub']) as z:
        assert z.infolist()[0].filename == 'mimetype'
        for name in z.namelist():
            if name.endswith(('.xhtml', '.opf', '.ncx', '.xml')):
                xml.dom.minidom.parseString(z.read(name))
        body = ' '.join(z.read(n).decode('utf-8') for n in sorted(z.namelist())
                        if n.startswith('OEBPS/text/'))
    # pictures in web formats reach the PDF and the e-book (DrawingML or old VML pictures)
    with zipfile.ZipFile(src) as z:
        web = [n for n in z.namelist() if n.startswith('word/media/')
               and n.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))]
    if web:
        assert sum(len(p.get_images()) for p in pymupdf.open(written['pdf'])) > 0
        assert any('/images/' in n for n in zipfile.ZipFile(written['epub']).namelist())
    # the e-book has the Markdown's words: its text in order, each footnote in order (the
    # e-book gathers footnotes at the chapter's end, the Markdown keeps them in place)
    body = re.sub(r'<head>.*?</head>', ' ', body, flags=re.S)    # chapter titles repeat headings
    body = re.sub(r'</?(span|sup|sub|a)\b[^>]*>', '', body)  # inline tags join words

    def words(fragment):
        return htmllib.unescape(re.sub(r'<[^>]+>', ' ', fragment)).split()
    notes = re.findall(r'<aside\b.*?</aside>', body, re.S)
    main = words(re.sub(r'<aside\b.*?</aside>', ' ', body, flags=re.S))
    md_words = _md_words(written['md'])

    def in_order(part, whole):
        it = iter(whole)
        return all(w in it for w in part)
    assert in_order(main, md_words)
    assert all(in_order(words(n), md_words) for n in notes)
    assert len(main) + sum(len(words(n)) for n in notes) == len(md_words)


@pytest.mark.skipif(not SAMPLES + DOCX_SAMPLES, reason='no samples in sample/')
@pytest.mark.parametrize('src', SAMPLES + DOCX_SAMPLES)
def test_printable_html_is_self_contained(src, tmp_path):
    """The html output opens anywhere: fonts and pictures are embedded, nothing points at
    this machine's files, and it says when it is ready to print."""
    from ansibangla import convert_file
    written = convert_file(src, tmp_path, formats=('html',))
    assert set(written) == {'html'}
    page = open(written['html'], encoding='utf-8').read()
    assert 'file://' not in page
    assert page.count("src: url('data:font/ttf;base64,") == 2          # regular and bold
    assert all(u.startswith('data:image/') for u in re.findall(r'<img [^>]*src="([^"]*)"', page))
    assert 'dataset.ready' in page
    assert any('ঀ' <= ch <= '৿' for ch in page)


def test_epub_letter_spaced_heading_is_written_as_words():
    """A heading set letter by letter in the PDF ("প্র থ ম  প র্ব") is written as words in
    the e-book, the chapter's own heading too, and with no CSS letter spacing, which breaks
    Bangla clusters apart (a detached reph) in Safari-based readers such as Apple Books."""
    import types
    from ansibangla.epubexport import CSS, _opening_html
    line = dict(spans=[dict(font='SutonnyMJ', text='cÖ _ g  c e©', size=20.0)],
                mj_size=20.0, size=20.0, base=100.0, x0=0, x1=50)
    layout = types.SimpleNamespace(scale=0.9, body_size=11.0)
    html = _opening_html([dict(kind='h', lines=[line], spaced=True)], layout)
    assert re.sub(r'<[^>]+>', '', html) == 'প্রথম পর্ব'
    assert 'letter-spacing' not in CSS


def test_epub_title_page_fits_and_has_the_title_as_heading():
    """A title page keeps its lines together (the printed page's large gaps are cut to
    TITLE_PAGE_GAP, so it fits one screen) and its largest line is the <h1>."""
    import types
    from ansibangla.epubexport import TITLE_PAGE_GAP, _opening_html

    def blk(text, size, base):
        return dict(kind='h', spaced=False, lines=[dict(
            spans=[dict(font='SutonnyMJ', text=text, size=size)], mj_size=size, size=size,
            base=base, x0=0, x1=50)])
    # author, title, subtitle, then the translator far down the printed page
    group = [blk('BDfvj', 18, 100), blk('†mwcqy',  34, 160), blk('gvby‡li', 18, 200), blk('fvlvšÍi', 16, 420)]
    layout = types.SimpleNamespace(scale=0.9, body_size=11.0)
    html = _opening_html(group, layout, title_page=True)
    gaps = [float(g) for g in re.findall(r'margin-top:([\d.]+)em', html)]
    assert gaps and max(gaps) <= TITLE_PAGE_GAP
    assert re.search(r'<h1[^>]*>.*?</h1>', html).group(0).count('font-size:3.00em') == 1   # the title


def test_pdf_tables_found_ruled_and_rules_only():
    """Tables in a PDF: a ruled one (borders all round) with its cells, and one drawn with
    horizontal rules only (a timeline), its columns found from where its text starts. A
    page without tables gets none."""
    import types
    import pymupdf
    from ansibangla.blocks import _table_block, find_tables, plain_line
    layout = types.SimpleNamespace(body_l=50, body_r=370)
    doc = pymupdf.open()
    page = doc.new_page(width=420, height=595)
    xs, ys = [50, 200, 370], [60, 80, 100, 120]
    for y in ys:
        page.draw_line((xs[0], y), (xs[-1], y))
    for x in xs:
        page.draw_line((x, ys[0]), (x, ys[-1]))
    for r in range(3):
        for c in range(2):
            page.insert_text((xs[c] + 4, ys[r] + 14), f'R{r}C{c}', fontsize=10)
    rows = [200 + 22 * k for k in range(5)]
    for y in rows:                                    # rules drawn as thin filled rectangles
        page.draw_rect(pymupdf.Rect(50, y, 370, y + 0.6), fill=(0, 0, 0), color=None)
    for r in range(4):
        page.insert_text((52, rows[r] + 15), f'T{r}', fontsize=10)
        page.insert_text((160, rows[r] + 15), f'text {r} here', fontsize=10)
    tables = sorted(find_tables(page, layout), key=lambda t: t['bbox'].y0)
    assert [t['ruled'] for t in tables] == [True, False]

    def texts(t):
        block = _table_block(page, 0, t)
        return [[' '.join(plain_line(l) for l in cell['lines']) for cell in row] for row in block['rows']]
    assert texts(tables[0]) == [['R0C0', 'R0C1'], ['R1C0', 'R1C1'], ['R2C0', 'R2C1']]
    assert texts(tables[1]) == [[f'T{r}', f'text {r} here'] for r in range(4)]
    plain = doc.new_page(width=420, height=595)
    plain.insert_text((50, 60), 'No table here.', fontsize=10)
    plain.draw_line((50, 70), (370, 70))                 # a single rule is not a table
    assert find_tables(plain, layout) == []


def test_formats_are_only_what_was_asked(tmp_path):
    from ansibangla.api import _check_formats
    assert _check_formats(['PDF', ' md', 'pdf']) == ('pdf', 'md')      # case, spaces, repeats
    with pytest.raises(ValueError):
        _check_formats([])                                              # nothing to write


def test_cli_formats_in_any_form(tmp_path, monkeypatch):
    import ansibangla.cli as cli
    seen = []
    monkeypatch.setattr(cli, 'convert_file', lambda path, out, formats=None, **kw: seen.append((path, formats)) or {})
    for argv in (['a.pdf', '-f', 'md,epub'], ['a.pdf', '-f', 'md', 'epub'], ['-f', 'md', 'epub', 'a.pdf'],
                 ['a.pdf', '-f', 'md', '-f', 'epub'], ['a.pdf', '--formats', 'md', 'epub']):
        seen.clear()
        assert cli.main(argv) == 0
        assert seen == [('a.pdf', ['md', 'epub'])], argv
    seen.clear()
    assert cli.main(['a.pdf']) == 0 and seen == [('a.pdf', None)]     # default: the input's format


def test_keep_latin_words(tmp_path):
    from ansibangla.api import _keep_latin
    assert convert_text('DNA') != 'DNA'                       # read as Bijoy key codes
    with _keep_latin(['DNA']):
        assert convert_text('(DNA)') == '(DNA)'               # kept as typed
    assert convert_text('DNA') != 'DNA'                       # setting does not leak
