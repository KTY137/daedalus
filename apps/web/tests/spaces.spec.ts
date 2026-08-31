import { expect, test } from '@playwright/test';

test('the existing Karte, Gespräch and IDE navigation remains one Cockpit', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const cockpit = page.locator('.cockpit');
  await expect(cockpit).toBeVisible();
  const navigation = page.getByRole('navigation', { name: 'Ansicht' });

  await navigation.getByRole('button', { name: 'Gespräch' }).click();
  await expect(cockpit).toHaveAttribute('data-view', 'chat');
  await navigation.getByRole('button', { name: 'IDE' }).click();
  await expect(cockpit).toHaveAttribute('data-view', 'ide');
  await navigation.getByRole('button', { name: 'Karte' }).click();
  await expect(cockpit).toHaveAttribute('data-view', 'map');
  await expect(page.locator('.app-shell')).toHaveCount(0);
});
