import { expect, test } from '@playwright/test';
import { collect } from './_app';

test('a refused API leaves Cockpit mounted and names the outage and remedy', async ({ page }) => {
  const seen = collect(page);
  await page.route('**/api/**', (route) => route.abort('connectionrefused'));
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.cockpit')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Die Daedalus-API antwortet nicht.' })).toBeVisible();
  // The remedy has to be a command that RUNS. This asserted
  // `daedalus.cli`, which stopped existing; the cockpit meanwhile offered
  // `daedalus.interfaces.cli.cli`, which never existed. Both were dead when
  // the whole point of this screen is the moment the user needs the right
  // one. tests/test_ui_advice_runs.py is the guard that checks the module is
  // importable; this one only checks the sentence reaches the screen.
  await expect(page.getByText(/python -m daedalus\.interfaces\.cli\.entry web/)).toBeVisible();
  expect(seen.pageErrors).toEqual([]);
});
