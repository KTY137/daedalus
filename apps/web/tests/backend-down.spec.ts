import { expect, test } from '@playwright/test';
import { collect } from './_app';

test('a refused API leaves Cockpit mounted and names the outage and remedy', async ({ page }) => {
  const seen = collect(page);
  await page.route('**/api/**', (route) => route.abort('connectionrefused'));
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.cockpit')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Die Daedalus-API antwortet nicht.' })).toBeVisible();
  await expect(page.getByText(/python -m daedalus\.cli web/)).toBeVisible();
  expect(seen.pageErrors).toEqual([]);
});
