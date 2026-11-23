"""Text conversion for the web app's paste box, run inside Pyodide.

Loads ansibangla/bijoy.py on its own, without the package's __init__ (which imports
PyMuPDF), so the paste box works as soon as Python itself has loaded, while the
much larger PyMuPDF is still downloading.
"""
import importlib.util
import os

_spec = importlib.util.spec_from_file_location(
    'ansibangla_bijoy_text', os.path.join(os.path.dirname(__file__), 'ansibangla', 'bijoy.py'))
bijoy = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bijoy)


def convert(text, keep_latin=None):
    """Bijoy (SutonnyMJ) text to Unicode. Line by line: the same result as the whole text
    at once (nothing in a conversion crosses a line break), and fast for long pastes."""
    bijoy.set_latin_keep(list(keep_latin) if keep_latin else [])
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return '\n'.join(bijoy.convert(line) for line in text.split('\n'))
