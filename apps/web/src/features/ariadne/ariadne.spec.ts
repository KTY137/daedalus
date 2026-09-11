import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import {
  startAriadne,
  type AriadneCampaignReceipt,
  type AriadneTrial
} from '@/shared/api';
import { AriadneReceiptView, AriadneWorkbench } from './Ariadne';
import {
  ARIADNE_TEXT_MAX_CHARACTERS,
  ariadneArmRows,
  ariadneDigestRows,
  ariadneIdentityFor,
  ariadneRequestFor,
  isAriadneCampaignReceipt,
  type AriadneFormValues
} from './model';

export interface AriadneSpecResult {
  name: string;
  ok: boolean;
  detail: string;
}

const SHA = {
  campaign: 'a'.repeat(64),
  experiment: 'b'.repeat(64),
  candidate: 'c'.repeat(64),
  evidence: 'd'.repeat(64),
  nomination: 'e'.repeat(64),
  budget: 'f'.repeat(64)
};
const REVISION = '1'.repeat(40);
const CAMPAIGN_ID = 'ariadne-fixture';

function locator(digest: string): string {
  return `artifact-locator:sha256:${digest}`;
}

function usage(wallTime = 1) {
  return {
    input_tokens: 0,
    output_tokens: 0,
    cost_microusd: 0,
    wall_time_ms: wallTime,
    est_input_tokens: 0
  };
}

function trial(
  variant: 'baseline' | 'negative-control' | 'repair',
  seed: number,
  status: 'passed' | 'failed',
  candidate: string,
  evidence: string
): AriadneTrial {
  return {
    campaign_id: CAMPAIGN_ID,
    seed,
    replay_role: 'origin',
    stage: 'complete',
    status,
    base_source_tree_sha256: '9'.repeat(64),
    base_source_tree_locator: locator('9'.repeat(64)),
    mission_sha256: null,
    mission_locator: null,
    attempt_ids: [`${CAMPAIGN_ID}-${variant}`],
    attempt_contract_sha256s: ['7'.repeat(64)],
    attempt_contract_locators: [locator('7'.repeat(64))],
    attempt_receipt_sha256s: ['8'.repeat(64)],
    attempt_receipt_locators: [locator('8'.repeat(64))],
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
    usage: usage(seed + 1),
    negative_outcomes: status === 'failed' ? ['frozen-evaluator-rejected'] : [],
    blockers: status === 'failed' ? ['exact-match-failed'] : [],
    started_at: `2026-09-05T10:00:0${seed}+00:00`,
    finished_at: `2026-09-05T10:00:1${seed}+00:00`,
    variant_id: variant,
    arm_role: variant === 'baseline' ? 'baseline' : 'candidate',
    configured_budget_sha256: SHA.budget,
    receipt_profile: 'controlled-repair-v1'
  };
}

function fixture(overrides: Partial<AriadneCampaignReceipt> = {}): AriadneCampaignReceipt {
  const baseline = trial('baseline', 0, 'failed', '2'.repeat(64), '3'.repeat(64));
  const negative = trial('negative-control', 1, 'failed', '4'.repeat(64), '5'.repeat(64));
  const repair = trial('repair', 2, 'passed', SHA.candidate, SHA.evidence);
  return {
    contract_type: 'daedalus.campaign-receipt',
    contract_version: '1.0.0',
    campaign_id: CAMPAIGN_ID,
    source_revision: REVISION,
    campaign_contract_sha256: SHA.campaign,
    campaign_contract_locator: locator(SHA.campaign),
    experiment_spec_sha256: SHA.experiment,
    experiment_spec_locator: locator(SHA.experiment),
    metric_names: ['exact_match'],
    trials: [baseline, negative, repair],
    execution_order: [0, 1, 2],
    outcome: 'nominated',
    selected_seed: 2,
    candidate_tree_sha256: SHA.candidate,
    candidate_tree_locator: locator(SHA.candidate),
    nomination_receipt_sha256: SHA.nomination,
    nomination_receipt_locator: locator(SHA.nomination),
    usage: usage(6),
    overhead_usage: usage(0),
    negative_outcomes: [
      'baseline:frozen-evaluator-rejected',
      'negative-control:frozen-evaluator-rejected'
    ],
    reproducibility_note: 'Frozen exact repair fixture.',
    blockers: [],
    started_at: '2026-09-05T10:00:00+00:00',
    finished_at: '2026-09-05T10:01:00+00:00',
    provenance: {
      origin: 'ariadne.controlled-repair.receipt',
      source_revision: REVISION,
      created_at: '2026-09-05T10:01:00+00:00',
      input_digests: []
    },
    selection_mode: 'best-passed-trial',
    selected_variant_id: 'repair',
    budget_equality: {
      configured_budget_sha256: SHA.budget,
      trial_keys: ['baseline:0', 'negative-control:1', 'repair:2'],
      trial_budget_sha256s: [SHA.budget, SHA.budget, SHA.budget],
      realized_usage_sha256s: ['6'.repeat(64), '7'.repeat(64), '8'.repeat(64)],
      configured_equal: true,
      realized_usage_recorded: true,
      within_budget: true
    },
    ...overrides
  };
}

