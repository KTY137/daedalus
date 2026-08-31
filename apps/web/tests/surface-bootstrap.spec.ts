import { expect, test, type Page } from '@playwright/test';

async function expectSingleCockpit(page: Page, path: string) {
  const response = await page.goto(path, { waitUntil: 'domcontentloaded' });
  expect(response?.status()).toBe(200);

  await expect(page.locator('.cockpit')).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('.app-shell')).toHaveCount(0);
  await expect(page.locator('#root')).toHaveCount(1);
  await expect(page.locator('#root > *')).toHaveCount(1);
}

test.describe('shared app bootstrap', () => {
  test('default and unknown surface values mount Cockpit through one root', async ({ page }) => {
    await expectSingleCockpit(page, '/');
    await expectSingleCockpit(page, '/?surface=unknown');
  });

  test('classic and its historical legacy alias render the same Cockpit implementation', async ({ page }) => {
    await expectSingleCockpit(page, '/?surface=classic');
    await expectSingleCockpit(page, '/?surface=legacy');
  });
});
