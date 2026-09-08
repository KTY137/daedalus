import { readFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import { controlledConversation, emitConversation, stubLiveProject } from './_live-fixtures';

/** Ports the former surfaces' negative stream contracts to the one durable UI. */
async function prepare(page: Page, allowProjectSwitch = false) {
  await stubLiveProject(page);
  if (allowProjectSwitch) await page.route('**/api/projects', (route) => route.fulfill({ json: {
    ok: true, projects: ['atlas', 'beta'].map((name) => ({ name, repo_root: `/fixtures/${name}`, reachable: true, team: {} }))
  } }));
  await controlledConversation(page);
  const observed = { creates: 0, legacy: 0, cancels: 0, cancelUrl: '' };
  await page.route('**/api/ikarus/**', async (route) => {
    observed.legacy += 1;
    await route.fulfill({ status: 500, json: { ok: false, error: 'legacy request forbidden' } });
  });
  await page.route('**/api/conversations', (route) => route.fulfill({ json: { ok: true, conversation_id: 'conv_stream' } }));
  await page.route('**/api/conversations/conv_stream/turns', async (route) => {
    observed.creates += 1;
    await route.fulfill({ status: 202, json: { ok: true, created: true, turn_request: {
      request_id: 51, conversation_id: 'conv_stream', project: 'atlas', state: 'streaming',
      client_request_id: route.request().postDataJSON().client_request_id
    } } });
  });
  await page.goto('/?view=chat', { waitUntil: 'domcontentloaded' });
  await expect(page.getByLabel('Nachricht an Ikarus')).toBeVisible();
  return observed;
}

test('a late cancellation response and closed observer cannot relabel another project', async ({ page }) => {
  const observed = await prepare(page, true);
  let release!: () => void;
  const released = new Promise<void>((resolve) => { release = resolve; });
  await page.route('**/api/conversations/conv_stream/turns/51/cancel-requests', async (route) => {
    observed.cancels += 1;
    await released;
    await route.fulfill({ json: { ok: true, cancellation: { request_id: 51, status: 'confirmed', subprocess: {
      request_id: 51, cancellation_requested: true, was_running: true, terminate_sent: true,
      kill_sent: false, process_exited: true, returncode: -15
    } } } });
  });
  await send(page);
  await page.getByRole('button', { name: 'Abbruch anfordern', exact: true }).click();
  await expect.poll(() => observed.cancels).toBe(1);
  await page.locator('.scope-trigger').click();
  await page.getByRole('button', { name: 'beta', exact: true }).click();
  await expect(page.locator('.statusline')).toContainText('beta');
  const response = page.waitForResponse((item) => item.url().endsWith('/turns/51/cancel-requests'));
  release();
  await response;
  await emitConversation(page, 'cancelled', { request_id: 51, status: 'confirmed' });
  await expect(page.getByText('Abbruch bestätigt', { exact: true })).toHaveCount(0);
  await expect(page.locator('.cockpit')).not.toContainText('Lokaler CLI-Prozess beendet');
  expect(observed.creates).toBe(1);
  expect(observed.legacy).toBe(0);
});

async function send(page: Page, message = 'Bound request, no automatic replay') {
  await page.getByLabel('Nachricht an Ikarus').fill(message);
  await page.getByRole('button', { name: 'Senden', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Abbruch anfordern', exact: true })).toBeEnabled();
}

test('the shipping conversation has one durable creation path and no legacy replay closure', () => {
  const source = readFileSync(new URL('../src/features/conversation/Conversation.tsx', import.meta.url), 'utf8');
  expect(source).not.toMatch(/\b(?:askIkarus|streamIkarus|isBackendDown)\s*\(/);
  expect(source).toMatch(/\bcreateConversationTurn\s*\(/);
  expect(source).toMatch(/\bobserveConversationTurn\s*\(/);
});

test('the canonical composer ignores blank input and IME confirmation Enter', async ({ page }) => {
  const observed = await prepare(page);
  const composer = page.getByLabel('Nachricht an Ikarus');
  const submit = page.getByRole('button', { name: 'Senden', exact: true });
  await expect(submit).toBeDisabled();
  await composer.fill('   ');
  await expect(submit).toBeDisabled();
  await composer.fill('入力中');
  await expect(submit).toBeEnabled();
  await composer.evaluate((element) => element.dispatchEvent(new KeyboardEvent('keydown', {
    key: 'Enter', code: 'Enter', bubbles: true, cancelable: true, isComposing: true
  })));
  await expect(composer).toHaveValue('入力中');
  expect(observed.creates + observed.legacy).toBe(0);
});

test('an interrupted durable stream retains partial text without replaying a POST', async ({ page }) => {
  const observed = await prepare(page);
  await send(page);
  await emitConversation(page, 'start', { intent: 'chat', provider_used: 'claude_code_cli' });
  await emitConversation(page, 'delta', { text: 'partial answer' });
  await emitConversation(page, 'error', { error: 'terminal fixture interruption' });
  await expect(page.getByText('partial answer', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Abbruch anfordern', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Ausführen', exact: true })).toHaveCount(0);
  expect(observed.creates).toBe(1);
  expect(observed.legacy).toBe(0);
});

test('an interrupted final never exposes an executable offer', async ({ page }) => {
  const observed = await prepare(page);
  await send(page);
  await emitConversation(page, 'final', {
    ok: true, project: 'atlas', intent: 'enqueue', assistant: 'Incomplete final must not expose an action.',
    provider_used: 'deterministic', stream_interrupted: true,
    action: { kind: 'queue_task', args: { project: 'atlas', objective: 'unsafe duplicate', lane: 'local_only' }, requires_confirmation: true }
  });
  await expect(page.getByText('Incomplete final must not expose an action.', { exact: true })).toBeVisible();
  await expect(page.getByRole('group', { name: 'Vorgeschlagene Aktion beantworten' })).toHaveCount(0);
  expect(observed.creates).toBe(1);
  expect(observed.legacy).toBe(0);
});

for (const evidence of ['absent', 'local-exit', 'foreign-request', 'not-exited', 'exit-without-code', 'code-without-exit', 'not-requested'] as const) {
  test(`cancellation preserves exact durable identity and ${evidence} evidence`, async ({ page }) => {
    const observed = await prepare(page);
    const subprocess = evidence === 'absent' ? undefined : {
      request_id: evidence === 'foreign-request' ? 52 : 51,
      cancellation_requested: evidence !== 'not-requested', was_running: true, terminate_sent: true, kill_sent: false,
      process_exited: evidence !== 'not-exited' && evidence !== 'code-without-exit',
      returncode: evidence === 'not-exited' || evidence === 'exit-without-code' ? null : -15
    };
    await page.route('**/api/conversations/conv_stream/turns/51/cancel-requests', async (route) => {
      observed.cancels += 1;
      observed.cancelUrl = route.request().url();
      expect(route.request().postDataJSON().client_cancel_id).toBeTruthy();
      await route.fulfill({ json: { ok: true, cancellation: { request_id: 51, status: 'requested' } } });
    });
    await send(page);
    await page.getByRole('button', { name: 'Abbruch anfordern', exact: true }).click();
    await expect.poll(() => observed.cancels).toBe(1);
    expect(observed.cancelUrl).toContain('/conversations/conv_stream/turns/51/cancel-requests');
    await expect(page.getByText('Abbruch angefordert – Bestätigung steht aus', { exact: true })).toBeVisible();
    await expect(page.getByText('Abbruch bestätigt', { exact: true })).toHaveCount(0);
    await emitConversation(page, 'cancelled', { status: 'confirmed', request_id: 51, subprocess });
    await expect(page.getByText('Abbruch bestätigt', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: /^Protokoll aufklappen/ }).click();
    const details = page.locator('.ledger-detail');
    await expect(details).toContainText('Remote-Termination nicht bewiesen');
    if (evidence === 'local-exit') await expect(details).toContainText('Lokaler CLI-Prozess beendet');
    else await expect(details).not.toContainText('Lokaler CLI-Prozess beendet');
    expect(observed.creates).toBe(1);
    expect(observed.legacy).toBe(0);
  });
}
