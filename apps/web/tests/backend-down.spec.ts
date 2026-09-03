import { expect, test } from '@playwright/test';
import { collect } from './_app';

test('a refused API leaves Cockpit mounted and names the outage and remedy', async ({ page }) => {
  const seen = collect(page);
  await page.route('**/api/**', (route) => route.abort('connectionrefused'));
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.cockpit')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Die Daedalus-API antwortet nicht.' })).toBeVisible();
  // The remedy has to be a command that RUNS, and the exact module -- not a
  // pattern that would pass on a plausible neighbour. This line is the
  // reader's last instruction when nothing else works, and it has been wrong
  // twice: it asserted `daedalus.cli`, which stopped existing, while the
  // cockpit offered `daedalus.interfaces.cli.cli`, which never existed.
  //
  // Two Python guards prove the module is importable --
  // `tests/contracts/test_ui_named_commands_resolve.py` and
  // `tests/test_ui_advice_runs.py`. This one only proves the sentence reaches
  // the screen.
  await expect(page.getByText(/python -m daedalus\.interfaces\.cli\.entry web/)).toBeVisible();
  expect(seen.pageErrors).toEqual([]);
});
