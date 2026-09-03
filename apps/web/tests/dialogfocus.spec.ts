import { expect, test, type Page } from '@playwright/test';
import { NOT_BUILT } from './_app';

/**
 * THE MODAL PROMISE, kept.
 *
 * Both overlay panels carry `aria-modal="true"`, which tells assistive
 * technology that everything outside the dialog is hidden. For a while the
 * code behind that promise only MOVED focus to the close button; it did not
 * trap it. Two Tabs from the close button landed on the theme controls behind
 * the scrim, which were then fully operable by keyboard — the exact behaviour
 * the source comment claimed had been fixed.
 *
 * `aria-modal` does nothing for a sighted keyboard user. These tests walk the
 * focus ring with real Tab presses and require it to stay inside.
 */

async function open(page: Page, chip: RegExp, dialog: string) {
  const response = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
  await page.getByRole('button', { name: chip }).click();
  const panel = page.getByRole('dialog', { name: dialog });
  await expect(panel).toBeVisible();
  return panel;
}

/** Where focus is, and whether it is inside the dialog. */
async function focusInside(page: Page, selector: string): Promise<{ inside: boolean; label: string }> {
  return page.evaluate((sel) => {
    const root = document.querySelector(sel);
    const active = document.activeElement as HTMLElement | null;
    return {
      inside: Boolean(root && active && root.contains(active)),
      label: active ? `${active.tagName.toLowerCase()}.${active.className} :: ${(active.textContent || '').trim().slice(0, 40)}` : 'none'
    };
  }, selector);
}

for (const surface of [
  { name: 'Zustand', chip: /^Zustand öffnen/ },
  { name: 'Promotion', chip: /^Promotion öffnen/ }
]) {
  test.describe(`${surface.name} dialog focus`, () => {
    test('Tab never leaves the dialog', async ({ page }) => {
      await open(page, surface.chip, surface.name);

      // Twenty Tabs is well past the number of controls in either panel, so
      // if the ring leaks at all it leaks inside this loop. Two was enough to
      // reach the theme controls before the trap existed.
      for (let i = 0; i < 20; i += 1) {
        await page.keyboard.press('Tab');
        const at = await focusInside(page, '[role="dialog"]');
        expect(at.inside, `Tab ${i + 1} left the dialog and landed on ${at.label}`).toBe(true);
      }
    });

    test('Shift+Tab never leaves the dialog either', async ({ page }) => {
      await open(page, surface.chip, surface.name);

      // Backwards from the close button is the shortest route out: the close
      // button is first in the ring, so one Shift+Tab is the whole test.
      for (let i = 0; i < 8; i += 1) {
        await page.keyboard.press('Shift+Tab');
        const at = await focusInside(page, '[role="dialog"]');
        expect(at.inside, `Shift+Tab ${i + 1} left the dialog and landed on ${at.label}`).toBe(true);
      }
    });

    test('focus starts on the close button and returns to the chip', async ({ page }) => {
      const before = await page.evaluate(() => document.activeElement?.className || '');
      expect(before).toBeDefined();

      await open(page, surface.chip, surface.name);
      const opened = await focusInside(page, '[role="dialog"]');
      expect(opened.inside).toBe(true);
      expect(opened.label).toContain('health-close');

      await page.keyboard.press('Escape');
      await expect(page.getByRole('dialog', { name: surface.name })).toHaveCount(0);

      // Focus is back on the chip that opened it, not lost on <body>.
      const returned = await page.evaluate(() => {
        const active = document.activeElement as HTMLElement | null;
        return active ? `${active.tagName.toLowerCase()}.${active.className}` : 'none';
      });
      expect(returned, 'focus was dropped on the body instead of returning').toContain('status-item');
    });

    test('the controls behind the scrim are not reachable by keyboard', async ({ page }) => {
      // The concrete leak that existed: the theme controls. Named explicitly
      // so a regression says what a user could have pressed.
      await open(page, surface.chip, surface.name);

      const reached: string[] = [];
      for (let i = 0; i < 20; i += 1) {
        await page.keyboard.press('Tab');
        const at = await focusInside(page, '[role="dialog"]');
        if (!at.inside) reached.push(at.label);
      }
      expect(reached, `keyboard reached ${reached.length} controls behind an aria-modal dialog`).toEqual([]);
    });
  });
}
