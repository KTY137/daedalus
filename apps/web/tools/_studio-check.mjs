/**
 * Exercise the Theme Studio for real: open it, walk the tabs, edit a built-in
 * (which must fork), rename the fork, export it, delete it, and report what
 * the page actually did at each step.
 */
import { chromium } from '@playwright/test';
import path from 'node:path';

const BASE = process.argv[2] || 'http://127.0.0.1:5199';
const OUT = process.argv[3] || '.';

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));

const log = (...a) => process.stdout.write(`${a.join(' ')}\n`);

await page.goto(BASE, { waitUntil: 'domcontentloaded' });
await page.evaluate(() => {
  localStorage.setItem('daedalus-theme-id', 'kammer');
  localStorage.removeItem('daedalus-themes');
});
await page.reload({ waitUntil: 'domcontentloaded' });
await page.waitForSelector('.stage-node', { timeout: 120000 });

await page.getByRole('button', { name: 'Themes' }).click();
await page.waitForTimeout(400);
log('studio open:', await page.locator('.studio.open').count());
log('built-ins listed:', await page.locator('.studio-body .theme-list').first().locator('li').count());
await page.screenshot({ path: path.join(OUT, 'studio-themes.png'), animations: 'disabled' });

// Farbe tab, then move a colour — this must FORK the built-in.
await page.getByRole('tab', { name: 'Farbe' }).click();
await page.waitForTimeout(200);
await page.screenshot({ path: path.join(OUT, 'studio-farbe.png'), animations: 'disabled' });

const accent = page.getByLabel('Akzent als CSS-Farbe', { exact: true });
await accent.fill('#7fd4ff');
await page.waitForTimeout(500);

const after = await page.evaluate(() => ({
  themeId: document.documentElement.dataset.themeId,
  accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
  stored: JSON.parse(localStorage.getItem('daedalus-themes') || '[]').map((t) => ({ id: t.id, name: t.name, forkedFrom: t.forkedFrom, accent: t.colors?.accent }))
}));
log('after edit ->', JSON.stringify(after));

// Bühne tab: switch the layout live
await page.getByRole('tab', { name: 'Bühne' }).click();
await page.getByRole('radio', { name: 'Karten' }).click();
await page.waitForTimeout(700);
log('stage attr now:', await page.evaluate(() => document.documentElement.dataset.stage));
await page.screenshot({ path: path.join(OUT, 'studio-buehne.png'), animations: 'disabled' });

// Aufbau tab: move the conversation
await page.getByRole('tab', { name: 'Aufbau' }).click();
await page.getByRole('radio', { name: 'Spalte daneben' }).click();
await page.waitForTimeout(700);
log('chat attr now:', await page.evaluate(() => document.documentElement.dataset.chat));
await page.screenshot({ path: path.join(OUT, 'studio-aufbau.png'), animations: 'disabled' });

// Daten tab: export the current theme
await page.getByRole('tab', { name: 'Daten' }).click();
await page.waitForTimeout(200);
await page.screenshot({ path: path.join(OUT, 'studio-daten.png'), animations: 'disabled' });

// back to Themes: the fork must be listed under "Eigene", rename + delete it
await page.getByRole('tab', { name: 'Themes' }).click();
await page.waitForTimeout(300);
const lists = page.locator('.studio-body .theme-list');
log('custom themes listed:', await lists.nth(1).locator('li').count());
await page.screenshot({ path: path.join(OUT, 'studio-fork.png'), animations: 'disabled' });

await lists.nth(1).getByRole('button', { name: 'Umbenennen' }).first().click();
await page.locator('.theme-rename').fill('Eis');
await page.keyboard.press('Enter');
await page.waitForTimeout(400);
log('renamed to:', await page.evaluate(() => JSON.parse(localStorage.getItem('daedalus-themes') || '[]').map((t) => t.name).join(',')));

await lists.nth(1).getByRole('button', { name: 'Löschen' }).first().click();
await page.waitForTimeout(600);
log('after delete ->', await page.evaluate(() => ({
  stored: JSON.parse(localStorage.getItem('daedalus-themes') || '[]').length,
  themeId: document.documentElement.dataset.themeId,
  accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()
})).then(JSON.stringify));

log('console errors:', errors.length ? errors.join(' | ') : 'none');
await browser.close();
