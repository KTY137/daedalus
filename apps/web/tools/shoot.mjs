/**
 * Shoot the cockpit in every theme.
 *
 * One command, one folder of PNGs, one manifest saying what was actually on
 * screen when each was taken. Design rounds in this repository have repeatedly
 * been reviewed from screenshots whose provenance nobody could reconstruct;
 * the manifest is there so a shot can never be mistaken for a mock.
 *
 *   node tools/shoot.mjs --base http://127.0.0.1:5199 --out ../../docs/design/prototypes/cockpit-<date>
 *
 * It fails loudly if the page never rendered a node: a screenshot of an empty
 * stage that looks like a design decision is exactly the lie to avoid.
 */
import { chromium } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';

const argv = process.argv.slice(2);
const arg = (name, fallback) => {
  const i = argv.indexOf(`--${name}`);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : fallback;
};

const BASE = arg('base', 'http://127.0.0.1:5199');
const OUT = path.resolve(arg('out', 'shots'));
const WIDTH = Number(arg('width', 1440));
const HEIGHT = Number(arg('height', 900));
const THEMES = arg('themes', 'kammer,werkstatt,sternkarte,depesche,nachtfenster,leitstand').split(',');
const WAIT_MS = Number(arg('wait', 120000));

async function main() {
  await mkdir(OUT, { recursive: true });
  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: WIDTH, height: HEIGHT } });
  const page = await context.newPage();

  const consoleErrors = [];
  page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()));
  page.on('pageerror', (e) => consoleErrors.push(`pageerror: ${e.message}`));

  const manifest = { base: BASE, viewport: { width: WIDTH, height: HEIGHT }, shots: [] };

  // First load: warm the structure index once so the per-theme shots are not
  // all screenshots of the same "the map is being built" message.
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.stage-node', { timeout: WAIT_MS });

  for (const id of THEMES) {
    await page.evaluate((themeId) => localStorage.setItem('daedalus-theme-id', themeId), id);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.stage-node', { timeout: WAIT_MS });
    // The decision card is fetched separately; without waiting for it the shot
    // is a picture of a cockpit that happens to have nothing pending, which is
    // a different design than the one being reviewed.
    await page.waitForSelector('.decision', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(700);

    const seen = await page.evaluate(() => ({
      themeId: document.documentElement.dataset.themeId,
      chat: document.documentElement.dataset.chat,
      chrome: document.documentElement.dataset.chrome,
      decision: document.documentElement.dataset.decision,
      stage: document.documentElement.dataset.stage,
      nodes: document.querySelectorAll('.stage-node').length,
      focus: document.querySelector('.stage-path')?.textContent || '',
      counts: document.querySelector('.stage-counts')?.textContent || '',
      status: document.querySelector('.statusline')?.textContent || ''
    }));

    if (seen.themeId !== id) throw new Error(`asked for theme ${id}, the page applied ${seen.themeId}`);
    if (!seen.nodes) throw new Error(`theme ${id} rendered zero nodes — refusing to save an empty stage`);

    const file = path.join(OUT, `${id}.png`);
    await page.screenshot({ path: file, animations: 'disabled' });
    manifest.shots.push({ ...seen, file: path.basename(file) });
    process.stdout.write(`${id}: ${seen.nodes} nodes, focus ${seen.focus}\n`);
  }

  manifest.consoleErrors = consoleErrors;
  await writeFile(path.join(OUT, 'manifest.json'), JSON.stringify(manifest, null, 2), 'utf8');
  await browser.close();
  process.stdout.write(`\n${manifest.shots.length} shots in ${OUT}\n`);
  if (consoleErrors.length) process.stdout.write(`console errors: ${consoleErrors.length}\n`);
}

main().catch((e) => {
  process.stderr.write(`${e.stack || e}\n`);
  process.exit(1);
});
