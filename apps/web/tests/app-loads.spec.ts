import { expect, test } from '@playwright/test';
import { NOT_BUILT, collect } from './_app';

test('the sole Cockpit implementation mounts and talks to its serving API', async ({ page }) => {
  const seen = collect(page);
  await page.route('**/api/**', (route) => route.fulfill({
    status: 200,
    json: { ok: true, generated_at: '', project: null, warnings: [], projects: [] }
  }));
  const response = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(response!.status()).toBe(200);
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
  await expect(page.locator('#root > *')).toHaveCount(1);
  await expect(page.getByRole('navigation', { name: 'Ansicht' })).toBeVisible();
  await expect.poll(() => seen.api.length, { timeout: 30_000 }).toBeGreaterThan(0);
  expect(seen.pageErrors).toEqual([]);
});
