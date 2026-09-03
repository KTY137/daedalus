import { expect, test, type Page } from '@playwright/test';
import { NOT_BUILT } from './_app';

/**
 * THE COMPUTE SECTION, in a browser.
 *
 * The reading rules are pinned without a browser in
 * `src/features/system/accelerators.spec.ts`, and that is where the standing
 * mutation guard lives: this suite drives the TRACKED `dist` bundle, so a
 * mutation to `src` does not reach it until `vite build` runs. A reviewer
 * proved that by mutating the source and watching all six of these stay green.
 * What is checked HERE is what a unit test cannot see — that the rendered
 * section used those rules, and that the honest caveats are on screen rather
 * than only in a comment.
 */

const LIVE = 'http://127.0.0.1:8765';

/** The shape the real server returns. `installed` is a live find_spec result
 *  even on this shallow answer — it is not a placeholder. */
function shallow(over: Record<string, unknown> = {}) {
  const fw = (installed: boolean) => ({
    installed, cuda_ready: null, detail: 'deep probe not requested', probed: false
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
      frameworks: { torch: fw(false), cupy: fw(true) },
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
      remote_rtx_ollama: { configured: false, available: false, endpoint: '', models: [], error: '', warning: '' },
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

function stub(page: Page, body: unknown = shallow()) {
  return page.route('**/api/accelerators/status*', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) })
  );
}

