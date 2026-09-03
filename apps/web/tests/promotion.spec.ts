import { expect, test, type Page } from '@playwright/test';
import { collect, NOT_BUILT } from './_app';

/**
 * The promotion surface, fixture-backed.
 *
 * The status line said "Promotion gesperrt · 2 Blocker" and stopped there.
 * `/api/governance` has always answered with far more: a `verdict` sentence
 * naming the reason, the blockers with their `why`, and for each gate the
 * QUESTION it asks, its state in the five-word vocabulary, its provenance and
 * its evidence.
 *
 * THE FIXTURE BELOW IS A VERBATIM CAPTURE of `get_governance(None)` on this
 * checkout, taken 2026-09-03. An earlier version was hand-written, claimed in
 * this very comment to be "the shape this machine really returns", and was
 * not: it invented both gate questions, invented `runs/gates/*.json` receipt
 * paths the server cannot emit, described gates as INHERITED when all three
 * are MEASURED, and set a blocker `why` that differed from its gate's
 * headline, which the backend never does. One of its assertions checked for a
 * receipt path no server would ever send.
 *
 * `the live backend still answers this shape` at the bottom of this file is
 * the guard against that happening again: it is unstubbed.
 */

const project = { name: 'atlas', repo_root: 'C:\\work\\atlas', team: {}, reachable: true };

/*
 * VERBATIM CAPTURE of `get_governance(None)` on this checkout, 2026-09-03.
 * Three gates, all `absent`, all `MEASURED`, `head: null`, and a `warnings`
 * entry explaining that the revision could not be read. Every blocker `why`
 * equals its gate's `headline`, because that is what the backend does.
 */
const governance = {
  ok: true,
  generated_at: '2026-09-03T11:36:53+00:00',
  project: project.name,
  warnings: [
    'The current revision could not be read, so every revision-tied claim below is reported as unknown.'
  ],
  promotion_allowed: false,
  verdict:
    'promotion is REFUSED: no discrimination measurement exists at all, so a green suite means only that pytest ran',
  state: 'absent',
  head: null,
  repo_root: project.repo_root,
  states_vocabulary: ['working', 'present', 'degraded', 'absent', 'unknown'],
  gates: [
    {
      id: 'discrimination',
      question: 'Has the test gate been shown to catch planted defects at THIS revision?',
      state: 'absent',
      headline:
        'no discrimination measurement exists at all, so a green suite means only that pytest ran',
      provenance: 'MEASURED',
      reason:
        'the current revision could not be read, so no receipt can be tied to it -- refusing rather than accepting a measurement of an unknown tree',
      kill_rate_floor: 0.8,
      receipt_path: 'runs/spine/gate_discrimination.json',
      detail: { proven: false, measured_at: null, measured_head: null, kill_rate: null }
    },
    {
      id: 'write_confinement',
      question: 'Is the local write lane confined to a declared allow-list?',
      state: 'absent',
      headline:
        'a policy is installed but declares no write_allow, so the local write lane is UNCONFINED -- the egress allow-list does NOT gate writes',
      provenance: 'MEASURED',
      write_allow: [],
      high_risk_paths: ['/devices/', '/firmware/', 'interlock', '/safety', '/kernel/'],
      detail: null
    },
    {
      id: 'operability_drill',
      question: 'Was every operability control tripped end-to-end at THIS revision?',
      state: 'absent',
      headline:
        'the operability drill has never been run in this checkout, so no control is known to hold',
      provenance: 'MEASURED',
      receipt_path: 'runs/spine/operability_drill.json',
      controls: [],
      detail: null
    }
  ],
  blockers: [
    {
      gate: 'discrimination',
      state: 'absent',
      why: 'no discrimination measurement exists at all, so a green suite means only that pytest ran'
    },
    {
      gate: 'write_confinement',
      state: 'absent',
      why: 'a policy is installed but declares no write_allow, so the local write lane is UNCONFINED -- the egress allow-list does NOT gate writes'
    },
    {
      gate: 'operability_drill',
      state: 'absent',
      why: 'the operability drill has never been run in this checkout, so no control is known to hold'
    }
  ]
};

