// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

/**
 * "Are the health states distinguishable?"
 *
 * The cockpit ships a CLOSED five-word vocabulary (`apps/web/src/views/health.ts`)
 * in which exactly one word -- `working` -- may be read as a pass. These specs
 * hold that contract from the outside, on `data-state`, which carries the word
 * verbatim and survives any restyle.
 *
 * BOTH HALVES, BECAUSE ONLY THE PAIR IS A CONTROL. A badge that hardcodes one
 * state passes any single-fixture test. Feeding the cockpit a MIXED fleet and
 * then an all-reachable one, and requiring the rendering to change in the right
 * direction, is what proves the surface is reading its input at all --
 * the same reasoning `system_check.py::safety.bus_chain_detects_a_break` uses.
 *
 * The fleet is intercepted rather than observed, because the real fleet on any
 * one machine is whatever it is -- and a fixture you did not choose cannot
 * discriminate.
 */
import { expect, test, type Page } from '@playwright/test';
import { PROVEN_STATE, ALL_STATES, collect, openApp, settle } from './_app';

const UP = 'Acceptance Runtime ALPHA';
const DOWN = 'Acceptance Runtime BETA';

function runtime(label: string, available: boolean) {
  return {
    id: label.toLowerCase().replace(/[^a-z]+/g, '_'),
    label,
    mode: 'cli',
    command: 'acceptance',
    env_key: '',
    local: true,
    trusted_with_ip: true,
    can_write: false,
    agentic: false,
    notes: 'injected by the browser acceptance suite',
    available,
    auth_status: available ? 'cli_detected' : 'not_configured',
    command_path: '',
    version: '',
    models: [],
    selected_model: '',
    model_present: false,
    last_error: available ? '' : 'acceptance: this runtime did not answer',
  };
}

function fleet(...rows: ReturnType<typeof runtime>[]) {
  return {
    status: 200,
    contentType: 'application/json; charset=utf-8',
    body: JSON.stringify({
      ok: true,
      generated_at: new Date().toISOString(),
      project: null,
      warnings: [],
      runtimes: rows,
    }),
  };
}

/** The health state rendered on the row for one runtime.
 *
 *  Located by walking UP from the label text to the nearest ancestor that also
 *  carries a `[data-state]` badge -- structural, but structure-agnostic: no
 *  class name, no nesting depth, no ordering assumption. */
async function stateFor(page: Page, label: string): Promise<{ state: string; text: string }> {
  // SCOPED TO THE HEALTH SURFACE (the complementary landmark). The same runtime
  // label also appears as an <option> in the brain selector, and an unscoped
  // document search finds that one first -- then walks up into a container
  // holding three unrelated badges and asserts against whichever it meets.
  // That is a spec measuring the wrong subsystem while looking green.
  const rail = page.getByRole('complementary').first();
  await expect(rail, 'the live rail (the health surface) did not render').toBeVisible();
  return rail.evaluate((root, lbl) => {
    // The element that OWNS the label as its own text -- not an ancestor that
    // merely contains it.
    const holder = Array.from(root.querySelectorAll<HTMLElement>('*')).find((el) =>
      Array.from(el.childNodes).some((n) => n.nodeType === Node.TEXT_NODE && (n.textContent || '').trim() === lbl),
    );
    if (!holder) return { state: '(the runtime is not on screen at all)', text: '' };

    // Walk up only until an ancestor holds EXACTLY ONE badge. Stopping at the
    // first badge found would walk past the row into a container whose badge
    // belongs to something else entirely -- which is how a spec ends up
    // asserting against the wrong subsystem's health and never noticing.
    let node: HTMLElement | null = holder;
    for (let depth = 0; node && depth < 10; depth++, node = node.parentElement) {
      const badges = node.querySelectorAll<HTMLElement>('[data-state]');
      if (badges.length === 1) {
        return { state: badges[0].getAttribute('data-state') || '', text: (node.innerText || '').trim() };
      }
      if (badges.length > 1) {
        return {
          state: `(walked past the row: ${badges.length} health badges in the nearest ancestor)`,
          text: (node.innerText || '').trim().slice(0, 300),
        };
      }
    }
    return { state: '(no health badge anywhere around this runtime)', text: (holder.parentElement?.innerText || '').trim().slice(0, 300) };
  }, label);
}