test.describe('compute section', () => {
  test('a visible GPU is never reported as a working backend', async ({ page }) => {
    // The whole point of the accelerators module: a card in the machine and a
    // usable lane are different facts.
    await stub(page);
    const panel = await openSettings(page);
    const compute = panel.locator('.compute');
    await expect(compute).toBeVisible();

    await expect(compute).toContainText('NVIDIA GeForce RTX 5080');
    // and yet:
    await expect(panel.locator('#compute-title ~ .settings-hint').first()).toContainText('0 von 2 Lanes einsatzbereit');
    await expect(compute).toContainText('Sichtbare Hardware bedeutet nicht, dass ein Backend bereit ist.');
  });

  test('the shallow answer distinguishes "found it" from "did not find it"', async ({ page }) => {
    /*
     * The shallow payload's `installed` is a live `importlib.util.find_spec`,
     * not a placeholder. An earlier version of this surface treated it as
     * meaningless and rendered BOTH rows as "nicht geprüft", discarding a real
     * measurement — and its comment asserted, wrongly, that the backend sets
     * `installed: false` on everything until a deep probe runs.
     */
    await stub(page);
    const panel = await openSettings(page);

    const cupy = panel.locator('.compute-fw', { hasText: 'cupy' });
    await expect(cupy).toContainText('importierbar, nicht ausgeführt');
    await expect(cupy, 'a module that was found is claimed as CUDA-capable').not.toContainText('CUDA-fähig');
    await expect(cupy).toHaveClass(/\bwarn\b/);

    const torch = panel.locator('.compute-fw', { hasText: 'torch' });
    await expect(torch).toContainText('nicht installiert');
    await expect(torch).toHaveClass(/\bbad\b/);

    // Said once for all rows, not repeated as a per-row "detail".
    await expect(panel.locator('.compute-shallow')).toContainText('nichts ausgeführt');
    await expect(panel.locator('.compute-fw-detail')).toHaveCount(0);
  });

  test('a probe that died is not drawn as six missing backends', async ({ page }) => {
    /*
     * When the probe subprocess times out or crashes, the backend still stamps
     * `probed: true` on all six rows with `installed: false` and an EMPTY
     * detail — because `_framework_rows` fills in defaults for names the probe
     * never reported. Read naively that is six confident red rows about six
     * modules nobody looked at.
     */
    await stub(page, shallow({
      frameworks: {
        torch: { installed: false, cuda_ready: null, detail: '', probed: true },
        cupy: { installed: false, cuda_ready: null, detail: '', probed: true }
      }
    }));
    const panel = await openSettings(page);

    const rows = panel.locator('.compute-fw');
    await expect(rows).toHaveCount(2);
    for (const name of ['torch', 'cupy']) {
      const row = panel.locator('.compute-fw', { hasText: name });
      await expect(row).toContainText('nicht geprüft');
      await expect(row, `${name} was reported missing by a probe that never ran`).not.toContainText('nicht installiert');
      await expect(row).not.toHaveClass(/\bbad\b/);
    }
  });

  test('a real probe result is drawn, and only a measured one goes green', async ({ page }) => {
    await stub(page, shallow({
      frameworks: {
        torch: { installed: true, cuda_ready: true, detail: '2.6.0 / cuda=12.4', probed: true },
        cuvs: { installed: true, cuda_ready: null, detail: '25.02 / import_only: no device kernel smoke', probed: true },
        cupy: { installed: false, cuda_ready: null, detail: "ModuleNotFoundError: No module named 'cupy'", probed: true }
      }
    }));
    const panel = await openSettings(page);

    const torch = panel.locator('.compute-fw', { hasText: 'torch' });
    await expect(torch).toContainText('CUDA-fähig');
    await expect(torch).toHaveClass(/\bok\b/);
    await expect(torch).toContainText('2.6.0 / cuda=12.4');

    // The probe deliberately leaves CUDA open for cuvs: "import success alone
    // must not claim CUDA readiness". So neither green nor absent.
    const cuvs = panel.locator('.compute-fw', { hasText: 'cuvs' });
    await expect(cuvs).toContainText('installiert, CUDA nicht geprüft');
    await expect(cuvs).not.toHaveClass(/\bok\b/);

    // This one WAS looked at, so "nicht installiert" is an honest word.
    const cupy = panel.locator('.compute-fw', { hasText: 'cupy' });
    await expect(cupy).toContainText('nicht installiert');
    await expect(cupy).toHaveClass(/\bbad\b/);
    await expect(cupy).toContainText('ModuleNotFoundError');
  });

  test('nothing on screen offers to run the effectful probe', async ({ page }) => {
    /*
     * `?deep=1` makes the server spawn a 30-second subprocess importing torch,
     * cupy and warp. `do_GET` carries no effect_boundary row, and read.py
     * refuses to expose the latent store on a GET for exactly that reason.
     * A dead route is not an entrypoint; a button is. So there is no button,
     * and no request this surface makes carries the flag.
     */
    const seen: string[] = [];
    await page.route('**/api/accelerators/status*', (route) => {
      seen.push(route.request().url());
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(shallow()) });
    });
    const panel = await openSettings(page);
    await expect(panel.locator('.compute')).toBeVisible();

    await expect(panel.getByRole('button', { name: /Tief prüfen/ })).toHaveCount(0);
    expect(seen.length, 'the section never called the route at all').toBeGreaterThan(0);
    expect(seen.filter((u) => u.includes('deep')), 'a request asked the server to spawn the probe').toEqual([]);
  });

  test('a lane that is deliberately not a backend is not drawn as broken', async ({ page }) => {
    await stub(page);
    const panel = await openSettings(page);

    const dlss = panel.locator('.compute-lane', { hasText: 'DLSS' });
    await expect(dlss).toContainText('kein Daedalus-Backend');
    await expect(dlss, 'a deliberate non-goal is painted as a failure').not.toHaveClass(/\bbad\b/);
    await expect(dlss).toContainText('not an executable Daedalus backend');

    // The lane that really is missing IS red, so the distinction is visible.
    await expect(panel.locator('.compute-lane', { hasText: 'CUDA tensor inference' })).toHaveClass(/\bbad\b/);
  });

  test('a card whose VRAM was not reported does not claim to have none', async ({ page }) => {
    // nvidia-smi answers `[N/A]` for some cards and the backend turns that
    // into null. `Math.round(null / 1024)` is 0 — "0 GiB".
    await stub(page, shallow({
      hardware: {
        available: true, command: 'nvidia-smi', error: '',
        devices: [{ name: 'RTX A2000', compute_capability: '8.6', memory_mib: null, driver_version: '610.47' }]
      }
    }));
    const panel = await openSettings(page);

    const device = panel.locator('.compute-devices li').first();
    await expect(device).toContainText('VRAM nicht gemeldet');
    await expect(device).not.toContainText('0 GiB');
  });

  test('a plaintext remote endpoint keeps its warning', async ({ page }) => {
    // The backend writes "remote endpoint uses plaintext HTTP; prefer a
    // private tunnel or TLS". A compute panel has no business swallowing it.
    await stub(page, shallow({
      remote_rtx_ollama: {
        configured: true, available: true, endpoint: 'http://bench:11434',
        models: ['qwen3:32b'], error: '',
        warning: 'remote endpoint uses plaintext HTTP; prefer a private tunnel or TLS'
      }
    }));
    const panel = await openSettings(page);

    const line = panel.locator('.compute').locator('..').getByText('plaintext HTTP');
    await expect(line).toBeVisible();
  });

  test('an unrecognised claim is shown rather than swallowed', async ({ page }) => {
    // The claims block exists to stop capability laundering. Dropping a claim
    // this interface has no sentence for is the wrong failure mode.
    await stub(page, shallow({
      claims: { hardware_visible_is_not_backend_ready: true, some_future_claim: false }
    }));
    const panel = await openSettings(page);

    await expect(panel.locator('.compute-claim-raw')).toContainText('some_future_claim');
    await expect(panel.locator('.compute-claim-raw')).toContainText('false');
  });

  test('an architectural blocker is not labelled as something to go install', async ({ page }) => {
    /*
     * `capability_lanes()` exists for this and says why in its docstring:
     * "'missing' invites someone to go install a library. 'impossible' tells
     * them to stop. Reporting the first when the second is true is how an
     * afternoon gets spent against the wrong silicon."
     *
     * The backend puts BOTH kinds of entry in the same `missing` list — the
     * installable one and the sentence ending "not installable, the silicon
     * does not have them". Labelling the whole list "fehlt" put the wrong verb
     * on the second and contradicted the text inside it.
     */
    await stub(page, shallow({
      lanes: [{
        id: 'tensor_inference', label: 'CUDA tensor inference', state: 'missing',
        applicable_to: ['embedding batches'], evidence: [],
        missing: [
          'tensor cores (this device is pre-Volta: NVIDIA MX330, compute capability 6.1) -- not installable, the silicon does not have them'
        ],
        warning: ''
      }]
    }));
    const panel = await openSettings(page);

    const lane = panel.locator('.compute-lane', { hasText: 'CUDA tensor inference' });
    // The backend's sentence survives intact and reads as its own statement.
    await expect(lane).toContainText('not installable, the silicon does not have them');
    // And the surface does not put "fehlt" in front of it.
    await expect(
      lane.locator('.compute-lane-missing-label'),
      'an uninstallable prerequisite is labelled as missing'
    ).not.toContainText('fehlt');
    await expect(lane.locator('.compute-lane-missing-label')).toContainText('Voraussetzungen');
  });

  test('each prerequisite is its own line, not a comma-joined run-on', async ({ page }) => {
    await stub(page, shallow({
      lanes: [{
        id: 'sparse_graph', label: 'CUDA sparse graph', state: 'missing',
        applicable_to: [], evidence: [],
        missing: ['NVIDIA CUDA device', 'CUDA-capable cuVS or cuGraph runtime'],
        warning: ''
      }]
    }));
    const panel = await openSettings(page);

    const items = panel.locator('.compute-lane-missing li');
    await expect(items).toHaveCount(2);
    await expect(items.nth(0)).toHaveText('NVIDIA CUDA device');
    await expect(items.nth(1)).toHaveText('CUDA-capable cuVS or cuGraph runtime');
  });

  test('a reachable bench reports what its silicon can host, not just that it answered', async ({ page }) => {
    /*
     * `_remote_compute_status` attaches `capability_lanes()` to every remote
     * device. Rendering only the word "erreichbar" threw away the answer to
     * "could this card host the lane at all" and left the bench GPU a rumour.
     */
    await stub(page, shallow({
      remote_compute: {
        configured: true, available: true, target: 'user@bench',
        devices: [{
          name: 'NVIDIA GeForce RTX 5080', compute_capability: '12.0',
          memory_mib: 16303, driver_version: '610.47',
          capability: {
            compute_capability: '12.0', known: true,
            supports: { tensor_cores: true, rt_cores: true },
            note: 'architecture supports rt_cores, tensor_cores'
          }
        }],
        lanes: { tensor_cores: true, rt_cores: true },
        error: '', hint: ''
      }
    }));
    const panel = await openSettings(page);

    const remote = panel.locator('.compute-remote');
    await expect(remote).toContainText('user@bench');
    await expect(remote).toContainText('erreichbar');
    await expect(remote).toContainText('NVIDIA GeForce RTX 5080');
    // The backend's verdict, verbatim and not recomputed in the browser.
    await expect(remote.locator('.compute-dev-capability')).toContainText('architecture supports rt_cores, tensor_cores');
  });

  test('a pre-Volta bench card says so rather than looking capable', async ({ page }) => {
    await stub(page, shallow({
      remote_compute: {
        configured: true, available: true, target: 'user@bench',
        devices: [{
          name: 'NVIDIA MX330', compute_capability: '6.1',
          memory_mib: 2048, driver_version: '560.94',
          capability: {
            compute_capability: '6.1', known: true,
            supports: { tensor_cores: false, rt_cores: false },
            note: 'pre-Volta: no tensor cores, no RT cores'
          }
        }],
        lanes: { tensor_cores: false, rt_cores: false },
        error: '', hint: ''
      }
    }));
    const panel = await openSettings(page);

    const remote = panel.locator('.compute-remote');
    await expect(remote).toContainText('erreichbar');
    // "Reachable" must not be allowed to read as "capable".
    await expect(remote.locator('.compute-dev-capability')).toContainText('pre-Volta: no tensor cores');
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
    // No stub. If the real payload loses a field this section reads, or emits
    // a lane state with no German word, this goes red.
    const response = await page.request.get(`${LIVE}/api/accelerators/status`);
    expect(response.ok(), 'the live accelerator endpoint did not answer').toBeTruthy();
    const snapshot = (await response.json()).accelerators;
    expect(snapshot.schema).toBe('daedalus-accelerators/1');
    for (const key of ['hardware', 'frameworks', 'lanes', 'remote_compute', 'remote_rtx_ollama', 'claims']) {
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
      expect(typeof row.installed, `${name}.installed is not a boolean`).toBe('boolean');
    }
    // The shallow answer really does carry a live find_spec result, which is
    // the premise the reading depends on.
    for (const row of Object.values(snapshot.frameworks) as Record<string, unknown>[]) {
      expect(row.probed, 'the unasked-for route ran a deep probe').toBe(false);
    }
  });
});
