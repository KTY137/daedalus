import type { ApiEnvelope, BootstrapPayload, ContextPlanPayload, ControlPlanePayload, DashboardPayload, DesktopStatusPayload, DistillPayload, EffortLevel, GovernancePayload, HierarchyPayload, IkarusAskPayload, IkarusChatPayload, LiveEventName, ProjectRegistration, ProjectRegistrationPayload, ProjectRow, RuntimeStatusPayload, RuntimeTestPayload, StructurePayload, TopologyPayload } from '../contracts';

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
      // GERMAN, BECAUSE THE COCKPIT IS GERMAN.
      //
      // These five strings are the only text this module puts in front of a
      // person, and they arrive at the worst moment — when something has just
      // failed. They were written in English while every surface that shows
      // them says "Die Daedalus-API antwortet nicht." two elements away.
      // Every surface query now renders the German Cockpit, so this client
      // keeps its human-facing failure vocabulary in the same language.
      //
      // The distinction each one draws is load-bearing and survives the
      // translation intact: an abandoned request is not a failed one, and
      // saying so is the difference between an honest error and a guess.
      if (controller.signal.aborted) {
        throw new ApiError(
          'timeout',
          `Keine Antwort binnen ${Math.round(timeoutMs / 1000)}s von ${url}. Die Anfrage wurde abgebrochen; das sagt nichts darüber, ob die Arbeit gelungen ist.`,
          url
        );
      }
      throw new ApiError(
        'network',
        `Die Daedalus-API unter ${location.origin}${url.startsWith('/') ? url : `/${url}`} ist nicht erreichbar.`,
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
      throw new ApiError('notfound', data?.error || `Dieses Backend kennt ${url} nicht.`, url, 404);
    }
    if (!res.ok) {
      throw new ApiError('http', data?.error || `Anfrage fehlgeschlagen: HTTP ${res.status}.`, url, res.status);
    }
    if (data && data.ok === false) {
      throw new ApiError('app', data.error || 'Der Endpunkt lief und hat abgelehnt.', url, res.status);
    }
    return data as T;
  } finally {
    window.clearTimeout(timer);
  }
}

export function getProjects() {
  return request<ApiEnvelope & { projects: ProjectRow[] }>('/api/projects');
}

/** Register an existing checkout. This sends only its local path and optional
 * display name; it is not a repository upload. */
export function createProject(registration: ProjectRegistration) {
  return request<ProjectRegistrationPayload>('/api/projects', {
    method: 'POST',
    body: JSON.stringify(registration)
  });
}

/** The desktop settings response is also the single measured service-status
 * snapshot. Source/dev servers may answer 404; callers must render that as
 * unavailable instead of inventing a running IDE. */
export function getDesktopStatus() {
  return request<DesktopStatusPayload>('/api/desktop/settings');
}

