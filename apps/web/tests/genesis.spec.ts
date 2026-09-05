import { expect, test, type Page } from '@playwright/test';
import { execFileSync } from 'node:child_process';

const PROMPT = 'Build a local task board with search';
const SHA256 = /^[a-f0-9]{64}$/;
const RUN_ID = 'genesis-0123456789abcdef01234567';
const ARTIFACT_KINDS = {
  autonomy_policy: 'autonomy policy',
  runtime_manifest: 'runtime manifest',
  build_intent: 'build intent',
  product_spec: 'product spec',
  policy_decision: 'policy decision',
  design_contract: 'design contract',
  target_fourfold: 'target fourfold',
  graph_proposal: 'graph proposal',
  mission: 'mission',
  materialization_plan: 'materialization plan',
  toolchain_manifest: 'toolchain manifest',
  attempt: 'attempt',
  evidence: 'evidence',
  run_record: 'run record',
  actual_fourfold: 'actual fourfold',
  roundtrip: 'roundtrip'
} as const;

function digest(index: number): string {
  return index.toString(16).padStart(64, '0');
}

const ARTIFACT_DIGESTS = Object.fromEntries(
  Object.keys(ARTIFACT_KINDS).map((key, index) => [key, digest(index + 1)])
) as Record<keyof typeof ARTIFACT_KINDS, string>;
const CANDIDATE_DIGEST = digest(32);

function artifact(kind: string, sha256: string) {
  return { kind, sha256, locator: `artifact-locator:sha256:${sha256}` };
}

function canonicalGreenRun(requestKey: string, origin: string): Record<string, unknown> {
  const artifacts = Object.fromEntries(
    Object.entries(ARTIFACT_KINDS).map(([key, kind]) => [
      key,
      artifact(kind, ARTIFACT_DIGESTS[key as keyof typeof ARTIFACT_KINDS])
    ])
  );
  return {
    run_id: RUN_ID,
    request_key: requestKey,
    status: 'preview-ready',
    target: 'web',
    defaults: {},
    blockers: [],
    mission: {
      mission_id: 'mission-0123456789abcdef01234567',
      objective: 'Build a local task board.',
      work_items: ['materialize'],
      success_criteria: ['build', 'test', 'runtime'],
      policy_sha256: ARTIFACT_DIGESTS.autonomy_policy
    },
    candidate: {
      ...artifact('candidate source tree', CANDIDATE_DIGEST),
      files: ['index.html', 'styles.css', 'app.js']
    },
    evidence: {
      ...artifact('evidence packet', ARTIFACT_DIGESTS.evidence),
      status: 'passed',
      candidate_tree_sha256: CANDIDATE_DIGEST,
      checks: ['build', 'test', 'runtime']
    },
    roundtrip: {
      ...artifact('round-trip report', ARTIFACT_DIGESTS.roundtrip),
      status: 'passed',
      checks: { build: true, code: true, data: true, knowledge: true, runtime: true, test: true, type: true },
      feature_assurance: { mechanism: 'kernel-owned certified-template conformance' }
    },
    preview: {
      kind: 'read-only-cas-preview',
      path: `/api/genesis/${RUN_ID}/preview/`,
      url: `${origin}/api/genesis/${RUN_ID}/preview/`
    },
    artifacts,
    publication: { status: 'not-requested', owner_approval_required: true, automatic_promotion: false }
  };
}

