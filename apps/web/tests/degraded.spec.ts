import { expect, test } from '@playwright/test';

test('a refused runtime source is reported in Settings instead of rendered as an empty fleet', async ({ page }) => {
  await page.route('**/api/**', (route) => route.fulfill({
    status: 200,
    json: {
      ok: true,
      generated_at: '',
      project: null,
      warnings: [],
      projects: [],
      env: { env_file: '', env_file_exists: false, loaded_keys: [], public: {}, secrets: {}, providers: {} }
    }
  }));
  await page.route('**/api/runtimes/status', (route) => route.fulfill({
    status: 500,
    json: { ok: false, error: 'acceptance: runtime inventory failed' }
  }));
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('.cockpit')).toBeVisible();
  await page.getByRole('button', { name: /^Einstellungen/ }).click();
  await expect(page.locator('.settings.open')).toBeVisible();
  await expect(page.getByText('acceptance: runtime inventory failed', { exact: true })).toBeVisible();
});
