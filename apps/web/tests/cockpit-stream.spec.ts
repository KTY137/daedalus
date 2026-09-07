import { readFileSync } from 'node:fs';
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

test('shipping cockpit has no dormant blocking replay closure', () => {
  const source = readFileSync(new URL('../src/cockpit/Conversation.tsx', import.meta.url), 'utf8');

  expect(source, 'the shipping Cockpit reintroduced the blocking Ikarus adapter').not.toMatch(/\baskIkarus\s*\(/);
  expect(source, 'the shipping Cockpit reintroduced the old backend-down replay branch').not.toMatch(/\bisBackendDown\s*\(/);
  expect(source, 'the shipping Cockpit stopped using the terminal streaming adapter').toMatch(/\bstreamIkarus\s*\(/);
});

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


test('shipping Stop cancels the exact SSE request and only claims completion from evidence', async ({ page }) => {
  const replay = { calls: 0 };
  let cancelBody: { request_id?: string } | undefined;

  await page.addInitScript(() => {
    (window as unknown as { __ikarusSseUrls: string[] }).__ikarusSseUrls = [];
    class HeldEventSource {
      url: string;
      onerror: ((event: Event) => unknown) | null = null;
      constructor(url: string | URL) {
        this.url = String(url);
        (window as unknown as { __ikarusSseUrls: string[] }).__ikarusSseUrls.push(this.url);
      }
      addEventListener() { /* intentionally held open until the UI cancels */ }
      close() { /* observation closed; the POST is the backend stop */ }
    }
    Object.defineProperty(window, 'EventSource', { value: HeldEventSource, configurable: true });
  });

  await page.route('**/api/ikarus/ask', blockUnexpectedReplay(replay));
  await page.route('**/api/conversations', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, conversation_id: 'conv_20260906T230000Z_stopbeef' })
    });
  });
  await page.route('**/api/runtimes/status', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, runtimes: [] }) });
  });
  await page.route('**/api/ikarus/cancel', async (route) => {
    cancelBody = route.request().postDataJSON() as { request_id?: string };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        generated_at: '2026-09-06T21:00:00Z',
        project: null,
        warnings: [],
        cancellation: {
          request_id: cancelBody.request_id,
          active: true,
          newly_cancelled: true,
          request_finished: true
        }
      })
    });
  });

  await openCockpit(page);
  await page.getByLabel('Nachricht an Ikarus').fill('keep working until I stop you');
  await page.getByRole('button', { name: 'Senden' }).click();
  const stop = page.getByRole('button', { name: 'Antwort stoppen' });
  await expect(stop).toBeVisible({ timeout: 10_000 });
  await stop.click();

  await expect.poll(() => cancelBody?.request_id || '').not.toBe('');
  const streamUrl = await page.evaluate(() => {
    const urls = (window as unknown as { __ikarusSseUrls: string[] }).__ikarusSseUrls;
    return [...urls].reverse().find((url) => url.includes('/api/ikarus/stream?')) || '';
  });
  const streamedRequestId = new URL(streamUrl, 'http://localhost').searchParams.get('request_id');
  expect(streamedRequestId).toBeTruthy();
  expect(cancelBody?.request_id).toBe(streamedRequestId);

  await expect(page.getByText('ABGEBROCHEN', { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('Request beendet · Remote-Termination nicht bewiesen', { exact: true })).toBeVisible();
  await expect(page.getByText('STOP ANGEFORDERT', { exact: true })).toHaveCount(0);
  await expect(page.getByText('STOP UNBESTÄTIGT', { exact: true })).toHaveCount(0);
  expect(replay.calls, 'Stop must never replay the turn through /api/ikarus/ask').toBe(0);
});


test('shipping Stop surfaces positive local child exit without claiming remote termination', async ({ page }) => {
  let cancelBody: { request_id?: string } | undefined;

  await page.addInitScript(() => {
    class HeldEventSource {
      onerror: ((event: Event) => unknown) | null = null;
      constructor(_url: string | URL) { /* held open until the UI cancels */ }
      addEventListener() { /* intentionally held open */ }
      close() { /* observation closed; the POST is the backend stop */ }
    }
    Object.defineProperty(window, 'EventSource', { value: HeldEventSource, configurable: true });
  });

  await page.route('**/api/conversations', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true, conversation_id: 'conv_20260907T040000Z_childbeef' })
    });
  });
  await page.route('**/api/runtimes/status', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, runtimes: [] }) });
  });
  await page.route('**/api/ikarus/cancel', async (route) => {
    cancelBody = route.request().postDataJSON() as { request_id?: string };
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        generated_at: '2026-09-07T04:00:00Z',
        project: null,
        warnings: [],
        cancellation: {
          request_id: cancelBody.request_id,
          active: true,
          newly_cancelled: true,
          request_finished: true,
          subprocess: {
            request_id: cancelBody.request_id,
            cancellation_requested: true,
            was_running: true,
            terminate_sent: true,
            kill_sent: false,
            process_exited: true,
            returncode: -15
          }
        }
      })
    });
  });

  await openCockpit(page);
  await page.getByLabel('Nachricht an Ikarus').fill('run a local CLI until I stop it');
  await page.getByRole('button', { name: 'Senden' }).click();
  const stop = page.getByRole('button', { name: 'Antwort stoppen' });
  await expect(stop).toBeVisible({ timeout: 10_000 });
  await stop.click();

  await expect.poll(() => cancelBody?.request_id || '').not.toBe('');
  await expect(page.getByText('ABGEBROCHEN', { exact: true })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText('lokaler CLI-Prozess beendet · Remote-Termination nicht bewiesen', { exact: true })).toBeVisible();
  await expect(page.getByText('Request beendet · Remote-Termination nicht bewiesen', { exact: true })).toHaveCount(0);
});
