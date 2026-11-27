"""Word (.docx) input: convert a document typed in SutonnyMJ (Bijoy) to Unicode Bengali.

The output keeps the document as it is (styles, paragraph spacing, alignment, page
setup, pictures, tables, headers and footers) and changes only SutonnyMJ text:

- Word splits text into many runs (spell-check marks alone cut it every few words).
  Neighbouring runs with the same formatting are merged, and a word still split across
  runs of different formatting is moved to one side, so Bijoy's reordering (ে typed
  before its letter, reph after it) sees whole words.
- Each SutonnyMJ run gets the bundled Unicode font. Bengali Unicode is a complex script
  in Word, laid out with the complex-script size, bold and italic, so those are set to
  match the run's own.
- Page-number fields set in SutonnyMJ get a digits-only font that draws 0-9 as ০-৯:
  Word fills those fields with 0-9, which SutonnyMJ drew as Bangla digits.
- The bundled fonts are embedded.

Markdown, PDF and EPUB are made from the converted document by docxrender (or from a
document already in Unicode, which needs no conversion).
"""
import io
import os
import re
import uuid
import zipfile
import xml.etree.ElementTree as ET

from ._common import _needs_join, is_mj
from .bijoy import convert as bijoy_convert
from .docxexport import BN_FONT, DIGITS_FONT, _obfuscate, embedded_fonts, font_entries

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
XML_SPACE = '{http://www.w3.org/XML/1998/namespace}space'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PARTS = re.compile(r'word/(document|header\d*|footer\d*|footnotes|endnotes|comments)\.xml$')
TEXT_RUN_CHILDREN = {'rPr', 't', 'lastRenderedPageBreak'}


def q(tag, ns=W):
    return f'{{{ns}}}{tag}'


def _local(el):
    return el.tag.rsplit('}', 1)[-1]


def _on(el):
    """A toggle property (w:b, w:i) that is present and not switched off."""
    return el is not None and el.get(q('val'), 'true') not in ('0', 'false', 'off')


# ---------------------------------------------------------------- styles

