import { expect, test, type Page, type Route } from '@playwright/test';
import { openApp } from './_app';

const SSE_HEADERS = {
  'Content-Type': 'text/event-stream; charset=utf-8',
  'Cache-Control': 'no-cache',
  'Connection': 'close',
};

async function submit(page: Page, message: string): Promise<void> {
  const composer = page.getByLabel('Ask Ikarus');
  await composer.fill(message);
  await page.getByRole('button', { name: 'Send' }).click();
}

function blockUnexpectedReplay(counter: { calls: number }) {
  return async (route: Route) => {
    counter.calls += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        project: 'sunny_garden',
        intent: 'chat',
        assistant: 'unexpected replay',
        provider_used: 'deterministic',
        delivery_mode: 'blocking',
        stream_interrupted: false,
      }),
    });
  };
}

test('classic composer only arms for sendable text and ignores IME confirmation Enter', async ({ page }) => {
  const requests = { stream: 0, ask: 0 };
  await page.route('**/api/ikarus/ask', async (route) => {
    requests.ask += 1;
    await route.abort();
  });
  await page.route(/\/api\/ikarus\/stream\?/, async (route) => {
    requests.stream += 1;
    await route.abort();
  });

  await openApp(page);
  const composer = page.getByLabel('Ask Ikarus');
  const send = page.getByRole('button', { name: 'Send' });

  await expect(send).toBeDisabled();
  await composer.fill('   ');
  await expect(send).toBeDisabled();

  await composer.fill('入力中');
  await expect(send).toBeEnabled();
  await composer.evaluate((element) => {
    element.dispatchEvent(new KeyboardEvent('keydown', {
      key: 'Enter',
      code: 'Enter',
      bubbles: true,
      cancelable: true,
      isComposing: true,
    }));
  });

  await expect(composer).toHaveValue('入力中');
  expect(requests.stream + requests.ask).toBe(0);
});

test('classic keeps a partial stream halted and never replays it with POST', async ({ page }) => {
  const replay = { calls: 0 };
  await page.route('**/api/ikarus/ask', blockUnexpectedReplay(replay));
  await page.route(/\/api\/ikarus\/stream\?/, async (route) => {
    await route.fulfill({
      status: 200,
      headers: SSE_HEADERS,
      body:
        'event: start\ndata: {"intent":"chat","provider_used":"ollama_http"}\n\n' +
        'event: delta\ndata: {"text":"partial answer"}\n\n',
    });
  });

  await openApp(page);
  await submit(page, 'tell me something that streams');

  await expect(page.getByText('partial answer', { exact: true })).toBeVisible();
  await expect(page.getByText('halted', { exact: true })).toBeVisible();
  await expect.poll(() => replay.calls).toBe(0);
});

test('classic suppresses action controls on an interrupted final', async ({ page }) => {
  const replay = { calls: 0 };
  await page.route('**/api/ikarus/ask', blockUnexpectedReplay(replay));
  await page.route(/\/api\/ikarus\/stream\?/, async (route) => {
    const final = {
      ok: true,
      project: 'sunny_garden',
      intent: 'enqueue',
      assistant: 'This incomplete turn must not expose an action.',
      provider_used: 'deterministic',
      delivery_mode: 'stream',
      stream_interrupted: true,
      action: {
        kind: 'queue_task',
        args: { project: 'sunny_garden', objective: 'unsafe duplicate', lane: 'local_only' },
        requires_confirmation: true,
      },
    };
    await route.fulfill({
      status: 200,
      headers: SSE_HEADERS,
      body: `event: final\ndata: ${JSON.stringify(final)}\n\n`,
    });
  });

  await openApp(page);
  await submit(page, 'build an interrupted thing');

  await expect(page.getByText('This incomplete turn must not expose an action.', { exact: true })).toBeVisible();
  await expect(page.getByText('halted', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Confirm' })).toHaveCount(0);
  await expect(page.getByText('Queue task', { exact: true })).toHaveCount(0);
  await expect.poll(() => replay.calls).toBe(0);
});
