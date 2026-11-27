"""ansibangla: convert Bengali text, PDFs and Word files set in the SutonnyMJ (Bijoy) font to Unicode.

    from ansibangla import convert_file, convert_pdf, convert_text
    convert_file('story.docx', 'out/')                    # writes a Unicode .docx
    convert_pdf('book.pdf', 'out/')                       # writes a Unicode .pdf
    convert_pdf('book.pdf', 'out/', formats=('docx', 'epub', 'md'))   # several at once
    convert_text('wbwØ©avq')                               # -> 'নির্দ্বিধায়'
"""
from .api import DEFAULT_FORMATS, FORMATS, convert_docx, convert_file, convert_pdf, convert_text
from .bijoy import convert as bijoy_convert

__all__ = ['convert_file', 'convert_pdf', 'convert_docx', 'convert_text', 'bijoy_convert', 'FORMATS', 'DEFAULT_FORMATS']
__version__ = '1.0.7'
