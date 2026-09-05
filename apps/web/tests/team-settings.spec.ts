import { expect, test, type Page } from '@playwright/test';
import { NOT_BUILT } from './_app';

/**
 * Browser acceptance for the team editor.
 *
 * The unit spec proves the patch is minimal and the draft is read correctly;
 * `tsc` proves the types line up. Neither proves a person can open the drawer
 * and change the lane — this repo has had three fully green suites over three
 * live escapes in one day, which is why this file drives the BUILT bundle.
 *
 * The hierarchy read is stubbed so the assertions do not depend on which
 * projects happen to be registered on the machine. The SAVE is not stubbed
 * beyond capturing it: what the form sends is the thing under test, and
 * `save_team`'s own validation is proven separately in
 * tests/test_project_row_rewrite.py.
 */

const LANES = ['auto', 'local', 'local_only', 'claude', 'codex'];

function hierarchy(overrides: Record<string, unknown> = {}) {
  return {
    ok: true,
    generated_at: '',
    project: 'probe',
    warnings: [],
    nodes: [
      {
        id: 'project:probe',
        type: 'project',
        label: 'probe',
        data: { max_workers: 3, default_lane: 'local_only' }
      },
      { id: 'agent:talos', type: 'agent', label: 'Talos', data: { name: 'talos', active: true } },
      { id: 'agent:minos', type: 'agent', label: 'Minos', data: { name: 'minos', active: false } }
    ],
    edges: [],
    health: {},
    capabilities: [],
    policy_flags: {},
    lanes: LANES,
    max_workers_ceiling: 64,
    ...overrides
  };
}

/**
 * A project the cockpit can select, injected.
 *
 * The first version of this spec stubbed only the two endpoints under test and
 * passed — because a throwaway project happened to be registered on the machine
 * at that moment. Removing it turned both tests red without a line of product
 * code changing. That is the trap the deleted loop.spec.ts named in its own
 * header: a spec that passes only when the environment happens to cooperate is
 * telling you about the machine, not about the cockpit.
 */
async function stubProject(page: Page): Promise<void> {
  const project = { name: 'probe', repo_root: 'C:\\work\\probe', team: {} };
  const envelope = (extra: Record<string, unknown> = {}) => ({
    ok: true, generated_at: '2026-09-03T00:00:00Z', project: project.name, warnings: [], ...extra
  });
  const json = (route: import('@playwright/test').Route, body: Record<string, unknown>) =>
    route.fulfill({ status: 200, contentType: 'application/json; charset=utf-8', body: JSON.stringify(body) });

  await page.route('**/api/**', (route) => json(route, envelope()));
  await page.route('**/api/events**', (route) => route.fulfill({
    status: 200,
    headers: { 'Content-Type': 'text/event-stream', Connection: 'close' },
    body: 'event: hello\ndata: {"queue_depth":0,"in_flight":0,"watcher_state":"idle","unread_count":0}\n\n'
  }));
  await page.route('**/api/projects', (route) => json(route, envelope({ projects: [project] })));
  await page.route('**/api/dashboard**', (route) => json(route, envelope({
    selected_project: project.name,
    queue: { pending: [], reports: [] },
    governance: envelope({ promotion_allowed: false, verdict: 'BLOCKED_BY_GATE', state: 'present', head: null, gates: [], blockers: [] })
  })));
}

async function openSettings(page: Page): Promise<void> {
  const response = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
  await page.getByRole('button', { name: /^Einstellungen/ }).click();
  await expect(page.locator('.settings.open')).toBeVisible();
}

