import { expect, test, type Page } from '@playwright/test';
import { NOT_BUILT } from './_app';

type CapMode = 'bounded' | 'custom' | 'unbounded_execution';
type CapAxis =
  | 'period_usd'
  | 'billable_calls'
  | 'mission_spend'
  | 'tokens'
  | 'wall_time'
  | 'attempts'
  | 'concurrency'
  | 'work_scope';

const AXES: Array<{ id: CapAxis; label: string }> = [
  { id: 'period_usd', label: 'Globale Periodenkosten (USD)' },
  { id: 'billable_calls', label: 'Bezahlte Modellaufrufe' },
  { id: 'mission_spend', label: 'Mission-, EffectLease- und SpendEnvelope-Beträge' },
  { id: 'tokens', label: 'Input-, Kontext- und Output-Tokens' },
  { id: 'wall_time', label: 'Ausführungs-, Provider-, Gate- und Evaluationszeit' },
  { id: 'attempts', label: 'Retries, Attempts, Iterationen und Agent-Schritte' },
  { id: 'concurrency', label: 'Read-only Worker, Fan-out und Kandidaten-Evaluation' },
  { id: 'work_scope', label: 'Queue-Batch, Zerlegung, Rewrite-Umfang und Kandidatenmenge' }
];

type CapConfigured = Record<CapAxis, boolean>;

interface FixtureConfig {
  [key: string]: unknown;
  bridge: { auto_start: boolean };
  caps: {
    mode: CapMode;
    configured: CapConfigured;
    confirm_widening?: boolean;
  };
  budget: {
    period_ceiling_usd: number;
    max_calls: number;
  };
  ide: {
    mode: string;
    auto_start: boolean;
    endpoint: string;
    executable: string;
    docker_image: string;
  };
  ollama: {
    mode: 'local' | 'remote_ssh';
    auto_start: boolean;
    model: string;
    local_host: string;
    remote: {
      host: string;
      user: string;
      port: number;
      identity_file: string;
      host_key_fingerprint: string;
      local_port: number;
      remote_port: number;
      start_method: 'systemd' | 'windows' | 'none';
      trust_remote_host: boolean;
    };
  };
}

type OwnedDesktopSections = Pick<FixtureConfig, 'bridge' | 'ollama' | 'budget' | 'caps'>;
interface DesktopSectionUpdate {
  section_updates: Partial<OwnedDesktopSections>;
}
type DesktopWrite = FixtureConfig | DesktopSectionUpdate;

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function configured(overrides: Partial<CapConfigured> = {}): CapConfigured {
  return Object.fromEntries(AXES.map(({ id }) => [id, overrides[id] ?? true])) as CapConfigured;
}

function makeConfig(
  mode: CapMode = 'bounded',
  configuredAxes: CapConfigured = configured(),
  periodUsd = 5,
  maxCalls = 100
): FixtureConfig {
  return {
    bridge: { auto_start: true },
    caps: { mode, configured: clone(configuredAxes) },
    budget: { period_ceiling_usd: periodUsd, max_calls: maxCalls },
    ide: {
      mode: 'docker',
      auto_start: false,
      endpoint: 'http://127.0.0.1:3000',
      executable: '',
      docker_image: 'daedalus/openvscode-server:1.109.5'
    },
    ollama: {
      mode: 'local',
      auto_start: false,
      model: 'qwen2.5-coder:7b',
      local_host: 'http://127.0.0.1:11434',
      remote: {
        host: '',
        user: '',
        port: 22,
        identity_file: '',
        host_key_fingerprint: '',
        local_port: 11434,
        remote_port: 11434,
        start_method: 'none',
        trust_remote_host: false
      }
    }
  };
}

function persisted(input: FixtureConfig): FixtureConfig {
  const output = clone(input);
  delete output.caps.confirm_widening;
  return output;
}

function updatesOf(input: DesktopWrite): Partial<OwnedDesktopSections> {
  return 'section_updates' in input ? input.section_updates : input;
}

function applyDesktopWrite(current: FixtureConfig, input: DesktopWrite): FixtureConfig {
  if (!('section_updates' in input)) return persisted(input);
  const output = clone(current);
  for (const [name, section] of Object.entries(input.section_updates)) {
    (output as unknown as Record<string, unknown>)[name] = clone(section);
  }
  delete output.caps.confirm_widening;
  return output;
}

function envelope(config: FixtureConfig) {
  return {
    ok: true,
    generated_at: '',
    project: null,
    warnings: [],
    desktop: {
      config: clone(config),
      config_path: 'C:\\Users\\test\\AppData\\Local\\Daedalus\\desktop.json',
      settings_update_contract: 'section_updates_v1',
      caps: { ariadne_campaign_live: true },
      credential_policy: {
        ssh_key_only: true,
        stores_passwords: false,
        stores_private_key_bytes: false,
        host_key_verification: 'strict'
      },
      services: {
        bridge: {
          managed: false,
          state: 'alive',
          managed_start_available: false,
          availability_reason: 'Desktop-Start nicht verfügbar; der File-Bridge-Watcher muss explizit gestartet werden.'
        },
        ollama: {
          mode: config.ollama.mode,
          endpoint: config.ollama.local_host,
          observed: true,
          reachable: true,
          tunnel_running: false,
          local_process_running: false,
          managed_start_available: false,
          remote_ssh_available: false,
          availability_reason: 'Nur ein bereits laufendes Loopback-Ollama kann geprüft und übernommen werden.',
          host_key_pinned: false
        },
        ide: {
          mode: config.ide.mode,
          endpoint: config.ide.endpoint,
          reachable: false,
          managed_start_available: false,
          availability_reason: 'Managed IDE start unavailable.'
        }
      }
    }
  };
}

async function stubQuietCockpit(page: Page, runtimes: unknown[] = []): Promise<void> {
  const project = { name: 'atlas', repo_root: 'C:\\work\\atlas', team: {} };
  await page.route('**/api/projects', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], projects: [project] }
  }));
  await page.route('**/api/structure**', (route) => route.fulfill({
    json: {
      ok: true,
      generated_at: '',
      project: project.name,
      warnings: [],
      structure: { repo_root: project.repo_root, graph: { nodes: [], edges: [] } }
    }
  }));
  await page.route('**/api/runtimes/status', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], runtimes }
  }));
  await page.route('**/api/env/status', (route) => route.fulfill({
    json: {
      ok: true,
      generated_at: '',
      project: project.name,
      warnings: [],
      env: {
        env_file: '',
        env_file_exists: false,
        loaded_keys: [],
        public: {},
        secrets: {},
        providers: {}
      }
    }
  }));
}

async function openSettings(page: Page): Promise<void> {
  const response = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
  await page.getByRole('button', { name: /^Einstellungen/ }).click();
  await expect(page.locator('.settings.open')).toBeVisible();
}

async function installDesktopRoute(
  page: Page,
  initial: FixtureConfig,
  puts: DesktopWrite[]
): Promise<void> {
  let canonical = clone(initial);
  await page.route('**/api/desktop/settings', async (route) => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON() as DesktopWrite;
      puts.push(clone(body));
      canonical = applyDesktopWrite(canonical, body);
    }
    await route.fulfill({ json: envelope(canonical) });
  });
}

function capRegion(page: Page) {
  return page.getByRole('region', { name: 'Ausführungsgrenzen' });
}

