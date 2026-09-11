import { expect, test } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.route((url) => url.pathname.startsWith('/api/'), (route) => route.fulfill({ json: { ok: true, projects: [], items: [] } }));
  await page.emulateMedia({ reducedMotion: 'reduce' });
});

test('six real scenes load, stay bounded and stop drawing with reduced motion', async ({ page }, info) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/?view=chat');
  await page.getByRole('button', { name: 'Themes', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Theme-Studio' });
  await editor.getByRole('tab', { name: 'Szene', exact: true }).click();
  await editor.getByRole('radio', { name: 'Interaktives 3D', exact: true }).click();
  const room = page.locator('.scene-environment');
  for (const [id, name] of [
    ['porcelain', 'Porcelain'], ['graphite', 'Graphite Atelier'], ['daylight', 'Spatial Daylight'],
    ['dusk', 'Spatial Dusk'], ['studio', 'Spatial Studio'], ['techno-forest', 'Techno Forest']
  ]) {
    await editor.getByRole('radiogroup', { name: 'Umgebung', exact: true }).getByRole('radio', { name, exact: true }).click();
    await expect(room).toHaveAttribute('data-environment', id);
    await expect(room).toHaveAttribute('data-renderer', 'webgl', { timeout: 25_000 });
    const canvas = room.locator('canvas');
    await expect.poll(() => canvas.getAttribute('data-frames')).not.toBeNull();
    const pixels = await canvas.evaluate((c: HTMLCanvasElement) => c.width * c.height);
    expect(pixels).toBeLessThanOrEqual(1_103_000);
  }
  await page.keyboard.press('Escape');
  const canvas = room.locator('canvas');
  await page.waitForTimeout(200);
  const frames = await canvas.getAttribute('data-frames');
  await page.mouse.move(900, 350);
  await page.waitForTimeout(350);
  expect(await canvas.getAttribute('data-frames')).toBe(frames);
  await page.screenshot({ path: info.outputPath('techno-forest-interactive.png') });
  await page.reload();
  await expect(room).toHaveAttribute('data-environment', 'techno-forest');
  await expect(room).toHaveAttribute('data-renderer', 'webgl', { timeout: 25_000 });
  await page.getByRole('button', { name: 'Themes', exact: true }).click();
  await editor.getByRole('tab', { name: 'Szene', exact: true }).click();
  await editor.getByRole('slider', { name: /^Licht/ }).fill('130');
  await page.waitForTimeout(300);
  await page.reload();
  await page.getByRole('button', { name: 'Themes', exact: true }).click();
  await editor.getByRole('tab', { name: 'Szene', exact: true }).click();
  await expect(editor.getByRole('slider', { name: /^Licht/ })).toHaveValue('130');
  await editor.getByRole('radio', { name: 'Bild', exact: true }).click();
  await expect(room).toHaveAttribute('data-renderer', 'image');
  await expect(room.locator('canvas')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('context loss and a failed asset retain the selected image and usable editor', async ({ page }) => {
  await page.goto('/?view=chat');
  await page.getByRole('button', { name: 'Themes', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Theme-Studio' });
  await editor.getByRole('tab', { name: 'Szene', exact: true }).click();
  await editor.getByRole('radio', { name: 'Interaktives 3D', exact: true }).click();
  const room = page.locator('.scene-environment');
  await expect(room).toHaveAttribute('data-renderer', 'webgl', { timeout: 25_000 });
  await room.locator('canvas').evaluate((c: HTMLCanvasElement) => c.getContext('webgl2')?.getExtension('WEBGL_lose_context')?.loseContext());
  await expect(room).toHaveAttribute('data-renderer', 'fallback');
  await expect(room.locator('img')).toBeVisible();
  await page.route('**/scenes/daylight.glb', (route) => route.abort());
  await editor.getByRole('radio', { name: 'Spatial Daylight', exact: true }).click();
  await expect(room).toHaveAttribute('data-renderer', 'fallback');
  await expect(room.locator('img')).toBeVisible();
  await expect(editor.getByRole('radio', { name: 'Bild', exact: true })).toBeEnabled();
  await page.setViewportSize({ width: 390, height: 844 });
  await editor.getByRole('radio', { name: 'Bild', exact: true }).scrollIntoViewIfNeeded();
  await expect(editor.getByRole('radio', { name: 'Bild', exact: true })).toBeInViewport();
});

test('a room loaded while hidden survives the loading deadline and resumes once visible', async ({ page }) => {
  await page.goto('/?view=chat');
  await page.getByRole('button', { name: 'Themes', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Theme-Studio' });
  await editor.getByRole('tab', { name: 'Szene', exact: true }).click();
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await editor.getByRole('radio', { name: 'Interaktives 3D', exact: true }).click();
  const room = page.locator('.scene-environment');
  // Exercise the actual 20-second deadline: loading may finish without a paint.
  await page.waitForTimeout(21_000);
  await expect(room).toHaveAttribute('data-renderer', 'loading');
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(room).toHaveAttribute('data-renderer', 'webgl');
});
