import { expect, test, type Page } from '@playwright/test';
import { collect, NOT_BUILT } from './_app';

/**
 * Acceptance for the themed cockpit — the surface `/` opens.
 *
 * The spec that matters most here is the FAKE-DATA one. Review round three
 * (docs/design/prototypes/sequoia-v2-2026-08-23) found the previous surface
 * offering one project's modules while another project was selected, and its
 * wiki captioned with a third project's name: 35 dead and 5 lying controls that
 * the builder's own tests missed because every test ran against the single
 * indexed project. The rule that came out of it — "every future round needs a
 * per-project fake-data test in the harness" — is `nothing on screen belongs to
 * a project other than the selected one`, and it is checked here against the
 * live payload rather than against a fixture.
 */

const COCKPIT = '/';

async function openCockpit(page: Page): Promise<void> {
  const res = await page.goto(COCKPIT, { waitUntil: 'domcontentloaded' });
  expect(res, 'the server did not answer GET / at all').not.toBeNull();
  expect(res!.status(), 'GET / did not come back 200').toBe(200);
  const html = await res!.text();
  expect(
    html,
    'the server served its "not built" placeholder instead of the app — apps/web/dist is missing or empty'
  ).not.toMatch(NOT_BUILT);

  // The chrome mounts immediately; the stage waits on the structure scan.
  await expect(page.locator('.cockpit'), 'the cockpit never mounted').toBeVisible({ timeout: 20_000 });
}

/** Wait for the map, which is a full structure scan on a cold index. */
async function waitForStage(page: Page, timeout = 240_000): Promise<void> {
  await expect(page.locator('.stage-node').first(), 'the stage never drew a node').toBeVisible({ timeout });
}

/** Every module path the stage is currently drawing. */
async function drawnModules(page: Page): Promise<string[]> {
  return page.locator('.stage-node title').evaluateAll((els) =>
    els
      .map((e) => (e.textContent || '').split(' — ')[0].trim())
      .filter((t) => t && !t.includes('weitere direkte'))
  );
}

/** The selected project, read from the chrome rather than from our own state. */
async function selectedProject(page: Page): Promise<string> {
  return (await page.locator('.projects button.on').first().innerText()).trim();
}

