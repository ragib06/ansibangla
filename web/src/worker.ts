/// <reference lib="webworker" />
// Runs the ansibangla Python package in Pyodide, off the main thread.
// Text conversion needs only Python and bijoy.py, so it is ready first; file conversion
// also needs PyMuPDF (about 17 MB), which loads after.
import type { Format, FromWorker, OutputFile, Stage, ToWorker } from './protocol';

const PYODIDE_URL = 'https://cdn.jsdelivr.net/pyodide/v0.28.3/full/';

declare const self: DedicatedWorkerGlobalScope;

// the parts of the Pyodide API used here
interface PyProxy {
  toJs(options?: { create_proxies?: boolean }): unknown;
  destroy(): void;
}
interface Pyodide {
  loadPackage(names: string | string[]): Promise<void>;
  unpackArchive(buffer: ArrayBuffer, format: string, options?: { extractDir?: string }): void;
  runPython(code: string): unknown;
  pyimport(name: string): { run(...args: unknown[]): PyProxy; convert(...args: unknown[]): string };
  toPy(value: unknown): unknown;
}

function post(msg: FromWorker, transfer: Transferable[] = []) {
  self.postMessage(msg, transfer);
}

function stage(s: Stage) {
  post({ type: 'stage', stage: s });
}

async function loadText(): Promise<Pyodide> {
  stage('runtime');
  // the worker lives one folder down (src/ in dev, assets/ when built), the zip at the site root
  const zip = fetch(new URL('../ansibangla.zip', self.location.href)).then((res) => {
    if (!res.ok) throw new Error(`could not load the converter (${res.status})`);
    return res.arrayBuffer();
  });
  const { loadPyodide } = await import(/* @vite-ignore */ `${PYODIDE_URL}pyodide.mjs`);
  const py: Pyodide = await loadPyodide({ indexURL: PYODIDE_URL });
  stage('package');
  py.unpackArchive(await zip, 'zip', { extractDir: '/app' });
  py.runPython("import sys; sys.path.insert(0, '/app')");
  py.pyimport('webtext');
  stage('text');
  return py;
}

async function loadFiles(text: Promise<Pyodide>): Promise<Pyodide> {
  const py = await text;
  stage('pymupdf');
  await py.loadPackage('pymupdf');
  py.pyimport('webconvert');            // import now, so the first conversion starts at once
  stage('ready');
  return py;
}

const textReady = loadText();
const fileReady = loadFiles(textReady);
fileReady.catch((e) => post({ type: 'error', id: null, message: String(e?.message ?? e) }));

self.onmessage = async (ev: MessageEvent<ToWorker>) => {
  const msg = ev.data;
  if (msg.type === 'text') {
    try {
      const py = await textReady;
      const text = py.pyimport('webtext').convert(msg.text, py.toPy(msg.keepLatin));
      post({ type: 'text', id: msg.id, text });
    } catch (e) {
      post({ type: 'error', id: msg.id, message: pythonError(e), text: true });
    }
    return;
  }
  try {
    const py = await fileReady;
    const t0 = performance.now();
    const run = py.pyimport('webconvert').run;
    const result = run(msg.name, py.toPy(new Uint8Array(msg.bytes)), py.toPy(msg.formats),
                       py.toPy(msg.keepLatin));
    const [rawFiles, notes] = result.toJs({ create_proxies: false }) as [
      [Format, string, Uint8Array][], string];
    result.destroy();
    const files: OutputFile[] = rawFiles.map(([format, name, bytes]) => ({ format, name, bytes }));
    post({ type: 'done', id: msg.id, files, notes, seconds: (performance.now() - t0) / 1000 },
         files.map((f) => f.bytes.buffer as ArrayBuffer));
  } catch (e) {
    post({ type: 'error', id: msg.id, message: pythonError(e) });
  }
};

/** The last line of a Python traceback is the message worth showing. */
function pythonError(e: unknown): string {
  const text = String((e as Error)?.message ?? e).trim();
  const last = text.split('\n').filter(Boolean).pop() ?? text;
  return last.replace(/^\w+(Error|Exception): /, '');
}