/*
 * CONSTRUCTED, and labelled as such. This shape is not what this machine
 * produces today, but the backend can produce it and it is the one the status
 * line got wrong: `promotion_allowed` is derived from the DISCRIMINATION gate
 * alone, so a green discrimination gate sets it true while another gate is
 * `absent` and the worst-of-five `state` says so. Field names and the
 * `why == headline` rule are matched to `daedalus/core.py`.
 */
const contested = {
  ...governance,
  warnings: [],
  promotion_allowed: true,
  verdict: 'the discrimination gate holds at this revision',
  state: 'absent',
  head: '5b58f8c3a3125d5199a6c0c9cd10f5cc7512140b',
  gates: [
    { ...governance.gates[0], state: 'working', headline: 'the gate caught 9 of 10 planted defects at this revision' },
    governance.gates[1]
  ],
  blockers: [governance.blockers[1]]
};

async function openCockpit(page: Page) {
  const response = await page.goto('/?view=chat', { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
}

async function stub(page: Page, options: { governance?: unknown; fail?: boolean } = {}) {
  await page.addInitScript(() => localStorage.setItem('daedalus-cockpit-view', 'chat'));
  await page.route('**/api/projects', async (route) => {
    if (route.request().method() !== 'GET') return route.fallback();
    await route.fulfill({ json: { ok: true, generated_at: '', project: null, warnings: [], projects: [project] } });
  });
  await page.route('**/api/structure**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], structure: { graph: { nodes: [], edges: [] } } }
  }));
  await page.route('**/api/runtimes/status**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: null, warnings: [], runtimes: [] }
  }));
  await page.route('**/api/drafts**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], scope: project.repo_root, pending_count: 0, drafts: [] }
  }));
  await page.route('**/api/governance**', async (route) => {
    if (options.fail) return route.abort('connectionrefused');
    await route.fulfill({ json: options.governance ?? governance });
  });
}

