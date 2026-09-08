import type { EffortLevel, IkarusAskAction, IkarusAskPayload } from '@/shared/contracts';
import { projectDispatches, type DispatchEvidence } from './dispatch';
import type {
  ConversationCancellationStatus,
  ConversationDispatch,
  ConversationTurn,
  ConversationView,
  SubprocessCancellationEvidence,
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
  /** The model the server named before any text; drawn, never guessed. */
  model_used?: string;
  /** The server's own wall-clock budget for this run, when it says one. */
  timeout_s?: number;
}

/**
 * What the backend said about the language-model leg of one turn.
 *
 * Everything below `reason` is ADDITIVE and OPTIONAL (G1-UI-22): the fields
 * exist so a finished run can say what it cost, how long it took and why it
 * ended. They are all provider SELF-REPORTS relayed by the kernel. A cost
 * here is not the amount the budget ledger settled — that ledger prices
 * `anthropic_cli` at a flat worst case — so the row that draws it says so.
 */
export interface LlmSelection {
  provider?: string;
  requested?: string | null;
  auto_selected?: boolean;
  timeout_s?: number;
  max_attempts?: number;
  reason?: string;
  /** Attempts actually spent. Already emitted by the backend today. */
  attempts?: number;
  /** `null` means the provider ran and reported no cost; absent means no cost information exists. */
  cost_usd_measured?: number | null;
  cost_basis?: 'provider_reported' | 'estimate';
  duration_ms?: number;
  stop_reason?: string;
  subtype?: string;
  num_turns?: number;
  /** Untrusted provider output. Escaped, clipped, and never in the answer bubble. */
  stderr_tail?: string;
  model_used?: string;
  /** What the budget ledger actually charged, when the backend relays it. */
  ledger_charged_usd?: number;
  ledger_basis?: string;
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
  cancellationProcess?: SubprocessCancellationEvidence;
  /** Project-bound editor artifacts actually attached to this request. */
  contextRefs?: string[];
  /** When the spine recorded the turn; present only on a resumed turn. */
  createdTs?: string;
  /** The effort sent with this turn, when this browser sent it. */
  effort?: EffortLevel;
}

export type TurnActivityPhase = 'creating' | 'accepted' | 'routed' | 'writing' | 'cancelling';

export interface TurnActivity {
  phase: TurnActivityPhase;
  /** Short, user-facing wording derived only from fields already observed. */
  label: string;
}

/**
 * The live sentence for one turn. This is deliberately not a plan or a
 * reasoning trace: it translates browser/request facts that already exist on
 * `Turn` into useful cadence while the final receipt is still outstanding.
 */
