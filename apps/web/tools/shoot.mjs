// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

/**
 * Shoot the cockpit in every theme.
 *
 * One command, one folder of PNGs, one manifest saying what was actually on
 * screen when each was taken. Design rounds in this repository have repeatedly
 * been reviewed from screenshots whose provenance nobody could reconstruct;
 * the manifest is there so a shot can never be mistaken for a mock.
 *
 *   node tools/shoot.mjs --base http://127.0.0.1:8765 --out ../../docs/design/prototypes/cockpit-<date>
 *
 * Two shots per theme: the map page and the conversation page.
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

const log = (line) => process.stdout.write(String(line).concat('\n'));

/**
 * Wait until the status line stops saying it is still reading the health
 * surface. That surface measurably costs ~40s here, so shooting before it
 * lands gives every round a bar reading "Zustand wird gelesen ..." — true, and
 * useless, since the thing under review is what the bar says once it knows.
 * Waited for, never faked: if it never settles, the shot keeps the unread
 * state and says so out loud.
 */
async function settleHealth(page) {
  await page
    .waitForFunction(() => !(document.querySelector('.statusline')?.textContent || '').includes('wird gelesen'), {
      timeout: 180000
    })
    .catch(() => log('  (health never settled; the shot shows it unread)'));
}

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
  //
  // The health wait belongs here too, and not only in the loop. Reloading while
  // a health request is in flight does not cancel it server-side, so the next
  // page's request queues behind an answer nobody will read — which is why the
  // FIRST theme, and only the first, kept being shot with an unread state line.
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.evaluate(() => localStorage.setItem('daedalus-cockpit-view', 'map'));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForSelector('.stage-node', { timeout: WAIT_MS });
  await settleHealth(page);

  for (const id of THEMES) {
    await page.evaluate((themeId) => {
      localStorage.setItem('daedalus-theme-id', themeId);
      localStorage.setItem('daedalus-cockpit-view', 'map');
    }, id);
    await page.reload({ waitUntil: 'domcontentloaded' });
    await page.waitForSelector('.stage-node', { timeout: WAIT_MS });
    await settleHealth(page);
    await page.waitForTimeout(700);

    const map = await page.evaluate(() => ({
      themeId: document.documentElement.dataset.themeId,
      chrome: document.documentElement.dataset.chrome,
      chat: document.documentElement.dataset.chat,
      stage: document.documentElement.dataset.stage,
      nodes: document.querySelectorAll('.stage-node').length,
      focus: document.querySelector('.stage-path')?.textContent || '',
      counts: document.querySelector('.stage-counts')?.textContent || '',
      status: document.querySelector('.statusline')?.textContent || ''
    }));

    if (map.themeId !== id) throw new Error(`asked for theme ${id}, the page applied ${map.themeId}`);
    if (!map.nodes) throw new Error(`theme ${id} rendered zero nodes — refusing to save an empty stage`);

    const mapFile = path.join(OUT, `karte-${id}.png`);
    await page.screenshot({ path: mapFile, animations: 'disabled' });
    manifest.shots.push({ ...map, page: 'karte', file: path.basename(mapFile) });
    log(`${id} · karte: ${map.nodes} nodes, focus ${map.focus}`);

    // ...and the conversation, which is the other page since 2026-08-25.
    await page.getByRole('button', { name: /Gespräch/ }).click();
    await page.waitForSelector('.talk-main', { timeout: 20000 });
    // The decision is fetched when this page mounts; without waiting the shot
    // is of a cockpit that happens to have nothing pending.
    await page.waitForSelector('.decision', { timeout: 20000 }).catch(() => {});
    await page.waitForTimeout(700);

    const talk = await page.evaluate(() => ({
      themeId: document.documentElement.dataset.themeId,
      chrome: document.documentElement.dataset.chrome,
      chat: document.documentElement.dataset.chat,
      pending: document.querySelector('.viewswitch-badge')?.textContent || '0',
      status: document.querySelector('.statusline')?.textContent || ''
    }));
    const talkFile = path.join(OUT, `gespraech-${id}.png`);
    await page.screenshot({ path: talkFile, animations: 'disabled' });
    manifest.shots.push({ ...talk, page: 'gespraech', nodes: 0, focus: '', counts: '', file: path.basename(talkFile) });
    log(`${id} · gespräch: ${talk.pending} pending`);
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
