import type { ApiEnvelope, BootstrapPayload, ControlPlanePayload, DashboardPayload, DistillPayload, EffortLevel, GovernancePayload, HierarchyPayload, IkarusAskPayload, IkarusChatPayload, LiveEventName, ProjectRow, RuntimeStatusPayload, RuntimeTestPayload, StructurePayload } from './types';

/**
 * Why a request failed, kept SEPARATE from the message.
 *
 * "the server said no" and "there is no server" are different facts and they
 * were previously the same thrown `Error` — which is exactly the collapse this
 * project keeps removing everywhere else. A UI that cannot tell them apart
 * renders "loading…" forever at a dead backend, or renders a 404 as an outage.
 *
 *   network   nothing answered on the loopback port — the API is not running
 *   timeout   something is there and did not answer in time — NOT proof of health
 *   notfound  the backend answered 404: this build talks to an older server
 *   http      the server answered with a non-2xx status
 *   app       HTTP 200 with `ok:false` — the endpoint ran and refused
 */
export type ApiFailure = 'network' | 'timeout' | 'notfound' | 'http' | 'app';

export class ApiError extends Error {
  readonly kind: ApiFailure;
  readonly status: number;
  readonly url: string;

  constructor(kind: ApiFailure, message: string, url: string, status = 0) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.url = url;
  }
}

/** True when nothing answered at all — the "start the backend" case. */
export function isBackendDown(error: unknown): boolean {
  return error instanceof ApiError && error.kind === 'network';
}

async function request<T>(url: string, init?: RequestInit, timeoutMs = 20_000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    let res: Response;
    try {
      res = await fetch(url, {
        headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
        ...init,
        signal: controller.signal
      });
    } catch (error) {
      // fetch only rejects on a transport failure or an abort. Anything the
      // server actually answered — including 500 — resolves.
      if (controller.signal.aborted) {
        throw new ApiError(
          'timeout',
          `No answer within ${Math.round(timeoutMs / 1000)}s from ${url}. The request was abandoned; this says nothing about whether the work succeeded.`,
          url
        );
      }
      throw new ApiError(
        'network',
        `Could not reach the Daedalus API at ${location.origin}${url.startsWith('/') ? url : `/${url}`}.`,
        url
      );
    }

    let data: (Record<string, unknown> & { ok?: boolean; error?: string }) | undefined;
    try {
      data = await res.json();
    } catch {
      data = undefined;
    }
    if (res.status === 404) {
      throw new ApiError('notfound', data?.error || `This backend has no ${url}`, url, 404);
    }
    if (!res.ok) {
      throw new ApiError('http', data?.error || `Request failed: HTTP ${res.status}`, url, res.status);
    }
    if (data && data.ok === false) {
      throw new ApiError('app', data.error || 'The endpoint ran and refused.', url, res.status);
    }
    return data as T;
  } finally {
    window.clearTimeout(timer);
  }
}

export function getProjects() {
  return request<ApiEnvelope & { projects: ProjectRow[] }>('/api/projects');
}

export function getDashboard(project: string) {
  return request<DashboardPayload>(`/api/dashboard?project=${encodeURIComponent(project)}`);
}

/** The promotion verdict on its own. Identical to `dashboard.governance` --
 *  same backend function, no second opinion. */
export function getGovernance(project: string) {
  return request<GovernancePayload>(`/api/governance?project=${encodeURIComponent(project)}`);
}

export function getHierarchy(project: string) {
  return request<HierarchyPayload>(`/api/projects/${encodeURIComponent(project)}/hierarchy`);
}

export function getControlPlane(project: string) {
  return request<ControlPlanePayload>(`/api/projects/${encodeURIComponent(project)}/control-plane`);
}

/** Per-provider BYOK readiness, from `daedalus/env.py` `env_status()`.
 * `configured` is the invariant that matters — `ollama` needs no key so it is
 * always `true`; `deepseek`/`anthropic_api`/`openai_api` reflect whether their
 * env key is actually set (never the key's value). */
export interface EnvProviderInfo {
  configured: boolean;
  host?: string;
  model?: string;
  embed_model?: string;
  base_url?: string;
}

export interface EnvStatusPayload {
  env_file: string;
  env_file_exists: boolean;
  loaded_keys: string[];
  public: Record<string, string>;
  secrets: Record<string, { configured: boolean }>;
  providers: Record<string, EnvProviderInfo>;
}

