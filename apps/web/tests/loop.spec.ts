// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

/**
 * The self-improvement loop, seen from the cockpit.
 *
 * TWO LAYERS, TAGGED SEPARATELY, ON PURPOSE.
 *
 *   (untagged)  the CONTRACT: the loop's queue reaches the browser, over the
 *               app's own origin, with the measurement that put each candidate
 *               there. Read against the REAL picker, whatever mood it is in.
 *
 *   @loopui     the SURFACE: a human looking at the cockpit can see it. Read
 *               against an INJECTED queue, because a spec whose subject is
 *               "does this render" must not also depend on the picker having
 *               found something today. Determinism is a property here, not a
 *               convenience: the live queue is currently degraded, and a spec
 *               that passed only when work happened to exist would be telling
 *               us about the repo, not about the cockpit.
 *
 * Neither layer is ever skipped. If the cockpit renders no loop surface, the
 * @loopui specs go RED and name it.
 */
import { expect, test, type Page } from '@playwright/test';
import { apiJson, collect, openApp, openSpace, settle, visibleText } from './_app';

interface Candidate {
  task_id: string;
  source: string;
  score: number | null;
  reason: string;
  instruction: string;
  evidence: Record<string, unknown>;
}
interface QueueBody {
  ok: boolean;
  warnings: string[];
  queue: {
    candidates: Candidate[];
    n_candidates: number;
    degraded_sources: string[];
    incomplete: boolean;
    notes: string[];
    sources: Record<string, unknown>;
  };
}

const KNOWLEDGE = /knowledge/i;

function candidate(task_id: string, source: string, score: number): Candidate {
  return {
    task_id,
    source,
    score,
    reason: `acceptance fixture: ranked ${score} because the module changed and its gate is thin`,
    instruction: `raise coverage on ${task_id}`,
    evidence: { changed_lines: 42, gate_paths: 1, prior_attempts: 0 },
  };
}

function queuePayload(candidates: Candidate[], degraded: string[]) {
  const warnings = degraded.length
    ? [
        `INCOMPLETE: ${degraded.join(', ')} could not be consulted, so this queue is not ` +
          'the whole picture -- an empty or short queue here is NOT evidence that there is no work.',
      ]
    : [];
  const sources: Record<string, unknown> = { map_island: { ran: true, candidates: candidates.length } };
  for (const d of degraded) sources[d] = { error: 'acceptance fault injection: this source failed' };
  return {
    status: 200,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify({
      ok: true,
      generated_at: new Date().toISOString(),
      project: null,
      warnings,
      queue: {
        candidates,
        n_candidates: candidates.length,
        limit: 10,
        sources,
        notes: [],
        degraded_sources: degraded,
        incomplete: degraded.length > 0,
        opt_in_sources_available: false,
        returned: candidates.length,
        dropped_for_size: 0,
      },
    }),
  };
}

async function queue(page: Page, limit = 10): Promise<QueueBody> {
  const res = await apiJson<QueueBody>(page, `/api/loop/queue?limit=${limit}`);
  expect(res.status, `/api/loop/queue answered ${res.status} to the app's own origin`).toBe(200);
  expect(res.body?.ok, `/api/loop/queue answered not-ok: ${JSON.stringify(res.body).slice(0, 300)}`).toBe(true);
  expect(res.body?.queue, '/api/loop/queue answered without a queue block').toBeTruthy();
  return res.body;
}

async function knowledgeSpace(page: Page): Promise<string> {
  const buttons = page.getByRole('navigation').getByRole('button');
  const labels = await buttons.evaluateAll((els) => els.map((e) => e.getAttribute('aria-label') || ''));
  const target = labels.find((l) => KNOWLEDGE.test(l));
  expect(target, `the cockpit offers no knowledge space. Dock: ${JSON.stringify(labels)}`).toBeTruthy();
  await openSpace(page, target!);
  return target!;
}

// --------------------------------------------------------------------------- //
// the contract -- against the REAL picker                                      //
// --------------------------------------------------------------------------- //
test('the loop queue reaches the browser with its evidence attached', async ({ page }) => {
  const seen = collect(page);
  await openApp(page);
  await settle(page, seen);

  const q = (await queue(page, 10)).queue;

  // A queue of opinion is not a queue. `system_check.py::picker.ranks_with_evidence`
  // holds this at the CLI; this holds it at the socket the cockpit reads from.
  const naked = q.candidates.filter((c) => !c.reason?.trim() || !c.evidence || Object.keys(c.evidence).length === 0);
  expect(
    naked.map((c) => c.task_id),
    'candidate(s) crossed to the browser with no reason or no evidence -- a cockpit ' +
      'rendering those would be showing opinion as measurement',
  ).toEqual([]);

  for (const c of q.candidates.slice(0, 5)) {
    expect(c.task_id?.trim(), 'a candidate arrived with no task_id').not.toEqual('');
    expect(c.source?.trim(), `candidate ${c.task_id} arrived with no source`).not.toEqual('');
  }
});