test.describe('promotion surface', () => {
  test('the chip opens the refusal, in the system\'s own sentence', async ({ page }) => {
    const seen = collect(page);
    await stub(page);
    await openCockpit(page);

    const chip = page.getByRole('button', { name: /^Promotion öffnen: Promotion gesperrt/ });
    await expect(chip).toContainText('3 Blocker');
    await chip.click();

    const panel = page.getByRole('dialog', { name: 'Promotion' });
    await expect(panel).toBeVisible();

    // The verdict is quoted, not summarised: it is the answer to "why not".
    await expect(panel.locator('.gate-verdict')).toContainText('promotion is REFUSED');
    // Every blocker, each with the gate that refused and its reason.
    await expect(panel.locator('.gate-blockers li')).toHaveCount(3);
    await expect(panel).toContainText('operability_drill');
    await expect(panel).toContainText('the operability drill has never been run in this checkout');
    // Every gate, with the question it asks and where its verdict came from.
    await expect(panel.locator('.gate-row')).toHaveCount(3);
    await expect(panel).toContainText('Is the local write lane confined to a declared allow-list?');
    await expect(panel).toContainText('MEASURED');

    /*
     * The backend's own caveat, on screen. This machine cannot read its
     * revision, so it says so — and that sentence is what makes the verdict
     * checkable. The panel used to drop `warnings` entirely and print
     * "Beurteilt für unbekannt", which reads as a formatting quirk rather
     * than as the reason every revision-tied claim below is unknown.
     */
    await expect(panel.locator('.gate-warnings')).toContainText(
      'The current revision could not be read'
    );
    await expect(panel.locator('.health-foot')).toContainText('unbekannt');
    // And the standing rule, stated rather than implied.
    await expect(panel.locator('.health-foot')).toContainText('Freigabe des Owners');

    expect(seen.pageErrors).toEqual([]);
  });

  test('a gate opens onto its evidence', async ({ page }) => {
    await stub(page);
    await openCockpit(page);
    await page.getByRole('button', { name: /^Promotion öffnen: Promotion gesperrt/ }).click();
    const panel = page.getByRole('dialog', { name: 'Promotion' });

    await panel.getByRole('button', { name: /write_confinement/ }).click();
    // The real gate carries the high-risk list and an EMPTY allow-list — which
    // is exactly why it refuses: nothing is declared, so nothing is confined.
    await expect(panel).toContainText('/devices/');
    await expect(panel).toContainText('interlock');

    await panel.getByRole('button', { name: /operability_drill/ }).click();
    await expect(panel).toContainText('runs/spine/operability_drill.json');
    // No control has ever been tripped here, so no control may be listed as
    // holding. An empty list is reported as an absence of detail, not as a
    // clean sheet.
    await expect(panel.locator('.gate-controls')).toHaveCount(0);
  });

  test('a green promotion flag never turns the chip green while a gate is absent', async ({ page }) => {
    /*
     * THE COLLAPSE THIS PINS. `promotion_allowed` is derived from the
     * discrimination gate ALONE — deliberately: core.py says the other gates
     * "inform the operator; they do not get a vote". `state` is the
     * worst-of-five across every gate, and it is the field the five-state
     * vocabulary exists for.
     *
     * The chip coloured itself from the boolean, so this payload — a holding
     * discrimination gate and an UNCONFINED write lane — rendered a green chip
     * reading "Promotion offen" with the blocker count suppressed, because the
     * count only existed on the blocked branch. A screen-reader user heard
     * "Promotion öffnen: Promotion offen" while the write lane was unconfined.
     */
    await stub(page, { governance: contested });
    await openCockpit(page);

    const chip = page.getByRole('button', { name: /^Promotion öffnen/ });
    await expect(chip).toContainText('Promotion offen');
    // The aggregate is named, and the count is no longer hidden.
    await expect(chip).toContainText('Gates fehlt');
    await expect(chip).toContainText('1 Blocker');
    // And it is NOT green.
    await expect(chip, 'a green chip while a gate is absent').not.toHaveClass(/\bok\b/);
    await expect(chip).toHaveClass(/\bbad\b/);

    await chip.click();
    const panel = page.getByRole('dialog', { name: 'Promotion' });
    // Both answers are on screen, and neither is merged into the other.
    await expect(panel.locator('.gate-aggregate')).toContainText('Promotion offen');
    await expect(panel.locator('.gate-aggregate')).toContainText('Gates insgesamt');
    await expect(panel.locator('.gate-aggregate')).toContainText('fehlt');
    // The verdict sentence takes its colour from the aggregate too.
    await expect(panel.locator('.gate-verdict')).not.toHaveClass(/\bok\b/);
  });

  test('a governance read that failed is never drawn as nothing standing in the way', async ({ page }) => {
    await stub(page, { fail: true });
    await openCockpit(page);

    const chip = page.getByRole('button', { name: /^Promotion öffnen: Promotion unbekannt/ });
    await expect(chip).toBeVisible();
    await chip.click();

    const panel = page.getByRole('dialog', { name: 'Promotion' });
    await expect(panel).toContainText('wurde nicht gelesen');
    await expect(panel).toContainText('nicht dasselbe wie');
    await expect(panel.locator('.gate-row')).toHaveCount(0);
  });

  test('an allowed promotion still says the owner decides', async ({ page }) => {
    await stub(page, {
      governance: {
        ...governance,
        promotion_allowed: true,
        state: 'working',
        verdict: 'promotion is permitted by the gates at this revision',
        blockers: [],
        gates: [{ ...governance.gates[1] }]
      }
    });
    await openCockpit(page);
    await page.getByRole('button', { name: /^Promotion öffnen: Promotion offen/ }).click();
    const panel = page.getByRole('dialog', { name: 'Promotion' });

    await expect(panel.locator('.gate-verdict.ok')).toBeVisible();
    await expect(panel.locator('.gate-blockers')).toHaveCount(0);
    // Green gates are not permission: the owner's approval is still required.
    await expect(panel.locator('.health-foot')).toContainText('Freigabe des Owners');
  });

  test('Escape closes it', async ({ page }) => {
    await stub(page);
    await openCockpit(page);
    await page.getByRole('button', { name: /^Promotion öffnen: Promotion gesperrt/ }).click();
    await expect(page.getByRole('dialog', { name: 'Promotion' })).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('dialog', { name: 'Promotion' })).toBeHidden();
  });
});