async function openDownloadFixture(page: Page, target = 'web') {
  await page.route('**/api/projects', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: null, warnings: [], projects: [] }
  }));
  await page.route('**/api/runtimes/status**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: null, warnings: [], runtimes: [] }
  }));
  await page.route('**/api/drafts**', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: null, warnings: [], scope: null, pending_count: 0, drafts: [] }
  }));
  await page.route('**/api/genesis/*/preview/**', (route) => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><title>Controlled preview</title><p>Preview</p>'
  }));
  await page.route('**/api/genesis', (route) => {
    const body = route.request().postDataJSON() as Record<string, unknown>;
    const run = canonicalGreenRun(String(body.request_key), new URL(route.request().url()).origin);
    run.target = target;
    if (target === 'cli') {
      run.status = 'succeeded';
      run.preview = null;
    }
    return route.fulfill({ json: { ok: true, genesis: run } });
  });
  await page.goto('/?view=genesis', { waitUntil: 'domcontentloaded' });
  await expect(page.locator('main.genesis')).toHaveJSProperty('scrollTop', 0);
  await page.locator('textarea[aria-describedby="genesis-prompt-help"]').fill(PROMPT);
  await page.getByRole('button', { name: 'Genesis starten' }).click();
  await expect(page.getByRole('button', { name: 'Quellcode herunterladen' })).toBeEnabled();
}

const EMPTY_ZIP = Buffer.from('504b0506000000000000000000000000000000000000', 'hex');
const SOURCE_HEADERS = {
  'Content-Type': 'application/zip',
  'Content-Disposition': 'attachment; filename="backend-source.zip"',
  'X-Daedalus-Candidate-Sha256': CANDIDATE_DIGEST
};

