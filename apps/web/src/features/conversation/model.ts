import type { EffortLevel, IkarusAskAction, IkarusAskPayload } from '@/shared/contracts';
import type {
  ConversationCancellationStatus,
  ConversationDispatch,
  ConversationTurn,
  ConversationView,
  TaskSnapshot
} from '@/shared/api';

/**
 * The conversation's data model, and the one derivation that makes this
 * surface different from a chat window: the PROTOKOLL.
 *
 * Every Ikarus answer arrives with receipts the kernel wrote about that
 * turn — which runtime was selected and why, what project context was read
 * and what was withheld, which policy refused what, whether a dispatch was
 * linked durably and how it ended. Claude Code shows what a model *called*;
 * this page shows what the kernel *receipted*. None of it is a model claim.
 *
 * Three rules for everything in here:
 *
 * 1. A row exists only when its source field arrived. Absent data is absent,
 *    never a grey placeholder — a ledger that pads itself is a metric strip.
 * 2. Rows are DERIVED at render, never stored. A resumed thread carries the
 *    stored envelope; the runtime list and the map arrive later; deriving
 *    late is what lets `claude_code_cli` become `Claude Code` once it can.
 * 3. This module is pure. No fetch, no DOM, no React — which is why it can be
 *    fed recorded frame sequences in a Node spec and asserted exactly.
 */

/* ------------------------------------------------------------------ turns */

export type Role = 'you' | 'ikarus' | 'note';

/** What the backend said produced one answer, kept verbatim. */
export interface TurnOrigin {
  intent?: string;
  provider_used?: string;
  model_used?: string;
}

/** The `start` frame: the route the server committed to before any text. */
export interface RouteStart {
  intent?: string;
  shell?: string;
  provider_used?: string;
}

export interface LlmSelection {
  provider?: string;
  requested?: string | null;
  auto_selected?: boolean;
  timeout_s?: number;
  max_attempts?: number;
  reason?: string;
}

export interface ContextReceipt {
  focus_file?: string | null;
  included?: number;
  withheld_count?: number;
  trimmed?: number;
  ambiguous?: boolean | string[];
}

/** The deny receipt `ikarus_os._deny_receipt` stamps on a refused turn. */
export interface DenyReceipt {
  entrypoint_id?: string;
  verdict?: string;
  contract?: string;
  provider?: string;
  host?: string | null;
  lane?: string;
  reason?: string;
}

export interface ActOffer {
  objective?: string;
  reason?: string;
  signal?: string;
}

export interface IntentMismatch {
  start?: string;
  final?: string;
  dropped_action?: boolean;
}

/**
 * The bounded subset of the final envelope the ledger reads. Every field is
 * optional because the server stores the envelope through `_loop_shape`,
 * which clips and may drop; a field that did not arrive produces no row.
 */
export interface TurnEnvelope {
  intent?: string;
  shell?: string;
  provider_used?: string;
  model_used?: string;
  llm?: LlmSelection;
  context?: ContextReceipt;
  refusal?: DenyReceipt;
  act_offer?: ActOffer;
  action?: IkarusAskAction;
  intent_mismatch?: IntentMismatch;
  stream_interrupted?: boolean;
}

export interface Turn {
  role: Role;
  text: string;
  /** Browser-local identity; dispatch progress is joined to this, never an index. */
  localId?: string;
  /** Canonical conversation-spine identity for this exact exchange. */
  backendTurnId?: number;
  /** Whether the backend proved that this exchange reached the durable spine. */
  conversationPersisted?: boolean;
  /** Stored verbatim; the stamp is derived at render. */
  origin?: TurnOrigin;
  /** The route the `start` frame committed to, before the envelope arrived. */
  started?: RouteStart;
  /** The bounded final envelope, live or stored. */
  envelope?: TurnEnvelope;
  /** The browser stopped observing this turn; backend cancellation is unproven. */
  halted?: boolean;
  /**
   * How long this answer took, measured in this browser. Absent means NOT
   * MEASURED — a resumed turn carries no duration, because the store does
   * not record one and inventing it from two timestamps would measure the
   * reader's thinking time as well.
   */
  seconds?: number;
  streaming?: boolean;
  /** An action Ikarus offered on this turn, still awaiting an answer. */
  offer?: IkarusAskAction;
  /** What happened to that offer, once something happened. */
  offerOutcome?: string;
  /** Live measured state of the task this exact turn launched. */
  dispatch?: TaskSnapshot;
  /** Canonical id of the generation request, separate from the persisted turn. */
  requestId?: number;
  /** An explicit server cancellation request is a separate fact from closing observation. */
  cancellation?: ConversationCancellationStatus;
  /** Project-bound editor artifacts actually attached to this request. */
  contextRefs?: string[];
  /** When the spine recorded the turn; present only on a resumed turn. */
  createdTs?: string;
  /** The effort sent with this turn, when this browser sent it. */
  effort?: EffortLevel;
}