export function getEnvStatus() {
  return request<ApiEnvelope & { env: EnvStatusPayload }>('/api/env/status');
}

/** One provider row from `daedalus/providers/__init__.py` `provider_health()` —
 * richer than a runtime row: carries `configured` (env key / CLI auth present)
 * SEPARATE from `available` (actually reachable right now), so the UI can tell
 * "no key" apart from "key set but server down" instead of collapsing both
 * into one flat unavailable/offline state. */
export interface ProviderStatusRow {
  name: string;
  display_name: string;
  local: boolean;
  trusted_with_ip: boolean;
  can_write: boolean;
  agentic: boolean;
  requires_key: boolean;
  env_keys: string[];
  implemented: boolean;
  configured: boolean;
  available: boolean;
  last_error: string;
}

export interface ProviderStatusPayload extends ApiEnvelope {
  providers: ProviderStatusRow[];
}

export function getProviderStatus() {
  return request<ProviderStatusPayload>('/api/providers/status');
}

/** One fact behind a health verdict. The backend refuses to call inherited or
 * configured data "measured", and the UI keeps that provenance visible. */
export interface HealthFact {
  label: string;
  value: unknown;
  provenance: 'MEASURED' | 'INHERITED' | 'ASSUMED';
  source: string | null;
  age_s: number | null;
}

export interface HealthSubsystem {
  name: string;
  asks: string;
  state: 'working' | 'present' | 'degraded' | 'absent' | 'unknown';
  headline: string;
  facts: HealthFact[];
  remedy: string;
  required: boolean;
  seconds: number;
}

export interface HealthSnapshot {
  schema: number;
  generated_at: string;
  states: string[];
  counts: Record<'working' | 'present' | 'degraded' | 'absent' | 'unknown', number>;
  /** 0 every probe held; 1 something is broken; 2 the run is unproven. */
  verdict: 0 | 1 | 2;
  not_proven: string[];
  subsystems: HealthSubsystem[];
}

export interface HealthPayload extends ApiEnvelope {
  health: HealthSnapshot;
  asked?: { deep: boolean; probe_remote: boolean; only: string | null };
}

/**
 * Read-only system glance. Expensive and remote probes remain off.
 *
 * The 30s budget this used to carry was BELOW what the endpoint costs. Measured
 * on this machine 2026-08-25, a shallow assess() takes ~39.5s wall (slowest
 * probes: picker.queue 13.9s, embed.bench 6.0s, hand.executor 6.0s), so every
 * call timed out and the surfaces printed "Zustand ungelesen" over a health
 * surface that was working. A timeout shorter than the work turns a slow
 * answer into a reported failure, which is the same lie as the reverse.
 *
 * 90s is the budget, not the expectation: callers should render "wird gelesen"
 * meanwhile and must not block anything else on it.
 */
export function getHealth(timeoutMs = 90_000) {
  return request<HealthPayload>('/api/health', undefined, timeoutMs);
}

export function updateAgent(project: string, agent: string, patch: Record<string, unknown>) {
  return request(`/api/projects/${encodeURIComponent(project)}/agents/${encodeURIComponent(agent)}`, {
    method: 'PUT',
    body: JSON.stringify(patch)
  });
}

export function updateCategory(project: string, category: string, patch: Record<string, unknown>) {
  return request(`/api/projects/${encodeURIComponent(project)}/categories/${encodeURIComponent(category)}`, {
    method: 'PUT',
    body: JSON.stringify(patch)
  });
}

export function queueTask(project: string, objective: string, lane: string) {
  return request('/api/queue', {
    method: 'POST',
    body: JSON.stringify({ project, objective, lane, source: 'agent-os', strategy: 'single' })
  });
}

export function chatIkarus(project: string, message: string, apply = false) {
  return request<IkarusChatPayload>('/api/ikarus/chat', {
    method: 'POST',
    body: JSON.stringify({ project, message, apply })
  }, 60_000);
}

/**
 * General Ikarus brain. `provider` is a runtime `id` (e.g. `ollama_http`,
 * `claude_code_cli`) or `deterministic`/omitted for the no-LLM default. BYOK —
 * no keys involved. Distinct from `chatIkarus`, which stays the network-designer.
 *
 * `model` optionally overrides the provider's default model (blank = default);
 * `effort` tunes freeform-chat reasoning depth (cheap-by-default 'low'). Both
 * are additive — deterministic intents ignore them and still return fast.
 */
