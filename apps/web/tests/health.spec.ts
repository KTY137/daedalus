import { expect, test, type Page } from '@playwright/test';
import { collect, NOT_BUILT } from './_app';

/**
 * The health surface, fixture-backed.
 *
 * The status line's health chip was a button wired to close the theme studio:
 * it looked like it would tell you which of the seven degraded subsystems was
 * degraded, and it did nothing. These payloads are the shape `/api/health`
 * really answers with — twenty subsystems, each carrying the question it
 * answers, a state from the five-word vocabulary, a headline, a remedy, and
 * facts stamped MEASURED / INHERITED / ASSUMED with their age.
 */

const project = { name: 'atlas', repo_root: 'C:\\work\\atlas', team: {}, reachable: true };

const health = {
  schema: 1,
  generated_at: '2026-09-03T09:00:00+00:00',
  states: ['working', 'present', 'degraded', 'absent', 'unknown'],
  counts: { working: 2, present: 0, degraded: 1, absent: 1, unknown: 0 },
  verdict: 1,
  not_proven: ['bench.residency'],
  asked: {},
  subsystems: [
    {
      name: 'git.worktree', asks: 'which tree is every other answer about?', state: 'working',
      headline: 'fba3bcd9 on worktree-g1-ui-ikarus', remedy: '', required: true, seconds: 0.1,
      facts: [{ label: 'head', value: 'fba3bcd9', provenance: 'MEASURED', source: null, age_s: 12 }]
    },
    {
      name: 'ollama.endpoint', asks: 'can the local bench answer at all?', state: 'degraded',
      headline: 'connect refused on 127.0.0.1:11434', remedy: 'Starte Ollama, dann lade neu.', required: false, seconds: 2,
      facts: [
        { label: 'host', value: 'http://127.0.0.1:11434', provenance: 'MEASURED', source: 'probe', age_s: 3 },
        { label: 'model', value: 'qwen2.5-coder:7b', provenance: 'ASSUMED', source: null, age_s: null },
        { label: 'shape', value: { tags: 0 }, provenance: 'INHERITED', source: 'cache', age_s: 7200 }
      ]
    },
    {
      name: 'docker.engine', asks: 'is a container runtime available?', state: 'absent',
      headline: 'no docker on PATH', remedy: '', required: false, seconds: 0.2, facts: []
    },
    {
      name: 'spine.ledger', asks: 'is the canonical event spine writable?', state: 'working',
      headline: 'runs/spine.sqlite3, 4210 intents', remedy: '', required: true, seconds: 0.3,
      facts: [{ label: 'intents', value: 4210, provenance: 'MEASURED', source: null, age_s: 1 }]
    }
  ]
};

async function openCockpit(page: Page) {
  const response = await page.goto('/?view=chat', { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
}

async function stub(page: Page, options: { health?: unknown; fail?: boolean } = {}) {
  await page.addInitScript(() => localStorage.setItem('daedalus-cockpit-view', 'chat'));
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], projects: [project] } });
  });
  await page.route('**/api/structure**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], structure: { graph: { nodes: [], edges: [] } } }
  }));
  await page.route('**/api/runtimes/status**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: null, warnings: [], runtimes: [] }
  }));
  await page.route('**/api/drafts**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], scope: project.repo_root, pending_count: 0, drafts: [] }
  }));
  await page.route('**/api/health**', async (route) => {
    if (options.fail) return route.abort('connectionrefused');
    await route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], health: options.health ?? health } });
  });
}

test.describe('health surface', () => {
  test('the chip opens the surface and names what the counts only counted', async ({ page }) => {
    const seen = collect(page);
    await stub(page);
    await openCockpit(page);

    // The chip carries the counts, as it always did.
    const chip = page.locator('.status-item.link');
    await expect(chip).toContainText('1 beeinträchtigt');
    await chip.click();

    const panel = page.getByRole('dialog', { name: 'Zustand' });
    await expect(panel).toBeVisible();

    // Only the ones that need attention, worst first, and the working ones
    // are hidden rather than absent — the foot says how many.
    await expect(panel.locator('.health-row')).toHaveCount(2);
    await expect(panel.locator('.health-row').first()).toContainText('ollama.endpoint');
    await expect(panel.locator('.health-row').nth(1)).toContainText('docker.engine');
    await expect(panel.locator('.health-foot')).toContainText('4 Prüfungen');
    await expect(panel.locator('.health-foot')).toContainText('2 laufende ausgeblendet');

    // The question the subsystem exists to answer, and its remedy.
    await expect(panel).toContainText('can the local bench answer at all?');
    await expect(panel).toContainText('Starte Ollama, dann lade neu.');

    // Not proven is not the same as failed, and the panel says so.
    await expect(panel).toContainText('bench.residency');
    await expect(panel).toContainText('nicht dasselbe wie fehlgeschlagen');

    expect(seen.pageErrors).toEqual([]);
  });

  test('every fact carries the provenance stamp the backend attached', async ({ page }) => {
    await stub(page);
    await openCockpit(page);
    await page.locator('.status-item.link').click();
    const panel = page.getByRole('dialog', { name: 'Zustand' });

    await panel.getByRole('button', { name: /ollama\.endpoint/ }).click();
    const facts = panel.locator('.health-fact');
    await expect(facts).toHaveCount(3);
    await expect(facts.nth(0)).toContainText('MEASURED');
    await expect(facts.nth(1)).toContainText('ASSUMED');
    await expect(facts.nth(2)).toContainText('INHERITED');
    // An object value is printed as JSON, never as [object Object].
    await expect(facts.nth(2)).toContainText('{"tags":0}');
    await expect(panel).not.toContainText('[object Object]');
    // The age is a measured fact too, and it belongs to the fact beside it.
    await expect(facts.nth(0)).toContainText('3 s alt');
    await expect(facts.nth(2)).toContainText('2 h alt');
    // `age_s: null` is not an age of zero: the fact simply shows none.
    await expect(facts.nth(1)).not.toContainText('alt');
  });

  test('showing all includes the working ones, and the filter says which way it is', async ({ page }) => {
    await stub(page);
    await openCockpit(page);
    await page.locator('.status-item.link').click();
    const panel = page.getByRole('dialog', { name: 'Zustand' });

    await panel.getByRole('button', { name: 'Alle zeigen' }).click();
    await expect(panel.locator('.health-row')).toHaveCount(4);
    await expect(panel).toContainText('spine.ledger');
    await expect(panel.getByRole('button', { name: 'Nur Auffälliges' })).toBeVisible();
  });

  test('a health read that failed is never drawn as a healthy system', async ({ page }) => {
    await stub(page, { fail: true });
    await openCockpit(page);

    // The chip already refuses to collapse the failure into a state.
    const chip = page.locator('.status-item.link');
    await expect(chip).toContainText('Zustand ungelesen');
    await chip.click();

    const panel = page.getByRole('dialog', { name: 'Zustand' });
    await expect(panel).toContainText('konnte nicht gelesen werden');
    // Not one subsystem row: an unread surface has nothing to list, and must
    // not render as "nothing wrong".
    await expect(panel.locator('.health-row')).toHaveCount(0);
  });

  test('Escape closes it', async ({ page }) => {
    await stub(page);
    await openCockpit(page);
    await page.locator('.status-item.link').click();
    await expect(page.getByRole('dialog', { name: 'Zustand' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog', { name: 'Zustand' })).toBeHidden();
  });
});
