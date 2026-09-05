import type {
  AriadneCampaignReceipt,
  AriadneRequest,
  AriadneTrial
} from '@/shared/api';

export interface AriadneFormValues {
  project: string;
  sourceRevision: string;
  targetPath: string;
  before: string;
  after: string;
}

export interface AriadneRequestIdentity {
  signature: string;
  campaignId: string;
}

export interface AriadneArmRow {
  id: 'baseline' | 'negative-control' | 'repair';
  label: string;
  purpose: string;
  trial?: AriadneTrial;
}

export interface AriadneDigestRow {
  id: string;
  label: string;
  digest: string;
  locator: string;
}

const SHA256_RE = /^[a-f0-9]{64}$/;
const REVISION_RE = /^[a-f0-9]{40}$/;
const CAMPAIGN_ID_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const IDENTIFIER_RE = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$/;
const TRIAL_STAGES = new Set(['admitted', 'mission', 'attempts', 'candidate', 'evidence', 'complete']);
const TRIAL_STATUSES = new Set(['passed', 'failed', 'cancelled', 'inconclusive', 'error']);
const USAGE_KEYS = ['input_tokens', 'output_tokens', 'cost_microusd', 'wall_time_ms', 'est_input_tokens'] as const;
const CONTROLLED_ARMS = ['baseline', 'negative-control', 'repair'] as const;
export const ARIADNE_HTTP_BODY_MAX_BYTES = 64 * 1024;
export const ARIADNE_TEXT_MAX_CHARACTERS = 30_000;
const ARM_ORDER: AriadneArmRow[] = [
  {
    id: 'baseline',
    label: 'Baseline',
    purpose: 'Unveränderte Ausgangsdatei gegen denselben eingefrorenen Evaluator.'
  },
  {
    id: 'negative-control',
    label: 'Negativkontrolle',
    purpose: 'Absichtlich falsche Änderung; ihr Scheitern bleibt als Evidenz erhalten.'
  },
  {
    id: 'repair',
    label: 'Reparatur',
    purpose: 'Exakt ein Vorkommen wird im isolierten Kandidaten ersetzt.'
  }
];

function recordOf(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string' && item.length > 0);
}

function isNullableSha256(value: unknown): value is string | null {
  return value === null || (typeof value === 'string' && SHA256_RE.test(value));
}

function isNullableLocator(value: unknown): value is string | null {
  return value === null || (
    typeof value === 'string'
    && /^artifact-locator:sha256:[a-f0-9]{64}$/.test(value)
  );
}

function locatorMatches(digest: unknown, locator: unknown): boolean {
  return typeof digest === 'string'
    && SHA256_RE.test(digest)
    && locator === `artifact-locator:sha256:${digest}`;
}

function nullableDigestLocatorPair(digest: unknown, locator: unknown): boolean {
  return (digest === null && locator === null) || locatorMatches(digest, locator);
}

function digestLocatorArraysMatch(digests: unknown, locators: unknown): boolean {
  return Array.isArray(digests)
    && Array.isArray(locators)
    && digests.length === locators.length
    && digests.every((digest, index) => locatorMatches(digest, locators[index]));
}

function isUsage(value: unknown): boolean {
  const usage = recordOf(value);
  return Boolean(usage)
    && Object.keys(usage!).length === USAGE_KEYS.length
    && USAGE_KEYS.every(
      (key) => Number.isSafeInteger(usage![key]) && (usage![key] as number) >= 0
    );
}

function isMetrics(value: unknown): value is Record<string, number> {
  const metrics = recordOf(value);
  return Boolean(metrics) && Object.values(metrics!).every(
    (item) => typeof item === 'number' && Number.isFinite(item)
  );
}

