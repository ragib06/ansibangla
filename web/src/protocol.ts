// Messages between the page and the conversion worker.

/** 'html' is the printable page layout; the page turns it into a PDF with the print dialog. */
export type Format = 'html' | 'docx' | 'epub' | 'md';

/** 'text' means text conversion works; files need 'ready' (PyMuPDF loaded too). */
export type Stage = 'runtime' | 'package' | 'text' | 'pymupdf' | 'ready';

export interface OutputFile {
  format: Format;
  name: string;
  bytes: Uint8Array;
}

export type ToWorker =
  | {
      type: 'convert';
      id: number;
      name: string;
      bytes: ArrayBuffer;
      formats: Format[];
      keepLatin: string[];
    }
  | { type: 'text'; id: number; text: string; keepLatin: string[] };

export type FromWorker =
  | { type: 'stage'; stage: Stage }
  | { type: 'done'; id: number; files: OutputFile[]; notes: string; seconds: number }
  | { type: 'text'; id: number; text: string }
  | { type: 'error'; id: number | null; message: string; text?: boolean };
