import { expect, test, type Page, type Route } from '@playwright/test';
import { NOT_BUILT, collect } from './_app';

const project = { name: 'atlas', repo_root: 'C:\\work\\atlas', team: {} };

function envelope(extra: Record<string, unknown> = {}) {
  return { ok: true, generated_at: '2026-08-31T00:00:00Z', project: project.name, warnings: [], ...extra };
}

function profile(mode = 'manual') {
  return {
    name: 'alpha',
    display_name: 'Alpha',
    sync_status: 'unified',
    daedalus: {},
    claude: {},
    category: 'engineering',
    category_label: 'Engineering',
    squads: ['runtime'],
    active: true,
    // One grant the registry declares, one it does not -- the live mix.
    capabilities: ['ollama_write', 'bash'],
    autonomy: { read_files: { project_default: mode } },
    ownership: ['daedalus/runtimes']
  };
}

function control(mode = 'manual') {
  return envelope({
    profiles: [profile(mode)],
    claude: { subagent_count: 1 },
    codex: { runtime: { communication: 'file_bus' } },
    autonomy: { agents: { alpha: mode, sibling: 'semi_auto' } },
    capability_gates: [{ id: 'read_files', label: 'Read files' }],
    runtimes: []
  });
}

async function fulfillJson(route: Route, body: Record<string, unknown>) {
  await route.fulfill({ status: 200, contentType: 'application/json; charset=utf-8', body: JSON.stringify(body) });
}

/**
 * The dashboard's `quality` block for the next stub. Mutable so one test can
 * make a safety probe fail without a second stub helper; reset per test.
 */
/** The capability registry the hierarchy carries. Mutable per test. */
let hierarchyCapabilities: Array<Record<string, unknown>> = [
  { id: 'ollama_write', name: 'Ollama Write', description: 'Write through the local Ollama runtime.', requires_secret: false, risk: 'local_write' },
  { id: 'deepseek_advisory', name: 'DeepSeek Advisory', description: '', requires_secret: true, risk: 'external_advisory' }
];

let dashboardWatcher: Record<string, unknown> = {
  running: true,
  stale_count: 0,
  watchers: [
    { pid: 45280, command: '"C:/x/worktrees/g1-ui-ikarus/.venv/Scripts/python.exe" -m daedalus.file_bridge watch --project atlas', stale: false }
  ]
};

let dashboardQuality: Record<string, unknown> = {
  local_only_never_claude: true,
  schema_non_empty_summary: true,
  empty_reports_fail: true,
  stale_watchers: 0,
  fallback_alarm: false,
  fallback_rate: 0.0,
  recommendation: ''
};

test.beforeEach(() => {
  hierarchyCapabilities = [
    { id: 'ollama_write', name: 'Ollama Write', description: 'Write through the local Ollama runtime.', requires_secret: false, risk: 'local_write' },
    { id: 'deepseek_advisory', name: 'DeepSeek Advisory', description: '', requires_secret: true, risk: 'external_advisory' }
  ];
  dashboardWatcher = {
    running: true,
    stale_count: 0,
    watchers: [
      { pid: 45280, command: '"C:/x/worktrees/g1-ui-ikarus/.venv/Scripts/python.exe" -m daedalus.file_bridge watch --project atlas', stale: false }
    ]
  };
  dashboardQuality = {
    local_only_never_claude: true,
    schema_non_empty_summary: true,
    empty_reports_fail: true,
    stale_watchers: 0,
    fallback_alarm: false,
    fallback_rate: 0.0,
    recommendation: ''
  };
});


/** The loop queue the cockpit is handed. Injected, never live: a spec whose
 *  subject is "does this render" must not also depend on the picker having
 *  found work today. That reasoning is inherited verbatim from the loop.spec.ts
 *  that G1-UI-02 deleted. */
function queueBody(overrides: Record<string, unknown> = {}) {
  return {
    candidates: [],
    n_candidates: 0,
    limit: 10,
    sources: {},
    notes: [],
    degraded_sources: ['inventory'],
    incomplete: true,
    opt_in_sources_available: false,
    ...overrides
  };
}

