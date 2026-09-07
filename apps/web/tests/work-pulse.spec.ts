import { expect, test } from '@playwright/test';
import { NOT_BUILT } from './_app';

/**
 * The chat rail must consume the work facts already carried by the canonical
 * project event stream instead of inventing a second task store. A controlled
 * EventSource makes watcher/attention/report evidence deterministic, proves
 * the bridge's real watcher vocabulary, and pins bounded recent-report history.
 */
test('work pulse projects canonical watcher and recent-report evidence honestly', async ({ page }) => {
  await page.addInitScript(() => {
    type Listener = EventListenerOrEventListenerObject;

    class WorkEventSource {
      readonly url: string;
      onerror: ((event: Event) => void) | null = null;
      private listeners = new Map<string, Listener[]>();
      private emitted = false;

      constructor(url: string | URL) {
        this.url = String(url);
        (window as unknown as { __workSource?: WorkEventSource }).__workSource = this;
      }

      addEventListener(name: string, listener: Listener | null): void {
        if (!listener) return;
        this.listeners.set(name, [...(this.listeners.get(name) ?? []), listener]);

        // openEventStream registers queue last, so every named handler exists.
        if (name === 'queue' && !this.emitted) {
          this.emitted = true;
          queueMicrotask(() => {
            this.emit('hello', {
              in_flight: true,
              queue_depth: 3,
              unread_count: 2,
              quarantined_count: 1,
              watcher_state: 'busy',
              latest_report: {
                id: 'report-7',
                name: 'verify-ui',
                lane: 'local_only',
                agent: 'qa-critic',
                status: 'done',
                summary: '52 browser checks green',
                created_at: '2026-09-07T09:40:00Z'
              }
            });
          });
        }
      }

      removeEventListener(): void {}
      close(): void {}

      fail(): void {
        const event = new Event('error');
        // useEventSource observes the EventSource.onerror property. A fake that
        // only dispatches addEventListener callbacks cannot model disconnects.
        this.onerror?.(event);
        this.emitEvent('error', event);
      }

      emit(name: string, data: unknown): void {
        this.emitEvent(name, new MessageEvent<string>(name, { data: JSON.stringify(data) }));
      }

      private emitEvent(name: string, event: Event): void {
        for (const listener of this.listeners.get(name) ?? []) {
          if (typeof listener === 'function') listener(event);
          else listener.handleEvent(event);
        }
      }
    }

    Object.defineProperty(window, 'EventSource', {
      configurable: true,
      writable: true,
      value: WorkEventSource
    });
  });

  const res = await page.goto('/?view=chat', { waitUntil: 'domcontentloaded' });
  expect(res, 'the server did not answer GET / at all').not.toBeNull();
  expect(res!.status(), 'GET / did not come back 200').toBe(200);
  expect(await res!.text(), 'the built web app is missing').not.toMatch(NOT_BUILT);

  await expect(page.locator('.cockpit'), 'the cockpit never mounted').toBeVisible({ timeout: 20_000 });
  const pulse = page.locator('[aria-label="Live-Arbeit"]');
  await expect(pulse).toBeVisible({ timeout: 20_000 });
  await expect(pulse).toContainText('Ausführung live · 1 aktiv · 3 wartend');
  await expect(pulse).toContainText('Wächter: arbeitet');
  await expect(pulse).toContainText('3 braucht Aufmerksamkeit · 2 ungelesen · 1 Quarantäne');
  await expect(pulse).toContainText('Zuletzt berichtet: verify-ui · done · Agent qa-critic · local_only');
  await expect(pulse).toContainText('52 browser checks green');

  // A partially populated hello is incomplete evidence, not proof that the
  // missing counter is zero. Keep the known side visible but label the gap.
  await page.evaluate(() => {
    (window as unknown as { __workSource?: { emit(name: string, data: unknown): void } }).__workSource?.emit('hello', {
      in_flight: true,
      queue_depth: 3,
      unread_count: 0,
      watcher_state: 'busy'
    });
  });
  await expect(pulse).toContainText('Aufmerksamkeitsstatus unvollständig · 0 ungelesen · Quarantäne unbekannt');
  await expect(pulse).not.toContainText('Nichts als ungelesen oder quarantiniert gemeldet');

  await page.evaluate(() => {
    (window as unknown as { __workSource?: { emit(name: string, data: unknown): void } }).__workSource?.emit('hello', {
      in_flight: true,
      queue_depth: 3,
      quarantined_count: 0,
      watcher_state: 'busy'
    });
  });
  await expect(pulse).toContainText('Aufmerksamkeitsstatus unvollständig · ungelesen unbekannt · 0 Quarantäne');
  await expect(pulse).not.toContainText('Nichts als ungelesen oder quarantiniert gemeldet');

  // Restore a complete snapshot so the remaining report/disconnect assertions
  // keep proving the same bounded recent-history and last-known-state contract.
  await page.evaluate(() => {
    (window as unknown as { __workSource?: { emit(name: string, data: unknown): void } }).__workSource?.emit('hello', {
      in_flight: true,
      queue_depth: 3,
      unread_count: 2,
      quarantined_count: 1,
      watcher_state: 'busy',
      latest_report: {
        id: 'report-7',
        name: 'verify-ui',
        lane: 'local_only',
        agent: 'qa-critic',
        status: 'done',
        summary: '52 browser checks green',
        created_at: '2026-09-07T09:40:00Z'
      }
    });
  });
  await expect(pulse).toContainText('3 braucht Aufmerksamkeit · 2 ungelesen · 1 Quarantäne');

  await page.evaluate(() => {
    (window as unknown as { __workSource?: { emit(name: string, data: unknown): void } }).__workSource?.emit('report', {
      id: 'report-8',
      name: 'lint-core',
      lane: 'local_only',
      agent: 'typescript-lint',
      status: 'done',
      summary: 'Typen sauber',
      created_at: '2026-09-07T09:41:00Z'
    });
  });
  await expect(pulse).toContainText('Zuletzt berichtet: lint-core · done · Agent typescript-lint · local_only · Typen sauber');
  await expect(pulse).toContainText('Davor: verify-ui · done · Agent qa-critic · local_only · 52 browser checks green');

  await page.evaluate(() => {
    (window as unknown as { __workSource?: { emit(name: string, data: unknown): void } }).__workSource?.emit('heartbeat', {
      in_flight: true,
      watcher_state: 'wedged'
    });
  });
  await expect(pulse).toContainText('Wächter: möglicherweise festgefahren');

  await page.evaluate(() => {
    (window as unknown as { __workSource?: { fail(): void } }).__workSource?.fail();
  });
  await expect(pulse).toContainText('letzter beobachteter Stand');
  await expect(pulse).toContainText('beim letzten Verbinden gezählt');
  await expect(page.locator('.statusline')).toContainText('Ereignisstrom getrennt · letzter Stand: 1 aktiv · 3 wartend');
});