class Styles:
    """Resolves a run's effective font, size, bold and italic through Word's chain:
    run properties, character style, paragraph style (with basedOn), document defaults."""

    def __init__(self, styles_xml, theme_xml):
        self.styles, self.default_para, self.defaults = {}, None, None
        self.theme = {}
        if theme_xml:
            troot = ET.fromstring(theme_xml)
            for kind in ('major', 'minor'):
                latin = troot.find(f'.//{q(kind + "Font", A)}/{q("latin", A)}')
                if latin is not None:
                    self.theme[kind] = latin.get('typeface')
        self.ppr_defaults = None
        if styles_xml:
            root = ET.fromstring(styles_xml)
            self.defaults = root.find(f'{q("docDefaults")}/{q("rPrDefault")}/{q("rPr")}')
            self.ppr_defaults = root.find(f'{q("docDefaults")}/{q("pPrDefault")}/{q("pPr")}')
            for st in root.findall(q('style')):
                self.styles[st.get(q('styleId'))] = st
                if st.get(q('type')) == 'paragraph' and st.get(q('default')) in ('1', 'true'):
                    self.default_para = st.get(q('styleId'))

    def _chain(self, style_id):
        seen = set()
        while style_id and style_id in self.styles and style_id not in seen:
            seen.add(style_id)
            st = self.styles[style_id]
            yield st.find(q('rPr'))
            based = st.find(q('basedOn'))
            style_id = based.get(q('val')) if based is not None else None

    def para_attrs(self, para, tag):
        """Attributes of a paragraph property (spacing, ind, jc, ...), each taken from the
        first place that sets it: the paragraph, its style chain, the document defaults."""
        sources = []
        ppr = para.find(q('pPr'))
        if ppr is not None:
            sources.append(ppr)
        pstyle = ppr.find(q('pStyle')) if ppr is not None else None
        style_id = pstyle.get(q('val')) if pstyle is not None else self.default_para
        seen = set()
        while style_id and style_id in self.styles and style_id not in seen:
            seen.add(style_id)
            sources.append(self.styles[style_id].find(q('pPr')))
            based = self.styles[style_id].find(q('basedOn'))
            style_id = based.get(q('val')) if based is not None else None
        sources.append(self.ppr_defaults)
        out = {}
        for src in sources:
            el = src.find(q(tag)) if src is not None else None
            if el is None:
                continue
            if not el.attrib:
                out.setdefault('present', True)
            for k, v in el.attrib.items():
                out.setdefault(k.rsplit('}', 1)[-1], v)
        return out

    def line_spacing(self, para):
        """(line, lineRule) of a paragraph: its own spacing, its style chain, the defaults.
        Word's default is single spacing: (240, 'auto')."""
        candidates = []
        ppr = para.find(q('pPr'))
        if ppr is not None:
            candidates.append(ppr)
        pstyle = ppr.find(q('pStyle')) if ppr is not None else None
        style_id = pstyle.get(q('val')) if pstyle is not None else self.default_para
        seen = set()
        while style_id and style_id in self.styles and style_id not in seen:
            seen.add(style_id)
            candidates.append(self.styles[style_id].find(q('pPr')))
            based = self.styles[style_id].find(q('basedOn'))
            style_id = based.get(q('val')) if based is not None else None
        candidates.append(self.ppr_defaults)
        for p in candidates:
            sp = p.find(q('spacing')) if p is not None else None
            if sp is not None and sp.get(q('line')):
                return int(sp.get(q('line'))), sp.get(q('lineRule'), 'auto')
        return 240, 'auto'

    def _font(self, rpr):
        fonts = rpr.find(q('rFonts')) if rpr is not None else None
        if fonts is None:
            return None
        if fonts.get(q('ascii')):
            return fonts.get(q('ascii'))
        theme = fonts.get(q('asciiTheme'))
        if theme:
            return self.theme.get('major' if theme.startswith('major') else 'minor')
        return None

    def resolve(self, run_rpr, para):
        """{'font', 'size' (half-points), 'bold', 'italic'} of a run in a paragraph."""
        chain = [run_rpr]
        rstyle = run_rpr.find(q('rStyle')) if run_rpr is not None else None
        if rstyle is not None:
            chain += list(self._chain(rstyle.get(q('val'))))
        ppr = para.find(q('pPr')) if para is not None else None
        pstyle = ppr.find(q('pStyle')) if ppr is not None else None
        chain += list(self._chain(pstyle.get(q('val')) if pstyle is not None else self.default_para))
        chain.append(self.defaults)
        out = dict(font=None, size=None, bold=None, italic=None)
        for rpr in chain:
            if rpr is None:
                continue
            if out['font'] is None:
                out['font'] = self._font(rpr)
            if out['size'] is None and rpr.find(q('sz')) is not None:
                out['size'] = int(rpr.find(q('sz')).get(q('val')))
            for key, tag in (('bold', 'b'), ('italic', 'i')):
                if out[key] is None and rpr.find(q(tag)) is not None:
                    out[key] = _on(rpr.find(q(tag)))
        out['size'] = out['size'] or 20
        out['bold'], out['italic'] = bool(out['bold']), bool(out['italic'])
        return out


# ---------------------------------------------------------------- runs

def _is_text_run(run):
    return all(_local(c) in TEXT_RUN_CHILDREN for c in run)


def _run_text(run):
    return ''.join(t.text or '' for t in run.findall(q('t')))


def _set_text(run, text):
    ts = run.findall(q('t'))
    if not ts:
        ts = [ET.SubElement(run, q('t'))]
    ts[0].text = text
    ts[0].set(XML_SPACE, 'preserve')
    for t in ts[1:]:
        run.remove(t)
    for c in run.findall(q('lastRenderedPageBreak')):
        run.remove(c)


