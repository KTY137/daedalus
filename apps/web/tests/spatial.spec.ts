import { expect, test } from '@playwright/test';

// Offline presentation fixtures. Never run a mission or mutate backend state.
test.beforeEach(async ({ page }) => {
  await page.route((url) => url.pathname.startsWith('/api/'), async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/projects') {
      await route.fulfill({ json: {
        ok: true,
        projects: [{ name: 'UI fixture', reachable: true, repo_root: '/ui-fixture' }]
      } });
    } else {
      await route.fulfill({ status: 503, json: { ok: false, error: 'Offline UI fixture' } });
    }
  });
});

test('spatial controls persist and the existing navigation still works', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/?view=chat');
  // A fresh installation opens in a room with the sculpture off (G1-UI-13).
  await expect(page.locator('html')).toHaveAttribute('data-theme-id', 'room-graphite');
  await expect(page.locator('html')).toHaveAttribute('data-environment', 'graphite');
  await expect(page.locator('.scene-environment[data-environment="graphite"] img')).toHaveCount(1);
  await expect(page.locator('.spatial-scene')).toHaveCount(0);
  await page.getByRole('button', { name: 'Architektur verstehen', exact: true }).click();
  await expect(page.locator('.composer textarea')).toHaveValue('Erklär mir die Architektur dieses Projekts.');
  await page.getByRole('button', { name: 'Themes', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Theme-Studio' });
  // The rejected Liquid Glass reference is still selectable and still draws its sculpture.
  await editor.getByRole('button', { name: 'Liquid Glass auswählen', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme-id', 'liquid');
  await expect(page.locator('.spatial-scene.compact')).toHaveAttribute('data-renderer', 'webgl');
  await expect(page.locator('.spatial-scene[data-renderer="webgl"]')).toHaveCount(1);
  await editor.getByRole('tab', { name: 'Szene', exact: true }).click();
  await editor.getByRole('radio', { name: 'Aus', exact: true }).click();
  await expect(page.locator('.spatial-scene')).toHaveCount(0);
  await expect(editor.getByRole('status')).toContainText('Kopie');
  await page.waitForTimeout(350); // Existing debounced localStorage write.
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-scene', 'off');
  await expect(page.locator('.spatial-scene')).toHaveCount(0);
  await page.getByRole('button', { name: 'Themes', exact: true }).click();
  await editor.getByRole('button', { name: 'Frost auswählen', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
  await page.keyboard.press('Escape');
  await expect(page.getByRole('button', { name: 'Themes', exact: true })).toBeFocused();
  await page.getByRole('button', { name: 'Karte', exact: true }).first().click();
  await expect(page.locator('.cockpit')).toHaveAttribute('data-view', 'map');
  await page.getByRole('button', { name: 'Gespräch', exact: true }).click();
  await expect(page.locator('.convo-open-line')).toBeVisible();
  expect(errors).toEqual([]);
});

test('390px layout keeps the invitation, composer and editor reachable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/?view=chat');
  const invitation = page.locator('.convo-open-line');
  const composer = page.locator('.composer');
  await expect(invitation).toBeVisible();
  await expect(invitation).toBeInViewport();
  await expect(composer).toBeInViewport();
  const bodyBounds = await page.locator('.cockpit-body.talk').boundingBox();
  const inputBounds = await composer.boundingBox();
  expect(bodyBounds).not.toBeNull();
  expect(inputBounds).not.toBeNull();
  expect(inputBounds!.x).toBeGreaterThanOrEqual(0);
  expect(inputBounds!.x + inputBounds!.width).toBeLessThanOrEqual(390);
  expect(inputBounds!.y).toBeGreaterThanOrEqual(bodyBounds!.y);
  expect(inputBounds!.y + inputBounds!.height).toBeLessThanOrEqual(bodyBounds!.y + bodyBounds!.height);
  await page.getByRole('button', { name: 'Architektur verstehen', exact: true }).click();
  await expect(page.locator('.composer textarea')).toHaveValue('Erklär mir die Architektur dieses Projekts.');
  await expect(page.locator('.composer textarea')).toBeFocused();
  await expect(composer).toBeInViewport();
  const rail = await page.locator('.talk-side').boundingBox();
  expect(rail!.y).toBeGreaterThanOrEqual(inputBounds!.y + inputBounds!.height);
  await page.getByRole('button', { name: 'Themes', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Theme-Studio' });
  await expect.poll(async () => {
    const bounds = await editor.boundingBox();
    return Boolean(bounds && bounds.x >= 0 && bounds.x + bounds.width <= 390);
  }).toBe(true);
  await editor.getByRole('tab', { name: 'Material', exact: true }).click();
  await expect(editor.getByRole('slider', { name: /Eckradius/ })).toBeVisible();
});

test('the spatial map preserves inspectable module evidence', async ({ page }, testInfo) => {
  await page.route((url) => url.pathname === '/api/projects', (route) => route.fulfill({ json: {
    ok: true, projects: [{ name: 'UI fixture', reachable: true, repo_root: '/ui-fixture' }]
  } }));
  await page.route((url) => url.pathname === '/api/structure', (route) => route.fulfill({ json: {
    ok: true, project: 'UI fixture', structure: {
      n_files: 4, graph: {
        nodes: ['app.ts', 'theme.ts', 'scene.ts', 'store.ts'].map((module, index) => ({ module, fan_in: 4 - index, loc: 100 + index * 20, score: 10 - index, language: 'typescript' })),
        edges: ['theme.ts', 'scene.ts', 'store.ts'].map((target) => ({ source: 'app.ts', target, weight: 1 })),
        n_nodes_total: 4, n_edges_total: 3, n_edges_offmap: 0, truncated: false
      }
    }
  } }));
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/?view=map');
  await expect(page.locator('.stage-node')).toHaveCount(4);
  await expect(page.locator('.stage-counts')).toContainText('3 direkt');
  await expect(page.locator('.stage-focus')).toHaveText('app.ts');
  await page.screenshot({ path: testInfo.outputPath('spatial-map.png') });
  await page.getByRole('button', { name: 'Themes', exact: true }).click();
  await page.getByRole('button', { name: 'Frost auswählen', exact: true }).click();
  await page.keyboard.press('Escape');
  await expect(page.locator('.stage-node')).toHaveCount(4);
  await expect(page.locator('.stage-counts')).toContainText('3 direkt');
  await page.screenshot({ path: testInfo.outputPath('spatial-frost-map.png') });
  expect(errors).toEqual([]);
});

test('reduced motion stops drawing and WebGL loss keeps the UI usable', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  // The sculpture only draws in the Liquid Glass reference now; pin it.
  await page.addInitScript(() => localStorage.setItem('daedalus-theme-id', 'liquid'));
  await page.addInitScript(() => {
    const prototype = WebGLRenderingContext.prototype;
    const draw = prototype.drawArrays;
    (window as unknown as { sceneFrames: number }).sceneFrames = 0;
    prototype.drawArrays = function (...args) {
      (window as unknown as { sceneFrames: number }).sceneFrames++;
      return draw.apply(this, args);
    };
  });
  await page.goto('/?view=chat');
  await expect(page.locator('.spatial-scene.compact')).toHaveAttribute('data-renderer', 'webgl');
  await page.waitForTimeout(350);
  const frames = await page.evaluate(() => (window as unknown as { sceneFrames: number }).sceneFrames);
  await page.waitForTimeout(400);
  expect(await page.evaluate(() => (window as unknown as { sceneFrames: number }).sceneFrames)).toBe(frames);
  await page.locator('.spatial-scene.compact canvas').evaluate((element) => {
    (element as HTMLCanvasElement).getContext('webgl')?.getExtension('WEBGL_lose_context')?.loseContext();
  });
  await expect(page.locator('.spatial-scene.compact')).toHaveAttribute('data-renderer', 'ambient');
  await expect(page.locator('.convo-open-line')).toBeVisible();
  await page.getByRole('button', { name: 'Themes', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Theme-Studio' })).toBeVisible();
});

test('a rendered room can be chosen behind the glass, persists and can be removed', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/?view=chat');
  // Default look: Graphite Atelier, so its room is already behind the glass.
  await expect(page.locator('html')).toHaveAttribute('data-environment', 'graphite');
  const picture = page.locator('.scene-environment[data-environment="graphite"] img');
  await expect(picture).toHaveCount(1);
  await expect.poll(() => picture.evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth)).toBe(1600);
  await page.getByRole('button', { name: 'Themes', exact: true }).click();
  const editor = page.getByRole('dialog', { name: 'Theme-Studio' });
  await editor.getByRole('tab', { name: 'Szene', exact: true }).click();
  const rooms = editor.getByRole('radiogroup', { name: 'Umgebung' });
  await expect(rooms.getByRole('radio')).toHaveCount(7);
  await expect(rooms.getByRole('radio', { name: 'Graphite Atelier', exact: true })).toHaveAttribute('aria-checked', 'true');
  await expect(editor.getByText(/Final · Blender 4\.5/)).toBeVisible();
  // Any room can go behind any look; choosing one forks the built-in like every other edit.
  await rooms.getByRole('radio', { name: 'Porcelain', exact: true }).click();
  await expect(page.locator('html')).toHaveAttribute('data-environment', 'porcelain');
  await expect(page.locator('.scene-environment[data-environment="porcelain"] img')).toHaveCount(1);
  await expect(editor.getByRole('status')).toContainText('Kopie');
  await expect(editor.getByText(/heller Raum hinter einem dunklen Look/)).toBeVisible();
  // Keyboard: the room group is a roving radiogroup like every other choice.
  await rooms.getByRole('radio', { name: 'Porcelain', exact: true }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('html')).toHaveAttribute('data-environment', 'graphite');
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('html')).toHaveAttribute('data-environment', 'daylight');
  await page.waitForTimeout(350); // Existing debounced localStorage write.
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-environment', 'daylight');
  await expect(page.locator('.scene-environment[data-environment="daylight"] img')).toHaveCount(1);
  await page.getByRole('button', { name: 'Themes', exact: true }).click();
  await editor.getByRole('tab', { name: 'Szene', exact: true }).click();
  await rooms.getByRole('radio', { name: 'Kein Raum', exact: true }).click();
  await expect(page.locator('.scene-environment')).toHaveCount(0);
  await expect(page.locator('html')).toHaveAttribute('data-environment', 'none');
  // A stored theme naming an unknown room loses the field visibly instead of rendering a broken picture.
  await page.evaluate(() => {
    const raw = JSON.parse(localStorage.getItem('daedalus-themes') || '[]') as Array<{ scene?: Record<string, unknown> }>;
    if (raw[0]?.scene) raw[0].scene.environment = 'lava-lamp';
    localStorage.setItem('daedalus-themes', JSON.stringify(raw));
  });
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-environment', 'none');
  await expect(page.locator('.scene-environment')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('an empty conversation is one workspace pane, with the rail and sculpture in their places', async ({ page }) => {
  // Room look (default): invitation and suggestions sit on a glass pane.
  await page.goto('/?view=chat');
  const pane = page.locator('.convo-open');
  await expect(pane).toBeVisible();
  // React re-renders the invitation once the project fixture arrives; a node
  // measured in that instant is detached and reports empty computed styles.
  // Poll until the pane is attached and styled before reading it.
  const readPane = () => pane.evaluate((el) => {
    const s = getComputedStyle(el);
    // The headless shell reports an empty computed backdrop-filter, so the
    // blur is read from the glass rule that matches this pane instead.
    const declaredBlur = [...document.styleSheets].some((sheet) => {
      try {
        return [...sheet.cssRules].some((rule) =>
          rule instanceof CSSStyleRule && rule.selectorText.includes('.convo-open') && el.matches(rule.selectorText) &&
          /blur\(/.test(rule.style.getPropertyValue('backdrop-filter') + rule.style.getPropertyValue('-webkit-backdrop-filter')));
      } catch { return false; }
    });
    return {
      background: s.backgroundColor,
      image: s.backgroundImage,
      declaredBlur,
      // An engine without backdrop-filter drops the declaration from the CSSOM;
      // there the pane is still a pane (fill, edge, shadow), only unfrosted.
      canBlur: CSS.supports('backdrop-filter', 'blur(1px)') || CSS.supports('-webkit-backdrop-filter', 'blur(1px)'),
      border: parseFloat(s.borderTopWidth),
      shadow: s.boxShadow,
      overflow: s.overflow,
      attached: el.isConnected && s.borderTopWidth !== ''
    };
  });
  await expect.poll(async () => (await readPane()).attached, { message: 'invitation pane attached and styled' }).toBe(true);
  const paneStyle = await readPane();
  expect(paneStyle.background === 'rgba(0, 0, 0, 0)' && paneStyle.image === 'none').toBe(false);
  expect(paneStyle.border).toBeGreaterThan(0);
  expect(paneStyle.shadow).not.toBe('none');
  if (paneStyle.canBlur) expect(paneStyle.declaredBlur).toBe(true);
  expect(paneStyle.overflow).toBe('hidden');
  const headline = page.locator('.convo-open-line');
  await expect(headline).toHaveText(/Woran arbeiten wir/);
  await expect.poll(() => headline.evaluate((el) => parseFloat(getComputedStyle(el).fontSize))).toBeLessThanOrEqual(40);
  // The rail hugs its content on an empty thread instead of filling the row.
  const rail = await page.locator('.talk-side').boundingBox();
  const body = await page.locator('.cockpit-body.talk').boundingBox();
  expect(rail!.height).toBeLessThan(body!.height * 0.6);
  // Liquid Glass keeps its sculpture, whole, inside the pane — including at the
  // 800 px-high viewport that used to clip it.
  await page.setViewportSize({ width: 1440, height: 760 });
  await page.getByRole('button', { name: 'Themes', exact: true }).click();
  await page.getByRole('button', { name: 'Liquid Glass auswählen', exact: true }).click();
  await page.keyboard.press('Escape');
  const canvas = page.locator('.convo-open .spatial-scene.compact');
  await expect(canvas).toHaveAttribute('data-renderer', 'webgl');
  const paneBox = await pane.boundingBox();
  const canvasBox = await canvas.boundingBox();
  expect(canvasBox!.x).toBeGreaterThanOrEqual(paneBox!.x);
  expect(canvasBox!.x + canvasBox!.width).toBeLessThanOrEqual(paneBox!.x + paneBox!.width + 1);
  expect(canvasBox!.height).toBeGreaterThanOrEqual(120);
  await expect(page.locator('.composer')).toBeInViewport();
});
