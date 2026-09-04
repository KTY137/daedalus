import './styles.css';
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Activity,
  AlertTriangle,
  Bot,
  Boxes,
  BrainCircuit,
  Check,
  ChevronRight,
  Cpu,
  FileText,
  GitBranch,
  Inbox,
  KeyRound,
  Library,
  MessageSquare,
  Moon,
  Network,
  Palette,
  Play,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  Sun,
  Terminal,
  Trash2,
  Users,
  Waypoints,
  X,
  Zap
} from 'lucide-react';
import { useTheme } from './hooks/useTheme';
import { useEventSource } from './hooks/useEventSource';
import { ThemeEditor } from './components/ThemeEditor';
import { MissionControl } from './components/MissionControl';
import './views/spaces.css';
import './mission-control.css';
import { GraphSpace } from './views/GraphSpace';
import { KnowledgeSpace } from './views/KnowledgeSpace';
import { useLoop } from './views/useLoop';
import { StateBadge } from './views/StateBadge';
import { coerceState, type HealthState } from './views/health';
import { assessProvider } from './views/health';
import {
  ChatBubble,
  Composer,
  Dock,
  DockGroup,
  DockItem,
  DockSpacer,
  GlassButton,
  GlassCard,
  GlassSheet,
  LiveDot,
  LiveRail,
  RailCard,
  SegmentedControl,
  cx
} from './components/glass';
import {
  applyDraft,
  askIkarus,
  streamIkarus,
  chatIkarus,
  dismissDraft,
  getControlPlane,
  getDashboard,
  getClaudeBootstrap,
  getDraft,
  getDrafts,
  getEnvStatus,
  getHealth,
  getHierarchy,
  getProjects,
  getProviderStatus,
  getRuntimeStatus,
  getStructure,
  isBackendDown,
  queueTask,
  testRuntime,
  updateAutonomy,
  type DraftDetail,
  type DraftRow,
  type EnvStatusPayload,
  type HealthPayload,
  type ProviderStatusRow
} from './api';
import type { AgentProfile, BootstrapPayload, ControlPlanePayload, DashboardPayload, EffortLevel, HierarchyPayload, IkarusAskPayload, IkarusChatPayload, ProjectRow, RuntimeRow, RuntimeTestPayload, StructurePayload } from './types';

/**
 * THREE SPACES. Chat is home.
 *
 *   chat       the assistant is the primary surface — you talk to the OS
 *   graph      the distilled codebase graph: the skeleton of everything
 *   knowledge  what the system has established about itself, and what it has NOT
 *
 * The dock's remaining entries are TOOLS, not spaces: they open as overlay
 * sheets over whichever space you are in, and closing one returns you to it.
 */
type Space = 'chat' | 'graph' | 'knowledge';

type SheetView = 'network' | 'claude' | 'codex' | 'providers' | 'queue' | 'inbox' | 'structure';

// The structure explorer pulls in Sigma, Graphology and a layout worker. Keep
// that WebGL stack off the chat-first startup path and load it only on demand.
const StructureSheet = lazy(() => import('./components/StructureSheet').then((module) => ({ default: module.StructureSheet })));
const NetworkSheet = lazy(() => import('./components/NetworkSheet').then((module) => ({ default: module.NetworkSheet })));

function FeatureFallback({ label }: { label: string }) {
  return (
    <div className="struct-state" role="status" aria-live="polite">
      <RefreshCw size={20} className="spin" />
      <strong>Opening {label}</strong>
      <span>Loading this workspace only when you need it keeps startup fast.</span>
    </div>
  );
}

/** Fast mode is OPT-IN, not the default.
 *
 * The glass surface is the product's identity, not decoration, so new users
 * should see it. Blur was also never the deep cost: the surfaces are already
 * unnested (one frost layer per structural surface, `backdrop-filter: none` on
 * everything repeated), and a static blurred surface rasterizes once and stays
 * cached. The real costs were the 580kB startup bundle and the >20s dashboard
 * request, both addressed directly. Users on weak GPUs can still opt in via the
 * bolt in the topbar, and the choice persists. */
function loadPerformanceMode() {
  try {
    return localStorage.getItem('daedalus-performance') === 'fast';
  } catch {
    return false;
  }
}

function asText(value: unknown, fallback = '') {
  return value == null || value === '' ? fallback : String(value);
}

function Inspector({ profile, control, onAutonomy }: { profile?: AgentProfile; control?: ControlPlanePayload; onAutonomy: (mode: string) => void }) {
  if (!profile) {
    return (
      <section className="panel inspector empty-panel">
        <Network size={22} />
        <h2>Pick an agent profile</h2>
        <p>Open the Agent Network sheet and tap a node to inspect it here.</p>
      </section>
    );
  }
  const autonomyModes = ['manual', 'semi_auto', 'autonomous'];
  return (
    <section className="panel inspector">
      <div className="panel-head">
        <span className={`sync-dot sync-${profile.sync_status}`} />
        <div>
          <h2>{profile.display_name}</h2>
          <p>{profile.name} | {profile.sync_status.replace('_', ' ')}</p>
        </div>
      </div>
      <div className="field-grid">
        <div><label>Category</label><strong>{profile.category_label || 'none'}</strong></div>
        <div><label>Squads</label><strong>{profile.squads.join(', ') || 'none'}</strong></div>
        <div><label>Active</label><strong>{profile.active ? 'yes' : 'no'}</strong></div>
        <div><label>Ownership</label><strong>{profile.ownership.join(', ') || 'none'}</strong></div>
      </div>
      <div className="section-title">Agent autonomy</div>
      <SegmentedControl
        options={autonomyModes}
        value={asText(profile.autonomy.read_files?.project_default)}
        onChange={onAutonomy}
      />
      <div className="section-title">Capabilities</div>
      <div className="cap-list">
        {profile.capabilities.map((cap) => {
          const policy = profile.autonomy[cap] || {};
          const gate = (control?.capability_gates || []).find((g) => g.id === cap);
          return (
            <div key={cap} className="cap-row">
              <span>{asText(gate?.label, cap)}</span>
              <b className={asText(policy.requires_confirmation) === 'true' ? 'needs-confirm' : ''}>{asText(policy.mode, 'manual')}</b>
            </div>
          );
        })}
      </div>
      <div className="section-title">Claude Code</div>
      <pre>{profile.claude ? JSON.stringify(profile.claude, null, 2) : 'No Claude subagent profile yet.'}</pre>
    </section>
  );
}

type ChatMsg = {
  id: number;
  role: 'ik' | 'me';
  text: string;
  system?: boolean;                                            // error / notice styling (still an Ikarus-side bubble)
  brain?: string;                                              // provider_used, surfaced as a subtle caption
  model?: string;                                              // model_used, appended to the brain caption
  stat?: string;                                               // optional stat line (distill / structure / status)
  design?: { message: string; roles: number; subs: number };  // design intent → existing chatIkarus apply path
  enqueue?: { objective: string; lane: string };              // enqueue intent → existing queueTask
  enqueueState?: 'pending' | 'queued' | 'cancelled';
  streaming?: boolean;                                         // live bubble mid-turn; never persisted (see saveTranscript)
  halted?: boolean;                                            // delivery ended without a proven complete final
};

const CHAT_CHIPS = ["What's running?", 'Build me an agent network', 'Route this to Claude', 'Show the mission feed'];

/** Effort segments — cheap-by-default. `low` keeps the interface chatbot snappy. */
const EFFORTS: Array<[EffortLevel, string]> = [['low', 'Low'], ['medium', 'Med'], ['high', 'High']];
const LS_EFFORT = 'daedalus-ikarus-effort';
const LS_MODEL = 'daedalus-ikarus-model';

function loadEffort(): EffortLevel {
  try {
    const v = localStorage.getItem(LS_EFFORT);
    if (v === 'low' || v === 'medium' || v === 'high') return v;
  } catch { /* storage disabled */ }
  return 'low';
}
function loadModel(): string {
  try {
    return localStorage.getItem(LS_MODEL) || '';
  } catch { return ''; }
}

/**
 * Transcript persistence.
 *
 * The transcript survives dock-sheet switching on its own (IkarusPanel is a
 * stable sibling of the sheet and never remounts — measured, 0 remounts across
 * all nine dock views). What it did NOT survive was a page load of any kind:
 * F5, a Tauri webview reload, or Chrome discarding a backgrounded tab under
 * memory pressure all dropped it back to the bare greeting, irrecoverably.
 *
 * sessionStorage rather than localStorage — deliberately. A reload and a
 * discard/restore both keep sessionStorage, which is exactly the loss we are
 * closing, while a NEW tab correctly starts a fresh conversation instead of
 * resurrecting a stale one and growing without bound. `effort`/`model` above
 * are genuine cross-session preferences, so those stay in localStorage.
 */
const SS_TRANSCRIPT = 'daedalus-ikarus-transcript';
/** Only the most recent turns are persisted; the in-memory transcript is never trimmed. */
const TRANSCRIPT_CAP = 200;

const GREETING: ChatMsg = {
  id: 0,
  role: 'ik',
  text:
    'Ikarus here — your Agent OS spine. Ask me to draft an agent network, route a task to a lane, or open any panel from the dock on the left. I propose; you confirm before anything writes. Pick my brain from the selector up top — Deterministic needs no model; a connected runtime gives me a real LLM.'
};

