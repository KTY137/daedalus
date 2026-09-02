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

  test('an unreachable IDE starts through the desktop service with the registered project name', async ({ page }) => {
    await stubQuietCockpit(page);
    let reachable = false;
    let startBody: unknown;
    await page.route('**/api/desktop/settings', (route) => route.fulfill({
      json: {
        ok: true,
        generated_at: '',
        project: null,
        warnings: [],
        desktop: { services: { ide: { available: true, endpoint: 'http://127.0.0.1:3000', reachable, last_error: reachable ? '' : 'connection refused' } } }
      }
    }));
    await page.route('**/api/desktop/services/ide/start', async (route) => {
      startBody = route.request().postDataJSON();
      reachable = true;
      await route.fulfill({
        json: { ok: true, generated_at: '', project: null, warnings: [], service: { endpoint: 'http://127.0.0.1:3000', reachable: true } }
      });
    });
    await page.route('http://127.0.0.1:3000/**', (route) => route.fulfill({ contentType: 'text/html', body: '<title>OpenVSCode</title>' }));

    await openCockpit(page);
    await page.getByRole('button', { name: 'IDE', exact: true }).click();
    await expect(page.getByRole('heading', { name: 'OpenVSCode Server ist nicht erreichbar' })).toBeVisible();
    await expect(page.getByText('connection refused')).toBeVisible();

    await page.getByRole('button', { name: 'IDE starten' }).click();
    await expect(page.getByTitle(`OpenVSCode – ${project.name}`)).toBeVisible();
    expect(startBody).toEqual({ project: project.name });
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
    await expect(notice).toContainText('Desktop-IDE-Steuerung');
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

  test('closing observation never repeats a turn POST and cancellation is a separate requested state', async ({ page }) => {
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
    await page.getByRole('button', { name: 'Beobachtung schließen' }).click();
    await page.getByRole('button', { name: 'Abbruch anfordern' }).click();
    await expect.poll(() => cancelPosts).toBe(1);
    await expect(page.getByText('Abbruch angefordert – Bestätigung steht aus')).toBeVisible();
    expect(turnPosts).toBe(1);
  });
});