test.describe('Owner execution cap menu', () => {
  test('zeigt Laden, Fehler, Retry und die unveränderlichen Grenzen ehrlich an', async ({ page }) => {
    await stubQuietCockpit(page);
    const config = makeConfig();
    let releaseFirst!: () => void;
    const firstMayFinish = new Promise<void>((resolve) => { releaseFirst = resolve; });
    let gets = 0;
    await page.route('**/api/desktop/settings', async (route) => {
      gets += 1;
      if (gets === 1) {
        await firstMayFinish;
        await route.fulfill({ status: 500, json: { ok: false, error: 'Cap-Snapshot fehlgeschlagen.' } });
        return;
      }
      await route.fulfill({ json: envelope(config) });
    });

    await openSettings(page);
    const caps = capRegion(page);
    await expect(caps.getByText('Cap-Policy wird gelesen …')).toBeVisible();
    await expect(caps.getByText('Kill-Switch')).toBeVisible();
    await expect(caps.getByText('Provider-Kontextfenster')).toBeVisible();
    await expect(caps.getByText('Ariadne-Campaign-Status ist noch nicht bestätigt')).toBeVisible();
    releaseFirst();
    await expect(caps.getByRole('alert').filter({ hasText: 'Cap-Snapshot fehlgeschlagen.' })).toBeVisible();
    await expect(page.getByRole('alert').filter({ hasText: 'Cap-Snapshot fehlgeschlagen.' })).toHaveCount(1);
    await expect(caps.getByRole('alert')).toContainText('Desktop-Einstellungen konnten nicht geladen werden');

    await caps.getByRole('button', { name: 'Erneut laden' }).click();
    await expect(caps.getByText('Ariadne Campaign Workbench ist live')).toBeVisible();
    await expect(caps.getByRole('radio', { name: /^Begrenzt/ })).toBeChecked();
    await expect(caps.getByLabel('Gespeicherter USD-Fallback pro Budgetperiode')).toHaveValue('5');
    await expect(caps.getByLabel('Gespeicherter Aufruf-Fallback pro Budgetperiode')).toHaveValue('100');
  });

  const modeMatrix: Array<{
    mode: CapMode;
    configuredAxes: CapConfigured;
    effectiveOn: number;
    effectiveOff: number;
  }> = [
    {
      mode: 'bounded',
      configuredAxes: configured({ period_usd: false, attempts: false }),
      effectiveOn: 8,
      effectiveOff: 0
    },
    {
      mode: 'custom',
      configuredAxes: configured({ period_usd: false, attempts: false }),
      effectiveOn: 6,
      effectiveOff: 2
    },
    {
      mode: 'unbounded_execution',
      configuredAxes: configured(),
      effectiveOn: 0,
      effectiveOff: 8
    }
  ];

  for (const scenario of modeMatrix) {
    test(`leitet den effektiven Zustand für ${scenario.mode} aus dem Modus ab`, async ({ page }) => {
      await stubQuietCockpit(page);
      await installDesktopRoute(page, makeConfig(scenario.mode, scenario.configuredAxes), []);
      await openSettings(page);

      const caps = capRegion(page);
      await expect(caps.locator('.cap-effective.on')).toHaveCount(scenario.effectiveOn);
      await expect(caps.locator('.cap-effective.off')).toHaveCount(scenario.effectiveOff);
      await expect(caps.locator('.cap-axis-switch').getByRole('switch')).toHaveCount(8);
      if (scenario.mode === 'custom') {
        await expect(caps.locator('.cap-axis-switch').getByRole('switch').first()).toBeEnabled();
      } else {
        await expect(caps.locator('.cap-axis-switch').getByRole('switch').first()).toBeDisabled();
      }
      await expect(caps.locator('.cap-disabled-disclosure')).toHaveCount(scenario.effectiveOff ? 1 : 0);
    });
  }

  test('schaltet im Custom-Modus jede der acht Achsen und bestätigt die Aufweitung transient', async ({ page }) => {
    await stubQuietCockpit(page);
    const puts: DesktopWrite[] = [];
    await installDesktopRoute(page, makeConfig('custom'), puts);
    await openSettings(page);

    const caps = capRegion(page);
    for (const axis of AXES) {
      await caps.getByRole('switch', { name: `${axis.label} begrenzen` }).uncheck();
    }
    await expect(caps.locator('.cap-effective.off')).toHaveCount(8);
    await expect(caps.locator('.cap-disabled-disclosure li')).toHaveCount(8);
    const save = caps.getByRole('button', { name: 'Cap-Policy speichern' });
    await expect(save).toBeDisabled();
    await caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ }).check();
    await save.click();

    await expect(caps.getByRole('status')).toContainText('Individuelle Cap-Policy mit 8 deaktivierten Achsen');
    expect(puts).toHaveLength(1);
    expect(updatesOf(puts[0]).caps).toEqual({
      mode: 'custom',
      configured: configured(Object.fromEntries(AXES.map(({ id }) => [id, false])) as Partial<CapConfigured>),
      confirm_widening: true
    });
    expect(updatesOf(puts[0]).budget).not.toHaveProperty('confirm_widening');
    await expect(caps.locator('.cap-disabled-disclosure')).toBeVisible();
  });

  test('erzwingt Ack für bounded→custom und unbounded, setzt ihn bei jeder Änderung zurück', async ({ page }) => {
    await stubQuietCockpit(page);
    const puts: DesktopWrite[] = [];
    await installDesktopRoute(page, makeConfig('bounded'), puts);
    await openSettings(page);

    const caps = capRegion(page);
    await caps.getByRole('radio', { name: /^Individuell/ }).check();
    await expect(caps.getByRole('button', { name: 'Cap-Policy speichern' })).toBeDisabled();
    await caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ }).check();
    await caps.getByRole('button', { name: 'Cap-Policy speichern' }).click();
    await expect.poll(() => puts.length).toBe(1);
    expect(updatesOf(puts[0]).caps?.confirm_widening).toBe(true);

    await expect(caps.getByRole('status')).toContainText('Individuelle Cap-Policy');
    await caps.getByRole('radio', { name: /^Begrenzt/ }).check();
    await expect(caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ })).toHaveCount(0);
    await caps.getByRole('button', { name: 'Cap-Policy speichern' }).click();
    await expect.poll(() => puts.length).toBe(2);
    expect(updatesOf(puts[1]).caps).not.toHaveProperty('confirm_widening');

    await expect(caps.getByRole('status')).toContainText('Alle acht Daedalus-Ausführungsgrenzen');
    await caps.getByRole('radio', { name: /^Unbegrenzte Ausführung/ }).check();
    await expect(caps.locator('.cap-effective.off')).toHaveCount(8);
    const ack = caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ });
    await ack.check();
    await caps.getByLabel('Gespeicherter USD-Fallback pro Budgetperiode').fill('6');
    await expect(ack).not.toBeChecked();
    await expect(caps.getByRole('button', { name: 'Cap-Policy speichern' })).toBeDisabled();
    await ack.check();
    await caps.getByRole('button', { name: 'Cap-Policy speichern' }).click();
    await expect.poll(() => puts.length).toBe(3);
    expect(updatesOf(puts[2]).caps?.confirm_widening).toBe(true);
    expect(updatesOf(puts[2]).budget?.period_ceiling_usd).toBe(6);
    await expect(caps.getByRole('status')).toContainText('Unbegrenzte Daedalus-Ausführung');
    await expect(caps.locator('.cap-disabled-disclosure li')).toHaveCount(8);

    await page.getByRole('button', { name: 'Neu prüfen' }).click();
    await expect(caps.getByRole('radio', { name: /^Unbegrenzte Ausführung/ })).toBeChecked();
    await expect(caps.locator('.cap-disabled-disclosure li')).toHaveCount(8);
    await expect(caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ })).toHaveCount(0);
  });

  test('verwirft Cap- und Budgetentwürfe samt Risiko-Ack ohne PUT', async ({ page }) => {
    await stubQuietCockpit(page);
    const puts: DesktopWrite[] = [];
    await installDesktopRoute(page, makeConfig('bounded', configured(), 5, 100), puts);
    await openSettings(page);

    const caps = capRegion(page);
    const usd = caps.getByLabel('Gespeicherter USD-Fallback pro Budgetperiode');
    const save = caps.getByRole('button', { name: 'Cap-Policy speichern' });
    const discard = caps.getByRole('button', { name: 'Verwerfen', exact: true });
    await caps.getByRole('radio', { name: /^Unbegrenzte Ausführung/ }).check();
    await usd.fill('9');
    await caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ }).check();
    await expect(discard).toBeEnabled();

    await discard.click();

    await expect(caps.getByRole('radio', { name: /^Begrenzt/ })).toBeChecked();
    await expect(usd).toHaveValue('5');
    await expect(caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ })).toHaveCount(0);
    await expect(discard).toBeDisabled();
    await expect(save).toBeDisabled();
    expect(puts).toHaveLength(0);
  });

  test('bestätigt höhere Fallback-Werte, aber nicht Senkungen, und akzeptiert keine Sentinel-Werte', async ({ page }) => {
    await stubQuietCockpit(page);
    const puts: DesktopWrite[] = [];
    await installDesktopRoute(page, makeConfig('bounded', configured(), 5, 100), puts);
    await openSettings(page);

    const caps = capRegion(page);
    const usd = caps.getByLabel('Gespeicherter USD-Fallback pro Budgetperiode');
    const calls = caps.getByLabel('Gespeicherter Aufruf-Fallback pro Budgetperiode');
    const save = caps.getByRole('button', { name: 'Cap-Policy speichern' });
    await usd.fill('10');
    await calls.fill('200');
    await expect(save).toBeDisabled();
    await caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ }).check();
    await save.click();
    await expect(caps.getByRole('status')).toContainText('Gespeichert');
    expect(updatesOf(puts[0]).caps?.confirm_widening).toBe(true);
    expect(updatesOf(puts[0]).budget).toEqual({ period_ceiling_usd: 10, max_calls: 200 });

    await usd.fill('4');
    await calls.fill('50');
    await expect(caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ })).toHaveCount(0);
    await expect(save).toBeEnabled();
    await save.click();
    await expect.poll(() => puts.length).toBe(2);
    expect(updatesOf(puts[1]).caps).not.toHaveProperty('confirm_widening');

    await expect(caps.getByRole('status')).toContainText('Gespeichert');
    await usd.fill('0');
    await expect(save).toBeDisabled();
    await expect(usd).toHaveAttribute('aria-invalid', 'true');
    await expect(usd).toHaveAttribute('aria-describedby', /cap-period-usd-error/);
    await expect(caps.getByRole('alert').filter({ hasText: 'USD-Fallback' })).toBeVisible();
    await usd.fill('4');
    await calls.fill('2.5');
    await expect(save).toBeDisabled();
    await expect(calls).toHaveAttribute('aria-invalid', 'true');
    await expect(calls).toHaveAttribute('aria-describedby', /cap-max-calls-error/);
    await expect(caps.getByRole('alert').filter({ hasText: 'positive ganze Zahl' })).toBeVisible();
    await expect(calls).toHaveValue('2.5');
  });

  test('behält den riskanten Entwurf und verwirft den Ack nach einer Backend-Ablehnung', async ({ page }) => {
    await stubQuietCockpit(page);
    let canonical = makeConfig('bounded');
    let putCount = 0;
    let getCount = 0;
    await page.route('**/api/desktop/settings', async (route) => {
      if (route.request().method() === 'PUT') {
        putCount += 1;
        if (putCount === 1) {
          await route.fulfill({ status: 400, json: { ok: false, error: 'Risk-Ack vom Backend abgelehnt.' } });
          return;
        }
        canonical = applyDesktopWrite(canonical, route.request().postDataJSON() as DesktopWrite);
      } else {
        getCount += 1;
      }
      await route.fulfill({ json: envelope(canonical) });
    });
    await openSettings(page);

    const caps = capRegion(page);
    await caps.getByRole('radio', { name: /^Unbegrenzte Ausführung/ }).check();
    const ack = caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ });
    await ack.check();
    await caps.getByRole('button', { name: 'Cap-Policy speichern' }).click();
    await expect(caps.getByRole('alert').filter({ hasText: 'Risk-Ack vom Backend abgelehnt.' })).toBeVisible();
    await expect(caps.getByRole('alert')).toContainText('Speichern abgelehnt');
    await expect(caps.getByRole('alert')).not.toContainText('nicht eindeutig');
    await expect(ack).not.toBeChecked();
    await expect(caps.locator('.cap-disabled-disclosure')).toBeVisible();
    await expect(caps.getByRole('button', { name: 'Cap-Policy speichern' })).toBeDisabled();

    await ack.check();
    await caps.getByRole('button', { name: 'Cap-Policy speichern' }).click();
    await expect(caps.getByRole('status')).toContainText('Unbegrenzte Daedalus-Ausführung');
  });

  test('reconciles a lost Cap-save response before the consent controls unlock', async ({ page }) => {
    await stubQuietCockpit(page);
    let canonical = makeConfig('bounded');
    let gets = 0;
    let releaseCanonicalRead: (() => void) | undefined;
    await page.route('**/api/desktop/settings', async (route) => {
      if (route.request().method() === 'PUT') {
        canonical = applyDesktopWrite(canonical, route.request().postDataJSON() as DesktopWrite);
        await route.abort('connectionreset');
        return;
      }
      gets += 1;
      if (gets === 2) {
        await new Promise<void>((resolve) => { releaseCanonicalRead = resolve; });
      }
      await route.fulfill({ json: envelope(canonical) });
    });
    await openSettings(page);

    const caps = capRegion(page);
    const save = caps.getByRole('button', { name: 'Cap-Policy speichern' });
    await caps.getByRole('radio', { name: /^Unbegrenzte Ausführung/ }).check();
    await caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ }).check();
    await save.click();

    await expect.poll(() => Boolean(releaseCanonicalRead)).toBe(true);
    await expect(caps.getByRole('radio', { name: /^Unbegrenzte Ausführung/ })).toBeDisabled();
    await expect(save).toBeDisabled();
    releaseCanonicalRead?.();

    await expect(caps.getByRole('radio', { name: /^Unbegrenzte Ausführung/ })).toBeChecked();
    await expect(caps.getByRole('radio', { name: /^Unbegrenzte Ausführung/ })).toBeEnabled();
    await expect(save).toBeDisabled();
    await expect(caps.getByRole('alert').filter({ hasText: 'Speicherergebnis nicht eindeutig' })).toContainText(
      'aktuelle Desktop-Stand wurde neu gelesen'
    );
    expect(gets).toBe(2);
  });

  test('retains a Cap draft when a marker-bearing HTTP 200 silently ignores it', async ({ page }) => {
    await stubQuietCockpit(page);
    const canonical = makeConfig('bounded');
    let gets = 0;
    let releaseCanonicalRead: (() => void) | undefined;
    await page.route('**/api/desktop/settings', async (route) => {
      if (route.request().method() === 'PUT') {
        await route.fulfill({ json: envelope(canonical) });
        return;
      }
      gets += 1;
      if (gets === 2) {
        await new Promise<void>((resolve) => { releaseCanonicalRead = resolve; });
      }
      await route.fulfill({ json: envelope(canonical) });
    });
    await openSettings(page);

    const caps = capRegion(page);
    const mode = caps.getByRole('radio', { name: /^Unbegrenzte Ausführung/ });
    const save = caps.getByRole('button', { name: 'Cap-Policy speichern' });
    await mode.check();
    await caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ }).check();
    await save.click();

    await expect.poll(() => Boolean(releaseCanonicalRead)).toBe(true);
    await expect(mode).toBeDisabled();
    releaseCanonicalRead?.();

    await expect(mode).toBeChecked();
    await expect(mode).toBeEnabled();
    await expect(caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ })).not.toBeChecked();
    await expect(save).toBeDisabled();
    await expect(caps.getByRole('alert')).toContainText('angeforderten Cap- und Budgetänderungen nicht');
    await expect(caps.getByRole('alert')).toContainText('nicht eindeutig');
    expect(gets).toBe(2);
  });

  test('hält Cap- und Verbindungsentwürfe bei beiden PUT-Richtungen getrennt', async ({ page }) => {
    await stubQuietCockpit(page);
    const puts: DesktopWrite[] = [];
    await installDesktopRoute(page, makeConfig('custom'), puts);
    await openSettings(page);

    const caps = capRegion(page);
    const model = page.getByLabel('Ollama-Modell');
    const usd = caps.getByLabel('Gespeicherter USD-Fallback pro Budgetperiode');
    await model.fill('ungespeichertes-modell');
    await usd.fill('4');
    await caps.getByRole('button', { name: 'Cap-Policy speichern' }).click();
    await expect(caps.getByRole('status')).toContainText('Gespeichert');
    expect(puts[0]).toEqual({
      section_updates: {
        caps: expect.any(Object),
        budget: expect.objectContaining({ period_ceiling_usd: 4 })
      }
    });
    await expect(model).toHaveValue('ungespeichertes-modell');

    const periodSwitch = caps.getByRole('switch', { name: 'Globale Periodenkosten (USD) begrenzen' });
    await periodSwitch.uncheck();
    await page.getByRole('button', { name: 'Verbindungen speichern' }).click();
    await expect.poll(() => puts.length).toBe(2);
    expect(puts[1]).toEqual({
      section_updates: {
        bridge: expect.any(Object),
        ollama: expect.objectContaining({ model: 'ungespeichertes-modell' })
      }
    });
    await expect(periodSwitch).not.toBeChecked();
  });

  test('adopts backend-normalized connection fields after a Cap save without creating connection dirtiness', async ({ page }) => {
    await stubQuietCockpit(page);
    let canonical = makeConfig('bounded');
    const puts: DesktopWrite[] = [];
    await page.route('**/api/desktop/settings', async (route) => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON() as DesktopWrite;
        puts.push(clone(body));
        canonical = applyDesktopWrite(canonical, body);
        canonical.ollama.model = 'server-normalized:latest';
      }
      await route.fulfill({ json: envelope(canonical) });
    });
    await openSettings(page);

    const caps = capRegion(page);
    await caps.getByLabel('Gespeicherter USD-Fallback pro Budgetperiode').fill('4');
    await caps.getByRole('button', { name: 'Cap-Policy speichern' }).click();
    await expect.poll(() => puts.length).toBe(1);

    await expect(page.getByLabel('Ollama-Modell')).toHaveValue('server-normalized:latest');
    await expect(page.getByRole('button', { name: 'Verbindungen speichern' })).toBeDisabled();
  });

  test('invalidates a widening acknowledgement while a newer Cap baseline is loading', async ({ page }) => {
    await stubQuietCockpit(page);
    let canonical = makeConfig('bounded');
    let gets = 0;
    let releaseRefresh: (() => void) | undefined;
    await page.route('**/api/desktop/settings', async (route) => {
      gets += 1;
      if (gets === 2) {
        await new Promise<void>((resolve) => { releaseRefresh = resolve; });
        canonical = makeConfig('bounded', configured(), 6, 100);
      }
      await route.fulfill({ json: envelope(canonical) });
    });
    await openSettings(page);

    const caps = capRegion(page);
    await caps.getByRole('radio', { name: /^Unbegrenzte Ausführung/ }).check();
    const ack = caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ });
    await ack.check();
    const refreshed = page.waitForResponse((response) => (
      response.request().method() === 'GET' && response.url().endsWith('/api/desktop/settings')
    ));
    await page.getByRole('button', { name: 'Neu prüfen' }).click();
    await expect.poll(() => Boolean(releaseRefresh)).toBe(true);
    await expect(ack).toBeDisabled();
    await expect(ack).not.toBeChecked();

    releaseRefresh?.();
    await refreshed;
    await expect(ack).toBeEnabled();
    await expect(ack).not.toBeChecked();
    await expect(caps.getByRole('button', { name: 'Cap-Policy speichern' })).toBeDisabled();
    expect(gets).toBe(2);
  });

  test('keeps a dirty Cap draft read-only when a refresh has no valid canonical policy', async ({ page }) => {
    await stubQuietCockpit(page);
    const canonical = makeConfig('bounded');
    let returnMalformed = false;
    let puts = 0;
    await page.route('**/api/desktop/settings', async (route) => {
      if (route.request().method() === 'PUT') {
        puts += 1;
        await route.fulfill({ status: 500, json: { ok: false, error: 'must not write' } });
        return;
      }
      const next = clone(canonical);
      if (returnMalformed) delete (next as { caps?: FixtureConfig['caps'] }).caps;
      await route.fulfill({ json: envelope(next) });
    });
    await openSettings(page);

    const caps = capRegion(page);
    const usd = caps.getByLabel('Gespeicherter USD-Fallback pro Budgetperiode');
    const save = caps.getByRole('button', { name: 'Cap-Policy speichern' });
    await usd.fill('4');
    returnMalformed = true;
    const refreshed = page.waitForResponse((response) => (
      response.request().method() === 'GET' && response.url().endsWith('/api/desktop/settings')
    ));
    await page.getByRole('button', { name: 'Neu prüfen' }).click();
    await refreshed;

    await expect(usd).toHaveValue('4');
    await expect(caps.getByRole('alert').filter({ hasText: 'keine gültige Ausführungs-Cap-Policy' })).toBeVisible();
    await expect(caps.getByRole('alert').filter({ hasText: 'Server-Policy ist nicht bestätigt' })).toBeVisible();
    await expect(usd).toBeDisabled();
    await expect(save).toBeDisabled();
    expect(puts).toBe(0);
  });
});

