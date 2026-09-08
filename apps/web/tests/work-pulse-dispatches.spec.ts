import { stubLiveProject } from './_live-fixtures';
import { expect, test } from '@playwright/test';
import { NOT_BUILT } from './_app';

/**
 * The JARVIS rail must name durable work that has not reported back yet, not
 * merely show an anonymous queue count. The identity comes from the canonical
 * conversation spine's `open_dispatches`; the live file-bus stream only tells
 * the card when that read should be refreshed.
 */
test('work rail prefers bound dispatch identity, shows bound execution evidence, keeps legacy fallback, and clears after a report', async ({ page }) => {
  await stubLiveProject(page, 'jarvis-project');
  let reported = false;

  await page.addInitScript(() => {
    localStorage.setItem('daedalus-cockpit-view', 'chat');
    localStorage.setItem('daedalus-thread:jarvis-project', 'conv_jarvis_abc12345');

    type Listener = (event: MessageEvent<string>) => void;
    type LiveWindow = Window & { __emitDaedalusLive?: (name: string, data: unknown) => void };

    class PulseEventSource {
      readonly url: string;
      onerror: ((event: Event) => void) | null = null;
      private listeners = new Map<string, Listener[]>();
      private helloSent = false;

      constructor(url: string | URL) {
        this.url = String(url);
        (window as LiveWindow).__emitDaedalusLive = (name, data) => this.emit(name, data);
      }

      addEventListener(name: string, listener: EventListenerOrEventListenerObject | null): void {
        if (!listener) return;
        const callback: Listener = (event) => {
          if (typeof listener === 'function') listener(event);
          else listener.handleEvent(event);
        };
        this.listeners.set(name, [...(this.listeners.get(name) ?? []), callback]);
        if (name === 'queue' && !this.helloSent) {
          this.helloSent = true;
          queueMicrotask(() => this.emit('hello', {
            in_flight: 1,
            queue_depth: 0,
            unread_count: 0,
            quarantined_count: 0,
            watcher_state: 'busy'
          }));
        }
      }

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
      value: PulseEventSource
    });
  });

  await page.route('**/api/projects', (route) => route.fulfill({
    json: {
      ok: true,
      generated_at: '',
      project: null,
      warnings: [],
      projects: [{ name: 'jarvis-project', repo_root: '/fixtures/jarvis-project', team: {}, reachable: true }]
    }
  }));

  await page.route('**/api/structure**', (route) => route.fulfill({
    json: {
      ok: true,
      generated_at: '2026-09-07T12:00:00Z',
      project: 'jarvis-project',
      warnings: [],
      structure: {
        backend: { tree_sitter: true, lizard: true },
        repo_root: '/fixtures/jarvis-project',
        n_files: 1,
        languages: {},
        totals: { unit_clusters: 0, window_clusters: 0, safety_fenced: 0 },
        hotspots: [],
        clones: [],
        window_clones: [],
        fan_in: [],
        graph: {
          nodes: [{ module: 'src/core.ts', language: 'typescript', loc: 10, score: 1, churn: 0, fan_in: 0 }],
          edges: [],
          n_nodes_total: 1,
          n_edges_total: 0,
          n_edges_eligible: 0,
          n_edges_shown: 0,
          n_edges_offmap: 0,
          truncated: false
        }
      }
    }
  }));

  await page.route('**/api/topology**', (route) => route.fulfill({
    json: {
      ok: true,
      generated_at: '',
      project: 'jarvis-project',
      warnings: [],
      topology: {
        available: false,
        graph_type: 'fixture',
        node_count: 1,
        edge_count: 0,
        connected_components: 1,
        method: 'none',
        reason: 'fixture',
        partition_a: [],
        partition_b: [],
        cut_edges: 0,
        conductance: 0,
        algebraic_connectivity: 0
      }
    }
  }));

  await page.route('**/api/governance**', (route) => route.fulfill({
    json: {
      ok: true,
      generated_at: '',
      project: 'jarvis-project',
      warnings: [],
      promotion_allowed: false,
      verdict: 'fixture',
      state: 'unknown',
      head: null,
      gates: [],
      blockers: []
    }
  }));

  await page.route('**/api/health**', (route) => route.fulfill({
    json: {
      ok: true,
      generated_at: '',
      project: null,
      warnings: [],
      health: {
        schema: 1,
        generated_at: '',
        states: ['working', 'present', 'degraded', 'absent', 'unknown'],
        counts: { working: 0, present: 0, degraded: 0, absent: 0, unknown: 0 },
        verdict: 2,
        not_proven: [],
        subsystems: []
      }
    }
  }));

  await page.route('**/api/runtimes/status**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: null, warnings: [], runtimes: [] }
  }));

  await page.route('**/api/conversations/conv_jarvis_abc12345**', (route) => route.fulfill({
    json: {
      ok: true,
      generated_at: '',
      project: 'jarvis-project',
      warnings: [],
      conversation: {
        conversation_id: 'conv_jarvis_abc12345',
        exists: true,
        project_binding: { state: 'bound', project: 'jarvis-project', row_count: 2 },
        turn_count: 2,
        narrative: '',
        turns_returned: 2,
        turns: [
          {
            id: 42,
            project: 'jarvis-project',
            user_message: 'Legacy-Auftrag ausführen.',
            assistant_text: 'Ich kann das als lokalen Task ausführen.',
            intent: 'enqueue',
            provider_used: 'deterministic',
            proposed_action: {
              kind: 'queue_task',
              args: {
                project: 'jarvis-project',
                objective: 'Legacy-Auftrag',
                lane: 'legacy_lane',
                agent: 'legacy-agent-must-not-render',
                runtime_id: 'legacy-runtime-must-not-render'
              },
              requires_confirmation: true
            }
          },
          {
            id: 99,
            project: 'other-project',
            user_message: 'Fremdes Projekt',
            assistant_text: 'Nicht Teil dieses Projekts.',
            intent: 'enqueue',
            provider_used: 'deterministic',
            proposed_action: {
              kind: 'queue_task',
              args: { project: 'other-project', objective: 'Fremdes Projekt ausführen', lane: 'codex' },
              requires_confirmation: true
            }
          }
        ],
        open_dispatches: reported ? [] : [
          {
            link: {
              id: 501,
              conversation_id: 'conv_jarvis_abc12345',
              turn_id: 7,
              dispatch_ref: '20260907T120000Z_parser_123456789abcdef',
              kind: 'queue_task',
              created_ts: '2026-09-07T12:00:00Z'
            },
            latest: {
              id: 501,
              dispatch_link_id: 501,
              ts: '2026-09-07T12:00:00Z',
              lifecycle: 'dispatched',
              summary: 'dispatched',
              detail: {
                schema: 'conversation.dispatch.identity.v1',
                project: 'jarvis-project',
                objective: 'Parser härten',
                lane: 'local_only',
                work_item_id: 'work-parser-42',
                attempt_id: 'attempt-parser-7',
                agent: 'qa-critic',
                tool: 'read-file',
                runtime_id: 'claude-code',
                phase: 'executing'
              }
            }
          },
          {
            link: {
              id: 502,
              conversation_id: 'conv_jarvis_abc12345',
              turn_id: 42,
              dispatch_ref: 'legacy_dispatch',
              kind: 'queue_task',
              created_ts: '2026-09-07T11:59:00Z'
            },
            latest: {
              id: 502,
              dispatch_link_id: 502,
              ts: '2026-09-07T11:59:00Z',
              lifecycle: 'dispatched',
              summary: 'dispatched'
            }
          },
          {
            link: {
              id: 503,
              conversation_id: 'conv_jarvis_abc12345',
              turn_id: 99,
              dispatch_ref: 'foreign_dispatch',
              kind: 'queue_task',
              created_ts: '2026-09-07T12:01:00Z'
            },
            latest: {
              id: 503,
              dispatch_link_id: 503,
              ts: '2026-09-07T12:01:00Z',
              lifecycle: 'dispatched',
              summary: 'dispatched',
              detail: {
                schema: 'conversation.dispatch.identity.v1',
                project: 'other-project',
                objective: 'Fremdes Projekt ausführen',
                lane: 'codex'
              }
            }
          },
          {
            link: {
              id: 504,
              conversation_id: 'conv_jarvis_abc12345',
              turn_id: 7,
              dispatch_ref: 'corrupt_dispatch',
              kind: 'queue_task',
              created_ts: '2026-09-07T12:02:00Z'
            },
            latest: {
              id: 504,
              dispatch_link_id: 504,
              ts: '2026-09-07T12:02:00Z',
              lifecycle: 'dispatched',
              summary: 'dispatched',
              detail: {
                schema: 'conversation.dispatch.identity.v1',
                objective: 'Ohne Projekt darf das nicht erscheinen'
              }
            }
          },
          {
            link: {
              id: 505,
              conversation_id: 'conv_jarvis_abc12345',
              turn_id: 42,
              dispatch_ref: 'future_schema_dispatch',
              kind: 'queue_task',
              created_ts: '2026-09-07T12:03:00Z'
            },
            latest: {
              id: 505,
              dispatch_link_id: 505,
              ts: '2026-09-07T12:03:00Z',
              lifecycle: 'dispatched',
              summary: 'dispatched',
              detail: {
                schema: 'conversation.dispatch.identity.v2',
                project: 'jarvis-project',
                objective: 'Neue Schema-Evidenz',
                lane: 'future_lane'
              }
            }
          }
        ]
      }
    }
  }));

  const res = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(res, 'the server did not answer GET / at all').not.toBeNull();
  expect(res!.status(), 'GET / did not come back 200').toBe(200);
  expect(await res!.text(), 'the built web app is missing').not.toMatch(NOT_BUILT);

  await expect(page.locator('.cockpit'), 'the cockpit never mounted').toBeVisible({ timeout: 20_000 });
  await page.getByRole('button', { name: /^Arbeit/ }).click();
  const pulse = page.locator('.work');
  await expect(pulse.locator('.work-section.live .work-count')).toHaveText('2', { timeout: 20_000 });
  await expect(pulse).toContainText('Parser härten');
  await expect(pulse).toContainText('Lane local_only');
  await expect(pulse).toContainText('noch kein Bericht');
  await expect(pulse).toContainText('gebundene Evidenz');
  await expect(pulse).toContainText('aus Chatverlauf rekonstruiert');
  await expect(pulse).toContainText('1 projektgebundene Dispatch-Evidenzen sind nicht sicher interpretierbar');
  await expect(pulse).toContainText('Agent qa-critic');
  await expect(pulse).toContainText('Tool read-file');
  await expect(pulse).toContainText('Runtime claude-code');
  await expect(pulse).toContainText('Phase executing');
  await expect(pulse).toContainText('WorkItem work-parser-42');
  await expect(pulse).toContainText('Attempt attempt-parser-7');
  await expect(pulse).toContainText('Legacy-Auftrag');
  await expect(pulse).toContainText('Lane legacy_lane');
  await expect(pulse).not.toContainText('legacy-agent-must-not-render');
  await expect(pulse).not.toContainText('legacy-runtime-must-not-render');
  await expect(pulse).not.toContainText('Fremdes Projekt ausführen');
  await expect(pulse).not.toContainText('foreign_dispatch');
  await expect(pulse).not.toContainText('Ohne Projekt darf das nicht erscheinen');
  await expect(pulse).not.toContainText('corrupt_dispatch');
  await expect(pulse).not.toContainText('future_schema_dispatch');
  await expect(pulse).not.toContainText('future_lane');

  reported = true;
  await page.evaluate(() => {
    const live = window as Window & { __emitDaedalusLive?: (name: string, data: unknown) => void };
    live.__emitDaedalusLive?.('report', {
      name: 'parser.report.json',
      status: 'working',
      lane: 'local_only',
      project: 'jarvis-project',
      summary: 'Parser gehärtet'
    });
  });

  await expect(pulse).toContainText('Keine offenen Aufträge im aktuellen Verlauf', { timeout: 20_000 });
  await expect(pulse.locator('.work-section.past')).toContainText('parser.report.json');
  await expect(pulse).toContainText('Parser gehärtet');
});
