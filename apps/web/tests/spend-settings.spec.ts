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

function envelope(config: FixtureConfig) {
  return {
    ok: true,
    generated_at: '',
    project: null,
    warnings: [],
    desktop: {
      config: clone(config),
      config_path: 'C:\\Users\\test\\AppData\\Local\\Daedalus\\desktop.json',
      credential_policy: {
        ssh_key_only: true,
        stores_passwords: false,
        stores_private_key_bytes: false,
        host_key_verification: 'strict'
      },
      services: {
        bridge: { managed: true, state: 'alive' },
        ollama: {
          mode: config.ollama.mode,
          endpoint: config.ollama.local_host,
          reachable: true,
          tunnel_running: false,
          local_process_running: true,
          host_key_pinned: false
        },
        ide: {
          mode: config.ide.mode,
          endpoint: config.ide.endpoint,
          reachable: false
        }
      }
    }
  };
}

async function stubQuietCockpit(page: Page): Promise<void> {
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
    json: { ok: true, generated_at: '', project: project.name, warnings: [], runtimes: [] }
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
  puts: FixtureConfig[]
): Promise<void> {
  let canonical = clone(initial);
  await page.route('**/api/desktop/settings', async (route) => {
    if (route.request().method() === 'PUT') {
      const body = route.request().postDataJSON() as FixtureConfig;
      puts.push(clone(body));
      canonical = persisted(body);
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
    await expect(caps.getByText('Ariadne ist noch nicht live')).toBeVisible();
    releaseFirst();
    await expect(caps.getByRole('alert').filter({ hasText: 'Cap-Snapshot fehlgeschlagen.' })).toBeVisible();

    await caps.getByRole('button', { name: 'Erneut laden' }).click();
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
    const puts: FixtureConfig[] = [];
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
    expect(puts[0].caps).toEqual({
      mode: 'custom',
      configured: configured(Object.fromEntries(AXES.map(({ id }) => [id, false])) as Partial<CapConfigured>),
      confirm_widening: true
    });
    expect(puts[0].budget).not.toHaveProperty('confirm_widening');
    await expect(caps.locator('.cap-disabled-disclosure')).toBeVisible();
  });

  test('erzwingt Ack für bounded→custom und unbounded, setzt ihn bei jeder Änderung zurück', async ({ page }) => {
    await stubQuietCockpit(page);
    const puts: FixtureConfig[] = [];
    await installDesktopRoute(page, makeConfig('bounded'), puts);
    await openSettings(page);

    const caps = capRegion(page);
    await caps.getByRole('radio', { name: /^Individuell/ }).check();
    await expect(caps.getByRole('button', { name: 'Cap-Policy speichern' })).toBeDisabled();
    await caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ }).check();
    await caps.getByRole('button', { name: 'Cap-Policy speichern' }).click();
    await expect.poll(() => puts.length).toBe(1);
    expect(puts[0].caps.confirm_widening).toBe(true);

    await expect(caps.getByRole('status')).toContainText('Individuelle Cap-Policy');
    await caps.getByRole('radio', { name: /^Begrenzt/ }).check();
    await expect(caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ })).toHaveCount(0);
    await caps.getByRole('button', { name: 'Cap-Policy speichern' }).click();
    await expect.poll(() => puts.length).toBe(2);
    expect(puts[1].caps).not.toHaveProperty('confirm_widening');

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
    expect(puts[2].caps.confirm_widening).toBe(true);
    expect(puts[2].budget.period_ceiling_usd).toBe(6);
    await expect(caps.getByRole('status')).toContainText('Unbegrenzte Daedalus-Ausführung');
    await expect(caps.locator('.cap-disabled-disclosure li')).toHaveCount(8);

    await page.getByRole('button', { name: 'Neu prüfen' }).click();
    await expect(caps.getByRole('radio', { name: /^Unbegrenzte Ausführung/ })).toBeChecked();
    await expect(caps.locator('.cap-disabled-disclosure li')).toHaveCount(8);
    await expect(caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ })).toHaveCount(0);
  });

  test('bestätigt höhere Fallback-Werte, aber nicht Senkungen, und akzeptiert keine Sentinel-Werte', async ({ page }) => {
    await stubQuietCockpit(page);
    const puts: FixtureConfig[] = [];
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
    expect(puts[0].caps.confirm_widening).toBe(true);
    expect(puts[0].budget).toEqual({ period_ceiling_usd: 10, max_calls: 200 });

    await usd.fill('4');
    await calls.fill('50');
    await expect(caps.getByRole('checkbox', { name: /Risiko bewusst bestätigen/ })).toHaveCount(0);
    await expect(save).toBeEnabled();
    await save.click();
    await expect.poll(() => puts.length).toBe(2);
    expect(puts[1].caps).not.toHaveProperty('confirm_widening');

    await expect(caps.getByRole('status')).toContainText('Gespeichert');
    await usd.fill('0');
    await expect(save).toBeDisabled();
    await expect(caps.getByRole('alert').filter({ hasText: 'USD-Fallback' })).toBeVisible();
    await usd.fill('4');
    await calls.fill('2.5');
    await expect(save).toBeDisabled();
    await expect(caps.getByRole('alert').filter({ hasText: 'positive ganze Zahl' })).toBeVisible();
    await expect(calls).toHaveValue('2.5');
  });

  test('behält den riskanten Entwurf und verwirft den Ack nach einer Backend-Ablehnung', async ({ page }) => {
    await stubQuietCockpit(page);
    let canonical = makeConfig('bounded');
    let putCount = 0;
    await page.route('**/api/desktop/settings', async (route) => {
      if (route.request().method() === 'PUT') {
        putCount += 1;
        if (putCount === 1) {
          await route.fulfill({ status: 400, json: { ok: false, error: 'Risk-Ack vom Backend abgelehnt.' } });
          return;
        }
        canonical = persisted(route.request().postDataJSON() as FixtureConfig);
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
    await expect(ack).not.toBeChecked();
    await expect(caps.locator('.cap-disabled-disclosure')).toBeVisible();
    await expect(caps.getByRole('button', { name: 'Cap-Policy speichern' })).toBeDisabled();

    await ack.check();
    await caps.getByRole('button', { name: 'Cap-Policy speichern' }).click();
    await expect(caps.getByRole('status')).toContainText('Unbegrenzte Daedalus-Ausführung');
  });

  test('hält Cap- und Verbindungsentwürfe bei beiden PUT-Richtungen getrennt', async ({ page }) => {
    await stubQuietCockpit(page);
    const puts: FixtureConfig[] = [];
    await installDesktopRoute(page, makeConfig('custom'), puts);
    await openSettings(page);

    const caps = capRegion(page);
    const model = page.getByLabel('Ollama-Modell');
    const usd = caps.getByLabel('Gespeicherter USD-Fallback pro Budgetperiode');
    await model.fill('ungespeichertes-modell');
    await usd.fill('4');
    await caps.getByRole('button', { name: 'Cap-Policy speichern' }).click();
    await expect(caps.getByRole('status')).toContainText('Gespeichert');
    expect(puts[0].ollama.model).toBe('qwen2.5-coder:7b');
    expect(puts[0].budget.period_ceiling_usd).toBe(4);
    expect(puts[0].ide.docker_image).toBe('daedalus/openvscode-server:1.109.5');
    await expect(model).toHaveValue('ungespeichertes-modell');

    const periodSwitch = caps.getByRole('switch', { name: 'Globale Periodenkosten (USD) begrenzen' });
    await periodSwitch.uncheck();
    await page.getByRole('button', { name: 'Verbindungen speichern' }).click();
    await expect.poll(() => puts.length).toBe(2);
    expect(puts[1].ollama.model).toBe('ungespeichertes-modell');
    expect(puts[1].caps.configured.period_usd).toBe(true);
    expect(puts[1].budget.period_ceiling_usd).toBe(4);
    await expect(periodSwitch).not.toBeChecked();
  });
});