export function positiveTurnId(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : undefined;
}

/* ---------------------------------------------------------------- narrow */

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function str(value: unknown): string | undefined {
  return typeof value === 'string' && value ? value : undefined;
}

function num(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function bool(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

/**
 * Narrow an unknown envelope (live `final` payload or the stored, clipped
 * one) to the fields the ledger reads. Anything of the wrong shape is
 * dropped rather than drawn: storage and transport are both writable by
 * things this page does not control, and a row is read as evidence.
 */
export function envelopeFrom(value: unknown): TurnEnvelope | undefined {
  if (!isRecord(value)) return undefined;
  const out: TurnEnvelope = {};
  const intent = str(value.intent);
  if (intent) out.intent = intent;
  const shell = str(value.shell);
  if (shell) out.shell = shell;
  const provider = str(value.provider_used);
  if (provider) out.provider_used = provider;
  const model = str(value.model_used);
  if (model) out.model_used = model;
  if (isRecord(value.llm)) {
    const llm: LlmSelection = {};
    const p = str(value.llm.provider);
    if (p) llm.provider = p;
    const requested = value.llm.requested;
    if (typeof requested === 'string' || requested === null) llm.requested = requested;
    const auto = bool(value.llm.auto_selected);
    if (auto !== undefined) llm.auto_selected = auto;
    const timeout = num(value.llm.timeout_s);
    if (timeout !== undefined) llm.timeout_s = timeout;
    const attempts = num(value.llm.max_attempts);
    if (attempts !== undefined) llm.max_attempts = attempts;
    const reason = str(value.llm.reason);
    if (reason) llm.reason = reason;
    if (Object.keys(llm).length > 0) out.llm = llm;
  }
  if (isRecord(value.context)) {
    const ctx: ContextReceipt = {};
    const focus = value.context.focus_file;
    if (typeof focus === 'string' || focus === null) ctx.focus_file = focus;
    const included = num(value.context.included);
    if (included !== undefined) ctx.included = included;
    const withheld = num(value.context.withheld_count);
    if (withheld !== undefined) ctx.withheld_count = withheld;
    const trimmed = num(value.context.trimmed);
    if (trimmed !== undefined) ctx.trimmed = trimmed;
    const ambiguous = value.context.ambiguous;
    if (typeof ambiguous === 'boolean') ctx.ambiguous = ambiguous;
    else if (Array.isArray(ambiguous)) ctx.ambiguous = ambiguous.filter((x): x is string => typeof x === 'string');
    if (Object.keys(ctx).length > 0) out.context = ctx;
  }
  if (isRecord(value.refusal)) {
    const r = value.refusal;
    const refusal: DenyReceipt = {};
    for (const key of ['entrypoint_id', 'verdict', 'contract', 'provider', 'lane', 'reason'] as const) {
      const v = str(r[key]);
      if (v) refusal[key] = v;
    }
    if (typeof r.host === 'string' || r.host === null) refusal.host = r.host;
    if (Object.keys(refusal).length > 0) out.refusal = refusal;
  }
  if (isRecord(value.act_offer)) {
    const offer: ActOffer = {};
    for (const key of ['objective', 'reason', 'signal'] as const) {
      const v = str(value.act_offer[key]);
      if (v) offer[key] = v;
    }
    if (Object.keys(offer).length > 0) out.act_offer = offer;
  }
  if (isRecord(value.action) && value.action.kind === 'queue_task' && isRecord(value.action.args)) {
    out.action = {
      kind: 'queue_task',
      args: {
        project: str(value.action.args.project) || '',
        objective: str(value.action.args.objective) || '',
        lane: str(value.action.args.lane) || ''
      },
      requires_confirmation: value.action.requires_confirmation !== false
    };
  }
  if (isRecord(value.intent_mismatch)) {
    const m: IntentMismatch = {};
    const start = str(value.intent_mismatch.start);
    if (start) m.start = start;
    const final = str(value.intent_mismatch.final);
    if (final) m.final = final;
    const dropped = bool(value.intent_mismatch.dropped_action);
    if (dropped !== undefined) m.dropped_action = dropped;
    if (Object.keys(m).length > 0) out.intent_mismatch = m;
  }
  const interrupted = bool(value.stream_interrupted);
  if (interrupted !== undefined) out.stream_interrupted = interrupted;
  return out;
}

/* --------------------------------------------------------------- resume */

export function resumedDispatch(dispatch: ConversationDispatch): TaskSnapshot | undefined {
  const id = typeof dispatch.link?.dispatch_ref === 'string' ? dispatch.link.dispatch_ref : '';
  if (!id) return undefined;
  const latest = dispatch.latest;
  const detail = latest?.detail && typeof latest.detail === 'object' ? latest.detail : {};
  const text = (key: string): string | null =>
    typeof detail[key] === 'string' && detail[key] ? String(detail[key]) : null;
  const providers = Array.isArray(detail.actual_providers)
    ? detail.actual_providers.filter((provider): provider is string => typeof provider === 'string' && Boolean(provider))
    : [];
  const bridgeStatus = text('bridge_status');
  const outcome = String(latest?.outcome_state || '').toUpperCase();
  const state = latest?.lifecycle === 'dispatched'
    ? 'dispatched'
    : bridgeStatus || (outcome === 'PRESENT' ? 'done' : outcome === 'DEGRADED' ? 'failed' : 'unknown');
  return {
    id,
    found: true,
    state,
    source: 'conversation_spine',
    lane: text('lane'),
    requested_lane: text('requested_lane'),
    actual_providers: providers,
    summary: typeof latest?.summary === 'string' && latest.summary ? latest.summary : null,
    error: text('error'),
    applied: typeof detail.applied === 'boolean' ? detail.applied : null,
    applied_reason: text('application_reason'),
    stalled: false,
    timed_out: false
  };
}

/**
 * The turns of a stored conversation, in the shape the transcript draws.
 * Everything here was said before this page loaded, so nothing "arrives".
 */
export function resumedTurns(view: ConversationView, threadId: string): Turn[] {
  const rows: ConversationTurn[] = view.turns || [];
  const dispatchByTurn = new Map<number, TaskSnapshot>();
  for (const dispatch of view.dispatches || []) {
    const turnId = positiveTurnId(dispatch.link?.turn_id);
    const snapshot = resumedDispatch(dispatch);
    if (turnId !== undefined && snapshot) dispatchByTurn.set(turnId, snapshot);
  }
  return rows.flatMap<Turn>((t, index) => {
    const backendTurnId = positiveTurnId(t.id);
    const envelope = envelopeFrom(t.envelope);
    return [
      { role: 'you', text: t.user_message, localId: `stored-${threadId}-${index}-you`, createdTs: t.created_ts },
      {
        role: 'ikarus',
        text: t.assistant_text || '',
        localId: `stored-${threadId}-${index}-ikarus`,
        backendTurnId,
        conversationPersisted: backendTurnId !== undefined,
        dispatch: backendTurnId !== undefined ? dispatchByTurn.get(backendTurnId) : undefined,
        origin: t.provider_used
          ? { intent: t.intent, provider_used: t.provider_used, model_used: t.model_used }
          : undefined,
        envelope,
        createdTs: t.created_ts
      }
    ];
  });
}

/**
 * A dispatch this conversation started that has not reported back.
 *
 * `ConversationStore.resume()` has always returned `open_dispatches` — a
 * dispatch whose latest lifecycle is still `dispatched` — and its own
 * docstring calls it a display of what has not been heard from, never an
 * instruction to redo it. Nothing rendered it until the work rail.
 */
export interface OpenDispatch {
  ref: string;
  turnId?: number;
  /** when the dispatch was linked, from the link row */
  since?: string;
  /** what the dispatch said it was, from the dispatched event */
  summary?: string;
}

export function openDispatchesFrom(view: ConversationView | undefined): OpenDispatch[] {
  const rows = view?.open_dispatches || [];
  const out: OpenDispatch[] = [];
  for (const row of rows) {
    const ref = typeof row.link?.dispatch_ref === 'string' ? row.link.dispatch_ref : '';
    if (!ref) continue;
    const summary = typeof row.latest?.summary === 'string' && row.latest.summary ? row.latest.summary : undefined;
    const since = typeof row.link?.created_ts === 'string' && row.link.created_ts ? row.link.created_ts : undefined;
    out.push({ ref, turnId: positiveTurnId(row.link?.turn_id), since, summary });
  }
  return out;
}

/* ---------------------------------------------------------------- labels */

export function taskStateLabel(task: TaskSnapshot): string {
  if (task.stalled) return 'festgefahren';
  if (task.timed_out) return 'unklar';
  const state = task.state.toLowerCase();
  if (state === 'dispatched') return 'übergeben';
  if (state === 'queued') return 'eingereiht';
  if (state === 'running' || state === 'claimed') return 'läuft';
  if (state === 'done' || state === 'completed' || state === 'succeeded') return 'fertig';
  if (state === 'failed' || state === 'quarantined') return 'fehlgeschlagen';
  return 'unklar';
}

export function handoffLabel(applied: boolean | null): string {
  // Older task reports name this field `applied`. In the conversation it is
  // only an observed handoff result, never proof that a repository changed or
  // that promotion happened.
  return applied === true ? 'bestätigt' : applied === false ? 'nicht bestätigt' : 'unklar';
}

export function cancellationLabel(status: ConversationCancellationStatus): string {
  switch (status) {
    case 'requested': return 'Abbruch angefordert – Bestätigung steht aus';
    case 'confirmed': return 'Abbruch bestätigt';
    case 'not_supported': return 'Server unterstützt keinen Abbruch-Request';
    case 'already_terminal': return 'Turn war bereits abgeschlossen';
    default: return 'Abbruchzustand unbekannt';
  }
}

/** Seconds while a turn is out. Past a minute a bare `73s` stops being read. */
export function elapsedLabel(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/**
 * A measured wait, in German decimal notation and at a precision the
 * measurement can carry: tenths under ten seconds, whole seconds above.
 * `44,6 s` and `0,3 s` are both true; `44,63 s` claims a millisecond the
 * round trip cannot resolve.
 */
export function waitLabel(seconds: number): string {
  if (seconds >= 10) return `${Math.round(seconds)} s`;
  return `${seconds.toFixed(1).replace('.', ',')} s`;
}

/** `vor 2 min`, `vor 3 h`, `gestern`, or the date — for the thread list. */
export function relativeTime(iso: string | undefined, now: number = Date.now()): string {
  if (!iso) return '';
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return '';
  const s = Math.max(0, Math.round((now - then) / 1000));
  if (s < 60) return 'gerade eben';
  const m = Math.round(s / 60);
  if (m < 60) return `vor ${m} min`;
  const h = Math.round(m / 60);
  if (h < 24) return `vor ${h} h`;
  const d = Math.round(h / 24);
  if (d === 1) return 'gestern';
  if (d < 7) return `vor ${d} Tagen`;
  try {
    return new Date(then).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
  } catch {
    return '';
  }
}

function baseName(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean);
  return parts[parts.length - 1] || path;
}

/* ----------------------------------------------------------------- stamp */

export type StampKind = 'measured' | 'model' | 'failed' | 'note';

/**
 * A stamp is a word and an origin, not one string.
 *
 * The word stays in the product's own capitals — the invitation on the empty
 * page names `GEMESSEN` literally, so the two must not drift apart. The origin
 * beside it keeps its own case, and it is flagged when it is an internal ID
 * rather than a name: the runtime list is a separate slow request, and when
 * it has not arrived the honest rendering of `claude_code_cli` is the
 * identifier itself, set as one.
 */
export interface Stamp {
  word: string;
  origin?: string;
  originIsId?: boolean;
  kind: StampKind;
}

export function stampFor(origin: TurnOrigin, labelOf: (id: string) => string | undefined): Stamp | undefined {
  const provider = origin.provider_used || '';
  if (origin.intent === 'error') return { word: 'FEHLGESCHLAGEN', kind: 'failed' };
  if (provider === 'deterministic' || origin.intent === 'status' || origin.intent === 'distill') {
    return { word: 'GEMESSEN', origin: 'lokaler Index', kind: 'measured' };
  }
  // No provider and no deterministic intent: nothing produced this, so
  // nothing is stamped. "MODELL · unbekannt" would be a word for a fact that
  // was not measured.
  if (!provider) return undefined;
  const named = labelOf(provider);
  const runtime = named || provider;
  // `claude_code_cli` + model `claude` printed the same word twice. A model
  // name earns its place only when the runtime's own name does not contain it.
  const model = origin.model_used || '';
  const extra = model && !runtime.toLowerCase().includes(model.toLowerCase()) ? ` · ${model}` : '';
  return { word: 'MODELL', origin: `${runtime}${extra}`, originIsId: !named, kind: 'model' };
}

/** The stamp for one drawn turn, or nothing when nothing produced it yet. */
export function stampForTurn(turn: Turn, labelOf: (id: string) => string | undefined): Stamp | undefined {
  if (turn.role === 'note') return { word: 'OBERFLÄCHE', origin: 'nicht gesendet', kind: 'note' };
  if (turn.role !== 'ikarus') return undefined;
  if (turn.halted) return { word: 'ANZEIGE BEENDET', kind: 'failed' };
  return turn.origin ? stampFor(turn.origin, labelOf) : undefined;
}

/* ------------------------------------------------------------- citations */

/** One identifier Ikarus named, and the module on the map it resolves to. */
export interface Citation {
  seen: string;
  module: string;
}

/**
 * Pull identifiers out of an answer so the reader can jump to them. Keyed by
 * the MODULE, not by the string that named it: one answer wrote
 * `daedalus/spine/attempt.py` and `attempt.py` about the same file.
 */
export function citationsFrom(text: string, resolve: (id: string) => string | undefined): Citation[] {
  const found = new Map<string, string>();
  const re = /[A-Za-z0-9_./\\-]+\.(?:py|ts|tsx|js|jsx|rs|go|json|md)\b/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text)) !== null) {
    const module = resolve(m[0]);
    if (!module || found.has(module)) continue;
    found.set(module, m[0]);
    if (found.size >= 6) break;
  }
  return [...found].map(([module, seen]) => ({ seen, module }));
}

