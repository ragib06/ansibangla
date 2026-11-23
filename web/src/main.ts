import './style.css';
import { printLayout } from './print';
import type { Format, FromWorker, OutputFile, Stage, ToWorker } from './protocol';

const $ = <T extends HTMLElement>(sel: string) => document.querySelector<T>(sel)!;

const statusEl = $('#status');
const statusText = $('#status-text');
const drop = $<HTMLLabelElement>('#drop');
const fileInput = $<HTMLInputElement>('#file');
const fileName = $('#file-name');
const form = $<HTMLFormElement>('#form');
const convertBtn = $<HTMLButtonElement>('#convert');
const keepLatin = $<HTMLTextAreaElement>('#keep-latin');
const results = $('#results');
const resultList = $('#result-list');
const notesEl = $('#notes');
const errorEl = $('#error');

const tabFile = $<HTMLButtonElement>('#tab-file');
const tabText = $<HTMLButtonElement>('#tab-text');
const textPanel = $('#text-panel');
const bijoyIn = $<HTMLTextAreaElement>('#bijoy-in');
const unicodeOut = $<HTMLTextAreaElement>('#unicode-out');
const copyBtn = $<HTMLButtonElement>('#copy');
const textError = $('#text-error');

const STAGES: Record<Stage, string> = {
  runtime: 'Loading the Python runtime…',
  package: 'Loading the converter…',
  text: 'Text converter ready. Loading the PDF reader (about 17 MB, once)…',
  pymupdf: 'Text converter ready. Loading the PDF reader (about 17 MB, once)…',
  ready: 'Ready. Your files stay on this device.',
};

const LABELS: Record<Format, string> = {
  html: 'PDF',
  docx: 'Word',
  epub: 'EPUB',
  md: 'Markdown',
};

let workerReady = false;
let textReady = false;
let busy = false;
let file: File | null = null;
let nextId = 1;

const worker = new Worker(new URL('./worker.ts', import.meta.url), { type: 'module' });

worker.onmessage = (ev: MessageEvent<FromWorker>) => {
  const msg = ev.data;
  if (msg.type === 'stage') {
    statusText.textContent = STAGES[msg.stage];
    statusEl.dataset.state = msg.stage === 'ready' ? 'ready' : 'loading';
    workerReady = msg.stage === 'ready';
    if (!textReady && (msg.stage === 'text' || msg.stage === 'pymupdf' || msg.stage === 'ready')) {
      textReady = true;
      convertText();                     // anything pasted while loading
    }
    update();
  } else if (msg.type === 'text') {
    if (msg.id !== lastTextId) return;   // a newer edit is already on its way
    unicodeOut.value = msg.text;
    copyBtn.disabled = !msg.text;
  } else if (msg.type === 'error' && msg.text) {
    textError.textContent = msg.message;
    textError.hidden = false;
  } else if (msg.type === 'done') {
    busy = false;
    showResults(msg.files, msg.notes, msg.seconds);
    update();
  } else {
    busy = false;
    if (msg.id === null) {
      statusEl.dataset.state = 'error';
      statusText.textContent = 'The converter could not load. Check your connection and reload the page.';
    }
    showError(msg.message);
    update();
  }
};

function update() {
  const formats = selectedFormats();
  convertBtn.disabled = !workerReady || busy || !file || formats.length === 0;
  convertBtn.textContent = busy ? 'Converting…' : !workerReady && file ? 'Waiting for the converter…' : 'Convert';
  form.setAttribute('aria-busy', String(busy));
}

function selectedFormats(): Format[] {
  return [...form.querySelectorAll<HTMLInputElement>('input[name=format]:checked')].map(
    (i) => i.value as Format);
}

function setFile(f: File | undefined) {
  errorEl.hidden = true;
  if (!f) return;
  if (!/\.(pdf|docx)$/i.test(f.name)) {
    showError('Choose a PDF or a Word (.docx) file. Older .doc files need saving as .docx first.');
    return;
  }
  file = f;
  fileName.textContent = `${f.name} · ${size(f.size)}`;
  drop.dataset.hasFile = 'true';
  // the same format as the input is the usual wish
  const isPdf = /\.pdf$/i.test(f.name);
  form.querySelectorAll<HTMLInputElement>('input[name=format]').forEach((i) => {
    i.checked = i.value === (isPdf ? 'html' : 'docx');
  });
  results.hidden = true;
  delete results.dataset.filled;
  update();
}

fileInput.addEventListener('change', () => setFile(fileInput.files?.[0]));
form.addEventListener('change', update);
for (const t of ['dragenter', 'dragover']) {
  drop.addEventListener(t, (e) => { e.preventDefault(); drop.dataset.over = 'true'; });
}
for (const t of ['dragleave', 'drop']) {
  drop.addEventListener(t, () => { delete drop.dataset.over; });
}
drop.addEventListener('drop', (e) => {
  e.preventDefault();
  setFile((e as DragEvent).dataTransfer?.files[0]);
});

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!file || busy) return;
  busy = true;
  errorEl.hidden = true;
  results.hidden = true;
  delete results.dataset.filled;
  update();
  const msg: ToWorker = {
    type: 'convert',
    id: nextId++,
    name: file.name,
    bytes: await file.arrayBuffer(),
    formats: selectedFormats(),
    keepLatin: keepLatinWords(),
  };
  worker.postMessage(msg, [msg.bytes]);
});

