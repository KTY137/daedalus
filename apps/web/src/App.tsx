import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import {
  Activity,
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
  getDrafts,
  getHierarchy,
  getProjects,
  getRuntimeStatus,
  getStructure,
  queueTask,
  testRuntime,
  updateAutonomy,
  type DraftRow
} from './api';
import type { AgentProfile, BootstrapPayload, ControlPlanePayload, DashboardPayload, EffortLevel, HierarchyPayload, IkarusAskPayload, IkarusChatPayload, ProjectRow, RuntimeRow, RuntimeTestPayload, StructurePayload } from './types';

type SheetView = 'network' | 'claude' | 'codex' | 'providers' | 'queue' | 'inbox' | 'structure' | 'map';

// The structure explorer pulls in Sigma, Graphology and a layout worker. Keep
// that WebGL stack off the chat-first startup path and load it only on demand.
const StructureSheet = lazy(() => import('./components/StructureSheet').then((module) => ({ default: module.StructureSheet })));
const CodeMap = lazy(() => import('./components/CodeMap').then((module) => ({ default: module.CodeMap })));
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

/** Friendly label for a `provider_used` id: runtime label if known, else prettified. */
function brainLabel(id: string, runtimes: RuntimeRow[]): string {
  if (!id) return '';
  if (id === 'deterministic') return 'Deterministic';
  return runtimes.find((r) => r.id === id)?.label || id;
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
function IkarusPanel({ project, runtimes, onApplied }: { project: string; runtimes: RuntimeRow[]; onApplied: () => void }) {
  const [messages, setMessages] = useState<ChatMsg[]>([
    {
      id: 0,
      role: 'ik',
      text:
        'Ikarus here — your Agent OS spine. Ask me to draft an agent network, route a task to a lane, or open any panel from the dock on the left. I propose; you confirm before anything writes. Pick my brain from the selector up top — Deterministic needs no model; a connected runtime gives me a real LLM.'
    }
  ]);
  const [input, setInput] = useState('Build a clean app-project agent network with Claude, Codex, Ikarus, QA, UI, API and memory roles.');
  const [provider, setProvider] = useState('deterministic');
  const [effort, setEffort] = useState<EffortLevel>(loadEffort);
  const [model, setModel] = useState<string>(loadModel);
  const [busy, setBusy] = useState(false);
  // Non-null while an `askIkarus` call is in flight — drives the thinking bubble.
  const [thinking, setThinking] = useState<{ brain: string } | null>(null);
  const idRef = useRef(1);
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = transcriptRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, thinking]);

  // Persist the cheap-by-default controls so they survive reloads.
  useEffect(() => { try { localStorage.setItem(LS_EFFORT, effort); } catch { /* noop */ } }, [effort]);
  useEffect(() => { try { localStorage.setItem(LS_MODEL, model); } catch { /* noop */ } }, [model]);

  const push = useCallback((msg: Omit<ChatMsg, 'id'>) => {
    setMessages((prev) => [...prev, { ...msg, id: idRef.current++ }]);
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
    setThinking({ brain: provider === 'deterministic' ? 'deterministic' : `via ${brainLabel(provider, runtimes)}` });

    // STREAM FIRST. The endpoint routes identically to /api/ikarus/ask and
    // returns the same `final` envelope, so this is purely a latency win: the
    // Claude CLI has a ~4s startup floor that no amount of backend work removes,
    // and streaming turns that from a blank wait into text appearing.
    // Falls back to the blocking call if the stream never produced anything.
    const streamed = await new Promise<boolean>((resolve) => {
      if (typeof EventSource === 'undefined') { resolve(false); return; }

      let liveId: number | null = null;
      let acc = '';

      const openBubble = () => {
        // Allocate the id OURSELVES rather than via push(): push() increments
        // idRef inside the setMessages updater, which React StrictMode may run
        // twice, and we need a stable handle to patch on every delta.
        const id = idRef.current++;
        setMessages((prev) => [...prev, { id, role: 'ik', text: '' }]);
        setThinking(null);          // first token replaces the thinking bubble
        return id;
      };

      let settled = false;
      const finish = (ok: boolean) => { if (!settled) { settled = true; resolve(ok); } };

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
          // Partial text with no `final` is worse than useless — it looks like a
          // complete answer. Drop the bubble and let the blocking path retry.
          if (liveId !== null) {
            const id = liveId;
            setMessages((prev) => prev.filter((m) => m.id !== id));
          }
          finish(false);
        }
      });
    });

    if (streamed) {
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

  const currentBrain = brainLabel(provider, runtimes);
  // Prefill local model names for the current provider when we know them (Ollama etc.).
  const providerModels = runtimes.find((r) => r.id === provider)?.models || [];

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
              {runtimes.filter((r) => r.available).map((r) => (
                <option key={r.id} value={r.id}>{r.label}</option>
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
                brain: {brainLabel(m.brain, runtimes)}{m.model ? ` · ${m.model}` : ''}
              </small>
            )}
            {m.stat && (
              <small style={{ display: 'block', marginTop: 4, color: 'var(--muted)', fontSize: 11 }}>{m.stat}</small>
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

function InboxTray({ drafts, onChange }: { drafts: DraftRow[]; onChange: () => void }) {
  const [busy, setBusy] = useState('');
  const [applied, setApplied] = useState<Record<string, unknown> | undefined>();
  const pending = drafts.filter((d) => d.status === 'pending');

  async function act(id: string, verb: 'apply' | 'dismiss') {
    setBusy(id);
    try {
      if (verb === 'apply') {
        const res = await applyDraft(id);
        setApplied(res.applied);
      } else {
        await dismissDraft(id);
      }
      onChange();
    } finally {
      setBusy('');
    }
  }

  return (
    <section className="panel feature-panel">
      <div className="panel-head"><Inbox size={18} /><div>
        <h2>Draft Inbox</h2>
        <p>Advisory proposals from the free bench. A free model may propose — never merge. Applying hands a review packet to the trusted (Claude) lane.</p>
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
              <button className="primary" disabled={busy === d.id} onClick={() => act(d.id, 'apply')}><Check size={13} /> Apply</button>
              <button disabled={busy === d.id} onClick={() => act(d.id, 'dismiss')}><Trash2 size={13} /> Dismiss</button>
            </div>
          </div>
        ))}
      </div>
      {applied && (
        <div className="bootstrap-box">
          <div className="panel-head compact"><MessageSquare size={16} /><div><h2>Review packet</h2><p>Hand this to the Claude lane to actually apply the change.</p></div></div>
          <pre>{JSON.stringify(applied, null, 2)}</pre>
        </div>
      )}
    </section>
  );
}

function RuntimeCenter({ runtimes }: { runtimes: RuntimeRow[] }) {
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
        <div><h2>Provider Runtime Registry</h2><p>CLI-first today, API-ready later. The app never talks to random subprocesses directly.</p></div>
      </div>
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

const DOCK_VIEWS: Array<{ key: SheetView; label: string; icon: ReactNode }> = [
  { key: 'network', label: 'Agent Network', icon: <Network size={20} /> },
  { key: 'structure', label: 'Structure', icon: <Boxes size={20} /> },
  { key: 'map', label: 'Code Map', icon: <Waypoints size={20} /> },
  { key: 'queue', label: 'Mission Feed', icon: <GitBranch size={20} /> },
  { key: 'providers', label: 'Connections', icon: <KeyRound size={20} /> },
  { key: 'inbox', label: 'Draft Inbox', icon: <Inbox size={20} /> },
  { key: 'claude', label: 'Claude Code', icon: <BrainCircuit size={20} /> },
  { key: 'codex', label: 'Codex', icon: <Terminal size={20} /> }
];

const SHEET_META: Record<SheetView, { title: string; subtitle: string }> = {
  network: { title: 'Agent Network', subtitle: 'A useful map, not the whole product — talk to Ikarus to change it.' },
  structure: { title: 'Structure', subtitle: 'Code-health across languages: hotspots, duplication and distillation.' },
  map: { title: 'Code Map', subtitle: 'The living dependency graph — hot means complex and changing.' },
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
  const [bootstrap, setBootstrap] = useState<BootstrapPayload | undefined>();
  const [selectedName, setSelectedName] = useState('');
  const [view, setView] = useState<SheetView>('network');
  const [sheetOpen, setSheetOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(true);
  const [editorOpen, setEditorOpen] = useState(false);
  const [drafts, setDrafts] = useState<DraftRow[]>([]);
  const [objective, setObjective] = useState('');
  const [lane, setLane] = useState('local_only');
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [fastMode, setFastMode] = useState(loadPerformanceMode);
  // Lightweight live counters pushed by the SSE stream — updated instantly on
  // events so badges/dots react without waiting for a full dashboard fetch.
  const [live, setLive] = useState<{ queueDepth?: number; inFlight?: number; watcherState?: string; unread?: number }>({});
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
    setRefreshing(true);
    try {
      const projectPayload = await getProjects();
      if (serial !== refreshSerial.current) return;
      setProjects(projectPayload.projects);
      const chosen = nextProject || queryProject || projectPayload.projects[0]?.name || '';
      if (!chosen) return;
      setProject(chosen);

      // Each surface commits as soon as it arrives. One slow dashboard scan
      // must not blank the agent graph, runtime controls or project picker.
      const tasks = [
        getDashboard(chosen).then((payload) => {
          if (serial === refreshSerial.current) setDashboard(payload);
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
        setError(`${failures.length} data source${failures.length === 1 ? '' : 's'} did not respond. Available panels are still usable. ${first}`);
      }
    } catch (err) {
      if (serial === refreshSerial.current) setError(err instanceof Error ? err.message : String(err));
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
      if (project) getDashboard(project).then(setDashboard).catch(() => undefined);
    },
    onReport: () => {
      // A task finished → pull the fresh reports/feed once.
      if (project) getDashboard(project).then(setDashboard).catch(() => undefined);
    }
  });

  // Degraded fallback: only while the stream is NOT live do we poll the
  // dashboard on an interval (keeps the mission feed fresh when SSE is down).
  useEffect(() => {
    if (!project || liveStatus === 'live') return;
    const timer = setInterval(() => {
      getDashboard(project).then(setDashboard).catch(() => undefined);
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

  // The Structure sheet and the Code Map read the SAME `/api/structure`
  // payload (the map consumes `structure.graph`), so opening either one warms
  // the index for both — we never pay for that scan twice.
  useEffect(() => {
    if (!sheetOpen || !project) return;
    if (view !== 'structure' && view !== 'map') return;
    if (structureFetchedFor.current === project) return;
    loadStructure(false);
  }, [sheetOpen, view, project, loadStructure]);

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
        setSheetOpen(false);
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

  function openSheet(next: SheetView) {
    setView(next);
    setSheetOpen(true);
  }

  function closeSheet() {
    setSheetOpen(false);
  }

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

    if (target === 'map') {
      return (
        <Suspense fallback={<FeatureFallback label="Code Map" />}>
          <CodeMap
            project={project}
            data={structure}
            loading={structureLoading}
            error={structureError}
            onRefresh={() => loadStructure(true)}
            theme={theme}
          />
        </Suspense>
      );
    }

    if (target === 'providers') return <RuntimeCenter runtimes={runtimes} />;

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

      <div className={cx('app-body', !railOpen && 'rail-collapsed')}>
        <Dock>
          <DockGroup>
            <DockItem icon={<MessageSquare size={20} />} label="Ikarus chat" active={!sheetOpen} onClick={closeSheet} />
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
          {error && <div className="error-banner">{error}</div>}
          <IkarusPanel project={project} runtimes={runtimes} onApplied={() => refresh(project)} />
        </div>

        <LiveRail>
          <RailCard
            title="Mission queue"
            icon={<GitBranch size={15} />}
            badge={<span className="pill"><LiveDot status={streamLive ? 'good' : 'warn'} /> {streamLive ? 'live' : 'polling'}</span>}
          >
            <div className="kpi">{inFlight} <span style={{ fontSize: 12, color: 'var(--muted)', fontWeight: 500 }}>in flight</span></div>
            <div className="bars">
              {[40, 70, 55, 90, 35, 65, 80, 50].map((h, i) => <i key={i} style={{ height: `${h}%` }} />)}
            </div>
          </RailCard>

          <RailCard title="Connections" icon={<KeyRound size={15} />} badge={<span className="pill">BYOK</span>}>
            {runtimes.length === 0 && <div className="conn"><div className="l"><span className="sub">No runtimes detected yet.</span></div></div>}
            {runtimes.map((r) => (
              <div className="conn" key={r.id}>
                <div className="l">
                  <span className="cdot" style={{ background: r.available ? 'var(--good)' : 'var(--dim)' }} />
                  <div>{r.label}<div className="sub">{r.mode} · {r.auth_status}</div></div>
                </div>
                <span
                  className="pill"
                  style={{
                    color: r.available ? 'var(--good)' : 'var(--muted)',
                    borderColor: r.available ? 'color-mix(in srgb, var(--good) 45%, transparent)' : undefined
                  }}
                >
                  {r.available ? 'connected' : 'offline'}
                </span>
              </div>
            ))}
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