def _key(run):
    rpr = run.find(q('rPr'))
    return ET.tostring(rpr) if rpr is not None else b''


# order of run-property children in the WordprocessingML schema
RPR_ORDER = ['rStyle', 'rFonts', 'b', 'bCs', 'i', 'iCs', 'caps', 'smallCaps', 'strike', 'dstrike',
             'outline', 'shadow', 'emboss', 'imprint', 'noProof', 'snapToGrid', 'vanish', 'webHidden',
             'color', 'spacing', 'w', 'kern', 'position', 'sz', 'szCs', 'highlight', 'u', 'effect',
             'bdr', 'shd', 'fitText', 'vertAlign', 'rtl', 'cs', 'em', 'lang', 'eastAsianLayout',
             'specVanish', 'oMath']


def _insert_ordered(rpr, el):
    """Insert a run-property child where the schema wants it."""
    rank = RPR_ORDER.index(_local(el)) if _local(el) in RPR_ORDER else len(RPR_ORDER)
    for k, child in enumerate(rpr):
        if _local(child) in RPR_ORDER and RPR_ORDER.index(_local(child)) > rank:
            rpr.insert(k, el)
            return el
    rpr.append(el)
    return el


SUTONNY_LINE = 1.09    # SutonnyMJ's natural line height per point of size (14.1 pt lines
                       # for 12 pt text at Word's 1.08 spacing)

PPR_ORDER = ['pStyle', 'keepNext', 'keepLines', 'pageBreakBefore', 'framePr', 'widowControl',
             'numPr', 'suppressLineNumbers', 'pBdr', 'shd', 'tabs', 'suppressAutoHyphens', 'kinsoku',
             'wordWrap', 'overflowPunct', 'topLinePunct', 'autoSpaceDE', 'autoSpaceDN', 'bidi',
             'adjustRightInd', 'snapToGrid', 'spacing', 'ind', 'contextualSpacing', 'mirrorIndents',
             'suppressOverlap', 'jc', 'textDirection', 'textAlignment', 'textboxTightWrap',
             'outlineLvl', 'divId', 'cnfStyle', 'rPr', 'sectPr', 'pPrChange']


def _exact_lines(para, styles, max_size):
    """Word's 'auto' line spacing multiplies the font's own line height, and Unicode
    Bengali fonts have much taller ones than SutonnyMJ. Set the spacing the paragraph
    had in SutonnyMJ as an exact value, so lines and pages stay where they were."""
    line, rule = styles.line_spacing(para)
    if rule != 'auto' or not max_size:
        return
    exact = line / 240 * SUTONNY_LINE * max_size / 2          # pt (size is in half-points)
    ppr = para.find(q('pPr'))
    if ppr is None:
        ppr = ET.Element(q('pPr'))
        para.insert(0, ppr)
    sp = ppr.find(q('spacing'))
    if sp is None:
        sp = ET.Element(q('spacing'))
        rank = PPR_ORDER.index('spacing')
        pos = next((k for k, c in enumerate(ppr) if _local(c) in PPR_ORDER
                    and PPR_ORDER.index(_local(c)) > rank), len(ppr))
        ppr.insert(pos, sp)
    sp.set(q('line'), str(round(exact * 20)))
    sp.set(q('lineRule'), 'exact')


def _scaled(half_points, scale):
    """A font size in half-points times scale, rounded down (never wider than the source)."""
    return str(max(2, int(int(half_points) * scale + 1e-6)))


