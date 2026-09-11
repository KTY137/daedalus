import type { GenesisRequest, GenesisRun } from '@/shared/api';

export interface GenesisFactRow {
  label: string;
  value: string;
}

export interface GenesisArtifactRow {
  key: string;
  label: string;
  digest: string;
  reference: string;
}

function recordOf(value: unknown): Record<string, unknown> | undefined {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function textOf(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

export function humanGenesisKey(key: string): string {
  const known: Record<string, string> = {
    base_repository: 'Basis-Repository',
    product_class: 'Produktklasse',
    target: 'Ziel',
    stack: 'Stack',
    language: 'Sprache',
    audience: 'Zielgruppe',
    telemetry: 'Telemetrie',
    authentication: 'Anmeldung',
    accessibility: 'Barrierefreiheit'
  };
  if (known[key]) return known[key];
  const words = key.replace(/[_-]+/g, ' ').trim();
  return words ? `${words.charAt(0).toUpperCase()}${words.slice(1)}` : 'Wert';
}

export function displayGenesisValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'nicht gemeldet';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return 'nicht darstellbar';
  }
}

export function genesisFactRows(value: unknown, fallbackLabel = 'Wert'): GenesisFactRow[] {
  const record = recordOf(value);
  if (record) {
    return Object.entries(record).map(([key, item]) => ({
      label: humanGenesisKey(key),
      value: key === 'base_repository' && item === null
        ? 'kein Repository'
        : displayGenesisValue(item)
    }));
  }
  if (Array.isArray(value)) {
    return value.map((item, index) => ({
      label: `${fallbackLabel} ${index + 1}`,
      value: displayGenesisValue(item)
    }));
  }
  return value === null || value === undefined
    ? []
    : [{ label: fallbackLabel, value: displayGenesisValue(value) }];
}

function blockerMessage(value: unknown): string {
  if (typeof value === 'string') return value.trim();
  const record = recordOf(value);
  if (!record) return displayGenesisValue(value);
  const message = textOf(record.message) || textOf(record.reason) || textOf(record.detail);
  const code = textOf(record.code) || textOf(record.kind);
  if (message && code) return `${code}: ${message}`;
  return message || code || displayGenesisValue(record);
}

export function genesisBlockers(value: unknown): string[] {
  if (value === null || value === undefined) return [];
  if (Array.isArray(value)) return value.map(blockerMessage).filter(Boolean);
  const record = recordOf(value);
  if (!record) {
    const one = blockerMessage(value);
    return one ? [one] : [];
  }
  if (record.message || record.reason || record.detail || record.code || record.kind) {
    const one = blockerMessage(record);
    return one ? [one] : [];
  }
  return Object.entries(record)
    .map(([key, item]) => `${humanGenesisKey(key)}: ${blockerMessage(item)}`)
    .filter((item) => !item.endsWith(': '));
}

