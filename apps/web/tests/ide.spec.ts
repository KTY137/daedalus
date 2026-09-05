import { expect, test, type Page } from '@playwright/test';
import { NOT_BUILT } from './_app';

async function openCockpit(page: Page, path = '/') {
  const response = await page.goto(path, { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
}

const project = { name: 'atlas', repo_root: 'C:\\work\\atlas', team: {} };

async function stubQuietCockpit(page: import('@playwright/test').Page) {
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], projects: [project] } });
  });
  await page.route('**/api/structure**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], structure: { graph: { nodes: [], edges: [] } } }
  }));
}

async function installControlledConversationEvents(page: Page) {
  await page.addInitScript(() => {
    class ControlledConversationEventSource {
      static readonly CONNECTING = 0;
      static readonly OPEN = 1;
      static readonly CLOSED = 2;
      readonly CONNECTING = 0;
      readonly OPEN = 1;
      readonly CLOSED = 2;
      readonly url: string;
      readonly withCredentials = false;
      readyState = ControlledConversationEventSource.OPEN;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      private readonly listeners = new Map<string, Set<(event: Event) => void>>();

      constructor(url: string | URL) {
        this.url = String(url);
        controlledSources.push(this);
      }

      addEventListener(type: string, listener: EventListenerOrEventListenerObject | null) {
        if (!listener) return;
        const callback = typeof listener === 'function'
          ? listener
          : (event: Event) => listener.handleEvent(event);
        const listeners = this.listeners.get(type) || new Set<(event: Event) => void>();
        listeners.add(callback);
        this.listeners.set(type, listeners);
      }

      removeEventListener() { /* the fixture owns its short-lived page */ }

      dispatchEvent(event: Event) {
        for (const listener of this.listeners.get(event.type) || []) listener(event);
        if (event.type === 'error') this.onerror?.(event);
        return true;
      }

      close() {
        this.readyState = ControlledConversationEventSource.CLOSED;
      }

      emit(type: string, data: Record<string, unknown>) {
        this.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(data) }));
      }
    }

    const controlledSources: ControlledConversationEventSource[] = [];
    Object.defineProperty(window, 'EventSource', {
      configurable: true,
      value: ControlledConversationEventSource,
    });
    Object.defineProperty(window, '__emitConversationEvent', {
      configurable: true,
      value: (requestId: number, type: string, data: Record<string, unknown>) => {
        const suffix = `/turns/${requestId}/events`;
        const source = controlledSources.find((candidate) => candidate.url.endsWith(suffix));
        if (!source) throw new Error(`no controlled EventSource for ${suffix}`);
        source.emit(type, data);
      },
    });
    Object.defineProperty(window, '__hasConversationEventSource', {
      configurable: true,
      value: (requestId: number) => {
        const suffix = `/turns/${requestId}/events`;
        return controlledSources.some((candidate) => candidate.url.endsWith(suffix));
      },
    });
  });
}

async function emitConversationEvent(page: Page, requestId: number, type: string, data: Record<string, unknown>) {
  await page.evaluate(
    ({ requestId, type, data }) => (window as unknown as {
      __emitConversationEvent: (id: number, event: string, payload: Record<string, unknown>) => void;
    }).__emitConversationEvent(requestId, type, data),
    { requestId, type, data },
  );
}

async function hasConversationEventSource(page: Page, requestId: number) {
  return page.evaluate(
    (id) => (window as unknown as {
      __hasConversationEventSource: (candidate: number) => boolean;
    }).__hasConversationEventSource(id),
    requestId,
  );
}

async function openProjectDialog(page: Page) {
  await page.locator('.scope-trigger').click();
  await page.locator('.scope-add').click();
  const dialog = page.getByRole('dialog', { name: 'Projekt hinzufügen' });
  await expect(dialog).toBeVisible();
  return dialog;
}

async function emulateTauriPlatform(page: Page, platform: string) {
  await page.addInitScript((value) => {
    Object.defineProperty(window, '__TAURI_INTERNALS__', {
      configurable: true,
      value: {}
    });
    Object.defineProperty(navigator, 'platform', {
      configurable: true,
      get: () => value
    });
  }, platform);
}