def _unicode_rpr(rpr, props, scale=1.0):
    """Give a run (or style, or paragraph mark) the Unicode font at scale times its size,
    with complex-script size, bold and italic matching its own."""
    sz = rpr.find(q('sz'))
    if sz is not None:
        sz.set(q('val'), _scaled(sz.get(q('val')), scale))
    elif props.get('sz') is not None:
        sz = _insert_ordered(rpr, ET.Element(q('sz')))
        sz.set(q('val'), _scaled(props['sz'], scale))
    props = dict(props, sz=None)
    fonts = rpr.find(q('rFonts'))
    if fonts is None:
        fonts = _insert_ordered(rpr, ET.Element(q('rFonts')))
    for attr in list(fonts.attrib):
        if attr.endswith('Theme') or attr.endswith('theme'):
            del fonts.attrib[attr]
    for attr in ('ascii', 'hAnsi', 'cs', 'eastAsia'):
        fonts.set(q(attr), BN_FONT)
    for tag, cs_tag in (('b', 'bCs'), ('i', 'iCs'), ('sz', 'szCs')):
        el = rpr.find(q(tag))
        want = props.get(tag)
        if el is None and want is None:
            continue
        cs = rpr.find(q(cs_tag))
        if cs is None:
            cs = _insert_ordered(rpr, ET.Element(q(cs_tag)))
        if tag == 'sz':
            cs.set(q('val'), el.get(q('val')))
        elif el is not None and el.get(q('val')) is not None:
            cs.set(q('val'), el.get(q('val')))


class _Converter:
    def __init__(self, styles, scale):
        self.styles = styles
        self.scale = scale
        self.runs_converted = 0
        self.para_size = {}                      # paragraph -> largest SutonnyMJ size (half-points)

    def _props(self, run, para):
        rpr = run.find(q('rPr'))
        return self.styles.resolve(rpr, para)

    def is_mj_run(self, run, para):
        font = self._props(run, para)['font']
        return bool(font) and is_mj(font)

    def _to_unicode(self, run, para):
        props = self._props(run, para)
        rpr = run.find(q('rPr'))
        if rpr is None:
            rpr = ET.Element(q('rPr'))
            run.insert(0, rpr)
        _unicode_rpr(rpr, dict(sz=props['size'], b=props['bold'] or None, i=props['italic'] or None),
                     self.scale)
        self.runs_converted += 1
        if para is not None:
            self.para_size[para] = max(self.para_size.get(para, 0), props['size'])

    def container(self, el, para):
        """Convert the runs that are direct children of el (a paragraph, hyperlink, ...)."""
        for c in [c for c in el if _local(c) == 'proofErr']:
            el.remove(c)                         # spell-check marks only split runs
        for c in [c for c in el if _local(c) == 'r' and _is_text_run(c) and _run_text(c)
                  and not _run_text(c).replace('‍', '').replace('‌', '')]:
            el.remove(c)                         # a run holding only a zero-width joiner splits a word
        groups, current = [], []
        for c in list(el):
            if _local(c) == 'r' and self.is_mj_run(c, para) and _is_text_run(c):
                current.append(c)
                continue
            if current:
                groups.append(current)
                current = []
            if _local(c) == 'r' and self.is_mj_run(c, para):
                for t in c.findall(q('t')):      # tabs, breaks, pictures: convert piece by piece
                    t.text = bijoy_convert(t.text or '')
                    t.set(XML_SPACE, 'preserve')
                self._to_unicode(c, para)
        if current:
            groups.append(current)
        for group in groups:
            self._group(el, group, para)

    def _group(self, el, runs, para):
        # 1. merge neighbours with identical formatting
        merged = [runs[0]]
        for run in runs[1:]:
            if _key(run) == _key(merged[-1]):
                _set_text(merged[-1], _run_text(merged[-1]) + _run_text(run))
                el.remove(run)
            else:
                merged.append(run)
        # zero-width joiners mean nothing in Bijoy text and would hide a split word
        texts = [_run_text(r).replace('‍', '').replace('‌', '') for r in merged]
        # 2. a word split across differently formatted runs goes to the earlier one
        for k in range(1, len(merged)):
            a, b = dict(font='MJ', text=texts[k - 1]), dict(font='MJ', text=texts[k])
            if texts[k] and texts[k - 1] and _needs_join(a, b):
                piece = re.match(r'\S*', texts[k]).group(0)
                texts[k - 1] += piece
                texts[k] = texts[k][len(piece):]
        # 3. convert and switch the font
        for run, text in zip(merged, texts):
            if not text:
                el.remove(run)
                continue
            _set_text(run, bijoy_convert(text))
            self._to_unicode(run, para)