test.describe('cockpit', () => {
  test('opens on a real neighbourhood, and says what it did not draw', async ({ page }) => {
    const signals = collect(page);
    await openCockpit(page);
    await waitForStage(page);

    const project = await selectedProject(page);
    expect(project, 'no project is selected').not.toBe('');

    // The header states three numbers; all three must come from the payload.
    const counts = await page.locator('.stage-counts').innerText();
    expect(counts, 'the header does not state the neighbourhood size').toMatch(/\d+\s*direkt/);
    expect(counts).toMatch(/über zwei Ebenen/);

    const modules = await drawnModules(page);
    expect(modules.length, 'the stage drew no identifiable modules').toBeGreaterThan(0);

    // NO SILENT CAPS. If the layout dropped neighbours, the surface says so and
    // offers the list — a stage that quietly draws 14 of 80 is a smaller
    // codebase than the one on disk.
    const elision = page.locator('.stage-elision');
    if (await elision.count()) {
      await expect(elision).toContainText(/Nicht gezeichnet/);
      const listAll = elision.getByRole('button', { name: 'Alle auflisten' });
      if (await listAll.count()) {
        await listAll.click();
        await expect(page.locator('.palette')).toBeVisible();
        await expect(page.locator('.palette-foot')).toContainText(/nicht gezeichnet|Module der Karte/);
        await page.keyboard.press('Escape');
      }
    }

    expect(signals.pageErrors, `the page threw: ${signals.pageErrors.join(' | ')}`).toHaveLength(0);
  });

  test('nothing on screen belongs to another project', async ({ page }) => {
    await openCockpit(page);
    await waitForStage(page);

    const project = await selectedProject(page);

    // The truth, fetched by the page itself under its own origin.
    const truth = await page.evaluate(async (name) => {
      const r = await fetch(`/api/structure?project=${encodeURIComponent(name)}`);
      const body = await r.json();
      const s = body?.structure;
      return {
        ok: Boolean(s),
        repoRoot: s?.repo_root || '',
        modules: (s?.graph?.nodes || []).map((n: { module: string }) => n.module)
      };
    }, project);

    expect(truth.ok, `/api/structure did not answer for ${project}`).toBe(true);
    const known = new Set(truth.modules);

    // 1. every drawn node is a module of THIS project
    const drawn = await drawnModules(page);
    const foreign = drawn.filter((m) => !known.has(m));
    expect(
      foreign,
      `the stage drew modules that are not in ${project}'s map: ${foreign.slice(0, 5).join(', ')}`
    ).toHaveLength(0);

    // 2. the palette offers only modules of THIS project
    await page.keyboard.press('Control+k');
    await expect(page.locator('.palette')).toBeVisible();
    const offered = await page.locator('.palette-path').allInnerTexts();
    const foreignOffered = offered.map((t) => t.trim()).filter((m) => m && !known.has(m));
    expect(
      foreignOffered,
      `the palette offered modules from another project: ${foreignOffered.slice(0, 5).join(', ')}`
    ).toHaveLength(0);
    await page.keyboard.press('Escape');

    // 3. the status line names THIS project's repository, not a remembered one
    const status = await page.locator('.statusline').innerText();
    expect(status, 'the status line does not name the selected project').toContain(project);
    if (truth.repoRoot) {
      expect(status, 'the status line shows a different repository than the payload').toContain(truth.repoRoot);
    }
  });

  test('switching project replaces the map instead of relabelling it', async ({ page }) => {
    await openCockpit(page);
    await waitForStage(page);

    const first = await selectedProject(page);
    const firstModules = new Set(await drawnModules(page));

    const others = await page.locator('.projects button:not(.on)').allInnerTexts();
    test.skip(others.length === 0, 'this machine has only one project registered — nothing to switch to');

    const second = others[0].trim();
    await page.getByRole('button', { name: second, exact: true }).click();

    // The map must go away BEFORE the new one arrives. Waiting straight for a
    // node would be satisfied by the nodes that are already on screen, and the
    // leak this test exists to catch would slip through its own assertion.
    await expect(page.locator('.stage-empty'), 'the previous map was not cleared on switch').toBeVisible({
      timeout: 15_000
    });

    // A second project means a second scan, which is minutes on a cold index.
    // If it never lands, that is reported as NOT MEASURED rather than as a pass.
    const arrived = await page
      .locator('.stage-node')
      .first()
      .waitFor({ state: 'visible', timeout: 300_000 })
      .then(() => true)
      .catch(() => false);
    test.skip(!arrived, `the map for ${second} did not finish building — cross-project check not measured`);

    await expect
      .poll(async () => (await selectedProject(page)) === second, { timeout: 10_000 })
      .toBe(true);

    const secondModules = await drawnModules(page);
    const leaked = secondModules.filter((m) => firstModules.has(m));
    expect(
      leaked,
      `after switching from ${first} to ${second} the stage still showed ${first}'s modules: ${leaked.slice(0, 5).join(', ')}`
    ).toHaveLength(0);

    const status = await page.locator('.statusline').innerText();
    expect(status, 'the status line still names the previous project').toContain(second);
  });

  test('the theme decides the composition, and switching one re-lays the surface', async ({ page }) => {
    await openCockpit(page);
    await waitForStage(page);

    const read = () =>
      page.evaluate(() => ({
        id: document.documentElement.dataset.themeId,
        chat: document.documentElement.dataset.chat,
        chrome: document.documentElement.dataset.chrome,
        stage: document.documentElement.dataset.stage
      }));

    const before = await read();
    expect(before.id, 'no theme was applied').toBeTruthy();

    await page.getByRole('button', { name: 'Themes' }).click();
    await expect(page.locator('.studio.open')).toBeVisible();

    // Six built-ins, one per design of the gallery round.
    const builtIns = page.locator('.studio-body .theme-list').first().locator('li');
    await expect(builtIns).toHaveCount(6);

    // Pick a different one and prove the SURFACE changed, not just a colour.
    const target = before.id === 'depesche' ? 'Werkstatt' : 'Depesche';
    await page.locator('.theme-pick', { hasText: target }).click();
    await expect.poll(async () => (await read()).id, { timeout: 10_000 }).not.toBe(before.id);

    const after = await read();
    const changed = after.chat !== before.chat || after.chrome !== before.chrome || after.stage !== before.stage;
    expect(changed, `theme ${after.id} changed nothing about the composition`).toBe(true);
    await waitForStage(page, 30_000);
  });

  test('editing a built-in forks it and leaves the original alone', async ({ page }) => {
    await openCockpit(page);
    await waitForStage(page);

    await page.evaluate(() => localStorage.removeItem('daedalus-themes'));
    await page.reload({ waitUntil: 'domcontentloaded' });
    await waitForStage(page);

    await page.getByRole('button', { name: 'Themes' }).click();
    const startId = await page.evaluate(() => document.documentElement.dataset.themeId);

    await page.getByRole('tab', { name: 'Farbe' }).click();
    await page.getByLabel('Akzent als CSS-Farbe', { exact: true }).fill('#7fd4ff');

    await expect
      .poll(() => page.evaluate(() => document.documentElement.dataset.themeId), { timeout: 10_000 })
      .not.toBe(startId);

    // The write to localStorage is deliberately coalesced (a colour picker
    // fires on every frame of a drag), so the assertion polls rather than
    // reading once and calling the delay a defect.
    await expect
      .poll(() => page.evaluate(() => JSON.parse(localStorage.getItem('daedalus-themes') || '[]').length), {
        message: 'the fork was never stored',
        timeout: 5_000
      })
      .toBe(1);

    const state = await page.evaluate(() => ({
      accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(),
      stored: JSON.parse(localStorage.getItem('daedalus-themes') || '[]')
    }));
    expect(state.accent, 'the edit did not reach the page').toBe('#7fd4ff');
    expect(state.stored[0].forkedFrom, 'the fork does not record what it came from').toBe(startId);

    // The built-in must be untouched and still selectable.
    await page.getByRole('tab', { name: 'Themes' }).click();
    await expect(page.locator('.studio-body .theme-list').first().locator('li')).toHaveCount(6);
  });

  test('the composer is live, or it is not there', async ({ page }) => {
    await openCockpit(page);
    await waitForStage(page);

    const input = page.getByLabel('Nachricht an Ikarus');
    await expect(input, 'the conversation has no visible input').toBeVisible();
    await expect(input).toBeEnabled();

    // Send is disabled ONLY while there is nothing to send — never as decoration.
    const send = page.getByRole('button', { name: 'Senden' });
    await expect(send).toBeDisabled();
    await input.fill('Was ist hier los?');
    await expect(send, 'the send button stays dead with a message typed').toBeEnabled();
    await input.fill('');
  });
});
