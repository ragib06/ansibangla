"""SutonnyMJ (Bijoy ASCII) -> Unicode Bengali.

Usage:  import bijoy_convert as bc; bc.convert(text)
Self-test: python3 bijoy_convert.py
"""
import re
import unicodedata

# Glyph fixes for the CID-keyed SutonnyMJ subsets produced by PDF text extraction.
# Applied in order, so sequences come before the single characters they contain.
PDF_FIXUPS = {
    # \u2022 is the half form \u0999\u09cd before \u0996 (L) and \u0995\u09cd\u09b7 (\u00ff): \u09b6\u0999\u09cd\u0996, \u0986\u0995\u09be\u0999\u09cd\u0995\u09cd\u09b7\u09be; elsewhere it is \u09c8
    '\u2022L': '\ue010',
    '\u2022\u00ff': '\ue011',
    # \u2026 right after \u09b8\u09cd / \u09b7\u09cd is the \u0995\u09cd\u09b0 glyph (\u09a4\u09c7\u099c\u09b8\u09cd\u0995\u09cd\u09b0\u09bf\u09af\u09bc); after \u2039 (\u0995) it is \u09c3 (\u09b8\u0982\u09b8\u09cd\u0995\u09c3\u09a4\u09bf)
    '\u00af\u2026': '\u00af\u0152',
    '\u00ae\u2026': '\u00ae\u0152',
    '\u2023': '\u02c6',
    '\u2027': '\u2018',
    '\u2025': '\u2039',
    '\u2024': '\u0160',
    '\u2028': '\u2019',
    '\u2022': '\u02c6',
}

REPH = '\uE000'      # placeholder for reph (র্) until it is moved into place
LATIN_MARK = '\uE100'

