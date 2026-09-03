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

/** `UnitProgress.to_dict()` — note `fraction_hint` is a sentence, and both
 *  verdicts are tri-state with `null` meaning "no verdict recorded". */
const progress = {
  unit_id: 'req_open',
  observed_at: '2026-09-03T10:00:00+00:00',
  found: true,
  events_seen: 3,
  kinds_seen: ['queued', 'claimed', 'disk_changed'],
  latest_kind: 'disk_changed',
  latest_source: 'offload',
  latest_ts: '2026-09-03T09:59:00+00:00',
  age_s: 60,
  claimed_ts: '2026-09-03T09:55:00+00:00',
  claimed_age_s: 300,
  terminal: false,
  succeeded: null,
  applied: null,
  stalled: false,
  fraction_hint: 'one unit has no honest denominator; use batch_snapshot() for a real N-of-M fraction',
  facts: [],
  narrative: [
    { unit_id: 'req_open', kind: 'queued', ts: '2026-09-03T09:54:00+00:00', source: 'web_api', detail: { lane: 'local_only' }, batch_id: null },
    { unit_id: 'req_open', kind: 'claimed', ts: '2026-09-03T09:55:00+00:00', source: 'watcher', detail: {}, batch_id: null },
    { unit_id: 'req_open', kind: 'disk_changed', ts: '2026-09-03T09:59:00+00:00', source: 'offload', detail: { basis: 'git_status', paths: 2 }, batch_id: null }
  ]
};

