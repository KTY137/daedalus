import { expect, test, type Page } from '@playwright/test';
import { collect, NOT_BUILT } from './_app';

/**
 * G1-UI-05 — the rail's Verlauf and the `/` commands, fixture-backed.
 *
 * Every API the page reads is stubbed with the shapes the backend emits, so
 * these run in seconds and prove the surface's own promises: threads come
 * from the list route and resume through the existing conversation GET; a
 * `/` command that stays on the page never POSTs; effort is sent, not
 * invented; a list that cannot be read says so.
 */

const project = { name: 'atlas', repo_root: 'C:\\work\\atlas', team: {}, reachable: true };

const storedView = {
  conversation_id: 'conv_1',
  exists: true,
  turn_count: 2,
  narrative: '',
  turns: [
    {
      id: 44,
      user_message: 'status',
      assistant_text: 'Alles ruhig.',
      intent: 'status',
      provider_used: 'deterministic',
      created_ts: '2026-09-02T10:00:00+00:00',
      envelope: {
        intent: 'status',
        shell: 'deterministic',
        provider_used: 'deterministic',
        context: { focus_file: 'daedalus/spine/attempt.py', included: 3, withheld_count: 1, trimmed: 0, ambiguous: false }
      }
    },
    {
      id: 45,
      user_message: 'Und der Parser?',
      assistant_text: 'Der Parser ist **robust**.',
      intent: 'chat',
      provider_used: 'claude_code_cli',
      model_used: 'claude',
      created_ts: '2026-09-02T10:05:00+00:00',
      envelope: {
        intent: 'chat',
        shell: 'voice',
        provider_used: 'claude_code_cli',
        model_used: 'claude',
        llm: { provider: 'claude_code_cli', requested: null, auto_selected: true, timeout_s: 150, max_attempts: 1, reason: 'first available' }
      }
    }
  ],
  turns_returned: 2,
  dispatches: [],
  open_dispatches: []
};

const listRows = [
  {
    conversation_id: 'conv_2',
    turn_count: 1,
    first_message: 'Wo würdest du refactoren?',
    last_message: 'Wo würdest du refactoren?',
    last_ts: '2026-09-02T11:00:00+00:00',
    last_intent: 'chat',
    last_provider_used: 'claude_code_cli',
    last_status: 'answered'
  },
  {
    conversation_id: 'conv_1',
    turn_count: 2,
    first_message: 'status',
    last_message: 'Und der Parser?',
    last_ts: '2026-09-02T10:05:00+00:00',
    last_intent: 'chat',
    last_provider_used: 'claude_code_cli',
    last_status: 'answered'
  }
];

async function openCockpit(page: Page, path = '/?view=chat') {
  const response = await page.goto(path, { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
}

async function stubQuietCockpit(page: Page, options: { list?: 'ok' | 'fail' } = {}) {
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], projects: [project] } });
  });
  await page.route('**/api/structure**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], structure: { graph: { nodes: [], edges: [] } } }
  }));
  await page.route('**/api/runtimes/status**', (route) => route.fulfill({
    json: {
      ok: true, generated_at: '', project: null, warnings: [],
      runtimes: [{ id: 'claude_code_cli', label: 'Claude Code', mode: 'cli', available: true, auth_status: 'cli_detected', version: '2.1.233 (Claude Code)' }]
    }
  }));
  await page.route('**/api/drafts**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], scope: project.repo_root, pending_count: 0, drafts: [] }
  }));
  await page.route((url) => url.pathname === '/api/conversations' && url.searchParams.has('project'), async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    if (options.list === 'fail') {
      await route.fulfill({ status: 500, json: { ok: false, error: 'the conversation store failed: OperationalError: locked' } });
      return;
    }
    await route.fulfill({ json: { ok: true, generated_at: '', project: project.name, warnings: [], conversations: listRows } });
  });
  await page.route((url) => /^\/api\/conversations\/conv_1$/.test(url.pathname), (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation: storedView }
  }));
}

