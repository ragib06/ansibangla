"""Glue between the web app's worker and the ansibangla package, run inside Pyodide.

The worker writes nothing itself: it hands over the uploaded file's bytes and gets back
the output files as bytes, so all paths stay inside Pyodide's in-memory file system.
"""
import contextlib
import io
import os
import shutil
import sys
import zipfile

from ansibangla import api

WORK = '/work'


def run(name, data, formats, keep_latin=None):
    """Convert one uploaded file. formats is a list of 'html', 'docx', 'epub', 'md'
    ('html' is the printable page layout the browser turns into a PDF).

    Returns (files, notes): files is a list of (format, file name, bytes); Markdown with
    pictures comes as one .zip holding the .md and its pictures folder. notes is what
    the converter reported on stderr (pictures left out and so on).
    """
    shutil.rmtree(WORK, ignore_errors=True)
    src_dir, out_dir = os.path.join(WORK, 'in'), os.path.join(WORK, 'out')
    os.makedirs(src_dir)
    os.makedirs(out_dir)
    src = os.path.join(src_dir, os.path.basename(name))
    with open(src, 'wb') as fh:
        fh.write(bytes(data))

    err = io.StringIO()
    keep = list(keep_latin) if keep_latin else None
    with contextlib.redirect_stderr(err):
        try:
            written = api.convert_file(src, out_dir, formats=list(formats), keep_latin=keep)
        except ValueError as exc:
            # a Word file already in Unicode (say, an edited earlier output) has no Word
            # file to make, but can still become a PDF, e-book or Markdown
            if 'already in Unicode' not in str(exc):
                raise
            rest = [f for f in formats if f != 'docx']
            if not rest:
                raise ValueError('This Word file is already in Unicode. Choose PDF, EPUB or '
                                 'Markdown to make those from it.') from None
            written = api.convert_file(src, out_dir, formats=rest, keep_latin=keep)
            print('note: this Word file is already in Unicode, so no new Word file was made',
                  file=sys.stderr)

    files = []
    for fmt, path in written.items():
        img_dir = path[:-len('.md')] + '_images' if fmt == 'md' else None
        if img_dir and os.path.isdir(img_dir) and os.listdir(img_dir):
            files.append((fmt, os.path.basename(path)[:-len('.md')] + '_md.zip', _zip_md(path, img_dir)))
            continue
        with open(path, 'rb') as fh:
            files.append((fmt, os.path.basename(path), fh.read()))
    shutil.rmtree(WORK, ignore_errors=True)
    notes = err.getvalue().replace(src_dir + '/', '')
    return files, notes


def _zip_md(md_path, img_dir):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        z.write(md_path, os.path.basename(md_path))
        for f in sorted(os.listdir(img_dir)):
            z.write(os.path.join(img_dir, f), os.path.basename(img_dir) + '/' + f)
    return buf.getvalue()
