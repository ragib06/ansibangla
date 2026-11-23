// Zip the ansibangla Python package (and the web glue module) into public/ansibangla.zip,
// which the worker unpacks into Pyodide. Runs before `dev` and `build`.
import { zipSync } from 'fflate';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const web = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const pkg = path.join(web, '..', 'python', 'ansibangla');
const files = {};

function add(dir, prefix) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    if (e.name === '__pycache__' || e.name.endsWith('.pyc')) continue;
    const full = path.join(dir, e.name);
    if (e.isDirectory()) add(full, `${prefix}${e.name}/`);
    // fonts are already compressed; store them as they are
    else files[prefix + e.name] = [fs.readFileSync(full), { level: e.name.endsWith('.ttf') ? 0 : 9 }];
  }
}

add(pkg, 'ansibangla/');
files['webconvert.py'] = fs.readFileSync(path.join(web, 'py', 'webconvert.py'));
fs.mkdirSync(path.join(web, 'public'), { recursive: true });
const out = path.join(web, 'public', 'ansibangla.zip');
fs.writeFileSync(out, zipSync(files, { mtime: '2000-01-01' }));
console.log(`packed ${Object.keys(files).length} files -> ${path.relative(web, out)}`);
