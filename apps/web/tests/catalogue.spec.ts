import { expect, test, type Page } from '@playwright/test';
import { NOT_BUILT } from './_app';

/**
 * WHAT THIS INTERFACE MAY BE BUILT FROM, in a browser.
 *
 * `/api/catalogue` had no caller in the cockpit. Its whole purpose is to catch
 * licence traps, and it documents three by name — a licence whose string
 * starts with "MIT" and is not MIT, one recorded NOASSERTION as "the worked
 * example of the honest third state", and a split licence recorded at its
 * stricter half "so a human is forced to look". None of it was on screen.
 *
 * The entries below are verbatim from that endpoint on 2026-09-03.
 */

const project = { name: 'atlas', repo_root: 'C:/work/atlas', team: {}, reachable: true };

const entries = [
  { name: 'ext/react-bits', licence: 'MIT-with-Commons-Clause', licence_url: 'https://github.com/DavidHDev/react-bits/blob/main/LICENSE.md', use_mode: 'reference_only', vendorable: false },
  { name: 'ext/skiper-ui', licence: 'NOASSERTION', licence_url: '', use_mode: 'reference_only', vendorable: false },
  { name: 'ext/origin-ui', licence: 'AGPL-3.0', licence_url: '', use_mode: 'reciprocal', vendorable: false },
  { name: 'ext/shadcn-ui', licence: 'MIT', licence_url: '', use_mode: 'copy_in', vendorable: true },
  { name: 'ext/tremor', licence: 'Apache-2.0', licence_url: '', use_mode: 'copy_in', vendorable: true }
];

function body(over: Record<string, unknown> = {}) {
  return {
    ok: true, generated_at: '', project: null, warnings: [],
    catalogue: {
      schema: 'daedalus-gui-catalogue/1',
      sources: ['external.json', 'glass.json'],
      entries, entry_count: entries.length, rejected: [], rejected_count: 0,
      ...over
    }
  };
}

async function openSettings(page: Page) {
  const response = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
  await page.getByRole('button', { name: 'Einstellungen' }).click();
  const panel = page.locator('.settings.open');
  await expect(panel).toBeVisible();
  return panel;
}