test.describe('Verlauf and commands', () => {
  test('the rail lists this project\'s threads from the spine and resumes one on click', async ({ page }) => {
    await stubQuietCockpit(page);
    await page.addInitScript(() => localStorage.removeItem('daedalus-thread:atlas'));
    const seen = collect(page);
    await openCockpit(page);

    const rail = page.getByRole('navigation', { name: 'Verläufe' });
    await expect(rail).toBeVisible();
    await expect(rail.getByText('Wo würdest du refactoren?')).toBeVisible();
    await expect(rail.getByText('2 Turns')).toBeVisible();
    // The rail names the runtime the way the transcript does, once the
    // runtime list has arrived; it never typesets an unknown id as a name.
    await expect(rail.getByText('Claude Code').first()).toBeVisible();

    await rail.getByRole('button', { name: /^status/ }).click();
    await expect(page.locator('.turn.you').first()).toContainText('status');
    await expect(page.locator('.turn.ikarus').first()).toContainText('Alles ruhig.');
    // The stored envelope reaches the Protokoll: route, context, and the stamp
    // that names what produced the answer.
    const first = page.locator('.turn.ikarus').first();
    await expect(first.locator('.ledger-row[data-key="route"]')).toContainText('Lokaler Index');
    await expect(first.locator('.ledger-row[data-key="context"]')).toContainText('attempt.py');
    await expect(first.locator('.ledger-row[data-key="context"]')).toContainText('1 zurückgehalten');
    await expect(first.locator('.stamp')).toContainText('GEMESSEN');
    const second = page.locator('.turn.ikarus').nth(1);
    await expect(second.locator('.ledger-row[data-key="route"]')).toContainText('Automatisch → Claude Code');
    await expect(second.locator('.stamp')).toContainText('MODELL');
    await expect(second.locator('strong')).toHaveText('robust');

    const stored = await page.evaluate(() => localStorage.getItem('daedalus-thread:atlas'));
    expect(stored).toBe('conv_1');
    await expect(rail.locator('.threads-row.current')).toContainText('status');
    expect(seen.pageErrors).toEqual([]);
  });

  test('Neuer Chat in the rail leaves the thread and the page becomes the invitation again', async ({ page }) => {
    await stubQuietCockpit(page);
    await page.addInitScript(() => localStorage.setItem('daedalus-thread:atlas', 'conv_1'));
    await openCockpit(page);
    await expect(page.locator('.turn.you').first()).toContainText('status');

    await page.getByRole('navigation', { name: 'Verläufe' }).getByRole('button', { name: 'Neuer Chat' }).click();
    await expect(page.locator('.convo-open')).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem('daedalus-thread:atlas'))).toBeNull();
  });

  test('a list that cannot be read says so and can be asked again', async ({ page }) => {
    await stubQuietCockpit(page, { list: 'fail' });
    await openCockpit(page);
    const rail = page.getByRole('navigation', { name: 'Verläufe' });
    await expect(rail).toContainText('Die Verläufe konnten nicht gelesen werden');
    await expect(rail.getByRole('button', { name: 'Erneut lesen' })).toBeVisible();
  });

  test('a slash opens the command menu; /hilfe stays on the page and never POSTs', async ({ page }) => {
    await stubQuietCockpit(page);
    let turnPosts = 0;
    await page.route('**/api/conversations/*/turns', async (route) => {
      turnPosts += 1;
      await route.fallback();
    });
    await page.addInitScript(() => localStorage.removeItem('daedalus-thread:atlas'));
    const seen = collect(page);
    await openCockpit(page);

    const input = page.getByLabel('Nachricht an Ikarus');
    await input.fill('/');
    const menu = page.getByRole('listbox', { name: 'Befehle' });
    await expect(menu).toBeVisible();
    await expect(menu.getByRole('option', { name: /\/status/ })).toBeVisible();
    await expect(menu.getByRole('option', { name: /\/hilfe/ })).toBeVisible();

    await input.fill('/hil');
    await expect(menu.getByRole('option')).toHaveCount(1);
    await input.press('Enter');
    const note = page.locator('.turn.note');
    await expect(note).toBeVisible();
    await expect(note.locator('.stamp')).toContainText('OBERFLÄCHE');
    await expect(note).toContainText('/aufwand');
    expect(turnPosts).toBe(0);

    // An argument-taking command is completed, not sent: the hint explains.
    await input.fill('/aufwand');
    await expect(page.locator('.cmd-hint')).toContainText('gering, mittel oder hoch');
    await input.fill('/aufwand hoch');
    await input.press('Enter');
    await expect(page.getByRole('radio', { name: 'hoch' })).toHaveAttribute('aria-checked', 'true');
    expect(turnPosts).toBe(0);
    expect(seen.pageErrors).toEqual([]);
  });

  test('the effort control is sent with the turn, and defaults to low', async ({ page }) => {
    await stubQuietCockpit(page);
    let turnBody: Record<string, unknown> | undefined;
    await page.route('**/api/conversations', (route) => {
      if (route.request().method() !== 'POST') return route.fallback();
      return route.fulfill({ json: { ok: true, generated_at: '', project: project.name, warnings: [], conversation_id: 'conv_new' } });
    });
    await page.route('**/api/conversations/*/turns', async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      turnBody = body;
      await route.fulfill({
        status: 202,
        json: {
          ok: true, generated_at: '', project: project.name, warnings: [], created: true,
          turn_request: { request_id: 7, conversation_id: 'conv_new', client_request_id: body.client_request_id, project: project.name, state: 'streaming' }
        }
      });
    });
    await page.route('**/api/conversations/*/turns/*/events', (route) => route.abort('failed'));
    await page.addInitScript(() => {
      localStorage.removeItem('daedalus-thread:atlas');
      localStorage.removeItem('daedalus-effort:atlas');
    });
    await openCockpit(page);

    await expect(page.getByRole('radio', { name: 'gering' })).toHaveAttribute('aria-checked', 'true');
    await page.getByRole('radio', { name: 'mittel' }).click();
    await page.getByLabel('Nachricht an Ikarus').fill('Wie steht es?');
    await page.getByRole('button', { name: 'Senden' }).click();
    await expect.poll(() => turnBody).toBeTruthy();
    expect(turnBody).toMatchObject({ message: 'Wie steht es?', effort: 'medium' });
    expect(await page.evaluate(() => localStorage.getItem('daedalus-effort:atlas'))).toBe('medium');
    // While the request is out, the Protokoll already shows the answer row live.
    await expect(page.locator('.turn.ikarus .ledger-row[data-key="answer"]')).toContainText('Ikarus denkt');
  });
});
