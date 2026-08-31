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
    capabilities: ['read_files'],
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

async function stubCockpit(page: Page, providerFails = false) {
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
    edges: [], health: {}, capabilities: [], policy_flags: {}
  })));
  await page.route('**/api/providers/status', (route) => providerFails
    ? route.fulfill({ status: 500, json: { ok: false, error: 'provider sample unavailable' } })
    : fulfillJson(route, envelope({ providers: [{
      name: 'claude_cli', display_name: 'Claude CLI', local: true, trusted_with_ip: true,
      can_write: false, agentic: true, requires_key: false, env_keys: [], implemented: true,
      configured: true, available: false, last_error: 'CLI did not answer'
    }] })));
  await page.route('**/api/loop/queue**', (route) => fulfillJson(route, envelope({
    queue: { candidates: [], n_candidates: 0, limit: 10, sources: {}, notes: [], degraded_sources: ['inventory'], incomplete: true, opt_in_sources_available: false }
  })));
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