export function askIkarus(
  project: string,
  message: string,
  provider?: string,
  model?: string,
  effort?: EffortLevel
) {
  const body: Record<string, unknown> = { project, message };
  if (provider) body.provider = provider;
  if (model && model.trim()) body.model = model.trim();
  if (effort) body.effort = effort;
  return request<IkarusAskPayload>('/api/ikarus/ask', {
    method: 'POST',
    body: JSON.stringify(body)
  }, 120_000);
}

/**
 * Open the live server-sent-event stream for a project. Named events
 * (`hello|report|heartbeat|queue`) each carry a JSON `data:` payload. The
 * browser `EventSource` auto-reconnects when the server recycles the stream
 * (~5 min) — callers just keep the returned handle and `.close()` on teardown.
 */
export function openEventStream(
  project: string,
  onEvent: (name: LiveEventName, data: unknown) => void
): EventSource {
  const es = new EventSource(`/api/events?project=${encodeURIComponent(project)}`);
  const names: LiveEventName[] = ['hello', 'report', 'heartbeat', 'queue'];
  names.forEach((name) => {
    es.addEventListener(name, (event) => {
      let data: unknown;
      try {
        data = JSON.parse((event as MessageEvent).data);
      } catch {
        data = undefined;
      }
      onEvent(name, data);
    });
  });
  return es;
}

/**
 * Streaming twin of `askIkarus` — renders text as it is produced instead of
 * blocking on the whole reply. Same routing and the same `final` envelope, so
 * callers can reuse their existing result handling verbatim.
 *
 * ⚠️ LIFECYCLE IS LOAD-BEARING. `EventSource` AUTO-RECONNECTS whenever the
 * server closes the socket, and this endpoint is a ONE-SHOT stream that closes
 * after `final`. Without an explicit `close()` the browser silently reopens it
 * and **re-runs the entire chat turn — re-spending tokens and money, forever**.
 * So every terminal path here closes exactly once, via `settle()`.
 *
 * Falls back to nothing on its own: if the stream dies before `final`, the
 * caller is told via `onError` and should retry with the blocking `askIkarus`.
 */
export function streamIkarus(
  project: string,
  message: string,
  provider: string | undefined,
  model: string | undefined,
  effort: EffortLevel | undefined,
  handlers: {
    onStart?: (data: { intent?: string; provider_used?: string }) => void;
    onDelta: (text: string) => void;
    onFinal: (payload: IkarusAskPayload) => void;
    onError: (err: Error) => void;
  }
): { close: () => void } {
  const qs = new URLSearchParams({ project, message });
  if (provider) qs.set('provider', provider);
  if (model && model.trim()) qs.set('model', model.trim());
  if (effort) qs.set('effort', effort);

  const es = new EventSource(`/api/ikarus/stream?${qs.toString()}`);

  // One-shot guard: `final` and `error` can both fire, and a closed EventSource
  // must not be closed (or reported) twice.
  let done = false;
  const settle = (fn?: () => void) => {
    if (done) return;
    done = true;
    es.close();
    fn?.();
  };

  es.addEventListener('start', (event) => {
    try {
      handlers.onStart?.(JSON.parse((event as MessageEvent).data));
    } catch { /* a malformed start frame is not worth failing the turn over */ }
  });

  es.addEventListener('delta', (event) => {
    try {
      const { text } = JSON.parse((event as MessageEvent).data);
      if (typeof text === 'string' && text) handlers.onDelta(text);
    } catch { /* skip an unparseable delta rather than kill the stream */ }
  });

  es.addEventListener('final', (event) => {
    let payload: IkarusAskPayload | undefined;
    try {
      payload = JSON.parse((event as MessageEvent).data);
    } catch {
      settle(() => handlers.onError(new Error('malformed final frame')));
      return;
    }
    settle(() => handlers.onFinal(payload as IkarusAskPayload));
  });

  // Fires on network failure AND on the normal server-side close. If `final`
  // already arrived we are settled and this is the expected teardown, so the
  // guard makes it a no-op rather than a spurious error.
  es.onerror = () => settle(() => handlers.onError(new Error('ikarus stream interrupted')));

  return { close: () => settle() };
}

export function updateAutonomy(project: string, patch: Record<string, unknown>) {
  return request<ControlPlanePayload>(`/api/projects/${encodeURIComponent(project)}/autonomy`, {
    method: 'PUT',
    body: JSON.stringify(patch)
  });
}