test.describe('Genesis', () => {
  test('downloads one exact-candidate archive across view changes and releases its object URL', async ({ page }) => {
    let calls = 0;
    let release!: () => void;
    const mayFinish = new Promise<void>((resolve) => { release = resolve; });
    await page.addInitScript(() => {
      const state = { created: [] as string[], revoked: [] as string[] };
      (window as unknown as { genesisUrls: typeof state }).genesisUrls = state;
      const create = URL.createObjectURL.bind(URL);
      const revoke = URL.revokeObjectURL.bind(URL);
      URL.createObjectURL = (blob) => { const url = create(blob); state.created.push(url); return url; };
      URL.revokeObjectURL = (url) => { state.revoked.push(url); revoke(url); };
    });
    await page.route('**/api/genesis/*/source.zip?**', async (route) => {
      calls += 1;
      const requestUrl = new URL(route.request().url());
      expect(requestUrl.pathname).toBe(`/api/genesis/${RUN_ID}/source.zip`);
      expect(requestUrl.search).toBe(`?candidate_sha256=${CANDIDATE_DIGEST}`);
      expect(route.request().method()).toBe('GET');
      await mayFinish;
      await route.fulfill({ status: 200, headers: SOURCE_HEADERS, body: EMPTY_ZIP });
    });
    await openDownloadFixture(page);
    await page.getByRole('button', { name: 'Quellcode herunterladen' }).evaluate((button) => {
      (button as HTMLButtonElement).click();
      (button as HTMLButtonElement).click();
    });
    await expect.poll(() => calls).toBe(1);
    await expect(page.getByRole('button', { name: 'Quellcode wird geladen …' })).toBeDisabled();
    await expect(page.locator('.genesis-source [role="status"]')).toContainText('geprüft und geladen');
    await page.getByRole('button', { name: 'Karte', exact: true }).click();
    await page.getByRole('button', { name: 'Genesis', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Quellcode wird geladen …' })).toBeDisabled();
    const downloadPromise = page.waitForEvent('download');
    release();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe(`${RUN_ID}-${CANDIDATE_DIGEST.slice(0, 12)}-source.zip`);
    expect(await download.failure()).toBeNull();
    await expect(page.locator('.genesis-source [role="status"]')).toContainText('Download an den Browser übergeben');
    await expect(page.getByRole('button', { name: 'Quellcode herunterladen' })).toBeEnabled();
    await expect.poll(() => page.evaluate(() => {
      const state = (window as unknown as { genesisUrls: { created: string[]; revoked: string[] } }).genesisUrls;
      return state.created.length === 1 && state.created[0] === state.revoked[0];
    })).toBe(true);
    await expect(page.locator('a[download]')).toHaveCount(0);
    expect(calls).toBe(1);
  });

  test('keeps archive errors visible and retries a verified CLI candidate without navigation', async ({ page }) => {
    let calls = 0;
    let downloads = 0;
    page.on('download', () => { downloads += 1; });
    await page.route('**/api/genesis/*/source.zip?**', async (route) => {
      calls += 1;
      if (calls === 1) {
        await route.fulfill({ status: 409, json: { ok: false, error: 'controlled archive refusal' } });
      } else {
        await route.fulfill({ status: 200, body: EMPTY_ZIP, headers: {
          ...SOURCE_HEADERS,
          'X-Daedalus-Candidate-Sha256': calls === 2 ? digest(33) : CANDIDATE_DIGEST
        } });
      }
    });
    await openDownloadFixture(page, 'cli');
    await expect(page.locator('iframe[title^="Genesis-Vorschau"]')).toHaveCount(0);
    const initialUrl = page.url();
    await page.getByRole('button', { name: 'Quellcode herunterladen' }).click();
    await expect(page.locator('.genesis-source [role="alert"]')).toContainText('HTTP 409');
    await page.getByRole('button', { name: 'Quellcode herunterladen' }).click();
    await expect(page.locator('.genesis-source [role="alert"]')).toContainText('anderen oder keinen Kandidaten');
    expect(downloads).toBe(0);
    expect(page.url()).toBe(initialUrl);
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Quellcode herunterladen' }).click();
    await downloadPromise;
    await expect(page.locator('.genesis-source [role="alert"]')).toHaveCount(0);
    await expect(page.locator('.genesis-source [role="status"]')).toContainText('Download an den Browser übergeben');
    expect(calls).toBe(3);
    expect(downloads).toBe(1);
    expect(page.url()).toBe(initialUrl);
  });

  test('builds one CAS-bound candidate, downloads verified sources and operates its opaque CRUD-search preview', async ({ page }, testInfo) => {
    test.skip(process.platform !== 'win32', 'Windows browser receipt; Linux OCI has a separate live matrix');
    test.setTimeout(300_000);

    const opened = await page.goto('/?view=genesis', { waitUntil: 'domcontentloaded' });
    expect(opened?.status()).toBe(200);
    await page.locator('textarea[aria-describedby="genesis-prompt-help"]').fill(PROMPT);

    const responsePromise = page.waitForResponse(
      (response) => response.url().endsWith('/api/genesis')
        && response.request().method() === 'POST',
      // Candidate materialization is intentionally an end-to-end operation.
      // The test already grants it five minutes overall; inheriting the
      // global 15-second action timeout made the response waiter fail early
      // while the server kept working, then starved unrelated following specs.
      { timeout: 240_000 }
    );
    await page.getByRole('button', { name: 'Genesis starten' }).click();
    const response = await responsePromise;
    expect(response.status()).toBe(200);
    const envelope = await response.json();
    const run = envelope.genesis;

    expect(envelope.ok).toBe(true);
    expect(run.status).toBe('preview-ready');
    expect(run.candidate.sha256).toMatch(SHA256);
    expect(run.evidence.candidate_tree_sha256).toBe(run.candidate.sha256);
    expect(run.roundtrip.status).toBe('passed');
    expect(run.roundtrip.checks).toMatchObject({
      build: true,
      certified_template_conformance: true,
      containment: true,
      package: true,
      runtime: true,
      test: true
    });

    const downloadPromise = page.waitForEvent('download');
    const archiveResponsePromise = page.waitForResponse((item) => item.url().includes(`/api/genesis/${run.run_id}/source.zip?`));
    await page.getByRole('button', { name: 'Quellcode herunterladen' }).click();
    const downloaded = await downloadPromise;
    const archiveResponse = await archiveResponsePromise;
    expect(archiveResponse.status()).toBe(200);
    expect(archiveResponse.headers()['x-daedalus-candidate-sha256']).toBe(run.candidate.sha256);
    expect(archiveResponse.headers()['content-type']).toBe('application/zip');
    expect(archiveResponse.headers()['content-disposition']).toMatch(/^attachment;/);
    const archivePath = await downloaded.path();
    expect(archivePath).not.toBeNull();
    // Independent stdlib verifier reads the saved download, without importing
    // Daedalus or trusting the exporter to assert its own source identities.
    const verified = JSON.parse(execFileSync('python', ['-c', `
import hashlib, json, stat, sys, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    manifest_bytes = archive.read('source-tree.json')
    assert hashlib.sha256(manifest_bytes).hexdigest() == sys.argv[2]
    manifest = json.loads(manifest_bytes)
    report = json.loads(archive.read('genesis-run.json'))
    assert report['run_id'] == sys.argv[3]
    assert report['candidate']['sha256'] == sys.argv[2]
    expected = ['genesis-run.json', 'source-tree.json'] + ['source/' + e['path'] for e in manifest['entries']]
    assert archive.namelist() == sorted(expected)
    for entry in manifest['entries']:
        name = 'source/' + entry['path']
        payload = archive.read(name)
        info = archive.getinfo(name)
        assert len(payload) == entry['size']
        assert hashlib.sha256(payload).hexdigest() == entry['blob_sha256']
        mode = info.external_attr >> 16
        assert stat.S_ISREG(mode)
        assert bool(mode & 0o111) == entry['executable']
    assert 'source/README.md' in expected
    print(json.dumps({'files': len(manifest['entries']), 'candidate_sha256': sys.argv[2]}))
`, archivePath!, run.candidate.sha256, run.run_id], { encoding: 'utf8', windowsHide: true }));
    expect(verified.files).toBe(run.candidate.files.length);
    await testInfo.attach('verified-genesis-source.zip', { path: archivePath!, contentType: 'application/zip' });
    await testInfo.attach('genesis-source-download.png', {
      body: await page.locator('.genesis-source').screenshot(), contentType: 'image/png'
    });

    const previewResponse = await page.request.get(run.preview.url, {
      headers: { 'Sec-Fetch-Site': 'same-origin' }
    });
    expect(previewResponse.status()).toBe(200);
    const csp = previewResponse.headers()['content-security-policy'] || '';
    const previewOrigin = new URL(run.preview.url).origin;
    const scriptDirective = csp.split(';').map((value) => value.trim()).find((value) => value.startsWith('script-src '));
    const previewAssetRoot = scriptDirective?.slice('script-src '.length) || '';
    expect(csp).toContain("default-src 'none'");
    // The preview's opaque iframe loads only this candidate's capability-bound
    // asset directory. Requiring an origin-wide source would weaken the check.
    expect(previewAssetRoot.startsWith(`${previewOrigin}/api/genesis/${run.run_id}/preview/~cap-`)).toBe(true);
    expect(previewAssetRoot.split('/').at(-2)).toMatch(/^~cap-[a-f0-9]{64}$/);
    expect(previewAssetRoot.endsWith('/')).toBe(true);
    expect(csp).toContain(`style-src ${previewAssetRoot};`);
    expect(csp).toContain(`img-src ${previewAssetRoot} data:;`);
    expect(csp).not.toContain("script-src 'self'");
    expect(csp).not.toContain("style-src 'self'");
    expect(csp).toContain("form-action 'none'");
    expect(csp).toContain("frame-ancestors 'self'");
    expect(csp).toContain('sandbox allow-scripts allow-forms');

    const iframe = page.locator('iframe[title^="Genesis-Vorschau"]');
    await expect(iframe).toHaveAttribute('sandbox', 'allow-scripts allow-forms');
    expect((await iframe.getAttribute('sandbox')) || '').not.toContain('allow-same-origin');
    const preview = page.frameLocator('iframe[title^="Genesis-Vorschau"]');
    await expect(preview.locator('#count')).toHaveText('0 items');
    expect(await preview.locator('body').evaluate(() => self.origin)).toBe('null');
    expect(await preview.locator('body').evaluate(() => {
      try {
        localStorage.getItem('genesis-browser-probe');
        return 'available';
      } catch (error) {
        return error instanceof DOMException ? error.name : 'blocked';
      }
    })).toBe('SecurityError');

    await preview.locator('#title').fill('Alpha');
    await preview.locator('#details').fill('First detail');
    await preview.getByRole('button', { name: 'Add item' }).click();
    await expect(preview.locator('#count')).toHaveText('1 item');

    await preview.locator('#title').fill('Probe');
    await preview.locator('#details').fill('Search Needle');
    await preview.locator('#title').press('Enter');
    await expect(preview.locator('#count')).toHaveText('2 items');

    await preview.locator('#filter').fill('needle');
    await expect(preview.locator('#count')).toHaveText('1 of 2 items');
    await expect(preview.locator('#items > li')).toHaveCount(1);
    await expect(preview.locator('#items')).toContainText('Probe');
    await preview.locator('#filter').fill('');

    await preview.getByRole('checkbox', { name: 'Mark Alpha complete' }).check();
    await expect(preview.locator('#items > li.done')).toHaveCount(1);
    await preview.locator('#items > li').filter({ hasText: 'Alpha' })
      .getByRole('button', { name: 'Edit' }).click();
    await preview.locator('#title').fill('Alpha revised');
    await preview.getByRole('button', { name: 'Save changes' }).click();
    await expect(preview.locator('#items')).toContainText('Alpha revised');
    await preview.locator('#items > li').filter({ hasText: 'Probe' })
      .getByRole('button', { name: 'Delete' }).click();
    await expect(preview.locator('#items > li')).toHaveCount(1);

    const attemptedFormTargets: string[] = [];
    page.on('request', (request) => {
      if (request.url().includes('genesis-form-egress.invalid')) {
        attemptedFormTargets.push(request.url());
      }
    });
    const previewFrame = page.frames().find((frame) => frame.url() === previewAssetRoot);
    expect(previewFrame).toBeDefined();
    await preview.locator('body').evaluate(() => {
      const form = document.createElement('form');
      form.action = 'https://genesis-form-egress.invalid/submit';
      form.method = 'post';
      document.body.append(form);
      form.submit();
    });
    await page.waitForTimeout(250);
    expect(attemptedFormTargets).toEqual([]);
    expect(previewFrame!.url()).toBe(previewAssetRoot);

    const direct = await page.context().newPage();
    try {
      const directResponse = await direct.goto(run.preview.url, { waitUntil: 'domcontentloaded' });
      expect(directResponse?.status()).toBe(200);
      await expect(direct.locator('#count')).toHaveText('0 items');
      expect(await direct.evaluate(() => self.origin)).toBe('null');
      expect(await direct.evaluate(() => {
        try {
          localStorage.getItem('genesis-direct-browser-probe');
          return 'available';
        } catch (error) {
          return error instanceof DOMException ? error.name : 'blocked';
        }
      })).toBe('SecurityError');
      await direct.locator('#title').fill('Direct preview item');
      await direct.locator('#title').press('Enter');
      await expect(direct.locator('#count')).toHaveText('1 item');
      await expect(direct.locator('#status')).toContainText(
        'Preview sandbox keeps changes until reload.'
      );
    } finally {
      await direct.close();
    }
  });

  test('claims a submit synchronously and keeps that one request across view changes', async ({ page }) => {
    let calls = 0;
    let release!: () => void;
    const mayFinish = new Promise<void>((resolve) => { release = resolve; });
    await page.route('**/api/projects', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: null, warnings: [], projects: [] }
    }));
    await page.route('**/api/runtimes/status**', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: null, warnings: [], runtimes: [] }
    }));
    await page.route('**/api/drafts**', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: null, warnings: [], scope: null, pending_count: 0, drafts: [] }
    }));
    await page.route('**/api/genesis', async (route) => {
      calls += 1;
      await mayFinish;
      await route.fulfill({ status: 500, json: { ok: false, error: 'controlled genesis failure' } });
    });

    const opened = await page.goto('/?view=genesis', { waitUntil: 'domcontentloaded' });
    expect(opened?.status()).toBe(200);
    await page.locator('textarea[aria-describedby="genesis-prompt-help"]').fill(PROMPT);
    await page.locator('.genesis-intake form').evaluate((form) => {
      const target = form as HTMLFormElement;
      target.requestSubmit();
      target.requestSubmit();
    });
    await expect.poll(() => calls).toBe(1);

    await page.getByRole('button', { name: 'Karte', exact: true }).click();
    await expect(page.locator('main.genesis')).toBeHidden();
    await page.getByRole('button', { name: 'Genesis', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Genesis arbeitet …' })).toBeDisabled();
    expect(calls).toBe(1);

    release();
    await expect(page.locator('.genesis-error')).toContainText('controlled genesis failure');
    expect(calls).toBe(1);
  });

  test('rejects foreign, incomplete, or failed-preview runs and accepts the complete canonical chain without sticking', async ({ page }) => {
    const requestKeys: string[] = [];
    await page.route('**/api/projects', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: null, warnings: [], projects: [] }
    }));
    await page.route('**/api/runtimes/status**', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: null, warnings: [], runtimes: [] }
    }));
    await page.route('**/api/drafts**', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: null, warnings: [], scope: null, pending_count: 0, drafts: [] }
    }));
    await page.route('**/api/genesis', async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      const requestKey = String(body.request_key);
      requestKeys.push(requestKey);
      const run = canonicalGreenRun(requestKey, new URL(route.request().url()).origin);
      if (requestKeys.length === 1) run.request_key = `${requestKey}:foreign`;
      if (requestKeys.length === 2) {
        const artifacts = run.artifacts as Record<string, unknown>;
        run.artifacts = { evidence: artifacts.evidence, roundtrip: artifacts.roundtrip };
      }
      if (requestKeys.length === 3) run.status = 'failed';
      await route.fulfill({
        json: {
          ok: true,
          generated_at: '',
          project: null,
          warnings: [],
          genesis: run
        }
      });
    });

    await page.goto('/?view=genesis', { waitUntil: 'domcontentloaded' });
    await page.locator('textarea[aria-describedby="genesis-prompt-help"]').fill(PROMPT);
    await page.getByRole('button', { name: 'Genesis starten' }).click();
    await expect(page.locator('.genesis-error')).toContainText('Genesis-Lauf gemeldet.');
    await expect(page.locator('.genesis-result')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Genesis starten' })).toBeEnabled();

    await page.getByRole('button', { name: 'Genesis starten' }).click();
    await expect.poll(() => requestKeys.length).toBe(2);
    expect(requestKeys[1]).toBe(requestKeys[0]);
    await expect(page.locator('.genesis-error')).toContainText('Genesis-Lauf gemeldet.');
    await expect(page.locator('.genesis-result')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Genesis starten' })).toBeEnabled();

    await page.getByRole('button', { name: 'Genesis starten' }).click();
    await expect.poll(() => requestKeys.length).toBe(3);
    expect(requestKeys[2]).toBe(requestKeys[0]);
    await expect(page.locator('.genesis-error')).toContainText('Genesis-Lauf gemeldet.');
    await expect(page.locator('.genesis-result')).toHaveCount(0);
    await expect(page.locator('iframe[title^="Genesis-Vorschau"]')).toHaveCount(0);
    await expect(page.getByRole('button', { name: 'Genesis starten' })).toBeEnabled();

    await page.getByRole('button', { name: 'Genesis starten' }).click();
    await expect.poll(() => requestKeys.length).toBe(4);
    expect(requestKeys[3]).toBe(requestKeys[0]);
    await expect(page.locator('.genesis-error')).toHaveCount(0);
    await expect(page.locator('.genesis-result')).toBeVisible();
    await expect(page.locator('.genesis-status[data-tone="ok"]')).toContainText('preview-ready');
    await expect(page.locator('.genesis-artifacts li')).toHaveCount(17);
  });
});
