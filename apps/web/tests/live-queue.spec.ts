import { expect, test } from '@playwright/test';
import { NOT_BUILT } from './_app';

/**
 * The cockpit must follow the queue event's canonical `queue_depth` field, not
 * keep the `hello` snapshot forever.  A tiny in-browser EventSource keeps this
 * test about the projection contract instead of filesystem/watcher timing.
 */
test('queue events refresh the live waiting count', async ({ page }) => {
  await page.addInitScript(() => {
    type Listener = (event: MessageEvent<string>) => void;

    class QueueEventSource {
      readonly url: string;
      onerror: ((event: Event) => void) | null = null;
      private listeners = new Map<string, Listener[]>();
      private emitted = false;

      constructor(url: string | URL) {
        this.url = String(url);
      }

      addEventListener(name: string, listener: EventListenerOrEventListenerObject | null): void {
        if (!listener) return;
        const callback: Listener = (event) => {
          if (typeof listener === 'function') listener(event);
          else listener.handleEvent(event);
        };
        this.listeners.set(name, [...(this.listeners.get(name) ?? []), callback]);

        // `openEventStream` registers queue last.  Emitting after that listener
        // exists guarantees the hello snapshot and the subsequent queue update
        // travel through the exact same adapter the real browser uses.
        if (name === 'queue' && !this.emitted) {
          this.emitted = true;
          queueMicrotask(() => {
            this.emit('hello', { in_flight: 0, queue_depth: 1 });
            this.emit('queue', { queue_depth: 7 });
          });
        }
      }

      close(): void {}

      private emit(name: string, data: unknown): void {
        const event = new MessageEvent<string>(name, { data: JSON.stringify(data) });
        for (const listener of this.listeners.get(name) ?? []) listener(event);
      }
    }

    Object.defineProperty(window, 'EventSource', {
      configurable: true,
      writable: true,
      value: QueueEventSource
    });
  });

  const res = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(res, 'the server did not answer GET / at all').not.toBeNull();
  expect(res!.status(), 'GET / did not come back 200').toBe(200);
  expect(await res!.text(), 'the built web app is missing').not.toMatch(NOT_BUILT);

  await expect(page.locator('.cockpit'), 'the cockpit never mounted').toBeVisible({ timeout: 20_000 });
  await expect(page.locator('.statusline')).toContainText('Ausführung live · 0 aktiv · 7 wartend', { timeout: 20_000 });
  await expect(page.locator('.statusline')).not.toContainText('1 wartend');
});