test('an EMPTY loop queue always arrives with a reason', async ({ page }) => {
  // The exact shape of the escape this repo already paid for: a queue that is
  // short because a source FAILED must never be indistinguishable from a queue
  // that is short because the work is done.
  const seen = collect(page);
  await openApp(page);
  await settle(page, seen);

  const body = await queue(page, 10);
  const q = body.queue;
  const degraded = q.degraded_sources || [];

  expect(
    q.incomplete,
    `the queue reports degraded_sources=${JSON.stringify(degraded)} but incomplete=${q.incomplete}; ` +
      'a client branching on `incomplete` would misread it',
  ).toBe(degraded.length > 0);

  if (q.candidates.length === 0) {
    expect(
      degraded.length > 0 || (q.notes || []).length > 0,
      'the queue is EMPTY and carries neither a degraded source nor a note -- there is ' +
        'no way to tell "nothing to do" from "could not look"',
    ).toBe(true);
  }
  if (degraded.length > 0) {
    expect(
      (body.warnings || []).join(' '),
      `sources ${JSON.stringify(degraded)} were degraded but the envelope carries no INCOMPLETE warning`,
    ).toMatch(/INCOMPLETE/i);
  }
});

test('the loop ledger and the architecture snapshot answer the browser too', async ({ page }) => {
  const seen = collect(page);
  await openApp(page);
  await settle(page, seen);

  const attempts = await apiJson<any>(page, '/api/loop/attempts?limit=5');
  expect(attempts.status, `/api/loop/attempts answered ${attempts.status}`).toBe(200);
  const led = attempts.body?.attempts?.ledger;
  expect(led, '/api/loop/attempts answered without a ledger block').toBeTruthy();
  // "no ledger yet" and "the ledger would not open" are DIFFERENT facts and the
  // endpoint must keep them apart.
  expect(led.exists === false ? Boolean(led.note) : true, 'the ledger is absent and the answer says nothing about why').toBe(true);
  expect(led.read_only, 'the cockpit ledger read did not declare itself read-only').toBe(true);

  const arch = await apiJson<any>(page, '/api/loop/architecture');
  expect(arch.status, `/api/loop/architecture answered ${arch.status}`).toBe(200);
  const a = arch.body?.architecture;
  expect(a, '/api/loop/architecture answered without an architecture block').toBeTruthy();
  expect(a.trusted === false ? Boolean(a.trust_reason) : true, 'the architecture snapshot is untrusted and the answer gives no reason').toBe(true);
});

// --------------------------------------------------------------------------- //
// the surface -- against an INJECTED queue                                     //
// --------------------------------------------------------------------------- //
const A = candidate('acceptance-candidate-alpha-7f31c2', 'map_island', 830);
const B = candidate('acceptance-candidate-beta-9d02ab', 'eval_baseline', 610);

test('@loopui a human can SEE the ranked candidates, with the reason they were ranked', async ({ page }) => {
  const seen = collect(page);
  await page.route('**/api/loop/queue*', (r) => r.fulfill(queuePayload([A, B], [])));
  await openApp(page);
  await settle(page, seen);

  const space = await knowledgeSpace(page);
  const text = await visibleText(page);

  expect(
    text,
    `the loop queue served 2 candidates and ${JSON.stringify(space)} does not render ` +
      `${JSON.stringify(A.task_id)}. The loop is inspectable over HTTP and invisible on screen. Screen:\n${text.slice(0, 900)}`,
  ).toContain(A.task_id);
  expect(text, `the second candidate ${JSON.stringify(B.task_id)} is not rendered -- the queue is truncated on screen`).toContain(B.task_id);

  // A row without its evidence is a row nobody can argue with.
  expect(
    text,
    'the candidates render without the reason they were ranked -- the cockpit is ' +
      'showing a to-do list where the product promises a measurement',
  ).toMatch(/ranked 830|changed_lines|prior_attempts/i);
});

test('@loopui a degraded loop source renders as a WARNING, never as "no work"', async ({ page }) => {
  // THE PROPERTY THIS WHOLE HARNESS EXISTS FOR, one layer up from the picker's
  // exit code: zero candidates BECAUSE a source failed must not paint the same
  // screen as zero candidates because there is nothing to do.
  const seen = collect(page);
  await page.route('**/api/loop/queue*', (r) => r.fulfill(queuePayload([], ['map_island', 'inventory'])));
  await openApp(page);
  await settle(page, seen);

  await knowledgeSpace(page);
  const text = await visibleText(page);

  expect(
    text,
    'the queue came back with ZERO candidates and degraded_sources=["map_island","inventory"], ' +
      `and no visible surface names the failed source. Screen:\n${text.slice(0, 900)}`,
  ).toMatch(/map_island/);
  expect(
    text,
    'the failed source is named but the screen never says the queue is INCOMPLETE ' +
      'because of it -- "we could not look" is being shown as "there is nothing there"',
  ).toMatch(/DEGRADED|INCOMPLETE|could not be consulted|failed/i);

  // And the degradation must be reachable without hunting for it: the top bar
  // carries it from every space (App.tsx renders `loopDegraded` there).
  await page.getByRole('navigation').getByRole('button', { name: /chat/i }).first().click();
  await page.waitForTimeout(700);
  const fromChat = await visibleText(page);
  expect(
    fromChat,
    'the degraded loop source is invisible from the chat home surface -- an operator ' +
      `who never opens the knowledge space would never learn a source failed. Screen:\n${fromChat.slice(0, 600)}`,
  ).toMatch(/DEGRADED|sources? failed|could not be consulted/i);
});