export function getRuntimeStatus() {
  return request<RuntimeStatusPayload>('/api/runtimes/status');
}

export function testRuntime(runtimeId: string) {
  return request<RuntimeTestPayload>(`/api/runtimes/${encodeURIComponent(runtimeId)}/test`, {
    method: 'POST',
    body: JSON.stringify({})
  }, 30_000);
}

export function getClaudeBootstrap(project: string) {
  return request<BootstrapPayload>(`/api/projects/${encodeURIComponent(project)}/bootstrap/claude`);
}

export interface DraftRow {
  id: string;
  created: string;
  agent: string;
  objective: string;
  paths: string[];
  status: 'pending' | 'applied' | 'dismissed';
}

export function getDrafts() {
  return request<ApiEnvelope & { drafts: DraftRow[]; pending_count: number }>('/api/drafts');
}

/** Full draft content — `daedalus/drafts.py` `save_draft()`'s stored shape.
 * `report` is the agent_report_v1 the offload run produced; there is no
 * separate computed unified diff on the backend, so `report` (summary,
 * files_changed, risks, todos, handoff) IS the proposal a reviewer reads
 * before Apply. `handoff` is free-form (provider-specific: e.g. `notes` or
 * `suggestion`) and may itself contain diff-shaped text. */
export interface DraftReport {
  status: 'done' | 'blocked' | 'needs_review' | 'failed';
  summary: string;
  files_changed: string[];
  tests_run: string[];
  risks: string[];
  todos: string[];
  handoff: Record<string, unknown>;
}

export interface DraftDetail {
  id: string;
  created: string;
  objective: string;
  paths: string[];
  agent: string;
  provider: string;
  persona: string;
  repo_root: string;
  report: DraftReport;
  status: 'pending' | 'applied' | 'dismissed';
  status_changed?: string;
}

/** The review packet for ONE draft — GET before Apply, so a user reads the
 * proposal instead of applying it blind. 404 (unknown id) surfaces as a
 * thrown Error via the shared `request()` envelope check. */
export function getDraft(id: string) {
  return request<ApiEnvelope & { draft: DraftDetail }>(`/api/drafts/${encodeURIComponent(id)}`);
}

export function applyDraft(id: string) {
  return request<ApiEnvelope & { applied: Record<string, unknown> }>(
    `/api/drafts/${encodeURIComponent(id)}/apply`, { method: 'POST', body: '{}' });
}

export function dismissDraft(id: string) {
  return request(`/api/drafts/${encodeURIComponent(id)}/dismiss`, { method: 'POST', body: '{}' });
}

/* ------------------------------------------------------------------ *
 * The self-improvement loop — three READ-ONLY endpoints (web_api.py).
 *
 * These three payloads all carry `degraded_sources` / `incomplete`, and that
 * is the field the rest of this app is built around: an EMPTY list and a
 * FAILED source produce the same short answer, and only these flags keep them
 * apart. Nothing in `views/` is allowed to render one of these payloads
 * without rendering that flag.
 * ------------------------------------------------------------------ */

/** One ranked candidate, WITH the measurement that put it in the queue.
 *
 * `score = band + measured_offset`. The BAND is a stated priority (a prior,
 * per source); only the OFFSET is measured. `evidence` is the audit trail and
 * is open-ended by design — the backend bounds it, never allowlists it — so it
 * is typed as an open record and rendered generically. */
export interface LoopCandidate {
  task_id: string;
  source: string;
  score: number | null;
  band: number | null;
  measured_offset: number | null;
  reason: string;
  instruction: string;
  gate_paths: unknown;
  evidence: Record<string, unknown>;
}

export interface LoopQueueBlock {
  candidates: LoopCandidate[];
  n_candidates: number;
  limit: number;
  /** Per-source detail. Shapes differ per source ON PURPOSE — see views/health.ts. */
  sources: Record<string, unknown>;
  notes: string[];
  /** Sources that could NOT be consulted. An empty queue with a non-empty
   * `degraded_sources` is NOT evidence that there is no work. */
  degraded_sources: string[];
  incomplete: boolean;
  opt_in_sources_available: boolean;
  returned?: number;
  dropped_for_size?: number;
  response_bytes?: number;
}

export interface LoopQueuePayload extends ApiEnvelope {
  queue: LoopQueueBlock;
}