PAGE_FIELDS = {'PAGE', 'NUMPAGES', 'SECTIONPAGES'}


def _page_field_runs(root):
    """Runs that make up a page-number field: a simple field, or a complex one from its
    begin mark to its end mark (fields can nest; a run belongs to every open field)."""
    def is_page(instr):
        words = (instr or '').split()
        return bool(words) and words[0].upper() in PAGE_FIELDS

    out, stack = [], []
    for el in root.iter():
        if _local(el) == 'fldSimple' and is_page(el.get(q('instr'))):
            out += list(el.iter(q('r')))
        if _local(el) != 'r':
            continue
        for frame in stack:
            frame['runs'].append(el)
        mark = el.find(q('fldChar'))
        kind = mark.get(q('fldCharType')) if mark is not None else None
        if kind == 'begin':
            stack.append(dict(instr='', runs=[el]))
        for instr in el.findall(q('instrText')):
            if stack:
                stack[-1]['instr'] += instr.text or ''
        if kind == 'end' and stack:
            frame = stack.pop()
            if is_page(frame['instr']):
                out += frame['runs']
    return out


def _convert_part(xml_bytes, styles, scale=1.0, digits_font=None):
    """Convert one WordprocessingML part. Returns (new bytes, runs converted).
    With digits_font, page-number fields set in SutonnyMJ get that font, so Word's
    0-9 still show as ০-৯ (SutonnyMJ drew them so)."""
    text = xml_bytes.decode('utf-8')
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(xml_bytes), events=('start-ns',)):
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass                                 # reserved prefixes such as ns0
    root = ET.fromstring(xml_bytes)
    conv = _Converter(styles, scale)
    parents = {c: p for p in root.iter() for c in p}

    def para_of(el):
        while el is not None and _local(el) != 'p':
            el = parents.get(el)
        return el

    # decided before converting: afterwards every SutonnyMJ run has the Unicode font
    page_runs = [r for r in _page_field_runs(root) if conv.is_mj_run(r, para_of(r))] if digits_font else []
    for el in list(root.iter()):
        if any(_local(c) == 'r' for c in el):
            para = el
            while para is not None and _local(para) != 'p':
                para = parents.get(para)
            conv.container(el, para)
    for ppr_rpr in root.iter(q('rPr')):          # paragraph marks (empty lines keep their size)
        ppr = parents.get(ppr_rpr)
        if ppr is not None and _local(ppr) == 'pPr':
            fonts = ppr_rpr.find(q('rFonts'))
            if fonts is not None and is_mj(fonts.get(q('ascii')) or ''):
                sz = ppr_rpr.find(q('sz'))
                para = parents.get(ppr)
                if sz is not None and para is not None and para not in conv.para_size:
                    conv.para_size[para] = int(sz.get(q('val')))      # an empty SutonnyMJ line
                _unicode_rpr(ppr_rpr, {}, scale)
    for para, size in conv.para_size.items():
        # a paragraph holding a picture, shape or object keeps its spacing: an exact line
        # height would crop the picture to it
        if not any(_local(e) in ('pict', 'drawing', 'object') for e in para.iter()):
            _exact_lines(para, styles, size)
    for run in page_runs:
        fonts = run.find(q('rPr')).find(q('rFonts'))      # set by the conversion just now
        for attr in ('ascii', 'hAnsi', 'cs', 'eastAsia'):
            fonts.set(q(attr), digits_font)
    out = ET.tostring(root, encoding='unicode')
    # keep the original root tag: it declares every prefix that mc:Ignorable names
    original_root = re.search(r'<[A-Za-z][^>]*>', text[text.index('?>') + 2:] if text.startswith('<?') else text)
    out = re.sub(r'^<[^>]*>', lambda m: original_root.group(0), out, count=1)
    decl = text[:text.index('?>') + 2] if text.startswith('<?') else '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    return (decl + '\r\n' + out).encode('utf-8'), conv.runs_converted