MAP = [
    ('\ue010', 'ঙ্খ'),            # from PDF_FIXUPS (•L)
    ('\ue011', 'ঙ্ক্ষ'),           # from PDF_FIXUPS (•ÿ)
    ('i\u00a8', 'র\u200d্য'),
    ('\u00aa\u00a8', '্র্য'),
    ('Av', 'আ'),
    ('\u00af\u0152', 'স্ক্র'),
    ('\u00ae\u0152', 'ষ্ক্র'),
    ('A', 'অ'),
    ('B', 'ই'),
    ('C', 'ঈ'),
    ('D', 'উ'),
    ('E', 'ঊ'),
    ('F', 'ঋ'),
    ('G', 'এ'),
    ('H', 'ঐ'),
    ('I', 'ও'),
    ('J', 'ঔ'),
    ('K', 'ক'),
    ('L', 'খ'),
    ('M', 'গ'),
    ('N', 'ঘ'),
    ('O', 'ঙ'),
    ('P', 'চ'),
    ('Q', 'ছ'),
    ('R', 'জ'),
    ('S', 'ঝ'),
    ('T', 'ঞ'),
    ('U', 'ট'),
    ('V', 'ঠ'),
    ('W', 'ড'),
    ('X', 'ঢ'),
    ('Y', 'ণ'),
    ('Z', 'ত'),
    ('_', 'থ'),
    ('`', 'দ'),
    ('a', 'ধ'),
    ('b', 'ন'),
    ('c', 'প'),
    ('d', 'ফ'),
    ('e', 'ব'),
    ('f', 'ভ'),
    ('g', 'ম'),
    ('h', 'য'),
    ('i', 'র'),
    ('j', 'ল'),
    ('k', 'শ'),
    ('l', 'ষ'),
    ('m', 'স'),
    ('n', 'হ'),
    ('o', 'ড়'),
    ('p', 'ঢ়'),
    ('q', 'য়'),
    ('r', 'ৎ'),
    ('s', 'ং'),
    ('t', 'ঃ'),
    ('u', 'ঁ'),
    ('0', '০'),
    ('1', '১'),
    ('2', '২'),
    ('3', '৩'),
    ('4', '৪'),
    ('5', '৫'),
    ('6', '৬'),
    ('7', '৭'),
    ('8', '৮'),
    ('9', '৯'),
    ('v', 'া'),
    ('w', 'ি'),
    ('x', 'ী'),
    ('y', 'ু'),
    ('z', 'ু'),
    ('\u201c', 'ু'),
    ('\u2013', 'ু'),
    ('\u00e6', 'ু'),
    ('~', 'ূ'),
    ('\u0192', 'ূ'),
    ('\u201a', 'ূ'),
    ('\u201e', 'ৃ'),
    ('\u2026', 'ৃ'),
    ('\u2020', 'ে'),
    ('\u2021', 'ে'),
    ('\u02c6', 'ৈ'),
    ('\u2030', 'ৈ'),
    ('\u0160', 'ৗ'),
    ('|', '\u0964'),
    ('\\', '\u0965'),     # ॥ double danda (\ in SutonnyMJ)
    ('&', '্'),
    ('\u00d2', '\u201c'),
    ('\u00d3', '\u201d'),
    ('\u00d4', '\u2018'),
    ('\u00d5', '\u2019'),
    ('\u00d1', '\u2013'),
    ('^', '্ব'),
    ('\u2018', '্তু'),
    ('\u2019', '্থ'),
    ('\u2039', '্ক'),
    ('\u0152', '্ক্র'),
    ('\u201d', 'চ্'),
    ('\u2014', '্ত'),
    ('\u02dc', 'দ্'),
    ('\u2122', 'দ্'),
    ('\u0161', 'ন্'),
    ('\u203a', 'ন্'),
    ('\u0153', '্ন'),
    ('\u0178', '্ব'),
    ('\u00a1', '্ব'),
    ('\u00a2', '্ভ'),
    ('\u00a3', '্ভ্র'),
    ('\u00a4', 'ম্'),
    ('\u00a5', '্ম'),
    ('\u00a6', '্ব'),
    ('\u00a7', '্ম'),
    ('\u00a8', '্য'),
    ('\u00a9', '\ue000'),
    ('\u00aa', '্র'),
    ('\u00ab', '্র'),
    ('\u00ac', '্ল'),
    ('\u00ad', '্ল'),
    ('\u00ae', 'ষ্'),
    ('\u00af', 'স্'),
    ('\u00b0', 'ক্ক'),
    ('\u00b1', 'ক্ট'),
    ('\u00b2', 'ক্ষ্ম'),
    ('\u00b3', 'ক্ত'),
    ('\u00b4', 'ক্ম'),
    ('\u00b5', 'ক্র'),
    ('\u00b6', 'ক্ষ'),
    ('\u00b7', 'ক্স'),
    ('\u00b8', 'গু'),
    ('\u00b9', 'জ্ঞ'),
    ('\u00ba', 'গ্দ'),
    ('\u00bb', 'গ্ধ'),
    ('\u00bc', 'ঙ্ক'),
    ('\u00bd', 'ঙ্গ'),
    ('\u00be', 'জ্জ'),
    ('\u00bf', '্ত্র'),
    ('\u00c0', 'জ্ঝ'),
    ('\u00c1', 'জ্ঞ'),
    ('\u00c2', 'ঞ্চ'),
    ('\u00c3', 'ঞ্ছ'),
    ('\u00c4', 'ঞ্জ'),
    ('\u00c5', 'ঞ্ঝ'),
    ('\u00c6', 'ট্ট'),
    ('\u00c7', 'ড্ড'),
    ('\u00c8', 'ণ্ট'),
    ('\u00c9', 'ণ্ঠ'),
    ('\u00ca', 'ণ্ড'),
    ('\u00cb', 'ত্ত'),
    ('\u00cc', 'ত্থ'),
    ('\u00cd', '্ত'),
    ('\u00ce', 'ত্র'),
    ('\u00cf', 'দ্দ'),
    ('\u00d0', 'ণ্ড'),
    ('\u00d6', '্র'),
    ('\u00d7', 'দ্ধ'),
    ('\u00d8', 'দ্ব'),
    ('\u00d9', 'দ্ম'),
    ('\u00da', 'ন্ঠ'),
    ('\u00db', 'ন্ড'),
    ('\u00dc', 'ন্ধ'),
    ('\u00dd', 'ন্স'),
    ('\u00de', 'প্ট'),
    ('\u00df', 'প্ত'),
    ('\u00e0', 'প্প'),
    ('\u00e1', 'প্স'),
    ('\u00e2', 'ব্জ'),
    ('\u00e3', 'ব্দ'),
    ('\u00e4', 'ব্ধ'),
    ('\u00e5', 'ভ্র'),
    ('\u00e7', 'ম্ফ'),
    ('\u00e8', '্ণ'),            # ণ-ফলা (ÿè = ক্ষ্ণ in তীক্ষ্ণ); the ন-ফলা is œ
    ('\u00e9', 'ল্ক'),
    ('\u00ea', 'ল্গ'),
    ('\u00eb', 'ল্ট'),
    ('\u00ec', 'ল্ড'),
    ('\u00ed', 'ল্প'),
    ('\u00ee', 'ল্ফ'),
    ('\u00ef', 'শু'),
    ('\u00f0', 'শ্চ'),
    ('\u00f1', 'শ্ছ'),
    ('\u00f2', 'ষ্ণ'),
    ('\u00f3', 'ষ্ট'),
    ('\u00f4', 'ষ্ঠ'),
    ('\u00f5', 'ষ্ফ'),
    ('\u00f6', 'স্খ'),
    ('\u00f7', 'স্ট'),
    ('\u00f8', '্ল'),
    ('\u00f9', 'স্ফ'),
    ('\u00fa', '্প'),
    ('\u00fb', 'হু'),
    ('\u00fc', 'হৃ'),
    ('\u00fd', 'হ্ন'),
    ('\u00fe', 'হ্ম'),
    ('\u00ff', 'ক্ষ'),
]

