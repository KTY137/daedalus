import { expect, test } from '@playwright/test';
import { NOT_BUILT, collect } from './_app';

test('the sole Cockpit implementation mounts and talks to its serving API', async ({ page }) => {
  const seen = collect(page);
  await page.route(
    (url) => url.pathname.startsWith('/api/'),
    (route) => route.fulfill({
      status: 200,
      json: { ok: true, generated_at: '', project: null, warnings: [], projects: [] }
    })
  );
  const response = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(response!.status()).toBe(200);
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
  await expect(page.locator('#root > *')).toHaveCount(1);
  await expect(page.getByRole('navigation', { name: 'Ansicht', exact: true })).toBeVisible();
  await expect.poll(() => seen.api.length, { timeout: 30_000 }).toBeGreaterThan(0);
  expect(seen.pageErrors).toEqual([]);
});

test('native Chromium EventSource reaches the guarded legacy stream without an Origin header', async ({ page }) => {
  await page.goto('/', { waitUntil: 'domcontentloaded' });
  const probe = 'origin-guard-browser-probe';
  const requestPromise = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname === '/api/ikarus/stream' && url.searchParams.get('message') === probe;
  });
  const responsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === '/api/ikarus/stream' && url.searchParams.get('message') === probe;
  });

  const browserResult = page.evaluate((message) => new Promise<string>((resolve) => {
    const source = new EventSource(`/api/ikarus/stream?message=${encodeURIComponent(message)}`);
    source.onopen = () => {
      source.close();
      resolve('open');
    };
    source.onerror = () => {
      source.close();
      resolve('error');
    };
  }), probe);

  const [request, response, result] = await Promise.all([
    requestPromise,
    responsePromise,
    browserResult,
  ]);
  const headers = await request.allHeaders();
  expect(headers.origin).toBeUndefined();
  expect(headers['sec-fetch-site']).toBe('same-origin');
  // 400 is the post-guard "project and message are required" validation.
  // A 403 here means the browser-compatible admission path regressed.
  expect(response.status()).toBe(400);
  expect(result).toBe('error');
});