export function startDesktopIde(projectName: string) {
  return request<DesktopStatusPayload>('/api/desktop/services/ide/start', {
    method: 'POST',
    body: JSON.stringify({ project: projectName })
  }, 70_000);
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

/** Per-provider BYOK readiness, from `daedalus/foundation/env.py` `env_status()`.
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

/* ---- Conversations: the chat that survives a reload ---- */

export interface ConversationTurn {
  /** Canonical conversation-spine identity for this exchange. */
  id?: number;
  user_message: string;
  assistant_text: string | null;
  intent?: string;
  provider_used?: string;
  model_used?: string;
  created?: string;
  /** When the spine recorded this turn (ISO). Absent on an older server. */
  created_ts?: string;
  project?: string;
  status?: string;
  proposed_action?: Record<string, unknown> | null;
  /**
   * The bounded final envelope the server stored with the turn (clipped by
   * `_loop_shape`). The ledger reads its receipts from here on resume; a
   * field that was not stored is simply absent.
   */
  envelope?: Record<string, unknown> | null;
}

/** One row of GET /api/conversations?project= — a thread, newest activity first. */
export interface ConversationListRow {
  conversation_id: string;
  turn_count: number;
  first_message: string;
  last_message: string;
  last_ts: string;
  last_intent?: string | null;
  last_provider_used?: string | null;
  last_status?: string | null;
}

export interface ConversationView {
  conversation_id: string;
  exists: boolean;
  turn_count: number;
  narrative?: string;
  turns: ConversationTurn[];
  turns_returned: number;
  dispatches?: ConversationDispatch[];
  open_dispatches?: ConversationDispatch[];
}

export interface ConversationDispatch {
  link?: {
    turn_id?: number;
    dispatch_ref?: string;
    /** when the dispatch was linked — what "seit" is measured from */
    created_ts?: string;
    kind?: string;
  } | null;
  latest?: {
    lifecycle?: string;
    summary?: string;
    outcome_state?: string | null;
    detail?: Record<string, unknown> | null;
    ts?: string;
  } | null;
}

/**
 * Mint an id. Deliberately a pure id: the row is created by the FIRST
 * `append_turn`, so this never leaves a conversation-shaped id behind that
 * GET would 404 on forever.
 */
export function newConversation() {
  return request<ApiEnvelope & { conversation_id: string }>('/api/conversations', {
    method: 'POST',
    body: '{}'
  });
}

/** This project's threads from the canonical spine, newest first. Read-only. */
export function listConversations(project: string, limit = 20) {
  return request<ApiEnvelope & { conversations: ConversationListRow[] }>(
    `/api/conversations?project=${encodeURIComponent(project)}&limit=${limit}`
  );
}

/** The resumable view: the narrative, the bounded turn list, open dispatches. */
export function getConversation(id: string, limit = 40) {
  return request<ApiEnvelope & { conversation: ConversationView }>(
    `/api/conversations/${encodeURIComponent(id)}?limit=${limit}`
  );
}

/** Immutable editor selection metadata. The selection itself stays server-side;
 * this public receipt says exactly which project-bound artifact may be attached
 * to an Ikarus turn. */
export interface EditorContextReceipt {
  context_ref: string;
  project: string;
  path: string;
  range?: { start_line: number; start_column: number; end_line: number; end_column: number } | null;
  selection_chars: number;
  expires_at: string;
  expired: boolean;
  sensitivity: string;
  inclusion_report?: { accepted?: boolean; reason?: string } | null;
}

export function getEditorContext(contextRef: string) {
  return request<ApiEnvelope & { context: EditorContextReceipt }>(
    `/api/editor/contexts/${encodeURIComponent(contextRef)}`
  );
}

export type ConversationCancellationStatus =
  | 'requested'
  | 'confirmed'
  | 'not_supported'
  | 'already_terminal'
  | 'unknown';

export interface ConversationCancellation {
  cancellation_id?: number;
  request_id?: number;
  client_cancel_id?: string;
  status: ConversationCancellationStatus;
  created_at?: string;
  resolved_at?: string | null;
}

/** The canonical, idempotent request for one generation turn. POST creates
 * exactly once under `client_request_id`; all later reading uses its request id. */
export interface ConversationTurnRequest {
  request_id: number;
  conversation_id: string;
  client_request_id: string;
  project: string;
  state: 'streaming' | 'cancel_requested' | 'final' | 'cancelled' | 'error' | 'unknown';
  created_at?: string;
  resolved_at?: string | null;
  turn_id?: number | null;
  final?: IkarusAskPayload | null;
  error?: string | null;
  cancellation?: ConversationCancellation | null;
}

export interface CreateConversationTurnPayload extends ApiEnvelope {
  turn_request: ConversationTurnRequest;
  created: boolean;
  status_url?: string;
  events_url?: string;
}

export function createConversationTurn(
  conversationId: string,
  input: {
    client_request_id: string;
    project: string;
    message: string;
    provider?: string;
    model?: string;
    effort?: EffortLevel;
    context_refs?: string[];
  }
) {
  const body: Record<string, unknown> = {
    client_request_id: input.client_request_id,
    project: input.project,
    message: input.message,
    context_refs: input.context_refs || []
  };
  if (input.provider) body.provider = input.provider;
  if (input.model?.trim()) body.model = input.model.trim();
  if (input.effort) body.effort = input.effort;
  return request<CreateConversationTurnPayload>(
    `/api/conversations/${encodeURIComponent(conversationId)}/turns`,
    { method: 'POST', body: JSON.stringify(body) },
    30_000
  );
}

export function cancelConversationTurn(
  conversationId: string,
  requestId: number,
  clientCancelId: string
) {
  return request<ApiEnvelope & { cancellation: ConversationCancellation }>(
    `/api/conversations/${encodeURIComponent(conversationId)}/turns/${encodeURIComponent(String(requestId))}/cancel-requests`,
    { method: 'POST', body: JSON.stringify({ client_cancel_id: clientCancelId }) },
    30_000
  );
}

/** Read-only SSE observation of an already-created generation request. A
 * reconnect repeats only this GET, never the effectful creation POST. */
export function observeConversationTurn(
  conversationId: string,
  requestId: number,
  handlers: {
    onStart?: (data: { intent?: string; provider_used?: string }) => void;
    onDelta?: (text: string) => void;
    onFinal?: (payload: IkarusAskPayload) => void;
    onCancelled?: (cancellation: ConversationCancellation) => void;
    onError?: (error: Error) => void;
    onState?: (status: ConversationTurnRequest) => void;
  }
): { close: () => void } {
  const es = new EventSource(
    `/api/conversations/${encodeURIComponent(conversationId)}/turns/${encodeURIComponent(String(requestId))}/events`
  );
  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    es.close();
  };
  const read = (event: Event): Record<string, unknown> => {
    const value: unknown = JSON.parse((event as MessageEvent).data);
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('malformed conversation observation frame');
    return value as Record<string, unknown>;
  };

  es.addEventListener('start', (event) => {
    try { handlers.onStart?.(read(event)); } catch { /* start is advisory */ }
  });
  es.addEventListener('delta', (event) => {
    try {
      const text = read(event).text;
      if (typeof text === 'string' && text) handlers.onDelta?.(text);
    } catch { /* one malformed delta must not discard the observed request */ }
  });
  es.addEventListener('final', (event) => {
    try {
      handlers.onFinal?.(read(event) as unknown as IkarusAskPayload);
      close();
    } catch {
      handlers.onError?.(new Error('malformed final observation frame'));
      close();
    }
  });
  es.addEventListener('cancelled', (event) => {
    try {
      const data = read(event);
      handlers.onCancelled?.({ status: data.status === 'confirmed' ? 'confirmed' : 'unknown', request_id: requestId });
    } catch {
      handlers.onCancelled?.({ status: 'unknown', request_id: requestId });
    }
    close();
  });
  es.addEventListener('error', (event) => {
    // EventSource uses the same DOM event name for a transport interruption
    // and for the server's named `event: error` frame. Only the latter carries
    // MessageEvent data and is terminal; the former must remain reconnectable
    // observation and, crucially, must never trigger another POST.
    if (!(event instanceof MessageEvent) || typeof event.data !== 'string') return;
    try {
      const error = read(event).error;
      handlers.onError?.(new Error(typeof error === 'string' ? error : 'Ikarus-Request fehlgeschlagen'));
    } catch {
      handlers.onError?.(new Error('malformed conversation error frame'));
    }
    close();
  });
  es.addEventListener('state', (event) => {
    try {
      const status = read(event) as unknown as ConversationTurnRequest;
      handlers.onState?.(status);
      if (['final', 'cancelled', 'error', 'unknown'].includes(status.state)) close();
    } catch {
      handlers.onError?.(new Error('malformed conversation status frame'));
      close();
    }
  });
  // Native EventSource reconnects after an interrupted GET. That is safe here:
  // it observes this fixed request id and cannot invoke the creation POST.
  es.onerror = () => { /* transport reconnect is observation-only */ };
  return { close };
}

