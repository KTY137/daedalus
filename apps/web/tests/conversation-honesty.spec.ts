import { expect, test, type Page } from '@playwright/test';
import { controlledConversation, emitConversation, stubLiveProject } from './_live-fixtures';

/**
 * G1-UI-22 — the cockpit says what the run cost, why it ended, and exactly
 * what a confirmed offer will run.
 *
 * Every frame here is fixture data through the controlled EventSource. No
 * provider is called and no money is spent: the measured budget state on this
 * host already carries a $3.00 reserve and settle against a $5.00 daily
 * ceiling, so a live probe would be refused anyway.
 */

const RUN_LLM = {
  provider: 'claude_code_cli',
  requested: null,
  auto_selected: true,
  timeout_s: 150,
  max_attempts: 1,
  attempts: 1,
  cost_usd_measured: 0.4056,
  cost_basis: 'provider_reported',
  duration_ms: 18900,
  stop_reason: 'tool_use',
  subtype: 'error_max_turns',
  num_turns: 2,
  model_used: 'claude-opus-5[1m]'
};

interface Observed {
  creates: number;
  legacy: number;
  queued: number;
  queuedBody: Record<string, unknown> | null;
  mintDelayMs: number;
}

async function prepare(page: Page): Promise<Observed> {
  await stubLiveProject(page);
  await controlledConversation(page);
  const observed: Observed = { creates: 0, legacy: 0, queued: 0, queuedBody: null, mintDelayMs: 0 };
  await page.route('**/api/ikarus/**', (route) => {
    observed.legacy += 1;
    return route.fulfill({ status: 500, json: { ok: false, error: 'legacy request forbidden' } });
  });
  await page.route('**/api/conversations', async (route) => {
    if (observed.mintDelayMs > 0) await new Promise((resolve) => setTimeout(resolve, observed.mintDelayMs));
    await route.fulfill({ json: { ok: true, conversation_id: 'conv_stream' } });
  });
  await page.route('**/api/conversations/conv_stream/turns', async (route) => {
    observed.creates += 1;
    await route.fulfill({ status: 202, json: { ok: true, created: true, turn_request: {
      request_id: 51, conversation_id: 'conv_stream', project: 'atlas', state: 'streaming',
      client_request_id: route.request().postDataJSON().client_request_id
    } } });
  });
  await page.route('**/api/queue', async (route) => {
    observed.queued += 1;
    observed.queuedBody = route.request().postDataJSON();
    await route.fulfill({ json: { ok: true, id: 'req_fixture', conversation_link: { linked: false } } });
  });
  await page.goto('/?view=chat', { waitUntil: 'domcontentloaded' });
  await expect(page.getByLabel('Nachricht an Ikarus')).toBeVisible();
  return observed;
}