/* --------------------------------------------------------------- ledger */

export type RowTone = 'info' | 'live' | 'ok' | 'bad' | 'warn';

export type LedgerKey =
  | 'route'
  | 'context'
  | 'refusal'
  | 'editor'
  | 'answer'
  | 'mismatch'
  | 'offer'
  | 'dispatch'
  | 'cancel';

export interface LedgerRow {
  key: LedgerKey;
  /** the role word, in the label type role */
  label: string;
  /** one line, the datum */
  datum: string;
  tone: RowTone;
  /** lines a disclosure opens; absent when the datum is the whole fact */
  detail?: string[];
  /** this row IS the provenance stamp of a settled answer (never while streaming) */
  stamp?: boolean;
}

function shellWord(shell: string | undefined): string | undefined {
  if (!shell) return undefined;
  if (shell === 'deterministic') return 'deterministisch';
  if (shell === 'voice') return 'Voice';
  if (shell === 'hand') return 'Hand';
  return shell;
}

function routeRow(turn: Turn, labelOf: (id: string) => string | undefined): LedgerRow | undefined {
  const env = turn.envelope;
  const llm = env?.llm;
  const provider = env?.provider_used || turn.origin?.provider_used || turn.started?.provider_used;
  const shell = shellWord(env?.shell || turn.started?.shell);
  if (!provider && !llm) return undefined;

  const detail: string[] = [];
  if (shell) detail.push(`Shell: ${shell}`);

  if (llm?.provider) {
    const name = labelOf(llm.provider) || llm.provider;
    const datum = llm.auto_selected ? `Automatisch → ${name}` : name;
    if (llm.requested && llm.requested !== llm.provider) detail.push(`angefragt: ${labelOf(llm.requested) || llm.requested}`);
    if (llm.reason) detail.push(llm.reason);
    const model = env?.model_used;
    if (model && !name.toLowerCase().includes(model.toLowerCase())) detail.push(`Modell ${model}`);
    if (llm.timeout_s !== undefined) detail.push(`Zeitfenster ${Math.round(llm.timeout_s)} s`);
    if (llm.max_attempts !== undefined && llm.max_attempts > 1) detail.push(`bis zu ${llm.max_attempts} Versuche`);
    return { key: 'route', label: 'Route', datum, tone: turn.streaming ? 'live' : 'info', detail: detail.length ? detail : undefined };
  }

  if (provider === 'deterministic') {
    return { key: 'route', label: 'Route', datum: 'Lokaler Index', tone: turn.streaming ? 'live' : 'info', detail: detail.length ? detail : undefined };
  }
  const name = labelOf(provider || '') || provider || '';
  if (!name) return undefined;
  return {
    key: 'route',
    label: 'Route',
    datum: turn.streaming ? `${name} · antwortet` : name,
    tone: turn.streaming ? 'live' : 'info',
    detail: detail.length ? detail : undefined
  };
}