async function openCockpit(page: Page) {
  const response = await page.goto('/?view=chat', { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
}

async function stub(
  page: Page,
  options: {
    task?: Record<string, unknown>;
    artifacts?: Record<string, unknown>;
    /** `/api/drafts` answers `scope: null` when it could not narrow the pile
     *  to this project. Those drafts are real, and they are not this
     *  project's to count or to act on. */
    scope?: string | null;
    /** the bus answers 404 for an id it does not have — the real shape */
    taskMissing?: boolean;
  } = {}
) {
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
  const scope = options.scope === undefined ? project.repo_root : options.scope;
  await page.route('**/api/drafts**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], scope, pending_count: drafts.length, drafts }
  }));
  await page.route((url) => url.pathname === '/api/conversations' && url.searchParams.has('project'), (route) =>
    route.fulfill({ json: { ok: true, generated_at: '', project: project.name, warnings: [], conversations: [] } })
  );
  await page.route((url) => url.pathname === '/api/conversations/conv_1', (route) =>
    route.fulfill({ json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation: storedView } })
  );
  await page.route((url) => url.pathname === '/api/queue/req_open', (route) => {
    // `read.py` answers `200 if snap["found"] else 404`. A test that stubbed
    // 200 with `found: false` would assert a shape the server never emits —
    // and did, until the review caught it.
    if (options.taskMissing) {
      return route.fulfill({
        status: 404,
        json: { ok: false, error: 'unknown task id req_open (wrong id, or the archive has since been cleared)' }
      });
    }
    return route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], task: options.task ?? runningTask } });
  });
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

  test('a dispatch the bus does not know is a fact, not an outage', async ({ page }) => {
    // The server answers 404 here, so this is also the regression for the
    // reading that dressed the most likely real case — an archive that was
    // cleared — as "the bus could not be read".
    await stub(page, { taskMissing: true });
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();
    await page.getByRole('button', { name: /req_open/ }).click();

    const note = page.locator('.work-row.live .work-detail-note');
    await expect(note).toContainText('Auf dem Bus nicht auffindbar');
    await expect(note).toContainText('archive has since been cleared');
    // Not an infrastructure failure: the row must not be painted as one.
    await expect(page.locator('.work-detail-note.bad')).toHaveCount(0);
  });

  test('the recorded timeline is drawn, with the source of every step', async ({ page }) => {
    await stub(page, { task: { ...runningTask, progress } });
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();
    await page.getByRole('button', { name: /req_open/ }).click();

    const timeline = page.locator('.timeline');
    await expect(timeline).toBeVisible();
    /*
     * There is no percentage, the refusal is stated, and the backend's own
     * explanation is ON SCREEN next to it.
     *
     * This briefly asserted the sentence was present as a `title` attribute.
     * That passed while the sentence was unreachable: `title` on a bare span
     * is mouse-only, so a keyboard user could never read the honest half, and
     * screen-reader exposure of `title` is inconsistent. Asserting the
     * attribute exists is not asserting anyone can read it.
     */
    await expect(timeline).toContainText('ohne Prozentangabe');
    await expect(timeline.locator('.work-no-fraction')).toContainText('honest denominator');
    await expect(page.locator('.timeline progress, .timeline [role="progressbar"]')).toHaveCount(0);
    // Tri-state verdicts: `null` is a recorded absence, never a success.
    await expect(timeline).toContainText('Erfolg nicht gemeldet');
    await expect(timeline).toContainText('Übernommen nicht gemeldet');
    await expect(timeline).toContainText('angenommen vor 300 s');

    // Steps are closed until asked, then every one carries its source —
    // progress.py refuses to record an event without one.
    await expect(page.locator('.step')).toHaveCount(0);
    await timeline.getByRole('button', { name: '3 Schritte zeigen' }).click();
    const steps = page.locator('.step');
    await expect(steps).toHaveCount(3);
    await expect(steps.nth(0)).toContainText('eingereiht');
    await expect(steps.nth(0)).toContainText('web_api');
    await expect(steps.nth(1)).toContainText('watcher');
    await expect(steps.nth(2)).toContainText('Dateien geändert');
    await expect(steps.nth(2)).toContainText('offload');
    // The evidence basis the log demands for a disk claim is shown, not hidden.
    await expect(steps.nth(2)).toContainText('git_status');
  });

  test('a failed run does not paint its last step green', async ({ page }) => {
    // progress.py has no `failed` kind: a failure is `done` with
    // `succeeded: false`. Colouring the word rather than the verdict told the
    // reader a failed run had finished well.
    await stub(page, {
      task: {
        ...runningTask,
        state: 'done',
        progress: {
          ...progress,
          terminal: true,
          succeeded: false,
          latest_kind: 'done',
          narrative: [
            ...progress.narrative,
            { unit_id: 'req_open', kind: 'done', ts: '2026-09-03T10:00:00+00:00', source: 'watcher', detail: { succeeded: false, reason: 'gate refused' }, batch_id: null }
          ],
          events_seen: 4
        }
      }
    });
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();
    await page.getByRole('button', { name: /req_open/ }).click();
    await page.getByRole('button', { name: '4 Schritte zeigen' }).click();

    const last = page.locator('.step').last();
    await expect(last).toContainText('abgeschlossen');
    await expect(last).toHaveClass(/\bbad\b/);
    await expect(last).not.toHaveClass(/\bok\b/);
    await expect(page.locator('.timeline')).toContainText('Erfolg nein');
  });

  test('a terminal step with no verdict is neither green nor red', async ({ page }) => {
    await stub(page, {
      task: {
        ...runningTask,
        state: 'done',
        progress: {
          ...progress,
          terminal: true,
          succeeded: null,
          narrative: [{ unit_id: 'req_open', kind: 'done', ts: '2026-09-03T10:00:00+00:00', source: 'watcher', detail: {}, batch_id: null }],
          events_seen: 1
        }
      }
    });
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();
    await page.getByRole('button', { name: /req_open/ }).click();
    await page.getByRole('button', { name: '1 Schritt zeigen' }).click();

    const step = page.locator('.step').first();
    await expect(step).toHaveClass(/\bwarn\b/);
    await expect(page.locator('.timeline')).toContainText('Erfolg nicht gemeldet');
  });

  test('every recorded event kind has a German word', async ({ page }) => {
    // The ten kinds of daedalus/progress.py EVENT_KINDS. An earlier map
    // invented `failed`/`cancelled` and omitted four real ones, which then
    // rendered as raw English identifiers in a German cockpit.
    const kinds = ['queued', 'claimed', 'heartbeat', 'generating', 'tool_ran', 'gate_verdict', 'disk_changed', 'no_change', 'patch_produced', 'done'];
    await stub(page, {
      task: {
        ...runningTask,
        progress: {
          ...progress,
          events_seen: kinds.length,
          narrative: kinds.map((kind, i) => ({
            unit_id: 'req_open', kind, ts: `2026-09-03T09:0${i}:00+00:00`, source: 'offload', detail: {}, batch_id: null
          }))
        }
      }
    });
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();
    await page.getByRole('button', { name: /req_open/ }).click();
    await page.getByRole('button', { name: '10 Schritte zeigen' }).click();

    // Not one kind falls through to the verbatim identifier rendering.
    await expect(page.locator('.step-kind.mono')).toHaveCount(0);
    await expect(page.locator('.timeline')).toContainText('Patch erzeugt');
    await expect(page.locator('.timeline')).toContainText('Werkzeug gelaufen');
    await expect(page.locator('.timeline')).toContainText('Gate-Urteil');
  });

  test('a step with more detail than fits says how much it left out', async ({ page }) => {
    await stub(page, {
      task: {
        ...runningTask,
        progress: {
          ...progress,
          events_seen: 1,
          narrative: [{
            unit_id: 'req_open', kind: 'done', ts: '2026-09-03T10:00:00+00:00', source: 'watcher',
            detail: { a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7, h: 8 }, batch_id: null
          }]
        }
      }
    });
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();
    await page.getByRole('button', { name: /req_open/ }).click();
    await page.getByRole('button', { name: '1 Schritt zeigen' }).click();

    await expect(page.locator('.step')).toContainText('und 2 weitere');
  });

  test('a unit with nothing recorded says so instead of drawing an empty run', async ({ page }) => {
    await stub(page, {
      task: {
        ...runningTask,
        progress: {
          ...progress, found: false, events_seen: 0, kinds_seen: [], latest_kind: null,
          latest_source: null, latest_ts: null, age_s: null, claimed_ts: null, claimed_age_s: null,
          narrative: [], fraction_hint: 'no events recorded for this unit_id'
        }
      }
    });
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();
    await page.getByRole('button', { name: /req_open/ }).click();

    await expect(page.locator('.work-detail')).toContainText('no events recorded for this unit_id');
    await expect(page.locator('.step')).toHaveCount(0);
  });

  test('an unscoped draft pile is never counted under this project\'s name', async ({ page }) => {
    // `/api/drafts` could not narrow the pile to this project. Those drafts
    // exist and belong to someone; they are not this project's decision, and
    // the rail must neither list nor count them.
    await stub(page, { scope: null });
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();

    const waiting = page.locator('.work-section.wait');
    await expect(waiting).not.toContainText('Parser härten');
    await expect(waiting).not.toContainText('Tests nachziehen');
    await expect(waiting.locator('.work-count')).toHaveCount(0);
    // And the tab must not advertise them either.
    await expect(page.getByRole('tab', { name: /Arbeit/ }).locator('.rail-badge')).toHaveCount(0);
    // "Nothing waits" would be a claim about a pile it could not read.
    await expect(waiting).toContainText('Projekt wird ermittelt');
  });

  test('counts the event stream never reported are not asserted as nothing', async ({ page }) => {
    // The stream never answers here, so quarantined/unread were never
    // reported. Saying "Nichts" would assert an absence from a source that
    // never spoke. (Without this abort the REAL server answers and reports
    // zeroes, which is a different, honest sentence.)
    await page.route('**/api/events**', (route) => route.abort('connectionrefused'));
    await stub(page, { scope: project.repo_root });
    await page.route('**/api/drafts**', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: project.name, warnings: [], scope: project.repo_root, pending_count: 0, drafts: [] }
    }));
    await openCockpit(page);
    await page.getByRole('tab', { name: /Arbeit/ }).click();

    const waiting = page.locator('.work-section.wait');
    await expect(waiting).toContainText('Ereignisstrom noch nicht gemeldet');
  });
});
