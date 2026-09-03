import { expect, test, type Page } from '@playwright/test';
import { NOT_BUILT } from './_app';

/**
 * WHERE YOUR SOURCE GOES, in a browser.
 *
 * The reachability list offered six runtimes and said nothing about which of
 * them the egress gate treats as untrusted with proprietary source. It could
 * not: `local`, `trusted_with_ip`, `can_write` and `agentic` had been sent by
 * `/api/runtimes/status` since it shipped and were undeclared in the
 * TypeScript contract, so they were unreachable through the typed path.
 *
 * The rows below are verbatim from that endpoint on 2026-09-03.
 */

const project = { name: 'atlas', repo_root: 'C:\\work\\atlas', team: {}, reachable: true };

/** The live six, after the registry/provider trust disagreement was fixed. */
const runtimes = [
  { id: 'claude_code_cli', label: 'Claude Code CLI', mode: 'cli', available: true, auth_status: 'cli_detected', command_path: 'claude.exe', version: '2.1.252', models: [], selected_model: '', model_present: false, last_error: '', notes: '', local: false, trusted_with_ip: true, can_write: true, agentic: true },
  { id: 'codex_cli', label: 'Codex CLI', mode: 'cli', available: true, auth_status: 'cli_detected', command_path: 'codex', version: '0.152.0', models: [], selected_model: '', model_present: false, last_error: '', notes: '', local: false, trusted_with_ip: false, can_write: true, agentic: true },
  { id: 'ollama_http', label: 'Ollama HTTP', mode: 'local_http', available: true, auth_status: 'open', command_path: '', version: '', endpoint: 'http://127.0.0.1:11434', models: [], selected_model: '', model_present: false, last_error: '', notes: '', local: true, trusted_with_ip: true, can_write: true, agentic: true },
  { id: 'openai_api', label: 'OpenAI API', mode: 'api', available: false, auth_status: 'no_key', command_path: '', version: '', models: [], selected_model: '', model_present: false, last_error: '', notes: '', local: false, trusted_with_ip: false, can_write: false, agentic: false }
];

async function openSettings(page: Page) {
  const response = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
  await page.getByRole('button', { name: 'Einstellungen' }).click();
  const panel = page.locator('.settings.open');
  await expect(panel).toBeVisible();
  await expect(panel.locator('.reach-row').first()).toBeVisible({ timeout: 60_000 });
  return panel;
}

function stub(page: Page, rows: unknown[] = runtimes) {
  return Promise.all([
    page.route('**/api/projects', (route) =>
      route.request().method() === 'GET'
        ? route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], projects: [project] } })
        : route.fallback()),
    page.route('**/api/runtimes/status**', (route) =>
      route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], runtimes: rows } }))
  ]);
}

/** The list item for one runtime, by its visible label. */
function rowFor(panel: ReturnType<Page['locator']>, label: string) {
  return panel.locator('.reach li').filter({ hasText: label });
}

test.describe('runtime trust', () => {
  // Stub by default. Without this the first tests would silently run against
  // whatever the live server happens to report, and pass or fail for reasons
  // that have nothing to do with the claim under test.
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('daedalus-cockpit-view', 'chat'));
    await stub(page);
  });

  test('a runtime the egress gate distrusts says so, in red', async ({ page }) => {
    /*
     * `providers/codex_cli.py` declares `trusted_with_ip=False,   # NEVER
     * receives denylisted/sensitive content`, and ikarus_os builds that lane's
     * brain context with `lane="untrusted"`. Offering it beside a green
     * reachability dot with no further word invites an operator to send it
     * proprietary source.
     */
    const panel = await openSettings(page);
    const codex = rowFor(panel, 'Codex CLI');

    const chip = codex.locator('.trust-chip.bad');
    await expect(chip).toContainText('kein sensibler Quellcode');
    // The reason names the gate rather than implying the UI decided.
    await expect(chip).toHaveAttribute('title', /Egress-Gate/);
  });

  test('an approved runtime is not alarmed about', async ({ page }) => {
    const panel = await openSettings(page);
    const claude = rowFor(panel, 'Claude Code CLI');

    await expect(claude.locator('.trust-chip', { hasText: 'Quellcode erlaubt' })).toBeVisible();
    await expect(claude.locator('.trust-chip.bad')).toHaveCount(0);
  });

  test('a local runtime says nothing leaves the machine', async ({ page }) => {
    const panel = await openSettings(page);
    const ollama = rowFor(panel, 'Ollama HTTP');

    const place = ollama.locator('.trust-chip', { hasText: 'auf diesem Rechner' });
    await expect(place).toBeVisible();
    await expect(place).toHaveAttribute('title', /verlässt die Maschine/);
    // and an external one is marked as external
    await expect(rowFor(panel, 'Claude Code CLI').locator('.trust-chip', { hasText: 'extern' })).toBeVisible();
  });

  test('a runtime that may change files says so', async ({ page }) => {
    const panel = await openSettings(page);

    await expect(rowFor(panel, 'Claude Code CLI')
      .locator('.trust-chip', { hasText: 'darf schreiben' })).toBeVisible();
    // The API row is neither agentic nor a writer, and claims neither.
    const openai = rowFor(panel, 'OpenAI API');
    await expect(openai.locator('.trust-chip', { hasText: 'darf schreiben' })).toHaveCount(0);
    await expect(openai.locator('.trust-chip', { hasText: 'agentisch' })).toHaveCount(0);
  });

  test('a runtime that reported no clearance is never drawn as cleared', async ({ page }) => {
    // An older server that predates these flags sends none of them. Silence is
    // not approval, and it must not render like approval.
    await stub(page, [{
      id: 'legacy', label: 'Legacy Runtime', mode: 'cli', available: true,
      auth_status: 'cli_detected', command_path: 'x', version: '1', models: [],
      selected_model: '', model_present: false, last_error: '', notes: ''
    }]);
    const panel = await openSettings(page);
    const legacy = rowFor(panel, 'Legacy Runtime');

    await expect(legacy.locator('.trust-chip', { hasText: 'Freigabe unbekannt' })).toBeVisible();
    await expect(legacy.locator('.trust-chip', { hasText: 'Quellcode erlaubt' })).toHaveCount(0);
    // Unproven, not a measured refusal: amber, not red.
    await expect(legacy.locator('.trust-chip.bad')).toHaveCount(0);
    await expect(legacy.locator('.trust-chip.warn').first()).toBeVisible();
  });
});