test.describe('IDE and project registration', () => {
  test('a zero-project cockpit still exposes the existing-folder registration flow', async ({ page }) => {
    let rows: typeof project[] = [];
    let posted: unknown;
    await page.route('**/api/projects', async (route) => {
      if (route.request().method() === 'POST') {
        posted = route.request().postDataJSON();
        rows = [project];
        await route.fulfill({
          json: {
            ok: true,
            generated_at: '',
            project: project.name,
            warnings: [],
            registered_project: { name: project.name, repo_root: project.repo_root },
            created: true
          }
        });
        return;
      }
      await route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], projects: rows } });
    });
    await page.route('**/api/structure**', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: project.name, warnings: [], structure: { graph: { nodes: [], edges: [] } } }
    }));

    await openCockpit(page);
    await page.getByRole('button', { name: /Projekt hinzufügen/ }).click();
    await page.getByRole('button', { name: /Projekt hinzufügen \/ Ordner öffnen/ }).click();

    const dialog = page.getByRole('dialog', { name: 'Projekt hinzufügen' });
    await expect(dialog).toBeVisible();
    // This suite drives the browser build, not Tauri. A native picker here is
    // a false affordance: browsers cannot disclose an existing folder's local
    // path to the backend. Direct path registration remains fully usable.
    await expect(dialog.getByRole('button', { name: 'Durchsuchen …' })).toHaveCount(0);
    await expect(dialog.getByText(/vollständigen lokalen Pfad direkt/)).toBeVisible();
    await dialog.getByLabel('Projektordner').fill(project.repo_root);
    await dialog.getByLabel(/Name/).fill(project.name);
    await dialog.getByRole('button', { name: 'Ordner öffnen' }).click();

    await expect(dialog).toBeHidden();
    await expect(page.locator('.scope-name').first()).toHaveText(project.name);
    expect(posted).toEqual({ repo_root: project.repo_root, name: project.name });
  });

  test('a newly registered project wins over an existing reachable default', async ({ page }) => {
    const existing = { name: 'existing', repo_root: 'C:\\work\\existing', team: {}, reachable: true };
    let rows = [existing];
    await page.route('**/api/projects', async (route) => {
      if (route.request().method() === 'POST') {
        rows = [existing, { ...project, reachable: true }];
        await route.fulfill({
          json: {
            ok: true,
            generated_at: '',
            project: project.name,
            warnings: [],
            registered_project: { name: project.name, repo_root: project.repo_root },
            created: true
          }
        });
        return;
      }
      await route.fulfill({
        json: { ok: true, generated_at: '', project: null, warnings: [], projects: rows }
      });
    });
    await page.route('**/api/structure**', (route) => {
      const selected = new URL(route.request().url()).searchParams.get('project');
      return route.fulfill({
        json: { ok: true, generated_at: '', project: selected, warnings: [], structure: { graph: { nodes: [], edges: [] } } }
      });
    });

    await openCockpit(page);
    await expect(page.locator('.scope-name').first()).toHaveText(existing.name);
    const dialog = await openProjectDialog(page);
    await dialog.getByLabel('Projektordner').fill(project.repo_root);
    await dialog.getByLabel(/Name/).fill(project.name);
    await dialog.getByRole('button', { name: 'Ordner öffnen' }).click();

    await expect(dialog).toBeHidden();
    await expect(page.locator('.scope-name').first()).toHaveText(project.name);
  });

  test('the newest project-list request wins when registration races the initial read', async ({ page }) => {
    let getCount = 0;
    let initialCompleted = false;
    let releaseInitial: () => void = () => {};
    const initialGate = new Promise<void>((resolve) => {
      releaseInitial = resolve;
    });
    await page.route('**/api/projects', async (route) => {
      if (route.request().method() === 'POST') {
        await route.fulfill({
          json: {
            ok: true,
            generated_at: '',
            project: project.name,
            warnings: [],
            registered_project: { name: project.name, repo_root: project.repo_root },
            created: true
          }
        });
        return;
      }
      getCount += 1;
      if (getCount === 1) {
        await initialGate;
        await route.fulfill({
          json: { ok: true, generated_at: '', project: null, warnings: [], projects: [] }
        });
        initialCompleted = true;
        return;
      }
      await route.fulfill({
        json: {
          ok: true,
          generated_at: '',
          project: null,
          warnings: [],
          projects: [{ ...project, reachable: true }]
        }
      });
    });
    await page.route('**/api/structure**', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: project.name, warnings: [], structure: { graph: { nodes: [], edges: [] } } }
    }));

    await openCockpit(page);
    await expect.poll(() => getCount).toBe(1);
    const dialog = await openProjectDialog(page);
    await dialog.getByLabel('Projektordner').fill(project.repo_root);
    await dialog.getByLabel(/Name/).fill(project.name);
    await dialog.getByRole('button', { name: 'Ordner öffnen' }).click();

    await expect.poll(() => getCount).toBe(2);
    await expect(dialog).toBeHidden();
    await expect(page.locator('.scope-name').first()).toHaveText(project.name);
    releaseInitial();
    await expect.poll(() => initialCompleted).toBe(true);
    await expect(page.locator('.scope-name').first()).toHaveText(project.name);
  });

  test('known-stale-only registration data defaults to adding a project', async ({ page }) => {
    let structureRequests = 0;
    const stale = { name: 'stale', repo_root: 'C:\\missing\\stale', team: {}, reachable: false };
    await page.route('**/api/projects', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: null, warnings: [], projects: [stale] }
    }));
    await page.route('**/api/structure**', (route) => {
      structureRequests += 1;
      return route.fulfill({ status: 500, json: { ok: false, error: 'must not scan a known-missing checkout' } });
    });

    await openCockpit(page);

    await expect(page.locator('.scope-name').first()).toHaveText('Projekt hinzufügen');
    await expect(page.getByRole('heading', { name: 'Kein erreichbarer Checkout ausgewählt.' })).toBeVisible();
    await expect(page.getByText(/vollständigen lokalen Pfad eines bestehenden Checkouts/)).toBeVisible();
    expect(structureRequests).toBe(0);
    await page.locator('.scope-trigger').click();
    await expect(page.getByRole('button', { name: 'stale · Pfad fehlt' })).toBeVisible();
  });

  test('an explicit stale project URL keeps its identity and labels the missing path', async ({ page }) => {
    const stale = { name: 'stale', repo_root: 'C:\\missing\\stale', team: {}, reachable: false };
    const present = { ...project, reachable: true };
    let structureProject = '';
    await page.route('**/api/projects', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: null, warnings: [], projects: [stale, present] }
    }));
    await page.route('**/api/structure**', (route) => {
      structureProject = new URL(route.request().url()).searchParams.get('project') || '';
      return route.fulfill({
        status: 500,
        json: { ok: false, error: 'the explicitly selected checkout is missing' }
      });
    });

    await openCockpit(page, '/?project=stale');

    await expect(page.locator('.scope-name').first()).toHaveText('stale · Pfad fehlt');
    await expect.poll(() => structureProject).toBe('stale');
  });

  test('the first observed reachable checkout wins over earlier unknown and stale rows', async ({ page }) => {
    // Empty optional preferences must not accidentally match this malformed
    // row and outrank the first checkout the backend actually observed.
    const legacyUnknown = { name: 'legacy-unknown', repo_root: '', team: {} };
    const stale = { name: 'stale', repo_root: '', team: {}, reachable: false };
    const present = { ...project, reachable: true };
    let structureProject = '';
    await page.route('**/api/projects', (route) => route.fulfill({
      json: {
        ok: true,
        generated_at: '',
        project: null,
        warnings: [],
        projects: [legacyUnknown, stale, present]
      }
    }));
    await page.route('**/api/structure**', (route) => {
      structureProject = new URL(route.request().url()).searchParams.get('project') || '';
      return route.fulfill({
        json: { ok: true, generated_at: '', project: structureProject, warnings: [], structure: { graph: { nodes: [], edges: [] } } }
      });
    });

    await openCockpit(page);

    await expect(page.locator('.scope-name').first()).toHaveText(project.name);
    await expect.poll(() => structureProject).toBe(project.name);
  });

  test('an older project payload without reachability keeps first-row compatibility', async ({ page }) => {
    const legacyFirst = { name: 'legacy-first', repo_root: 'C:\\legacy\\first', team: {} };
    await page.route('**/api/projects', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: null, warnings: [], projects: [legacyFirst, project] }
    }));
    await page.route('**/api/structure**', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: legacyFirst.name, warnings: [], structure: { graph: { nodes: [], edges: [] } } }
    }));

    await openCockpit(page);

    await expect(page.locator('.scope-name').first()).toHaveText(legacyFirst.name);
  });

  for (const platform of ['Win32', 'MacIntel']) {
    test(`Tauri on ${platform} exposes the capability-backed native folder picker`, async ({ page }) => {
      await emulateTauriPlatform(page, platform);
      await stubQuietCockpit(page);

      await openCockpit(page);
      const dialog = await openProjectDialog(page);

      await expect(dialog.getByRole('button', { name: 'Durchsuchen …' })).toBeVisible();
      await expect(dialog.getByText(/keine Upload-Kopie/)).toBeVisible();
    });
  }

  test('Linux Tauri keeps the typed-path fallback because no dialog capability is granted', async ({ page }) => {
    await emulateTauriPlatform(page, 'Linux x86_64');
    await stubQuietCockpit(page);

    await openCockpit(page);
    const dialog = await openProjectDialog(page);

    await expect(dialog.getByRole('button', { name: 'Durchsuchen …' })).toHaveCount(0);
    await expect(dialog.getByText(/vollständigen lokalen Pfad direkt/)).toBeVisible();
  });

  test('shortcut 3 opens the selected checkout in the measured loopback IDE endpoint', async ({ page }) => {
    await stubQuietCockpit(page);
    await page.route('**/api/desktop/settings', (route) => route.fulfill({
      json: {
        ok: true,
        generated_at: '',
        project: null,
        warnings: [],
        desktop: { services: { ide: {
          mode: 'docker',
          endpoint: 'http://127.0.0.1:3000',
          ui_url: 'http://127.0.0.1:3000/?folder=/home/workspace',
          reachable: true,
          managed: true
        } } }
      }
    }));
    await page.route('http://127.0.0.1:3000/**', (route) => route.fulfill({ contentType: 'text/html', body: '<title>OpenVSCode</title>' }));

    await openCockpit(page);
    await page.keyboard.press('3');

    const frame = page.getByTitle(`OpenVSCode – ${project.name}`);
    await expect(frame).toBeVisible();
    const src = new URL((await frame.getAttribute('src'))!);
    expect(src.origin).toBe('http://127.0.0.1:3000');
    expect(src.searchParams.get('folder')).toBe('/home/workspace');
    await expect(page.getByRole('link', { name: 'Extern öffnen' })).toHaveAttribute('href', src.toString());
  });

  test('an unreachable IDE stays read-only when managed start is unavailable', async ({ page }) => {
    await stubQuietCockpit(page);
    let startRequests = 0;
    await page.route('**/api/desktop/settings', (route) => route.fulfill({
      json: {
        ok: true,
        generated_at: '',
        project: null,
        warnings: [],
        desktop: { services: { ide: {
          available: false,
          endpoint: 'http://127.0.0.1:3000',
          reachable: false,
          managed_start_available: false,
          availability_reason: 'Managed IDE start unavailable.'
        } } }
      }
    }));
    await page.route('**/api/desktop/services/ide/start', async (route) => {
      startRequests += 1;
      await route.fulfill({ status: 400, json: { ok: false, error: 'managed IDE start unavailable' } });
    });

    await openCockpit(page);
    await page.getByRole('button', { name: 'IDE', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'IDE-Start nicht verfügbar' })).toBeVisible();
    await expect(page.getByText(/startet in v0\.1\.6 keinen IDE-Prozess/)).toBeVisible();
    await expect(page.getByRole('button', { name: 'IDE starten' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Status neu prüfen' })).toBeVisible();
    expect(startRequests).toBe(0);
  });

  test('a missing desktop IDE capability does not expose a start action or raw endpoint error', async ({ page }) => {
    await stubQuietCockpit(page);
    await page.route('**/api/desktop/settings', (route) => route.fulfill({
      status: 404,
      json: { ok: false, error: 'unknown endpoint /api/desktop/settings' },
    }));

    await openCockpit(page);
    await page.keyboard.press('3');

    const notice = page.locator('.ide-notice');
    await expect(page.getByRole('heading', { name: 'IDE-Integration nicht verfügbar' })).toBeVisible();
    await expect(notice).toContainText('keinen gemessenen Desktop-IDE-Status');
    await expect(notice).not.toContainText('unknown endpoint');
    await expect(page.getByRole('button', { name: 'IDE starten' })).toHaveCount(0);
  });

  test('mobile IDE view hands off a reachable editor to desktop instead of embedding it', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await stubQuietCockpit(page);
    const url = `http://127.0.0.1:3000/?folder=${encodeURIComponent(project.repo_root)}`;
    await page.route('**/api/desktop/settings', (route) => route.fulfill({
      json: {
        ok: true,
        generated_at: '',
        project: null,
        warnings: [],
        desktop: { services: { ide: {
          mode: 'native', installed: true, available: true, reachable: true, running: true,
          endpoint: 'http://127.0.0.1:3000', ui_url: url, error: '', managed: true,
        } } },
      },
    }));

    await openCockpit(page);
    await page.keyboard.press('3');

    await expect(page.getByRole('heading', { name: 'IDE auf einem Desktop fortsetzen' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Auf Desktop öffnen' })).toHaveAttribute('href', url);
    await expect(page.locator('.ide-frame')).toHaveCount(0);
  });

  test('a draft remains pending until a person explicitly confirms its handoff', async ({ page }) => {
    let handedOff = false;
    let handoffCalls = 0;
    await stubQuietCockpit(page);
    await page.route('**/api/drafts**', async (route) => {
      if (route.request().method() === 'POST') {
        handoffCalls += 1;
        handedOff = true;
        await route.fulfill({ json: { ok: true, generated_at: '', project: project.name, warnings: [], applied: {} } });
        return;
      }
      await route.fulfill({
        json: {
          ok: true,
          generated_at: '',
          project: project.name,
          warnings: [],
          scope: project.repo_root,
          pending_count: handedOff ? 0 : 1,
          drafts: handedOff ? [] : [{
            id: 'draft-1', created: '2026-08-31', agent: 'Ikarus', objective: 'Testübergabe',
            paths: ['apps/web/src/cockpit/Decision.tsx'], status: 'pending', repo_root: project.repo_root,
          }],
        },
      });
    });

    await openCockpit(page);
    await page.getByRole('button', { name: 'Gespräch', exact: true }).click();
    const confirm = page.getByRole('button', { name: 'Übergabe bestätigen' });
    await expect(confirm).toBeVisible();
    await expect(page.locator('.decision-sub')).toContainText('explizite Bestätigung');
    await expect(page.locator('.decision-sub')).toContainText('belegt keine Repository-Änderung');
    expect(handoffCalls).toBe(0);

    await confirm.click();
    await expect.poll(() => handoffCalls).toBe(1);
  });

  test('draft list, detail and action callbacks cannot cross a project generation', async ({ page }) => {
    const alpha = { name: 'decision-alpha', repo_root: 'C:\\work\\decision-alpha', team: {}, reachable: true };
    const beta = { name: 'decision-beta', repo_root: 'C:\\work\\decision-beta', team: {}, reachable: true };
    let releaseDetail!: () => void;
    let releaseAction!: () => void;
    let releaseBeta!: () => void;
    const detailMayFinish = new Promise<void>((resolve) => { releaseDetail = resolve; });
    const actionMayFinish = new Promise<void>((resolve) => { releaseAction = resolve; });
    const betaMayFinish = new Promise<void>((resolve) => { releaseBeta = resolve; });
    let alphaListReads = 0;
    let betaListReads = 0;
    let actionCalls = 0;
    let actionReturned = false;

    await page.route('**/api/projects', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: null, warnings: [], projects: [alpha, beta] }
    }));
    await page.route('**/api/structure**', (route) => {
      const selected = new URL(route.request().url()).searchParams.get('project') || '';
      return route.fulfill({
        json: { ok: true, generated_at: '', project: selected, warnings: [], structure: { graph: { nodes: [], edges: [] } } }
      });
    });
    await page.route('**/api/runtimes/status**', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: null, warnings: [], runtimes: [] }
    }));
    await page.route((url) => url.pathname === '/api/conversations' && url.searchParams.has('project'), (route) =>
      route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], conversations: [] } })
    );
    await page.route((url) => url.pathname === '/api/drafts', async (route) => {
      const selected = new URL(route.request().url()).searchParams.get('project');
      if (!selected) {
        await route.fulfill({ json: {
          ok: true, generated_at: '', project: null, warnings: [], scope: null, pending_count: 0, drafts: []
        } });
        return;
      }
      const row = selected === beta.name ? beta : alpha;
      if (selected === beta.name) {
        betaListReads += 1;
        await betaMayFinish;
      } else {
        alphaListReads += 1;
      }
      await route.fulfill({ json: {
        ok: true, generated_at: '', project: row.name, warnings: [], scope: row.repo_root, pending_count: 1,
        drafts: [{
          id: `draft-${row.name}`, created: '2026-09-05', agent: 'Ikarus',
          objective: row === alpha ? 'Nur Alpha entscheiden' : 'Nur Beta entscheiden',
          paths: ['apps/web/src/app/Cockpit.tsx'], status: 'pending', repo_root: row.repo_root
        }]
      } });
    });
    await page.route((url) => url.pathname === '/api/drafts/draft-decision-alpha', async (route) => {
      await detailMayFinish;
      await route.fulfill({ json: {
        ok: true, generated_at: '', project: alpha.name, warnings: [],
        draft: {
          id: 'draft-decision-alpha', created: '2026-09-05', agent: 'Ikarus', objective: 'Nur Alpha entscheiden',
          paths: [], provider: 'test', persona: '', repo_root: alpha.repo_root, status: 'pending',
          report: {
            status: 'needs_review', summary: 'Vertrauliches Alpha-Detail', files_changed: [], tests_run: [], risks: [], todos: [], handoff: {}
          }
        }
      } });
    });
    await page.route((url) => url.pathname === '/api/drafts/draft-decision-alpha/apply', async (route) => {
      actionCalls += 1;
      await actionMayFinish;
      await route.fulfill({ json: { ok: true, generated_at: '', project: alpha.name, warnings: [], applied: {} } });
      actionReturned = true;
    });

    await openCockpit(page, `/?view=chat&project=${alpha.name}`);
    await expect(page.getByRole('heading', { name: 'Nur Alpha entscheiden' })).toBeVisible();
    await page.getByRole('button', { name: 'Warum' }).click();
    await page.getByRole('button', { name: 'Übergabe bestätigen' }).click();
    await expect.poll(() => actionCalls).toBe(1);

    await page.locator('.scope-trigger').click();
    await page.locator(`.scope-menu [data-project-name="${beta.name}"]`).click();
    await expect(page.locator('.scope-name')).toHaveText(beta.name);
    await expect(page.getByRole('heading', { name: 'Nur Alpha entscheiden' })).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Übergabe bestätigen' })).toHaveCount(0);
    await expect.poll(() => betaListReads).toBe(1);

    releaseDetail();
    releaseAction();
    await expect.poll(() => actionReturned).toBe(true);
    await page.waitForTimeout(150);
    releaseBeta();
    await expect(page.getByRole('heading', { name: 'Nur Beta entscheiden' })).toBeVisible();
    await expect(page.getByText('Vertrauliches Alpha-Detail')).toHaveCount(0);
    await page.waitForTimeout(100);
    expect(alphaListReads).toBe(1);
    expect(betaListReads).toBe(1);
    expect(actionCalls).toBe(1);
  });

  test('tablet status details are collapsible while the conversation stays first', async ({ page }) => {
    await page.setViewportSize({ width: 800, height: 900 });
    await stubQuietCockpit(page);

    await openCockpit(page);
    await page.getByRole('button', { name: 'Gespräch', exact: true }).click();

    const details = page.locator('#cockpit-status-details');
    // The toggle renames itself once open ("Statusdetails ausblenden"), so
    // it is held by its stable class rather than by the name it has while
    // closed — otherwise the last assertion looks for a button that no
    // longer exists.
    const toggle = page.locator('.status-details-toggle');
    await expect(toggle).toHaveText('Statusdetails anzeigen');
    await expect(details).toBeHidden();
    await toggle.click();
    await expect(details).toBeVisible();
    await expect(toggle).toHaveAttribute('aria-expanded', 'true');
    await expect(toggle).toHaveText('Statusdetails ausblenden');
  });

  test('an editor context from the URL is visibly attached and sent only in the canonical turn POST', async ({ page }) => {
    const contextRef = `editor-context:sha256:${'a'.repeat(64)}`;
    let turnBody: Record<string, unknown> | undefined;
    let turnPosts = 0;
    await stubQuietCockpit(page);
    await page.route('**/api/editor/contexts/**', (route) => route.fulfill({
      json: {
        ok: true,
        generated_at: '',
        project: project.name,
        warnings: [],
        context: {
          context_ref: contextRef,
          project: project.name,
          path: 'apps/web/src/cockpit/Conversation.tsx',
          selection_chars: 48,
          expires_at: '2099-01-01T00:00:00+00:00',
          expired: false,
          sensitivity: 'secret_floor_passed',
          inclusion_report: { accepted: true, reason: 'validated_local_context' },
        },
      },
    }));
    await page.route('**/api/conversations', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation_id: 'conv_context' },
    }));
    await page.route('**/api/conversations/*/turns', async (route) => {
      turnPosts += 1;
      const body = route.request().postDataJSON() as Record<string, unknown>;
      turnBody = body;
      await route.fulfill({
        status: 202,
        json: {
          ok: true,
          generated_at: '',
          project: project.name,
          warnings: [],
          created: true,
          turn_request: {
            request_id: 41,
            conversation_id: 'conv_context',
            client_request_id: body.client_request_id,
            project: project.name,
            state: 'streaming',
          },
        },
      });
    });
    await page.route('**/api/conversations/*/turns/*/events', (route) => route.abort('failed'));

    await openCockpit(page, `/?context_ref=${encodeURIComponent(contextRef)}`);
    await page.getByRole('button', { name: 'Gespräch', exact: true }).click();
    await expect(page.getByLabel('Editor-Anhang')).toContainText('akzeptiert');
    await expect(page.getByLabel('Editor-Anhang')).toContainText('Conversation.tsx');

    await page.getByLabel('Nachricht an Ikarus').fill('Nutze den sichtbaren Anhang.');
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect.poll(() => turnPosts).toBe(1);
    expect(turnBody).toMatchObject({
      project: project.name,
      message: 'Nutze den sichtbaren Anhang.',
      context_refs: [contextRef],
    });
    expect(typeof turnBody?.client_request_id).toBe('string');
  });

  test('a mismatched editor context is visible as withheld and never crosses the project boundary', async ({ page }) => {
    const contextRef = `editor-context:sha256:${'b'.repeat(64)}`;
    let turnBody: Record<string, unknown> | undefined;
    await stubQuietCockpit(page);
    await page.route('**/api/editor/contexts/**', (route) => route.fulfill({
      json: {
        ok: true,
        generated_at: '',
        project: 'other-project',
        warnings: [],
        context: {
          context_ref: contextRef,
          project: 'other-project',
          path: 'private.py', selection_chars: 4,
          expires_at: '2099-01-01T00:00:00+00:00', expired: false,
          sensitivity: 'secret_floor_passed', inclusion_report: { accepted: true },
        },
      },
    }));
    await page.route('**/api/conversations', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation_id: 'conv_withheld' },
    }));
    await page.route('**/api/conversations/*/turns', async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      turnBody = body;
      await route.fulfill({
        status: 202,
        json: { ok: true, generated_at: '', project: project.name, warnings: [], created: true, turn_request: {
          request_id: 42, conversation_id: 'conv_withheld', client_request_id: body.client_request_id,
          project: project.name, state: 'streaming',
        } },
      });
    });
    await page.route('**/api/conversations/*/turns/*/events', (route) => route.abort('failed'));

    await openCockpit(page, `/?context_ref=${encodeURIComponent(contextRef)}`);
    await page.getByRole('button', { name: 'Gespräch', exact: true }).click();
    await expect(page.getByLabel('Editor-Anhang')).toContainText(/nicht enthalten/i);
    await expect(page.getByLabel('Editor-Anhang')).toContainText('other-project');
    await page.getByLabel('Nachricht an Ikarus').fill('Keine Fremdkontexte.');
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect.poll(() => turnBody).toBeTruthy();
    expect(turnBody?.context_refs).toEqual([]);
  });

  test('Genesis releases its synchronous claim when secure request-key generation throws', async ({ page }) => {
    await page.addInitScript(() => {
      Object.defineProperty(globalThis.crypto, 'randomUUID', {
        configurable: true,
        value: () => { throw new Error('fixture WebCrypto failure'); },
      });
    });
    await stubQuietCockpit(page);
    let genesisPosts = 0;
    await page.route('**/api/genesis', async (route) => {
      genesisPosts += 1;
      await route.fulfill({ status: 503, json: { ok: false, error: 'fixture backend unavailable' } });
    });

    await openCockpit(page);
    await page.locator('.viewswitch').getByRole('button', { name: 'Genesis', exact: true }).click();
    const prompt = page.getByLabel('Produktbeschreibung');
    const submit = page.getByRole('button', { name: 'Genesis starten' });
    await prompt.fill('Eine lokale Aufgabenliste.');
    await submit.click();

    await expect(page.locator('.genesis-error')).toContainText('fixture WebCrypto failure');
    expect(genesisPosts, 'request-key failure reached the effectful Genesis route').toBe(0);
    await expect(submit).toBeEnabled();

    // A working generator on the next explicit submit must reach the route;
    // this proves the failed attempt released the ref claim, not only `pending`.
    await page.evaluate(() => {
      Object.defineProperty(globalThis.crypto, 'randomUUID', {
        configurable: true,
        value: () => '00000000-0000-4000-8000-000000000001',
      });
    });
    await submit.click();
    await expect.poll(() => genesisPosts).toBe(1);
    await expect(page.locator('.genesis-error')).toContainText('fixture backend unavailable');
    await expect(submit).toBeEnabled();
  });

  test('stream phases and completion use one concise live region without announcing token updates', async ({ page }) => {
    await installControlledConversationEvents(page);
    await stubQuietCockpit(page);
    await page.route('**/api/runtimes/status', (route) => route.fulfill({
      json: {
        ok: true,
        generated_at: '',
        project: project.name,
        warnings: [],
        runtimes: [{ id: 'ollama_http', label: 'Ollama', available: true }],
      },
    }));
    await page.route('**/api/conversations', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation_id: 'conv_live_region' },
    }));
    await page.route('**/api/conversations/*/turns', async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        status: 202,
        json: { ok: true, generated_at: '', project: project.name, warnings: [], created: true, turn_request: {
          request_id: 45, conversation_id: 'conv_live_region', client_request_id: body.client_request_id,
          project: project.name, state: 'streaming',
        } },
      });
    });

    await openCockpit(page);
    await page.getByRole('button', { name: 'Gespräch', exact: true }).click();
    const surface = page.getByRole('region', { name: 'Gespräch mit Ikarus' });
    const live = surface.locator('[data-conversation-live]');
    await expect(live).toHaveCount(1);
    await expect(surface.locator('[aria-live="polite"]')).toHaveCount(1);
    await expect(surface.locator('[role="status"]')).toHaveCount(1);
    await expect(live).toHaveAttribute('role', 'status');
    await expect(live).toHaveAttribute('aria-atomic', 'true');
    await expect(surface.locator('.convo-scroll')).toHaveAttribute('aria-live', 'off');

    await page.getByLabel('Nachricht an Ikarus').fill('Erkläre den aktuellen Stand.');
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect.poll(() => hasConversationEventSource(page, 45)).toBe(true);
    await expect(live).toHaveText('Anfrage angenommen.');
    await expect(surface.locator('.convo-scroll [role="status"]')).toHaveCount(0);
    await expect(surface.locator('.convo-elapsed')).toHaveAttribute('aria-hidden', 'true');

    await emitConversationEvent(page, 45, 'start', {
      intent: 'chat', shell: 'voice', provider_used: 'ollama_http',
    });
    await expect(live).toHaveText('Ollama ist ausgewählt.');
    await emitConversationEvent(page, 45, 'delta', { text: 'Hallo' });
    await expect(surface.locator('.turn.ikarus')).toContainText('Hallo');
    await expect(live).toHaveText('Ollama antwortet.');
    const beforeMoreTokens = await live.textContent();
    await emitConversationEvent(page, 45, 'delta', { text: ' Welt' });
    await expect(surface.locator('.turn.ikarus')).toContainText('Hallo Welt');
    await expect(live).toHaveText(beforeMoreTokens || 'Ollama antwortet.');

    await emitConversationEvent(page, 45, 'final', {
      ok: true, project: project.name, warnings: [], generated_at: '',
      intent: 'chat', shell: 'voice', provider_used: 'ollama_http',
      assistant: 'Hallo Welt',
    });
    await expect(live).toHaveText('Antwort abgeschlossen.');
    await expect(page.getByRole('button', { name: 'Senden' })).toBeVisible();
  });

  test('a terminal error state after restart settles the turn without a named error event', async ({ page }) => {
    await installControlledConversationEvents(page);
    await stubQuietCockpit(page);
    await page.route('**/api/conversations', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation_id: 'conv_restart_error' },
    }));
    let turnPosts = 0;
    await page.route('**/api/conversations/*/turns', async (route) => {
      turnPosts += 1;
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const requestId = 46 + turnPosts;
      await route.fulfill({
        status: 202,
        json: { ok: true, generated_at: '', project: project.name, warnings: [], created: true, turn_request: {
          request_id: requestId, conversation_id: 'conv_restart_error', client_request_id: body.client_request_id,
          project: project.name, state: 'streaming',
        } },
      });
    });

    await openCockpit(page);
    await page.getByRole('button', { name: 'Gespräch', exact: true }).click();
    const composer = page.getByLabel('Nachricht an Ikarus');
    await composer.fill('Erster Versuch');
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect.poll(() => hasConversationEventSource(page, 47)).toBe(true);

    // Restart reconciliation may have only this durable terminal snapshot;
    // deliberately emit no named `error` event and no optional error detail.
    await emitConversationEvent(page, 47, 'state', {
      request_id: 47,
      conversation_id: 'conv_restart_error',
      project: project.name,
      state: 'error',
      error: null,
    });
    await expect(page.locator('[data-conversation-live]')).toHaveText('Antwort fehlgeschlagen.');
    await expect(page.locator('.turn.ikarus').first()).toContainText('Der Turn ist fehlgeschlagen.');
    await expect(page.locator('.turn.ikarus').first()).toContainText('Der Server hat keinen Fehlergrund übermittelt.');
    await expect(page.locator('.convo-error')).toContainText('Ikarus-Turn fehlgeschlagen');
    await expect(page.getByRole('button', { name: 'Senden' })).toBeVisible();

    // Releasing `busy` alone is insufficient: a leaked synchronous send claim
    // also refuses the successor. A second accepted POST proves both cleared.
    await composer.fill('Zweiter Versuch');
    await expect(page.getByRole('button', { name: 'Senden' })).toBeEnabled();
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect.poll(() => turnPosts).toBe(2);
    await expect.poll(() => hasConversationEventSource(page, 48)).toBe(true);
    await emitConversationEvent(page, 48, 'final', {
      ok: true, project: project.name, warnings: [], generated_at: '',
      intent: 'chat', shell: 'voice', provider_used: 'deterministic',
      assistant: 'Wieder erreichbar.',
    });
    await expect(page.locator('.turn.ikarus').last()).toContainText('Wieder erreichbar.');
  });

  test('a streaming turn survives every Cockpit view and queues its proposal only after an explicit click', async ({ page }) => {
    await installControlledConversationEvents(page);
    // Negative evidence for the retired browser preference: an existing value
    // may remain in an old profile, but it must have no authority to dispatch.
    await page.addInitScript(() => localStorage.setItem('daedalus-autonomy', 'vorschlaege'));
    await stubQuietCockpit(page);
    await page.route('**/api/runtimes/status', (route) => route.fulfill({
      json: {
        ok: true,
        generated_at: '',
        project: project.name,
        warnings: [],
        runtimes: [{ id: 'ollama_http', label: 'Ollama', available: true }],
      },
    }));
    await page.route('**/api/conversations', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation_id: 'conv_view_handoff' },
    }));
    await page.route('**/api/conversations/*/turns', async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        status: 202,
        json: { ok: true, generated_at: '', project: project.name, warnings: [], created: true, turn_request: {
          request_id: 46, conversation_id: 'conv_view_handoff', client_request_id: body.client_request_id,
          project: project.name, state: 'streaming',
        } },
      });
    });
    let queuePosts = 0;
    let queuedBody: Record<string, unknown> | undefined;
    await page.route((url) => url.pathname === '/api/queue', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      queuePosts += 1;
      queuedBody = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        json: {
          ok: true,
          id: 'task_explicit_click',
          conversation_link: {
            linked: true,
            conversation_id: 'conv_view_handoff',
            turn_id: 91,
            dispatch_ref: 'task_explicit_click',
          },
        },
      });
    });

    await openCockpit(page);
    const views = page.locator('.viewswitch');
    await views.getByRole('button', { name: 'Gespräch', exact: true }).click();
    const talk = page.locator('main.cockpit-body.talk');
    await expect(talk).toBeVisible();
    await page.getByLabel('Nachricht an Ikarus').fill('Bleib bei diesem Turn.');
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect.poll(() => hasConversationEventSource(page, 46)).toBe(true);
    await emitConversationEvent(page, 46, 'start', {
      intent: 'chat', shell: 'voice', provider_used: 'ollama_http',
    });

    for (const [viewName, chunk] of [
      ['Karte', 'Karte '],
      ['IDE', 'IDE '],
      ['Genesis', 'Genesis'],
    ] as const) {
      await views.getByRole('button', { name: viewName, exact: true }).click();
      await expect(talk).toHaveAttribute('hidden', '');
      await expect(talk).toHaveAttribute('inert', '');
      await expect(page.locator('.convo')).toHaveCount(1);
      await emitConversationEvent(page, 46, 'delta', { text: chunk });
    }
    await emitConversationEvent(page, 46, 'final', {
      ok: true,
      project: project.name,
      warnings: [],
      generated_at: '',
      intent: 'enqueue',
      shell: 'voice',
      provider_used: 'ollama_http',
      assistant: 'Karte IDE Genesis — fertig.',
      turn_id: 91,
      conversation_persisted: true,
      action: {
        kind: 'queue_task',
        args: { project: project.name, objective: 'Parser härten', lane: 'local_only' },
        // A response flag is descriptive data, never UI-side authority.
        requires_confirmation: false,
      },
    });

    await views.getByRole('button', { name: 'Gespräch', exact: true }).click();
    await expect(talk).not.toHaveAttribute('hidden', '');
    await expect(talk).not.toHaveAttribute('inert', '');
    await expect(page.locator('.turn.ikarus').last()).toContainText('Karte IDE Genesis — fertig.');
    const approve = page.getByRole('button', { name: 'Loslegen' });
    await expect(approve).toBeVisible();
    expect(queuePosts, 'a legacy browser preference dispatched the proposal').toBe(0);

    await approve.click();
    await expect.poll(() => queuePosts).toBe(1);
    expect(queuedBody).toEqual(expect.objectContaining({
      project: project.name,
      objective: 'Parser härten',
      lane: 'local_only',
      conversation_id: 'conv_view_handoff',
      turn_id: 91,
    }));
    await expect(page.locator('.turn.ikarus').last()).toContainText('eingereiht');
  });

  test('stream auto-follow keeps a bottom reader with the answer and preserves an intentional scroll-up', async ({ page }) => {
    await installControlledConversationEvents(page);
    await stubQuietCockpit(page);
    await page.route('**/api/conversations', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation_id: 'conv_follow' },
    }));
    let requestId = 70;
    await page.route('**/api/conversations/*/turns', async (route) => {
      requestId += 1;
      const body = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        status: 202,
        json: { ok: true, generated_at: '', project: project.name, warnings: [], created: true, turn_request: {
          request_id: requestId, conversation_id: 'conv_follow', client_request_id: body.client_request_id,
          project: project.name, state: 'streaming',
        } },
      });
    });

    await openCockpit(page);
    await page.getByRole('button', { name: 'Gespräch', exact: true }).click();
    const composer = page.getByLabel('Nachricht an Ikarus');
    const scroller = page.locator('.convo-scroll');
    await scroller.evaluate((element) => {
      const node = element as HTMLElement;
      node.style.height = '220px';
      node.style.maxHeight = '220px';
      node.style.flex = '0 0 220px';
    });
    const bottomGap = () => scroller.evaluate((element) => {
      const node = element as HTMLElement;
      return node.scrollHeight - node.scrollTop - node.clientHeight;
    });
    const longAnswer = Array.from({ length: 60 }, (_, index) => `Absatz ${index}: beobachtbarer Inhalt.`).join('\n\n');

    await composer.fill('Erster langer Turn');
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect.poll(() => hasConversationEventSource(page, 71)).toBe(true);
    await emitConversationEvent(page, 71, 'delta', { text: longAnswer });
    await expect(page.locator('.turn.ikarus').last()).toContainText('Absatz 59');
    await expect.poll(bottomGap).toBeLessThanOrEqual(2);
    await emitConversationEvent(page, 71, 'delta', { text: '\n\nNachlauf im Stream.' });
    await expect(page.locator('.turn.ikarus').last()).toContainText('Nachlauf im Stream.');
    await expect.poll(bottomGap).toBeLessThanOrEqual(2);
    await emitConversationEvent(page, 71, 'final', {
      ok: true, project: project.name, warnings: [], generated_at: '',
      intent: 'chat', shell: 'voice', provider_used: 'ollama_http',
      assistant: `${longAnswer}\n\nNachlauf im Stream.\n\nFinal bestätigt.`,
    });
    await expect(page.locator('.turn.ikarus').last()).toContainText('Final bestätigt.');
    await expect.poll(bottomGap).toBeLessThanOrEqual(2);

    await composer.fill('Zweiter langer Turn');
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect.poll(() => hasConversationEventSource(page, 72)).toBe(true);
    await emitConversationEvent(page, 72, 'delta', { text: longAnswer });
    await expect(page.locator('.turn.ikarus').last()).toContainText('Absatz 59');
    await expect.poll(bottomGap).toBeLessThanOrEqual(2);
    await scroller.evaluate((element) => {
      const node = element as HTMLElement;
      node.scrollTop = 0;
      node.dispatchEvent(new Event('scroll'));
    });
    await expect.poll(() => scroller.evaluate((element) => (element as HTMLElement).scrollTop)).toBe(0);

    await emitConversationEvent(page, 72, 'delta', { text: '\n\nDieser Text kommt unterhalb des Lesers.' });
    await emitConversationEvent(page, 72, 'final', {
      ok: true, project: project.name, warnings: [], generated_at: '',
      intent: 'chat', shell: 'voice', provider_used: 'ollama_http',
      assistant: `${longAnswer}\n\nDieser Text kommt unterhalb des Lesers.\n\nAbschluss unterhalb.`,
    });
    await expect(page.locator('.turn.ikarus').last()).toContainText('Abschluss unterhalb.');
    await expect.poll(() => scroller.evaluate((element) => (element as HTMLElement).scrollTop)).toBe(0);
    await expect(page.getByRole('button', { name: 'Neue Antwort ↓' })).toBeVisible();
  });

  test('the square stop requests canonical cancellation while observation disconnect stays secondary', async ({ page }) => {
    let turnPosts = 0;
    let cancelPosts = 0;
    await stubQuietCockpit(page);
    await page.route('**/api/conversations', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation_id: 'conv_cancel' },
    }));
    await page.route('**/api/conversations/*/turns', async (route) => {
      turnPosts += 1;
      const body = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        status: 202,
        json: { ok: true, generated_at: '', project: project.name, warnings: [], created: true, turn_request: {
          request_id: 43, conversation_id: 'conv_cancel', client_request_id: body.client_request_id,
          project: project.name, state: 'streaming',
        } },
      });
    });
    await page.route('**/api/conversations/*/turns/*/cancel-requests', async (route) => {
      cancelPosts += 1;
      await route.fulfill({ json: { ok: true, generated_at: '', project: project.name, warnings: [], cancellation: { status: 'requested' } } });
    });
    await page.route('**/api/conversations/*/turns/*/events', (route) => route.abort('failed'));

    await openCockpit(page);
    await page.getByRole('button', { name: 'Gespräch', exact: true }).click();
    await page.getByLabel('Nachricht an Ikarus').fill('Bitte beobachtbar starten.');
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect.poll(() => turnPosts).toBe(1);
    await page.getByRole('button', { name: 'Abbruch anfordern' }).click();
    await expect.poll(() => cancelPosts).toBe(1);
    await expect(page.getByText('Abbruch angefordert – Bestätigung steht aus')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Nur Beobachtung trennen' })).toBeEnabled();
    await page.getByRole('button', { name: 'Nur Beobachtung trennen' }).click();
    expect(turnPosts).toBe(1);
  });

  test('observation cannot be closed before a canonical request exists', async ({ page }) => {
    let releaseConversation!: () => void;
    const conversationGate = new Promise<void>((resolve) => { releaseConversation = resolve; });
    let conversationPosts = 0;
    let turnPosts = 0;
    await stubQuietCockpit(page);
    await page.route('**/api/conversations', async (route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      conversationPosts += 1;
      await conversationGate;
      await route.fulfill({
        json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation_id: 'conv_slow_create' },
      });
    });
    await page.route('**/api/conversations/*/turns', async (route) => {
      turnPosts += 1;
      const body = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        status: 202,
        json: { ok: true, generated_at: '', project: project.name, warnings: [], created: true, turn_request: {
          request_id: 44, conversation_id: 'conv_slow_create', client_request_id: body.client_request_id,
          project: project.name, state: 'streaming',
        } },
      });
    });
    await page.route('**/api/conversations/*/turns/*/events', (route) => route.abort('failed'));

    await openCockpit(page);
    await page.getByRole('button', { name: 'Gespräch', exact: true }).click();
    await page.getByLabel('Nachricht an Ikarus').fill('Starte genau einmal.');
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect.poll(() => conversationPosts).toBe(1);

    const pending = page.getByRole('button', { name: 'Anfrage wird angelegt' });
    await expect(pending).toBeVisible();
    await expect(pending).toBeDisabled();
    await expect(page.locator('.turn.ikarus .thinking')).toContainText('Anfrage wird angelegt');
    expect(turnPosts).toBe(0);

    releaseConversation();
    await expect.poll(() => turnPosts).toBe(1);
    await expect(page.getByRole('button', { name: 'Abbruch anfordern' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'Nur Beobachtung trennen' })).toBeEnabled();
    await page.getByRole('button', { name: 'Nur Beobachtung trennen' }).click();
    expect(turnPosts).toBe(1);
  });

  for (const cancelOutcome of ['success', 'error'] as const) {
    test(`a late ${cancelOutcome} response for cancellation A cannot clear active request B`, async ({ page }) => {
      let releaseCancel!: () => void;
      const cancelGate = new Promise<void>((resolve) => { releaseCancel = resolve; });
      let releaseSecondTurn!: () => void;
      const secondTurnGate = new Promise<void>((resolve) => { releaseSecondTurn = resolve; });
      let turnPosts = 0;
      let cancelPosts = 0;

      await stubQuietCockpit(page);
      await page.route('**/api/conversations', (route) => route.fulfill({
        json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation_id: 'conv_cancel_race' },
      }));
      await page.route('**/api/conversations/*/turns', async (route) => {
        turnPosts += 1;
        const body = route.request().postDataJSON() as Record<string, unknown>;
        if (turnPosts === 2) await secondTurnGate;
        await route.fulfill({
          status: 202,
          json: { ok: true, generated_at: '', project: project.name, warnings: [], created: true, turn_request: {
            request_id: 60 + turnPosts, conversation_id: 'conv_cancel_race', client_request_id: body.client_request_id,
            project: project.name, state: 'streaming',
          } },
        });
      });
      await page.route('**/api/conversations/*/turns/*/cancel-requests', async (route) => {
        cancelPosts += 1;
        await cancelGate;
        if (cancelOutcome === 'error') {
          await route.fulfill({
            status: 500,
            json: { ok: false, error: 'late cancellation response failed' },
          });
          return;
        }
        await route.fulfill({
          json: { ok: true, generated_at: '', project: project.name, warnings: [], cancellation: { status: 'unknown' } },
        });
      });
      await page.route('**/api/conversations/*/turns/*/events', (route) => route.abort('failed'));

      await openCockpit(page);
      await page.getByRole('button', { name: 'Gespräch', exact: true }).click();
      const composer = page.getByLabel('Nachricht an Ikarus');
      const answers = page.locator('.turn.ikarus');

      await composer.fill('Turn A');
      await page.getByRole('button', { name: 'Senden' }).click();
      await expect.poll(() => turnPosts).toBe(1);
      await page.getByRole('button', { name: 'Nur Beobachtung trennen' }).click();
      await page.getByRole('button', { name: 'Server-Abbruch anfordern' }).click();
      await expect.poll(() => cancelPosts).toBe(1);

      await composer.fill('Turn B');
      await page.getByRole('button', { name: 'Senden' }).click();
      await expect.poll(() => turnPosts).toBe(2);

      // While B has no canonical id yet, A's detached identity must not turn
      // the composer control into an enabled close button.
      const pending = page.getByRole('button', { name: 'Anfrage wird angelegt' });
      await expect(pending).toBeVisible();
      await expect(pending).toBeDisabled();
      await expect(page.getByRole('button', { name: 'Nur Beobachtung trennen' })).toHaveCount(0);

      releaseSecondTurn();
      await expect(page.getByRole('button', { name: 'Abbruch anfordern' })).toBeEnabled();
      await expect(page.getByRole('button', { name: 'Nur Beobachtung trennen' })).toBeEnabled();

      // The late A response is actually consumed (the A ledger changes), but
      // its conditional clear must retain B's exact active identity.
      releaseCancel();
      await expect(answers.first().locator('.ledger-row[data-key="cancel"]'))
        .toContainText('Abbruchzustand unbekannt');
      await expect(page.getByRole('button', { name: 'Abbruch anfordern' })).toBeEnabled();
      expect(turnPosts).toBe(2);
    });
  }

  test('a late terminal event from a closed observation cannot stop the next turn', async ({ page }) => {
    await page.addInitScript(() => {
      const sources: ControlledEventSource[] = [];

      class ControlledEventSource {
        static readonly CONNECTING = 0;
        static readonly OPEN = 1;
        static readonly CLOSED = 2;
        readonly CONNECTING = 0;
        readonly OPEN = 1;
        readonly CLOSED = 2;
        readonly url: string;
        readonly withCredentials = false;
        readyState = ControlledEventSource.OPEN;
        onopen: ((event: Event) => void) | null = null;
        onmessage: ((event: MessageEvent) => void) | null = null;
        onerror: ((event: Event) => void) | null = null;
        private readonly listeners = new Map<string, Set<(event: Event) => void>>();

        constructor(url: string | URL) {
          this.url = String(url);
          sources.push(this);
        }

        addEventListener(type: string, listener: EventListenerOrEventListenerObject | null) {
          if (!listener) return;
          const callback = typeof listener === 'function'
            ? listener
            : (event: Event) => listener.handleEvent(event);
          const listeners = this.listeners.get(type) || new Set<(event: Event) => void>();
          listeners.add(callback);
          this.listeners.set(type, listeners);
        }

        removeEventListener() { /* test driver retains queued listeners */ }

        dispatchEvent(event: Event) {
          for (const listener of this.listeners.get(event.type) || []) listener(event);
          if (event.type === 'error') this.onerror?.(event);
          return true;
        }

        close() {
          // Deliberately retain listeners: this fixture models a callback that
          // was already queued by the browser when close() won the UI race.
          this.readyState = ControlledEventSource.CLOSED;
        }

        emit(type: string, data: Record<string, unknown>) {
          this.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(data) }));
        }
      }

      Object.defineProperty(window, 'EventSource', {
        configurable: true,
        value: ControlledEventSource,
      });
      Object.defineProperty(window, '__emitConversationEvent', {
        configurable: true,
        value: (requestId: number, type: string, data: Record<string, unknown>) => {
          const suffix = `/turns/${requestId}/events`;
          const source = sources.find((candidate) => candidate.url.endsWith(suffix));
          if (!source) throw new Error(`no controlled EventSource for ${suffix}`);
          source.emit(type, data);
        },
      });
      Object.defineProperty(window, '__hasConversationEventSource', {
        configurable: true,
        value: (requestId: number) => {
          const suffix = `/turns/${requestId}/events`;
          return sources.some((candidate) => candidate.url.endsWith(suffix));
        },
      });
    });

    let turnPosts = 0;
    await stubQuietCockpit(page);
    await page.route('**/api/conversations', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation_id: 'conv_late_terminal' },
    }));
    await page.route('**/api/conversations/*/turns', async (route) => {
      turnPosts += 1;
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const requestId = 50 + turnPosts;
      await route.fulfill({
        status: 202,
        json: { ok: true, generated_at: '', project: project.name, warnings: [], created: true, turn_request: {
          request_id: requestId, conversation_id: 'conv_late_terminal', client_request_id: body.client_request_id,
          project: project.name, state: 'streaming',
        } },
      });
    });

    const emit = (requestId: number, type: string, data: Record<string, unknown>) => page.evaluate(
      ({ requestId, type, data }) => (window as unknown as {
        __emitConversationEvent: (id: number, event: string, payload: Record<string, unknown>) => void;
      }).__emitConversationEvent(requestId, type, data),
      { requestId, type, data },
    );
    const hasSource = (requestId: number) => page.evaluate(
      (id) => (window as unknown as {
        __hasConversationEventSource: (requestId: number) => boolean;
      }).__hasConversationEventSource(id),
      requestId,
    );

    await openCockpit(page);
    await page.getByRole('button', { name: 'Gespräch', exact: true }).click();
    const composer = page.getByLabel('Nachricht an Ikarus');

    await composer.fill('Erster Turn');
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect.poll(() => hasSource(51)).toBe(true);
    await emit(51, 'delta', { text: 'ALT-TEIL' });
    const answers = page.locator('.turn.ikarus');
    await expect(answers.first()).toContainText('ALT-TEIL');
    await page.getByRole('button', { name: 'Nur Beobachtung trennen' }).click();

    await composer.fill('Zweiter Turn');
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect.poll(() => hasSource(52)).toBe(true);
    await expect(page.getByRole('button', { name: 'Abbruch anfordern' })).toBeEnabled();

    // Both terminal shapes may already have been queued when the old source
    // was closed. Neither may mutate shared state owned by request 52.
    await emit(51, 'error', { error: 'late old failure' });
    await emit(51, 'cancelled', { status: 'confirmed' });
    await expect(page.getByRole('button', { name: 'Abbruch anfordern' })).toBeEnabled();
    await expect(page.locator('.convo-error')).toHaveCount(0);
    await expect(answers.first()).toContainText('ALT-TEIL');

    await emit(52, 'final', {
      ok: true, project: project.name, warnings: [], generated_at: '',
      intent: 'chat', shell: 'voice', provider_used: 'ollama_http',
      assistant: 'NEU-FERTIG',
    });
    await expect(answers.last()).toContainText('NEU-FERTIG');
    await expect(page.getByRole('button', { name: 'Senden' })).toBeVisible();
    expect(turnPosts).toBe(2);
  });
});
