import { expect, test, type Page } from '@playwright/test';
import { collect, NOT_BUILT } from './_app';

/**
 * G1-UI-05 — `/status` against the LIVE server.
 *
 * `status` is the one word that routes deterministically (ikarus_os.classify),
 * so this exercises the whole command path — menu, pick, the canonical turn
 * POST, the resumable observation, the final envelope, the Protokoll — without
 * reaching a paid vendor. The rail then has to list the thread this test just
 * made, read back from the canonical spine.
 */

async function openCockpit(page: Page): Promise<void> {
  const res = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(res).not.toBeNull();
  expect(res!.status()).toBe(200);
  expect(await res!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible({ timeout: 20_000 });
}

async function waitForStage(page: Page, timeout = 240_000): Promise<void> {
  await expect(page.locator('.stage-node').first(), 'the stage never drew a node').toBeVisible({ timeout });
}

async function goChat(page: Page): Promise<void> {
  await page.getByRole('button', { name: /Gespräch/ }).click();
  await expect(page.locator('.talk-main')).toBeVisible({ timeout: 10_000 });
}

test.describe('commands, live', () => {
  test('/status sends the deterministic word and the thread appears in the rail', async ({ page }) => {
    const seen = collect(page);
    await openCockpit(page);
    await waitForStage(page);
    await goChat(page);
    await page.evaluate(() => {
      Object.keys(localStorage)
        .filter((k) => k.startsWith('daedalus-thread:'))
        .forEach((k) => localStorage.removeItem(k));
    });
    await page.reload({ waitUntil: 'domcontentloaded' });
    await expect(page.locator('.talk-main')).toBeVisible({ timeout: 60_000 });

    const input = page.getByLabel('Nachricht an Ikarus');
    await input.fill('/status');
    await expect(page.getByRole('listbox', { name: 'Befehle' })).toBeVisible();
    await input.press('Enter');

    // What was sent is the word, not the slash.
    await expect(page.locator('.turn.you .turn-text').last()).toHaveText('status');
    const answer = page.locator('.turn.ikarus').last();
    await expect(answer, 'Ikarus never answered').toBeVisible({ timeout: 60_000 });
    const stamp = answer.locator('.stamp');
    await expect(stamp).toBeVisible({ timeout: 60_000 });
    await expect(stamp).toContainText('GEMESSEN');
    await expect(stamp).toContainText('lokaler Index');
    await expect(answer.locator('.ledger-row[data-key="route"]')).toContainText('Lokaler Index');
    const body = (await answer.locator('.turn-text').innerText()).trim();
    expect(body.length).toBeGreaterThan(0);

    // The spine now has this thread; the rail reads it back from the list route.
    const rail = page.getByRole('navigation', { name: 'Verläufe' });
    await expect(rail.locator('.threads-row.current')).toContainText('status', { timeout: 30_000 });
    expect(seen.pageErrors).toEqual([]);
    expect(seen.api.filter((a) => a.path === '/api/conversations' && a.status >= 400)).toEqual([]);
  });
});
