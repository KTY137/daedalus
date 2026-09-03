import { expect, test, type Page } from '@playwright/test';
import { NOT_BUILT } from './_app';

/**
 * THE COMPUTE SECTION, in a browser.
 *
 * The reading rules are pinned without a browser in
 * `src/features/system/accelerators.spec.ts`. What is checked HERE is the
 * thing a unit test cannot see: that the rules are actually the ones the
 * rendered section used, and that the shallow answer is labelled as shallow
 * on screen rather than only in a comment.
 */

const LIVE = 'http://127.0.0.1:8765';

/** The shallow shape the real server returns with no `?deep=1`. */
function shallow(over: Record<string, unknown> = {}) {
  const fw = (detail = 'deep probe not requested') => ({
    installed: false, cuda_ready: null, detail, probed: false
  });
  return {
    ok: true,
    generated_at: '2026-09-03T11:15:13+00:00',
    project: null,
    warnings: [],
    accelerators: {
      schema: 'daedalus-accelerators/1',
      hardware: {
        available: true,
        command: 'nvidia-smi',
        devices: [{ name: 'NVIDIA GeForce RTX 5080', compute_capability: '12.0', memory_mib: 16303, driver_version: '610.47' }],
        error: ''
      },
      frameworks: { torch: fw(), cupy: fw() },
      lanes: [
        {
          id: 'tensor_inference', label: 'CUDA tensor inference', state: 'missing',
          applicable_to: ['embedding batches'], evidence: [],
          missing: ['CUDA-capable PyTorch or CuPy runtime'], warning: ''
        },
        {
          id: 'dlss', label: 'DLSS', state: 'unsupported',
          applicable_to: [], evidence: [], missing: ['general tensor API'],
          warning: 'DLSS is inspiration for DSS, not an executable Daedalus backend'
        }
      ],
      remote_compute: { configured: false, available: null, target: '', devices: [], error: '', hint: 'set DAEDALUS_RTX_SSH=user@host' },
      claims: {
        hardware_visible_is_not_backend_ready: true,
        backend_ready_is_not_semantic_validity: true,
        dlss_general_tensor_backend: false
      },
      ...over
    }
  };
}

async function openSettings(page: Page) {
  const response = await page.goto('/', { waitUntil: 'domcontentloaded' });
  expect(response).not.toBeNull();
  expect(await response!.text()).not.toMatch(NOT_BUILT);
  await expect(page.locator('.cockpit')).toBeVisible();
  await page.getByRole('button', { name: 'Einstellungen' }).click();
  await expect(page.locator('.settings.open')).toBeVisible();
  return page.locator('.settings.open');
}

