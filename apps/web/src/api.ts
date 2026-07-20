import type { ApiEnvelope, BootstrapPayload, ControlPlanePayload, DashboardPayload, DistillPayload, EffortLevel, HierarchyPayload, IkarusAskPayload, IkarusChatPayload, LiveEventName, ProjectRow, RuntimeStatusPayload, RuntimeTestPayload, StructurePayload } from './types';

async function request<T>(url: string, init?: RequestInit, timeoutMs = 20_000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
      ...init,
      signal: controller.signal
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
      throw new Error(data.error || `Request failed: ${res.status}`);
    }
    return data;
  } catch (error) {
    if (controller.signal.aborted) {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)}s: ${url}`);
    }
    throw error;
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

export function getHierarchy(project: string) {
  return request<HierarchyPayload>(`/api/projects/${encodeURIComponent(project)}/hierarchy`);
}

export function getControlPlane(project: string) {
  return request<ControlPlanePayload>(`/api/projects/${encodeURIComponent(project)}/control-plane`);
}

export function getEnvStatus() {
  return request<ApiEnvelope & { env: Record<string, unknown> }>('/api/env/status');
}

export function getProviderStatus() {
  return request<ApiEnvelope & { providers: Array<Record<string, unknown>> }>('/api/providers/status');
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

export function applyDraft(id: string) {
  return request<ApiEnvelope & { applied: Record<string, unknown> }>(
    `/api/drafts/${encodeURIComponent(id)}/apply`, { method: 'POST', body: '{}' });
}

export function dismissDraft(id: string) {
  return request(`/api/drafts/${encodeURIComponent(id)}/dismiss`, { method: 'POST', body: '{}' });
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
