import { expect, test } from '@playwright/test';
import { collect } from './_app';

test('a refused API leaves Cockpit mounted and names the outage and remedy', async ({ page }) => {
  const seen = collect(page);
  await page.route('**/api/**', (route) => route.abort('connectionrefused'));
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.cockpit')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Die Daedalus-API antwortet nicht.' })).toBeVisible();
  // The exact module, not a pattern that would pass on a plausible
  // neighbour: this line is the reader's last instruction when nothing
  // else works, and it named a non-existent module for a while.
  // `tests/contracts/test_ui_named_commands_resolve.py` proves the module
  // imports; this proves the reader is shown it.
  await expect(page.getByText(/python -m daedalus\.interfaces\.cli\.entry web/)).toBeVisible();
  expect(seen.pageErrors).toEqual([]);
});
