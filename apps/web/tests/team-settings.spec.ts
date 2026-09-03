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
    await section.locator('input[type="number"]').fill('99');
    await section.getByRole('button', { name: /Team speichern/ }).click();

    // The user is told which field and why, not "Speichern fehlgeschlagen".
    await expect(section.getByText(/max_workers must be between 1 and 64/)).toBeVisible();
  });
});