test.describe('compute section', () => {
  test('a visible GPU is never reported as a working backend', async ({ page }) => {
    // The whole point of the accelerators module: a card in the machine and a
    // usable lane are different facts. This is the live state of this box.
    await page.route('**/api/accelerators/status*', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(shallow()) })
    );
    const panel = await openSettings(page);
    const compute = panel.locator('.compute');
    await expect(compute).toBeVisible();

    await expect(compute).toContainText('NVIDIA GeForce RTX 5080');
    // and yet:
    await expect(panel.locator('#compute-title ~ .settings-hint').first()).toContainText('0 von 2 Lanes einsatzbereit');
    await expect(compute).toContainText('Sichtbare Hardware bedeutet nicht, dass ein Backend bereit ist.');
  });

  test('an unprobed backend says it was not checked, not that it is missing', async ({ page }) => {
    // The failure this guards: six frameworks reported absent on a machine
    // where nothing was ever asked. `installed: false` here means "no probe".
    await page.route('**/api/accelerators/status*', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(shallow()) })
    );
    const panel = await openSettings(page);

    const torch = panel.locator('.compute-fw', { hasText: 'torch' });
    await expect(torch).toContainText('nicht geprüft');
    await expect(torch).not.toContainText('nicht installiert');
    // Not green, and not red either — nothing was measured.
    await expect(torch).toHaveClass(/\bwarn\b/);

    // And the section says out loud that this is the shallow answer.
    await expect(panel.locator('.compute-shallow')).toContainText('flache Antwort');
  });

  test('the deep probe is a button, and its result replaces the shallow one', async ({ page }) => {
    // Deep probing imports torch/cupy/warp. It costs seconds, so it may not
    // happen behind the reader's back on open.
    const seen: string[] = [];
    await page.route('**/api/accelerators/status*', (route) => {
      const url = route.request().url();
      seen.push(url);
      const deep = url.includes('deep=1');
      const body = deep
        ? shallow({
            frameworks: {
              torch: { installed: true, cuda_ready: true, detail: 'torch 2.6 + cu124', probed: true },
              cupy: { installed: false, cuda_ready: null, detail: 'not importable', probed: true }
            },
            lanes: [{
              id: 'tensor_inference', label: 'CUDA tensor inference', state: 'ready',
              applicable_to: ['embedding batches'], evidence: ['torch.cuda.is_available()'],
              missing: [], warning: ''
            }]
          })
        : shallow();
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    });

    const panel = await openSettings(page);
    await expect(panel.locator('.compute-shallow')).toBeVisible();
    // Nothing deep happened on open.
    expect(seen.filter((u) => u.includes('deep=1')), 'a deep probe ran without being asked for').toHaveLength(0);

    await panel.getByRole('button', { name: 'Tief prüfen' }).click();

    // Now the row is measured, and it is allowed to be green.
    const torch = panel.locator('.compute-fw', { hasText: 'torch' });
    await expect(torch).toContainText('CUDA-fähig');
    await expect(torch).toHaveClass(/\bok\b/);
    await expect(torch).toContainText('torch 2.6 + cu124');
    // cupy was really looked at this time, so absent is now an honest word.
    await expect(panel.locator('.compute-fw', { hasText: 'cupy' })).toContainText('nicht installiert');
    // The shallow label is gone because the answer is no longer shallow.
    await expect(panel.locator('.compute-shallow')).toHaveCount(0);
    // The lane is ready and shows the evidence that made it ready.
    await expect(panel.locator('.compute-lane')).toContainText('torch.cuda.is_available()');
  });

  test('a lane that is deliberately not a backend is not drawn as broken', async ({ page }) => {
    await page.route('**/api/accelerators/status*', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(shallow()) })
    );
    const panel = await openSettings(page);

    const dlss = panel.locator('.compute-lane', { hasText: 'DLSS' });
    await expect(dlss).toContainText('kein Daedalus-Backend');
    await expect(dlss, 'a deliberate non-goal is painted as a failure').not.toHaveClass(/\bbad\b/);
    // The semantic caveat rides along; without it "DLSS" in a compute list
    // reads as a capability this system has.
    await expect(dlss).toContainText('not an executable Daedalus backend');

    // The lane that really is missing IS red, so the distinction is visible.
    await expect(panel.locator('.compute-lane', { hasText: 'CUDA tensor inference' })).toHaveClass(/\bbad\b/);
  });

  test('a compute read that failed is never drawn as a machine without accelerators', async ({ page }) => {
    await page.route('**/api/accelerators/status*', (route) => route.abort('failed'));
    const panel = await openSettings(page);

    await expect(panel.locator('#compute-title ~ .settings-hint.bad')).toContainText(
      'Das ist nicht dasselbe wie „keine Beschleuniger“'
    );
    // No inventory is drawn at all, rather than an empty one.
    await expect(panel.locator('.compute')).toHaveCount(0);
  });

  test('the live backend answers the contract this section reads', async ({ page }) => {
    // No stub. If the real payload ever loses a field this section reads, the
    // section falls back to nothing and this goes red — which is the point of
    // having one unstubbed test.
    const response = await page.request.get(`${LIVE}/api/accelerators/status`);
    expect(response.ok(), 'the live accelerator endpoint did not answer').toBeTruthy();
    const body = await response.json();
    const snapshot = body.accelerators;
    expect(snapshot.schema).toBe('daedalus-accelerators/1');
    for (const key of ['hardware', 'frameworks', 'lanes', 'remote_compute', 'claims']) {
      expect(snapshot, `the live payload has no ${key}`).toHaveProperty(key);
    }
    for (const lane of snapshot.lanes) {
      expect(
        ['ready', 'unverified', 'configured', 'missing', 'unsupported'],
        `the backend emitted a lane state this interface has no word for: ${lane.state}`
      ).toContain(lane.state);
    }
    for (const [name, row] of Object.entries(snapshot.frameworks) as [string, Record<string, unknown>][]) {
      expect(typeof row.probed, `${name}.probed is not a boolean`).toBe('boolean');
      expect([true, false, null], `${name}.cuda_ready is not tri-state`).toContain(row.cuda_ready);
    }
  });
});