test.describe('component catalogue', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('daedalus-cockpit-view', 'chat'));
    await page.route('**/api/projects', (route) =>
      route.request().method() === 'GET'
        ? route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], projects: [project] } })
        : route.fallback());
    await page.route('**/api/catalogue*', (route) => route.fulfill({ json: body() }));
  });

  test('a licence that starts with MIT and is not MIT says so, in full', async ({ page }) => {
    /*
     * The catalogue's own note: "THE LICENCE TRAP THIS CATALOGUE EXISTS TO
     * CATCH. The string starts with 'MIT'; the licence is not MIT. The
     * Commons Clause removes exactly the right this repo would need."
     */
    const panel = await openSettings(page);
    const row = panel.locator('.cat-row', { hasText: 'ext/react-bits' });

    // Rendered WHOLE. Truncating at the first token produces "MIT", which is
    // the error the catalogue was built to prevent.
    await expect(row.locator('.cat-licence')).toHaveText('MIT-with-Commons-Clause');
    await expect(row).toContainText('nicht MIT');
    await expect(row).toContainText('nicht kopieren');
    await expect(row).toHaveClass(/\bbad\b/);
    // The licence link is offered so a reader can check rather than trust.
    await expect(row.locator('a.cat-licence')).toHaveAttribute('href', /LICENSE\.md$/);
  });

  test('an unestablished licence is neither absent nor free', async ({ page }) => {
    const panel = await openSettings(page);
    const row = panel.locator('.cat-row', { hasText: 'ext/skiper-ui' });

    await expect(row.locator('.cat-licence')).toHaveText('NOASSERTION');
    await expect(row).toContainText('nicht festgestellt');
    // The two readings it must not collapse into.
    await expect(row).toContainText('keine Lizenz');
    await expect(row).toContainText('freie Nutzung');
    await expect(row).toHaveClass(/\bbad\b/);
  });

  test('a reciprocal licence says adoption would spread it', async ({ page }) => {
    const panel = await openSettings(page);
    const row = panel.locator('.cat-row', { hasText: 'ext/origin-ui' });

    await expect(row).toContainText('färbt ab');
    await expect(row).toHaveClass(/\bbad\b/);
  });

  test('a permissive source is not alarmed about, and refusals come first', async ({ page }) => {
    const panel = await openSettings(page);

    const shadcn = panel.locator('.cat-row', { hasText: 'ext/shadcn-ui' });
    await expect(shadcn).toContainText('darf übernommen werden');
    await expect(shadcn).not.toHaveClass(/\bbad\b/);

    // The three that may not be copied are listed before the two that may:
    // a builder needs the refusals before the permissions.
    const names = await panel.locator('.cat-row .cat-name').allInnerTexts();
    expect(names.slice(0, 3).sort()).toEqual(['ext/origin-ui', 'ext/react-bits', 'ext/skiper-ui']);
  });

  test('an entry that never claimed vendorable is not treated as vendorable', async ({ page }) => {
    /*
     * `vendorable` is the operative flag and the backend derives it. An entry
     * that omits it has not been granted anything, and absence must not read
     * as permission. Every other fixture here sets the flag explicitly, so a
     * mutation flipping the check to `!== false` slipped past this suite until
     * this case existed.
     */
    await page.unroute('**/api/catalogue*');
    await page.route('**/api/catalogue*', (route) => route.fulfill({
      json: body({ entries: [{ name: 'ext/partial', licence: 'MIT', use_mode: 'copy_in' }], entry_count: 1 })
    }));
    const panel = await openSettings(page);
    const row = panel.locator('.cat-row', { hasText: 'ext/partial' });

    await expect(row).toBeVisible();
    await expect(row).not.toHaveClass(/ok/);
    // Counted among those that may not be copied.
    await expect(panel.locator('#catalogue-title ~ .settings-hint').first())
      .toContainText('1 davon nicht übernehmbar');
  });

  test('the summary counts what may NOT be copied', async ({ page }) => {
    const panel = await openSettings(page);
    await expect(panel.locator('#catalogue-title ~ .settings-hint').first())
      .toContainText('3 davon nicht übernehmbar');
  });

  test('zero rejections is stated rather than omitted', async ({ page }) => {
    // An empty refusal list is a fact about the load. Omitting it would leave
    // a reader unable to tell "nothing was refused" from "not reported".
    const panel = await openSettings(page);
    await expect(panel.getByText('Kein Eintrag wurde beim Laden abgewiesen.')).toBeVisible();
  });

  test('a catalogue that could not be read is not drawn as no restrictions', async ({ page }) => {
    await page.route('**/api/catalogue*', (route) => route.abort('failed'));
    const panel = await openSettings(page);

    await expect(panel.locator('#catalogue-title ~ .settings-hint.bad'))
      .toContainText('nicht dasselbe wie „keine Einschränkungen“');
    await expect(panel.locator('.cat-list')).toHaveCount(0);
  });

  test('the live backend answers the contract this section reads', async ({ page }) => {
    // No stub. Every entry must carry the three fields the reading depends on.
    await page.unroute('**/api/catalogue*');
    const response = await page.request.get('http://127.0.0.1:8765/api/catalogue');
    expect(response.ok()).toBeTruthy();
    const cat = (await response.json()).catalogue;
    expect(cat.schema).toBe('daedalus-gui-catalogue/1');
    expect(Array.isArray(cat.entries)).toBeTruthy();
    for (const e of cat.entries) {
      expect(typeof e.name, 'an entry with no name').toBe('string');
      expect(typeof e.licence, `${e.name} has no licence string`).toBe('string');
      expect(typeof e.vendorable, `${e.name}.vendorable is not a boolean`).toBe('boolean');
      expect(['copy_in', 'reference_only', 'reciprocal'],
        `${e.name} uses a use_mode this surface has no word for: ${e.use_mode}`).toContain(e.use_mode);
    }
  });
});
