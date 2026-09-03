import { expect, test, type Page } from '@playwright/test';
import { collect, NOT_BUILT } from './_app';

/**
 * G1-UI-06 — the work rail, fixture-backed.
 *
 * Every payload here is the shape the backend emits: the draft rows of
 * `GET /api/drafts`, the `open_dispatches` of `ConversationStore.resume()`,
 * and the twenty-one-key snapshot of `_task_snapshot`. The point of the suite
 * is that the rail draws only what those payloads carry — and that opening a
 * dispatch reaches the two queue routes that had no caller in this frontend
 * at all until this packet.
 */

const project = { name: 'atlas', repo_root: 'C:\\work\\atlas', team: {}, reachable: true };

const drafts = [
  { id: 'draft-1', created: '2026-09-03T05:00:00+00:00', agent: 'codex', objective: 'Parser härten', paths: ['a.py', 'b.py'], status: 'pending', repo_root: project.repo_root },
  { id: 'draft-2', created: '2026-09-03T04:00:00+00:00', agent: 'Ikarus', objective: 'Tests nachziehen', paths: ['c.py'], status: 'pending', repo_root: project.repo_root }
];

const storedView = {
  conversation_id: 'conv_1',
  exists: true,
  turn_count: 1,
  narrative: '',
  turns: [
    {
      id: 44,
      user_message: 'Mach den Parser robuster',
      assistant_text: 'Eingereiht.',
      intent: 'enqueue',
      provider_used: 'deterministic',
      created_ts: '2026-09-03T05:10:00+00:00',
      envelope: { intent: 'enqueue', provider_used: 'deterministic' }
    }
  ],
  turns_returned: 1,
  dispatches: [],
  open_dispatches: [
    {
      link: { turn_id: 44, dispatch_ref: 'req_open', created_ts: '2026-09-03T05:12:00+00:00', kind: 'queue_task' },
      latest: { lifecycle: 'dispatched', summary: 'Parser härten', outcome_state: null, detail: { lane: 'local_only' } }
    }
  ]
};

/** `_task_snapshot`'s running branch: found, on the bus, no report yet. */
const runningTask = {
  id: 'req_open',
  found: true,
  state: 'running',
  source: 'outbox',
  observed_at: '2026-09-03T05:13:00+00:00',
  age_s: 91,
  lane: 'local_only',
  requested_lane: 'local_only',
  actual_providers: ['ollama'],
  project: project.name,
  objective: 'Parser härten',
  bridge_status: 'running',
  report_status: null,
  summary: null,
  error: null,
  applied: null,
  applied_reason: 'noch nicht abgeschlossen',
  busy_for_s: 91,
  stalled: false,
  progress: null
};

async function openCockpit(page: Page) {
  const response = await page.goto('/?view=chat', { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
}

async function stub(page: Page, options: { task?: Record<string, unknown>; artifacts?: Record<string, unknown> } = {}) {
  await page.addInitScript(() => {
    localStorage.setItem('daedalus-thread:atlas', 'conv_1');
    localStorage.setItem('daedalus-cockpit-view', 'chat');
  });
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], projects: [project] } });
  });
  await page.route('**/api/structure**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], structure: { graph: { nodes: [], edges: [] } } }
  }));
  await page.route('**/api/runtimes/status**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: null, warnings: [], runtimes: [] }
  }));
  await page.route('**/api/drafts**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], scope: project.repo_root, pending_count: drafts.length, drafts }
  }));
  await page.route((url) => url.pathname === '/api/conversations' && url.searchParams.has('project'), (route) =>
    route.fulfill({ json: { ok: true, generated_at: '', project: project.name, warnings: [], conversations: [] } })
  );
  await page.route((url) => url.pathname === '/api/conversations/conv_1', (route) =>
    route.fulfill({ json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation: storedView } })
  );
  await page.route((url) => url.pathname === '/api/queue/req_open', (route) =>
    route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], task: options.task ?? runningTask } })
  );
  await page.route((url) => url.pathname === '/api/queue/req_open/artifacts', (route) =>
    route.fulfill({
      json: {
        ok: true, generated_at: '', project: null, warnings: [],
        artifacts: options.artifacts ?? { found: true, available: false, task: 'req_open', reason: 'der Lauf ist nicht abgeschlossen' }
      }
    })
  );
}

