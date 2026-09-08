import { expect, test } from '@playwright/test';
import { NOT_BUILT } from './_app';

/**
 * Terminal report attribution is evidence, not display context. A report that
 * does not name the selected project exactly must not become that project's
 * "latest report" merely because it arrived on its EventSource connection.
 */
test('terminal reports require exact project evidence before entering Work Pulse', async ({ page }) => {
  await page.addInitScript(() => {
    type Listener = (event: MessageEvent<string>) => void;

    class ProjectEventSource {
      readonly url: string;
      onerror: ((event: Event) => void) | null = null;
      private listeners = new Map<string, Listener[]>();

      constructor(url: string | URL) {
        this.url = String(url);
        (window as any).__projectEventSource = this;
      }

      addEventListener(name: string, listener: EventListenerOrEventListenerObject | null): void {
        if (!listener) return;
        const callback: Listener = (event) => {
          if (typeof listener === 'function') listener(event);
          else listener.handleEvent(event);
        };
        this.listeners.set(name, [...(this.listeners.get(name) ?? []), callback]);
      }

      removeEventListener(): void {}
      close(): void {}

      emit(name: string, data: unknown): void {
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

  const project = 'evidence-alpha';
  await page.route('**/api/projects', (route) => route.fulfill({
    json: {
      ok: true,
      generated_at: '',
      project: null,
      warnings: [],
      projects: [{ name: project, repo_root: `/fixtures/${project}`, team: {}, reachable: true }]
    }
  }));
  await page.route('**/api/structure**', (route) => route.fulfill({
    json: {
      ok: true,
      generated_at: '2026-09-08T06:00:00Z',
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
          nodes: [{ module: 'alpha/core.ts', language: 'fixture', loc: 10, score: 1, churn: 0, fan_in: 0 }],
          edges: [],
          n_nodes_total: 1,
          n_edges_total: 0,
          n_edges_eligible: 0,
          n_edges_shown: 0,
          n_edges_offmap: 0
        }
      }
    }
  }));

  // Work Pulse is part of the Chat workspace. Navigate to the owning surface
  // explicitly so the evidence assertions cannot accidentally depend on the
  // default workspace selection.
  const res = await page.goto('/?view=chat', { waitUntil: 'domcontentloaded' });
  expect(res, 'the server did not answer GET / at all').not.toBeNull();
  expect(res!.status(), 'GET / did not come back 200').toBe(200);
  expect(await res!.text(), 'the built web app is missing').not.toMatch(NOT_BUILT);

  const pulse = page.getByRole('region', { name: 'Live-Arbeit' });
  await expect(pulse).toBeVisible({ timeout: 20_000 });

  await page.evaluate(() => {
    (window as any).__projectEventSource.emit('hello', {
      in_flight: 0,
      queue_depth: 0,
      latest_report: {
        name: 'schemaless.report.json',
        status: 'done',
        agent: 'must-not-be-attributed',
        summary: 'missing project evidence'
      }
    });
  });
  await expect(pulse).toContainText('Noch kein Abschlussbericht beobachtet');
  await expect(pulse).not.toContainText('schemaless.report.json');
  await expect(pulse).not.toContainText('must-not-be-attributed');

  await page.evaluate((selectedProject) => {
    (window as any).__projectEventSource.emit('hello', {
      in_flight: 0,
      queue_depth: 0,
      latest_report: {
        name: 'padded-hello.report.json',
        project: ` ${selectedProject} `,
        status: 'done',
        agent: 'padded-hello-agent',
        summary: 'project evidence must not be normalized'
      }
    });
  }, project);
  await expect(pulse).toContainText('Noch kein Abschlussbericht beobachtet');
  await expect(pulse).not.toContainText('padded-hello.report.json');
  await expect(pulse).not.toContainText('padded-hello-agent');

  await page.evaluate(() => {
    (window as any).__projectEventSource.emit('report', {
      name: 'foreign.report.json',
      project: 'evidence-beta',
      status: 'done',
      agent: 'foreign-agent',
      summary: 'foreign terminal evidence'
    });
  });
  await expect(pulse).not.toContainText('foreign.report.json');
  await expect(pulse).not.toContainText('foreign-agent');

  await page.evaluate((selectedProject) => {
    (window as any).__projectEventSource.emit('report', {
      name: 'padded-event.report.json',
      project: `${selectedProject} `,
      status: 'done',
      agent: 'padded-event-agent',
      summary: 'near-match project evidence'
    });
  }, project);
  await expect(pulse).not.toContainText('padded-event.report.json');
  await expect(pulse).not.toContainText('padded-event-agent');

  // A correctly scoped report may still contain malformed optional execution
  // identity. Keep the report, but do not normalize those identity fields into
  // facts the producer did not canonically emit.
  await page.evaluate((selectedProject) => {
    (window as any).__projectEventSource.emit('report', {
      name: 'malformed-execution.report.json',
      project: selectedProject,
      status: 'done',
      agent: 'qa-critic',
      runtime_id: ' claude_code_cli ',
      work_item_id: ' work-item-padded ',
      attempt_id: ' attempt-padded ',
      phase: ' completed ',
      terminal_receipt_sha256: 'not-a-sha256',
      summary: 'report is valid but optional execution identity is not canonical'
    });
  }, project);
  await expect(pulse).toContainText('malformed-execution.report.json');
  await expect(pulse).not.toContainText('Runtime claude_code_cli');
  await expect(pulse).not.toContainText('work-item-padded');
  await expect(pulse).not.toContainText('attempt-padded');
  await expect(pulse).not.toContainText('Phase completed');
  await expect(pulse).not.toContainText('Receipt not-a-sha256');
  await expect(pulse.getByLabel('Status der Ausführungsevidenz')).toHaveCount(0);

  // A terminal-looking report with a missing receipt remains visible, but the
  // cockpit must call the evidence spine incomplete instead of presenting the
  // report's `done` status as proof that execution is fully bound.
  await page.evaluate((selectedProject) => {
    (window as any).__projectEventSource.emit('report', {
      name: 'partial.report.json',
      project: selectedProject,
      status: 'done',
      agent: 'qa-critic',
      runtime_id: 'claude_code_cli',
      work_item_id: 'work-item-partial',
      attempt_id: 'attempt-partial',
      phase: 'terminal',
      summary: 'terminal receipt intentionally absent'
    });
  }, project);
  await expect(pulse).toContainText('partial.report.json');
  await expect(pulse.getByLabel('Status der Ausführungsevidenz').first()).toContainText(
    'Terminale Evidenz: unvollständig · Abschluss nicht als vollständig belegt behandeln'
  );

  await page.evaluate((selectedProject) => {
    (window as any).__projectEventSource.emit('report', {
      name: 'bound.report.json',
      project: selectedProject,
      status: 'done',
      agent: 'qa-critic',
      runtime_id: 'claude_code_cli',
      work_item_id: 'work-item-0123456789abcdef',
      attempt_id: 'attempt-0123456789abcdef',
      phase: 'terminal',
      terminal_receipt_sha256: 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
      provider: 'claude_cli',
      replay: true,
      execution_executed: false,
      summary: 'verified terminal evidence'
    });
  }, project);
  await expect(pulse).toContainText('bound.report.json');
  await expect(pulse).toContainText('Agent qa-critic');
  await expect(pulse).toContainText('verified terminal evidence');
  const providerRun = pulse.getByLabel('Beobachteter Provider-Lauf').first();
  await expect(providerRun).toContainText('Provider claude_cli · Replay · kein neuer Provider-Lauf');
  const evidenceStatus = pulse.getByLabel('Status der Ausführungsevidenz').first();
  await expect(evidenceStatus).toContainText('Terminale Evidenz: geschlossen');
  const observed = pulse.getByLabel('Beobachtete Ausführungsevidenz').first();
  await expect(observed).toContainText('Runtime claude_code_cli');
  await expect(observed).toContainText('Phase terminal');
  await expect(observed).toContainText('WorkItem work-item-0123456789abcdef');
  await expect(observed).toContainText('Attempt attempt-0123456789abcdef');
  await expect(observed).toContainText('Receipt aaaaaaaaaaaaaa…aaaaaaaaa');
});