function isTrial(value: unknown, campaignId: string): value is AriadneTrial {
  const trial = recordOf(value);
  if (!trial) return false;
  const status = typeof trial.status === 'string' ? trial.status : '';
  const passed = status === 'passed';
  const attempts = trial.attempt_ids;
  return trial.campaign_id === campaignId
    && Number.isSafeInteger(trial.seed)
    && (trial.seed as number) >= 0
    && (trial.replay_role === 'origin' || trial.replay_role === 'replay')
    && typeof trial.stage === 'string' && TRIAL_STAGES.has(trial.stage)
    && TRIAL_STATUSES.has(status)
    && typeof trial.variant_id === 'string' && IDENTIFIER_RE.test(trial.variant_id)
    && (trial.arm_role === 'baseline' || trial.arm_role === 'candidate')
    && trial.receipt_profile === 'controlled-repair-v1'
    && typeof trial.configured_budget_sha256 === 'string'
    && SHA256_RE.test(trial.configured_budget_sha256)
    && locatorMatches(trial.base_source_tree_sha256, trial.base_source_tree_locator)
    && nullableDigestLocatorPair(trial.mission_sha256, trial.mission_locator)
    && nullableDigestLocatorPair(trial.gate1_receipt_sha256, trial.gate1_receipt_locator)
    && Array.isArray(attempts)
    && attempts.every((attempt) => typeof attempt === 'string' && IDENTIFIER_RE.test(attempt))
    && new Set(attempts).size === attempts.length
    && digestLocatorArraysMatch(trial.attempt_contract_sha256s, trial.attempt_contract_locators)
    && (trial.attempt_contract_sha256s as unknown[]).length === attempts.length
    && digestLocatorArraysMatch(trial.attempt_receipt_sha256s, trial.attempt_receipt_locators)
    && (trial.attempt_receipt_sha256s as unknown[]).length === attempts.length
    && nullableDigestLocatorPair(trial.candidate_tree_sha256, trial.candidate_tree_locator)
    && nullableDigestLocatorPair(trial.evidence_packet_sha256, trial.evidence_packet_locator)
    && nullableDigestLocatorPair(trial.candidate_snapshot_sha256, trial.candidate_snapshot_locator)
    && isNullableSha256(trial.candidate_source_bundle_sha256)
    && isNullableSha256(trial.graph_delta_sha256)
    && isMetrics(trial.metrics)
    && (!passed || Object.keys(trial.metrics as Record<string, number>).length > 0)
    && isUsage(trial.usage)
    && isStringArray(trial.negative_outcomes)
    && isStringArray(trial.blockers)
    && typeof trial.started_at === 'string' && trial.started_at.length > 0
    && typeof trial.finished_at === 'string' && trial.finished_at.length > 0
    && (
      passed
        ? trial.stage === 'complete'
          && attempts.length > 0
          && trial.candidate_tree_sha256 !== null
          && trial.evidence_packet_sha256 !== null
          && trial.blockers.length === 0
        : trial.blockers.length > 0
    );
}

/** The signature contains only the six owner-visible repair inputs. Exact
 * before/after bytes are deliberately not trimmed. */
export function ariadneRequestSignature(values: AriadneFormValues): string {
  return JSON.stringify({
    project: values.project.trim(),
    source_revision: values.sourceRevision.trim(),
    target_path: values.targetPath.trim(),
    before: values.before,
    after: values.after
  });
}

export function createAriadneCampaignId(uuid?: () => string): string {
  const raw = uuid
    ? uuid()
    : typeof globalThis.crypto?.randomUUID === 'function'
      ? globalThis.crypto.randomUUID()
      : '';
  const token = raw.replace(/[^A-Za-z0-9]/g, '').slice(0, 48);
  if (!token) throw new Error('Dieser Browser kann keine sichere Kampagnen-ID erzeugen.');
  return `ariadne-${token}`;
}

/** Reuse the exact id for an ambiguous retry; mint a sibling only when one of
 * the repair inputs really changed. */
export function ariadneIdentityFor(
  values: AriadneFormValues,
  current?: AriadneRequestIdentity,
  uuid?: () => string
): AriadneRequestIdentity {
  const signature = ariadneRequestSignature(values);
  if (current?.signature === signature && CAMPAIGN_ID_RE.test(current.campaignId)) return current;
  return { signature, campaignId: createAriadneCampaignId(uuid) };
}