export function activityForTurn(
  turn: Turn,
  labelOf: (id: string) => string | undefined
): TurnActivity | undefined {
  if (turn.role !== 'ikarus' || !turn.streaming) return undefined;
  if (turn.cancellation === 'requested') {
    return { phase: 'cancelling', label: 'Abbruch angefordert' };
  }

  const provider = turn.started?.provider_used || '';
  const providerLabel = provider === 'deterministic'
    ? 'Lokaler Index'
    : provider
      ? labelOf(provider) || provider
      : '';

  if (turn.text) {
    return {
      phase: 'writing',
      label: providerLabel ? `${providerLabel} antwortet` : 'Antwort entsteht'
    };
  }
  if (turn.started) {
    return {
      phase: 'routed',
      label: providerLabel ? `${providerLabel} ist ausgewählt` : 'Route ist ausgewählt'
    };
  }
  if (turn.requestId !== undefined) {
    return { phase: 'accepted', label: 'Anfrage angenommen' };
  }
  return { phase: 'creating', label: 'Anfrage wird angelegt' };
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

function int(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : undefined;
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
    // ---- additive execution evidence (G1-UI-22) ----
    // The voice lane (G1-IKARUS-36) nests its execution evidence under
    // `llm.invocation`; a flat block is accepted too. When both carry a key
    // the nested one wins: it is the measured invocation, not a summary.
    const src: Record<string, unknown> = isRecord(value.llm.invocation)
      ? { ...value.llm, ...value.llm.invocation }
      : value.llm;
    const spent = int(src.attempts);
    if (spent !== undefined) llm.attempts = spent;
    // `null` survives on purpose: "ran, reported no cost" is not "no cost field".
    if ('cost_usd_measured' in src) {
      const cost = src.cost_usd_measured;
      if (cost === null) llm.cost_usd_measured = null;
      else {
        const usd = num(cost);
        if (usd !== undefined && usd >= 0) llm.cost_usd_measured = usd;
      }
    }
    // Exactly two literals. An unrecognised basis is DROPPED, never upgraded
    // to `gemessen` by a malformed label.
    if (src.cost_basis === 'provider_reported' || src.cost_basis === 'estimate') {
      llm.cost_basis = src.cost_basis;
    }
    const took = num(src.duration_ms);
    if (took !== undefined && took >= 0) llm.duration_ms = took;
    const stop = str(src.stop_reason);
    if (stop) llm.stop_reason = stop;
    const subtype = str(src.subtype);
    if (subtype) llm.subtype = subtype;
    const providerTurns = int(src.num_turns);
    if (providerTurns !== undefined) llm.num_turns = providerTurns;
    const stderrTail = str(src.stderr_tail);
    if (stderrTail) llm.stderr_tail = stderrTail;
    const ran = str(src.model_used);
    if (ran) llm.model_used = ran;
    const charged = num(src.ledger_charged_usd);
    if (charged !== undefined && charged >= 0) llm.ledger_charged_usd = charged;
    const chargedBasis = str(src.ledger_basis);
    if (chargedBasis) llm.ledger_basis = chargedBasis;
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

/**
 * A stored id is only a hint until the canonical spine proves both its
 * identity and project. The proof is the server's unbounded cross-kind binding
 * field, never the bounded transcript tail. Empty, legacy, mixed, or corrupt
 * views fail closed: they must never be displayed under, or appended from,
 * another project's chrome.
 */
export function conversationConfirmsProject(
  view: ConversationView | undefined,
  threadId: string,
  project: string
): boolean {
  if (!view || !threadId || !project) return false;
  if (!view.exists || view.conversation_id !== threadId) return false;
  return view.quarantined !== true
    && view.project_binding?.state === 'bound'
    && view.project_binding.project === project;
}

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
export interface OpenDispatch extends DispatchEvidence {
  turnId?: number;
  /** when the dispatch was linked, from the link row */
  since?: string;
  /** what the dispatch said it was, from the dispatched event */
  summary?: string;
}

export function openDispatchesFrom(view: ConversationView | undefined, project = ''): {
  items: OpenDispatch[];
  unresolved: number;
} {
  const projected = projectDispatches(view, project);
  const byRef = new Map((view?.open_dispatches || []).map((row) => [row.link?.dispatch_ref, row]));
  return {
    unresolved: projected.unresolved,
    items: projected.items.map((item) => ({
      ...item,
      turnId: positiveTurnId(byRef.get(item.ref)?.link?.turn_id),
      since: item.startedAt,
      summary: item.description || str(byRef.get(item.ref)?.latest?.summary)
    }))
  };
}

/* ---------------------------------------------------------------- labels */

/** Anything that reports a bus state. Widened from `TaskSnapshot` so the
 *  one-shot read (`getTask`) and the stream share one vocabulary instead of
 *  growing a second, drifting copy. */
export interface TaskStateLike {
  state: string;
  stalled?: boolean;
  timed_out?: boolean;
}

export function taskStateLabel(task: TaskStateLike): string {
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

/**
 * Copy for an authoritative terminal `cancelled` state. The terminal state
 * alone does not prove that the cancellation request was confirmed: after a
 * crash or an external durable cancellation the backend can deliberately
 * report `unknown` here.
 */
export function cancelledObservation(status?: ConversationCancellationStatus): {
  cancellation: ConversationCancellationStatus;
  text: string;
} {
  const cancellation = status || 'unknown';
  return {
    cancellation,
    text: cancellation === 'confirmed'
      ? 'Der Server hat den Abbruch bestätigt.'
      : `Der Turn wurde als abgebrochen gemeldet. ${cancellationLabel(cancellation)}.`
  };
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

/**
 * Frozen glosses for provider end states. ONLY values that were actually
 * observed on a run are translated (MEASURED 2026-09-08, Claude Code 2.1.263:
 * `tool_use`, `error_max_turns`, `error_max_budget_usd`, `success`). An
 * unmeasured value is printed verbatim — inventing German for a state nobody
 * saw would be the surface authoring a claim the provider did not make.
 */
export const PROVIDER_END_DE: Readonly<Record<string, string>> = {
  success: 'regulär beendet',
  tool_use: 'wollte Werkzeuge benutzen',
  error_max_turns: 'Turn-Limit des Anbieters erreicht',
  error_max_budget_usd: 'Budget-Limit des Anbieters erreicht'
};

export function endLabel(value: string): string {
  return PROVIDER_END_DE[value] ?? value;
}

export const COST_BASIS_DE = {
  provider_reported: 'gemessen',
  estimate: 'geschätzt',
  unknown: 'Basis nicht angegeben'
} as const;

export const HONESTY_DE = {
  selfReport: 'Anbieter-Selbstauskunft; der Budget-Ledger verbucht nach eigener Preisliste.',
  derived: 'Der Text oben stammt unverändert vom Server; diese Zeile ist aus den Feldern der Antwort abgeleitet.',
  noReason: 'Kein Grund übermittelt',
  nomination: 'Nominierung, keine Übernahme. Nichts wird automatisch gemerged oder promotet; die Freigabe bleibt beim Owner.',
  flagIgnored: 'Der Server meldet „requires_confirmation: false“. Diese Oberfläche fragt trotzdem.',
  stderr: 'Provider-stderr (gekürzt, ungeprüft)'
} as const;

/** German money, at the precision a two-decimal USD figure actually carries. */
export function costLabel(usd: number): string {
  if (!Number.isFinite(usd) || usd < 0) return '';
  if (usd === 0) return '0,00 USD';
  if (usd < 0.005) return 'unter 0,01 USD';
  return `${usd.toFixed(2).replace('.', ',')} USD`;
}

/**
 * A provider-reported duration. Unlike `waitLabel`, whose seconds come from a
 * browser round trip, this one is a millisecond measurement, so tenths are
 * resolvable — but past a hundred seconds a tenth is noise, not information.
 */
export function durationLabel(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return '';
  if (seconds >= 100) return `${Math.round(seconds)} s`;
  return `${seconds.toFixed(1).replace('.', ',')} s`;
}

/** How the cockpit reads an offered action, for the panel AND the request. */
export interface OfferSubject {
  /** verbatim; '' when the server sent none */
  kind: string;
  project: string;
  lane: string;
  objective: string;
  /** only when a full 40-character lowercase hex revision arrived */
  sourceRevision?: string;
  revisionState: 'absent' | 'valid' | 'unreadable';
  /** descriptive server data; NEVER this surface's authority to act */
  requiresConfirmation: boolean;
  /** whether this cockpit has an endpoint for that kind at all */
  executable: boolean;
}

/**
 * The one derivation of an offered action, used by BOTH the confirm panel and
 * the queue request. Deriving them twice is how a surface ends up showing one
 * project and posting another; the fallbacks below are exactly the fallbacks
 * the request uses, which is the whole point.
 */
export function offerSubject(action: unknown, fallbackProject: string): OfferSubject | undefined {
  if (!isRecord(action)) return undefined;
  const args = isRecord(action.args) ? action.args : {};
  const kind = str(action.kind) || '';
  const raw = args.source_revision;
  let revisionState: OfferSubject['revisionState'] = 'absent';
  let sourceRevision: string | undefined;
  if (raw !== undefined && raw !== null && raw !== '') {
    if (typeof raw === 'string' && /^[0-9a-f]{40}$/.test(raw)) {
      revisionState = 'valid';
      sourceRevision = raw;
    } else {
      // A shortened, uppercased or non-hex value is NOT normalised into a
      // revision. Displaying `HEAD` as a revision would be an invention.
      revisionState = 'unreadable';
    }
  }
  return {
    kind,
    project: str(args.project) || fallbackProject,
    lane: str(args.lane) || 'local_only',
    objective: str(args.objective) || '',
    sourceRevision,
    revisionState,
    requiresConfirmation: action.requires_confirmation !== false,
    executable: kind === 'queue_task'
  };
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
  | 'execution'
  | 'answer'
  | 'failure'
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
  const startedModel = turn.started?.model_used;
  if (startedModel && !name.toLowerCase().includes(startedModel.toLowerCase())) detail.push(`Modell ${startedModel}`);
  return {
    key: 'route',
    label: 'Route',
    datum: turn.streaming ? `${name} · ausgewählt` : name,
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

function answerRow(
  turn: Turn,
  stamp: Stamp | undefined,
  labelOf: (id: string) => string | undefined
): LedgerRow | undefined {
  if (turn.streaming) {
    const activity = activityForTurn(turn, labelOf);
    if (!activity) return undefined;
    return { key: 'answer', label: 'Antwort', datum: activity.label, tone: 'live' };
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

/**
 * WHAT THE RUN COST AND HOW IT ENDED — one row, not a dashboard.
 *
 * Every fragment is a relayed provider self-report. The row exists only when
 * at least one of them arrived; it never pads itself with `unbekannt`. The
 * cost is labelled with its basis and carries the ledger caveat, because the
 * kernel prices this vendor at a flat worst case and the two numbers are
 * different facts about the same call.
 */
function executionRow(turn: Turn): LedgerRow | undefined {
  const llm = turn.envelope?.llm;
  if (!llm) return undefined;
  const hasCostKey = 'cost_usd_measured' in llm;
  const end = llm.subtype || llm.stop_reason;
  if (llm.duration_ms === undefined && !hasCostKey && !end && llm.num_turns === undefined) return undefined;

  const parts: string[] = [];
  if (llm.duration_ms !== undefined) parts.push(`${durationLabel(llm.duration_ms / 1000)} (Anbieter)`);
  let showedCost = false;
  if (typeof llm.cost_usd_measured === 'number') {
    parts.push(`${costLabel(llm.cost_usd_measured)} (${COST_BASIS_DE[llm.cost_basis || 'unknown']})`);
    showedCost = true;
  } else if (hasCostKey) {
    parts.push('Kosten nicht gemessen');
  }
  if (end) parts.push(`Ende: ${endLabel(end)}`);
  let turnsInDatum = false;
  if (parts.length === 0 && llm.num_turns !== undefined) {
    parts.push(`${llm.num_turns} Anbieter-Turns`);
    turnsInDatum = true;
  }
  if (parts.length === 0) return undefined;

  const detail: string[] = [];
  if (turn.seconds !== undefined) {
    detail.push(`Hier gemessen: ${waitLabel(turn.seconds)} (kompletter Rundweg inkl. Verlauf anlegen)`);
  }
  if (!turnsInDatum && llm.num_turns !== undefined) detail.push(`Turns des Anbieters: ${llm.num_turns}`);
  if (llm.attempts !== undefined) detail.push(`Versuche: ${llm.attempts}`);
  if (llm.subtype && llm.stop_reason && llm.subtype !== llm.stop_reason) detail.push(`Stop-Grund: ${llm.stop_reason}`);
  const envModel = turn.envelope?.model_used;
  if (llm.model_used && llm.model_used !== envModel) detail.push(`Modell laut Lauf: ${llm.model_used}`);
  if (showedCost) detail.push(HONESTY_DE.selfReport);
  if (llm.ledger_charged_usd !== undefined) {
    detail.push(`Vom Budget-Ledger verbucht: ${costLabel(llm.ledger_charged_usd)}${llm.ledger_basis ? ` (${llm.ledger_basis})` : ''}`);
  }
  if (llm.stderr_tail) detail.push(`${HONESTY_DE.stderr}: ${llm.stderr_tail.slice(0, 500)}`);

  const tone: RowTone = end && end.startsWith('error_')
    ? 'bad'
    : llm.cost_usd_measured === null
      ? 'warn'
      : 'info';
  return { key: 'execution', label: 'Ausführung', datum: parts.join(' · '), tone, detail: detail.length ? detail : undefined };
}

/**
 * WHY IT ENDED WITHOUT AN ANSWER, in German, on the collapsed spine.
 *
 * Before this row the reader of a dead 150-second turn saw exactly
 * `FEHLGESCHLAGEN · 150 s`. The reason is derived from structured fields, never
 * from translating the server's own sentence: the bubble above keeps that
 * sentence byte-identical, and the detail line says this row is derived.
 *
 * A refusal already has its own `Prüfung` row and owns that fact, so this row
 * stays out of the way whenever one is present.
 */
function failureRow(turn: Turn, stderrShownElsewhere: boolean): LedgerRow | undefined {
  const env = turn.envelope;
  if (env?.refusal) return undefined;
  const failed = env?.intent === 'error' || turn.origin?.intent === 'error';
  const interrupted = env?.stream_interrupted === true;
  if (!failed && !interrupted) return undefined;
  const llm = env?.llm;

  let datum: string;
  if (llm?.subtype) datum = `Anbieter beendet: ${endLabel(llm.subtype)}`;
  else if (llm?.stop_reason) datum = `Anbieter beendet: ${endLabel(llm.stop_reason)}`;
  else if (interrupted) datum = 'Stream ohne vollständige Antwort beendet';
  else if (llm?.attempts !== undefined && llm.attempts >= 1) datum = `Kein nutzbares Ergebnis nach ${llm.attempts} Versuch(en)`;
  else datum = HONESTY_DE.noReason;

  const detail: string[] = [HONESTY_DE.derived];
  if (llm?.stderr_tail && !stderrShownElsewhere) {
    detail.push(`${HONESTY_DE.stderr}: ${llm.stderr_tail.slice(0, 500)}`);
  }
  return { key: 'failure', label: 'Fehler', datum, tone: failed ? 'bad' : 'warn', detail };
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
  const localExit = turn.requestId !== undefined
    && turn.cancellationProcess?.request_id === turn.requestId
    && turn.cancellationProcess.process_exited === true;
  return {
    key: 'cancel', label: 'Abbruch', datum: cancellationLabel(turn.cancellation), tone,
    detail: [localExit
      ? 'Lokaler CLI-Prozess beendet · Remote-Termination nicht bewiesen'
      : 'Lokaler Prozessabbruch und Remote-Termination nicht bewiesen']
  };
}

/**
 * The Protokoll of one Ikarus turn, in the order the kernel produced its
 * receipts: route, context, refusal, editor attachment, answer, intent
 * reconciliation, offer, dispatch, cancellation. A note turn has no ledger.
 */
export function ledgerFor(turn: Turn, labelOf: (id: string) => string | undefined): LedgerRow[] {
  if (turn.role !== 'ikarus') return [];
  const stamp = stampForTurn(turn, labelOf);
  const execution = executionRow(turn);
  const rows = [
    routeRow(turn, labelOf),
    contextRow(turn),
    refusalRow(turn),
    editorRow(turn),
    execution,
    answerRow(turn, stamp, labelOf),
    failureRow(turn, Boolean(execution && turn.envelope?.llm?.stderr_tail)),
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
    offer: offerIsOpen && !payload.stream_interrupted && payload.action ? payload.action : undefined
  };
}


/* -------------------------------------------------------------- receipts */

/** Everything the surface derives about ONE turn, in one object. */
export interface TurnReceipt {
  stamp: Stamp | undefined;
  ledger: LedgerRow[];
  activity: TurnActivity | undefined;
  cites: Citation[];
}

/**
 * INCREMENTAL DERIVATION, keyed by turn object identity.
 *
 * The whole receipt set used to be recomputed from scratch on every batched
 * stream delta, because `setTurns((prev) => prev.map(...))` always returns a
 * new array: a citation regex ran over every settled answer in the thread once
 * per animation frame. Streaming replaces exactly ONE turn object per patch,
 * so an unchanged turn is reference-identical and its receipt can be reused —
 * which also gives `memo(Ledger)` a stable `rows` array to compare.
 *
 * Correctness rests on that identity discipline. A future `setTurns` that
 * rebuilds every turn would silently restore the per-frame cost; the counting
 * case in `conversation.spec.ts` is the guard against exactly that.
 */
export function createReceiptCache(
  labelOf: (id: string) => string | undefined,
  resolveModule: (needle: string) => string | undefined
): (turns: readonly Turn[]) => TurnReceipt[] {
  const cache = new WeakMap<Turn, TurnReceipt>();
  return (turns) => turns.map((turn) => {
    const hit = cache.get(turn);
    if (hit) return hit;
    const receipt: TurnReceipt = {
      stamp: stampForTurn(turn, labelOf),
      ledger: ledgerFor(turn, labelOf),
      activity: activityForTurn(turn, labelOf),
      cites: turn.role === 'ikarus' && !turn.streaming ? citationsFrom(turn.text, resolveModule) : []
    };
    cache.set(turn, receipt);
    return receipt;
  });
}
