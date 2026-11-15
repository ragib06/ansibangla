"""Build the bundled fonts: static instances of the variable Noto Serif Bengali whose
width matches SutonnyMJ.

SutonnyMJ draws its letters smaller than Unicode Bengali fonts at the same point size
(ink height of কমনবল: 0.573 em, Noto Serif Bengali 0.647 em), so the converter sets text
at 0.9 of the source size (--scale). At that scale Noto Serif Bengali's width axis at 94
gives the same line widths as SutonnyMJ (measured on non-justified body lines of
SutonnyMJ books: 0.997 of the source width; regular width 100 gives 1.036, SemiCondensed
87.5 gives 0.957).

The instances get their own family name, so Word and LibreOffice never swap in an
installed Noto Serif Bengali of another width. They also centre chandrabindu over the
join of a letter with া, ো or ৌ, as SutonnyMJ does (see centre_candrabindu).

Needs fontTools (pip install fonttools); the converter itself does not.

    python tools/make_fonts.py              # downloads the variable font from google/fonts
    python tools/make_fonts.py NotoSerifBengali[wdth,wght].ttf
"""
import os
import sys
import urllib.request

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

URL = ('https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifbengali/'
       'NotoSerifBengali%5Bwdth,wght%5D.ttf')
WIDTH = 94
FAMILY = 'Noto Serif Bengali W94'
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ansibangla', 'fonts')
STYLES = (('Regular', 400), ('Bold', 700))


def rename(font, style):
    full = f'{FAMILY} {style}' if style != 'Regular' else FAMILY
    ps = f'{FAMILY.replace(" ", "")}-{style}'
    names = font['name']
    for rec in list(names.names):
        if rec.nameID in (16, 17, 21, 22, 25):      # typographic / WWS / variations names
            names.removeNames(nameID=rec.nameID)
    for name_id, value in ((1, FAMILY), (2, style), (3, f'{ps};{WIDTH}'), (4, full), (6, ps)):
        names.setName(value, name_id, 3, 1, 0x409)
        names.setName(value, name_id, 1, 0, 0)
    os2 = font['OS/2']
    os2.usWeightClass = 700 if style == 'Bold' else 400
    os2.fsSelection = (os2.fsSelection & ~0b1100001) | (0b100000 if style == 'Bold' else 0b1000000)
    font['head'].macStyle = 1 if style == 'Bold' else 0


CANDRA = ('uni0981', 'uni0981.alt')          # chandrabindu glyphs
AA = 'uni09BE.fina'                           # া (also the right half of ো)
AU_LENGTH = 'uni09D7.fina'                    # ৗ (the right half of ৌ)


def _mark_base_anchors(font, mark):
    """{base glyph: (x offset of the mark from the base origin)} from the GPOS
    mark-to-base lookups, for one mark glyph."""
    offsets = {}
    for lookup in font['GPOS'].table.LookupList.Lookup:
        for st in lookup.SubTable:
            kind = lookup.LookupType
            if kind == 9:                                    # extension: unwrap
                kind, st = st.ExtensionLookupType, st.ExtSubTable
            if kind != 4:                                    # mark-to-base only
                continue
            marks = st.MarkCoverage.glyphs
            if mark not in marks:
                continue
            rec = st.MarkArray.MarkRecord[marks.index(mark)]
            for base, brec in zip(st.BaseCoverage.glyphs, st.BaseArray.BaseRecord):
                anchor = brec.BaseAnchor[rec.Class]
                if anchor is not None and base not in offsets:
                    offsets[base] = anchor.XCoordinate - rec.MarkAnchor.XCoordinate
    return offsets


def _ink_centre(font, glyph):
    g = font['glyf'][glyph]
    g.recalcBounds(font['glyf'])
    return (g.xMin + g.xMax) / 2 if g.numberOfContours else 0