test.describe('team editor', () => {
  test('renders the lanes the backend named and saves only what moved', async ({ page }) => {
    const puts: Array<Record<string, unknown>> = [];
    await stubProject(page);
    await page.route('**/api/projects/*/hierarchy', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(hierarchy()) })
    );
    await page.route('**/api/projects/*/team', async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      puts.push(body);
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ok: true,
          generated_at: '',
          project: 'probe',
          warnings: [],
          team: {
            max_workers: 9,
            default_lane: 'local_only',
            active_agents: ['talos'],
            squads: {},
            model_assignments: {},
            semi_auto: {}
          },
          ignored_fields: []
        })
      });
    });

    await openSettings(page);
    const section = page.locator('section[aria-labelledby="team-settings-title"]');
    await expect(section).toBeVisible();

    // The lane list is the backend's, not a copy kept in the frontend.
    const options = section.locator('select option');
    await expect(options).toHaveCount(LANES.length);
    expect((await options.allTextContents()).join(',')).toBe(LANES.join(','));

    // Nothing changed yet, so there is nothing to send.
    const save = section.getByRole('button', { name: /Team speichern/ });
    await expect(save).toBeDisabled();

    await section.locator('input[type="number"]').fill('9');
    await expect(save).toBeEnabled();
    await save.click();

    await expect(section.getByText('Gespeichert.')).toBeVisible();
    expect(puts).toHaveLength(1);
    // Only the field that moved: save_team merges, so sending the whole object
    // would rewrite squads and model_assignments, which this form never shows.
    expect(Object.keys(puts[0])).toEqual(['max_workers']);
    expect(puts[0].max_workers).toBe(9);
  });

  test('a rejected patch shows the backend reason verbatim', async ({ page }) => {
    await stubProject(page);
    await page.route('**/api/projects/*/hierarchy', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(hierarchy()) })
    );
    await page.route('**/api/projects/*/team', (route) =>
      route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ ok: false, error: 'max_workers must be between 1 and 64' })
      })
    );

    await openSettings(page);
    const section = page.locator('section[aria-labelledby="team-settings-title"]');
    await section.locator('input[type="number"]').fill('9');
    await section.getByRole('button', { name: /Team speichern/ }).click();

    // The user is told which field and why, not "Speichern fehlgeschlagen".
    await expect(section.getByText(/max_workers must be between 1 and 64/)).toBeVisible();
  });

  test('blocks an invalid worker count without sending a patch', async ({ page }) => {
    let puts = 0;
    await stubProject(page);
    await page.route('**/api/projects/*/hierarchy', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(hierarchy()) })
    );
    await page.route('**/api/projects/*/team', async (route) => {
      puts += 1;
      await route.fulfill({ status: 500, json: { ok: false, error: 'must not be called' } });
    });

    await openSettings(page);
    const section = page.locator('section[aria-labelledby="team-settings-title"]');
    const workers = section.locator('input[type="number"]');
    const save = section.getByRole('button', { name: /Team speichern/ });
    await workers.fill('99');
    await expect(workers).toHaveAttribute('aria-invalid', 'true');
    await expect(section.getByRole('alert')).toContainText('zwischen 1 und 64');
    await expect(save).toBeDisabled();
    expect(puts).toBe(0);
  });

  test('preserves a same-project draft across close and discards it without a write', async ({ page }) => {
    let puts = 0;
    await stubProject(page);
    await page.route('**/api/projects/*/hierarchy', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(hierarchy()) })
    );
    await page.route('**/api/projects/*/team', async (route) => {
      puts += 1;
      await route.fulfill({ status: 500, json: { ok: false, error: 'must not be called' } });
    });

    await openSettings(page);
    const section = page.locator('section[aria-labelledby="team-settings-title"]');
    const workers = section.locator('input[type="number"]');
    await workers.fill('9');
    await page.locator('.settings-close').click();
    await page.getByRole('button', { name: /^Einstellungen/ }).click();
    await expect(workers).toHaveValue('9');
    await section.getByRole('button', { name: 'Verwerfen' }).click();
    await expect(workers).toHaveValue('3');
    await expect(section.getByRole('button', { name: /Team speichern/ })).toBeDisabled();
    expect(puts).toBe(0);
  });

  test('reconciles an ambiguous same-project write before unlocking the editor', async ({ page }) => {
    await stubProject(page);
    let canonical = 3;
    let puts = 0;
    let writeResponseLost = false;
    let releaseCanonicalRead: (() => void) | undefined;

    await page.route('**/api/projects/*/hierarchy', async (route) => {
      if (writeResponseLost) {
        await new Promise<void>((resolve) => { releaseCanonicalRead = resolve; });
        writeResponseLost = false;
      }
      await route.fulfill({
        json: hierarchy({
          nodes: [
            {
              id: 'project:probe',
              type: 'project',
              label: 'probe',
              data: { max_workers: canonical, default_lane: 'local_only' }
            },
            { id: 'agent:talos', type: 'agent', label: 'Talos', data: { name: 'talos', active: true } }
          ]
        })
      });
    });
    await page.route('**/api/projects/*/team', async (route) => {
      puts += 1;
      const body = route.request().postDataJSON() as { max_workers?: number };
      canonical = body.max_workers ?? canonical;
      writeResponseLost = true;
      await route.abort('connectionreset');
    });

    await openSettings(page);
    const section = page.locator('section[aria-labelledby="team-settings-title"]');
    const workers = section.locator('input[type="number"]');
    const save = section.locator('.team-actions .settings-refresh').last();
    await workers.fill('9');
    await save.click();

    await expect.poll(() => Boolean(releaseCanonicalRead)).toBe(true);
    await expect(workers).toBeDisabled();
    await expect(save).toBeDisabled();

    releaseCanonicalRead?.();
    await expect(workers).toHaveValue('9');
    await expect(workers).toBeEnabled();
    await expect(save).toBeDisabled();
    await expect(section.getByRole('alert')).toContainText(/Ausgang .* unklar/);
    await expect(section.getByRole('alert')).not.toContainText('ist fehlgeschlagen');
    expect(puts).toBe(1);
  });

  test('keeps the submitted Team draft when an ambiguous write was not applied', async ({ page }) => {
    await stubProject(page);
    const canonical = 3;
    let puts = 0;
    let writeResponseLost = false;
    let releaseCanonicalRead: (() => void) | undefined;

    await page.route('**/api/projects/*/hierarchy', async (route) => {
      if (writeResponseLost) {
        await new Promise<void>((resolve) => { releaseCanonicalRead = resolve; });
        writeResponseLost = false;
      }
      await route.fulfill({
        json: hierarchy({
          nodes: [
            {
              id: 'project:probe',
              type: 'project',
              label: 'probe',
              data: { max_workers: canonical, default_lane: 'local_only' }
            },
            { id: 'agent:talos', type: 'agent', label: 'Talos', data: { name: 'talos', active: true } }
          ]
        })
      });
    });
    await page.route('**/api/projects/*/team', async (route) => {
      puts += 1;
      writeResponseLost = true;
      await route.abort('connectionreset');
    });

    await openSettings(page);
    const section = page.locator('section[aria-labelledby="team-settings-title"]');
    const workers = section.locator('input[type="number"]');
    const save = section.getByRole('button', { name: /Team speichern/ });
    await workers.fill('9');
    await save.click();

    await expect.poll(() => Boolean(releaseCanonicalRead)).toBe(true);
    await expect(workers).toBeDisabled();
    releaseCanonicalRead?.();

    await expect(workers).toHaveValue('9');
    await expect(workers).toBeEnabled();
    await expect(save).toBeEnabled();
    await expect(section.getByRole('alert')).toContainText(/Ausgang .* unklar/);
    await expect(section.getByRole('alert')).not.toContainText('ist fehlgeschlagen');
    expect(puts).toBe(1);
  });

  for (const committed of [true, false]) {
    test(`reconciles an unconfirmed HTTP 200 Team projection (${committed ? 'committed' : 'not committed'})`, async ({ page }) => {
      await stubProject(page);
      let canonical = 3;
      let reconcileRequested = false;
      let reconciliationReads = 0;
      let releaseCanonicalRead: (() => void) | undefined;

      await page.route('**/api/projects/*/hierarchy', async (route) => {
        if (reconcileRequested) {
          reconcileRequested = false;
          reconciliationReads += 1;
          await new Promise<void>((resolve) => { releaseCanonicalRead = resolve; });
        }
        await route.fulfill({
          json: hierarchy({
            nodes: [
              {
                id: 'project:probe',
                type: 'project',
                label: 'probe',
                data: { max_workers: canonical, default_lane: 'local_only' }
              },
              { id: 'agent:talos', type: 'agent', label: 'Talos', data: { name: 'talos', active: true } }
            ]
          })
        });
      });
      await page.route('**/api/projects/*/team', async (route) => {
        if (committed) canonical = 9;
        reconcileRequested = true;
        // The successful HTTP status cannot prove whether the mutation stuck:
        // the canonical Team projection is missing from the response.
        await route.fulfill({ json: { ok: true, project: 'probe', ignored_fields: [] } });
      });

      await openSettings(page);
      const section = page.locator('section[aria-labelledby="team-settings-title"]');
      const workers = section.locator('input[type="number"]');
      const save = section.getByRole('button', { name: /Team speichern/ });
      // SystemCapabilities consumes the same hierarchy endpoint. Wait for its
      // initial read so this test gates the post-PUT Team reconciliation, not
      // an unrelated settings-card request.
      await expect(page.getByTestId('system-capabilities')).toBeVisible();
      await workers.fill('9');
      await save.click();

      await expect.poll(() => Boolean(releaseCanonicalRead)).toBe(true);
      await expect(workers).toBeDisabled();
      releaseCanonicalRead?.();

      await expect(page.getByRole('dialog', { name: 'Einstellungen' })).toBeVisible();
      await expect(workers).toHaveValue('9');
      await expect(workers).toBeEnabled();
      if (committed) await expect(save).toBeDisabled();
      else await expect(save).toBeEnabled();
      await expect(section.getByRole('alert')).toContainText(/Ausgang .* unklar/);
      await expect(section.getByRole('alert')).toContainText('bestätigte den gespeicherten Projektstand nicht vollständig');
      expect(reconciliationReads).toBe(1);
    });
  }

  test('does not call a type-valid but silently ignored Team patch saved', async ({ page }) => {
    await stubProject(page);
    let reconcileRequested = false;
    let reconciliationReads = 0;
    await page.route('**/api/projects/*/hierarchy', async (route) => {
      if (reconcileRequested) {
        reconcileRequested = false;
        reconciliationReads += 1;
      }
      await route.fulfill({ json: hierarchy() });
    });
    await page.route('**/api/projects/*/team', async (route) => {
      reconcileRequested = true;
      await route.fulfill({
        json: {
          ok: true,
          generated_at: '',
          project: 'probe',
          warnings: [],
          team: {
            max_workers: 3,
            default_lane: 'local_only',
            active_agents: ['talos'],
            squads: {},
            model_assignments: {},
            semi_auto: {}
          },
          ignored_fields: []
        }
      });
    });

    await openSettings(page);
    const section = page.locator('section[aria-labelledby="team-settings-title"]');
    const workers = section.locator('input[type="number"]');
    const save = section.getByRole('button', { name: /Team speichern/ });
    await expect(page.getByTestId('system-capabilities')).toBeVisible();
    await workers.fill('9');
    await save.click();

    await expect(section.getByRole('alert')).toContainText(/Ausgang .* unklar/);
    await expect(section.getByRole('alert')).toContainText('angeforderten Änderungen nicht');
    await expect(workers).toHaveValue('9');
    await expect(save).toBeEnabled();
    expect(reconciliationReads).toBe(1);
  });

  for (const invalidHierarchy of [
    {
      name: 'wrong project',
      payload: hierarchy({
        project: 'beta',
        nodes: [{
          id: 'project:beta',
          type: 'project',
          label: 'beta',
          data: { max_workers: 4, default_lane: 'local_only' }
        }]
      })
    },
    {
      name: 'missing project row',
      payload: hierarchy({ nodes: [] })
    }
  ]) {
    test(`rejects a ${invalidHierarchy.name} during Team reconciliation and retains the submitted draft`, async ({ page }) => {
      await stubProject(page);
      let reconcileRequested = false;
      let reconciliationReads = 0;

      await page.route('**/api/projects/*/hierarchy', async (route) => {
        if (reconcileRequested) {
          reconcileRequested = false;
          reconciliationReads += 1;
          await route.fulfill({ json: invalidHierarchy.payload });
          return;
        }
        await route.fulfill({ json: hierarchy() });
      });
      await page.route('**/api/projects/*/team', async (route) => {
        reconcileRequested = true;
        await route.fulfill({ json: { ok: true, project: 'probe', ignored_fields: [] } });
      });

      await openSettings(page);
      const section = page.locator('section[aria-labelledby="team-settings-title"]');
      const workers = section.locator('input[type="number"]');
      const save = section.getByRole('button', { name: /Team speichern/ });
      await expect(page.getByTestId('system-capabilities')).toBeVisible();
      await workers.fill('9');
      await save.click();

      await expect(section.getByRole('alert')).toContainText('kanonische Serverstand konnte noch nicht bestätigt werden');
      await expect(section.getByRole('alert')).toContainText('keinen gültigen kanonischen Projektstand');
      await expect(section.getByRole('button', { name: 'Erneut laden' })).toBeVisible();
      expect(reconciliationReads).toBe(1);

      await section.getByRole('button', { name: 'Erneut laden' }).click();
      await expect(workers).toHaveValue('9');
      await expect(workers).toBeEnabled();
      await expect(save).toBeEnabled();
      await expect(section.getByRole('alert')).toContainText(/Ausgang .* unklar/);
    });
  }

  test('retains a requested field that the Team backend explicitly ignored', async ({ page }) => {
    await stubProject(page);
    let puts = 0;
    await page.route('**/api/projects/*/hierarchy', (route) =>
      route.fulfill({ json: hierarchy() })
    );
    await page.route('**/api/projects/*/team', async (route) => {
      puts += 1;
      await route.fulfill({
        json: {
          ok: true,
          generated_at: '',
          project: 'probe',
          warnings: [],
          team: {
            max_workers: 3,
            default_lane: 'local_only',
            active_agents: ['talos'],
            squads: {},
            model_assignments: {},
            semi_auto: {}
          },
          ignored_fields: ['max_workers']
        }
      });
    });

    await openSettings(page);
    const section = page.locator('section[aria-labelledby="team-settings-title"]');
    const workers = section.locator('input[type="number"]');
    const save = section.getByRole('button', { name: /Team speichern/ });
    await workers.fill('9');
    await save.click();

    await expect(section.getByRole('status')).toContainText('Nicht übernommen: max_workers');
    await expect(section.getByRole('status')).toContainText('zum erneuten Speichern erhalten');
    await expect(workers).toHaveValue('9');
    await expect(save).toBeEnabled();
    await expect(section.getByText('Ungespeicherte Änderung.')).toBeVisible();
    expect(puts).toBe(1);
  });

  test('keeps an in-flight team write locked across an A to B to A project round-trip', async ({ page }) => {
    await stubProject(page);
    const projects = [
      { name: 'probe', repo_root: 'C:\\work\\probe', team: {} },
      { name: 'beta', repo_root: 'C:\\work\\beta', team: {} }
    ];
    const canonical: Record<string, number> = { probe: 3, beta: 4 };
    let releaseSave: (() => void) | undefined;
    let saveFinished = false;

    await page.unroute('**/api/projects');
    await page.route('**/api/projects', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: 'probe', warnings: [], projects }
    }));
    await page.route('**/api/projects/*/hierarchy', (route) => {
      const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/')[3]);
      return route.fulfill({
        json: hierarchy({
          project: name,
          nodes: [
            {
              id: `project:${name}`,
              type: 'project',
              label: name,
              data: { max_workers: canonical[name], default_lane: 'local_only' }
            },
            { id: 'agent:talos', type: 'agent', label: 'Talos', data: { name: 'talos', active: true } }
          ]
        })
      });
    });
    await page.route('**/api/projects/*/team', async (route) => {
      const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/')[3]);
      const body = route.request().postDataJSON() as { max_workers?: number };
      await new Promise<void>((resolve) => { releaseSave = resolve; });
      canonical[name] = body.max_workers ?? canonical[name];
      await route.fulfill({
        json: {
          ok: true,
          generated_at: '',
          project: name,
          warnings: [],
          team: {
            max_workers: canonical[name],
            default_lane: 'local_only',
            active_agents: ['talos'],
            squads: {},
            model_assignments: {},
            semi_auto: {}
          },
          ignored_fields: []
        }
      });
      saveFinished = true;
    });

    const chooseProject = async (name: string) => {
      await page.locator('.scope-trigger').click();
      await page.getByRole('listbox', { name: 'Projekt wählen' }).getByRole('button', { name, exact: true }).click();
      await expect(page.locator('.scope-name')).toHaveText(name);
    };

    await openSettings(page);
    const section = page.locator('section[aria-labelledby="team-settings-title"]');
    const workers = section.locator('input[type="number"]');
    await workers.fill('9');
    await section.getByRole('button', { name: /Team speichern/ }).click();
    await expect.poll(() => Boolean(releaseSave)).toBe(true);

    await page.locator('.settings-close').click();
    await chooseProject('beta');
    await page.getByRole('button', { name: /^Einstellungen/ }).click();
    await expect(workers).toHaveValue('4');
    await expect(workers).toBeDisabled();

    await page.locator('.settings-close').click();
    await chooseProject('probe');
    await page.getByRole('button', { name: /^Einstellungen/ }).click();
    await expect(workers).toHaveValue('3');
    await expect(workers).toBeDisabled();

    releaseSave?.();
    await expect.poll(() => saveFinished).toBe(true);
    await expect(workers).toHaveValue('9');
    await expect(workers).toBeEnabled();
    await expect(section.getByRole('button', { name: /Team speichern/ })).toBeDisabled();
  });

  test('reports a failed team write after returning to its project', async ({ page }) => {
    await stubProject(page);
    const projects = [
      { name: 'probe', repo_root: 'C:\\work\\probe', team: {} },
      { name: 'beta', repo_root: 'C:\\work\\beta', team: {} }
    ];
    const canonical: Record<string, number> = { probe: 3, beta: 4 };
    let releaseSave: (() => void) | undefined;
    let saveFinished = false;

    await page.unroute('**/api/projects');
    await page.route('**/api/projects', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: 'probe', warnings: [], projects }
    }));
    await page.route('**/api/projects/*/hierarchy', (route) => {
      const name = decodeURIComponent(new URL(route.request().url()).pathname.split('/')[3]);
      return route.fulfill({
        json: hierarchy({
          project: name,
          nodes: [{
            id: `project:${name}`,
            type: 'project',
            label: name,
            data: { max_workers: canonical[name], default_lane: 'local_only' }
          }]
        })
      });
    });
    await page.route('**/api/projects/*/team', async (route) => {
      await new Promise<void>((resolve) => { releaseSave = resolve; });
      await route.fulfill({
        status: 409,
        json: { ok: false, error: 'team revision conflict' }
      });
      saveFinished = true;
    });

    const chooseProject = async (name: string) => {
      await page.locator('.scope-trigger').click();
      await page.getByRole('listbox', { name: 'Projekt wählen' }).getByRole('button', { name, exact: true }).click();
      await expect(page.locator('.scope-name')).toHaveText(name);
    };

    await openSettings(page);
    const section = page.locator('section[aria-labelledby="team-settings-title"]');
    const workers = section.locator('input[type="number"]');
    await workers.fill('9');
    await section.getByRole('button', { name: /Team speichern/ }).click();
    await expect.poll(() => Boolean(releaseSave)).toBe(true);

    await page.locator('.settings-close').click();
    await chooseProject('beta');
    await page.getByRole('button', { name: /^Einstellungen/ }).click();
    await expect(workers).toHaveValue('4');
    releaseSave?.();
    await expect.poll(() => saveFinished).toBe(true);
    await expect(workers).toBeEnabled();

    await page.locator('.settings-close').click();
    await chooseProject('probe');
    await page.getByRole('button', { name: /^Einstellungen/ }).click();
    await expect(workers).toHaveValue('3');
    await expect(section.getByRole('alert')).toContainText('team revision conflict');
  });
});