function loadTranscript(): ChatMsg[] {
  try {
    const raw = sessionStorage.getItem(SS_TRANSCRIPT);
    if (!raw) return [GREETING];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length === 0) return [GREETING];
    // Defensive: a bubble should never reach storage mid-stream, but if one ever
    // does, label it rather than let partial text pose as a finished answer.
    return (parsed as ChatMsg[]).map((m) =>
      m.streaming ? { ...m, streaming: false, system: true, text: `${m.text}\n\n(turn interrupted — not completed)` } : m
    );
  } catch { return [GREETING]; }
}

function saveTranscript(messages: ChatMsg[]): void {
  // Never write mid-stream: the effect fires on every delta, so persisting here
  // would rewrite the whole transcript once per token, and a half-arrived answer
  // is worse than no answer (same reason the stream's onError drops the bubble).
  if (messages.some((m) => m.streaming)) return;
  try {
    sessionStorage.setItem(SS_TRANSCRIPT, JSON.stringify(messages.slice(-TRANSCRIPT_CAP)));
  } catch { /* storage disabled or over quota — the live transcript is unaffected */ }
}

/** Friendly label for a `provider_used` id: runtime label if known, else the
 * matching `/api/providers/status` display name (covers brains like DeepSeek
 * that have no runtime-registry row), else the raw id. */
function brainLabel(id: string, runtimes: RuntimeRow[], providerStatus: ProviderStatusRow[] = []): string {
  if (!id) return '';
  if (id === 'deterministic') return 'Deterministic';
  const runtime = runtimes.find((r) => r.id === id)?.label;
  if (runtime) return runtime;
  return providerStatus.find((p) => p.name === id)?.display_name || id;
}

/** Maps a runtime-registry id (daedalus/runtime_registry.py, CLI-first) to the
 * matching provider-status name (daedalus/providers/__init__.py, capability-
 * first) so the two id namespaces can be joined for readiness gating. */
const RUNTIME_TO_PROVIDER: Record<string, string> = {
  claude_code_cli: 'claude_cli',
  codex_cli: 'codex_cli',
  ollama_http: 'ollama',
  ollama_cli: 'ollama'
};

interface BrainOption {
  id: string;
  label: string;
  disabled: boolean;
  reason: string;
}

/**
 * Brain picker options, GATED by real readiness instead of just "is the CLI
 * on PATH" (runtime availability) — a runtime being on PATH is not the same
 * as it being logged in / keyed, and picking a lane that then silently
 * degrades to a different brain is the exact footgun this closes.
 *
 * Also surfaces DeepSeek, which has NO runtime-registry row (registry is
 * CLI-first) but IS a real chat brain once `daedalus/ikarus_os.py` wires it —
 * without this it would be reachable on the backend yet unpickable in the UI.
 */
function brainOptions(runtimes: RuntimeRow[], providerStatus: ProviderStatusRow[]): BrainOption[] {
  const readiness = (name: string) => providerStatus.find((p) => p.name === name);

  const fromRuntimes: BrainOption[] = runtimes
    .filter((r) => r.available)
    .map((r) => {
      const row = readiness(RUNTIME_TO_PROVIDER[r.id] || r.id);
      if (!row) return { id: r.id, label: r.label, disabled: false, reason: '' };
      const disabled = !row.configured || !row.available;
      const reason = !row.configured
        ? `Needs ${row.env_keys.join(', ') || 'setup'}`
        : !row.available
          ? row.last_error || 'Not currently reachable'
          : '';
      return { id: r.id, label: r.label, disabled, reason };
    });

  const deepseek = readiness('deepseek');
  const extra: BrainOption[] = deepseek && !fromRuntimes.some((o) => o.id === 'deepseek')
    ? [{
        id: 'deepseek',
        label: deepseek.display_name || 'DeepSeek',
        disabled: !deepseek.configured || !deepseek.available,
        reason: !deepseek.configured
          ? `Needs ${deepseek.env_keys.join(', ') || 'an API key'}`
          : !deepseek.available
            ? deepseek.last_error || 'Not currently reachable'
            : ''
      }]
    : [];

  return [...fromRuntimes, ...extra];
}

/** Defensively count roles/subagents from the design draft (shape = chatIkarus draft). */
function draftCounts(draft: unknown): { roles: number; subs: number } {
  const d = (draft || {}) as { roles?: unknown[]; subagents?: unknown[] };
  return {
    roles: Array.isArray(d.roles) ? d.roles.length : 0,
    subs: Array.isArray(d.subagents) ? d.subagents.length : 0
  };
}

/** Optional one-line stat surfaced when distill/structure/status data rides along. */
function statLine(payload: IkarusAskPayload): string | undefined {
  if (payload.intent === 'distill' && payload.distill) return 'distill data attached';
  if (payload.structure) return 'structure attached';
  if (payload.intent === 'status' && payload.status) return 'live status attached';
  return undefined;
}

/**
 * The centre chat spine. Promoted from the old right-rail IkarusPanel: a
 * scrolling transcript of ChatBubbles + a Composer.
 *
 * Now routed through the general `askIkarus` brain with a selectable provider,
 * while the network-designer capability (`chatIkarus` + apply) stays intact and
 * is reused for the `design` intent's Apply affordance.
 */