def centre_candrabindu(font, step=10):
    """Put chandrabindu over the join between a letter and its right-hand vowel stroke
    (দাঁ, খোঁ, পৌঁ), as SutonnyMJ does. Noto attaches it to the letter's own anchor
    (far left on দ) or to ৗ (past the end of পৌঁ); elsewhere its placement is kept.

    Adds one chained-context positioning lookup to the 'abvm' feature, after the
    mark attachment: letter + ঁ + া shifts ঁ to the letter's advance width (where া
    joins); ৗ + ঁ shifts ঁ to the origin of ৗ (where ৗ joins the letter)."""
    from fontTools.otlLib import builder
    from fontTools.ttLib.tables import otTables as ot

    gpos = font['GPOS'].table
    glyph_map = font.getReverseGlyphMap()
    hmtx = font['hmtx']
    lookups = gpos.LookupList.Lookup
    by_dx = {}                                   # (mark, dx) -> base glyphs before া
    au_dx = {}                                   # mark -> dx after ৗ
    for mark in CANDRA:
        if mark not in glyph_map:
            continue
        centre = _ink_centre(font, mark)
        for base, off in _mark_base_anchors(font, mark).items():
            if base == AU_LENGTH:
                au_dx[mark] = round(-(off + centre))
                continue
            if base == AA:
                continue
            dx = round((hmtx[base][0] - (off + centre)) / step) * step
            if dx:
                by_dx.setdefault((mark, dx), []).append(base)

    def single(mark, dx):
        lk = builder.buildLookup([builder.buildSinglePosSubtable(
            {mark: builder.buildValue({'XPlacement': dx})}, glyph_map)])
        lookups.append(lk)
        return len(lookups) - 1

    def chain(backtrack, mark, lookahead, index):
        st = ot.ChainContextPos()
        st.Format = 3
        st.BacktrackCoverage = [builder.buildCoverage(g, glyph_map) for g in backtrack]
        st.InputCoverage = [builder.buildCoverage([mark], glyph_map)]
        st.LookAheadCoverage = [builder.buildCoverage(g, glyph_map) for g in lookahead]
        st.BacktrackGlyphCount, st.InputGlyphCount = len(backtrack), 1
        st.LookAheadGlyphCount = len(lookahead)
        rec = ot.PosLookupRecord()
        rec.SequenceIndex, rec.LookupListIndex = 0, index
        st.PosLookupRecord, st.PosCount = [rec], 1
        return st

    subtables = []
    for mark, dx in au_dx.items():
        subtables.append(chain([[AU_LENGTH]], mark, [], single(mark, dx)))
    for (mark, dx), bases in sorted(by_dx.items()):
        subtables.append(chain([bases], mark, [[AA]], single(mark, dx)))
    if not subtables:
        return 0
    main = ot.Lookup()
    main.LookupType, main.LookupFlag = 8, 0
    main.SubTable, main.SubTableCount = subtables, len(subtables)
    lookups.append(main)
    gpos.LookupList.LookupCount = len(lookups)
    index = len(lookups) - 1
    for rec in gpos.FeatureList.FeatureRecord:
        if rec.FeatureTag == 'abvm':
            rec.Feature.LookupListIndex.append(index)
            rec.Feature.LookupCount = len(rec.Feature.LookupListIndex)
    return sum(len(b) for b in by_dx.values())


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else None
    if src is None:
        src = os.path.join(OUT_DIR, '_NotoSerifBengali-VF.ttf')
        urllib.request.urlretrieve(URL, src)
    try:
        for style, weight in STYLES:
            font = instancer.instantiateVariableFont(TTFont(src), {'wdth': WIDTH, 'wght': weight})
            rename(font, style)
            print(f'{style}: chandrabindu centred for {centre_candrabindu(font)} letter shapes')
            out =os.path.join(OUT_DIR, f'{FAMILY.replace(" ", "")}-{style}.ttf')
            font.save(out)
            print(out)
    finally:
        if len(sys.argv) == 1:
            os.remove(src)


if __name__ == '__main__':
    main()