export function ariadneRequestFor(
  values: AriadneFormValues,
  campaignId: string
): AriadneRequest {
  const project = values.project.trim();
  const sourceRevision = values.sourceRevision.trim();
  const targetPath = values.targetPath.trim();
  const id = campaignId.trim();
  if (!project) throw new Error('Wähle zuerst ein registriertes Projekt.');
  if (!REVISION_RE.test(sourceRevision)) {
    throw new Error('Der aktuelle Git-HEAD ist nicht als exakte 40-stellige Revision bestätigt.');
  }
  if (!CAMPAIGN_ID_RE.test(id)) throw new Error('Die Kampagnen-ID ist ungültig.');
  if (!targetPath) throw new Error('Nenne eine relative Zieldatei.');
  if (!values.before) throw new Error('Der bisherige Text darf nicht leer sein.');
  if (values.before === values.after) throw new Error('Bisheriger und neuer Text müssen verschieden sein.');
  if (
    values.before.length > ARIADNE_TEXT_MAX_CHARACTERS
    || values.after.length > ARIADNE_TEXT_MAX_CHARACTERS
  ) {
    throw new Error(`Ein Reparaturtext darf höchstens ${ARIADNE_TEXT_MAX_CHARACTERS} Zeichen enthalten.`);
  }
  const request = {
    project,
    source_revision: sourceRevision,
    campaign_id: id,
    target_path: targetPath,
    before: values.before,
    after: values.after
  };
  const bodyBytes = new TextEncoder().encode(JSON.stringify(request)).byteLength;
  if (bodyBytes > ARIADNE_HTTP_BODY_MAX_BYTES) {
    throw new Error(
      `Die Ariadne-Anfrage umfasst ${bodyBytes} UTF-8-Bytes; erlaubt sind höchstens ${ARIADNE_HTTP_BODY_MAX_BYTES}.`
    );
  }
  return request;
}

export function isAriadneCampaignReceipt(value: unknown): value is AriadneCampaignReceipt {
  const receipt = recordOf(value);
  if (!receipt) return false;
  const campaignId = typeof receipt.campaign_id === 'string' ? receipt.campaign_id : '';
  const trials = receipt.trials;
  const outcome = receipt.outcome;
  const selectedSeed = receipt.selected_seed;
  const selectedVariant = receipt.selected_variant_id;
  const budget = receipt.budget_equality;
  const provenance = recordOf(receipt.provenance);
  if (
    receipt.contract_type !== 'daedalus.campaign-receipt'
    || receipt.contract_version !== '1.0.0'
    || !CAMPAIGN_ID_RE.test(campaignId)
    || typeof receipt.source_revision !== 'string'
    || !REVISION_RE.test(receipt.source_revision)
    || !locatorMatches(receipt.campaign_contract_sha256, receipt.campaign_contract_locator)
    || !locatorMatches(receipt.experiment_spec_sha256, receipt.experiment_spec_locator)
    || !isStringArray(receipt.metric_names)
    || receipt.metric_names.length === 0
    || !Array.isArray(trials)
    || !trials.every((trial) => isTrial(trial, campaignId))
    || !Array.isArray(receipt.execution_order)
    || !['nominated', 'rejected', 'failed', 'cancelled'].includes(String(outcome))
    || !(selectedSeed === null || (Number.isSafeInteger(selectedSeed) && (selectedSeed as number) >= 0))
    || !(selectedVariant === null || (typeof selectedVariant === 'string' && IDENTIFIER_RE.test(selectedVariant)))
    || !nullableDigestLocatorPair(receipt.candidate_tree_sha256, receipt.candidate_tree_locator)
    || !nullableDigestLocatorPair(receipt.nomination_receipt_sha256, receipt.nomination_receipt_locator)
    || !isUsage(receipt.usage)
    || !isUsage(receipt.overhead_usage)
    || !isStringArray(receipt.negative_outcomes)
    || !isStringArray(receipt.blockers)
    || typeof receipt.reproducibility_note !== 'string'
    || receipt.reproducibility_note.length === 0
    || typeof receipt.started_at !== 'string'
    || receipt.started_at.length === 0
    || typeof receipt.finished_at !== 'string'
    || receipt.finished_at.length === 0
    || receipt.selection_mode !== 'best-passed-trial'
    || !provenance
    || provenance.source_revision !== receipt.source_revision
    || provenance.created_at !== receipt.finished_at
  ) return false;

  const typedTrials = trials as AriadneTrial[];
  const metricNames = receipt.metric_names as string[];
  if (
    typedTrials.length > CONTROLLED_ARMS.length
    || new Set(typedTrials.map((trial) => `${trial.variant_id}:${trial.seed}`)).size !== typedTrials.length
    || typedTrials.some((trial, index) => (
      trial.variant_id !== CONTROLLED_ARMS[index]
      || trial.seed !== index
      || trial.arm_role !== (index === 0 ? 'baseline' : 'candidate')
    ))
    || receipt.execution_order.length !== typedTrials.length
    || receipt.execution_order.some((seed, index) => seed !== typedTrials[index].seed)
    || typedTrials.some((trial) => (
      trial.status === 'passed'
      && JSON.stringify(Object.keys(trial.metrics).sort())
        !== JSON.stringify([...metricNames].sort())
    ))
    || USAGE_KEYS.some((key) => (
      (receipt.usage as Record<string, number>)[key]
      !== typedTrials.reduce(
        (total, trial) => total + ((trial.usage as Record<string, number>)[key] || 0),
        0
      )
    ))
  ) return false;

  const budgetRecord = recordOf(budget);
  const expectedKeys = typedTrials.map((trial) => `${trial.variant_id}:${trial.seed}`);
  const budgetValid = Boolean(budgetRecord)
    && typeof budgetRecord!.configured_budget_sha256 === 'string'
    && SHA256_RE.test(budgetRecord!.configured_budget_sha256 as string)
    && Array.isArray(budgetRecord!.trial_keys)
    && JSON.stringify(budgetRecord!.trial_keys) === JSON.stringify(expectedKeys)
    && Array.isArray(budgetRecord!.trial_budget_sha256s)
    && budgetRecord!.trial_budget_sha256s.length === typedTrials.length
    && budgetRecord!.trial_budget_sha256s.every(
      (digest, index) => digest === typedTrials[index].configured_budget_sha256
        && digest === budgetRecord!.configured_budget_sha256
    )
    && Array.isArray(budgetRecord!.realized_usage_sha256s)
    && budgetRecord!.realized_usage_sha256s.length === typedTrials.length
    && budgetRecord!.realized_usage_sha256s.every(
      (digest) => typeof digest === 'string' && SHA256_RE.test(digest)
    )
    && budgetRecord!.configured_equal === true
    && budgetRecord!.realized_usage_recorded === true
    && budgetRecord!.within_budget === true;

  if (outcome === 'nominated') {
    const repair = typedTrials[2];
    return typedTrials.length === CONTROLLED_ARMS.length
      && typedTrials[0].status === 'failed'
      && typedTrials[1].status === 'failed'
      && repair.status === 'passed'
      && selectedSeed === repair.seed
      && selectedVariant === repair.variant_id
      && receipt.blockers.length === 0
      && receipt.candidate_tree_sha256 === repair.candidate_tree_sha256
      && receipt.candidate_tree_locator === repair.candidate_tree_locator
      && receipt.nomination_receipt_sha256 !== null
      && receipt.nomination_receipt_locator !== null
      && budgetValid;
  }
  return selectedSeed === null
    && selectedVariant === null
    && receipt.nomination_receipt_sha256 === null
    && receipt.nomination_receipt_locator === null
    && receipt.blockers.length > 0
    && (budget === null || budgetValid);
}