async function stubCockpit(
  page: Page,
  providerFails = false,
  queue: Record<string, unknown> = queueBody()
) {
  const calls: string[] = [];
  const autonomyBodies: Record<string, unknown>[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).pathname.startsWith('/api/')) calls.push(`${request.method()} ${new URL(request.url()).pathname}`);
  });

  await page.route('**/api/**', (route) => fulfillJson(route, envelope()));
  await page.route('**/api/events**', (route) => route.fulfill({
    status: 200,
    headers: { 'Content-Type': 'text/event-stream', Connection: 'close' },
    body: 'event: hello\ndata: {"queue_depth":0,"in_flight":0,"watcher_state":"idle","unread_count":0}\n\n'
  }));
  await page.route('**/api/projects', (route) => fulfillJson(route, envelope({ projects: [project] })));
  await page.route('**/api/structure**', (route) => fulfillJson(route, envelope({
    structure: {
      repo_root: project.repo_root,
      n_files: 1,
      languages: { TypeScript: { files: 1, loc: 10 } },
      totals: { unit_clusters: 0, window_clusters: 0, safety_fenced: 0 },
      hotspots: [], clones: [], window_clones: [], fan_in: [],
      graph: { nodes: [], edges: [], n_nodes_total: 0, n_edges_total: 0, truncated: false }
    }
  })));
  await page.route('**/api/runtimes/status', (route) => fulfillJson(route, envelope({ runtimes: [] })));
  await page.route('**/api/env/status', (route) => fulfillJson(route, envelope({
    env: { env_file: '', env_file_exists: false, loaded_keys: [], public: {}, secrets: {}, providers: {} }
  })));
  await page.route('**/api/dashboard**', (route) => fulfillJson(route, envelope({
    selected_project: project.name,
    queue: { pending: [], reports: [] },
    // The live `quality` block, measured 2026-09-03. core.py builds it by
    // RUNNING two probes and escalates either failure as SAFETY.
    quality: dashboardQuality,
    watcher: dashboardWatcher,
    governance: envelope({ promotion_allowed: false, verdict: 'BLOCKED_BY_GATE', state: 'present', head: null, gates: [], blockers: [] })
  })));
  await page.route('**/api/projects/*/control-plane', async (route) => {
    if (route.request().method() === 'PUT') {
      autonomyBodies.push(route.request().postDataJSON() as Record<string, unknown>);
      await fulfillJson(route, control('autonomous'));
      return;
    }
    await fulfillJson(route, control());
  });
  await page.route('**/api/projects/*/autonomy', async (route) => {
    autonomyBodies.push(route.request().postDataJSON() as Record<string, unknown>);
    await fulfillJson(route, control('autonomous'));
  });
  await page.route('**/api/projects/*/bootstrap/claude', (route) => fulfillJson(route, envelope({ prompt: 'CLAUDE_BOOTSTRAP_FIXTURE' })));
  await page.route('**/api/projects/*/hierarchy', (route) => fulfillJson(route, envelope({
    nodes: [{ id: 'alpha', type: 'agent', label: 'Alpha', data: {} }],
    edges: [], health: {},
    // The live capability registry, verbatim (2026-09-03). It was typed as an
    // opaque Record and stubbed as [], so nothing exercised it.
    capabilities: hierarchyCapabilities,
    policy_flags: {}
  })));
  await page.route('**/api/providers/status', (route) => providerFails
    ? route.fulfill({ status: 500, json: { ok: false, error: 'provider sample unavailable' } })
    : fulfillJson(route, envelope({ providers: [{
      name: 'claude_cli', display_name: 'Claude CLI', local: true, trusted_with_ip: true,
      can_write: false, agentic: true, requires_key: false, env_keys: [], implemented: true,
      configured: true, available: false, last_error: 'CLI did not answer'
    }] })));
  await page.route('**/api/loop/queue**', (route) => fulfillJson(route, envelope({ queue })));
  await page.route('**/api/loop/attempts**', (route) => fulfillJson(route, envelope({
    attempts: { intents: [], limit: 20, kind: '', task_id: null, ledger: { path: '', exists: false, read_only: true, error: null, note: null }, degraded_sources: [], incomplete: false, attempt_intent_kind: '' }
  })));
  await page.route('**/api/loop/architecture**', (route) => fulfillJson(route, envelope({
    architecture: { path: '', read: true, schema: 1, digest: 'a'.repeat(64), note: '', counts: {}, measured_lengths: {}, count_disagreements: {}, trusted: true, trust_reason: 'fixture', trust: {}, degraded_sources: [], incomplete: false }
  })));

  return { calls, autonomyBodies };
}