/** The Connections card must actually be showing runtimes before any statement
 *  about their health means anything. */
async function expectFleetRendered(page: Page, ...labels: string[]): Promise<void> {
  const rail = page.getByRole('complementary').first();
  for (const label of labels) {
    // Substring, not exact: the label shares its element with the mode/auth
    // subtitle, so an exact-text match would fail on a row that is rendering
    // perfectly -- a red that says nothing about the product.
    await expect(
      rail.getByText(label).first(),
      `the injected runtime ${JSON.stringify(label)} never reached the health surface`,
    ).toBeVisible({ timeout: 20_000 });
  }
}

test('a mixed fleet renders TWO different health states', async ({ page }) => {
  const seen = collect(page);
  await page.route('**/api/runtimes/status*', (r) => r.fulfill(fleet(runtime(UP, true), runtime(DOWN, false))));
  await openApp(page);
  await settle(page, seen);
  await expectFleetRendered(page, UP, DOWN);

  const up = await stateFor(page, UP);
  const down = await stateFor(page, DOWN);

  expect(ALL_STATES, `the reachable runtime rendered state ${JSON.stringify(up.state)}, which is not one of the five. Row read:\n${up.text}`).toContain(up.state);
  expect(ALL_STATES, `the unreachable runtime rendered state ${JSON.stringify(down.state)}, which is not one of the five. Row read:\n${down.text}`).toContain(down.state);

  expect(
    down.state,
    `a runtime that did NOT answer is rendered as ${JSON.stringify(down.state)} -- ` +
      `a dead runtime is indistinguishable from a live one. Row read:\n${down.text}`,
  ).not.toEqual(up.state);
  expect(
    ['degraded', 'absent'],
    `a runtime that did NOT answer rendered as ${JSON.stringify(down.state)}; ` +
      'the only honest states for "configured and it did not answer" are degraded or absent',
  ).toContain(down.state);
});

test('an all-reachable fleet renders NO failed state (the control)', async ({ page }) => {
  // Without this half, a badge that always said DEGRADED would pass the test
  // above.
  const seen = collect(page);
  await page.route('**/api/runtimes/status*', (r) => r.fulfill(fleet(runtime(UP, true), runtime(DOWN, true))));
  await openApp(page);
  await settle(page, seen);
  await expectFleetRendered(page, UP, DOWN);

  const up = await stateFor(page, UP);
  const down = await stateFor(page, DOWN);

  expect(up.state, `two reachable runtimes rendered differently (${up.state} vs ${down.state}) -- the badge is not a function of the data`).toEqual(down.state);
  expect(
    ['degraded', 'absent'],
    `a REACHABLE runtime is rendered as ${JSON.stringify(up.state)}; the health indicator is inverted. Row read:\n${up.text}`,
  ).not.toContain(up.state);
});

test('reachable is NOT rendered as proven -- presence is not a pass', async ({ page }) => {
  // The invariant `views/health.ts` was written for, held from the outside: a
  // runtime found on PATH has been INSTALLED, not EXERCISED, and a billable
  // call was deliberately never made. A cockpit that paints that green is the
  // exact defect the five-word vocabulary exists to prevent -- and it is the
  // one an acceptance suite must pin, because it is invisible in a screenshot.
  const seen = collect(page);
  await page.route('**/api/runtimes/status*', (r) => r.fulfill(fleet(runtime(UP, true))));
  await openApp(page);
  await settle(page, seen);
  await expectFleetRendered(page, UP);

  const up = await stateFor(page, UP);
  expect(
    up.state,
    'a runtime that was merely FOUND is rendered as proven-working. Nothing invoked it, ' +
      'so this run established no such thing -- and no billable call may be made to establish it.',
  ).not.toEqual(PROVEN_STATE);
});

test('BYOK readiness is stated as a count, not a vibe', async ({ page }) => {
  const seen = collect(page);
  await openApp(page);
  await settle(page, seen);

  const badge = page.getByLabel(/BYOK readiness/i).first();
  await expect(badge, 'no BYOK readiness indicator rendered').toBeVisible();
  const name = (await badge.getAttribute('aria-label')) || '';
  expect(name, `the BYOK indicator states no counts: ${JSON.stringify(name)}`).toMatch(/\d+\s+of\s+\d+/i);
});
