import { expect, test } from '@playwright/test';
import { NOT_BUILT } from './_app';

async function openCockpit(page: import('@playwright/test').Page) {
  const response = await page.goto('/', { waitUntil: 'domcontentloaded' });
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
    await expect(dialog.getByRole('button', { name: 'Durchsuchen …' })).toBeVisible();
    await dialog.getByLabel('Projektordner').fill(project.repo_root);
    await dialog.getByLabel(/Name/).fill(project.name);
    await dialog.getByRole('button', { name: 'Ordner öffnen' }).click();

    await expect(dialog).toBeHidden();
    await expect(page.locator('.scope-name').first()).toHaveText(project.name);
    expect(posted).toEqual({ repo_root: project.repo_root, name: project.name });
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

  test('an unreachable IDE stays honest and starts through the desktop service with the selected root', async ({ page }) => {
    await stubQuietCockpit(page);
    let reachable = false;
    let startBody: unknown;
    await page.route('**/api/desktop/settings', (route) => route.fulfill({
      json: {
        ok: true,
        generated_at: '',
        project: null,
        warnings: [],
        desktop: { services: { ide: { endpoint: 'http://127.0.0.1:3000', reachable, last_error: reachable ? '' : 'connection refused' } } }
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
    expect(startBody).toEqual({ project: project.repo_root });
  });
});
