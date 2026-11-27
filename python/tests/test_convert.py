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


def _source_lines(src):
    """Plain text of every source line except page numbers (digits alone) and
    letter-spaced headings. Deliberately independent of the converter's footer zone."""
    import pymupdf
    from ansibangla._common import read_lines
    from ansibangla.blocks import is_letter_spaced, plain_line
    for page in pymupdf.open(src):
        for line in read_lines(page):
            text = ' '.join(plain_line(line).split())
            if not text or is_letter_spaced(line) or re.fullmatch(r'[০-৯0-9]+', text):
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
    for name, out in (('md', md), ('docx', docx), ('epub', epub)):
        missing = [(p, t) for p, t in _source_lines(src) if t not in out]
        assert not missing, f'{name}: lines missing, e.g. {missing[:3]}'


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
    # every word of the Markdown is in the e-book, in order
    body = re.sub(r'</?(span|sup)\b[^>]*>', '', body)        # inline tags join words
    epub_words = htmllib.unescape(re.sub(r'<[^>]+>', ' ', body)).split()
    md_words = _md_words(written['md'])
    it = iter(epub_words)
    assert all(w in it for w in md_words)


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
