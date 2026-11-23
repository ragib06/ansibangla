"""Command line: ansibangla FILE.pdf|FILE.docx [...] [-o OUT_DIR] [-f pdf docx epub md html]"""
import argparse
import sys

from .api import FORMATS, convert_file


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='ansibangla',
        description='Convert PDFs and Word documents set in the SutonnyMJ (Bijoy) Bengali font '
                    'to Unicode.')
    parser.add_argument('files', nargs='*', metavar='FILE',
                        help='one or more SutonnyMJ PDF or .docx files')
    parser.add_argument('-o', '--out-dir', default='.', help='output folder (default: current folder)')
    parser.add_argument('-f', '--formats', nargs='+', action='append', metavar='FORMAT',
                        help=f'output formats, any of {", ".join(FORMATS)}; several can be given, '
                             'separated by spaces or commas or by repeating -f '
                             '(default: the same format as the input, pdf for PDFs and docx for .docx files)')
    parser.add_argument('--scale', type=float, default=0.9,
                        help='font-size factor for the Unicode PDF and DOCX (default 0.9)')
    parser.add_argument('--chrome', help='path to Chrome or Chromium (needed for pdf output)')
    parser.add_argument('--title', help='e-book title for epub output (default: the first heading)')
    parser.add_argument('--keep-latin', metavar='FILE',
                        help='file listing English words typed in the SutonnyMJ font that stay as '
                             'typed (one per line or separated by spaces; # starts a comment)')
    args = parser.parse_args(argv)

    keep_latin = None
    if args.keep_latin:
        with open(args.keep_latin, encoding='utf-8') as fh:
            keep_latin = [w for line in fh for w in line.split('#', 1)[0].split()]

    formats, files = None, list(args.files)
    if args.formats:
        # -f pdf,docx   -f pdf docx   -f pdf -f docx   all mean the same; in
        # "-f pdf docx book.pdf" the file name was taken as a format, so give it back
        tokens = [f for group in args.formats for item in group for f in item.split(',') if f.strip()]
        files += [t for t in tokens if t.lower().endswith(('.pdf', '.docx'))]
        formats = [t for t in tokens if not t.lower().endswith(('.pdf', '.docx'))]
    if not files:
        parser.error('give one or more PDF or .docx files')
    status = 0
    for path in files:
        try:
            written = convert_file(path, args.out_dir, formats=formats, scale=args.scale,
                                   chrome=args.chrome, title=args.title, keep_latin=keep_latin)
        except Exception as exc:          # report and keep going with the other files
            print(f'error: {path}: {exc}', file=sys.stderr)
            status = 1
            continue
        for fmt in written:
            print(written[fmt])
    return status
