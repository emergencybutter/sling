// Writes a glTF binary next to this script by loading index.html in headless Chromium
// and calling the page's exportGLB(). Needs Playwright, and either network access to
// cdn.jsdelivr.net or THREE_DIR pointing at an unpacked three@0.160.0 package.
//
//   npx playwright install chromium   # once, if you have no Chromium for Playwright
//   node export-glb.mjs               # standard detail -> sling-tsi.glb
//   node export-glb.mjs --high        # ~1M triangles   -> sling-tsi-high.glb
//   THREE_DIR=path/to/three node export-glb.mjs   # offline
import { chromium } from 'playwright';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, join } from 'node:path';

const high = process.argv.includes('--high');
const here = dirname(fileURLToPath(import.meta.url));
const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader'] });
try {
  const page = await browser.newPage();
  page.on('pageerror', e => { console.error('page error:', e.message); });
  page.on('console', m => { if (m.type() === 'error') console.error('console:', m.text()); });
  if (high) await page.addInitScript(() => { window.SLING_DETAIL = 'high'; });
  if (process.env.THREE_DIR) {
    const prefix = 'https://cdn.jsdelivr.net/npm/three@0.160.0/';
    await page.route(prefix + '**', r => r.fulfill({
      body: readFileSync(join(process.env.THREE_DIR, r.request().url().slice(prefix.length))),
      contentType: 'application/javascript',
    }));
  }
  await page.goto(pathToFileURL(join(here, 'index.html')).href);
  await page.waitForFunction(() => typeof window.exportGLB === 'function', null, { timeout: 180000 });
  // Pass the file out as base64: far lighter than a JSON array of bytes for tens of megabytes.
  const b64 = await page.evaluate(async () => {
    const blob = new Blob([await window.exportGLB()]);
    return new Promise(res => {
      const r = new FileReader();
      r.onload = () => res(r.result.slice(r.result.indexOf(',') + 1));
      r.readAsDataURL(blob);
    });
  });
  const out = join(here, high ? 'sling-tsi-high.glb' : 'sling-tsi.glb');
  const bytes = Buffer.from(b64, 'base64');
  writeFileSync(out, bytes);
  console.log(`wrote ${out} (${(bytes.length / 1e6).toFixed(1)} MB)`);
} finally {
  await browser.close();
}