function IkarusPanel({ project, runtimes, providerStatus, onApplied }: { project: string; runtimes: RuntimeRow[]; providerStatus: ProviderStatusRow[]; onApplied: () => void }) {
  const [messages, setMessages] = useState<ChatMsg[]>(loadTranscript);
  const [input, setInput] = useState('Build a clean app-project agent network with Claude, Codex, Ikarus, QA, UI, API and memory roles.');
  const [provider, setProvider] = useState('deterministic');
  const [effort, setEffort] = useState<EffortLevel>(loadEffort);
  const [model, setModel] = useState<string>(loadModel);
  const [busy, setBusy] = useState(false);
  // Non-null while an `askIkarus` call is in flight — drives the thinking bubble.
  const [thinking, setThinking] = useState<{ brain: string } | null>(null);
  // Resume ids ABOVE anything restored from storage — a fresh bubble reusing a
  // restored id would give React two rows with the same key. Only the first
  // render's value is kept, so the scan costs nothing after mount.
  const idRef = useRef(messages.reduce((max, m) => Math.max(max, m.id), 0) + 1);
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, thinking]);

  // Persist the cheap-by-default controls so they survive reloads.
  useEffect(() => { try { localStorage.setItem(LS_EFFORT, effort); } catch { /* noop */ } }, [effort]);
  useEffect(() => { try { localStorage.setItem(LS_MODEL, model); } catch { /* noop */ } }, [model]);
  // …and the transcript itself, so a reload/discard no longer destroys the chat.
  useEffect(() => { saveTranscript(messages); }, [messages]);

  const push = useCallback((msg: Omit<ChatMsg, 'id'>) => {
    // Allocate outside the updater for the same reason openBubble does: React
    // StrictMode may invoke the updater twice, and the id must not depend on
    // how many times it ran.
    const id = idRef.current++;
    setMessages((prev) => [...prev, { ...msg, id }]);
  }, []);

  const updateMsg = useCallback((id: number, patch: Partial<ChatMsg>) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch } : m)));
  }, []);

  /**
   * Render a completed turn. Shared by the streaming and blocking paths.
   *
   * `liveId` is the bubble that already streamed text into view, or null if
   * nothing streamed (deterministic intents emit no deltas). When it exists we
   * PATCH it rather than pushing a second bubble — otherwise the user sees the
   * answer twice.
   */
  const renderResult = useCallback((
    result: IkarusAskPayload, sourceMessage: string, liveId: number | null
  ) => {
    const brain = result.provider_used;
    // The turn is over however it renders below — clear the streaming flag in one
    // place so no branch can leave a bubble marked live and block persistence.
    // (The enqueue/design branches push a NEW bubble and leave `liveId` in place.)
    if (liveId !== null) updateMsg(liveId, { streaming: false });
    if (result.stream_interrupted) {
      // Interrupted text is display-only. Even if a malformed or stale final
      // carries an action shape, never surface Apply/Confirm from an incomplete
      // turn.
      const text = result.assistant || 'The response stream was interrupted before a complete answer arrived.';
      const patch: Partial<ChatMsg> = {
        streaming: false,
        halted: true,
        system: true,
        brain,
        model: result.model_used,
        text,
        stat: 'interrupted - answer incomplete; no action was started'
      };
      if (liveId !== null) updateMsg(liveId, patch);
      else push({
        role: 'ik', text, streaming: false, halted: true, system: true,
        brain, model: result.model_used,
        stat: 'interrupted - answer incomplete; no action was started'
      });
      return;
    }
    if (!result.ok || result.intent === 'error') {
      const text = result.assistant || 'Ikarus could not answer that.';
      if (liveId !== null) updateMsg(liveId, { system: true, brain, text });
      else push({ role: 'ik', system: true, brain, text });
      return;
    }
    if (result.intent === 'enqueue' && result.action?.requires_confirmation) {
      push({
        role: 'ik',
        brain,
        text: result.assistant || 'Queue this task?',
        enqueue: { objective: result.action.args.objective, lane: result.action.args.lane },
        enqueueState: 'pending'
      });
    } else if (result.intent === 'design' && result.draft) {
      push({
        role: 'ik',
        brain,
        text: result.assistant || 'Drafted an agent network.',
        design: { message: sourceMessage, ...draftCounts(result.draft) }
      });
    } else if (liveId !== null) {
      // Streamed. Deltas are the authoritative text; only fall back to the
      // final envelope's copy if nothing actually streamed through.
      const patch: Partial<ChatMsg> = { brain, model: result.model_used, stat: statLine(result) };
      if (result.assistant) patch.text = result.assistant;
      updateMsg(liveId, patch);
    } else {
      push({ role: 'ik', brain, model: result.model_used, text: result.assistant || '…', stat: statLine(result) });
    }
  }, [push, updateMsg]);

  async function send(text: string) {
    const trimmed = text.trim();
    if (!trimmed || busy) return;
    push({ role: 'me', text: trimmed });
    setInput('');
    setBusy(true);
    // Show the thinking bubble immediately with the brain we expect to use.
    setThinking({ brain: provider === 'deterministic' ? 'deterministic' : `via ${brainLabel(provider, runtimes, providerStatus)}` });

    // STREAM FIRST. The endpoint routes identically to /api/ikarus/ask and
    // returns the same `final` envelope, so this is purely a latency win: the
    // Claude CLI has a ~4s startup floor that no amount of backend work removes,
    // and streaming turns that from a blank wait into text appearing.
    // A blocking call is only a capability fallback when EventSource does not
    // exist. Once a stream is attempted, every uncertain outcome is terminal:
    // replaying the same turn could duplicate provider spend or an action.
    const streamHandled = await new Promise<boolean>((resolve) => {
      if (typeof EventSource === 'undefined') { resolve(false); return; }

      let liveId: number | null = null;
      let acc = '';

      const openBubble = () => {
        // Allocate the id OURSELVES rather than via push(): push() increments
        // idRef inside the setMessages updater, which React StrictMode may run
        // twice, and we need a stable handle to patch on every delta.
        const id = idRef.current++;
        setMessages((prev) => [...prev, { id, role: 'ik', text: '', streaming: true }]);
        setThinking(null);          // first token replaces the thinking bubble
        return id;
      };

      let settled = false;
      const finish = (ok: boolean) => { if (!settled) { settled = true; resolve(ok); } };

      const halt = () => {
        if (liveId === null) liveId = openBubble();
        updateMsg(liveId, {
          text: acc || 'The response stream was interrupted before a complete answer arrived.',
          streaming: false,
          halted: true,
          system: true,
          stat: 'interrupted - answer incomplete; not automatically retried'
        });
        finish(true);
      };

      try {
        streamIkarus(project, trimmed, provider, model, effort, {
          onDelta: (chunk) => {
            acc += chunk;
            if (liveId === null) liveId = openBubble();
            updateMsg(liveId, { text: acc });
          },
          onFinal: (result) => {
            renderResult(result, trimmed, liveId);
            finish(true);
          },
          onError: () => {
            halt();
          }
        });
      } catch {
        // A constructor/transport exception cannot prove the GET never reached
        // the server. Preserve the unknown outcome instead of replaying it.
        halt();
      }
    });

    if (streamHandled) {
      setThinking(null);
      setBusy(false);
      return;
    }

    try {
      const result = await askIkarus(project, trimmed, provider, model, effort);
      renderResult(result, trimmed, null);
    } catch (err) {
      push({ role: 'ik', system: true, text: err instanceof Error ? err.message : String(err) });
    } finally {
      setThinking(null);
      setBusy(false);
    }
  }

  // Design intent → the untouched network-designer apply path.
  async function applyDraftMessage(sourceMessage: string) {
    if (busy) return;
    setBusy(true);
    try {
      const result: IkarusChatPayload = await chatIkarus(project, sourceMessage, true);
      push({ role: 'ik', text: result.assistant ? `Applied. ${result.assistant}` : 'Applied the drafted network.' });
      onApplied();
    } catch (err) {
      push({ role: 'ik', system: true, text: err instanceof Error ? `Apply failed: ${err.message}` : String(err) });
    } finally {
      setBusy(false);
    }
  }

  // Enqueue intent → the existing queueTask endpoint (never a new one).
  async function confirmEnqueue(id: number, objective: string, lane: string) {
    if (busy) return;
    setBusy(true);
    try {
      await queueTask(project, objective, lane);
      updateMsg(id, { enqueueState: 'queued' });
      onApplied();
    } catch (err) {
      push({ role: 'ik', system: true, text: err instanceof Error ? `Queue failed: ${err.message}` : String(err) });
    } finally {
      setBusy(false);
    }
  }

  const currentBrain = brainLabel(provider, runtimes, providerStatus);
  // Prefill local model names for the current provider when we know them (Ollama etc.).
  const providerModels = runtimes.find((r) => r.id === provider)?.models || [];
  // Readiness-gated picker options — see brainOptions() for why this is not
  // just `runtimes.filter(available)`.
  const brains = useMemo(() => brainOptions(runtimes, providerStatus), [runtimes, providerStatus]);

  return (
    <section className="spine glass">
      <div className="spine-head">
        <span className="ava"><Sparkles size={16} /></span>
        <div className="spine-title">
          <h2>Ikarus</h2>
          <p>talk to your Agent OS · brain: {currentBrain}</p>
        </div>
        <div className="chat-controls">
          <div className="mini-seg" role="group" aria-label="Reasoning effort" title="higher = longer, more thorough, slower/costlier">
            {EFFORTS.map(([val, lab]) => (
              <button
                key={val}
                type="button"
                className={cx(effort === val && 'active')}
                aria-pressed={effort === val}
                onClick={() => setEffort(val)}
              >
                {lab}
              </button>
            ))}
          </div>
          <input
            className="model-input"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="model"
            aria-label="Model override (blank = provider default)"
            title="Override the model — leave blank for the provider default"
            list="ikarus-model-suggestions"
            spellCheck={false}
          />
          {providerModels.length > 0 && (
            <datalist id="ikarus-model-suggestions">
              {providerModels.map((m) => <option key={m} value={m} />)}
            </datalist>
          )}
          <label className="brain-pick">
            <Cpu size={13} style={{ color: 'var(--accent)' }} />
            <select
              value={provider}
              onChange={(e) => setProvider(e.target.value)}
              aria-label="Ikarus brain / provider"
            >
              <option value="deterministic">Deterministic</option>
              {brains.map((opt) => (
                <option key={opt.id} value={opt.id} disabled={opt.disabled} title={opt.reason || undefined}>
                  {opt.label}{opt.disabled ? ' (not configured)' : ''}
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <div className="transcript" ref={transcriptRef}>
        {messages.map((m) => (
          <ChatBubble key={m.id} role={m.role}>
            {m.system && (
              <small style={{ display: 'block', marginBottom: 4, color: 'var(--muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.04em' }}>system</small>
            )}
            <span>{m.text}</span>
            {m.brain && (
              <small style={{ display: 'block', marginTop: 6, color: 'var(--dim)', fontSize: 11 }}>
                brain: {brainLabel(m.brain, runtimes, providerStatus)}{m.model ? ` · ${m.model}` : ''}
              </small>
            )}
            {m.stat && (
              <small style={{ display: 'block', marginTop: 4, color: 'var(--muted)', fontSize: 11 }}>{m.stat}</small>
            )}
            {m.halted && (
              <small style={{ display: 'block', marginTop: 4, color: 'var(--warn)', fontSize: 11 }}>halted</small>
            )}

            {m.design && (
              <GlassCard className="msg-draft">
                <span className="obj">Drafted agent network</span>
                <div className="meta">
                  <span className="lane">{m.design.roles} Daedalus roles</span>
                  <span className="lane">{m.design.subs} Claude subagents</span>
                </div>
                <div className="confirm-row">
                  <GlassButton primary disabled={busy} onClick={() => applyDraftMessage(m.design!.message)}>
                    <Check size={14} /> Apply draft
                  </GlassButton>
                </div>
              </GlassCard>
            )}

            {m.enqueue && (
              <GlassCard className="msg-draft">
                <span className="obj">Queue task</span>
                <div className="meta">
                  <span className="lane">{m.enqueue.lane}</span>
                  <span className="lane">{m.enqueue.objective}</span>
                </div>
                {m.enqueueState === 'pending' && (
                  <div className="confirm-row">
                    <GlassButton primary disabled={busy} onClick={() => confirmEnqueue(m.id, m.enqueue!.objective, m.enqueue!.lane)}>
                      <Check size={14} /> Confirm
                    </GlassButton>
                    <GlassButton disabled={busy} onClick={() => updateMsg(m.id, { enqueueState: 'cancelled' })}>
                      <X size={14} /> Cancel
                    </GlassButton>
                  </div>
                )}
                {m.enqueueState === 'queued' && (
                  <span className="lane" style={{ color: 'var(--good)' }}><Check size={12} /> queued</span>
                )}
                {m.enqueueState === 'cancelled' && <span className="lane">cancelled</span>}
              </GlassCard>
            )}
          </ChatBubble>
        ))}
        {thinking && (
          <ChatBubble role="ik">
            <div className="thinking-row" aria-live="polite">
              <span className="dots" aria-hidden="true"><i /><i /><i /></span>
              <span>Ikarus is thinking…</span>
            </div>
            <small className="thinking-sub">{thinking.brain}</small>
          </ChatBubble>
        )}
      </div>
      <Composer
        value={input}
        onChange={setInput}
        onSend={() => send(input)}
        busy={busy}
        chips={CHAT_CHIPS}
        onChip={(chip) => setInput(chip)}
      />
    </section>
  );
}

/** Best-effort diff-line coloring for free-form proposal text. The backend has
 * no structured unified-diff endpoint — `report.handoff` is whatever free-form
 * text/object the provider returned (see providers/_report.py) — so this only
 * upgrades rendering WHEN the text already looks diff-shaped (+/-/@@ prefixed
 * lines); plain text still renders, just unstyled. */
function DraftProposalText({ text }: { text: string }) {
  return (
    <pre
      style={{
        whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 320, overflowY: 'auto',
        fontSize: 12, lineHeight: 1.6, margin: 0, padding: 10,
        background: 'var(--glass-thin)', border: '1px solid var(--edge-soft)', borderRadius: 'var(--r-md)'
      }}
    >
      {text.split('\n').map((line, i) => {
        const color = /^\+(?!\+\+)/.test(line) ? 'var(--good)'
          : /^-(?!--)/.test(line) ? 'var(--bad)'
          : /^@@/.test(line) ? 'var(--warn)'
          : undefined;
        return <div key={i} style={{ color }}>{line || ' '}</div>;
      })}
    </pre>
  );
}

/** `report.handoff` is a free-form object (provider-specific keys like `notes`
 * or `suggestion`); render every entry rather than guessing one canonical key. */
function DraftHandoff({ handoff }: { handoff: Record<string, unknown> }) {
  const entries = Object.entries(handoff || {});
  if (entries.length === 0) {
    return <p style={{ color: 'var(--muted)', fontSize: 12 }}>No proposed content in this draft's handoff.</p>;
  }
  return (
    <>
      {entries.map(([key, value]) => (
        <div key={key} style={{ marginBottom: 10 }}>
          <small style={{ display: 'block', marginBottom: 4, color: 'var(--muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.04em' }}>
            {key}
          </small>
          {typeof value === 'string'
            ? <DraftProposalText text={value} />
            : <pre style={{ margin: 0, fontSize: 12, maxHeight: 240, overflowY: 'auto' }}>{JSON.stringify(value, null, 2)}</pre>}
        </div>
      ))}
    </>
  );
}

/**
 * Draft inbox + review-before-apply. Applying a draft you have not read is
 * the footgun: Apply is no longer reachable straight from the compact row —
 * "Review" fetches the FULL draft (`getDraft`) and only the detail panel it
 * opens carries the Apply button. Dismiss stays on the row: it is not
 * destructive/spendy (it never hands anything to a write-capable lane), so
 * forcing a read first would only add friction without closing a footgun.
 */
function InboxTray({ drafts, onChange }: { drafts: DraftRow[]; onChange: () => void }) {
  const [busy, setBusy] = useState('');
  const [applied, setApplied] = useState<Record<string, unknown> | undefined>();
  const [selectedId, setSelectedId] = useState('');
  const [detail, setDetail] = useState<DraftDetail | undefined>();
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState('');
  const pending = drafts.filter((d) => d.status === 'pending');

  async function review(id: string) {
    setSelectedId(id);
    setDetail(undefined);
    setDetailError('');
    setDetailLoading(true);
    try {
      const res = await getDraft(id);
      setDetail(res.draft);
    } catch (err) {
      setDetailError(err instanceof Error ? err.message : String(err));
    } finally {
      setDetailLoading(false);
    }
  }

  function closeReview() {
    setSelectedId('');
    setDetail(undefined);
    setDetailError('');
  }

  async function act(id: string, verb: 'apply' | 'dismiss') {
    setBusy(id);
    try {
      if (verb === 'apply') {
        const res = await applyDraft(id);
        setApplied(res.applied);
      } else {
        await dismissDraft(id);
      }
      if (selectedId === id) closeReview();
      onChange();
    } finally {
      setBusy('');
    }
  }

  return (
    <section className="panel feature-panel">
      <div className="panel-head"><Inbox size={18} /><div>
        <h2>Draft Inbox</h2>
        <p>Advisory proposals from the free bench. A free model may propose — never merge. Review a draft before applying; applying hands the review packet to the trusted (Claude) lane.</p>
      </div></div>
      {pending.length === 0 && <div className="feed-row"><span>No pending drafts. Advisory offloads land here.</span></div>}
      <div className="feed-list">
        {pending.map((d) => (
          <div className="feed-row draft-row" key={d.id}>
            <div className="draft-main">
              <b>{d.agent || 'bench'}</b>
              <span>{d.objective}</span>
              <small>{(d.paths || []).join(', ') || 'no paths'} · {d.created}</small>
            </div>
            <div className="draft-actions">
              <button className="primary" disabled={busy === d.id} onClick={() => review(d.id)}><FileText size={13} /> Review</button>
              <button disabled={busy === d.id} onClick={() => act(d.id, 'dismiss')}><Trash2 size={13} /> Dismiss</button>
            </div>
          </div>
        ))}
      </div>

      {selectedId && (
        <div className="bootstrap-box">
          <div className="panel-head compact">
            <MessageSquare size={16} />
            <div><h2>Review before applying</h2><p>Nothing is written yet — Apply hands this packet to the trusted (Claude) lane.</p></div>
          </div>
          {detailLoading && <div className="feed-row"><span>Loading draft…</span></div>}
          {detailError && <div className="feed-row"><span style={{ color: 'var(--bad)' }}>{detailError}</span></div>}
          {detail && (
            <>
              <div className="field-grid">
                <div><label>Agent</label><strong>{detail.agent || 'bench'}</strong></div>
                <div><label>Provider</label><strong>{detail.provider || 'unknown'}</strong></div>
                <div><label>Status</label><strong>{detail.report?.status || 'needs_review'}</strong></div>
                <div><label>Paths</label><strong>{(detail.paths || []).join(', ') || 'none'}</strong></div>
              </div>
              <p><b>Objective:</b> {detail.objective}</p>
              <p>{detail.report?.summary || 'No summary provided.'}</p>
              {(detail.report?.files_changed?.length ?? 0) > 0 && (
                <p><b>Files:</b> {detail.report.files_changed.join(', ')}</p>
              )}
              {(detail.report?.risks?.length ?? 0) > 0 && (
                <div>
                  <small style={{ color: 'var(--warn)' }}>Risks</small>
                  <ul>{detail.report.risks.map((r, i) => <li key={i}>{r}</li>)}</ul>
                </div>
              )}
              {(detail.report?.todos?.length ?? 0) > 0 && (
                <div>
                  <small>Todos</small>
                  <ul>{detail.report.todos.map((t, i) => <li key={i}>{t}</li>)}</ul>
                </div>
              )}
              <div className="section-title">Proposed change</div>
              <DraftHandoff handoff={detail.report?.handoff || {}} />
              <div className="confirm-row">
                <GlassButton primary disabled={busy === selectedId} onClick={() => act(selectedId, 'apply')}>
                  <Check size={14} /> Apply
                </GlassButton>
                <GlassButton disabled={busy === selectedId} onClick={closeReview}>
                  <X size={14} /> Close
                </GlassButton>
              </div>
            </>
          )}
        </div>
      )}

      {applied && (
        <div className="bootstrap-box">
          <div className="panel-head compact"><MessageSquare size={16} /><div><h2>Review packet</h2><p>Hand this to the Claude lane to actually apply the change.</p></div></div>
          <pre>{JSON.stringify(applied, null, 2)}</pre>
        </div>
      )}
    </section>
  );
}

function RuntimeCenter({
  runtimes,
  providers,
  providerError,
  providerLoadedAt
}: {
  runtimes: RuntimeRow[];
  providers: ProviderStatusRow[];
  providerError: string;
  providerLoadedAt: number | null;
}) {
  const [tests, setTests] = useState<Record<string, RuntimeTestPayload['test']>>({});
  const [busy, setBusy] = useState('');

  async function runTest(id: string) {
    setBusy(id);
    try {
      const result = await testRuntime(id);
      setTests((prev) => ({ ...prev, [id]: result.test }));
    } finally {
      setBusy('');
    }
  }

  return (
    <section className="panel feature-panel">
      <div className="panel-head">
        <KeyRound size={18} />
        <div><h2>Provider truth table</h2><p>Configuration is declared. Reachability is sampled. Neither proves that a model call succeeded.</p></div>
      </div>
      <div className="provider-truth">
        <div className="provider-truth-head">
          <span>provider</span><span>configuration</span><span>reachability</span><span>verdict</span>
        </div>
        {providerError && (
          <div className="provider-sample-error" role="status">
            <StateBadge state="unknown" compact />
            <span>{providerError} Cached rows below are stale evidence, not current availability.</span>
          </div>
        )}
        {providers.map((provider) => {
          const state: HealthState = providerError
            ? 'unknown'
            : !provider.implemented || !provider.configured
              ? 'absent'
              : !provider.available
                ? 'degraded'
                : 'present';
          return (
            <div className="provider-truth-row" key={provider.name}>
              <span><b>{provider.display_name}</b><small>{provider.name}</small></span>
              <span>{provider.configured ? 'configured' : provider.requires_key ? 'key missing' : 'not configured'}</span>
              <span>{providerError ? 'unknown' : provider.available ? 'answered probe' : provider.last_error || 'did not answer'}</span>
              <StateBadge state={state} compact />
            </div>
          );
        })}
        {providers.length === 0 && (
          <div className="provider-sample-error">
            <StateBadge state="unknown" compact />
            <span>No provider rows were returned. Availability is unknown.</span>
          </div>
        )}
        <p className="provider-sampled">
          {providerLoadedAt
            ? `sampled ${new Date(providerLoadedAt).toLocaleTimeString()}`
            : 'not sampled in this session'}
        </p>
      </div>
      <div className="section-title"><h3>Runtime adapters</h3><p>Executable paths and manual connection probes.</p></div>
      <div className="runtime-table">
        {runtimes.map((runtime) => (
          <div className="runtime-row" key={runtime.id}>
            <div>
              <strong>{runtime.label}</strong>
              <small>{runtime.id} | {runtime.mode} | {runtime.auth_status}</small>
              <p>{runtime.notes}</p>
            </div>
            <div className="runtime-detail">
              <span className={runtime.available ? 'ok' : 'warn'}>{runtime.available ? 'available' : 'unavailable'}</span>
              <code>{runtime.command_path || runtime.endpoint || 'no path'}</code>
              <small>{runtime.version || runtime.last_error || runtime.selected_model}</small>
            </div>
            <button onClick={() => runTest(runtime.id)} disabled={busy === runtime.id}>{busy === runtime.id ? 'Testing...' : 'Test'}</button>
            {tests[runtime.id] && (
              <div className={`test-result ${tests[runtime.id].ok ? 'ok' : 'warn'}`}>
                {tests[runtime.id].ok ? 'OK' : 'Check failed'}: {tests[runtime.id].detail}
              </div>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

const SPACES: Array<{ key: Space; label: string; icon: ReactNode }> = [
  { key: 'chat', label: 'Chat · home', icon: <MessageSquare size={20} /> },
  { key: 'graph', label: 'Graph · the skeleton', icon: <Waypoints size={20} /> },
  { key: 'knowledge', label: 'Knowledge · what is established', icon: <Library size={20} /> }
];

const DOCK_VIEWS: Array<{ key: SheetView; label: string; icon: ReactNode }> = [
  { key: 'network', label: 'Agent Network', icon: <Network size={20} /> },
  { key: 'structure', label: 'Structure', icon: <Boxes size={20} /> },
  { key: 'queue', label: 'Mission Feed', icon: <GitBranch size={20} /> },
  { key: 'providers', label: 'Connections', icon: <KeyRound size={20} /> },
  { key: 'inbox', label: 'Draft Inbox', icon: <Inbox size={20} /> },
  { key: 'claude', label: 'Claude Code', icon: <BrainCircuit size={20} /> },
  { key: 'codex', label: 'Codex', icon: <Terminal size={20} /> }
];

const SHEET_META: Record<SheetView, { title: string; subtitle: string }> = {
  network: { title: 'Agent Network', subtitle: 'A useful map, not the whole product — talk to Ikarus to change it.' },
  structure: { title: 'Structure', subtitle: 'Code-health across languages: hotspots, duplication and distillation.' },
  queue: { title: 'Mission Feed', subtitle: 'Every runtime talks through the queue, reports and memory.' },
  providers: { title: 'Connections', subtitle: 'CLI-first, BYOK. The platform never holds your paid key.' },
  inbox: { title: 'Draft Inbox', subtitle: 'Advisory proposals from the free bench — it proposes, never merges.' },
  claude: { title: 'Claude Code Control', subtitle: 'Subagents, permissions, MCP, hooks and runtime features.' },
  codex: { title: 'Codex Runtime', subtitle: 'Codex participates through AGENTS.md and the Daedalus file bus.' }
};

export default function App() {
  const queryProject = new URLSearchParams(location.search).get('project') || '';
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [project, setProject] = useState(queryProject);
  const [dashboard, setDashboard] = useState<DashboardPayload | undefined>();
  const [hierarchy, setHierarchy] = useState<HierarchyPayload | undefined>();
  const [control, setControl] = useState<ControlPlanePayload | undefined>();
  const [runtimes, setRuntimes] = useState<RuntimeRow[]>([]);
  const [envStatus, setEnvStatus] = useState<EnvStatusPayload | undefined>();
  const [providerStatus, setProviderStatus] = useState<ProviderStatusRow[]>([]);
  const [providerStatusError, setProviderStatusError] = useState('');
  const [providerStatusLoadedAt, setProviderStatusLoadedAt] = useState<number | null>(null);
  const [health, setHealth] = useState<HealthPayload | undefined>();
  const [healthError, setHealthError] = useState('');
  const [healthLoadedAt, setHealthLoadedAt] = useState<number | null>(null);
  const [dashboardLoadedAt, setDashboardLoadedAt] = useState<number | null>(null);
  const [bootstrap, setBootstrap] = useState<BootstrapPayload | undefined>();
  const [selectedName, setSelectedName] = useState('');
  // Chat is the home surface: the app opens into the assistant, never into a
  // dashboard.
  const [space, setSpace] = useState<Space>('chat');
  const [view, setView] = useState<SheetView>('network');
  const [sheetOpen, setSheetOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [drafts, setDrafts] = useState<DraftRow[]>([]);
  const [objective, setObjective] = useState('');
  const [lane, setLane] = useState('local_only');
  const [error, setError] = useState('');
  /** Set only when NOTHING answered on the loopback port. A dead backend is a
   * different fact from a slow one or a refusing one, and it gets its own
   * banner with the command that fixes it — never an endless spinner. */
  const [offline, setOffline] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [fastMode, setFastMode] = useState(loadPerformanceMode);
  // Lightweight live counters pushed by the SSE stream — updated instantly on
  // events so badges/dots react without waiting for a full dashboard fetch.
  const [live, setLive] = useState<{ queueDepth?: number; inFlight?: number; watcherState?: string; unread?: number }>({});
  const [loopSignal, setLoopSignal] = useState(0);
  const [structure, setStructure] = useState<StructurePayload | undefined>();
  const [structureLoading, setStructureLoading] = useState(false);
  const [structureError, setStructureError] = useState('');
  const structureFetchedFor = useRef('');
  const [hierarchyLoading, setHierarchyLoading] = useState(false);
  const [hierarchyError, setHierarchyError] = useState('');
  const hierarchyFetchedFor = useRef('');
  const refreshSerial = useRef(0);
  const initialRefreshStarted = useRef(false);
  const { theme, toggle: toggleTheme } = useTheme();

  const selectedProfile = useMemo(
    () => (control?.profiles || []).find((p) => p.name === selectedName) || control?.profiles?.[0],
    [control, selectedName]
  );

  const refresh = useCallback(async (nextProject = project) => {
    const serial = ++refreshSerial.current;
    setError('');
    setProviderStatusError('');
    setHealthError('');
    setRefreshing(true);
    try {
      const projectPayload = await getProjects();
      if (serial !== refreshSerial.current) return;
      setOffline(false);
      setProjects(projectPayload.projects);
      const chosen = nextProject || queryProject || projectPayload.projects[0]?.name || '';
      if (!chosen) return;
      setProject(chosen);

      // Each surface commits as soon as it arrives. One slow dashboard scan
      // must not blank the agent graph, runtime controls or project picker.
      const tasks = [
        getDashboard(chosen).then((payload) => {
          if (serial === refreshSerial.current) {
            setDashboard(payload);
            setDashboardLoadedAt(Date.now());
          }
        }),
        getControlPlane(chosen).then((plane) => {
          if (serial !== refreshSerial.current) return;
          setControl(plane);
          setSelectedName((current) => (
            current && plane.profiles.some((profile) => profile.name === current)
              ? current
              : plane.profiles[0]?.name || ''
          ));
        }),
        getRuntimeStatus().then((payload) => {
          if (serial === refreshSerial.current) setRuntimes(payload.runtimes);
        }),
        getEnvStatus().then((payload) => {
          if (serial === refreshSerial.current) setEnvStatus(payload.env);
        }),
        getProviderStatus().then((payload) => {
          if (serial === refreshSerial.current) {
            setProviderStatus(payload.providers || []);
            setProviderStatusLoadedAt(Date.now());
            setProviderStatusError('');
          }
        }).catch((err) => {
          if (serial === refreshSerial.current) {
            setProviderStatusError(err instanceof Error ? err.message : String(err));
          }
          throw err;
        }),
        getHealth().then((payload) => {
          if (serial === refreshSerial.current) {
            setHealth(payload);
            setHealthLoadedAt(Date.now());
            setHealthError('');
          }
        }).catch((err) => {
          if (serial === refreshSerial.current) {
            setHealthError(err instanceof Error ? err.message : String(err));
          }
          throw err;
        }),
        getClaudeBootstrap(chosen).then((payload) => {
          if (serial === refreshSerial.current) setBootstrap(payload);
        }),
        getDrafts().then((payload) => {
          if (serial === refreshSerial.current) setDrafts(payload.drafts || []);
        })
      ];

      const results = await Promise.allSettled(tasks);
      if (serial !== refreshSerial.current) return;
      const failures = results.filter((result): result is PromiseRejectedResult => result.status === 'rejected');
      if (failures.length > 0) {
        const first = failures[0].reason instanceof Error ? failures[0].reason.message : String(failures[0].reason);
        // Naming the count matters: "some panels are stale" and "everything is
        // fine" look identical once the stale panels keep rendering old data.
        setError(`${failures.length} data source${failures.length === 1 ? '' : 's'} did not respond — the panels they feed are showing nothing, not "nothing to show". ${first}`);
      }
    } catch (err) {
      if (serial !== refreshSerial.current) return;
      setOffline(isBackendDown(err));
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (serial === refreshSerial.current) setRefreshing(false);
    }
  }, [project, queryProject]);

  useEffect(() => {
    // React StrictMode intentionally replays effects in development. Guard the
    // expensive bootstrap so local UI work does not launch every API scan twice.
    if (initialRefreshStarted.current) return;
    initialRefreshStarted.current = true;
    refresh();
  }, [refresh]);

  // Provider availability is a sampled measurement, not a startup constant.
  // The main SSE channel does not carry provider changes, so keep this one
  // cheap endpoint warm and label its age in Mission Control. A failed refresh
  // leaves the prior rows visible as stale evidence but flips their state to
  // UNKNOWN instead of allowing cached reachability to pose as live.
  useEffect(() => {
    let active = true;
    const sample = () => {
      getProviderStatus().then((payload) => {
        if (!active) return;
        setProviderStatus(payload.providers || []);
        setProviderStatusLoadedAt(Date.now());
        setProviderStatusError('');
      }).catch((err) => {
        if (active) setProviderStatusError(err instanceof Error ? err.message : String(err));
      });
    };
    const timer = window.setInterval(sample, 20_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  // The backend's health glance is read-only and keeps expensive/remote probes
  // disabled by default. It changes independently of the task event stream
  // (heartbeats, receipts and ledgers age), so sample it at a slower cadence.
  useEffect(() => {
    let active = true;
    const sample = () => {
      getHealth().then((payload) => {
        if (!active) return;
        setHealth(payload);
        setHealthLoadedAt(Date.now());
        setHealthError('');
      }).catch((err) => {
        if (active) setHealthError(err instanceof Error ? err.message : String(err));
      });
    };
    const timer = window.setInterval(sample, 60_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.performance = fastMode ? 'fast' : 'quality';
    try {
      localStorage.setItem('daedalus-performance', fastMode ? 'fast' : 'quality');
    } catch { /* storage disabled */ }
  }, [fastMode]);

  // Live stream (Era-3): the SSE feed replaces the always-on dashboard poll.
  // Events update the lightweight `live` counters instantly, and we only re-
  // fetch the full dashboard when an event says the queue/reports changed —
  // never on a fixed interval.
  const { status: liveStatus } = useEventSource(project, {
    onHello: (d) => {
      setLive({ queueDepth: d.queue_depth, inFlight: d.in_flight, watcherState: d.watcher_state, unread: d.unread_count });
    },
    onHeartbeat: (d) => {
      setLive((prev) => ({ ...prev, watcherState: d.watcher_state, inFlight: d.in_flight }));
    },
    onQueue: (d) => {
      setLive((prev) => ({ ...prev, queueDepth: d.queue_depth }));
      // A queue change is a real "something changed" signal → refresh the feed.
      if (project) getDashboard(project).then((payload) => {
        setDashboard(payload);
        setDashboardLoadedAt(Date.now());
      }).catch(() => undefined);
    },
    onReport: () => {
      // A task finished → pull the fresh reports/feed once.
      setLoopSignal((value) => value + 1);
      if (project) getDashboard(project).then((payload) => {
        setDashboard(payload);
        setDashboardLoadedAt(Date.now());
      }).catch(() => undefined);
    }
  });

  // Degraded fallback: only while the stream is NOT live do we poll the
  // dashboard on an interval (keeps the mission feed fresh when SSE is down).
  useEffect(() => {
    if (!project || liveStatus === 'live') return;
    const timer = setInterval(() => {
      getDashboard(project).then((payload) => {
        setDashboard(payload);
        setDashboardLoadedAt(Date.now());
      }).catch(() => undefined);
    }, 5000);
    return () => clearInterval(timer);
  }, [project, liveStatus]);

  // Structure (code-health) index. The first scan of a big repo can take up to
  // ~60s, so we lazy-load it when the Structure sheet opens and only re-fetch on
  // a project change or an explicit refresh — never on every open.
  const loadStructure = useCallback(async (refreshIndex = false) => {
    if (!project) return;
    structureFetchedFor.current = project;
    setStructureLoading(true);
    setStructureError('');
    try {
      const payload = await getStructure(project, refreshIndex);
      setStructure(payload);
    } catch (err) {
      setStructure(undefined);
      setStructureError(err instanceof Error ? err.message : String(err));
    } finally {
      setStructureLoading(false);
    }
  }, [project]);

  // The Structure sheet and the Graph space read the SAME `/api/structure`
  // payload (the graph consumes `structure.graph`), so opening either one
  // warms the index for both — we never pay for that scan twice.
  useEffect(() => {
    if (!project) return;
    const wantsStructure = space === 'graph' || (sheetOpen && view === 'structure');
    if (!wantsStructure) return;
    if (structureFetchedFor.current === project) return;
    loadStructure(false);
  }, [sheetOpen, view, space, project, loadStructure]);

  /**
   * The self-improvement loop's three read-only surfaces.
   *
   * Fetched immediately rather than lazily on the Knowledge tab, for one
   * reason: `degraded_sources` has to be visible from the CHAT home surface. A
   * source that failed while you were talking to Ikarus is exactly the fact
   * that must not wait for you to go looking for it.
   *
   * UNCONDITIONALLY enabled, including before a project resolves. All three
   * endpoints default to this checkout, and gating on `project` had a measured
   * failure mode: with the API down, `getProjects()` fails, no project ever
   * resolves, the loop is never CALLED — and "not called" rendered as
   * `present` ("the endpoint exists and nothing ran it"), which is a far
   * gentler claim than the truth. Calling it always means a dead API reports
   * `unknown` with "start the backend", which is what actually happened.
   */
  const loop = useLoop(project, true);

  // The generic event stream cannot carry loop iteration detail, but a report
  // event is still a trustworthy invalidation signal. Re-read the loop's
  // read-only queue/history/map surfaces once for each completed task.
  useEffect(() => {
    if (loopSignal === 0) return;
    loop.reload();
  }, [loopSignal, loop.reload]);

  const loadHierarchy = useCallback(async (force = false) => {
    if (!project || (!force && hierarchyFetchedFor.current === project)) return;
    hierarchyFetchedFor.current = project;
    setHierarchyLoading(true);
    setHierarchyError('');
    try {
      setHierarchy(await getHierarchy(project));
    } catch (err) {
      setHierarchyError(err instanceof Error ? err.message : String(err));
      if (!hierarchy) hierarchyFetchedFor.current = '';
    } finally {
      setHierarchyLoading(false);
    }
  }, [hierarchy, project]);

  useEffect(() => {
    if (sheetOpen && view === 'network') loadHierarchy(false);
  }, [sheetOpen, view, loadHierarchy]);

  // Fast keyboard escape hatch for sheets/theme controls, plus the standard
  // chat shortcut. Ignore Ctrl+K while already typing so normal editing wins.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setSheetOpen(false);
        setEditorOpen(false);
        return;
      }
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        const target = event.target as HTMLElement | null;
        if (target?.matches('input, textarea, select, [contenteditable="true"]')) return;
        event.preventDefault();
        // Ctrl+K is "take me to the assistant" — it must cross a space
        // boundary, not just close a sheet, now that chat is one of three.
        setSheetOpen(false);
        setSpace('chat');
        requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>('[data-ikarus-composer]')?.focus());
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const selectedProject = projects.find((p) => p.name === project);

  async function submitTask() {
    if (!objective.trim()) return;
    await queueTask(project, objective.trim(), lane);
    setObjective('');
    refresh(project);
  }

  async function setAgentAutonomy(mode: string) {
    if (!selectedProfile || !control) return;
    const agents = { ...((control.autonomy.agents as Record<string, string>) || {}), [selectedProfile.name]: mode };
    const updated = await updateAutonomy(project, { agents });
    setControl(updated);
  }

  const queue = dashboard?.queue as any;
  const draftPending = drafts.filter((d) => d.status === 'pending').length;
  const queuePending = ((queue?.pending || []) as unknown[]).length;
  const reportCount = ((queue?.reports || []) as unknown[]).length;
  // Prefer instant SSE counters; fall back to the last dashboard snapshot.
  const inFlight = typeof live.inFlight === 'number' && Number.isFinite(live.inFlight) ? live.inFlight : queuePending;
  const queueDepth = typeof live.queueDepth === 'number' && Number.isFinite(live.queueDepth) ? live.queueDepth : queuePending;
  const streamLive = liveStatus === 'live';

  // BYOK readiness badge (Connections/env.py `env_status().providers`). This
  // is the invariant the flagship BYOK promise depends on — a user who cannot
  // see whether a key is configured cannot trust that a paid brain will work
  // (or that a free one didn't just silently take over). `ollama` needs no
  // key so it always reads configured=true; the count is still meaningful as
  // a per-provider readiness rollup, and the tooltip spells out every row.
  const envProviders = Object.entries(envStatus?.providers || {});
  const byokConfigured = envProviders.filter(([, info]) => info.configured).length;
  const byokTitle = envProviders.length > 0
    ? envProviders.map(([name, info]) => `${name}: ${info.configured ? 'configured' : 'not configured'}`).join('\n')
    : 'Loading provider readiness…';

  function openSheet(next: SheetView) {
    setView(next);
    setSheetOpen(true);
  }

  function closeSheet() {
    setSheetOpen(false);
  }

  /** Switching space always closes any tool sheet: a sheet is an overlay ON a
   * space, so leaving it open across a switch would hide the space you asked
   * for behind the tool you were done with. */
  function goSpace(next: Space) {
    setSpace(next);
    setSheetOpen(false);
  }

  /* ---- the loop, summarised for the top bar ----
     `degraded_sources` is the one fact that must be reachable from every
     space, including the chat home surface. It is rendered with the same five
     state words as everything else: a failed source is DEGRADED, an
     unreachable API is UNKNOWN (we learned nothing), and only a queue whose
     sources all answered is allowed to be green. */
  const loopBlock = loop.queue.data?.queue;
  const loopDegraded = loopBlock?.degraded_sources || [];
  const loopState = loop.queue.error
    ? (loop.queue.error.kind === 'notfound' ? 'absent' as const
      : loop.queue.error.kind === 'app' || loop.queue.error.kind === 'http' ? 'degraded' as const
        : 'unknown' as const)
    : loop.queue.loading && !loopBlock
      ? 'unknown' as const
      : !loopBlock
        ? 'present' as const
        : loopDegraded.length > 0
          ? 'degraded' as const
          : 'working' as const;
  const loopChipText = loop.queue.error
    ? 'loop unread'
    : !loopBlock
      ? 'loop …'
      : loopDegraded.length > 0
        ? `${loopDegraded.length} source${loopDegraded.length === 1 ? '' : 's'} failed`
        : `${loopBlock.n_candidates} queued`;
  const loopChipTitle = loop.queue.error
    ? `The work queue could not be read: ${loop.queue.error.message}\nThis says nothing about whether there is work.`
    : loopDegraded.length > 0
      ? `INCOMPLETE — these sources could not be consulted:\n${loopDegraded.join('\n')}\n\nA short or empty queue is NOT evidence that there is no work.`
      : loopBlock
        ? 'Every picker source answered. The queue is complete as far as the sources go.'
        : 'The work queue has not been read yet.';

  /* ---- may this system promote anything right now, and why not? ----
     The single question an operator most needs answered, and until now it was
     answerable from no surface at all: the discrimination gate, the installed
     self-policy's write confinement and the operability drill all existed and
     none of them were rendered anywhere.

     Read off `dashboard.governance`, which the backend computes in ONE place
     (`core.get_governance`) so this chip cannot become a second, cheerier
     opinion than the shadow runner's. An ABSENT payload is `unknown`, never
     green: an older backend that does not serve the block has told us nothing
     about whether promotion is safe, and "we did not ask" must not render the
     same as "we asked and it was fine". */
  const governance = dashboard?.governance;
  // coerceState, not a cast: an unrecognised state word from a newer backend
  // must land on `unknown`, not be waved through as whatever it claims to be.
  const govState: HealthState = governance ? coerceState(governance.state) : 'unknown';
  const govChipText = !governance
    ? 'promotion unknown'
    : governance.promotion_allowed
      ? 'promotion allowed'
      : 'promotion refused';
  const govChipTitle = !governance
    ? 'This backend did not report a governance verdict, so whether promotion is '
      + 'allowed is UNKNOWN. Treat that as unproven, not as permission.'
    : [
      governance.verdict,
      '',
      ...(governance.gates || []).map(
        g => `${g.state.toUpperCase()} [${g.provenance}] ${g.id}: ${g.headline}`
      ),
      '',
      governance.head ? `HEAD ${governance.head.slice(0, 12)}` : 'HEAD unknown'
    ].join('\n');

  function renderSheet(target: SheetView) {
    if (target === 'network') {
      return (
        <Suspense fallback={<FeatureFallback label="Agent Network" />}>
          <NetworkSheet
            hierarchy={hierarchy}
            profiles={control?.profiles || []}
            selectedName={selectedProfile?.name || ''}
            loading={hierarchyLoading}
            error={hierarchyError}
            onSelect={setSelectedName}
            onRefresh={() => loadHierarchy(true)}
          />
        </Suspense>
      );
    }

    if (target === 'claude') {
      return (
        <section className="panel feature-panel">
          <div className="panel-head"><BrainCircuit size={18} /><div><h2>Claude Code Surface</h2><p>Subagents, permissions, MCP, hooks and runtime features.</p></div></div>
          <div className="feature-grid">
            <Info title="Subagents" value={`${asText(control?.claude?.subagent_count, '0')} detected`} icon={<Users size={18} />} />
            <Info title="Permission mode" value={asText((control?.claude?.settings as any)?.defaultMode, 'not set')} icon={<ShieldCheck size={18} />} />
            <Info title="MCP servers" value={`${(((control?.claude?.mcp as any)?.servers || []) as unknown[]).length} configured`} icon={<Cpu size={18} />} />
            <Info title="Hooks" value={`${Object.keys(((control?.claude?.settings as any)?.hooks || {}) as Record<string, unknown>).length} groups`} icon={<GitBranch size={18} />} />
          </div>
          <pre>{JSON.stringify(control?.claude || {}, null, 2)}</pre>
          <div className="bootstrap-box">
            <div className="panel-head compact"><MessageSquare size={16} /><div><h2>Claude Session Bootstrap</h2><p>Paste this at the start of a Claude Code session so it uses Daedalus/Ikarus/Ollama correctly.</p></div></div>
            <pre>{bootstrap?.prompt || 'Loading bootstrap prompt...'}</pre>
          </div>
        </section>
      );
    }

    if (target === 'codex') {
      return (
        <section className="panel feature-panel">
          <div className="panel-head"><Terminal size={18} /><div><h2>Codex Runtime</h2><p>Codex participates through AGENTS.md and the Daedalus file bus.</p></div></div>
          <div className="feature-grid">
            <Info title="AGENTS.md" value={(control?.codex?.agents_md as any)?.exists ? 'present' : 'missing'} icon={<FileText size={18} />} />
            <Info title="Managed block" value={(control?.codex?.agents_md as any)?.managed ? 'enforced' : 'not enforced'} icon={<Check size={18} />} />
            <Info title="Communication" value={asText((control?.codex?.runtime as any)?.communication, 'file_bus')} icon={<MessageSquare size={18} />} />
            <Info title="Queue source" value={asText((control?.codex?.runtime as any)?.queue_source, 'codex')} icon={<GitBranch size={18} />} />
          </div>
          <pre>{JSON.stringify(control?.codex || {}, null, 2)}</pre>
        </section>
      );
    }

    if (target === 'structure') {
      return (
        <Suspense fallback={<FeatureFallback label="Structure" />}>
          <StructureSheet
            project={project}
            data={structure}
            loading={structureLoading}
            error={structureError}
            onRefresh={() => loadStructure(true)}
          />
        </Suspense>
      );
    }

    if (target === 'providers') {
      return (
        <RuntimeCenter
          runtimes={runtimes}
          providers={providerStatus}
          providerError={providerStatusError}
          providerLoadedAt={providerStatusLoadedAt}
        />
      );
    }

    if (target === 'inbox') return <InboxTray drafts={drafts} onChange={() => refresh(project)} />;

    // queue / Mission Feed
    return (
      <section className="panel feature-panel">
        <div className="panel-head"><GitBranch size={18} /><div><h2>Mission Feed</h2><p>All runtimes communicate through queue, reports and memory.</p></div></div>
        <form className="queue-form" onSubmit={(e) => { e.preventDefault(); submitTask(); }}>
          <select value={lane} onChange={(e) => setLane(e.target.value)}>
            <option value="local_only">local_only</option>
            <option value="local">local</option>
            <option value="auto">auto</option>
            <option value="claude">claude</option>
          </select>
          <input value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="Describe work for the app project..." />
          <button className="primary" type="submit"><Play size={14} /> Queue</button>
        </form>
        <div className="feed-list">
          {([...(queue?.pending || []), ...(queue?.reports || [])] as any[]).slice(0, 20).map((item) => (
            <div className="feed-row" key={`${item.kind}-${item.name}`}>
              <b>{item.kind}</b>
              <span>{item.name}</span>
              <small>{item.lane || 'n/a'} | {item.status || 'queued'}</small>
            </div>
          ))}
        </div>
      </section>
    );
  }

  const meta = SHEET_META[view];

  return (
    <div className="app-shell">
      <header className="topbar glass">
        <div className="brand">
          <span className="logo"><Bot size={15} /></span>
          Daedalus <small>· Agent OS</small>
        </div>
        {projects.length > 0 && (
          <select className="proj" value={project} onChange={(e) => refresh(e.target.value)} aria-label="Project">
            {projects.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
          </select>
        )}
        <div className="spacer" />
        {envStatus && (
          <button
            type="button"
            className="pill"
            onClick={() => openSheet('providers')}
            title={byokTitle}
            aria-label={`BYOK readiness: ${byokConfigured} of ${envProviders.length} providers configured`}
          >
            <KeyRound size={12} /> BYOK {byokConfigured}/{envProviders.length}
          </button>
        )}
        <span
          className={cx('pill', 'loop-chip', govState === 'degraded' && 'bad', (govState === 'unknown' || govState === 'absent') && 'unknown')}
          title={govChipTitle}
          aria-label={`Promotion: ${govChipText}`}
        >
          <StateBadge state={govState} compact /> {govChipText}
        </span>
        <button
          type="button"
          className={cx('pill', 'loop-chip', loopState === 'degraded' && 'bad', loopState === 'unknown' && 'unknown')}
          onClick={() => goSpace('knowledge')}
          title={loopChipTitle}
          aria-label={`Self-improvement loop: ${loopChipText}`}
        >
          <StateBadge state={loopState} compact /> {loopChipText}
        </button>
        <span
          className="pill livechip"
          title={streamLive ? 'Live event stream connected' : 'Stream down — falling back to polling'}
        >
          <LiveDot status={streamLive ? 'good' : 'warn'} /> {streamLive ? 'live' : 'polling'} · {inFlight} running
        </span>
        <button type="button" className="iconbtn" onClick={() => refresh(project)} title="Refresh" aria-label="Refresh" aria-busy={refreshing} disabled={refreshing}><RefreshCw size={16} className={refreshing ? 'spin' : undefined} /></button>
        <button
          type="button"
          className={cx('iconbtn', fastMode && 'perf-active')}
          onClick={() => setFastMode((value) => !value)}
          title={fastMode ? 'Fast mode on · click for full glass effects' : 'Full glass effects on · click for fast mode'}
          aria-label="Toggle fast mode"
          aria-pressed={fastMode}
        >
          <Zap size={16} />
        </button>
        <button
          type="button"
          className="iconbtn"
          onClick={() => setRailOpen((v) => !v)}
          title={railOpen ? 'Hide live rail' : 'Show live rail'}
          aria-label="Toggle live rail"
        >
          <ChevronRight size={16} style={{ transform: railOpen ? 'none' : 'rotate(180deg)' }} />
        </button>
        <button type="button" className="iconbtn" onClick={() => setEditorOpen(true)} title="Theme editor" aria-label="Theme editor"><Palette size={16} /></button>
        <button
          type="button"
          className="iconbtn"
          onClick={toggleTheme}
          title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          aria-label="Toggle theme"
        >
          {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </header>

      <div className={cx('app-body', (!railOpen || space === 'graph') && 'rail-collapsed')}>
        <Dock>
          {/* The three spaces. A separate group with a rule under it, because
              a space and a tool sheet are different kinds of thing. */}
          <DockGroup>
            <div className="space-group">
              {SPACES.map((item) => (
                <DockItem
                  key={item.key}
                  icon={item.icon}
                  label={item.label}
                  active={space === item.key && !sheetOpen}
                  badge={item.key === 'knowledge' && loopDegraded.length > 0}
                  onClick={() => goSpace(item.key)}
                />
              ))}
            </div>
            {DOCK_VIEWS.map((item) => (
              <DockItem
                key={item.key}
                icon={item.icon}
                label={item.label}
                active={sheetOpen && view === item.key}
                badge={item.key === 'inbox' && draftPending > 0}
                onClick={() => openSheet(item.key)}
              />
            ))}
          </DockGroup>
          <DockSpacer />
          <DockGroup>
            <DockItem icon={<Palette size={20} />} label="Theme editor" active={editorOpen} onClick={() => setEditorOpen(true)} />
          </DockGroup>
        </Dock>

        <div className="spine-wrap">
          {/* A dead backend says so, with the command that fixes it. It never
              renders as an empty panel and it never spins. */}
          {offline && (
            <div className="error-banner" role="alert">
              <AlertTriangle size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />
              The Daedalus API is not answering on this port. Nothing on screen was read from it —
              that is not the same as there being nothing to show. Start it with{' '}
              <code>python -m daedalus.web_api</code> (loopback only), then Refresh.
            </div>
          )}
          {!offline && error && <div className="error-banner">{error}</div>}

          {space === 'chat' && (
            <>
              <MissionControl
                project={project}
                stream={liveStatus}
                inFlight={inFlight}
                queueDepth={queueDepth}
                health={health}
                healthError={healthError}
                healthLoadedAt={healthLoadedAt}
                providers={providerStatus}
                providersError={providerStatusError}
                providersLoadedAt={providerStatusLoadedAt}
                governance={governance}
                governanceLoadedAt={dashboardLoadedAt}
                loop={loop}
                onRefresh={() => refresh(project)}
                onOpenKnowledge={() => goSpace('knowledge')}
                onOpenProviders={() => openSheet('providers')}
                refreshing={refreshing}
              />
              <IkarusPanel project={project} runtimes={runtimes} providerStatus={providerStatus} onApplied={() => refresh(project)} />
            </>
          )}
          {space === 'graph' && (
            <GraphSpace
              project={project}
              structure={structure}
              loading={structureLoading}
              error={structureError}
              onRefresh={() => loadStructure(true)}
              theme={theme}
              loop={loop}
            />
          )}
          {space === 'knowledge' && <KnowledgeSpace loop={loop} project={project} />}
        </div>

        <LiveRail>
          <RailCard
            title="Mission queue"
            icon={<GitBranch size={15} />}
            badge={<span className="pill"><LiveDot status={streamLive ? 'good' : 'warn'} /> {streamLive ? 'live' : 'polling'}</span>}
          >
            <div className="rail-metrics">
              <div><b>{inFlight}</b><span>running</span></div>
              <div><b>{queueDepth}</b><span>queued</span></div>
              <div><b>{reportCount}</b><span>reports</span></div>
            </div>
          </RailCard>

          {/* The loop, on the home surface. `degraded_sources` must not require
              navigating to a tab: a source that failed while you were talking
              to Ikarus is exactly the fact you would otherwise never look for. */}
          <RailCard
            title="Self-improvement loop"
            icon={<Library size={15} />}
            badge={<StateBadge state={loopState} compact />}
          >
            {loop.queue.error ? (
              <div className="conn"><div className="l"><span className="sub">{loop.queue.error.message}</span></div></div>
            ) : loopBlock ? (
              <>
                <div className="kpi">
                  {loopBlock.n_candidates}{' '}
                  <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 500 }}>ranked candidate(s)</span>
                </div>
                {loopDegraded.length > 0 ? (
                  <p style={{ fontSize: 11, color: 'var(--bad)', lineHeight: 1.5, marginTop: 6 }}>
                    <b>{loopDegraded.join(', ')}</b> could not be consulted. This number is what
                    survived, not what there is.
                  </p>
                ) : (
                  <p style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.5, marginTop: 6 }}>
                    Every picker source answered.
                  </p>
                )}
                <button
                  type="button"
                  className="pill"
                  style={{ marginTop: 8, cursor: 'pointer' }}
                  onClick={() => goSpace('knowledge')}
                >
                  Open Knowledge
                </button>
              </>
            ) : (
              <div className="conn"><div className="l"><span className="sub">not read yet</span></div></div>
            )}
          </RailCard>

          {/* CONFIGURED and REACHABLE are two facts, and the old connected/offline
              dot collapsed them. Nothing here is ever `working`: a runtime being
              on PATH and answering a probe is not a billable call succeeding, so
              the honest ceiling for a lane is `present`. */}
          <RailCard title="Connections" icon={<KeyRound size={15} />} badge={<span className="pill">BYOK</span>}>
            {providerStatusError && (
              <div className="conn">
                <div className="l"><span className="sub">Provider sample failed. Cached rows are UNKNOWN.</span></div>
                <StateBadge state="unknown" compact />
              </div>
            )}
            {runtimes.length === 0 && !providerStatusError && <div className="conn"><div className="l"><span className="sub">No runtimes detected yet.</span></div></div>}
            {runtimes.map((r) => {
              const row = providerStatus.find((p) => p.name === (RUNTIME_TO_PROVIDER[r.id] || r.id));
              const item = providerStatusError ? {
                name: r.label,
                state: 'unknown' as const,
                headline: 'the provider availability sample failed; cached reachability is not a live claim',
                remedy: providerStatusError,
                derivedFrom: 'GET /api/providers/status'
              } : assessProvider({
                label: r.label,
                configured: row ? row.configured : undefined,
                available: r.available && (row ? row.available : true),
                requiresKey: row?.requires_key,
                detail: `${r.mode} · ${r.auth_status}`,
                lastError: r.last_error || row?.last_error
              });
              return (
                <div className="conn" key={r.id} title={`${item.headline}${item.remedy ? `\n→ ${item.remedy}` : ''}`}>
                  <div className="l">
                    <div>{r.label}<div className="sub">{r.mode} · {r.auth_status}</div></div>
                  </div>
                  <StateBadge state={item.state} compact title={item.headline} />
                </div>
              );
            })}
          </RailCard>

          <RailCard title="Watcher" icon={<Activity size={15} />}>
            <div className="heart">
              <LiveDot status={streamLive ? 'good' : 'warn'} />
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>
                  {streamLive ? `alive · ${live.watcherState || 'streaming'}` : 'polling…'}
                </div>
                <div className="sub" style={{ color: 'var(--dim)', fontSize: 11 }}>{queueDepth} queued · {reportCount} reports</div>
              </div>
            </div>
          </RailCard>

          <Inspector profile={selectedProfile} control={control} onAutonomy={setAgentAutonomy} />
        </LiveRail>
      </div>

      <GlassSheet open={sheetOpen} title={meta.title} subtitle={meta.subtitle} onClose={closeSheet}>
        {renderSheet(view)}
      </GlassSheet>

      <ThemeEditor open={editorOpen} onClose={() => setEditorOpen(false)} theme={theme} />
    </div>
  );
}

function Info({ title, value, icon }: { title: string; value: string; icon: React.ReactNode }) {
  return (
    <div className="info-card">
      {icon}
      <span>{title}</span>
      <strong>{value}</strong>
      <ChevronRight size={14} />
    </div>
  );
}