function contextRow(turn: Turn): LedgerRow | undefined {
  const ctx = turn.envelope?.context;
  if (!ctx) return undefined;
  const parts: string[] = [];
  const detail: string[] = [];
  if (ctx.focus_file) {
    parts.push(baseName(ctx.focus_file));
    detail.push(ctx.focus_file);
  }
  if (ctx.included !== undefined) parts.push(`${ctx.included} ${ctx.included === 1 ? 'Datei' : 'Dateien'} gelesen`);
  if (ctx.withheld_count !== undefined) parts.push(`${ctx.withheld_count} zurückgehalten`);
  if (ctx.trimmed) parts.push(`${ctx.trimmed} gekürzt`);
  let tone: RowTone = 'info';
  if (ctx.ambiguous === true || (Array.isArray(ctx.ambiguous) && ctx.ambiguous.length > 0)) {
    parts.push('mehrdeutig, nichts gelesen');
    tone = 'warn';
    if (Array.isArray(ctx.ambiguous)) detail.push(...ctx.ambiguous);
  }
  if (parts.length === 0) return undefined;
  return { key: 'context', label: 'Kontext', datum: parts.join(' · '), tone, detail: detail.length ? detail : undefined };
}

function refusalRow(turn: Turn): LedgerRow | undefined {
  const r = turn.envelope?.refusal;
  if (!r) return undefined;
  const detail: string[] = [];
  if (r.reason) detail.push(r.reason);
  if (r.lane) detail.push(`Lane ${r.lane}`);
  if (r.provider) detail.push(`Anbieter ${r.provider}`);
  if (r.host) detail.push(`Ziel ${r.host}`);
  if (r.entrypoint_id) detail.push(r.entrypoint_id);
  return {
    key: 'refusal',
    label: 'Prüfung',
    datum: `${r.contract || 'Policy'} · ${r.verdict === 'deny' || !r.verdict ? 'abgelehnt' : r.verdict}`,
    tone: 'bad',
    detail: detail.length ? detail : undefined
  };
}

