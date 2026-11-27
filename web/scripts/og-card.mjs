// Render scripts/og-card.html to public/og.png (1200 x 630), the social preview image.
// Only needed after editing the card. Needs Chrome or Chromium and playwright-core
// (not a project dependency):  npm i --no-save playwright-core && node scripts/og-card.mjs
// Set CHROME=/path/to/chrome if Chrome is not at /usr/bin/google-chrome.
import { chromium } from 'playwright-core';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const web = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const executablePath = process.env.CHROME || '/usr/bin/google-chrome';
const browser = await chromium.launch({ executablePath });
const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
await page.goto('file://' + path.join(web, 'scripts', 'og-card.html'));
await page.evaluate(() => document.fonts.ready);
await page.screenshot({ path: path.join(web, 'public', 'og.png') });
await browser.close();
console.log('wrote public/og.png');
