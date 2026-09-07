import { expect, test } from '@playwright/test';
import { NOT_BUILT } from './_app';

/**
 * Live queue/activity counters are observations from one project's SSE stream.
 * Switching project must revoke that evidence until the new project's stream
 * produces a fresh observation; otherwise the cockpit briefly relabels one
 * project's active work as another project's work.
 */
test('project switch does not relabel previous live execution evidence', async ({ page }) => {
  await page.addInitScript(() => {
    type Listener = (event: MessageEvent<string>) => void;

    class ProjectEventSource {
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

        // `openEventStream` registers queue last, so all named handlers exist
        // here. Alpha has measured live work; beta deliberately has no stream
        // evidence yet.
        if (name === 'queue' && !this.emitted) {
          this.emitted = true;
          const project = new URL(this.url, location.origin).searchParams.get('project');
          if (project === 'switch-alpha') {
            queueMicrotask(() => this.emit('hello', { in_flight: 4, queue_depth: 9 }));
          }
        }
      }

      // Cockpit removes its error listener before closing the previous
      // project's stream. The fake must implement that EventSource lifecycle
      // surface too; otherwise a project switch throws in React effect cleanup
      // and the test mistakes a broken fake for a cockpit regression.
      removeEventListener(): void {}
      close(): void {}

      private emit(name: string, data: unknown): void {
        const event = new MessageEvent<string>(name, { data: JSON.stringify(data) });
        for (const listener of this.listeners.get(name) ?? []) listener(event);
      }
    }

    Object.defineProperty(window, 'EventSource', {
      configurable: true,
      writable: true,
      value: ProjectEventSource
    });
  });

  const projects = [
    { name: 'switch-alpha', repo_root: '/fixtures/switch-alpha', team: {}, reachable: true },
    { name: 'switch-beta', repo_root: '/fixtures/switch-beta', team: {}, reachable: true }
  ];

  await page.route('**/api/projects', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: null, warnings: [], projects }
  }));
  await page.route('**/api/structure**', async (route) => {
    const project = new URL(route.request().url()).searchParams.get('project') || 'switch-alpha';
    const module = project === 'switch-beta' ? 'beta/main.py' : 'alpha/core.ts';
    await route.fulfill({
      json: {
        ok: true,
        generated_at: '2026-09-07T08:00:00Z',
        project,
        warnings: [],
        structure: {
          backend: { tree_sitter: true, lizard: true },
          repo_root: `/fixtures/${project}`,
          n_files: 1,
          languages: {},
          totals: { unit_clusters: 0, window_clusters: 0, safety_fenced: 0 },
          hotspots: [],
          clones: [],
          window_clones: [],
          fan_in: [],
          graph: {
            nodes: [{ module, language: 'fixture', loc: 10, score: 1, churn: 0, fan_in: 0 }],
            edges: [],
            n_nodes_total: 1,
            n_edges_total: 0,
            n_edges_eligible: 0,
            n_edges_shown: 0,
            n_edges_offmap: 0
          }
        }
      }
    });
  });

  const res = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(res, 'the server did not answer GET / at all').not.toBeNull();
  expect(res!.status(), 'GET / did not come back 200').toBe(200);
  expect(await res!.text(), 'the built web app is missing').not.toMatch(NOT_BUILT);

  const status = page.locator('.statusline');
  await expect(page.locator('.cockpit'), 'the cockpit never mounted').toBeVisible({ timeout: 20_000 });
  await expect(status).toContainText('switch-alpha', { timeout: 20_000 });
  await expect(status).toContainText('Ausführung live · 4 aktiv · 9 wartend', { timeout: 20_000 });

  await page.locator('.scope-trigger').click();
  await page.getByRole('button', { name: 'switch-beta', exact: true }).click();

  await expect(status).toContainText('switch-beta', { timeout: 20_000 });
  await expect(status).toContainText('kein Ereignisstrom · Ausführungsstand unbekannt', { timeout: 20_000 });
  await expect(status).not.toContainText('4 aktiv');
  await expect(status).not.toContainText('9 wartend');
});