function showResults(files: OutputFile[], notes: string, seconds: number) {
  resultList.replaceChildren(...files.map(resultItem));
  $('#result-time').textContent = `Done in ${seconds.toFixed(1)} s`;
  notesEl.textContent = notes.trim().replace(/^note: /gm, '');
  notesEl.hidden = !notes.trim();
  results.hidden = false;
  results.dataset.filled = 'true';
  results.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function resultItem(f: OutputFile): HTMLLIElement {
  const li = document.createElement('li');
  li.className = 'result';
  const pdfName = f.name.replace(/\.html$/, '.pdf');
  const info = document.createElement('div');
  info.className = 'result-info';
  info.innerHTML = '<span class="badge"></span><span class="result-name"></span><span class="result-size"></span>';
  info.querySelector('.badge')!.textContent = LABELS[f.format];
  info.querySelector('.result-name')!.textContent = f.format === 'html' ? pdfName : f.name;
  info.querySelector('.result-size')!.textContent = f.format === 'html' ? '' : size(f.bytes.length);
  li.append(info);

  const actions = document.createElement('div');
  actions.className = 'result-actions';
  if (f.format === 'html') {
    const print = button('Save as PDF', 'primary', async () => {
      print.disabled = true;
      print.textContent = 'Preparing pages…';
      try {
        await printLayout(f.bytes, pdfName.replace(/\.pdf$/, ''));
      } catch (err) {
        showError(String((err as Error).message ?? err));
      } finally {
        print.disabled = false;
        print.textContent = 'Save as PDF';
      }
    });
    actions.append(print, button('Download page (HTML)', 'secondary', () => download(f)));
    const hint = document.createElement('p');
    hint.className = 'hint';
    hint.innerHTML = 'In the print dialog, pick <b>Save as PDF</b> as the destination and keep the scale at 100%. '
      + 'Chrome and Edge give the best match to the original pages.';
    li.append(actions, hint);
  } else {
    actions.append(button('Download', 'primary', () => download(f)));
    li.append(actions);
  }
  return li;
}

function button(text: string, kind: 'primary' | 'secondary', onClick: () => void) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = `btn ${kind}`;
  b.textContent = text;
  b.addEventListener('click', onClick);
  return b;
}

const MIME: Record<string, string> = {
  html: 'text/html',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  epub: 'application/epub+zip',
  md: 'text/markdown',
  zip: 'application/zip',
};

function download(f: OutputFile) {
  const ext = f.name.split('.').pop() ?? '';
  const url = URL.createObjectURL(new Blob([f.bytes as BlobPart], { type: MIME[ext] ?? 'application/octet-stream' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = f.name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

// ---------------------------------------------------------------- tabs

function showTab(which: 'file' | 'text', remember = true) {
  const text = which === 'text';
  tabFile.setAttribute('aria-selected', String(!text));
  tabText.setAttribute('aria-selected', String(text));
  form.hidden = text;
  textPanel.hidden = !text;
  results.hidden = text || results.dataset.filled !== 'true';
  if (remember) {
    try { localStorage.setItem('ansibangla.tab', which); } catch { /* storage blocked */ }
  }
  if (text) bijoyIn.focus();
}

tabFile.addEventListener('click', () => showTab('file'));
tabText.addEventListener('click', () => showTab('text'));
// arrow keys move between the two tabs
for (const tab of [tabFile, tabText]) {
  tab.addEventListener('keydown', (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    const other = tab === tabFile ? tabText : tabFile;
    other.click();
    other.focus();
  });
}
try {
  if (location.hash === '#text' || localStorage.getItem('ansibangla.tab') === 'text') showTab('text', false);
} catch { /* storage blocked */ }

// ---------------------------------------------------------------- paste text

let lastTextId = 0;
let textTimer: ReturnType<typeof setTimeout> | undefined;

function keepLatinWords() {
  return keepLatin.value.split('\n').flatMap((l) => l.split('#')[0].split(/\s+/)).filter(Boolean);
}

function convertText() {
  clearTimeout(textTimer);
  textError.hidden = true;
  const text = bijoyIn.value;
  if (!text) {
    lastTextId++;
    unicodeOut.value = '';
    copyBtn.disabled = true;
    return;
  }
  if (!textReady) {
    unicodeOut.value = '';
    unicodeOut.placeholder = 'Loading the converter…';
    return;
  }
  unicodeOut.placeholder = 'ইউনিকোড লেখা এখানে আসবে';
  const msg: ToWorker = { type: 'text', id: ++lastTextId, text, keepLatin: keepLatinWords() };
  worker.postMessage(msg);
}

// convert as the text changes, a moment after typing stops
bijoyIn.addEventListener('input', () => {
  clearTimeout(textTimer);
  textTimer = setTimeout(convertText, 120);
});
keepLatin.addEventListener('input', () => {
  clearTimeout(textTimer);
  textTimer = setTimeout(convertText, 300);
});

copyBtn.addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(unicodeOut.value);
  } catch {
    unicodeOut.select();
    document.execCommand('copy');
  }
  copyBtn.textContent = 'Copied';
  setTimeout(() => { copyBtn.textContent = 'Copy'; }, 1500);
});

function showError(message: string) {
  errorEl.textContent = message;
  errorEl.hidden = false;
}

function size(n: number) {
  return n < 1e6 ? `${Math.max(1, Math.round(n / 1e3))} KB` : `${(n / 1e6).toFixed(1)} MB`;
}

update();