async function openSystemSettings(page: Page, path = '/?surface=classic') {
  const response = await page.goto(path, { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
  await expect(page.locator('.app-shell')).toHaveCount(0);
  await page.getByRole('button', { name: /^Einstellungen/ }).click();
  await expect(page.getByTestId('system-capabilities')).toBeVisible();
}

test('classic alias is Cockpit and preserves all former system contracts without the old stream', async ({ page }) => {
  const seen = collect(page);
  const fixture = await stubCockpit(page);
  await openSystemSettings(page);

  const system = page.getByTestId('system-capabilities');
  await expect(system.getByText('Projekt atlas · Verdikt BLOCKED_BY_GATE', { exact: true })).toBeVisible();
  await expect(system.getByText('CLAUDE_BOOTSTRAP_FIXTURE')).toBeVisible();
  await expect(system.getByText(/1 Knoten · 0 Kanten/)).toBeVisible();
  await expect(system.getByText(/Nicht gelesen: inventory/)).toBeVisible();
  await expect(system.getByText(/konfiguriert: ja/)).toBeVisible();
  await expect(system.getByText(/erreichbar: nein/)).toBeVisible();

  for (const path of [
    '/api/dashboard',
    '/api/projects/atlas/control-plane',
    '/api/projects/atlas/bootstrap/claude',
    '/api/providers/status',
    '/api/projects/atlas/hierarchy',
    '/api/loop/queue',
    '/api/loop/attempts',
    '/api/loop/architecture'
  ]) {
    expect(fixture.calls.some((call) => call === `GET ${path}`), `missing browser call ${path}`).toBe(true);
  }
  expect(fixture.calls.some((call) => call.includes('/api/ikarus/stream'))).toBe(false);
  expect(seen.pageErrors).toEqual([]);
});

test('one refused provider sample stays explicit while the other contracts remain visible', async ({ page }) => {
  await stubCockpit(page, true);
  await openSystemSettings(page, '/?surface=legacy');

  const system = page.getByTestId('system-capabilities');
  await expect(system.getByText(/1 Quelle war nicht lesbar/)).toBeVisible();
  await expect(system.getByText(/Quelle nicht lesbar — das ist kein leerer Datensatz/)).toBeVisible();
  await expect(system.getByText('CLAUDE_BOOTSTRAP_FIXTURE')).toBeVisible();
  await expect(system.getByText('Projekt atlas · Verdikt BLOCKED_BY_GATE', { exact: true })).toBeVisible();
});

test('agent autonomy still PUTs the existing project contract and preserves sibling policy', async ({ page }) => {
  const fixture = await stubCockpit(page);
  await openSystemSettings(page);

  await page.getByLabel('Projekt-Autonomie für Alpha').selectOption('autonomous');
  await expect.poll(() => fixture.autonomyBodies.length).toBe(1);
  expect(fixture.autonomyBodies[0]).toEqual({ agents: { alpha: 'autonomous', sibling: 'semi_auto' } });
  await expect(page.getByLabel('Projekt-Autonomie für Alpha')).toHaveValue('autonomous');
});

test('the safety gates are named, not buried in a JSON dump', async ({ page }) => {
  /*
   * core.py runs both probes and escalates either failure in its own words:
   * "SAFETY: local_only fail-closed guard did not verify -- investigate
   * before queueing". The card had the answers in hand and rendered the
   * project name, the governance verdict, and a raw contract blob, so a
   * failed gate was visible only to someone who expanded it and knew the key.
   */
  await stubCockpit(page);
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  const gates = system.locator('.safety-gates li');
  await expect(gates).toHaveCount(2);
  await expect(gates.first()).toContainText('local_only');
  await expect(gates.first().locator('.safety-verdict')).toContainText('geprüft und gehalten');
  await expect(gates.first()).toHaveClass(/\bok\b/);
  // Zero is stated as zero rather than omitted.
  await expect(system.getByText(/Hängengebliebene Watcher:/)).toBeVisible();
});

test('a safety probe that did not verify is red and says what it means', async ({ page }) => {
  dashboardQuality = { ...dashboardQuality, local_only_never_claude: false };
  await stubCockpit(page);
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  const gate = system.locator('.safety-gates li', { hasText: 'local_only' });
  await expect(gate).toHaveClass(/\bbad\b/);
  await expect(gate.locator('.safety-verdict')).toContainText('NICHT verifiziert');
  // core.py's own escalation reaches the reader.
  await expect(gate).toContainText('vor dem Einreihen');
});

test('a server that reports no gates is never drawn as having passed them', async ({ page }) => {
  // An older backend sends no `quality` block at all. Silence is not a pass.
  dashboardQuality = {};
  await stubCockpit(page);
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  const gates = system.locator('.safety-gates li');
  await expect(gates).toHaveCount(2);
  await expect(gates.first().locator('.safety-verdict')).toContainText('nicht gemeldet');
  await expect(gates.first()).not.toHaveClass(/\bok\b/);
  // Unproven, not a measured failure.
  await expect(gates.first()).toHaveClass(/\bwarn\b/);
  // And an uncounted stale-watcher figure is not rendered as zero.
  await expect(system.getByText(/Hängengebliebene Watcher: nicht gemeldet/)).toBeVisible();
  // Nor is an unreported fallback rate rendered as 0 %. "No fallbacks
  // happened" and "nobody counted" are different, and 0 is the reassuring
  // one — a mutation that defaulted it slipped past this suite until the
  // assertion below was added.
  await expect(system.getByText(/Fallback-Rate/)).toHaveCount(0);
});

test('a stale watcher carries the recommendation core.py wrote for it', async ({ page }) => {
  // core.py sets `recommendation` only when a watcher is stale, and routing
  // then recommends local_only "to avoid fallback ambiguity".
  dashboardQuality = {
    ...dashboardQuality,
    stale_watchers: 1,
    recommendation: 'Use local_only until Claude quota recovers.'
  };
  await stubCockpit(page);
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  await expect(system.getByText(/Hängengebliebene Watcher: 1 hängengeblieben/)).toBeVisible();
  await expect(system.getByText('Use local_only until Claude quota recovers.')).toBeVisible();
});

test('the watcher count says how it was detected, and never claims outbox ownership', async ({ page }) => {
  /*
   * core.py finds watchers by matching process command lines -- that is the
   * whole detection. `running: true` therefore means "a matching process
   * exists on this machine", not "your outbox has an owner": the watcher lock
   * lives beside HEARTBEAT_PATH, which is per-installation, so two checkouts
   * have two locks and two outboxes and both match the same scan.
   */
  await stubCockpit(page);
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  await expect(system.locator('.watcher-head')).toContainText('Watcher:');
  await expect(system.locator('.watcher-head')).toContainText('1 passender Prozess');
  // The caveat is on screen, not only in a source comment.
  await expect(system.locator('.watcher-basis')).toContainText('Kommandozeilen');
  // And the process is named by the tree it serves.
  await expect(system.locator('.watcher-list li')).toContainText('g1-ui-ikarus');
  await expect(system.locator('.watcher-list li')).toContainText('45280');
});

test('two matching processes are counted rather than hidden behind one word', async ({ page }) => {
  // Measured on this machine: two matches for one project, from two different
  // interpreters, both healthy. That is the ordinary multi-checkout case and
  // is stated as such rather than as a conflict.
  dashboardWatcher = {
    running: true,
    stale_count: 0,
    watchers: [
      { pid: 45280, command: '"C:/x/worktrees/g1-ui-ikarus/.venv/Scripts/python.exe" -m daedalus.file_bridge watch --project atlas', stale: false },
      { pid: 9844, command: '"C:/uv/python/cpython-3.12-windows-x86_64-none/python.exe" -m daedalus.file_bridge watch --project atlas', stale: false }
    ]
  };
  await stubCockpit(page);
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  await expect(system.locator('.watcher-head')).toContainText('2 passende Prozesse');
  await expect(system.locator('.watcher-list li')).toHaveCount(2);
  // Each names a different tree, so the reader can tell them apart.
  await expect(system.locator('.watcher-list li').nth(1)).toContainText('cpython-3.12');
  await expect(system.locator('.watcher-basis')).toContainText('mehrere Checkouts');
});

test('no matching process is reported as a stalled queue, not as silence', async ({ page }) => {
  dashboardWatcher = { running: false, stale_count: 0, watchers: [] };
  await stubCockpit(page);
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  await expect(system.locator('.watcher-head')).toContainText('kein passender Prozess gefunden');
  // Drawn as a failure, not merely stated. A mutation that kept the words and
  // dropped the colour slipped past this suite until the class was asserted.
  await expect(system.locator('.watcher-head span')).toHaveClass(/\bbad\b/);
  await expect(system.locator('.watcher-basis')).toContainText('bleiben liegen');
  await expect(system.locator('.watcher-list')).toHaveCount(0);
});

test('a dashboard with no watcher block is not reported as having no watcher', async ({ page }) => {
  // An older backend sends no `watcher` block at all. "Nobody told us" and
  // "nothing is running" are different, and only one of them is a fact.
  dashboardWatcher = undefined as unknown as Record<string, unknown>;
  await stubCockpit(page);
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  await expect(system.locator('.watcher-head')).toContainText('nicht gemeldet');
  await expect(system.locator('.watcher-head')).not.toContainText('kein passender Prozess');
  // Unproven, not a measured absence: amber rather than red.
  await expect(system.locator('.watcher-head span')).toHaveClass(/\bwarn\b/);
});

test('a granted capability nobody classified says so, and is not guessed at', async ({ page }) => {
  /*
   * Two vocabularies that do not line up. Measured across the 24 live
   * profiles: seven capabilities are granted, the registry declares five, and
   * only `ollama_write` and `claude_escalate` appear in both. The five
   * unclassified ones include `bash` and `file_write`.
   *
   * The grants used to print as a flat comma list in which every entry looked
   * alike, so an unassessed grant was indistinguishable from a cleared one.
   */
  await stubCockpit(page);
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  const grants = system.locator('.cap-grants li');
  await expect(grants).toHaveCount(2);

  // The declared one carries the registry's own class.
  const ollama = grants.filter({ hasText: 'ollama_write' });
  await expect(ollama).toContainText('schreibt lokal');

  // The undeclared one says no class was assigned -- and is NOT painted red.
  // Guessing that `bash` is dangerous would assert a classification nobody
  // made, which is the failure this whole surface refuses.
  const bash = grants.filter({ hasText: 'bash' });
  await expect(bash).toContainText('ohne eingestufte Risikoklasse');
  await expect(bash.locator('.cap-risk')).not.toHaveClass(/\bbad\b/);

  // And the profile summarises what is open, by name.
  await expect(system.getByText(/1 Berechtigung ohne eingestufte Risikoklasse: bash/)).toBeVisible();
});

test('a capability that needs a secret says so', async ({ page }) => {
  hierarchyCapabilities = [
    { id: 'bash', name: 'Bash', description: '', requires_secret: false, risk: 'local_write' },
    { id: 'ollama_write', name: 'Ollama Write', description: '', requires_secret: true, risk: 'local_write' }
  ];
  await stubCockpit(page);
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  await expect(system.locator('.cap-grants li', { hasText: 'ollama_write' })
    .locator('.cap-secret')).toContainText('braucht ein Geheimnis');
  // Now both grants are classified, so the open-grant summary disappears.
  await expect(system.getByText(/ohne eingestufte Risikoklasse/)).toHaveCount(0);
});

test('an empty registry does not silently clear every grant', async ({ page }) => {
  // A server that sends no registry has classified nothing. That must not
  // read the same as a server that classified everything.
  hierarchyCapabilities = [];
  await stubCockpit(page);
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  const grants = system.locator('.cap-grants li');
  await expect(grants).toHaveCount(2);
  await expect(grants.first()).toContainText('ohne eingestufte Risikoklasse');
  await expect(system.getByText(/2 Berechtigungen ohne eingestufte Risikoklasse/)).toBeVisible();
});

test('an unrecognised risk class reaches the screen rather than being swallowed', async ({ page }) => {
  // `risk` is a plain string in the contract on purpose: a NEW class must
  // surface as an unrecognised word, not become a browser type error.
  hierarchyCapabilities = [
    { id: 'ollama_write', name: 'Ollama Write', description: '', requires_secret: false, risk: 'quantum_egress' },
    { id: 'bash', name: 'Bash', description: '', requires_secret: false, risk: 'local_write' }
  ];
  await stubCockpit(page);
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  const ollama = system.locator('.cap-grants li', { hasText: 'ollama_write' });
  await expect(ollama).toContainText('quantum_egress');
  await expect(ollama.locator('.cap-risk')).toHaveClass(/\bwarn\b/);
});

/**
 * THE SURFACE LAYER — @loopui, restored.
 *
 * `tools/gui_check.py` runs two suites: everything except `@loopui`, and
 * `@loopui` alone, because "the cockpit renders no loop view" and "it renders
 * it wrong" are different findings with different owners. The two specs that
 * carried the tag lived in apps/web/tests/loop.spec.ts and were deleted with
 * the Classic app in e133e09b (G1-UI-02). Nothing replaced them, so the
 * `@loopui` suite has matched zero specs ever since and gui_check.py has
 * failed on every run — an alarm that was routed around rather than answered.
 *
 * Their own docstring said what should have happened: "If the cockpit renders
 * no loop surface, the @loopui specs go RED and name it." It does render one,
 * so these pass — but they are written against TODAY'S surface, and one claim
 * is deliberately weaker than the original: the deleted spec asserted a human
 * could see each candidate's REASON in a ranked list. Today the count and the
 * unread sources are on the card and the per-candidate reason is only reachable
 * by expanding the raw contract. That is a real reduction in the surface, and
 * it is named here rather than quietly asserted away.
 */

test('@loopui a human can SEE the ranked candidates, with the reason they were ranked', async ({ page }) => {
  await stubCockpit(page, false, queueBody({
    n_candidates: 2,
    degraded_sources: [],
    incomplete: false,
    candidates: [
      { task_id: 'T-1', source: 'inventory', score: 0.91, reason: 'highest fan-in, no tests', instruction: '', evidence: {} },
      { task_id: 'T-2', source: 'clones', score: 0.44, reason: 'duplicated block', instruction: '', evidence: {} }
    ]
  }));
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  await expect(system.getByText(/2 Kandidaten/)).toBeVisible();
  await expect(system.getByText(/vollständig gelesen/)).toBeVisible();

  // The reason is one click away, not on the card. See the note above.
  await system.getByText('Loop Queue: vollständiger Antwortvertrag').click();
  await expect(system.getByText(/highest fan-in, no tests/)).toBeVisible();
  await expect(system.getByText(/duplicated block/)).toBeVisible();
});

test('@loopui a degraded loop source renders as a WARNING, never as "no work"', async ({ page }) => {
  // Zero candidates AND an unread source: the case where a quiet surface would
  // be a lie. "0 Kandidaten" alone reads as "nothing to do"; the cockpit has to
  // say which source it could not read.
  await stubCockpit(page, false, queueBody({
    n_candidates: 0,
    candidates: [],
    degraded_sources: ['inventory', 'clones'],
    incomplete: true
  }));
  await openSystemSettings(page);
  const system = page.getByTestId('system-capabilities');

  await expect(system.getByText(/0 Kandidaten/)).toBeVisible();
  await expect(system.getByText(/unvollständig/)).toBeVisible();
  const unread = system.getByText(/Nicht gelesen: inventory, clones/);
  await expect(unread).toBeVisible();
  // Not merely present: styled as an error, so it cannot read as a footnote.
  await expect(unread).toHaveClass(/system-error/);
});