async function send(page: Page, message = 'verbessere Daedalus') {
  await page.getByLabel('Nachricht an Ikarus').fill(message);
  await page.getByRole('button', { name: 'Senden', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Abbruch anfordern', exact: true })).toBeEnabled();
}

/** The measured first-frame property: the turn is painted before the mint. */
test('the sent turn and its phase are painted before the thread mint answers', async ({ page }) => {
  const observed = await prepare(page);
  observed.mintDelayMs = 3000;
  const message = 'verbessere Daedalus';
  await page.getByLabel('Nachricht an Ikarus').fill(message);
  const started = Date.now();
  await page.getByRole('button', { name: 'Senden', exact: true }).click();
  await expect(page.locator('.turn.you').last()).toContainText(message);
  await expect(page.locator('.turn.ikarus').last()).toContainText('Anfrage wird angelegt');
  const painted = Date.now() - started;
  expect(painted, `first frame took ${painted} ms while the mint was held for 3000 ms`).toBeLessThan(500);
  expect(observed.creates).toBe(0);
  expect(observed.legacy).toBe(0);
});

test('a finished run states its duration, its cost with the basis, and how it ended', async ({ page }) => {
  const observed = await prepare(page);
  await send(page);
  await emitConversation(page, 'start', {
    intent: 'chat', shell: 'voice', provider_used: 'claude_code_cli', model_used: 'claude-opus-5[1m]', timeout_s: 150
  });
  await emitConversation(page, 'final', {
    ok: true, project: 'atlas', intent: 'error', shell: 'voice',
    assistant: 'claude_code_cli did not return a usable answer after 1 attempt(s).',
    provider_used: 'claude_code_cli', llm: RUN_LLM, turn_id: 90, conversation_persisted: true
  });
  const turn = page.locator('.turn.ikarus').last();
  // The Protokoll is still COLLAPSED: these are datum lines, not disclosure.
  await expect(turn).toContainText('18,9 s (Anbieter) · 0,41 USD (gemessen) · Ende: Turn-Limit des Anbieters erreicht');
  await expect(turn).toContainText('Anbieter beendet: Turn-Limit des Anbieters erreicht');
  await expect(turn.locator('.ledger-detail')).toHaveCount(0);
  // The server's own sentence stays byte-identical beside the derived reason.
  await expect(turn.locator('.turn-text')).toContainText('claude_code_cli did not return a usable answer after 1 attempt(s).');
  expect(observed.legacy).toBe(0);
});

test('provider stderr never reaches the answer bubble and stays behind the disclosure', async ({ page }) => {
  await prepare(page);
  const leak = 'ANTHROPIC_API_KEY=sk-live-XXXX at C:/Users/Administrator/.local/bin/claude.exe';
  await send(page);
  await emitConversation(page, 'final', {
    ok: true, project: 'atlas', intent: 'error', assistant: 'Kein Ergebnis.',
    provider_used: 'claude_code_cli', llm: { ...RUN_LLM, stderr_tail: `${leak} ${'x'.repeat(900)}` }
  });
  const turn = page.locator('.turn.ikarus').last();
  await expect(turn.locator('.turn-text')).not.toContainText('sk-live-XXXX');
  await expect(turn.locator('.ledger-detail')).toHaveCount(0);
  await turn.getByRole('button', { name: /Protokoll aufklappen/ }).click();
  const detail = turn.locator('.ledger-detail li', { hasText: 'sk-live-XXXX' });
  await expect(detail).toHaveCount(1);
  await expect(detail).toContainText('Provider-stderr (gekürzt, ungeprüft):');
  const shown = await detail.innerText();
  expect(shown.length).toBeLessThan(560);
  // It reached the DOM as escaped text, never through the markdown renderer.
  await expect(turn.locator('.turn-text a, .turn-text code')).toHaveCount(0);
});

test('an offered action states what it will run before any click, and the request matches it', async ({ page }) => {
  const observed = await prepare(page);
  await send(page, 'mach Daedalus besser');
  await emitConversation(page, 'final', {
    ok: true, project: 'atlas', intent: 'enqueue', assistant: 'Soll ich?', provider_used: 'deterministic',
    turn_id: 91, conversation_persisted: true,
    action: { kind: 'queue_task', args: { project: 'atlas', objective: 'Parser härten', lane: 'local_only' }, requires_confirmation: true }
  });
  const panel = page.locator('.offer-confirm').last();
  await expect(panel).toContainText('queue_task');
  await expect(panel).toContainText('atlas');
  await expect(panel).toContainText('local_only');
  await expect(panel).toContainText('Parser härten');
  await expect(panel).toContainText('Nominierung, keine Übernahme. Nichts wird automatisch gemerged oder promotet; die Freigabe bleibt beim Owner.');
  await expect(panel).toContainText('nicht übermittelt');
  expect(observed.queued).toBe(0);

  await page.getByRole('button', { name: 'Loslegen', exact: true }).click();
  await expect.poll(() => observed.queued).toBe(1);
  expect(observed.queuedBody).toEqual(expect.objectContaining({
    project: 'atlas', objective: 'Parser härten', lane: 'local_only', conversation_id: 'conv_stream', turn_id: 91
  }));
});

for (const [name, revision, shown] of [
  ['a full revision', 'db38a762991b04cbc96c3cbed5209d6a517fa611', 'db38a762991b'],
  ['a truncated revision', 'db38a762991b04cbc96c3cbed5209d6a517fa61', 'unlesbar übermittelt']
] as const) {
  test(`${name} is reported exactly as it arrived`, async ({ page }) => {
    await prepare(page);
    await send(page, 'mach Daedalus besser');
    await emitConversation(page, 'final', {
      ok: true, project: 'atlas', intent: 'enqueue', assistant: 'Soll ich?', provider_used: 'deterministic',
      action: {
        kind: 'queue_task',
        args: { project: 'atlas', objective: 'Parser härten', lane: 'local_only', source_revision: revision },
        requires_confirmation: true
      }
    });
    const panel = page.locator('.offer-confirm').last();
    await expect(panel).toContainText(shown);
    if (shown === 'db38a762991b') {
      await expect(panel.locator('dd[title]')).toHaveAttribute('title', revision);
    } else {
      await expect(panel).not.toContainText(revision);
    }
  });
}

test('a descriptive requires_confirmation:false never becomes UI authority', async ({ page }) => {
  const observed = await prepare(page);
  await send(page, 'mach Daedalus besser');
  await emitConversation(page, 'final', {
    ok: true, project: 'atlas', intent: 'enqueue', assistant: 'Soll ich?', provider_used: 'deterministic',
    action: { kind: 'queue_task', args: { project: 'atlas', objective: 'Parser härten', lane: 'local_only' }, requires_confirmation: false }
  });
  await expect(page.locator('.offer-confirm').last())
    .toContainText('Der Server meldet „requires_confirmation: false“. Diese Oberfläche fragt trotzdem.');
  await page.waitForTimeout(1000);
  expect(observed.queued).toBe(0);
  await page.getByRole('button', { name: 'Loslegen', exact: true }).click();
  await expect.poll(() => observed.queued).toBe(1);
});

test('an action kind this cockpit has no endpoint for is drawn and inert', async ({ page }) => {
  const observed = await prepare(page);
  await send(page, 'mach Daedalus besser');
  await emitConversation(page, 'final', {
    ok: true, project: 'atlas', intent: 'enqueue', assistant: 'Soll ich?', provider_used: 'deterministic',
    action: { kind: 'run_campaign', args: { project: 'atlas', objective: 'Self-Renovation', lane: 'local_only' }, requires_confirmation: true }
  });
  const panel = page.locator('.offer-confirm').last();
  await expect(panel).toContainText('run_campaign');
  await expect(panel).toContainText('Diese Oberfläche kennt für „run_campaign“ keinen Ausführungsweg. Nichts wurde gesendet.');
  await expect(page.getByRole('button', { name: 'Loslegen', exact: true })).toBeDisabled();
  await page.waitForTimeout(1000);
  expect(observed.queued).toBe(0);
});
