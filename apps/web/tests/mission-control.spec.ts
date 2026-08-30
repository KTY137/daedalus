// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import { expect, test } from '@playwright/test';
import { collect, failJson, openApp, settle } from './_app';

test('Mission Control exposes the operating truth before the conversation', async ({ page }) => {
  const seen = collect(page);
  await openApp(page);
  await settle(page, seen);

  const control = page.getByRole('region', { name: /Evolution control/i });
  await expect(control, 'the primary cockpit has no Mission Control overview').toBeVisible();
  await expect(control.getByText('system proof', { exact: true })).toBeVisible();
  await expect(control.getByText('provider sample', { exact: true })).toBeVisible();
  await expect(control.getByText('live evolution path', { exact: true })).toBeVisible();
  await expect(control.getByText('governance', { exact: true })).toBeVisible();
  await expect(control.getByText('Evidence console', { exact: true })).toBeVisible();

  // Mission Control is an overview, not a replacement for the product's main
  // interaction. The composer remains operable directly beneath it.
  await expect(page.getByLabel('Ask Ikarus')).toBeVisible();
  await expect(page.getByLabel('Ask Ikarus')).toBeEnabled();
});

test('a failed provider sample is UNKNOWN, never cached as reachable', async ({ page }) => {
  await page.route('**/api/providers/status*', (route) => (
    route.fulfill(failJson('provider availability could not be sampled'))
  ));
  const seen = collect(page);
  await openApp(page);
  await settle(page, seen);

  const control = page.getByRole('region', { name: /Evolution control/i });
  await expect(control).toBeVisible();
  await expect(control.getByText('endpoint unread', { exact: true })).toBeVisible();
  await expect(control.getByText('unknown', { exact: true }).first()).toBeVisible();

  const rail = page.getByRole('complementary').first();
  await expect(rail.getByText(/Provider sample failed/i)).toBeVisible();
  const providerFailureState = await rail
    .getByText(/Provider sample failed/i)
    .locator('xpath=ancestor::*[.//*[@data-state]][1]')
    .locator('[data-state]')
    .first()
    .getAttribute('data-state');
  expect(providerFailureState, 'a failed provider sample rendered as a proven state').toBe('unknown');
});

test('loop gate reason, lifecycle gaps and HTTP bounds are visible', async ({ page }) => {
  const queue = {
    ok: true,
    generated_at: new Date().toISOString(),
    project: 'agent_env',
    warnings: [],
    queue: {
      candidates: [{
        task_id: 'mc-windowed-rewrite',
        source: 'docref',
        score: 812,
        band: 800,
        measured_offset: 12,
        reason: 'two broken references measured in HANDOFF.md',
        instruction: 'repair the bounded line windows',
        gate_paths: ['tests/test_docrefs.py'],
        evidence: { broken_refs: 2 }
      }],
      n_candidates: 1,
      limit: 10,
      sources: { docref: { ran: true, candidates: 1 } },
      notes: [],
      degraded_sources: [],
      incomplete: false,
      opt_in_sources_available: false,
      returned: 1,
      dropped_for_size: 0,
      response_bytes: 2400
    }
  };
  const attempts = {
    ok: true,
    generated_at: new Date().toISOString(),
    project: null,
    warnings: [],
    attempts: {
      intents: [{
        intent_id: 77,
        kind: 'candidate_attempt',
        state: 'failed',
        created_ts: new Date().toISOString(),
        resolved_ts: new Date().toISOString(),
        effect_key: 'mc-windowed-rewrite',
        task_id: 'mc-windowed-rewrite',
        instruction: 'repair the bounded line windows',
        source: 'docref',
        score: 812,
        reason: 'write gate refused because target references remain broken',
        outcome: 'failed',
        gates_passed: false,
        changed_paths: 1,
        error: 'docref verifier still found stale targets'
      }],
      limit: 20,
      kind: 'candidate_attempt',
      task_id: null,
      ledger: { path: 'runs/spine/ledger.sqlite3', exists: true, read_only: true, error: null, note: null },
      degraded_sources: [],
      incomplete: false,
      attempt_intent_kind: 'candidate_attempt',
      returned: 1,
      dropped_for_size: 0,
      response_bytes: 1800
    }
  };
  const dashboard = {
    ok: true,
    generated_at: new Date().toISOString(),
    project: 'agent_env',
    warnings: [],
    selected_project: 'agent_env',
    queue: { pending: [], reports: [] },
    governance: {
      ok: true,
      generated_at: new Date().toISOString(),
      project: 'agent_env',
      warnings: [],
      promotion_allowed: false,
      verdict: 'promotion is REFUSED: discrimination receipt is stale',
      state: 'degraded',
      head: '0123456789abcdef',
      gates: [{
        id: 'discrimination',
        question: 'does the gate discriminate?',
        state: 'degraded',
        headline: 'discrimination receipt is stale',
        provenance: 'INHERITED'
      }],
      blockers: [{ gate: 'discrimination', state: 'degraded', why: 'receipt is stale' }]
    }
  };

  await page.route('**/api/loop/queue*', (route) => route.fulfill({ json: queue }));
  await page.route('**/api/loop/attempts*', (route) => route.fulfill({ json: attempts }));
  await page.route('**/api/dashboard*', (route) => route.fulfill({ json: dashboard }));
  const seen = collect(page);
  await openApp(page);
  await settle(page, seen);

  const control = page.getByRole('region', { name: /Evolution control/i });
  await expect(control.getByText('mc-windowed-rewrite', { exact: true })).toBeVisible();
  await expect(control.getByText(/docref verifier still found stale targets/i)).toBeVisible();
  await expect(control.getByText(/discrimination receipt is stale/i).first()).toBeVisible();
  await expect(control.getByText('not reported', { exact: true }).first()).toBeVisible();

  await control.getByText('Evidence console', { exact: true }).click();
  await expect(control.getByText('2,400 bytes', { exact: true })).toBeVisible();
  await expect(control.getByText('not served', { exact: true })).toBeVisible();
});