_table = dict(MAP)
_keys = sorted({k for k, _ in MAP}, key=len, reverse=True)
_rx = re.compile('|'.join(re.escape(k) for k in _keys))

CONS = set('কখগঘঙচছজঝঞটঠডঢণতথদধনপফবভমযরলশষসহ')
HAL = '্'
NUKTA = '়'
ZWJ = '‍'
PRE = set('িেৈ')          # ি ে ৈ  (pre-base vowel signs)
SIGNS = set('ািীুূৃেৈোৌৗঁংঃ')

# Latin words the publisher typed inside the SutonnyMJ run; they must stay Latin
# English words typed in a SutonnyMJ font, kept as English instead of being read as Bijoy
# key codes. Empty by default; set with set_latin_keep() (or --keep-latin on the command line).
LATIN_KEEP = []
_latin_rx = None


def set_latin_keep(words):
    """Words (case-sensitive) that stay as typed when they appear in SutonnyMJ text."""
    global LATIN_KEEP, _latin_rx
    LATIN_KEEP = sorted({w.strip() for w in words if w.strip()}, key=len, reverse=True)
    _latin_rx = re.compile(r'\b(' + '|'.join(map(re.escape, LATIN_KEEP)) + r')\b') if LATIN_KEEP else None


def _cluster_end(s, i):
    """s[i] is a consonant; return the index just past its conjunct cluster.
    s is a string or a list of characters."""
    j = i + 1
    if j < len(s) and s[j] == NUKTA:
        j += 1
    while j + 1 < len(s) and s[j] == HAL and s[j + 1] in CONS:
        j += 2
        if j < len(s) and s[j] == NUKTA:
            j += 1
    if j < len(s) and s[j] == ZWJ:
        j += 1
    return j