test.describe('Settings interaction integrity', () => {
  test('preserves an unsaved connection draft on refresh and refuses an obsolete service start', async ({ page }) => {
    await stubQuietCockpit(page);
    const puts: DesktopWrite[] = [];
    await installDesktopRoute(page, makeConfig(), puts);
    let serviceStarts = 0;
    await page.route('**/api/desktop/services/ollama/start', async (route) => {
      serviceStarts += 1;
      await route.fulfill({ json: { ok: true, service: { state: 'alive' } } });
    });
    await openSettings(page);

    const model = page.getByLabel('Ollama-Modell');
    await expect(model).toHaveValue('qwen2.5-coder:7b');
    await model.fill('draft-model:latest');
    await expect(page.getByText(/Verbindungsänderungen sind noch nicht gespeichert/)).toBeVisible();

    const refreshed = page.waitForResponse((response) => (
      response.url().endsWith('/api/desktop/settings') && response.request().method() === 'GET'
    ));
    await page.getByRole('button', { name: 'Neu prüfen' }).click();
    await refreshed;
    await expect(model).toHaveValue('draft-model:latest');

    const ollamaService = page.locator('.service-status').filter({ hasText: 'Ollama' });
    await ollamaService.getByRole('button', { name: 'Prüfen und übernehmen: Ollama' }).click();
    await expect(page.getByText(/Bitte zuerst speichern, damit die Prüfung keinen veralteten Endpoint übernimmt/)).toBeVisible();
    expect(serviceStarts).toBe(0);
    await expect(model).toHaveValue('draft-model:latest');

    await page.getByRole('button', { name: 'Verbindungen speichern' }).click();
    await expect.poll(() => puts.length).toBe(1);
    expect(updatesOf(puts[0]).ollama?.model).toBe('draft-model:latest');
    await ollamaService.getByRole('button', { name: 'Prüfen und übernehmen: Ollama' }).click();
    await expect.poll(() => serviceStarts).toBe(1);
  });

  test('does not send section updates to an older Desktop backend that cannot confirm the contract', async ({ page }) => {
    await stubQuietCockpit(page);
    const config = makeConfig();
    let puts = 0;
    await page.route('**/api/desktop/settings', async (route) => {
      if (route.request().method() === 'PUT') puts += 1;
      const body = envelope(config);
      delete body.desktop.settings_update_contract;
      await route.fulfill({ json: body });
    });
    await openSettings(page);

    const connections = page.locator('section.settings-section').filter({
      has: page.getByText('Dienste & Verbindungen', { exact: true })
    });
    const model = connections.getByLabel('Ollama-Modell');
    const save = connections.getByRole('button', { name: 'Verbindungen speichern' });
    await model.fill('must-remain-local');

    await expect(model).toHaveValue('must-remain-local');
    await expect(save).toBeDisabled();
    await expect(connections.getByRole('alert')).toContainText('bestätigt keine atomaren Bereichs-Updates');
    expect(puts).toBe(0);
  });

  test('tracks overlapping runtime probes independently', async ({ page }) => {
    const runtimes = [
      {
        id: 'alpha', label: 'Alpha Runtime', mode: 'cli', available: true,
        auth_status: 'cli_detected', selected_model: '', last_error: '', local: true,
        trusted_with_ip: true, can_write: false, agentic: false
      },
      {
        id: 'beta', label: 'Beta Runtime', mode: 'cli', available: true,
        auth_status: 'cli_detected', selected_model: '', last_error: '', local: true,
        trusted_with_ip: true, can_write: false, agentic: false
      }
    ];
    await stubQuietCockpit(page, runtimes);
    await installDesktopRoute(page, makeConfig(), []);

    let releaseAlpha!: () => void;
    let releaseBeta!: () => void;
    const alphaMayFinish = new Promise<void>((resolve) => { releaseAlpha = resolve; });
    const betaMayFinish = new Promise<void>((resolve) => { releaseBeta = resolve; });
    await page.route('**/api/runtimes/*/test', async (route) => {
      const id = decodeURIComponent(route.request().url().split('/').at(-2) || '');
      await (id === 'alpha' ? alphaMayFinish : betaMayFinish);
      await route.fulfill({ json: { ok: true, test: { ok: true, detail: `${id} ready`, mode: 'cli' } } });
    });
    await openSettings(page);

    const alphaRow = page.locator('.reach li').filter({ hasText: 'Alpha Runtime' });
    const betaRow = page.locator('.reach li').filter({ hasText: 'Beta Runtime' });
    const alphaButton = alphaRow.getByRole('button', { name: 'Testen' });
    const betaButton = betaRow.getByRole('button', { name: 'Testen' });
    const alphaRequest = page.waitForRequest('**/api/runtimes/alpha/test');
    await alphaButton.click();
    await alphaRequest;
    const betaRequest = page.waitForRequest('**/api/runtimes/beta/test');
    await betaButton.click();
    await betaRequest;

    await expect(alphaRow.getByRole('button')).toBeDisabled();
    await expect(betaRow.getByRole('button')).toBeDisabled();
    releaseAlpha();
    await expect(alphaRow.getByRole('button', { name: 'Testen' })).toBeEnabled();
    await expect(betaRow.getByRole('button')).toBeDisabled();
    releaseBeta();
    await expect(betaRow.getByRole('button', { name: 'Testen' })).toBeEnabled();
    await expect(alphaRow).toContainText('alpha ready');
    await expect(betaRow).toContainText('beta ready');
  });

  test('makes the mounted drawer inert while it is closed', async ({ page }) => {
    await stubQuietCockpit(page);
    await installDesktopRoute(page, makeConfig(), []);
    await openSettings(page);

    const panel = page.locator('.settings');
    await expect(panel).not.toHaveAttribute('inert', '');
    await panel.locator('.settings-close').click();
    await expect(panel).toHaveAttribute('aria-hidden', 'true');
    await expect(panel).toHaveAttribute('inert', '');

    const hiddenClose = panel.locator('.settings-close');
    await hiddenClose.evaluate((element) => (element as HTMLButtonElement).focus());
    expect(await hiddenClose.evaluate((element) => document.activeElement === element)).toBe(false);
  });

  test('keeps the pointer-dismiss scrim interactive while Settings is modal', async ({ page }) => {
    await stubQuietCockpit(page);
    await installDesktopRoute(page, makeConfig(), []);
    await openSettings(page);

    const scrim = page.locator('.settings-scrim');
    await expect(scrim).toBeVisible();
    await expect(scrim).not.toHaveAttribute('inert', '');
    await scrim.click({ position: { x: 8, y: 8 } });

    await expect(page.getByRole('dialog', { name: 'Einstellungen' })).not.toBeVisible();
    await expect(page.getByRole('button', { name: /^Einstellungen/ })).toBeFocused();
  });

  test('applies the Brain preference explicitly, minimally, and preserves the draft on close', async ({ page }) => {
    await page.addInitScript(() => {
      const state = window as typeof window & { __settingsWrites?: string[] };
      state.__settingsWrites = [];
      const original = Storage.prototype.setItem;
      Storage.prototype.setItem = function setItem(key: string, value: string) {
        if (key === 'daedalus-brain') state.__settingsWrites!.push(`${key}:${value}`);
        return original.call(this, key, value);
      };
      localStorage.removeItem('daedalus-brain');
    });
    await stubQuietCockpit(page, [{
      id: 'alpha', label: 'Alpha Runtime', mode: 'cli', available: true,
      auth_status: 'cli_detected', selected_model: '', last_error: '', local: true,
      trusted_with_ip: true, can_write: false, agentic: false
    }]);
    await installDesktopRoute(page, makeConfig(), []);
    await openSettings(page);

    const actions = page.locator('.general-settings-actions');
    const apply = actions.getByRole('button', { name: 'Brain übernehmen' });
    const discard = actions.getByRole('button', { name: 'Verwerfen' });
    const automatic = page.getByRole('radio', { name: 'Automatisch' });
    const alpha = page.getByRole('radio', { name: 'Alpha Runtime' });

    await alpha.click();
    await automatic.click();
    await expect(apply).toBeDisabled();
    await expect(discard).toBeDisabled();
    expect(await page.evaluate(() => (
      (window as typeof window & { __settingsWrites?: string[] }).__settingsWrites
    ))).toEqual([]);

    await alpha.click();
    await page.locator('.settings-close').click();
    await page.getByRole('button', { name: /^Einstellungen/ }).click();
    await expect(alpha).toBeChecked();
    expect(await page.evaluate(() => localStorage.getItem('daedalus-brain'))).toBeNull();

    await apply.click();
    await expect(apply).toBeDisabled();
    expect(await page.evaluate(() => localStorage.getItem('daedalus-brain'))).toBe('alpha');
    expect(await page.evaluate(() => (
      (window as typeof window & { __settingsWrites?: string[] }).__settingsWrites
    ))).toEqual(['daedalus-brain:alpha']);

    await automatic.click();
    await apply.click();
    expect(await page.evaluate(() => (
      (window as typeof window & { __settingsWrites?: string[] }).__settingsWrites
    ))).toEqual([
      'daedalus-brain:alpha',
      'daedalus-brain:'
    ]);

    await alpha.click();
    await discard.click();
    await expect(automatic).toBeChecked();
    expect(await page.evaluate(() => (
      (window as typeof window & { __settingsWrites?: string[] }).__settingsWrites
    ))).toHaveLength(2);

    await alpha.click();
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: /^Einstellungen/ }).click();
    await expect(alpha).toBeChecked();
    expect(await page.evaluate(() => (
      (window as typeof window & { __settingsWrites?: string[] }).__settingsWrites
    ))).toHaveLength(2);
    await discard.click();
  });

  test('implements the announced Brain radio-group keyboard contract', async ({ page }) => {
    await stubQuietCockpit(page, [
      {
        id: 'alpha', label: 'Alpha Runtime', mode: 'cli', available: true,
        auth_status: 'cli_detected', selected_model: '', last_error: '', local: true,
        trusted_with_ip: true, can_write: false, agentic: false
      },
      {
        id: 'beta', label: 'Beta Runtime', mode: 'cli', available: true,
        auth_status: 'cli_detected', selected_model: '', last_error: '', local: true,
        trusted_with_ip: true, can_write: false, agentic: false
      }
    ]);
    await installDesktopRoute(page, makeConfig(), []);
    await openSettings(page);

    const automatic = page.getByRole('radio', { name: 'Automatisch' });
    const alpha = page.getByRole('radio', { name: 'Alpha Runtime' });
    const beta = page.getByRole('radio', { name: 'Beta Runtime' });
    await automatic.focus();
    await expect(automatic).toBeFocused();
    await expect(automatic).toHaveAttribute('tabindex', '0');
    await expect(alpha).toHaveAttribute('tabindex', '-1');

    await page.keyboard.press('ArrowRight');
    await expect(alpha).toBeFocused();
    await expect(alpha).toBeChecked();
    await expect(alpha).toHaveAttribute('tabindex', '0');
    await expect(automatic).toHaveAttribute('tabindex', '-1');

    await page.keyboard.press('End');
    await expect(beta).toBeFocused();
    await expect(beta).toBeChecked();
    await page.keyboard.press('ArrowRight');
    await expect(automatic).toBeFocused();
    await expect(automatic).toBeChecked();
  });

  test('rebases a clean general draft when the Cockpit owner changes Brain outside Settings', async ({ page }) => {
    await page.addInitScript(() => {
      const state = window as typeof window & { __brainWrites?: string[] };
      state.__brainWrites = [];
      const original = Storage.prototype.setItem;
      Storage.prototype.setItem = function setItem(key: string, value: string) {
        if (key === 'daedalus-brain') state.__brainWrites!.push(value);
        return original.call(this, key, value);
      };
      localStorage.removeItem('daedalus-brain');
    });
    await stubQuietCockpit(page, [{
      id: 'alpha', label: 'Alpha Runtime', mode: 'cli', available: true,
      auth_status: 'cli_detected', selected_model: '', last_error: '', local: true,
      trusted_with_ip: true, can_write: false, agentic: false
    }]);
    await installDesktopRoute(page, makeConfig(), []);
    await openSettings(page);
    await page.locator('.settings-close').click();

    await page
      .getByRole('navigation', { name: 'Ansicht' })
      .getByRole('button', { name: 'Gespräch', exact: true })
      .click();
    await page.getByRole('button', { name: /Wer antwortet: Automatisch/ }).click();
    await page.getByRole('option', { name: /Alpha Runtime/ }).click();
    await expect(page.getByRole('button', { name: /Wer antwortet: Alpha Runtime/ })).toBeVisible();
    await page.getByRole('button', { name: /^Einstellungen/ }).click();

    const actions = page.locator('.general-settings-actions');
    const apply = actions.getByRole('button', { name: 'Brain übernehmen' });
    await expect(page.getByRole('radio', { name: 'Alpha Runtime' })).toBeChecked();
    await expect(apply).toBeDisabled();
    expect(await page.evaluate(() => (
      (window as typeof window & { __brainWrites?: string[] }).__brainWrites
    ))).toEqual(['alpha']);

  });

  test('derives connection dirtiness and merges a late server refresh before save', async ({ page }) => {
    await stubQuietCockpit(page);
    let canonical = makeConfig();
    const puts: DesktopWrite[] = [];
    let gets = 0;
    let releaseRefresh!: () => void;
    const refreshMayFinish = new Promise<void>((resolve) => { releaseRefresh = resolve; });
    await page.route('**/api/desktop/settings', async (route) => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON() as DesktopWrite;
        puts.push(clone(body));
        canonical = applyDesktopWrite(canonical, body);
        await route.fulfill({ json: envelope(canonical) });
        return;
      }
      gets += 1;
      if (gets === 2) {
        await refreshMayFinish;
      }
      await route.fulfill({ json: envelope(canonical) });
    });
    await openSettings(page);

    const model = page.getByLabel('Ollama-Modell');
    const save = page.getByRole('button', { name: 'Verbindungen speichern' });
    await expect(save).toBeDisabled();
    await model.fill('temporary-model');
    await expect(save).toBeEnabled();
    await model.fill('qwen2.5-coder:7b');
    await expect(save).toBeDisabled();
    expect(puts).toHaveLength(0);

    await model.fill('draft-after-request');
    const refreshRequest = page.waitForRequest((request) => (
      request.url().endsWith('/api/desktop/settings') && request.method() === 'GET'
    ));
    const refreshResponse = page.waitForResponse((response) => (
      response.url().endsWith('/api/desktop/settings') && response.request().method() === 'GET'
    ));
    await page.getByRole('button', { name: 'Neu prüfen' }).click();
    await refreshRequest;
    await expect(model).toBeDisabled();
    canonical.budget.max_calls = 777;
    canonical.ide.docker_image = 'daedalus/openvscode-server:1.110.0';
    canonical.bridge.auto_start = false;
    canonical.ollama.remote.host = 'server-updated.example';
    releaseRefresh();
    await refreshResponse;
    await expect(model).toHaveValue('draft-after-request');

    await save.click();
    await expect.poll(() => puts.length).toBe(1);
    expect(puts[0]).toEqual({
      section_updates: {
        bridge: { auto_start: false },
        ollama: expect.objectContaining({
          model: 'draft-after-request',
          remote: expect.objectContaining({ host: 'server-updated.example' })
        })
      }
    });
    await expect(save).toBeDisabled();
  });

  for (const committed of [true, false]) {
    test(`reconciles a lost connection-save response before unlocking (${committed ? 'committed' : 'not committed'})`, async ({ page }) => {
      await stubQuietCockpit(page);
      let canonical = makeConfig();
      let gets = 0;
      let puts = 0;
      let releaseCanonicalRead: (() => void) | undefined;
      await page.route('**/api/desktop/settings', async (route) => {
        if (route.request().method() === 'PUT') {
          puts += 1;
          if (committed) {
            canonical = applyDesktopWrite(canonical, route.request().postDataJSON() as DesktopWrite);
          }
          await route.abort('connectionreset');
          return;
        }
        gets += 1;
        if (gets === 2) {
          await new Promise<void>((resolve) => { releaseCanonicalRead = resolve; });
        }
        await route.fulfill({ json: envelope(canonical) });
      });
      await openSettings(page);

      const model = page.getByLabel('Ollama-Modell');
      const save = page.getByRole('button', { name: 'Verbindungen speichern' });
      await model.fill('ambiguous-model:latest');
      await save.click();

      await expect.poll(() => Boolean(releaseCanonicalRead)).toBe(true);
      await expect(model).toBeDisabled();
      await expect(save).toBeDisabled();
      releaseCanonicalRead?.();

      await expect(model).toHaveValue('ambiguous-model:latest');
      await expect(model).toBeEnabled();
      if (committed) await expect(save).toBeDisabled();
      else await expect(save).toBeEnabled();
      await expect(page.getByRole('alert').filter({ hasText: 'Speicherergebnis nicht eindeutig' })).toContainText(
        'aktuelle Desktop-Stand wurde neu gelesen'
      );
      expect(puts).toBe(1);
      expect(gets).toBe(2);
    });
  }

  test('retains a connection draft when a marker-bearing HTTP 200 silently ignores it', async ({ page }) => {
    await stubQuietCockpit(page);
    const canonical = makeConfig();
    let gets = 0;
    let releaseCanonicalRead: (() => void) | undefined;
    await page.route('**/api/desktop/settings', async (route) => {
      if (route.request().method() === 'PUT') {
        await route.fulfill({ json: envelope(canonical) });
        return;
      }
      gets += 1;
      if (gets === 2) {
        await new Promise<void>((resolve) => { releaseCanonicalRead = resolve; });
      }
      await route.fulfill({ json: envelope(canonical) });
    });
    await openSettings(page);

    const model = page.getByLabel('Ollama-Modell');
    const save = page.getByRole('button', { name: 'Verbindungen speichern' });
    await model.fill('must-not-be-lost:latest');
    await save.click();

    await expect.poll(() => Boolean(releaseCanonicalRead)).toBe(true);
    await expect(model).toBeDisabled();
    releaseCanonicalRead?.();

    await expect(model).toHaveValue('must-not-be-lost:latest');
    await expect(model).toBeEnabled();
    await expect(save).toBeEnabled();
    const outcome = page.getByRole('alert').filter({ hasText: 'Speicherergebnis nicht eindeutig' });
    await expect(outcome).toContainText('angeforderten Verbindungsänderungen nicht');
    await expect(outcome).toContainText('nicht eindeutig');
    expect(gets).toBe(2);
  });

  test('keeps a rejected connection draft without an unnecessary canonical reread', async ({ page }) => {
    await stubQuietCockpit(page);
    const canonical = makeConfig();
    let gets = 0;
    let puts = 0;
    await page.route('**/api/desktop/settings', async (route) => {
      if (route.request().method() === 'PUT') {
        puts += 1;
        await route.fulfill({ status: 400, json: { ok: false, error: 'connection validation refused' } });
        return;
      }
      gets += 1;
      await route.fulfill({ json: envelope(canonical) });
    });
    await openSettings(page);

    const connections = page.locator('section.settings-section').filter({
      has: page.getByText('Dienste & Verbindungen', { exact: true })
    });
    const model = connections.getByLabel('Ollama-Modell');
    const save = connections.getByRole('button', { name: 'Verbindungen speichern' });
    await model.fill('rejected-draft:latest');
    await save.click();

    await expect(connections.getByRole('alert')).toContainText('Speichern abgelehnt');
    await expect(connections.getByRole('alert')).toContainText('connection validation refused');
    await expect(connections.getByRole('alert')).not.toContainText('nicht eindeutig');
    await expect(model).toHaveValue('rejected-draft:latest');
    await expect(save).toBeEnabled();
    expect(puts).toBe(1);
    expect(gets).toBe(1);
  });

  test('reconciles a lost local-Ollama adoption response before enabling another action', async ({ page }) => {
    await stubQuietCockpit(page);
    const canonical = makeConfig();
    let gets = 0;
    let releaseCanonicalRead: (() => void) | undefined;
    await page.route('**/api/desktop/settings', async (route) => {
      gets += 1;
      if (gets === 2) {
        await new Promise<void>((resolve) => { releaseCanonicalRead = resolve; });
      }
      await route.fulfill({ json: envelope(canonical) });
    });
    await page.route('**/api/desktop/services/ollama/start', (route) => route.abort('connectionreset'));
    await openSettings(page);

    const ollama = page.locator('.service-status').filter({ hasText: 'Ollama' });
    const adopt = ollama.getByRole('button', { name: 'Prüfen und übernehmen: Ollama' });
    await adopt.click();
    await expect.poll(() => Boolean(releaseCanonicalRead)).toBe(true);
    await expect(adopt).toBeDisabled();

    releaseCanonicalRead?.();
    await expect(adopt).toBeEnabled();
    await expect(page.getByRole('alert').filter({ hasText: 'Ergebnis der Dienstaktion nicht eindeutig' })).toContainText(
      'aktuelle Desktop-Stand wurde neu gelesen'
    );
    expect(gets).toBe(2);
  });

  test('reports a rejected local-Ollama adoption without calling it ambiguous or rereading settings', async ({ page }) => {
    await stubQuietCockpit(page);
    const canonical = makeConfig();
    let gets = 0;
    await page.route('**/api/desktop/settings', async (route) => {
      gets += 1;
      await route.fulfill({ json: envelope(canonical) });
    });
    await page.route('**/api/desktop/services/ollama/start', (route) => route.fulfill({
      status: 403,
      json: { ok: false, error: 'ollama adoption denied' }
    }));
    await openSettings(page);

    const adopt = page.getByRole('button', { name: 'Prüfen und übernehmen: Ollama' });
    await adopt.click();

    const connections = page.locator('section.settings-section').filter({
      has: page.getByText('Dienste & Verbindungen', { exact: true })
    });
    await expect(connections.getByRole('alert')).toContainText('Dienstaktion abgelehnt');
    await expect(connections.getByRole('alert')).toContainText('ollama adoption denied');
    await expect(connections.getByRole('alert')).not.toContainText('nicht eindeutig');
    await expect(adopt).toBeEnabled();
    expect(gets).toBe(1);
  });

  test('can discard a connection draft after a failed refresh without writing', async ({ page }) => {
    await stubQuietCockpit(page);
    const canonical = makeConfig();
    let gets = 0;
    let puts = 0;
    await page.route('**/api/desktop/settings', async (route) => {
      if (route.request().method() === 'PUT') {
        puts += 1;
        await route.fulfill({ status: 500, json: { ok: false, error: 'must not write' } });
        return;
      }
      gets += 1;
      if (gets === 2) {
        await route.fulfill({ status: 503, json: { ok: false, error: 'temporary settings read failure' } });
        return;
      }
      await route.fulfill({ json: envelope(canonical) });
    });
    await openSettings(page);

    const connections = page.locator('section.settings-section').filter({
      has: page.getByText('Dienste & Verbindungen', { exact: true })
    });
    const model = connections.getByLabel('Ollama-Modell');
    const discard = connections.getByRole('button', { name: 'Verwerfen', exact: true });
    await model.fill('dirty-model');
    await page.getByRole('button', { name: 'Neu prüfen' }).click();
    await expect(connections.getByText(/Entwurf bleibt erhalten/)).toBeVisible();
    await expect(discard).toBeEnabled();
    await discard.click();

    await expect(model).toHaveValue('qwen2.5-coder:7b');
    await expect(discard).toBeDisabled();
    await expect(connections.getByRole('button', { name: 'Verbindungen speichern' })).toBeDisabled();
    expect(puts).toBe(0);
  });

  test('rejects a malformed desktop snapshot without crashing or losing the draft', async ({ page }) => {
    await stubQuietCockpit(page);
    const canonical = makeConfig();
    let gets = 0;
    let puts = 0;
    await page.route('**/api/desktop/settings', async (route) => {
      if (route.request().method() === 'PUT') {
        puts += 1;
        await route.fulfill({ status: 500, json: { ok: false, error: 'must not write' } });
        return;
      }
      gets += 1;
      await route.fulfill({
        json: gets === 2 ? { ok: true, desktop: { config: {} } } : envelope(canonical)
      });
    });
    await openSettings(page);

    const model = page.getByLabel('Ollama-Modell');
    const save = page.getByRole('button', { name: 'Verbindungen speichern' });
    await model.fill('draft-survives-malformed-response');
    const malformed = page.waitForResponse((response) => (
      response.request().method() === 'GET' && response.url().endsWith('/api/desktop/settings')
    ));
    await page.getByRole('button', { name: 'Neu prüfen' }).click();
    await malformed;

    await expect(page.getByRole('dialog', { name: 'Einstellungen' })).toBeVisible();
    await expect(page.getByRole('alert').filter({ hasText: 'unvollständige Einstellungen' })).toBeVisible();
    await expect(model).toHaveValue('draft-survives-malformed-response');
    await expect(save).toBeDisabled();
    expect(puts).toBe(0);

    await capRegion(page).getByRole('button', { name: 'Erneut laden' }).click();
    await expect(model).toHaveValue('draft-survives-malformed-response');
    await expect(save).toBeEnabled();
    expect(puts).toBe(0);
  });

  test('keeps remote SSH unavailable without impairing local Ollama', async ({ page }) => {
    await stubQuietCockpit(page);
    const puts: DesktopWrite[] = [];
    await installDesktopRoute(page, makeConfig(), puts);
    await openSettings(page);

    const mode = page.getByLabel('Ollama läuft');
    const remote = mode.locator('option[value="remote_ssh"]');
    await expect(remote).toHaveAttribute('disabled', '');
    await expect(remote).toContainText('nicht verfügbar');
    await expect(mode).toHaveValue('local');
    await expect(page.getByText(/Peer-\/Fingerprint-Nachweis/)).toBeVisible();

    const localEndpoint = page.getByLabel('Lokaler Endpoint');
    await expect(localEndpoint).toBeEnabled();
    await localEndpoint.fill('http://127.0.0.1:12434');
    const save = page.getByRole('button', { name: 'Verbindungen speichern' });
    await expect(save).toBeEnabled();
    await save.click();

    await expect.poll(() => puts.length).toBe(1);
    expect(updatesOf(puts[0]).ollama).toEqual(expect.objectContaining({
      mode: 'local',
      local_host: 'http://127.0.0.1:12434'
    }));
    const bridge = page.locator('.service-status').filter({ hasText: 'Bridge' });
    const ollama = page.locator('.service-status').filter({ hasText: 'Ollama' });
    await expect(bridge.getByRole('button', { name: 'Starten: Bridge — nicht verfügbar' })).toBeDisabled();
    await expect(page.getByText(
      'python -m daedalus.file_bridge watch --project <registered-project>',
      { exact: true }
    )).toBeVisible();
    await expect(page.getByRole('dialog', { name: 'Einstellungen' })).not.toContainText('daedalus watcher');
    await expect(page.getByRole('checkbox', { name: /Bridge automatisch starten/ })).toBeDisabled();
    await expect(page.getByRole('checkbox', { name: /Ollama automatisch starten/ })).toBeDisabled();
    await expect(ollama.getByRole('button', { name: 'Prüfen und übernehmen: Ollama' })).toBeEnabled();
    await expect(page.getByText(/startet keinen Ollama-Prozess/)).toBeVisible();
  });

  test('renders a persisted remote SSH setting but only permits repair back to local', async ({ page }) => {
    await stubQuietCockpit(page);
    const config = makeConfig();
    config.ollama.mode = 'remote_ssh';
    const puts: DesktopWrite[] = [];
    await installDesktopRoute(page, config, puts);
    await openSettings(page);

    const mode = page.getByLabel('Ollama läuft');
    await expect(mode).toHaveValue('remote_ssh');
    await expect(page.getByRole('group', { name: /Remote-SSH-Einstellungen/ })).toBeVisible();
    await expect(page.getByLabel('SSH Host')).toBeDisabled();
    const bridge = page.locator('.service-status').filter({ hasText: 'Bridge' });
    const ollama = page.locator('.service-status').filter({ hasText: 'Ollama' });
    await expect(bridge.getByRole('button', { name: 'Starten: Bridge — nicht verfügbar' })).toBeDisabled();
    await expect(ollama.getByRole('button', { name: 'Prüfen und übernehmen: Ollama' })).toBeDisabled();

    await mode.selectOption('local');
    await expect(page.getByLabel('Lokaler Endpoint')).toBeEnabled();
    const save = page.getByRole('button', { name: 'Verbindungen speichern' });
    await expect(save).toBeEnabled();
    await save.click();

    await expect.poll(() => puts.length).toBe(1);
    expect(updatesOf(puts[0]).ollama).toEqual(expect.objectContaining({ mode: 'local' }));
  });

  test('refuses to apply a Brain draft that became unreachable', async ({ page }) => {
    await page.addInitScript(() => localStorage.removeItem('daedalus-brain'));
    await stubQuietCockpit(page, [{
      id: 'alpha', label: 'Alpha Runtime', mode: 'cli', available: true,
      auth_status: 'cli_detected', selected_model: '', last_error: '', local: true,
      trusted_with_ip: true, can_write: false, agentic: false
    }]);
    await installDesktopRoute(page, makeConfig(), []);
    await openSettings(page);
    await page.getByRole('radio', { name: 'Alpha Runtime' }).click();

    let releaseRefresh: (() => void) | undefined;
    await page.route('**/api/runtimes/status', async (route) => {
      await new Promise<void>((resolve) => { releaseRefresh = resolve; });
      await route.fulfill({
        json: { ok: true, generated_at: '', project: 'atlas', warnings: [], runtimes: [] }
      });
    });
    await page.getByRole('button', { name: 'Neu prüfen' }).click();
    const apply = page.getByRole('button', { name: 'Brain übernehmen' });
    await expect.poll(() => Boolean(releaseRefresh)).toBe(true);
    const automatic = page.getByRole('radio', { name: 'Automatisch' });
    const alpha = page.getByRole('radio', { name: 'Alpha Runtime' });
    await expect(alpha).toBeDisabled();
    await expect(alpha).toHaveAttribute('tabindex', '-1');
    await expect(automatic).toBeEnabled();
    await expect(automatic).toHaveAttribute('tabindex', '0');
    await expect(apply).toBeDisabled();
    expect(await page.evaluate(() => localStorage.getItem('daedalus-brain'))).toBeNull();
    releaseRefresh?.();
    await expect(page.getByRole('alert').filter({ hasText: 'nicht mehr erreichbar' })).toBeVisible();
    await expect(apply).toBeDisabled();
    expect(await page.evaluate(() => localStorage.getItem('daedalus-brain'))).toBeNull();
  });

  test('rebases untouched cap fields from a newer server snapshot', async ({ page }) => {
    await stubQuietCockpit(page);
    let canonical = makeConfig();
    const puts: DesktopWrite[] = [];
    await page.route('**/api/desktop/settings', async (route) => {
      if (route.request().method() === 'PUT') {
        const body = route.request().postDataJSON() as DesktopWrite;
        puts.push(clone(body));
        canonical = applyDesktopWrite(canonical, body);
      }
      await route.fulfill({ json: envelope(canonical) });
    });
    await openSettings(page);

    const caps = capRegion(page);
    const usd = caps.getByLabel('Gespeicherter USD-Fallback pro Budgetperiode');
    const calls = caps.getByLabel('Gespeicherter Aufruf-Fallback pro Budgetperiode');
    await usd.fill('4');
    canonical.budget.max_calls = 777;
    const refreshed = page.waitForResponse((response) => (
      response.url().endsWith('/api/desktop/settings') && response.request().method() === 'GET'
    ));
    await page.getByRole('button', { name: 'Neu prüfen' }).click();
    await refreshed;
    await expect(usd).toHaveValue('4');
    await expect(calls).toHaveValue('777');

    await caps.getByRole('button', { name: 'Cap-Policy speichern' }).click();
    await expect.poll(() => puts.length).toBe(1);
    expect(updatesOf(puts[0]).budget).toEqual({ period_ceiling_usd: 4, max_calls: 777 });
  });

  test('keeps focus inside Settings and does not open the command palette underneath', async ({ page }) => {
    await stubQuietCockpit(page, [{
      id: 'alpha', label: 'Alpha Runtime', mode: 'cli', available: true,
      auth_status: 'cli_detected', selected_model: '', last_error: '', local: true,
      trusted_with_ip: true, can_write: false, agentic: false
    }]);
    await installDesktopRoute(page, makeConfig(), []);
    await openSettings(page);

    const settings = page.getByRole('dialog', { name: 'Einstellungen' });
    await expect(page.locator('.settings-close')).toBeFocused();
    for (let i = 0; i < 20; i += 1) {
      await page.keyboard.press('Tab');
      expect(await settings.evaluate((root) => root.contains(document.activeElement))).toBe(true);
    }
    for (let i = 0; i < 8; i += 1) {
      await page.keyboard.press('Shift+Tab');
      expect(await settings.evaluate((root) => root.contains(document.activeElement))).toBe(true);
    }
    await settings.evaluate((root) => {
      const selector = [
        'a[href]', 'button:not(:disabled)', 'input:not(:disabled)',
        'select:not(:disabled)', 'textarea:not(:disabled)', 'summary',
        '[tabindex]:not([tabindex="-1"])'
      ].join(',');
      const items = Array.from(root.querySelectorAll<HTMLElement>(selector)).filter(
        (element) => element.offsetParent !== null
      );
      items.at(-1)?.focus();
    });
    await page.keyboard.press('Tab');
    await expect(page.locator('.settings-close')).toBeFocused();

    let releaseProbe: (() => void) | undefined;
    await page.route('**/api/runtimes/*/test', async (route) => {
      await new Promise<void>((resolve) => { releaseProbe = resolve; });
      await route.fulfill({ json: { ok: true, generated_at: '', project: 'atlas', warnings: [], runtime: {} } });
    });
    const lastTest = settings.getByRole('button', { name: 'Testen' }).last();
    await lastTest.click();
    await expect.poll(() => Boolean(releaseProbe)).toBe(true);
    await expect(lastTest).toBeDisabled();
    await page.keyboard.press('Tab');
    await expect(page.locator('.settings-close')).toBeFocused();
    releaseProbe?.();

    await page.keyboard.press('Control+K');
    await expect(page.locator('.palette-scrim')).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(settings).not.toBeVisible();
    await expect(page.getByRole('button', { name: /^Einstellungen/ })).toBeFocused();
  });
});