export interface LoopAttempt {
  intent_id: number;
  kind: string;
  state: string;
  created_ts: string;
  resolved_ts: string | null;
  effect_key: string;
  task_id: string;
  instruction: string;
  source: string;
  score: number | null;
  reason: string;
  outcome: string | null;
  gates_passed: boolean | null;
  changed_paths: number | null;
  error: string | null;
  /** NOT YET SERVED by `/api/loop/attempts` (2026-07-29). The live loop report
   * now knows lane/worker, but this endpoint projects the separate spine
   * intent ledger through a fixed allowlist that omits them. Optional here so
   * an additive backend field will render immediately; absent is always shown
   * as "not reported", never as an empty value. */
  lane?: string;
  worker?: string;
  /** Also not yet served: the run/trace this attempt belongs to. Without it,
   * attempts cannot be scoped to "this run" — only to "all recorded history". */
  trace_id?: string;
  run_id?: string;
}

export interface LoopAttemptsBlock {
  intents: LoopAttempt[];
  limit: number;
  kind: string;
  task_id: string | null;
  ledger: {
    path: string;
    /** A ledger that does not exist yet and one that will not OPEN are
     * different facts: the first is a fresh checkout, the second is a source
     * that failed. `exists:false` + `error:null` is the first. */
    exists: boolean;
    read_only: boolean;
    error: string | null;
    note: string | null;
  };
  degraded_sources: string[];
  incomplete: boolean;
  attempt_intent_kind: string;
  returned?: number;
  dropped_for_size?: number;
  response_bytes?: number;
}

export interface LoopAttemptsPayload extends ApiEnvelope {
  attempts: LoopAttemptsBlock;
}

/** The snapshot's own verdict on itself: integrity (does the digest cover the
 * contents) AND freshness (was it written against this HEAD) are separate
 * questions, and the endpoint returns the whole verdict rather than a boolean
 * precisely because the predicate grew a second question after shipping. */
export interface LoopTrust {
  trusted?: boolean;
  reason?: string;
  integrity?: boolean;
  freshness?: {
    fresh?: boolean;
    reason?: string;
    recorded_head?: string;
    actual_head?: string;
    dirty?: boolean;
  };
  [key: string]: unknown;
}

export interface LoopArchitectureBlock {
  path: string;
  read: boolean;
  schema: number | null;
  digest: string;
  note: string;
  counts: Record<string, number>;
  measured_lengths: Record<string, number>;
  count_disagreements: Record<string, { recorded: number | null; measured: number }>;
  trusted: boolean;
  trust_reason: string;
  trust: LoopTrust;
  degraded_sources: string[];
  incomplete: boolean;
}

export interface LoopArchitecturePayload extends ApiEnvelope {
  architecture: LoopArchitectureBlock;
}

/** Ranked work queue + which sources spoke. `project` omitted = this checkout. */
export function getLoopQueue(project?: string, limit = 10) {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (project) qs.set('project', project);
  return request<LoopQueuePayload>(`/api/loop/queue?${qs.toString()}`, undefined, 45_000);
}

/** Attempt history from the spine ledger (opened read-only server-side). */
export function getLoopAttempts(limit = 20, kind?: string, taskId?: string) {
  const qs = new URLSearchParams({ limit: String(limit) });
  if (kind) qs.set('kind', kind);
  if (taskId) qs.set('task_id', taskId);
  return request<LoopAttemptsPayload>(`/api/loop/attempts?${qs.toString()}`, undefined, 30_000);
}

/** Counts + digest + the full trust verdict of the architecture snapshot. */
export function getLoopArchitecture(project?: string) {
  const qs = new URLSearchParams();
  if (project) qs.set('project', project);
  const suffix = qs.toString();
  return request<LoopArchitecturePayload>(
    `/api/loop/architecture${suffix ? `?${suffix}` : ''}`, undefined, 30_000);
}

/**
 * Structure (code-health / distillation) surface. The first call for a big
 * repo can take up to ~60s while the server indexes it — callers should show a
 * loading state. `refresh` forces a re-index server-side.
 */
export function getStructure(project: string, refresh = false): Promise<StructurePayload> {
  const q = `project=${encodeURIComponent(project)}${refresh ? '&refresh=1' : ''}`;
  return request<StructurePayload>(`/api/structure?${q}`, undefined, 70_000);
}

/** Distill a target module/symbol down to a minimal review slice. */
export function distill(project: string, target: string): Promise<DistillPayload> {
  return request<DistillPayload>('/api/distill', {
    method: 'POST',
    body: JSON.stringify({ project, target })
  }, 70_000);
}