function editorRow(turn: Turn): LedgerRow | undefined {
  const n = turn.contextRefs?.length || 0;
  if (n === 0) return undefined;
  return { key: 'editor', label: 'Editor', datum: n === 1 ? 'Anhang übergeben' : `${n} Anhänge übergeben`, tone: 'info' };
}

function answerRow(turn: Turn, stamp: Stamp | undefined): LedgerRow | undefined {
  if (turn.streaming) {
    return { key: 'answer', label: 'Antwort', datum: turn.text ? 'wird geschrieben' : 'Ikarus denkt', tone: 'live' };
  }
  if (!stamp) return undefined;
  const bits = [stamp.word];
  if (stamp.origin) bits.push(stamp.origin);
  if (turn.seconds !== undefined) bits.push(waitLabel(turn.seconds));
  const tone: RowTone = stamp.kind === 'measured' ? 'ok' : stamp.kind === 'failed' ? (turn.halted ? 'warn' : 'bad') : 'info';
  const detail: string[] = [];
  if (turn.envelope?.stream_interrupted) detail.push('Stream unterbrochen; der Text kann unvollständig sein.');
  if (turn.conversationPersisted === false) detail.push('Nicht dauerhaft gespeichert.');
  return { key: 'answer', label: 'Antwort', datum: bits.join(' · '), tone, detail: detail.length ? detail : undefined, stamp: true };
}