const DIGEST_KEYS = [
  'sha256',
  'digest',
  'content_digest',
  'artifact_digest',
  'tree_digest',
  'candidate_digest',
  'evidence_digest',
  'roundtrip_digest',
  'content_hash'
];
const REFERENCE_KEYS = ['artifact_id', 'candidate_id', 'evidence_id', 'report_id', 'ref', 'uri', 'locator', 'path', 'id'];
const SHA256_LIKE_RE = /^(?:sha256:)?[a-f0-9]{32,}$/i;
const GENESIS_RUN_ID_RE = /^genesis-[a-f0-9]{24}$/;
const MISSION_ID_RE = /^mission-[a-f0-9]{24}$/;
const SHA256_RE = /^[a-f0-9]{64}$/;
const GENESIS_STATUSES = new Set(['running', 'blocked', 'failed', 'preview-ready', 'succeeded']);
const REQUIRED_ROUNDTRIP_CHECKS = ['build', 'code', 'data', 'knowledge', 'runtime', 'test', 'type'];
const GREEN_ARTIFACT_KINDS = {
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
const GREEN_ARTIFACT_KEYS = Object.keys(GREEN_ARTIFACT_KINDS) as Array<keyof typeof GREEN_ARTIFACT_KINDS>;

function hasExactKeys(record: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(record).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length
    && actual.every((key, index) => key === expected[index]);
}

function hasCanonicalArtifactIdentity(value: unknown, kind: string): value is Record<string, unknown> {
  const artifact = recordOf(value);
  const digest = artifact?.sha256;
  return Boolean(artifact)
    && artifact!.kind === kind
    && typeof digest === 'string'
    && SHA256_RE.test(digest)
    && artifact!.locator === `artifact-locator:sha256:${digest}`;
}

function hasExactCanonicalArtifactIdentity(value: unknown, kind: string): value is Record<string, unknown> {
  const artifact = recordOf(value);
  const digest = artifact?.sha256;
  return Boolean(artifact)
    && hasExactKeys(artifact!, ['kind', 'sha256', 'locator'])
    && artifact!.kind === kind
    && typeof digest === 'string'
    && SHA256_RE.test(digest)
    && artifact!.locator === `artifact-locator:sha256:${digest}`;
}

function isStringList(
  value: unknown,
  { allowEmpty = true }: { allowEmpty?: boolean } = {}
): value is string[] {
  return Array.isArray(value)
    && (allowEmpty || value.length > 0)
    && value.every((item) => typeof item === 'string' && item.length > 0);
}

function hasGreenGenesisChain(run: Record<string, unknown>, status: string): boolean {
  const candidate = recordOf(run.candidate);
  const evidence = recordOf(run.evidence);
  const roundtrip = recordOf(run.roundtrip);
  const checks = recordOf(roundtrip?.checks);
  const mission = recordOf(run.mission);
  const artifacts = recordOf(run.artifacts);
  const publication = recordOf(run.publication);
  const preview = recordOf(run.preview);
  if (
    !hasCanonicalArtifactIdentity(candidate, 'candidate source tree')
    || !hasExactKeys(candidate!, ['kind', 'sha256', 'locator', 'files'])
    || !isStringList(candidate.files, { allowEmpty: false })
    || !hasCanonicalArtifactIdentity(evidence, 'evidence packet')
    || !hasExactKeys(evidence!, ['kind', 'sha256', 'locator', 'status', 'checks', 'candidate_tree_sha256'])
    || evidence.status !== 'passed'
    || evidence.candidate_tree_sha256 !== candidate.sha256
    || !isStringList(evidence.checks, { allowEmpty: false })
    || !hasCanonicalArtifactIdentity(roundtrip, 'round-trip report')
    || !hasExactKeys(roundtrip!, ['kind', 'sha256', 'locator', 'status', 'checks', 'feature_assurance'])
    || roundtrip.status !== 'passed'
    || !checks
    || Object.keys(checks).length === 0
    || !Object.values(checks).every((passed) => passed === true)
    || !REQUIRED_ROUNDTRIP_CHECKS.every((check) => checks[check] === true)
    || !mission
    || !hasExactKeys(mission, ['mission_id', 'objective', 'work_items', 'success_criteria', 'policy_sha256'])
    || !MISSION_ID_RE.test(textOf(mission.mission_id))
    || !textOf(mission.objective)
    || !isStringList(mission.work_items, { allowEmpty: false })
    || !isStringList(mission.success_criteria, { allowEmpty: false })
    || typeof mission.policy_sha256 !== 'string'
    || !SHA256_RE.test(mission.policy_sha256)
    || !artifacts
    || !hasExactKeys(artifacts, GREEN_ARTIFACT_KEYS)
    || !GREEN_ARTIFACT_KEYS.every((key) => (
      hasExactCanonicalArtifactIdentity(artifacts[key], GREEN_ARTIFACT_KINDS[key])
    ))
    || recordOf(artifacts.evidence)?.sha256 !== evidence.sha256
    || recordOf(artifacts.roundtrip)?.sha256 !== roundtrip.sha256
    || mission.policy_sha256 !== recordOf(artifacts.autonomy_policy)?.sha256
    || !publication
    || !hasExactKeys(publication, ['status', 'owner_approval_required', 'automatic_promotion'])
    || publication?.automatic_promotion !== false
    || publication?.owner_approval_required !== true
    || publication?.status !== 'not-requested'
  ) return false;
  return status === 'preview-ready'
    ? Boolean(preview)
      && hasExactKeys(preview!, ['kind', 'path', 'url'])
      && Boolean(safeGenesisPreviewUrl(run.preview, String(run.run_id)))
    : status === 'succeeded' && run.preview === null;
}

function nestedText(value: unknown, keys: string[], depth = 0): string {
  const record = recordOf(value);
  if (!record || depth > 3) return '';
  for (const key of keys) {
    const found = textOf(record[key]);
    if (found) return found;
  }
  for (const item of Object.values(record)) {
    const found = nestedText(item, keys, depth + 1);
    if (found) return found;
  }
  return '';
}

function looksLikeDigest(value: string): boolean {
  return SHA256_LIKE_RE.test(value);
}

function artifactRow(label: string, value: unknown, index: number): GenesisArtifactRow {
  const record = recordOf(value);
  const explicitLabel = record
    ? textOf(record.kind) || textOf(record.type) || textOf(record.name)
    : '';
  const direct = textOf(value);
  const digest = nestedText(value, DIGEST_KEYS) || (looksLikeDigest(direct) ? direct : '');
  const reference = nestedText(value, REFERENCE_KEYS) || (direct && !digest ? direct : '');
  const renderedLabel = explicitLabel || humanGenesisKey(label);
  return {
    key: `${label}:${digest || reference || index}`,
    label: renderedLabel,
    digest,
    reference
  };
}

function present(value: unknown): boolean {
  if (value === null || value === undefined || value === '') return false;
  if (Array.isArray(value)) return value.length > 0;
  const record = recordOf(value);
  return record ? Object.keys(record).length > 0 : true;
}

function isOneArtifact(record: Record<string, unknown>): boolean {
  return [...DIGEST_KEYS, ...REFERENCE_KEYS, 'kind', 'type', 'name'].some((key) => key in record);
}

function hasArtifactIdentity(value: unknown): boolean {
  return Boolean(nestedText(value, DIGEST_KEYS) || nestedText(value, REFERENCE_KEYS));
}

/** Candidate/evidence/round-trip references are first-class artifacts even
 * when an older backend does not repeat them in the aggregate artifact list. */
export function genesisArtifactRows(run: GenesisRun): GenesisArtifactRow[] {
  const values: Array<[string, unknown]> = [];
  if (present(run.candidate) && hasArtifactIdentity(run.candidate)) values.push(['Quellkandidat', run.candidate]);
  if (present(run.evidence) && hasArtifactIdentity(run.evidence)) values.push(['Evidenzpaket', run.evidence]);
  if (present(run.roundtrip) && hasArtifactIdentity(run.roundtrip)) values.push(['Round-trip-Bericht', run.roundtrip]);

  if (Array.isArray(run.artifacts)) {
    run.artifacts.forEach((artifact, index) => values.push([`Artefakt ${index + 1}`, artifact]));
  } else {
    const artifacts = recordOf(run.artifacts);
    if (artifacts && isOneArtifact(artifacts)) {
      values.push(['Artefakt', artifacts]);
    } else if (artifacts) {
      Object.entries(artifacts).forEach(([kind, artifact]) => {
        if (present(artifact)) values.push([kind, artifact]);
      });
    } else if (present(run.artifacts)) {
      values.push(['Artefakt', run.artifacts]);
    }
  }

  const seen = new Set<string>();
  return values
    .map(([label, value], index) => artifactRow(label, value, index))
    .filter((row) => {
      // The service intentionally repeats evidence and round-trip in the
      // first-class fields and the aggregate artifact map. Their CAS identity,
      // not the presentation label, determines whether they are the same row.
      const identity = row.digest || row.reference
        ? `${row.digest}|${row.reference}`
        : row.key;
      if (seen.has(identity)) return false;
      seen.add(identity);
      return true;
    });
}

export function genesisStatusLabel(status: string): string {
  const key = status.trim().toLowerCase();
  const known: Record<string, string> = {
    admitted: 'angenommen',
    queued: 'eingereiht',
    running: 'läuft',
    repairing: 'wird repariert',
    'preview-ready': 'Vorschau bereit',
    ready: 'bereit',
    completed: 'abgeschlossen',
    succeeded: 'erfolgreich',
    deployed: 'bereitgestellt',
    blocked: 'blockiert',
    blocked_external: 'extern blockiert',
    failed: 'fehlgeschlagen',
    cancelled: 'abgebrochen'
  };
  return known[key] || status || 'nicht gemeldet';
}

export function genesisStatusTone(status: string): 'live' | 'ok' | 'warn' | 'bad' | 'muted' {
  const key = status.trim().toLowerCase();
  if (['preview-ready', 'succeeded'].includes(key)) return 'ok';
  if (['blocked', 'blocked_external'].includes(key)) return 'warn';
  if (['failed', 'cancelled', 'error'].includes(key)) return 'bad';
  return key ? 'live' : 'muted';
}

/** A blocked/running response has not given the browser a new successful
 * terminal identity. Retaining the backend-confirmed key lets the owner retry
 * the exact request instead of accidentally creating a sibling Attempt. */
export function retainsGenesisRetryIdentity(status: string): boolean {
  return ['blocked', 'running'].includes(status.trim().toLowerCase());
}

export function genesisRequestFor(
  prompt: string,
  target: string,
  stack: string,
  requestKey: string
): GenesisRequest {
  const cleanPrompt = prompt.trim();
  const cleanTarget = target.trim();
  const cleanStack = stack.trim();
  const cleanKey = requestKey.trim();
  if (!cleanPrompt) throw new Error('Beschreibe zuerst das Produkt.');
  if (!cleanKey) throw new Error('Der Genesis-Request hat keinen stabilen Schlüssel.');
  return {
    prompt: cleanPrompt,
    ...(cleanTarget ? { target: cleanTarget } : {}),
    ...(cleanStack ? { stack: cleanStack } : {}),
    request_key: cleanKey
  };
}

export function createGenesisRequestKey(uuid?: () => string): string {
  if (uuid) return `genesis:${uuid()}`;
  if (typeof globalThis.crypto?.randomUUID === 'function') {
    return `genesis:${globalThis.crypto.randomUUID()}`;
  }
  if (typeof globalThis.crypto?.getRandomValues === 'function') {
    const bytes = globalThis.crypto.getRandomValues(new Uint8Array(16));
    return `genesis:${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
  }
  throw new Error('Dieser Browser kann keinen sicheren Request-Schlüssel erzeugen.');
}

export function isGenesisRun(value: unknown, expectedRequestKey?: string): value is GenesisRun {
  const run = recordOf(value);
  if (!run) return false;
  const runId = typeof run.run_id === 'string' ? run.run_id : '';
  const requestKey = typeof run.request_key === 'string' ? run.request_key : '';
  const status = typeof run.status === 'string' ? run.status : '';
  if (
    !GENESIS_RUN_ID_RE.test(runId)
    || !requestKey
    || (expectedRequestKey !== undefined && requestKey !== expectedRequestKey)
    || !GENESIS_STATUSES.has(status)
    || !['target', 'defaults', 'blockers', 'mission', 'candidate', 'evidence', 'roundtrip', 'preview', 'artifacts']
      .every((key) => key in run)
    || typeof run.target !== 'string'
    || !recordOf(run.defaults)
    || !isStringList(run.blockers)
  ) return false;
  if (status === 'preview-ready' || status === 'succeeded') {
    return hasGreenGenesisChain(run, status);
  }
  if (status === 'running' || status === 'blocked') {
    return run.candidate === null
      && run.evidence === null
      && run.roundtrip === null
      && run.preview === null;
  }
  return status === 'failed' && run.preview === null;
}

export function previewUrlFrom(value: unknown): string {
  return textOf(recordOf(value)?.url);
}

/** Generated code is embedded only when the complete service preview contract
 * binds an explicit numeric loopback URL to this exact canonical run. The
 * validated URL is projected back to the canonical same-origin path, so even a
 * forged sibling loopback port can never become iframe navigation. */
export function safeGenesisPreviewUrl(value: unknown, runId: string): string | undefined {
  const preview = recordOf(value);
  const raw = textOf(preview?.url);
  const cleanRunId = runId.trim();
  if (
    !preview
    || !raw
    || !GENESIS_RUN_ID_RE.test(cleanRunId)
    || textOf(preview.kind) !== 'read-only-cas-preview'
    || textOf(preview.path) !== `/api/genesis/${cleanRunId}/preview/`
  ) return undefined;
  try {
    const url = new URL(raw);
    const hostname = url.hostname;
    const ipv6Loopback = hostname === '[::1]';
    // WHATWG URL parsing canonicalizes valid IPv4 spellings; the complete
    // 127/8 block is loopback, not only 127.0.0.1.
    const ipv4Loopback = /^127(?:\.\d{1,3}){3}$/.test(hostname);
    if (
      url.protocol !== 'http:'
      || (!ipv4Loopback && !ipv6Loopback)
      || !url.port
      || url.username
      || url.password
      || url.pathname !== preview.path
      || url.search
      || url.hash
    ) return undefined;
    return textOf(preview.path);
  } catch {
    return undefined;
  }
}