export function ariadneArmRows(receipt?: AriadneCampaignReceipt): AriadneArmRow[] {
  const trials = receipt?.trials || [];
  return ARM_ORDER.map((arm) => ({
    ...arm,
    trial: trials.find((trial) => trial.variant_id === arm.id)
  }));
}

export function ariadneStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    passed: 'bestanden',
    failed: 'fehlgeschlagen',
    error: 'Fehler mit Evidenz',
    cancelled: 'abgebrochen',
    inconclusive: 'nicht eindeutig',
    nominated: 'nominiert',
    rejected: 'abgelehnt'
  };
  return labels[status] || status || 'nicht ausgeführt';
}

export function ariadneStatusTone(status: string): 'ok' | 'bad' | 'warn' | 'muted' {
  if (status === 'passed' || status === 'nominated') return 'ok';
  if (status === 'failed' || status === 'error' || status === 'rejected') return 'bad';
  if (status === 'cancelled' || status === 'inconclusive') return 'warn';
  return 'muted';
}

export function selectedAriadneTrial(receipt: AriadneCampaignReceipt): AriadneTrial | undefined {
  return receipt.trials.find(
    (trial) => trial.variant_id === receipt.selected_variant_id && trial.seed === receipt.selected_seed
  );
}

export function ariadneDigestRows(receipt: AriadneCampaignReceipt): AriadneDigestRow[] {
  const selected = selectedAriadneTrial(receipt);
  return [
    {
      id: 'candidate',
      label: 'Kandidatenbaum',
      digest: receipt.candidate_tree_sha256 || '',
      locator: receipt.candidate_tree_locator || ''
    },
    {
      id: 'evidence',
      label: 'Evidenzpaket',
      digest: selected?.evidence_packet_sha256 || '',
      locator: selected?.evidence_packet_locator || ''
    },
    {
      id: 'nomination',
      label: 'Nominierung',
      digest: receipt.nomination_receipt_sha256 || '',
      locator: receipt.nomination_receipt_locator || ''
    }
  ];
}