function mismatchRow(turn: Turn): LedgerRow | undefined {
  const m = turn.envelope?.intent_mismatch;
  if (!m?.dropped_action) return undefined;
  return {
    key: 'mismatch',
    label: 'Abgleich',
    datum: `Aktion verworfen · Start ${m.start || '?'}, Ende ${m.final || '?'}`,
    tone: 'warn'
  };
}

function offerRow(turn: Turn): LedgerRow | undefined {
  if (turn.offerOutcome) {
    return { key: 'offer', label: 'Angebot', datum: turn.offerOutcome, tone: 'info' };
  }
  if (turn.offer) {
    const detail: string[] = [];
    if (turn.offer.args?.lane) detail.push(`Lane ${turn.offer.args.lane}`);
    if (turn.offer.args?.project) detail.push(`Projekt ${turn.offer.args.project}`);
    return {
      key: 'offer',
      label: 'Angebot',
      datum: `Aufgabe · ${turn.offer.args?.objective || 'ohne Ziel'}`,
      tone: 'live',
      detail: detail.length ? detail : undefined
    };
  }
  const act = turn.envelope?.act_offer;
  if (act?.objective) {
    const detail: string[] = [];
    if (act.reason) detail.push(act.reason);
    if (act.signal) detail.push(`Signal ${act.signal}`);
    return {
      key: 'offer',
      label: 'Angebot',
      datum: `wartet auf Bestätigung · ${act.objective}`,
      tone: 'info',
      detail: detail.length ? detail : undefined
    };
  }
  return undefined;
}

