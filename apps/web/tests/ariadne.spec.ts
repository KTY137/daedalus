import { expect, test, type Page } from '@playwright/test';

const REVISION = '1'.repeat(40);
const SHA256 = /^[a-f0-9]{64}$/;

function locator(digest: string): string {
  return `artifact-locator:sha256:${digest}`;
}

function trial(campaignId: string, variant: string, seed: number, status: 'passed' | 'failed') {
  const candidate = String(seed + 2).repeat(64);
  const evidence = String(seed + 5).repeat(64);
  return {
    campaign_id: campaignId,
    seed,
    replay_role: 'origin',
    stage: 'complete',
    status,
    base_source_tree_sha256: '9'.repeat(64),
    base_source_tree_locator: locator('9'.repeat(64)),
    mission_sha256: null,
    mission_locator: null,
    attempt_ids: [`${campaignId}-${variant}`],
    attempt_contract_sha256s: ['a'.repeat(64)],
    attempt_contract_locators: [locator('a'.repeat(64))],
    attempt_receipt_sha256s: ['b'.repeat(64)],
    attempt_receipt_locators: [locator('b'.repeat(64))],
    gate1_receipt_sha256: null,
    gate1_receipt_locator: null,
    candidate_tree_sha256: candidate,
    candidate_tree_locator: locator(candidate),
    candidate_source_bundle_sha256: null,
    candidate_snapshot_sha256: null,
    candidate_snapshot_locator: null,
    graph_delta_sha256: null,
    evidence_packet_sha256: evidence,
    evidence_packet_locator: locator(evidence),
    metrics: { exact_match: status === 'passed' ? 1 : 0 },
    usage: { input_tokens: 0, output_tokens: 0, cost_microusd: 0, wall_time_ms: seed + 1, est_input_tokens: 0 },
    negative_outcomes: status === 'failed' ? ['frozen-evaluator-rejected'] : [],
    blockers: status === 'failed' ? ['exact-match-failed'] : [],
    started_at: `2026-09-05T10:00:0${seed}+00:00`,
    finished_at: `2026-09-05T10:00:1${seed}+00:00`,
    variant_id: variant,
    arm_role: variant === 'baseline' ? 'baseline' : 'candidate',
    configured_budget_sha256: 'f'.repeat(64),
    receipt_profile: 'controlled-repair-v1'
  };
}

function receipt(campaignId: string, sourceRevision = REVISION) {
  const trials = [
    trial(campaignId, 'baseline', 0, 'failed'),
    trial(campaignId, 'negative-control', 1, 'failed'),
    trial(campaignId, 'repair', 2, 'passed')
  ];
  const selected = trials[2];
  return {
    contract_type: 'daedalus.campaign-receipt',
    contract_version: '1.0.0',
    campaign_id: campaignId,
    source_revision: sourceRevision,
    campaign_contract_sha256: 'c'.repeat(64),
    campaign_contract_locator: locator('c'.repeat(64)),
    experiment_spec_sha256: 'd'.repeat(64),
    experiment_spec_locator: locator('d'.repeat(64)),
    metric_names: ['exact_match'],
    trials,
    execution_order: [0, 1, 2],
    outcome: 'nominated',
    selected_seed: 2,
    candidate_tree_sha256: selected.candidate_tree_sha256,
    candidate_tree_locator: selected.candidate_tree_locator,
    nomination_receipt_sha256: 'e'.repeat(64),
    nomination_receipt_locator: locator('e'.repeat(64)),
    usage: { input_tokens: 0, output_tokens: 0, cost_microusd: 0, wall_time_ms: 6, est_input_tokens: 0 },
    overhead_usage: { input_tokens: 0, output_tokens: 0, cost_microusd: 0, wall_time_ms: 0, est_input_tokens: 0 },
    negative_outcomes: ['baseline:frozen-evaluator-rejected', 'negative-control:frozen-evaluator-rejected'],
    reproducibility_note: 'Frozen browser fixture.',
    blockers: [],
    started_at: '2026-09-05T10:00:00+00:00',
    finished_at: '2026-09-05T10:01:00+00:00',
    provenance: { origin: 'ariadne.controlled-repair.receipt', source_revision: sourceRevision, created_at: '2026-09-05T10:01:00+00:00', input_digests: [] },
    selection_mode: 'best-passed-trial',
    selected_variant_id: 'repair',
    budget_equality: {
      configured_budget_sha256: 'f'.repeat(64),
      trial_keys: ['baseline:0', 'negative-control:1', 'repair:2'],
      trial_budget_sha256s: ['f'.repeat(64), 'f'.repeat(64), 'f'.repeat(64)],
      realized_usage_sha256s: ['6'.repeat(64), '7'.repeat(64), '8'.repeat(64)],
      configured_equal: true,
      realized_usage_recorded: true,
      within_budget: true
    }
  };
}