def _convert_styles(xml_bytes, scale=1.0):
    """Styles and document defaults set in SutonnyMJ get the Unicode font too."""
    text = xml_bytes.decode('utf-8')
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(xml_bytes), events=('start-ns',)):
        try:
            ET.register_namespace(prefix, uri)
        except ValueError:
            pass
    root = ET.fromstring(xml_bytes)
    changed = False
    for rpr in root.iter(q('rPr')):
        fonts = rpr.find(q('rFonts'))
        if fonts is not None and is_mj(fonts.get(q('ascii')) or ''):
            _unicode_rpr(rpr, {}, scale)
            changed = True
    if not changed:
        return xml_bytes
    out = ET.tostring(root, encoding='unicode')
    body = text[text.index('?>') + 2:] if text.startswith('<?') else text
    out = re.sub(r'^<[^>]*>', lambda m: re.search(r'<[A-Za-z][^>]*>', body).group(0), out, count=1)
    decl = text[:text.index('?>') + 2] if text.startswith('<?') else ''
    return (decl + '\r\n' + out).encode('utf-8')


# ---------------------------------------------------------------- fonts

def _embed_fonts(files, font_dir, fonts):
    """Add the bundled fonts to the package, embedded and obfuscated as Word does.
    fonts: [(family, [regular file, bold file])] from docxexport.embedded_fonts."""
    names = [name for _, family_files in fonts for name in family_files]
    keys = ['{' + str(uuid.uuid4()).upper() + '}' for _ in names]
    ids = [f'rIdSmFont{k}' for k in range(1, len(names) + 1)]
    for k, (name, key) in enumerate(zip(names, keys), 1):
        with open(os.path.join(font_dir, name), 'rb') as fh:
            files[f'word/fonts/ansibangla{k}.odttf'] = _obfuscate(fh.read(), key)

    table = files.get('word/fontTable.xml', b'').decode('utf-8')
    entry = font_entries(fonts, keys, 'rIdSmFont')
    if not table:
        table = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 f'<w:fonts xmlns:w="{W}" xmlns:r="{R}"></w:fonts>')
    if 'xmlns:r=' not in table[:table.index('>', table.index('<w:fonts')) + 1]:
        table = table.replace('<w:fonts ', f'<w:fonts xmlns:r="{R}" ', 1)
    for family, _ in fonts:
        table = re.sub(rf'<w:font w:name="{re.escape(family)}">.*?</w:font>', '', table, flags=re.S)
    files['word/fontTable.xml'] = table.replace('</w:fonts>', entry + '</w:fonts>').encode('utf-8')

    rels_name = 'word/_rels/fontTable.xml.rels'
    rels = files.get(rels_name, b'').decode('utf-8') or (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>')
    new = ''.join(f'<Relationship Id="{i}" Type="{REL}/font" Target="fonts/ansibangla{k}.odttf"/>'
                  for k, i in enumerate(ids, 1))
    files[rels_name] = rels.replace('</Relationships>', new + '</Relationships>').encode('utf-8')

    if 'word/fontTable.xml' not in _overrides(files):
        _add_override(files, '/word/fontTable.xml',
                      'application/vnd.openxmlformats-officedocument.wordprocessingml.fontTable+xml')
        doc_rels = files['word/_rels/document.xml.rels'].decode('utf-8')
        if 'fontTable.xml' not in doc_rels:
            doc_rels = doc_rels.replace('</Relationships>', f'<Relationship Id="rIdSmFontTable" '
                                        f'Type="{REL}/fontTable" Target="fontTable.xml"/></Relationships>')
            files['word/_rels/document.xml.rels'] = doc_rels.encode('utf-8')
    types = files['[Content_Types].xml'].decode('utf-8')
    if 'Extension="odttf"' not in types:
        types = types.replace('<Default ', '<Default Extension="odttf" ContentType='
                              '"application/vnd.openxmlformats-officedocument.obfuscatedFont"/><Default ', 1)
        files['[Content_Types].xml'] = types.encode('utf-8')

    settings = files.get('word/settings.xml', b'').decode('utf-8')
    if settings and '<w:embedTrueTypeFonts' not in settings:
        # schema order: these elements come before embedTrueTypeFonts
        before = ('writeProtection', 'view', 'zoom', 'removePersonalInformation', 'removeDateAndTime',
                  'doNotDisplayPageBoundaries', 'displayBackgroundShape', 'printPostScriptOverText',
                  'printFractionalCharacterWidth', 'printFormsData')
        pos = settings.index('>', settings.index('<w:settings')) + 1
        for tag in before:
            m = None
            for m in re.finditer(rf'<w:{tag}\b[^>]*?(/>|>.*?</w:{tag}>)', settings, re.S):
                pass
            if m:
                pos = max(pos, m.end())
        files['word/settings.xml'] = (settings[:pos] + '<w:embedTrueTypeFonts/>' + settings[pos:]).encode('utf-8')


def _overrides(files):
    return re.findall(r'PartName="/([^"]+)"', files['[Content_Types].xml'].decode('utf-8'))


def _add_override(files, part, content_type):
    types = files['[Content_Types].xml'].decode('utf-8')
    types = types.replace('</Types>', f'<Override PartName="{part}" ContentType="{content_type}"/></Types>')
    files['[Content_Types].xml'] = types.encode('utf-8')


# ---------------------------------------------------------------- entry point

class NoSutonnyMJText(ValueError):
    """The document has no SutonnyMJ text (it may already be Unicode)."""


def read_package(src):
    """A .docx as {part name: bytes}."""
    with zipfile.ZipFile(src) as z:
        return {i.filename: z.read(i.filename) for i in z.infolist()}


def has_unicode_bangla(files):
    """Whether the document's text parts hold Unicode Bengali letters."""
    return any(re.search('[ঀ-৿]', files[name].decode('utf-8', 'replace'))
               for name in files if PARTS.match(name))


def convert_docx(src, out_docx, font_dir, scale=0.9):
    """Convert a SutonnyMJ .docx and write it to out_docx. SutonnyMJ text
    is set at scale times its size, which matches its look (SutonnyMJ draws letters
    smaller than Unicode fonts at the same size). Returns the converted package as
    {part name: bytes}. Raises NoSutonnyMJText, writing nothing, when there is no
    SutonnyMJ text to convert."""
    with zipfile.ZipFile(src) as z:
        infos = z.infolist()
        files = {i.filename: z.read(i.filename) for i in infos}
    fonts = embedded_fonts(font_dir)
    digits_font = DIGITS_FONT if any(f == DIGITS_FONT for f, _ in fonts) else None
    styles = Styles(files.get('word/styles.xml'), files.get('word/theme/theme1.xml'))
    converted = 0
    for name in list(files):
        if PARTS.match(name):
            files[name], n = _convert_part(files[name], styles, scale, digits_font)
            converted += n
    if not converted:
        raise NoSutonnyMJText('no SutonnyMJ text found in this document')
    if 'word/styles.xml' in files:
        files['word/styles.xml'] = _convert_styles(files['word/styles.xml'], scale)
    _embed_fonts(files, font_dir, fonts)

    order = [i.filename for i in infos] + [n for n in files if n not in {i.filename for i in infos}]
    with zipfile.ZipFile(out_docx, 'w', zipfile.ZIP_DEFLATED) as z:
        for name in order:
            z.writestr(name, files[name])
    return files