export interface QueueTaskPayload extends ApiEnvelope {
  /** Address for GET /api/queue/<id> and its one-shot progress stream. */
  id: string;
  queued?: string;
  conversation_link?: {
    conversation_id?: string;
    turn_id?: number;
    dispatch_ref?: string;
    linked: boolean;
    error?: string;
    projection_pending?: boolean;
    projection_retry_queued?: boolean;
    projection?: {
      state?: string;
      event_id?: string;
      outcome_state?: string;
      error?: string;
    };
  };
}

export function queueTask(
  project: string,
  objective: string,
  lane: string,
  conversationId?: string,
  turnId?: number
) {
  // Attribution is an atomic pair. A current backend rejects either half on
  // its own; omitting both also keeps this client safe against an older backend
  // that inferred "latest turn" and could attach a delayed offer to a newer
  // exchange. An unlinked task is safer than a falsely linked one.
  const body: Record<string, unknown> = { project, objective, lane, source: 'agent-os', strategy: 'single' };
  if (conversationId && typeof turnId === 'number' && Number.isSafeInteger(turnId) && turnId > 0) {
    body.conversation_id = conversationId;
    body.turn_id = turnId;
  }
  return request<QueueTaskPayload>('/api/queue', {
    method: 'POST',
    body: JSON.stringify(body)
  });
}