async function stubProject(page: Page): Promise<void> {
  const project = { name: 'atlas', repo_root: 'C:\\work\\atlas', team: {}, reachable: true };
  await page.route('**/api/projects', (route) => route.fulfill({
    json: { ok: true, generated_at: '', project: project.name, warnings: [], projects: [project] }
  }));
  await page.route('**/api/structure**', (route) => route.fulfill({
    json: {
      ok: true,
      generated_at: '',
      project: project.name,
      warnings: [],
      structure: { repo_root: project.repo_root, graph: { nodes: [], edges: [] } }
    }
  }));
  await page.route('**/api/governance**', (route) => route.fulfill({
    json: {
      ok: true,
      generated_at: '',
      project: project.name,
      warnings: [],
      promotion_allowed: false,
      verdict: 'nomination only',
      state: 'blocked',
      head: REVISION,
      gates: [],
      blockers: []
    }
  }));
}

async function fillRepair(page: Page): Promise<void> {
  await page.getByLabel('Relative Zieldatei').fill('src/example.py');
  await page.getByLabel('Bisheriger Text').fill('old value');
  await page.getByLabel('Neuer Text').fill('new value');
}

test.describe('Ariadne Campaign Workbench', () => {
  test('posts only the exact repair contract and renders retained evidence without a promotion action', async ({ page }) => {
    await stubProject(page);
    let body: Record<string, unknown> = {};
    await page.route('**/api/ariadne', async (route) => {
      body = route.request().postDataJSON() as Record<string, unknown>;
      await route.fulfill({
        json: { ok: true, generated_at: '', project: 'atlas', warnings: [], ariadne: receipt(String(body.campaign_id)) }
      });
    });

    const opened = await page.goto('/?view=ariadne', { waitUntil: 'domcontentloaded' });
    expect(opened?.status()).toBe(200);
    await expect(page.getByText(REVISION, { exact: true })).toBeVisible();
    await fillRepair(page);
    await page.getByRole('button', { name: 'Kampagne starten' }).click();

    await expect(page.locator('.ariadne-result')).toBeVisible();
    expect(Object.keys(body)).toEqual([
      'project', 'source_revision', 'campaign_id', 'target_path', 'before', 'after'
    ]);
    expect(body).toMatchObject({
      project: 'atlas',
      source_revision: REVISION,
      target_path: 'src/example.py',
      before: 'old value',
      after: 'new value'
    });
    expect(String(body.campaign_id)).toMatch(/^ariadne-[A-Za-z0-9]+$/);

    await expect(page.locator('.ariadne-arm')).toHaveCount(3);
    await expect(page.locator('[data-arm="baseline"]')).toContainText('frozen-evaluator-rejected');
    await expect(page.locator('[data-arm="negative-control"]')).toContainText('frozen-evaluator-rejected');
    await expect(page.locator('[data-arm="repair"]')).toContainText('bestanden');
    const shownDigests = await page.locator('.ariadne-evidence code:not(.missing)').allInnerTexts();
    expect(shownDigests.every((value) => SHA256.test(value))).toBe(true);
    expect(shownDigests).toContain('4'.repeat(64));
    expect(shownDigests).toContain('7'.repeat(64));
    expect(shownDigests).toContain('e'.repeat(64));
    await expect(page.getByText('Nominiert, nicht übernommen.')).toBeVisible();
    await expect(
      page.locator('main.ariadne').getByRole('button', { name: /apply|merge|promotion|promote|übernehmen/i })
    ).toHaveCount(0);
  });

  test('claims one submit and reuses its campaign id after a failed transport while surviving view changes', async ({ page }) => {
    await stubProject(page);
    const ids: string[] = [];
    let release!: () => void;
    const firstMayFinish = new Promise<void>((resolve) => { release = resolve; });
    await page.route('**/api/ariadne', async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      ids.push(String(body.campaign_id));
      if (ids.length === 1) {
        await firstMayFinish;
        await route.fulfill({ status: 504, json: { ok: false, error: 'controlled ambiguous timeout' } });
        return;
      }
      await route.fulfill({
        json: { ok: true, generated_at: '', project: 'atlas', warnings: [], ariadne: receipt(String(body.campaign_id)) }
      });
    });

    await page.goto('/?view=ariadne', { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(REVISION, { exact: true })).toBeVisible();
    await fillRepair(page);
    await page.locator('.ariadne-intake form').evaluate((form) => {
      const target = form as HTMLFormElement;
      target.requestSubmit();
      target.requestSubmit();
    });
    await expect.poll(() => ids.length).toBe(1);

    await page.getByRole('button', { name: 'Karte', exact: true }).click();
    await expect(page.locator('main.ariadne')).toBeHidden();
    await page.getByRole('button', { name: 'Ariadne', exact: true }).click();
    await expect(page.getByRole('button', { name: 'Kampagne läuft …' })).toBeDisabled();
    expect(ids).toHaveLength(1);

    release();
    await expect(page.locator('.ariadne-error')).toContainText('controlled ambiguous timeout');
    await page.getByRole('button', { name: 'Kampagne starten' }).click();
    await expect(page.locator('.ariadne-result')).toBeVisible();
    expect(ids).toHaveLength(2);
    expect(ids[1]).toBe(ids[0]);
  });

  test('binds pending claims and late receipts to the exact project and HEAD', async ({ page }) => {
    const alpha = { name: 'ariadne-alpha', repo_root: 'C:\\work\\ariadne-alpha', team: {}, reachable: true };
    const beta = { name: 'ariadne-beta', repo_root: 'C:\\work\\ariadne-beta', team: {}, reachable: true };
    const betaRevision = '2'.repeat(40);
    const bodies: Array<Record<string, unknown>> = [];
    let releaseAlpha!: () => void;
    let releaseBetaRetry!: () => void;
    const alphaMayFinish = new Promise<void>((resolve) => { releaseAlpha = resolve; });
    const betaRetryMayFinish = new Promise<void>((resolve) => { releaseBetaRetry = resolve; });

    await page.route('**/api/projects', (route) => route.fulfill({
      json: { ok: true, generated_at: '', project: alpha.name, warnings: [], projects: [alpha, beta] }
    }));
    await page.route('**/api/structure**', (route) => {
      const selected = new URL(route.request().url()).searchParams.get('project') || alpha.name;
      const row = selected === beta.name ? beta : alpha;
      return route.fulfill({
        json: {
          ok: true,
          generated_at: '',
          project: row.name,
          warnings: [],
          structure: { repo_root: row.repo_root, graph: { nodes: [], edges: [] } }
        }
      });
    });
    await page.route('**/api/governance**', (route) => {
      const selected = new URL(route.request().url()).searchParams.get('project') || alpha.name;
      const head = selected === beta.name ? betaRevision : REVISION;
      return route.fulfill({
        json: {
          ok: true,
          generated_at: '',
          project: selected,
          warnings: [],
          promotion_allowed: false,
          verdict: 'nomination only',
          state: 'blocked',
          head,
          gates: [],
          blockers: []
        }
      });
    });
    await page.route('**/api/ariadne', async (route) => {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      bodies.push(body);
      if (body.project === alpha.name) await alphaMayFinish;
      if (
        body.project === beta.name
        && bodies.filter((request) => request.project === beta.name).length === 2
      ) await betaRetryMayFinish;
      await route.fulfill({
        json: {
          ok: true,
          generated_at: '',
          project: body.project,
          warnings: [],
          ariadne: receipt(String(body.campaign_id), String(body.source_revision))
        }
      });
    });

    await page.goto(`/?view=ariadne&project=${alpha.name}`, { waitUntil: 'domcontentloaded' });
    await expect(page.getByText(REVISION, { exact: true })).toBeVisible();
    await fillRepair(page);
    await page.getByRole('button', { name: 'Kampagne starten' }).click();
    await expect.poll(() => bodies.length).toBe(1);
    const alphaCampaign = String(bodies[0].campaign_id);

    await page.locator('.scope-trigger').click();
    await page.locator(`.scope-menu [data-project-name="${beta.name}"]`).click();
    await expect(page.getByText(betaRevision, { exact: true })).toBeVisible();
    await expect(page.locator('.ariadne-waiting')).toHaveCount(0);
    await fillRepair(page);
    await page.getByRole('button', { name: 'Kampagne starten' }).click();
    await expect.poll(() => bodies.length).toBe(2);
    expect(bodies[1]).toMatchObject({ project: beta.name, source_revision: betaRevision });
    const betaCampaign = String(bodies[1].campaign_id);
    expect(betaCampaign).not.toBe(alphaCampaign);
    await expect(page.locator('.ariadne-result')).toContainText(betaCampaign);

    releaseAlpha();
    await page.waitForTimeout(100);
    await expect(page.locator('.ariadne-result')).toContainText(betaCampaign);
    await expect(page.locator('.ariadne-result')).not.toContainText(alphaCampaign);
    await expect(page.locator('.ariadne-error')).toHaveCount(0);

    await page.getByLabel('Neuer Text').fill('new beta value held in flight');
    await page.getByRole('button', { name: 'Kampagne starten' }).click();
    await expect.poll(() => bodies.length).toBe(3);
    await page.locator('.scope-trigger').click();
    await page.locator(`.scope-menu [data-project-name="${alpha.name}"]`).click();
    await expect(page.getByText(REVISION, { exact: true })).toBeVisible();
    await expect(page.locator('.ariadne-waiting')).toHaveCount(0);

    releaseBetaRetry();
    await page.waitForTimeout(100);
    await page.locator('.scope-trigger').click();
    await page.locator(`.scope-menu [data-project-name="${beta.name}"]`).click();
    await expect(page.getByText(betaRevision, { exact: true })).toBeVisible();
    await expect(page.locator('.ariadne-waiting')).toHaveCount(0);
    await expect(page.locator('.ariadne-result')).toHaveCount(0);
    await fillRepair(page);
    await expect(page.getByRole('button', { name: 'Kampagne starten' })).toBeEnabled();
  });
});