function dispatchRow(turn: Turn): LedgerRow | undefined {
  const d = turn.dispatch;
  if (!d) return undefined;
  const word = taskStateLabel(d);
  const tone: RowTone =
    word === 'läuft' || word === 'eingereiht' || word === 'übergeben'
      ? 'live'
      : word === 'fertig'
        ? 'ok'
        : word === 'fehlgeschlagen'
          ? 'bad'
          : 'warn';
  const bits = [word, d.id || 'ohne ID'];
  const lane = d.requested_lane || d.lane;
  if (lane) bits.push(`Lane ${lane}`);
  const detail: string[] = [];
  if (d.summary) detail.push(d.summary);
  if (d.error) detail.push(`Fehler: ${d.error}`);
  if (d.actual_providers.length > 0) detail.push(`ausgeführt über ${d.actual_providers.join(', ')}`);
  detail.push(`Übergabe: ${handoffLabel(d.applied)}`);
  if (d.applied_reason && d.applied_reason !== 'not finished yet' && d.applied_reason !== 'noch nicht abgeschlossen') {
    detail.push(d.applied_reason);
  }
  return { key: 'dispatch', label: 'Auftrag', datum: bits.join(' · '), tone, detail };
}

function cancelRow(turn: Turn): LedgerRow | undefined {
  if (!turn.cancellation) return undefined;
  const tone: RowTone =
    turn.cancellation === 'requested'
      ? 'warn'
      : turn.cancellation === 'confirmed' || turn.cancellation === 'already_terminal'
        ? 'info'
        : 'bad';
  return { key: 'cancel', label: 'Abbruch', datum: cancellationLabel(turn.cancellation), tone };
}

/**
 * The Protokoll of one Ikarus turn, in the order the kernel produced its
 * receipts: route, context, refusal, editor attachment, answer, intent
 * reconciliation, offer, dispatch, cancellation. A note turn has no ledger.
 */
export function ledgerFor(turn: Turn, labelOf: (id: string) => string | undefined): LedgerRow[] {
  if (turn.role !== 'ikarus') return [];
  const stamp = stampForTurn(turn, labelOf);
  const rows = [
    routeRow(turn, labelOf),
    contextRow(turn),
    refusalRow(turn),
    editorRow(turn),
    answerRow(turn, stamp),
    mismatchRow(turn),
    offerRow(turn),
    dispatchRow(turn),
    cancelRow(turn)
  ];
  return rows.filter((row): row is LedgerRow => row !== undefined);
}

/** The turn as it stands after the `final` frame, applied to a streaming turn. */
export function settleTurn(turn: Turn, payload: IkarusAskPayload, seconds: number | undefined, offerIsOpen: boolean): Turn {
  const envelope = envelopeFrom(payload);
  // Narrowed like the envelope: a final without a provider is stored as
  // having none, not as the string "undefined" wearing a stamp.
  const origin: TurnOrigin = {};
  if (typeof payload.intent === 'string' && payload.intent) origin.intent = payload.intent;
  if (typeof payload.provider_used === 'string' && payload.provider_used) origin.provider_used = payload.provider_used;
  if (typeof payload.model_used === 'string' && payload.model_used) origin.model_used = payload.model_used;
  return {
    ...turn,
    text: payload.assistant || turn.text,
    origin: Object.keys(origin).length > 0 ? origin : undefined,
    envelope,
    seconds,
    streaming: false,
    backendTurnId: positiveTurnId(payload.turn_id),
    conversationPersisted: payload.conversation_persisted,
    offer: offerIsOpen && payload.action ? payload.action : undefined
  };
}