/** The measured fields pushed by GET /api/queue/<id>/events. */
export interface TaskSnapshot {
  id: string;
  found: boolean;
  state: string;
  source: string;
  lane: string | null;
  requested_lane: string | null;
  actual_providers: string[];
  summary: string | null;
  error: string | null;
  applied: boolean | null;
  applied_reason: string | null;
  stalled: boolean;
  timed_out: boolean;
}

function taskSnapshot(value: unknown, expectedId: string): TaskSnapshot {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('malformed task progress frame');
  }
  const row = value as Record<string, unknown>;
  const id = typeof row.id === 'string' && row.id ? row.id : expectedId;
  if (id !== expectedId) throw new Error('task progress id mismatch');
  return {
    id,
    found: row.found === true,
    state: typeof row.state === 'string' && row.state ? row.state : 'unknown',
    source: typeof row.source === 'string' && row.source ? row.source : 'unknown',
    lane: typeof row.lane === 'string' ? row.lane : null,
    requested_lane: typeof row.requested_lane === 'string' ? row.requested_lane : null,
    actual_providers: Array.isArray(row.actual_providers)
      ? row.actual_providers.filter((provider): provider is string => typeof provider === 'string' && Boolean(provider))
      : [],
    summary: typeof row.summary === 'string' && row.summary ? row.summary : null,
    error: typeof row.error === 'string' && row.error ? row.error : null,
    applied: typeof row.applied === 'boolean' ? row.applied : null,
    applied_reason: typeof row.applied_reason === 'string' && row.applied_reason ? row.applied_reason : null,
    stalled: row.stalled === true,
    timed_out: row.timed_out === true
  };
}

/**
 * Follow one queued task until the backend emits `final` or the transport
 * fails. This endpoint is one-shot: leaving EventSource reconnect enabled
 * would replay a completed task forever, so every terminal path shares the
 * same guarded close.
 */
export function streamTask(
  taskId: string,
  handlers: {
    onHello?: (snapshot: TaskSnapshot) => void;
    onProgress?: (snapshot: TaskSnapshot) => void;
    onFinal: (snapshot: TaskSnapshot) => void;
    onError: (error: Error) => void;
  }
): { close: () => void } {
  const es = new EventSource(`/api/queue/${encodeURIComponent(taskId)}/events`);
  let done = false;
  const settle = (fn?: () => void) => {
    if (done) return;
    done = true;
    es.close();
    fn?.();
  };

  const read = (event: Event): TaskSnapshot =>
    taskSnapshot(JSON.parse((event as MessageEvent).data), taskId);

  es.addEventListener('hello', (event) => {
    if (done) return;
    try {
      handlers.onHello?.(read(event));
    } catch {
      settle(() => handlers.onError(new Error('malformed task hello frame')));
    }
  });

  es.addEventListener('progress', (event) => {
    if (done) return;
    try {
      handlers.onProgress?.(read(event));
    } catch {
      settle(() => handlers.onError(new Error('malformed task progress frame')));
    }
  });

  es.addEventListener('final', (event) => {
    let snapshot: TaskSnapshot;
    try {
      snapshot = read(event);
    } catch {
      settle(() => handlers.onError(new Error('malformed task final frame')));
      return;
    }
    settle(() => handlers.onFinal(snapshot));
  });

  es.onerror = () => settle(() => handlers.onError(new Error('task progress stream interrupted')));

  return { close: () => settle() };
}

export function chatIkarus(project: string, message: string, apply = false) {
  return request<IkarusChatPayload>('/api/ikarus/chat', {
    method: 'POST',
    body: JSON.stringify({ project, message, apply })
  }, 60_000);
}