export async function runAriadneSpec(): Promise<AriadneSpecResult[]> {
  const results: AriadneSpecResult[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });
  const values: AriadneFormValues = {
    project: '  atlas  ',
    sourceRevision: ` ${REVISION} `,
    targetPath: ' src/example.py ',
    before: ' exact\nold ',
    after: ' exact\nnew '
  };

  const identity = ariadneIdentityFor(values, undefined, () => '01234567-89ab-cdef-0123-456789abcdef');
  const sameIdentity = ariadneIdentityFor(values, identity, () => 'must-not-be-used');
  const changedIdentity = ariadneIdentityFor(
    { ...values, after: 'different' },
    identity,
    () => 'fedcba98-7654-3210-fedc-ba9876543210'
  );
  check(
    'Ariadne keeps one campaign id for an ambiguous retry and changes it only with repair inputs',
    identity === sameIdentity
      && identity.campaignId === 'ariadne-0123456789abcdef0123456789abcdef'
      && changedIdentity.campaignId !== identity.campaignId,
    `${identity.campaignId} -> ${changedIdentity.campaignId}`
  );

  const request = ariadneRequestFor(values, identity.campaignId);
  check(
    'Ariadne sends exactly six canonical fields while preserving exact repair fragments',
    JSON.stringify(Object.keys(request)) === JSON.stringify([
      'project', 'source_revision', 'campaign_id', 'target_path', 'before', 'after'
    ])
      && request.project === 'atlas'
      && request.source_revision === REVISION
      && request.target_path === 'src/example.py'
      && request.before === values.before
      && request.after === values.after,
    JSON.stringify(request)
  );
  for (const [name, invalid] of [
    ['missing project', { ...values, project: '' }],
    ['unbound revision', { ...values, sourceRevision: 'main' }],
    ['missing target', { ...values, targetPath: '' }],
    ['empty old text', { ...values, before: '' }],
    ['unchanged text', { ...values, after: values.before }]
  ] as Array<[string, AriadneFormValues]>) {
    let refused = false;
    try {
      ariadneRequestFor(invalid, identity.campaignId);
    } catch {
      refused = true;
    }
    check(`${name} is refused before the Ariadne API call`, refused);
  }
  for (const [name, invalid] of [
    [
      'oversized character count',
      { ...values, before: 'x'.repeat(ARIADNE_TEXT_MAX_CHARACTERS + 1) }
    ],
    [
      'oversized UTF-8 request body',
      { ...values, before: '🙂'.repeat(20_000) }
    ]
  ] as Array<[string, AriadneFormValues]>) {
    let refused = false;
    try {
      ariadneRequestFor(invalid, identity.campaignId);
    } catch {
      refused = true;
    }
    check(`${name} is refused before transport`, refused);
  }

  const receipt = fixture();
  check('the complete canonical CampaignReceipt shape is accepted', isAriadneCampaignReceipt(receipt));
  check(
    'partial or cross-campaign receipts cannot be painted as Ariadne evidence',
    !isAriadneCampaignReceipt({ campaign_id: CAMPAIGN_ID, trials: [] })
      && !isAriadneCampaignReceipt(fixture({
        trials: [{ ...receipt.trials[0], campaign_id: 'foreign-campaign' }, ...receipt.trials.slice(1)]
      })),
    'validator must bind every trial to the receipt campaign'
  );
  check(
    'duplicate trial identities are rejected instead of hiding one outcome',
    !isAriadneCampaignReceipt(fixture({ trials: [receipt.trials[0], receipt.trials[0]] }))
  );
  check(
    'a nominated receipt must bind the complete selected repair and equal-budget evidence',
    !isAriadneCampaignReceipt(fixture({
      trials: [],
      execution_order: [],
      selected_seed: null,
      selected_variant_id: null,
      candidate_tree_sha256: null,
      candidate_tree_locator: null,
      nomination_receipt_sha256: null,
      nomination_receipt_locator: null,
      budget_equality: null
    }))
      && !isAriadneCampaignReceipt(fixture({
        trials: [
          receipt.trials[0],
          receipt.trials[1],
          { ...receipt.trials[2], status: 'mystery' }
        ]
      }))
      && !isAriadneCampaignReceipt(fixture({
        candidate_tree_sha256: '0'.repeat(64),
        candidate_tree_locator: locator('0'.repeat(64))
      }))
      && !isAriadneCampaignReceipt(fixture({
        budget_equality: { ...receipt.budget_equality!, configured_equal: false }
      }))
  );

  const arms = ariadneArmRows(receipt);
  check(
    'baseline, negative control and repair keep their frozen visual order',
    arms.map((arm) => arm.id).join(',') === 'baseline,negative-control,repair'
      && arms.every((arm) => arm.trial?.variant_id === arm.id)
  );
  const partialArms = ariadneArmRows(fixture({ trials: receipt.trials.slice(0, 1) }));
  check(
    'a stopped campaign shows unexecuted arms rather than inventing outcomes',
    Boolean(partialArms[0].trial) && !partialArms[1].trial && !partialArms[2].trial
  );
  const digests = ariadneDigestRows(receipt);
  check(
    'candidate, selected evidence and nomination expose their full canonical digests',
    digests.map((row) => row.digest).join(',') === [SHA.candidate, SHA.evidence, SHA.nomination].join(',')
  );

  const intakeHtml = renderToStaticMarkup(createElement(AriadneWorkbench, {
    project: 'atlas', sourceRevision: REVISION
  }));
  check(
    'the intake exposes only the exact repair subject and no evaluator or promotion controls',
    intakeHtml.includes('Relative Zieldatei')
      && intakeHtml.includes('Bisheriger Text')
      && intakeHtml.includes('Neuer Text')
      && intakeHtml.includes('Evaluator, Kommando, Laufzeitgrenze und Promotion')
      && !/<(?:input|textarea|select)[^>]*(?:repo_root|model|evaluator|command|timeout|promotion)/i.test(intakeHtml),
    intakeHtml.slice(0, 600)
  );
  const hiddenHtml = renderToStaticMarkup(createElement(AriadneWorkbench, {
    project: 'atlas', sourceRevision: REVISION, hidden: true
  }));
  check(
    'Ariadne stays mounted across view changes but leaves the accessibility tree',
    /<main[^>]*\shidden=""[^>]*\sinert=""/i.test(hiddenHtml)
      || /<main[^>]*\sinert=""[^>]*\shidden=""/i.test(hiddenHtml),
    hiddenHtml.slice(0, 220)
  );

  const resultHtml = renderToStaticMarkup(createElement(AriadneReceiptView, { receipt }));
  check(
    'the receipt renders all three arms and retains their negative outcomes',
    (resultHtml.match(/class="ariadne-arm"/g) || []).length === 3
      && resultHtml.includes('data-arm="baseline"')
      && resultHtml.includes('data-arm="negative-control"')
      && resultHtml.includes('data-arm="repair"')
      && resultHtml.includes('frozen-evaluator-rejected'),
    resultHtml.slice(0, 700)
  );
  check(
    'the receipt displays candidate, evidence and nomination digests without shortening',
    [SHA.candidate, SHA.evidence, SHA.nomination].every((digest) => resultHtml.includes(digest))
  );
  check(
    'nomination has no apply, merge or promotion action',
    resultHtml.includes('Nominiert, nicht übernommen')
      && !/<(?:button|a)[^>]*>[^<]*(?:apply|merge|promotion|promote|übernehmen)/i.test(resultHtml)
  );
  check(
    'only the compact campaign status is an aria-live region',
    !/<section class="ariadne-result"[^>]*aria-live/i.test(resultHtml)
      && /class="ariadne-status"[^>]*role="status"[^>]*aria-live="polite"/i.test(resultHtml)
  );

  const globals = globalThis as unknown as Record<string, unknown>;
  const originalWindow = globals.window;
  const originalFetch = globals.fetch;
  let requestedUrl = '';
  let requestedInit: RequestInit | undefined;
  try {
    globals.window = globalThis;
    globals.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      requestedUrl = String(input);
      requestedInit = init;
      return {
        ok: true,
        status: 200,
        json: async () => ({ ok: true, project: 'atlas', generated_at: '', warnings: [], ariadne: receipt })
      } as Response;
    }) as typeof fetch;
    const response = await startAriadne(request);
    check(
      'shared API posts the exact Ariadne body to /api/ariadne',
      requestedUrl === '/api/ariadne'
        && requestedInit?.method === 'POST'
        && JSON.stringify(JSON.parse(String(requestedInit?.body))) === JSON.stringify(request)
        && response.ariadne.campaign_id === CAMPAIGN_ID,
      `${requestedUrl} ${requestedInit?.method || ''} ${String(requestedInit?.body)}`
    );
  } finally {
    if (originalWindow === undefined) delete globals.window;
    else globals.window = originalWindow;
    if (originalFetch === undefined) delete globals.fetch;
    else globals.fetch = originalFetch;
  }

  return results;
}
