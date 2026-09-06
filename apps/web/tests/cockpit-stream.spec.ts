import { expect, test, type Page, type Route } from '@playwright/test';
import { NOT_BUILT } from './_app';

const SSE_HEADERS = {
  'Content-Type': 'text/event-stream; charset=utf-8',
  'Cache-Control': 'no-cache',
  Connection: 'close'
};

async function openCockpit(page: Page): Promise<void> {
  const res = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(res, 'the server did not answer GET / at all').not.toBeNull();
  expect(res!.status(), 'GET / did not come back 200').toBe(200);
  expect(await res!.text(), 'apps/web/dist is missing or empty').not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit'), 'the cockpit never mounted').toBeVisible({ timeout: 20_000 });
  await page.getByRole('button', { name: /Gespräch/ }).click();
  await expect(page.getByLabel('Nachricht an Ikarus')).toBeVisible({ timeout: 10_000 });
}

function blockUnexpectedReplay(counter: { calls: number }) {
  return async (route: Route) => {
    counter.calls += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        project: 'daedalus',
        intent: 'chat',
        assistant: 'unexpected blocking replay',
        provider_used: 'deterministic',
        delivery_mode: 'blocking',
        stream_interrupted: false
      })
    });
  };
}

test('shipping cockpit keeps an interrupted stream terminal and never replays it with POST', async ({ page }) => {
  const replay = { calls: 0 };

  await page.route('**/api/ikarus/ask', blockUnexpectedReplay(replay));
  await page.route('**/api/conversations', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, conversation_id: 'conv_20260906T120000Z_deadbeef' })
    });
  });
  await page.route('**/api/runtimes/status', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, runtimes: [] })
    });
  });
  await page.route(/\/api\/ikarus\/stream\?/, async (route) => {
    await route.fulfill({
      status: 200,
      headers: SSE_HEADERS,
      body:
        'event: start\ndata: {"intent":"chat","provider_used":"claude_code_cli"}\n\n' +
        'event: delta\ndata: {"text":"partial answer"}\n\n'
    });
  });

  await openCockpit(page);
  const composer = page.getByLabel('Nachricht an Ikarus');
  await composer.fill('tell me something that streams');
  await page.getByRole('button', { name: 'Senden' }).click();

  await expect(page.getByText('partial answer', { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('FEHLGESCHLAGEN', { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole('button', { name: 'Antwort stoppen' })).toHaveCount(0);
  await expect(page.getByRole('region', { name: 'Vorgeschlagene Aktion' })).toHaveCount(0);
  await page.waitForTimeout(750);
  expect(replay.calls, 'an interrupted SSE turn was replayed through /api/ikarus/ask').toBe(0);
});