def _cluster_start(s, i):
    """s[i] is the last consonant of a cluster; return the index of its first letter.
    s is a string or a list of characters."""
    j = i
    if s[j] == NUKTA:
        j -= 1
    while j - 2 >= 0 and s[j - 1] == HAL and (s[j - 2] in CONS or s[j - 2] == NUKTA):
        j -= 2
        if s[j] == NUKTA:
            j -= 1
    return j


def convert(text):
    # zero-width (non-)joiners typed into Bijoy text mean nothing there, but in Unicode they
    # change how conjuncts are drawn (ত্র‍্য); the mapping adds its own where needed (র‍্য)
    text = text.replace('‍', '').replace('‌', '')
    for a, b in PDF_FIXUPS.items():
        text = text.replace(a, b)
    # ú is ্প after a half form (¤ ম্, ¯ স্, ® ষ্: কম্পানি, স্পষ্ট); alone it is প (wú = পি)
    text = re.sub('(?<![¤¯®])ú', 'c', text)
    latin = []
    if _latin_rx is not None:
        text = _latin_rx.sub(lambda m: latin.append(m.group()) or LATIN_MARK, text)
    s = _rx.sub(lambda m: _table[m.group()], text)
    s = s.replace(HAL + HAL, HAL)
    s = s.replace('অা', 'আ')          # অ + া -> আ

    # 1. move pre-base vowel signs (ি ে ৈ) after the consonant cluster they precede
    #    (on a list, in place: rebuilding the string each time is quadratic in long text)
    out = list(s)
    i = 0
    while i < len(out):
        c = out[i]
        if c in PRE and i + 1 < len(out) and out[i + 1] in CONS:
            end = _cluster_end(out, i + 1)
            cluster = out[i + 1:end]
            sign, tail = c, end
            if c == 'ে' and end < len(out) and out[end] == 'া':   # ে + া = ো
                sign, tail = 'ো', end + 1
            elif c == 'ে' and end < len(out) and out[end] == 'ৗ':  # ে + ৗ = ৌ
                sign, tail = 'ৌ', end + 1
            out[i:tail] = cluster + [sign]
            i += len(cluster) + 1
            continue
        i += 1

    # 2. move reph in front of the syllable it sits on, first to last (nothing before a
    #    reph changes once it is placed, so each search starts where the last one was)
    i = 0
    while True:
        try:
            i = out.index(REPH, i)
        except ValueError:
            break
        j = i
        while j - 1 >= 0 and out[j - 1] in SIGNS:
            j -= 1
        if j - 1 >= 0 and (out[j - 1] in CONS or out[j - 1] == NUKTA):
            j = _cluster_start(out, j - 1)
        del out[i]
        out[j:j] = ['র', HAL]
    s = ''.join(out)

    # 3. kar typed before a fola (e.g. Zz¨ = ত্যু), or split from it by a reph
    #    (‡N©¨ = র্ঘ্যে); a vowel sign is never followed by a virama in Unicode
    s = re.sub('([ািীুূৃেৈোৌ])(্[যরব])', r'\2\1', s)
    # chandrabindu typed before a fola and/or vowel sign goes after them (nu¨v = হ্যাঁ)
    s = re.sub('ঁ((?:্[যরব])*)([ািীুূৃোৌ]?)', r'\1\2ঁ', s)
    s = s.replace(HAL + HAL, HAL)

    # ে + ঁ + ৗ / া  ->  ৌ + ঁ / ো + ঁ  (chandrabindu typed between the vowel parts)
    s = s.replace('\u09c7\u0981\u09d7', '\u09cc\u0981')
    s = s.replace('\u09c7\u0981\u09be', '\u09cb\u0981')
    # restore Latin words
    parts = s.split(LATIN_MARK)
    s = parts[0] + ''.join(latin[i] + parts[i + 1] for i in range(len(parts) - 1))
    s = s.replace('অা', 'আ')          # second pass after reordering
    return unicodedata.normalize('NFC', s)
