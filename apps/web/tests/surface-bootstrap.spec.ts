import { expect, test, type Page } from '@playwright/test';

async function expectSingleSurface(page: Page, path: string, expected: 'cockpit' | 'classic') {
  const response = await page.goto(path, { waitUntil: 'domcontentloaded' });
  expect(response?.status()).toBe(200);

  const wanted = expected === 'cockpit' ? page.locator('.cockpit') : page.locator('.app-shell');
  const unwanted = expected === 'cockpit' ? page.locator('.app-shell') : page.locator('.cockpit');
  await expect(wanted).toBeVisible({ timeout: 20_000 });
  await expect(unwanted).toHaveCount(0);
  await expect(page.locator('#root')).toHaveCount(1);
  await expect(page.locator('#root > *')).toHaveCount(1);
}

test.describe('shared app bootstrap', () => {
  test('default and unknown surface values mount Cockpit through one root', async ({ page }) => {
    await expectSingleSurface(page, '/', 'cockpit');
    await expectSingleSurface(page, '/?surface=unknown', 'cockpit');
  });

  test('classic and its historical legacy alias stay on the lazy compatibility branch', async ({ page }) => {
    await expectSingleSurface(page, '/?surface=classic', 'classic');
    await expectSingleSurface(page, '/?surface=legacy', 'classic');
  });
});