test.describe('work rail', () => {
  test('the rail lists what waits and what runs, from the payloads that carry them', async ({ page }) => {
    const seen = collect(page);
    await stub(page);
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();

    const rail = page.locator('.work');
    await expect(rail).toBeVisible();

    // Every pending draft, not just the first — the decision card reads them
    // all and used to draw one.
    const waiting = rail.locator('.work-section.wait');
    await expect(waiting).toContainText('Parser härten');
    await expect(waiting).toContainText('Tests nachziehen');
    await expect(waiting.locator('.work-count')).toHaveText('2');

    // The open dispatch, which no component rendered before this packet.
    const runningSection = rail.locator('.work-section.live');
    await expect(runningSection).toContainText('req_open');
    await expect(runningSection).toContainText('noch kein Bericht');

    expect(seen.pageErrors).toEqual([]);
  });

  test('opening a dispatch reads the bus, and says so when there is no result yet', async ({ page }) => {
    let taskReads = 0;
    let artifactReads = 0;
    await stub(page);
    await page.route((url) => url.pathname === '/api/queue/req_open', async (route) => {
      taskReads += 1;
      await route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], task: runningTask } });
    });
    await page.route((url) => url.pathname === '/api/queue/req_open/artifacts', async (route) => {
      artifactReads += 1;
      await route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], artifacts: { found: true, available: false, reason: 'x' } } });
    });
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();

    // Nothing is fetched until asked: a rail that read every dispatch as it
    // drew would turn a glance into a fan-out.
    expect(taskReads).toBe(0);

    await page.getByRole('button', { name: /req_open/ }).click();
    const detail = page.locator('.work-detail');
    await expect(detail).toBeVisible();
    await expect(detail).toContainText('läuft');
    await expect(detail).toContainText('local_only');
    await expect(detail).toContainText('ollama');
    await expect.poll(() => taskReads).toBe(1);
    // A running task is not asked for artifacts it cannot have.
    expect(artifactReads).toBe(0);
  });

  test('a finished dispatch shows what it produced, and never claims it was applied', async ({ page }) => {
    await stub(page, {
      task: { ...runningTask, state: 'done', bridge_status: 'done', summary: 'Patch erzeugt, nicht angewendet', applied: false, applied_reason: 'patch produced, not applied' },
      artifacts: {
        found: true,
        available: true,
        task: 'req_open',
        applied: false,
        applied_reason: 'patch produced, not applied',
        files_changed: ['daedalus/parse.py', 'tests/test_parse.py'],
        rolled_back: [],
        wrote: [],
        draft_ids: ['draft-9'],
        tests_run: ['pytest -q'],
        risks: ['Randfall bei leerer Datei'],
        todos: []
      }
    });
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();
    await page.getByRole('button', { name: /req_open/ }).click();

    const detail = page.locator('.work-detail');
    await expect(detail).toContainText('fertig');
    await expect(detail).toContainText('Patch erzeugt, nicht angewendet');
    await expect(detail).toContainText('daedalus/parse.py');
    await expect(detail).toContainText('pytest -q');
    await expect(detail).toContainText('draft-9');
    await expect(detail).toContainText('Randfall bei leerer Datei');
    // The word "angewendet" must never appear as a claim; the run said it did
    // not apply, and the summary is the only place that word may live.
    await expect(detail).not.toContainText('Übergabe: bestätigt');
  });

  test('the activity log reads on demand and says whose history it is', async ({ page }) => {
    let reads = 0;
    await stub(page);
    await page.route('**/api/loop/attempts**', async (route) => {
      reads += 1;
      await route.fulfill({
        json: {
          ok: true, generated_at: '', project: null, warnings: [],
          attempts: {
            intents: [
              {
                intent_id: 12, kind: 'attempt', state: 'closed', created_ts: '2026-09-03T05:00:00+00:00',
                resolved_ts: '2026-09-03T05:02:00+00:00', effect_key: 'k', task_id: 'req_a', instruction: 'Parser härten',
                source: 'picker', score: 0.8, reason: 'heat', outcome: 'applied', gates_passed: true,
                changed_paths: 3, error: null
              },
              {
                intent_id: 11, kind: 'attempt', state: 'failed', created_ts: '2026-09-03T04:00:00+00:00',
                resolved_ts: null, effect_key: 'k', task_id: 'req_b', instruction: 'Tests nachziehen',
                source: '', score: null, reason: '', outcome: null, gates_passed: false,
                changed_paths: 0, error: 'pytest exited 1'
              }
            ],
            limit: 8, kind: '', task_id: null,
            ledger: { path: 'runs/spine.sqlite3', exists: true, read_only: true, error: null, note: null },
            degraded_sources: [], incomplete: true, attempt_intent_kind: 'attempt', dropped_for_size: 2
          }
        }
      });
    });
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();

    // Closed until asked: the ledger read is bounded but not free.
    expect(reads).toBe(0);
    await page.getByRole('button', { name: 'Zuletzt versucht' }).click();

    const log = page.locator('.work-log');
    await expect(log).toContainText('Parser härten');
    await expect(log).toContainText('Tests nachziehen');
    await expect(log).toContainText('Gates bestanden');
    await expect(log).toContainText('Gates nicht bestanden');
    await expect(log).toContainText('pytest exited 1');
    // An attempt with no verdict says so rather than reading as a success.
    await expect(log).toContainText('ohne Ergebnis');
    // The endpoint is not project-scoped, and the surface says so.
    await expect(log).toContainText('nicht nur in diesem Projekt');
    // Everything the endpoint reported about its own reading is printed.
    await expect(log).toContainText('nur lesbar');
    await expect(log).toContainText('unvollständig');
    await expect(log).toContainText('2 Zeilen wegen Größe weggelassen');
    await expect.poll(() => reads).toBe(1);
  });

  test('a ledger that could not be read is never drawn as an empty history', async ({ page }) => {
    await stub(page);
    await page.route('**/api/loop/attempts**', (route) =>
      route.fulfill({
        json: {
          ok: true, generated_at: '', project: null, warnings: [],
          attempts: {
            intents: [], limit: 8, kind: '', task_id: null,
            ledger: { path: 'runs/spine.sqlite3', exists: true, read_only: false, error: 'database is locked', note: null },
            degraded_sources: ['spine'], incomplete: true, attempt_intent_kind: 'attempt'
          }
        }
      })
    );
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();
    await page.getByRole('button', { name: 'Zuletzt versucht' }).click();

    const log = page.locator('.work-log');
    await expect(log).toContainText('Ledger nicht lesbar: database is locked');
    await expect(log).toContainText('Beeinträchtigt: spine');
    // "could not look" must never render as "nothing happened".
    await expect(log.locator('.work-detail-note.bad')).toBeVisible();
  });

  test('a dispatch the bus does not know is a fact, not an error', async ({ page }) => {
    await stub(page, {
      task: {
        ...runningTask, found: false, state: 'unknown', source: 'none', observed_at: null, age_s: null,
        lane: null, requested_lane: null, actual_providers: [], project: null, objective: null,
        bridge_status: null, report_status: null, summary: null, error: null, applied: null,
        applied_reason: 'no task with this id was found on the file bus (wrong id, or the archive has since been cleared)',
        busy_for_s: null, progress: null
      }
    });
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();
    await page.getByRole('button', { name: /req_open/ }).click();

    const detail = page.locator('.work-detail');
    await expect(detail).toContainText('Auf dem Bus nicht auffindbar');
    await expect(detail).toContainText('wrong id');
  });
});