/**
 * General Ikarus brain. `provider` is a runtime `id` (e.g. `ollama_http`,
 * `claude_code_cli`) or `deterministic`; omitted means automatic LLM selection. BYOK —
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
  effort?: EffortLevel,
  conversationId?: string
) {
  const body: Record<string, unknown> = { project, message };
  if (provider) body.provider = provider;
  if (model && model.trim()) body.model = model.trim();
  if (effort) body.effort = effort;
  if (conversationId) body.conversation_id = conversationId;
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
 * Falls back to nothing on its own. A missing `final` does not prove the server
 * did no work: it may have persisted the turn and lost only the last frame.
 * The caller is told via `onError` and must not automatically replay the
 * request without a server-owned idempotency key.
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
  },
  conversationId?: string
): { close: () => void } {
  const qs = new URLSearchParams({ project, message });
  if (provider) qs.set('provider', provider);
  if (model && model.trim()) qs.set('model', model.trim());
  if (effort) qs.set('effort', effort);
  // Passed through to ikarus_os.ask_stream: this is what turns a sequence of
  // one-shot answers into a conversation that survives a reload.
  if (conversationId) qs.set('conversation_id', conversationId);

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

/**
 * A CEILING THAT MATCHES THE MEASUREMENT, NOT THE DEFAULT.
 *
 * This endpoint probes the installed runtimes — it launches each CLI to ask
 * its version — so it is slow by construction, not by accident. Measured on
 * this machine on 2026-08-26: 16.6s with the box under load, 28.0s with the
 * box quiet. Against `request()`'s 20s default that meant the call aborted
 * more often than it answered, and two surfaces silently lost their content:
 * the settings reachability list rendered no rows at all, and the
 * conversation's runtime picker had nothing to offer and fell back to
 * printing a raw id where a name belongs.
 *
 * The backend now CACHES the probe (owner decision 2026-08-27): only the first
 * poll after a TTL window launches the CLIs, the rest are served from the last
 * reading. Each row carries `measured_at`/`measured_age_s`, and the settings
 * reachability list shows the age, so a cached "erreichbar" cannot pass itself
 * off as live for a CLI that broke since. The 45s ceiling STAYS — it is the net
 * for that first cold probe, which is still 12–36s by construction; the cache
 * makes the common case instant, it does not make the cold case fast.
 */
export function getRuntimeStatus() {
  return request<RuntimeStatusPayload>('/api/runtimes/status', undefined, 45_000);
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
  /** which repository this draft was written against; '' for one written
   *  before the store recorded it, which therefore belongs to no project */
  repo_root: string;
}

/**
 * Drafts, scoped to one project — and the answer says which scope it used.
 *
 * The store is a single directory shared by every project. Calling this
 * without a project returns ALL of them, which is what the cockpit used to
 * do: measured on this machine on 2026-08-26, the decision card showed 427
 * pending under `agent_env`, which has none of its own — the count was every
 * project's drafts wearing the selected project's name.
 *
 * `scope` is the repository actually filtered on, or null when the listing
 * spans every project. A surface that shows the count must read it, so an
 * unscoped total can never be presented as one project's own.
 */
export function getDrafts(project?: string) {
  const q = project ? `?project=${encodeURIComponent(project)}` : '';
  return request<ApiEnvelope & { drafts: DraftRow[]; pending_count: number; scope: string | null }>(
    `/api/drafts${q}`
  );
}

/** Full draft content — `daedalus/kairos/drafts.py` `save_draft()`'s stored shape.
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
  /** Per-source detail. Shapes differ per source ON PURPOSE; consumers must
   * preserve `degraded_sources` rather than flattening a failed read to empty. */
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
export function getStructure(
  project: string,
  refresh = false,
  graphNodes?: number | 'all'
): Promise<StructurePayload> {
  const q = new URLSearchParams({ project });
  if (refresh) q.set('refresh', '1');
  if (graphNodes !== undefined) q.set('graph_nodes', String(graphNodes));
  return request<StructurePayload>(`/api/structure?${q.toString()}`, undefined, 70_000);
}

/** Distill a target module/symbol down to a minimal review slice. */
/**
 * What the system would READ to work on an objective — the seed ranking, the
 * terms it derived, whether the latent route was consulted, and the receipt
 * digests. Fast once the index is warm (~0.26s measured), and it had no caller
 * anywhere in this repository until 2026-08-25.
 */
export function getContextPlan(project: string, objective: string): Promise<ContextPlanPayload> {
  const qs = new URLSearchParams({ project, q: objective });
  return request<ContextPlanPayload>(`/api/context/plan?${qs.toString()}`, undefined, 60_000);
}

/**
 * The spectral read of the import graph. Cheap once the index is warm (it
 * reuses the same scoped index as `/api/structure`), and until 2026-08-25 it
 * had no caller anywhere in this repository.
 */
export function getTopology(project: string, refresh = false): Promise<TopologyPayload> {
  const qs = new URLSearchParams({ project });
  if (refresh) qs.set('refresh', '1');
  return request<TopologyPayload>(`/api/topology?${qs.toString()}`, undefined, 120_000);
}

export function distill(project: string, target: string): Promise<DistillPayload> {
  return request<DistillPayload>('/api/distill', {
    method: 'POST',
    body: JSON.stringify({ project, target })
  }, 70_000);
}
