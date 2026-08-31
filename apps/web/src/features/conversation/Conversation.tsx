import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import {
  ApiError,
  cancelConversationTurn,
  createConversationTurn,
  getConversation,
  getEditorContext,
  getRuntimeStatus,
  newConversation,
  observeConversationTurn,
  queueTask,
  streamTask
} from '@/shared/api';
import type {
  ConversationCancellation,
  ConversationCancellationStatus,
  ConversationDispatch,
  ConversationTurnRequest,
  EditorContextReceipt,
  TaskSnapshot
} from '@/shared/api';
import type { IkarusAskAction, IkarusAskPayload, RuntimeRow } from '@/shared/contracts';
import {
  armVariants,
  bubbleVariants,
  pressProps,
  revealVariants,
  transitionFor,
  useReducedMotionPref
} from '@/shared/ui/motion';
import { recordAutonomy, type AutonomyLevel } from '@/features/settings/autonomy';
import { ContextPlan } from '@/features/knowledge/ContextPlan';
import { MarkdownMessage } from './MarkdownMessage';
import { shortLabel } from '@/features/twin/graph';

/**
 * The conversation with Ikarus.
 *
 * Three rules decide everything here:
 *
 * 1. The provenance stamp reports what actually produced the answer. An answer
 *    read off the local structure index is stamped GEMESSEN; an answer a model
 *    wrote is stamped with the model that wrote it. The stamp is never
 *    decoration and never the same word for both, because that is exactly the
 *    collapse ("everything says MEASURED") this project keeps deleting.
 * 2. The composer is live or it is not there. No greyed-out send button that
 *    does nothing, no suggestion chips that are pictures of suggestions.
 * 3. The thread is DURABLE. Every turn carries a `conversation_id`, so the
 *    backend appends it via `daedalus/conversation.py` and the thread survives
 *    a reload — the difference between a chat and a row of one-shot answers.
 *    Agentic-J (arXiv 2606.02080) names the same property "chat history is
 *    preserved across sessions"; the store for it already existed here and
 *    simply had no caller.
 */

/** What the backend said produced one answer, kept verbatim. */
export interface TurnOrigin {
  intent?: string;
  provider_used?: string;
  model_used?: string;
}

export interface Turn {
  role: 'you' | 'ikarus';
  text: string;
  /** Browser-local identity; dispatch progress is joined to this, never an index. */
  localId?: string;
  /** Canonical conversation-spine identity for this exact exchange. */
  backendTurnId?: number;
  /** Whether the backend proved that this exchange reached the durable spine. */
  conversationPersisted?: boolean;
  /**
   * The origin is STORED, the stamp is DERIVED at render.
   *
   * It used to be the other way round: `stampFor()` ran once, when the turn
   * arrived, and the string it produced was frozen onto the turn. A resumed
   * thread is read on mount, before `/api/runtimes/status` has answered, so
   * every stamp on it was rendered from an empty runtime list and said
   * `MODELL · claude_code_cli` — an internal id — forever. Same bug, same
   * cause, as the citations below.
   */
  origin?: TurnOrigin;
  /** the browser stopped observing this turn; backend cancellation is unproven */
  halted?: boolean;
  /**
   * How long this answer took, measured in this browser. Absent means NOT
   * MEASURED — a resumed turn carries no duration, because the store does not
   * record one and inventing it from two timestamps would measure the
   * reader's thinking time as well.
   */
  seconds?: number;
  streaming?: boolean;
  /** an action Ikarus offered on this turn, still awaiting an answer */
  offer?: IkarusAskAction;
  /** what happened to that offer, once something happened */
  offerOutcome?: string;
  /** live measured state of the task this exact turn launched */
  dispatch?: TaskSnapshot;
  /** Canonical id of the generation request, separate from the persisted turn. */
  requestId?: number;
  /** An explicit server cancellation request is a separate fact from closing observation. */
  cancellation?: ConversationCancellationStatus;
  /** Project-bound editor artifacts actually attached to this request. */
  contextRefs?: string[];
}

function taskStateLabel(task: TaskSnapshot): string {
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

function handoffLabel(applied: boolean | null): string {
  // Older task reports name this field `applied`. In the conversation it is
  // only an observed handoff result, never proof that a repository changed or
  // that promotion happened.
  return applied === true ? 'bestätigt' : applied === false ? 'nicht bestätigt' : 'unklar';
}

function cancellationLabel(status: ConversationCancellationStatus): string {
  switch (status) {
    case 'requested': return 'Abbruch angefordert – Bestätigung steht aus';
    case 'confirmed': return 'Abbruch bestätigt';
    case 'not_supported': return 'Server unterstützt keinen Abbruch-Request';
    case 'already_terminal': return 'Turn war bereits abgeschlossen';
    default: return 'Abbruchzustand unbekannt';
  }
}

function clientId(prefix: string): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return `${prefix}_${crypto.randomUUID()}`;
  } catch { /* a timestamp fallback remains an idempotency key for this page */ }
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2)}`;
}

type EditorAttachment =
  | { state: 'idle' }
  | { state: 'loading'; ref: string }
  | { state: 'attached'; ref: string; context: EditorContextReceipt }
  | { state: 'withheld'; ref: string; reason: string; context?: EditorContextReceipt }
  | { state: 'unavailable'; ref: string; reason: string };

function editorContextRefFromUrl(): string {
  try { return new URLSearchParams(window.location.search).get('context_ref')?.trim() || ''; } catch { return ''; }
}

function positiveTurnId(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isSafeInteger(value) && value > 0 ? value : undefined;
}

function resumedDispatch(dispatch: ConversationDispatch): TaskSnapshot | undefined {
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

/** One identifier Ikarus named, and the module on the map it resolves to. */
export interface Citation {
  seen: string;
  module: string;
}

/**
 * How long each route has taken to answer, in THIS session.
 *
 * The picker decides the shape of the wait — measured on this machine, the
 * local index answers a status question in 0.3s and the Claude CLI takes
 * 42.4s — and until now the control said nothing about that at all. This is
 * the honest version of those numbers: the page reports what it has actually
 * timed, keyed by the route that served it, and shows nothing for a route it
 * has never used. A number nobody measured is not printed.
 */
export type WaitLedger = Record<string, number>;

/** One conversation id per project, so switching projects switches threads. */
const THREAD_KEY = 'daedalus-thread';

function loadThreadId(project: string): string {
  try {
    return localStorage.getItem(`${THREAD_KEY}:${project}`) || '';
  } catch {
    return '';
  }
}

function saveThreadId(project: string, id: string): void {
  try {
    localStorage.setItem(`${THREAD_KEY}:${project}`, id);
  } catch {
    /* storage blocked — the thread still holds for this session */
  }
}

/**
 * The wait ledger outlives the tab, because a measurement does.
 *
 * Kept in session state only, the picker's third column was empty on every
 * fresh load — the one moment the reader is choosing a route blind. These are
 * waits THIS browser timed on THIS project; the legend in the menu says
 * "zuletzt gemessen" rather than promising anything about the next call.
 */
const WAIT_KEY = 'daedalus-waits';

function loadWaits(project: string): WaitLedger {
  try {
    const raw = localStorage.getItem(`${WAIT_KEY}:${project}`);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return {};
    const out: WaitLedger = {};
    for (const [id, seconds] of Object.entries(parsed as Record<string, unknown>)) {
      // Anything that is not a plausible number is dropped rather than drawn:
      // storage is writable by anything, and this column is read as evidence.
      if (typeof seconds === 'number' && Number.isFinite(seconds) && seconds >= 0 && seconds < 3600) {
        out[id] = seconds;
      }
    }
    return out;
  } catch {
    return {};
  }
}

function saveWaits(project: string, waits: WaitLedger): void {
  try {
    localStorage.setItem(`${WAIT_KEY}:${project}`, JSON.stringify(waits));
  } catch {
    /* storage blocked — the ledger still holds for this session */
  }
}

type StampKind = 'measured' | 'model' | 'failed';

/**
 * A stamp is a word and an origin, not one string.
 *
 * The word stays in the product's own capitals — the invitation on the empty
 * page names `GEMESSEN` literally, so the two must not drift apart. The origin
 * beside it keeps its own case, and it is flagged when it is an internal ID
 * rather than a name: the runtime list is a separate 16.6s request that
 * regularly times out on this machine, and when it has not arrived the honest
 * rendering of `claude_code_cli` is the identifier itself, set as one. A raw
 * id typeset as if it were a product name is a small lie about what is known.
 */
interface Stamp {
  word: string;
  origin?: string;
  originIsId?: boolean;
  kind: StampKind;
}

function stampFor(origin: TurnOrigin, labelOf: (id: string) => string | undefined): Stamp {
  const provider = origin.provider_used || '';
  if (origin.intent === 'error') return { word: 'FEHLGESCHLAGEN', kind: 'failed' };
  if (provider === 'deterministic' || origin.intent === 'status' || origin.intent === 'distill') {
    return { word: 'GEMESSEN', origin: 'lokaler Index', kind: 'measured' };
  }
  const named = provider ? labelOf(provider) : undefined;
  const runtime = named || provider || 'unbekannt';
  // `claude_code_cli` + model `claude` printed the same word twice. A model
  // name earns its place only when the runtime's own name does not contain it.
  const model = origin.model_used || '';
  const extra = model && !runtime.toLowerCase().includes(model.toLowerCase()) ? ` · ${model}` : '';
  return { word: 'MODELL', origin: `${runtime}${extra}`, originIsId: !named && Boolean(provider), kind: 'model' };
}

/**
 * Pull identifiers out of an answer so the reader can jump to them.
 *
 * Resolved eagerly here and DERIVED at render, never frozen onto the turn:
 * the map arrives after the thread does, so a citation list computed while
 * `resolveModule` still had an empty index was empty forever. Measured on a
 * four-turn thread naming `daedalus/spine/attempt.py`: zero citations drawn,
 * both files present on the map.
 */
function citationsFrom(text: string, resolve: (id: string) => string | undefined): Citation[] {
  // Keyed by the MODULE, not by the string that named it: one answer wrote
  // `daedalus/spine/attempt.py` and `attempt.py` about the same file, and the
  // receipt drew two links to one place.
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

/** Seconds while a turn is out. Past a minute a bare `73s` stops being read. */
function elapsedLabel(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
}

/**
 * A measured wait, in German decimal notation and at a precision the
 * measurement can carry: tenths under ten seconds, whole seconds above.
 * `44,6 s` and `0,3 s` are both true; `44,63 s` claims a millisecond the
 * round trip cannot resolve.
 */
function waitLabel(seconds: number): string {
  if (seconds >= 10) return `${Math.round(seconds)} s`;
  return `${seconds.toFixed(1).replace('.', ',')} s`;
}

/**
 * IKARUS ANSWERS IN MARKDOWN, AND THIS PAGE USED TO PRINT THE MARKS.
 *
 * Measured against the live backend: a Claude CLI answer arrives as
 * `**\`daedalus/spine/attempt.py\`** is the single seam …` and the transcript
 * drew the asterisks and the backticks. This is not a Markdown renderer and
 * must not become one — it handles exactly the two inline marks the backend
 * was observed to emit, plus the blank line between paragraphs. Anything else
 * (headings, lists, links) stays verbatim on screen, which is honest: an
 * unhandled mark is visible rather than silently swallowed.
 */
type Piece = { kind: 'text' | 'code'; value: string; strong?: boolean };

const MARKS = /`([^`\n]+)`|\*\*([^*\n]+)\*\*/;

function piecesIn(text: string, strong = false): Piece[] {
  const out: Piece[] = [];
  let at = 0;
  let m: RegExpExecArray | null;
  const re = new RegExp(MARKS.source, 'g');
  while ((m = re.exec(text)) !== null) {
    if (m.index > at) out.push({ kind: 'text', value: text.slice(at, m.index), strong });
    if (m[1] !== undefined) {
      // A backtick span is a leaf: what is inside it is verbatim by definition.
      out.push({ kind: 'code', value: m[1], strong });
    } else {
      /* `**\`web_api.py\`**` is the shape this backend actually emits, and the
         outer `**` wins on position, so treating strong as a leaf printed the
         backticks inside a bold run. Emphasis is a wrapper: read it again. */
      out.push(...piecesIn(m[2], true));
    }
    at = m.index + m[0].length;
  }
  if (at < text.length) out.push({ kind: 'text', value: text.slice(at), strong });
  return out;
}

/**
 * Why a runtime is not available, in its own words.
 *
 * The backend already distinguishes these four; collapsing them to "nicht
 * verfügbar" throws away the only thing that tells the reader whether to start
 * Ollama or to put a key in a file. Unknown statuses fall through verbatim
 * rather than being rounded to a friendly lie.
 */
const AUTH_NOTE: Record<string, string> = {
  cli_detected: 'CLI gefunden',
  local_unreachable: 'nicht erreichbar',
  unavailable: 'nicht gefunden',
  not_configured: 'kein Schlüssel hinterlegt'
};

/** What a runtime row can honestly say about itself on one line. */
function runtimeNote(r: RuntimeRow): string {
  const bits = [r.mode];
  if (r.selected_model) bits.push(r.selected_model);
  else if (r.version) {
    // Versions arrive as `2.1.233 (Claude Code)` and `codex-cli 0.146.0`. The
    // product name is already the row's label, so only the number is new.
    const num = r.version.match(/\d[\w.+-]*/);
    if (num) bits.push(num[0]);
  }
  return bits.join(' · ');
}

/* Three glyphs, drawn rather than typed. `↑` and `▾` are whatever the body
   face happens to have; these are the same stroke weight in all six themes and
   they take the theme's colour. */
function SendGlyph() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <path
        d="M8 13V3.6M4.2 7.4 8 3.6l3.8 3.8"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function StopGlyph() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <rect x="5" y="5" width="6" height="6" rx="1" fill="currentColor" />
    </svg>
  );
}

/**
 * The caret turns over when the menu opens — an acknowledgement, so the `ack`
 * tier. It is driven from JS rather than by a CSS transition because
 * `--dur-fast` / `--ease` are declared in `styles.css`, which the cockpit
 * surface deliberately never loads (see main.tsx). On this surface those
 * custom properties are undefined, so a CSS transition written against them
 * would silently not run. Reported to the Bewegung lane.
 */
function Chevron({ open, reduced }: { open: boolean; reduced: boolean }) {
  return (
    <motion.svg
      className="brain-caret"
      data-motion="caret"
      viewBox="0 0 12 12"
      width="12"
      height="12"
      aria-hidden="true"
      focusable="false"
      initial={false}
      animate={{ rotate: open ? 180 : 0 }}
      transition={transitionFor('ack', reduced)}
    >
      <path d="M3 4.75 6 7.75 9 4.75" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </motion.svg>
  );
}

/** Whether the runtime list could be read at all. */
type RuntimeState = 'laden' | 'ok' | 'fehler';

interface BrainPickerProps {
  runtimes: RuntimeRow[];
  /** whether that list is the answer or the absence of one */
  state: RuntimeState;
  /** the chosen runtime id; empty means the backend routes */
  value: string;
  onChange?: (id: string) => void;
  /** what each route has actually cost, timed in this session */
  waits: WaitLedger;
  /** which route the automatic setting last resolved to */
  lastRoute: string;
  /** a runtime id in the reader's words, or nothing when that is not known */
  labelOf: (id: string) => string | undefined;
  /** ask the backend again after the list could not be read */
  onRecheck?: () => void | Promise<void>;
}

/**
 * WHO ANSWERS.
 *
 * This was a native `<select>` carrying OS chrome and an OS arrow, marooned at
 * the far left of a bar with 340px of nothing beside it. It is not a
 * preference — it decides the whole shape of the wait. Measured on this
 * machine against the live backend: a status question off the local index
 * comes back in 0.3s with no model in it, and the same question through the
 * Claude CLI takes 42.4s.
 *
 * Three things follow from that, and they are the whole design of this
 * control:
 *
 *  1. It sits INSIDE the composer well, first on the rail that says what will
 *     happen when you press send — who answers, what is on the stage, what
 *     would be read. Not in a strip at the top of the page, three unrelated
 *     things away from the wait it causes.
 *  2. It carries a role label (`Antwortet`), because a control that shows only
 *     its current value reads as a status readout.
 *  3. Every row shows what that runtime IS (`cli · 2.1.233`) and, once this
 *     session has actually timed it, what it COST. An untimed route shows
 *     nothing rather than a plausible number.
 *
 * Runtimes that are not available are listed with the reason, outside the
 * listbox where nothing can be clicked. A row you cannot pick is information,
 * never an affordance.
 */
function BrainPicker({ runtimes, state, value, onChange, waits, lastRoute, labelOf, onRecheck }: BrainPickerProps) {
  const [open, setOpen] = useState(false);
  const reduced = useReducedMotionPref();
  const reveal = useMemo(() => revealVariants(reduced), [reduced]);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const options = useRef<(HTMLLIElement | null)[]>([]);

  const ready = runtimes.filter((r) => r.available);
  const off = runtimes.filter((r) => !r.available);
  /**
   * '' (automatic), then the local index, then every available runtime in API
   * order.
   *
   * The local index is a route, not an absence of one: `provider:
   * 'deterministic'` is accepted by `/api/ikarus/ask` and measured here at
   * 158ms against 30s for the Claude CLI — the single comparison this control
   * exists to make. It had no row, so the fastest thing the product can do was
   * the one option you could not ask for.
   */
  const ids = ['', 'deterministic', ...ready.map((r) => r.id)];
  const chosen = ready.find((r) => r.id === value);
  // A value we cannot resolve is reported as itself, not rounded to
  // "Automatisch" — a control must be able to say it does not recognise its
  // own state.
  const label = !value ? 'Automatisch' : value === 'deterministic' ? 'Lokaler Index' : chosen?.label || value;

  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  }, []);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', away);
    return () => document.removeEventListener('pointerdown', away);
  }, [open]);

  // Opening puts focus on the row that is already selected, so the first
  // ArrowDown moves from where you are rather than from the top.
  useEffect(() => {
    if (!open) return;
    const at = Math.max(0, ids.indexOf(value));
    options.current[at]?.focus();
    // ids is derived from runtimes/value, both in the dep list already
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const pick = useCallback(
    (id: string) => {
      onChange?.(id);
      close(true);
    },
    [close, onChange]
  );

  const onOptionKey = useCallback(
    (e: React.KeyboardEvent, index: number) => {
      const last = ids.length - 1;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End') {
        e.preventDefault();
        const to =
          e.key === 'Home' ? 0 : e.key === 'End' ? last : e.key === 'ArrowDown' ? Math.min(last, index + 1) : Math.max(0, index - 1);
        options.current[to]?.focus();
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        pick(ids[index]);
      } else if (e.key === 'Escape' || e.key === 'Tab') {
        close(true);
      }
    },
    [close, ids, pick]
  );

  /**
   * The measured wait for one row, or nothing.
   *
   * `Automatisch` has no fixed cost of its own — it borrows the cost of
   * whichever route it last resolved to. Averaging the routes, or quoting the
   * fastest, would be a number about no run that ever happened.
   *
   * The number and only the number: the column is right-aligned and tabular,
   * so anything else in it (the route's name, say) pushes the two columns
   * beside it out of line. Which route it was belongs in the note.
   */
  const waitFor = (id: string): string => {
    const route = id || lastRoute;
    const seconds = route ? waits[route] : undefined;
    return seconds === undefined ? '' : waitLabel(seconds);
  };

  /** What `Automatisch` has to say for itself, once it has done something. */
  const autoNote = lastRoute && waits[lastRoute] !== undefined
    ? `zuletzt ${labelOf(lastRoute) || lastRoute}`
    : 'wählt ein verfügbares Modell';

  const row = (id: string, name: string, note: string, index: number) => (
    <li
      key={id || 'auto'}
      ref={(el) => {
        options.current[index] = el;
      }}
      role="option"
      aria-selected={value === id}
      tabIndex={-1}
      className={value === id ? 'brain-opt on' : 'brain-opt'}
      onClick={() => pick(id)}
      onKeyDown={(e) => onOptionKey(e, index)}
    >
      <span className="brain-opt-name">{name}</span>
      <span className="brain-opt-note">{note}</span>
      <span className="brain-opt-wait">{waitFor(id)}</span>
    </li>
  );

  const chosenWait = value ? waitFor(value) : '';

  return (
    <div className="brain" ref={box}>
      <button
        ref={trigger}
        type="button"
        className="brain-btn"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Wer antwortet: ${label}`}
        disabled={!onChange}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        <span className="brain-btn-role">Antwortet</span>
        <span className="brain-btn-name">{label}</span>
        {chosenWait && <span className="brain-btn-wait">{chosenWait}</span>}
        <Chevron open={open} reduced={reduced} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            className="brain-menu"
            data-motion="menu"
            variants={reveal}
            initial="hidden"
            animate="visible"
            exit="hidden"
          >
            <ul className="brain-list" role="listbox" aria-label="Wer antwortet">
              {row('', 'Automatisch', autoNote, 0)}
              {row('deterministic', 'Lokaler Index', 'ohne Modell', 1)}
              {ready.map((r, i) => row(r.id, r.label || r.id, runtimeNote(r), i + 2))}
            </ul>
            {/* The right-hand column is only readable if it says what it is,
                and it must not be mistaken for a specification: these are the
                waits this browser timed, not a promise about the next one. */}
            {Object.keys(waits).length > 0 && (
              <p className="brain-legend">Zuletzt gemessen, auf diesem Rechner</p>
            )}
            {/* A list of one that is really a list of none is the failure this
                interface keeps making: an instrument that cannot measure must
                say so, distinguishably from having measured nothing. */}
            {state !== 'ok' && (
              <div className="brain-off">
                <p className="brain-off-note">
                  {state === 'laden'
                    ? 'Laufzeiten werden geprüft …'
                    : 'Der Zustand der Laufzeiten konnte nicht gelesen werden. Nur die automatische Route steht fest.'}
                </p>
                {state === 'fehler' && onRecheck && (
                  <button type="button" className="brain-recheck" onClick={() => void onRecheck()}>
                    Erneut prüfen
                  </button>
                )}
              </div>
            )}
            {state === 'ok' && off.length > 0 && (
              <div className="brain-off">
                <p className="brain-off-head">Stehen nicht zur Wahl</p>
                {off.map((r) => (
                  <p key={r.id} className="brain-off-row">
                    <span>{r.label || r.id}</span>
                    <span>{AUTH_NOTE[r.auth_status] || r.auth_status}</span>
                  </p>
                ))}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

export interface ConversationProps {
  project: string;
  /** used to turn a cited path into a clickable jump */
  resolveModule: (needle: string) => string | undefined;
  onFocusModule: (module: string) => void;
  /** the module the stage currently shows, offered as something to insert */
  contextModule?: string;
  /** which runtime answers; undefined lets the backend route */
  provider?: string;
  /** picking a brain from inside the conversation, where the wait happens */
  onProvider?: (id: string) => void;
  /** how much may happen without a click */
  autonomy: AutonomyLevel;
  /** something was queued, so the caller can refresh what depends on it */
  onDispatched?: () => void;
  compact?: boolean;
}

export function Conversation({
  project,
  resolveModule,
  onFocusModule,
  contextModule,
  provider,
  onProvider,
  autonomy,
  onDispatched,
  compact
}: ConversationProps) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copiedTurn, setCopiedTurn] = useState<number | null>(null);
  const [thread, setThread] = useState('');
  const [resuming, setResuming] = useState(false);
  const [runtimes, setRuntimes] = useState<RuntimeRow[]>([]);
  /** whether that list was read, is being read, or could not be read */
  const [runtimeState, setRuntimeState] = useState<RuntimeState>('laden');
  /** seconds the current turn has been running; a caret is not a progress report */
  const [elapsed, setElapsed] = useState(0);
  /** what actually served the last turn, so a canned answer can say it was canned */
  const [lastProvider, setLastProvider] = useState('');
  const [editorAttachment, setEditorAttachment] = useState<EditorAttachment>({ state: 'idle' });
  const [activeRequest, setActiveRequest] = useState<{
    conversationId: string;
    requestId: number;
    localTurnId: string;
  } | null>(null);
  /** what every route has cost so far, timed here, keyed by the route that served */
  const [waits, setWaits] = useState<WaitLedger>({});
  /** when the turn currently out was sent, so its own wait can be recorded */
  const sentAt = useRef(0);
  const scroller = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  /** true while the reader is at the bottom; only then may new text scroll */
  const pinned = useRef(true);
  const reduced = useReducedMotionPref();
  /* The whole motion vocabulary this page uses, resolved once. Nothing below
     writes a duration, an easing or a distance of its own — see
     src/shared/ui/motion/tokens.ts, which is the only implementation owner. */
  const youArrive = useMemo(() => bubbleVariants(reduced, 'right'), [reduced]);
  const ikarusArrive = useMemo(() => bubbleVariants(reduced, 'left'), [reduced]);
  const reveal = useMemo(() => revealVariants(reduced), [reduced]);
  const arm = useMemo(() => armVariants(reduced), [reduced]);
  /**
   * The index from which a turn is NEW and may animate in.
   *
   * A resumed thread of twenty turns all rising at once is a slow page load
   * wearing a costume, so everything already on screen when the thread was
   * read starts at rest. Only turns appended after that arrive.
   */
  const freshFrom = useRef(0);
  const stream = useRef<{ close: () => void } | null>(null);
  /** Invalidates chat callbacks that outlive their project or thread. */
  const chatScope = useRef(0);
  /** Synchronous claim: React's `busy` state cannot close a same-render double submit. */
  const chatSendClaim = useRef<symbol | null>(null);
  /** Every queued task has its own one-shot stream until final/error/teardown. */
  const taskStreams = useRef<Map<string, { close: () => void }>>(new Map());
  /** Invalidates a queue response that arrives after its thread/project left. */
  const taskScope = useRef(0);
  const turnSerial = useRef(0);
  /** Synchronous claim guard: React state alone cannot stop a double-click. */
  const claimedOffers = useRef<Set<string>>(new Set());
  const autonomyRef = useRef(autonomy);
  autonomyRef.current = autonomy;
  /* `settle` must not be rebuilt every time the project string changes — it is
     the stream's own callback — so the project it writes the ledger under is
     read through a ref. */
  const projectRef = useRef(project);
  projectRef.current = project;

  /**
   * Follow the conversation, but do not YANK it.
   *
   * Scrolling to the bottom unconditionally means that reading an older answer
   * while a new one streams in throws the reader back down every frame. The
   * transcript follows only while it is already at the bottom.
   */
  useEffect(() => {
    const el = scroller.current;
    if (el && pinned.current) el.scrollTop = el.scrollHeight;
  }, [turns]);

  const onScroll = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  }, []);

  // The box grows with the text and shrinks back when it is sent.
  useEffect(() => {
    const el = composer.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(200, el.scrollHeight)}px`;
  }, [draft]);

  // Focus lands where typing goes, on arrival and after every turn.
  useEffect(() => {
    if (!busy) composer.current?.focus();
  }, [busy, project]);

  const closeTaskStreams = useCallback(() => {
    taskScope.current += 1;
    taskStreams.current.forEach((taskStream) => taskStream.close());
    taskStreams.current.clear();
  }, []);

  const invalidateChat = useCallback(() => {
    chatScope.current += 1;
    chatSendClaim.current = null;
    stream.current?.close();
    stream.current = null;
  }, []);

  useEffect(
    () => () => {
      invalidateChat();
      closeTaskStreams();
    },
    [closeTaskStreams, invalidateChat]
  );

  /**
   * WHO CAN ANSWER — and this request is itself slow enough to fail.
   *
   * `/api/runtimes/status` probes a CLI, a second CLI and an unreachable
   * Ollama endpoint whose connect timeout it waits out; measured here at
   * 16.6s warm, against the 20s ceiling `request()` gives it. So the answer
   * arrives late, and under load it does not arrive at all: the picker then
   * degrades to "only the automatic route is certain" — true, and the whole
   * control is gone.
   *
   * One retry, and a way to ask again by hand from inside the menu (the
   * `fehler` branch below). Not a spinner over a lie: while it is unread the
   * control says so, and it can be told to look again.
   */
  const readRuntimes = useCallback(async (): Promise<void> => {
    setRuntimeState('laden');
    try {
      const payload = await getRuntimeStatus();
      setRuntimes(payload.runtimes || []);
      setRuntimeState('ok');
    } catch {
      setRuntimes([]);
      setRuntimeState('fehler');
    }
  }, []);

  useEffect(() => {
    let alive = true;
    let retry = 0;
    const attempt = () => {
      getRuntimeStatus()
        .then((p) => {
          if (!alive) return;
          setRuntimes(p.runtimes || []);
          setRuntimeState('ok');
        })
        .catch(() => {
          if (!alive) return;
          if (retry === 0) {
            retry = 1;
            attempt();
            return;
          }
          setRuntimes([]);
          setRuntimeState('fehler');
        });
    };
    attempt();
    return () => {
      alive = false;
    };
  }, []);

  /* The editor owns the selection artifact; chat only reads its public receipt.
     A URL ref that belongs to another checkout is shown as withheld and is never
     sent across the project boundary. */
  useEffect(() => {
    const ref = editorContextRefFromUrl();
    if (!ref) {
      setEditorAttachment({ state: 'idle' });
      return;
    }
    if (!project) {
      setEditorAttachment({ state: 'withheld', ref, reason: 'Kein Projekt für den Editor-Anhang ausgewählt.' });
      return;
    }
    let alive = true;
    setEditorAttachment({ state: 'loading', ref });
    getEditorContext(ref)
      .then((payload) => {
        if (!alive) return;
        const context = payload.context;
        if (!context || context.context_ref !== ref) {
          setEditorAttachment({ state: 'unavailable', ref, reason: 'Der Editor-Anhang hat keine prüfbare Referenz geliefert.' });
        } else if (context.project !== project) {
          setEditorAttachment({ state: 'withheld', ref, context, reason: `Der Anhang gehört zu Projekt ${context.project}, nicht zu ${project}.` });
        } else if (context.expired) {
          setEditorAttachment({ state: 'withheld', ref, context, reason: 'Der Editor-Anhang ist abgelaufen und wird nicht gesendet.' });
        } else if (context.inclusion_report?.accepted === false) {
          setEditorAttachment({ state: 'withheld', ref, context, reason: context.inclusion_report.reason || 'Der Kontext wurde bei der Prüfung nicht aufgenommen.' });
        } else {
          setEditorAttachment({ state: 'attached', ref, context });
        }
      })
      .catch(() => {
        if (alive) setEditorAttachment({ state: 'unavailable', ref, reason: 'Der Editor-Anhang konnte nicht gelesen werden und wird nicht gesendet.' });
      });
    return () => { alive = false; };
  }, [project]);

  // A running clock while a turn is out. 45 seconds of blinking caret reads as
  // a hang; 45 seconds of a counter reads as work.
  useEffect(() => {
    if (!busy) {
      setElapsed(0);
      return;
    }
    const started = Date.now();
    const timer = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500);
    return () => window.clearInterval(timer);
  }, [busy]);

  /* ---- the thread: resume it, or mint one lazily ---- */
  useEffect(() => {
    invalidateChat();
    closeTaskStreams();
    claimedOffers.current.clear();
    setBusy(false);
    setActiveRequest(null);
    setResuming(false);
    setError('');
    setLastProvider('');
    if (!project) {
      setTurns([]);
      setThread('');
      return;
    }
    let alive = true;
    const resumeProject = project;
    const isCurrentResume = () => alive && projectRef.current === resumeProject;
    const known = loadThreadId(project);
    setTurns([]);
    setThread(known);
    setWaits(loadWaits(project));
    freshFrom.current = 0;
    if (!known) return;

    setResuming(true);
    getConversation(known)
      .then((payload) => {
        if (!isCurrentResume()) return;
        const rows = payload.conversation?.turns || [];
        // Everything already in the store was not just said; it does not arrive.
        freshFrom.current = rows.length * 2;
        /* What served the LAST stored turn is what "zuletzt" means on a
           resumed thread — for the nudge under that answer and for the
           `Automatisch` row in the picker, which otherwise sat next to a
           persisted measurement with nothing to attach it to. Read from the
           turn itself, so it can never claim a route that thread never used. */
        const lastRow = rows[rows.length - 1];
        if (lastRow?.provider_used) setLastProvider(lastRow.provider_used);
        const dispatchByTurn = new Map<number, TaskSnapshot>();
        for (const dispatch of payload.conversation?.dispatches || []) {
          const turnId = positiveTurnId(dispatch.link?.turn_id);
          const snapshot = resumedDispatch(dispatch);
          if (turnId !== undefined && snapshot) dispatchByTurn.set(turnId, snapshot);
        }
        setTurns(
          rows.flatMap<Turn>((t, index) => {
            const backendTurnId = positiveTurnId(t.id);
            return [
              { role: 'you', text: t.user_message, localId: `stored-${known}-${index}-you` },
              {
                role: 'ikarus',
                text: t.assistant_text || '',
                localId: `stored-${known}-${index}-ikarus`,
                backendTurnId,
                conversationPersisted: backendTurnId !== undefined,
                dispatch: backendTurnId !== undefined ? dispatchByTurn.get(backendTurnId) : undefined,
                // Stored verbatim; the stamp and the citations are derived at
                // render, once the runtime list and the map have arrived.
                origin: t.provider_used
                  ? { intent: t.intent, provider_used: t.provider_used, model_used: t.model_used }
                  : undefined
              }
            ];
          })
        );
      })
      .catch(() => {
        // A thread that cannot be read is not a thread that never existed, and
        // the difference is worth one line rather than a silently empty page.
        if (isCurrentResume()) setError('Der bisherige Verlauf konnte nicht gelesen werden. Neue Turns laufen trotzdem.');
      })
      .finally(() => {
        if (isCurrentResume()) setResuming(false);
      });

    return () => {
      alive = false;
      closeTaskStreams();
    };
    // resolveModule changes identity with the map; the thread does not need to
    // be re-read for that.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [closeTaskStreams, invalidateChat, project]);

  const ensureThread = useCallback(async (scope: number): Promise<string> => {
    if (thread) return thread;
    try {
      const payload = await newConversation();
      if (scope !== chatScope.current || projectRef.current !== project) return '';
      const id = payload.conversation_id;
      setThread(id);
      saveThreadId(project, id);
      return id;
    } catch {
      // No id is not a reason to lose the turn: the backend accepts a turn
      // without one, it just will not remember it.
      return '';
    }
  }, [project, thread]);

  /* ---- offered actions ---- */

  const updateDispatch = useCallback((turnId: string, dispatch: TaskSnapshot) => {
    setTurns((prev) => prev.map((turn) => (turn.localId === turnId ? { ...turn, dispatch } : turn)));
  }, []);

  const runAction = useCallback(
    async (
      action: IkarusAskAction,
      automatic: boolean,
      threadId: string,
      localTurnId: string,
      backendTurnId?: number,
      conversationPersisted?: boolean
    ) => {
      const objective = action.args?.objective || '';
      const lane = action.args?.lane || 'local_only';
      const scope = taskScope.current;
      // `project` can change during the queue await before the project effect
      // gets a chance to bump `taskScope`. The render-time ref closes that
      // window; both identities must still match before this request may touch
      // the currently visible conversation or its task-stream registry.
      const requestProject = project;
      const actionProject = action.args?.project || requestProject;
      const isCurrentRequest = () => (
        scope === taskScope.current && projectRef.current === requestProject
      );
      const durableTurnId = positiveTurnId(backendTurnId);
      const hasDurableAttribution = conversationPersisted === true
        && Boolean(threadId)
        && durableTurnId !== undefined;
      try {
        const queued = await queueTask(
          actionProject,
          objective,
          lane,
          hasDurableAttribution ? threadId : undefined,
          hasDurableAttribution ? durableTurnId : undefined
        );
        if (!isCurrentRequest()) return null;
        const taskId = typeof queued.id === 'string' ? queued.id : '';
        const link = queued.conversation_link;
        const linkedAsRequested = hasDurableAttribution
          && Boolean(taskId)
          && link?.linked === true
          && link.conversation_id === threadId
          && link.turn_id === durableTurnId
          && link.dispatch_ref === taskId;
        let attributionNote = '';
        if (!hasDurableAttribution) {
          attributionNote = ' · ohne dauerhafte Turn-Zuordnung';
        } else if (!linkedAsRequested) {
          attributionNote = ` · dauerhafte Turn-Zuordnung fehlgeschlagen${link?.error ? `: ${link.error}` : ''}`;
        } else if (link?.projection_pending || link?.projection?.state === 'pending') {
          attributionNote = ' · Turn-Zuordnung gespeichert; Ergebnisprojektion wartet';
        } else if (link?.projection?.state === 'error') {
          attributionNote = ` · Turn-Zuordnung gespeichert; Ergebnisprojektion fehlgeschlagen${link.projection.error ? `: ${link.projection.error}` : ''}`;
        }
        if (!taskId) {
          if (!isCurrentRequest()) return null;
          updateDispatch(localTurnId, {
            id: '', found: false, state: 'unknown', source: 'queue_response', lane,
            requested_lane: lane, actual_providers: [],
            summary: null, error: 'Die Queue hat keine Task-ID zurückgegeben.',
            applied: null, applied_reason: null, stalled: false, timed_out: false
          });
          if (isCurrentRequest()) onDispatched?.();
          return `eingereiht; Fortschritt nicht adressierbar · Lane ${lane}${attributionNote}`;
        }

        let latest: TaskSnapshot = {
          id: taskId, found: true, state: 'queued', source: 'queue_response', lane,
          requested_lane: lane, actual_providers: [],
          summary: null, error: null, applied: null, applied_reason: 'noch nicht abgeschlossen',
          stalled: false, timed_out: false
        };
        if (!isCurrentRequest()) return null;
        updateDispatch(localTurnId, latest);

        const receive = (snapshot: TaskSnapshot) => {
          if (!isCurrentRequest()) return;
          latest = snapshot;
          updateDispatch(localTurnId, snapshot);
        };
        try {
          const taskStream = streamTask(taskId, {
            onHello: receive,
            onProgress: receive,
            onFinal: (snapshot) => {
              if (!isCurrentRequest()) return;
              taskStreams.current.delete(taskId);
              receive(snapshot);
              if (isCurrentRequest()) onDispatched?.();
            },
            onError: (streamError) => {
              if (!isCurrentRequest()) return;
              taskStreams.current.delete(taskId);
              updateDispatch(localTurnId, {
                ...latest,
                state: 'unknown',
                source: 'stream_error',
                error: `Fortschritt nicht mehr erreichbar: ${streamError.message}`,
                applied: null,
                applied_reason: 'Der Task kann weiterlaufen; sein Ergebnis ist hier nicht belegt.',
                timed_out: false
              });
            }
          });
          if (!isCurrentRequest()) {
            taskStream.close();
            return null;
          }
          taskStreams.current.get(taskId)?.close();
          taskStreams.current.set(taskId, taskStream);
        } catch (streamError) {
          if (!isCurrentRequest()) return null;
          updateDispatch(localTurnId, {
            ...latest,
            state: 'unknown',
            source: 'stream_error',
            error: `Fortschritt nicht erreichbar: ${streamError instanceof Error ? streamError.message : 'unbekannter Fehler'}`,
            applied: null,
            applied_reason: 'Der Task wurde eingereiht; sein Ergebnis ist hier nicht belegt.'
          });
        }
        if (!isCurrentRequest()) return null;
        if (automatic) {
          recordAutonomy({
            what: 'Aufgabe eingereiht',
            detail: `${objective} · Lane ${lane}`,
            level: autonomyRef.current
          });
        }
        if (isCurrentRequest()) onDispatched?.();
        return automatic
          ? `automatisch eingereiht · Lane ${lane}${attributionNote}`
          : `eingereiht · Lane ${lane}${attributionNote}`;
      } catch (e) {
        if (!isCurrentRequest()) return null;
        return `Einreihung nicht bestätigt: ${e instanceof Error ? e.message : 'unbekannter Fehler'}. `
          + 'Nicht automatisch wiederholt; der Server könnte die Aufgabe bereits angenommen haben.';
      }
    },
    [onDispatched, project, updateDispatch]
  );

  const answerOffer = useCallback(
    async (index: number, accept: boolean) => {
      const turn = turns[index];
      if (!turn?.offer) return;
      const action = turn.offer;
      const localTurnId = turn.localId || '';
      const claimKey = localTurnId || `offer-index-${index}`;
      if (claimedOffers.current.has(claimKey)) return;
      claimedOffers.current.add(claimKey);

      // Clear the offer before any network await. The ref above closes the
      // same-render double-click window before React can paint this change.
      setTurns((prev) => prev.map((t, i) => (
        (localTurnId ? t.localId === localTurnId : i === index)
          ? { ...t, offer: undefined, offerOutcome: accept ? 'wird eingereiht …' : 'abgelehnt' }
          : t
      )));
      if (!accept) {
        claimedOffers.current.delete(claimKey);
        return;
      }

      try {
        const outcome = await runAction(
          action,
          false,
          thread,
          localTurnId,
          turn.backendTurnId,
          turn.conversationPersisted
        );
        if (outcome === null) return;
        setTurns((prev) => prev.map((t, i) => (
          (localTurnId ? t.localId === localTurnId : i === index) ? { ...t, offerOutcome: outcome } : t
        )));
      } finally {
        claimedOffers.current.delete(claimKey);
      }
    },
    [runAction, thread, turns]
  );

  const settle = useCallback(
    (
      payload: IkarusAskPayload,
      threadId: string,
      localTurnId: string,
      scope: number,
      requestProject: string,
      sendClaim: symbol
    ) => {
      if (chatSendClaim.current === sendClaim) chatSendClaim.current = null;
      if (scope !== chatScope.current || projectRef.current !== requestProject) return;
      stream.current = null;
      const route = payload.provider_used || '';
      setLastProvider(route);
      /* The wait is timed here and nowhere else. `sentAt` is set the moment
         the sentence leaves the box, so this covers the whole round trip the
         reader actually sat through — including minting the thread — rather
         than the part of it the backend chose to report. */
      const seconds = sentAt.current ? (Date.now() - sentAt.current) / 1000 : undefined;
      if (route && seconds !== undefined) {
        setWaits((prev) => {
          const next = { ...prev, [route]: seconds };
          saveWaits(projectRef.current, next);
          return next;
        });
      }
      const action = payload.action;
      /**
       * `vorschlaege` and above: a proposed TASK starts without a click. The
       * draft that task produces is a separate decision and is deliberately
       * NOT covered here — see Decision.tsx and autonomy.ts.
       */
      const auto = Boolean(action) && autonomyRef.current !== 'aus';
      // Read directly from this final envelope. Waiting for the state update
      // below would race the automatic action against React's next render.
      const backendTurnId = positiveTurnId(payload.turn_id);
      const conversationPersisted = payload.conversation_persisted;

      setTurns((prev) => {
        const next = [...prev];
        const index = next.findIndex((turn) => turn.localId === localTurnId);
        const target = next[index];
        if (target && target.role === 'ikarus') {
          next[index] = {
            ...target,
            text: payload.assistant || target.text,
            origin: { intent: payload.intent, provider_used: payload.provider_used, model_used: payload.model_used },
            seconds,
            streaming: false,
            backendTurnId,
            conversationPersisted,
            offer: action && !auto ? action : undefined
          };
        }
        return next;
      });
      setBusy(false);

      if (action && auto) {
        void runAction(
          action,
          true,
          threadId,
          localTurnId,
          backendTurnId,
          conversationPersisted
        ).then((outcome) => {
          if (outcome === null || scope !== chatScope.current || projectRef.current !== requestProject) return;
          setTurns((prev) => prev.map((t) => (
            t.localId === localTurnId ? { ...t, offerOutcome: outcome } : t
          )));
        });
      }
    },
    [runAction]
  );

  /** Close only this browser's observation. The generation request remains
   * server-owned; cancelling it is an explicit, separately recorded POST. */
  const closeObservation = useCallback(() => {
    stream.current?.close();
    stream.current = null;
    setBusy(false);
    setTurns((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last && last.role === 'ikarus' && last.streaming) {
        next[next.length - 1] = {
          ...last,
          streaming: false,
          halted: true,
          text: last.text || 'Die Beobachtung wurde geschlossen; ob der Server weiterarbeitet, ist hier nicht bestätigt.'
        };
      }
      return next;
    });
  }, []);

  const requestCancellation = useCallback(async () => {
    const target = activeRequest;
    if (!target) return;
    const mark = (status: ConversationCancellationStatus) => {
      setTurns((prev) => prev.map((turn) => (
        turn.localId === target.localTurnId ? { ...turn, cancellation: status } : turn
      )));
    };
    try {
      const payload = await cancelConversationTurn(
        target.conversationId,
        target.requestId,
        clientId('cancel')
      );
      const status = payload.cancellation?.status || 'unknown';
      mark(status);
      if (status === 'already_terminal' || status === 'unknown') setActiveRequest(null);
    } catch (reason) {
      const notSupported = reason instanceof ApiError
        && reason.kind === 'notfound'
        && /unknown endpoint|kennt .* nicht/i.test(reason.message);
      const status: ConversationCancellationStatus = notSupported ? 'not_supported' : 'unknown';
      mark(status);
      if (status !== 'not_supported') setActiveRequest(null);
    }
  }, [activeRequest]);

  /** A fresh thread. The old one stays in the store; this stops carrying it. */
  const newThread = useCallback(() => {
    closeObservation();
    closeTaskStreams();
    claimedOffers.current.clear();
    setActiveRequest(null);
    setTurns([]);
    setThread('');
    setError('');
    freshFrom.current = 0;
    try {
      localStorage.removeItem(`${THREAD_KEY}:${project}`);
    } catch {
      /* storage blocked — the fresh thread still holds for this session */
    }
  }, [closeObservation, closeTaskStreams, project]);

  const send = useCallback(async () => {
    const message = draft.trim();
    if (!message || busy || chatSendClaim.current !== null || !project) return;
    const scope = chatScope.current;
    const requestProject = project;
    const sendClaim = Symbol('ikarus-chat-send');
    chatSendClaim.current = sendClaim;
    const releaseSendClaim = () => {
      if (chatSendClaim.current === sendClaim) chatSendClaim.current = null;
    };
    setDraft('');
    setError('');
    setBusy(true);
    sentAt.current = Date.now();

    /**
     * WHAT IS SENT IS WHAT WAS TYPED.
     *
     * An earlier version prepended a line naming the module on the stage. It
     * read as helpful and was not: the backend classifies intent by substring
     * (daedalus/ikarus_os.py::classify), so a focus on `clones.py` silently
     * routed a plain question down the distillation path, and the turn stored
     * in the conversation was not the sentence the person wrote. Context is
     * offered as something to INSERT, visibly, above the composer.
     *
     * The turns go up BEFORE the thread id is awaited. Minting a thread is a
     * round trip, and this API has been measured at 17-26s under load; doing
     * it first meant the sentence vanished out of the box and nothing at all
     * appeared in its place for as long as that took.
     */
    turnSerial.current += 1;
    const exchangeId = `turn-${turnSerial.current}`;
    const replyId = `${exchangeId}-ikarus`;
    setTurns((prev) => [
      ...prev,
      { role: 'you', text: message, localId: `${exchangeId}-you` },
      { role: 'ikarus', text: '', streaming: true, localId: replyId }
    ]);

    const threadId = await ensureThread(scope);
    if (scope !== chatScope.current || projectRef.current !== requestProject) {
      releaseSendClaim();
      return;
    }

    if (!threadId) {
      releaseSendClaim();
      setBusy(false);
      setTurns((prev) => prev.map((turn) => (
        turn.localId === replyId
          ? { ...turn, streaming: false, halted: true, text: 'Der Verlauf konnte nicht angelegt werden; es wurde keine Anfrage gestartet.' }
          : turn
      )));
      setError('Ikarus-Turn nicht gestartet, weil kein dauerhafter Verlauf verfügbar ist.');
      return;
    }

    const contextRefs = editorAttachment.state === 'attached' ? [editorAttachment.ref] : [];
    const isCurrent = () => scope === chatScope.current && projectRef.current === requestProject;
    const failCreation = (creationError: Error) => {
      releaseSendClaim();
      if (!isCurrent()) return;
      setBusy(false);
      setTurns((prev) => prev.map((turn) => (
        turn.localId === replyId
          ? {
              ...turn,
              streaming: false,
              halted: true,
              text: turn.text || 'Der Turn konnte nicht eindeutig angelegt werden; sein Serverzustand ist unbekannt.'
            }
          : turn
      )));
      setError(
        `Ikarus-Turn konnte nicht bestätigt werden (${creationError.message}). Die POST-Anfrage wird nicht automatisch wiederholt.`
      );
    };

    try {
      // This is the single effectful transition. Its client_request_id binds
      // retries to the same canonical request; EventSource below only observes
      // the returned request id and can safely reconnect without another POST.
      const created = await createConversationTurn(threadId, {
        client_request_id: clientId('turn'),
        project: requestProject,
        message,
        provider,
        context_refs: contextRefs
      });
      const request = created.turn_request;
      if (!isCurrent()) {
        releaseSendClaim();
        return;
      }
      if (!request || !Number.isSafeInteger(request.request_id) || request.request_id <= 0) {
        throw new Error('Der Server hat keine gültige Turn-Request-ID geliefert.');
      }
      setActiveRequest({ conversationId: threadId, requestId: request.request_id, localTurnId: replyId });
      setTurns((prev) => prev.map((turn) => (
        turn.localId === replyId ? { ...turn, requestId: request.request_id, contextRefs } : turn
      )));

      stream.current = observeConversationTurn(threadId, request.request_id, {
        onDelta: (text) => {
          if (!isCurrent()) return;
          setTurns((prev) => {
            const next = [...prev];
            const index = next.findIndex((turn) => turn.localId === replyId);
            const target = next[index];
            if (target && target.role === 'ikarus') next[index] = { ...target, text: target.text + text };
            return next;
          });
        },
        onFinal: (payload) => {
          setActiveRequest((current) => current?.requestId === request.request_id ? null : current);
          settle(payload, threadId, replyId, scope, requestProject, sendClaim);
        },
        onCancelled: (cancellation) => {
          releaseSendClaim();
          if (!isCurrent()) return;
          stream.current = null;
          setActiveRequest((current) => current?.requestId === request.request_id ? null : current);
          setBusy(false);
          setTurns((prev) => prev.map((turn) => (
            turn.localId === replyId
              ? {
                  ...turn,
                  streaming: false,
                  halted: true,
                  cancellation: cancellation.status,
                  text: turn.text || 'Der Server hat den Abbruch bestätigt.'
                }
              : turn
          )));
        },
        onError: (observationError) => {
          releaseSendClaim();
          if (!isCurrent()) return;
          stream.current = null;
          setActiveRequest((current) => current?.requestId === request.request_id ? null : current);
          setBusy(false);
          setTurns((prev) => prev.map((turn) => (
            turn.localId === replyId
              ? {
                  ...turn,
                  streaming: false,
                  halted: true,
                  text: turn.text || 'Der Server meldet für diesen Turn keinen bestätigten Abschluss.'
                }
              : turn
          )));
          setError(`Ikarus-Turn beendet mit unbestätigtem Ergebnis: ${observationError.message}`);
        },
        onState: (status) => {
          if (!isCurrent()) return;
          if (status.cancellation?.status) {
            setTurns((prev) => prev.map((turn) => (
              turn.localId === replyId ? { ...turn, cancellation: status.cancellation!.status } : turn
            )));
          }
          if (status.state === 'final' && status.final) {
            setActiveRequest((current) => current?.requestId === request.request_id ? null : current);
            settle(status.final, threadId, replyId, scope, requestProject, sendClaim);
          } else if (status.state === 'cancelled') {
            releaseSendClaim();
            setActiveRequest((current) => current?.requestId === request.request_id ? null : current);
            setBusy(false);
            setTurns((prev) => prev.map((turn) => (
              turn.localId === replyId
                ? { ...turn, streaming: false, halted: true, cancellation: 'confirmed', text: turn.text || 'Der Server hat den Abbruch bestätigt.' }
                : turn
            )));
          } else if (status.state === 'unknown') {
            releaseSendClaim();
            setActiveRequest((current) => current?.requestId === request.request_id ? null : current);
            setBusy(false);
            setTurns((prev) => prev.map((turn) => (
              turn.localId === replyId
                ? { ...turn, streaming: false, halted: true, cancellation: status.cancellation?.status || 'unknown', text: turn.text || 'Der Turn-Zustand ist nach der Beobachtung unbekannt.' }
                : turn
            )));
          }
        }
      });
    } catch (creationError) {
      failCreation(creationError instanceof Error ? creationError : new Error('Der Turn konnte nicht angelegt werden.'));
    }
  }, [busy, draft, editorAttachment, ensureThread, project, provider, settle]);

  /** Nothing said yet — the page becomes an invitation rather than a form. */
  const empty = !resuming && turns.length === 0;
  /**
   * The identifying part of the thread id. Ids look like
   * `conv_20260826T122633Z_e90e07e2`, so the first eight characters are
   * `conv_202` for every thread that will ever exist — an identifier that
   * identifies nothing. The trailing segment is the one that does.
   */
  const threadTag = thread ? /_([0-9a-f]{6,})$/i.exec(thread)?.[1] || thread.slice(-8) : '';
  /** A runtime id in the reader's words, or nothing when that is not known. */
  const labelOf = useCallback(
    (id: string): string | undefined =>
      id === 'deterministic' ? 'lokaler Index' : runtimes.find((r) => r.id === id)?.label || undefined,
    [runtimes]
  );
  /**
   * DERIVED, not stored. Both of these depend on data that arrives AFTER a
   * resumed thread does — the runtime list for the stamp, the structure map
   * for the citations — so computing them once when the turn was parsed froze
   * both in their unloaded state. Cheap enough to redo: six identifiers per
   * answer against a map this page already holds.
   */
  const receipts = useMemo(
    () =>
      turns.map((t) => {
        if (t.role !== 'ikarus') return { stamp: undefined, cites: [] as Citation[] };
        const stamp: Stamp | undefined = t.halted
          ? { word: 'ANZEIGE BEENDET', kind: 'failed' }
          : t.origin
            ? stampFor(t.origin, labelOf)
            : undefined;
        return { stamp, cites: t.streaming ? [] : citationsFrom(t.text, resolveModule) };
      }),
    [labelOf, resolveModule, turns]
  );
  /**
   * The nudge belongs to the answer it is about, not to the top of the page.
   * It offers a switch and says so: pressing it changes what answers NEXT. It
   * does not re-ask, so it must not be labelled as if it did.
   */
  const showNudge = Boolean(!busy && !provider && lastProvider === 'deterministic' && runtimes.some((r) => r.available));
  const armed = Boolean(draft.trim()) && !busy && Boolean(project);
  const exchanges = Math.ceil(turns.length / 2);
  /**
   * The thread bar exists when a thread does.
   *
   * At rest it used to draw a picker, the words "Neuer Verlauf" and a
   * greyed-out "Neuer Chat" — three controls whose entire message was that
   * there is nothing here yet — and then stranded them alone at the top of an
   * otherwise composed page, 160px above the invitation. The picker moved
   * into the composer, where the wait it causes actually happens; the other
   * two only have anything to say once a thread exists, so they wait until it
   * does. An affordance that does nothing is worse than an absent one.
   */
  const hasThread = Boolean(thread) || turns.length > 0;

  return (
    <section
      className={['convo', compact ? 'compact' : '', empty ? 'at-rest' : ''].filter(Boolean).join(' ')}
      aria-label="Gespräch mit Ikarus"
    >
      {/* THE THREAD'S OWN HEADER — what this thread is, what it is doing, and
          how to leave it. The rule between the two ends is the composition:
          the 340px that used to sit there was a void between three unrelated
          things, and it is now the span of one continuous thread drawn
          between its name and its exit. */}
      {hasThread && (
        <motion.div className="convo-bar" data-motion="bar" variants={reveal} initial="hidden" animate="visible">
          <span className="convo-thread">
            <span className="convo-thread-role">Verlauf</span>
            {/* No literal separators: `.convo-thread` is a flex row, so each
                run of text becomes its own item and the gap already spaces
                them. A written ` · ` between them was separated twice. */}
            <span>
              {exchanges} {exchanges === 1 ? 'Turn' : 'Turns'}
            </span>
            {threadTag && <code>{threadTag}</code>}
          </span>
          <span className="convo-bar-rule" aria-hidden="true" />
          {busy && (
            <span className="convo-elapsed" role="status">
              antwortet · {elapsedLabel(elapsed)}
            </span>
          )}
          <button type="button" onClick={newThread}>
            Neuer Chat
          </button>
        </motion.div>
      )}

      <div className={empty ? 'convo-scroll empty' : 'convo-scroll'} ref={scroller} onScroll={onScroll} role="log" aria-live="polite" aria-busy={busy}>
        {resuming && <p className="convo-reading">Verlauf wird gelesen …</p>}

        {/* THE INVITATION. An empty conversation is not a form waiting to be
            filled in — it is the one moment the page gets to say what it is.
            Two sizes, one measure, composed around the composer below it. */}
        {empty && (
          <div className="convo-open">
            <h2 className="convo-open-line">
              Frag Ikarus etwas über <b>{project || 'dieses Projekt'}</b>.
            </h2>
            <p className="convo-open-note">
              Ikarus wählt automatisch ein verfügbares LLM. Gemessene lokale Antworten bleiben klar von Modellantworten getrennt.
            </p>
            <div className="convo-suggestions" aria-label="Vorschläge">
              {['Erklär mir die Architektur dieses Projekts.', 'Wo würdest du als Nächstes refactoren?', 'Fass den aktuellen Projektzustand zusammen.'].map((suggestion) => (
                <button key={suggestion} type="button" onClick={() => setDraft(suggestion)}>{suggestion}</button>
              ))}
            </div>
          </div>
        )}

        {turns.map((t, i) => (
          <motion.article
            key={t.localId || i}
            className={`turn ${t.role}`}
            data-motion="bubble"
            variants={t.role === 'you' ? youArrive : ikarusArrive}
            initial={i >= freshFrom.current ? 'hidden' : false}
            animate="visible"
          >
            {/* The graphic treatment says who spoke — the question is quieter
                and carries a rule, the answer is full strength and names its
                own origin in the stamp. A screen reader gets it in words. */}
            <span className="visually-hidden">{t.role === 'you' ? 'Du' : 'Ikarus'}</span>
            <div className="turn-body">
              {/* Your words are printed exactly as you typed them; Ikarus's are
                  typeset, because they arrive marked up. The difference is the
                  point: one is a record, the other is a rendering. */}
              {t.role === 'you' ? (
                <p className="turn-text">{t.text}</p>
              ) : (
                <MarkdownMessage text={t.text} streaming={t.streaming} />
              )}

              {t.role === 'ikarus' && !t.streaming && t.text && (
                <div className="turn-actions" aria-label="Antwortaktionen">
                  <button
                    type="button"
                    onClick={() => {
                      void navigator.clipboard.writeText(t.text).then(() => {
                        setCopiedTurn(i);
                        window.setTimeout(() => setCopiedTurn((current) => (current === i ? null : current)), 1200);
                      });
                    }}
                  >
                    {copiedTurn === i ? 'Kopiert' : 'Antwort kopieren'}
                  </button>
                </div>
              )}

              {t.role === 'ikarus' && (t.requestId || t.cancellation || t.contextRefs?.length) && (
                <div className="turn-request" aria-label="Turn-Request-Status">
                  {t.requestId && <span>Request <code>{t.requestId}</code></span>}
                  {t.contextRefs?.length ? <span>· Editor-Anhang übergeben</span> : null}
                  {t.cancellation && <span className={`turn-cancellation ${t.cancellation}`}>· {cancellationLabel(t.cancellation)}</span>}
                  {activeRequest?.requestId === t.requestId && (
                    <button
                      type="button"
                      onClick={() => void requestCancellation()}
                      disabled={t.cancellation === 'requested'}
                    >
                      {t.cancellation === 'requested' ? 'Abbruch angefordert' : 'Abbruch anfordern'}
                    </button>
                  )}
                </div>
              )}

              {(receipts[i].stamp || receipts[i].cites.length > 0) && (
                <motion.div
                  className="turn-receipt"
                  data-motion="receipt"
                  variants={reveal}
                  initial="hidden"
                  animate="visible"
                >
                  {receipts[i].stamp && (
                    <span className={`stamp ${receipts[i].stamp!.kind}`}>
                      <span className="stamp-word">{receipts[i].stamp!.word}</span>
                      {receipts[i].stamp!.origin &&
                        (receipts[i].stamp!.originIsId ? (
                          <code className="stamp-id">{receipts[i].stamp!.origin}</code>
                        ) : (
                          <span className="stamp-origin">{receipts[i].stamp!.origin}</span>
                        ))}
                      {t.seconds !== undefined && <span className="stamp-wait">{waitLabel(t.seconds)}</span>}
                    </span>
                  )}
                  {receipts[i].cites.map((c) => (
                    <button key={c.seen} type="button" className="cite" onClick={() => onFocusModule(c.module)}>
                      {c.seen}
                    </button>
                  ))}
                </motion.div>
              )}

              {t.offer && (
                <motion.div
                  className="offer"
                  role="region"
                  aria-label="Vorgeschlagene Aktion"
                  data-motion="offer"
                  variants={reveal}
                  initial="hidden"
                  animate="visible"
                >
                  <span className="offer-eyebrow">Ikarus schlägt vor</span>
                  <p className="offer-what">{t.offer.args?.objective}</p>
                  <p className="offer-where">
                    Lane <code>{t.offer.args?.lane}</code> · Projekt <code>{t.offer.args?.project}</code>
                  </p>
                  <div className="offer-acts">
                    <button type="button" className="primary" onClick={() => void answerOffer(i, true)}>
                      Loslegen
                    </button>
                    <button type="button" onClick={() => void answerOffer(i, false)}>
                      Nicht jetzt
                    </button>
                  </div>
                </motion.div>
              )}
              {t.offerOutcome && <span className="offer-outcome">{t.offerOutcome}</span>}

              {t.dispatch && (
                <div className="offer" role="status" aria-label={`Aufgabenstatus: ${taskStateLabel(t.dispatch)}`}>
                  <span className="offer-eyebrow">Aufgabe · {taskStateLabel(t.dispatch)}</span>
                  {t.dispatch.summary && <p className="offer-what">{t.dispatch.summary}</p>}
                  {t.dispatch.error && <p className="offer-what">Fehler: {t.dispatch.error}</p>}
                  <p className="offer-where">
                    Task <code>{t.dispatch.id || 'ohne ID'}</code>
                    {t.dispatch.requested_lane && (
                      <> · angefordert <code>{t.dispatch.requested_lane}</code></>
                    )}
                    {!t.dispatch.requested_lane && t.dispatch.lane && (
                      <> · Lane <code>{t.dispatch.lane}</code></>
                    )}
                    {t.dispatch.actual_providers.length > 0 && (
                      <> · ausgeführt über <code>{t.dispatch.actual_providers.join(', ')}</code></>
                    )}
                    {' · '}Übergabe: {handoffLabel(t.dispatch.applied)}
                  </p>
                  {t.dispatch.applied_reason && t.dispatch.applied_reason !== 'not finished yet' && (
                    <p className="offer-where">{t.dispatch.applied_reason}</p>
                  )}
                </div>
              )}

              {showNudge && t.role === 'ikarus' && i === turns.length - 1 && (
                <p className="turn-nudge">
                  <span>Ohne Modell beantwortet. Nächste Frage an</span>
                  {runtimes
                    .filter((r) => r.available)
                    .map((r) => (
                      <button key={r.id} type="button" onClick={() => onProvider?.(r.id)}>
                        {r.label || r.id}
                      </button>
                    ))}
                </p>
              )}
            </div>
          </motion.article>
        ))}
      </div>

      {error && (
        <p className="convo-error" role="alert">
          {error}
        </p>
      )}

      {/* ONE CONTROL.
          The box you type in, what will be read with it, and send are the same
          object: one well, one border, one focus ring. "Was würde gelesen?" and
          the module on the stage used to float above the composer as bare grey
          text aligned to nothing — they belong to the box, because they
          describe what the box will do when you press send. The grid areas put
          them under the input in reading order, and the DOM order matches, so
          Tab walks the well the way the eye does. */}
      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        {/* A textarea, not an input. Enter sends, Shift+Enter breaks the line,
            and the box grows with the text — the three things that separate a
            chat composer from a search field, and their absence is a large
            part of why this did not feel like one. */}
        <div className="composer-line">
        <textarea
          ref={composer}
          value={draft}
          rows={1}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              void send();
            }
          }}
          placeholder={busy ? 'Du kannst schon weiterschreiben …' : 'Nachricht an Ikarus …'}
          aria-label="Nachricht an Ikarus"
          autoComplete="off"
          disabled={!project}
        />
        {/* Send and observation-close share one stable slot. A server cancel is
            deliberately separate on the request receipt, because closing this
            browser view is not evidence that provider work stopped. */}
        <motion.button
          type={busy ? 'button' : 'submit'}
          className={busy ? 'composer-send stopping' : 'composer-send'}
          data-motion="send"
          variants={arm}
          initial={false}
          animate={armed || busy ? 'armed' : 'idle'}
          whileTap={pressProps(reduced)}
          onClick={busy ? closeObservation : undefined}
          disabled={!armed && !busy}
          aria-label={busy ? 'Beobachtung schließen' : 'Senden'}
          title={busy ? 'Schließt nur diese Browser-Beobachtung. Ein Server-Abbruch wird separat angefordert.' : undefined}
        >
          {busy ? <StopGlyph /> : <SendGlyph />}
        </motion.button>
        </div>

        {/* THE PRE-FLIGHT RAIL, in the order the three facts matter: who
            answers, what is on the stage, what would be read. All three
            describe what pressing send will do, so all three live in the well
            that send belongs to. */}
        <BrainPicker
          runtimes={runtimes}
          state={runtimeState}
          value={provider || ''}
          onChange={onProvider}
          waits={waits}
          lastRoute={lastProvider}
          labelOf={labelOf}
          onRecheck={readRuntimes}
        />

        {contextModule && (
          <div className="composer-stage">
            {/* The rail has three tenants now, so both the path and the
                sentence around it had to give way. The path is set as the
                name it is known by (`daedalus/spine/a…` hid the only part
                that identifies it, and the full path is already on the focus
                card beside the stage); the sentence became the label role the
                rail already uses next door, so `Bühne picker.py` reads as one
                fact rather than truncating to `Auf de… picker.py`. */}
            <span className="composer-stage-label">Bühne</span>
            <code title={contextModule}>{shortLabel(contextModule)}</code>
            <button
              type="button"
              onClick={() => setDraft((d) => (d ? `${d.replace(/\s+$/, '')} ${contextModule} ` : `${contextModule} `))}
              title="Den Pfad in deine Frage einfügen"
            >
              Einfügen
            </button>
          </div>
        )}

        {editorAttachment.state !== 'idle' && (
          <div
            className={`editor-attachment ${editorAttachment.state}`}
            role={editorAttachment.state === 'attached' || editorAttachment.state === 'loading' ? 'status' : 'note'}
            aria-label="Editor-Anhang"
          >
            <span className="editor-attachment-label">Editor-Anhang</span>
            {editorAttachment.state === 'loading' ? (
              <span>Kontext wird geprüft …</span>
            ) : editorAttachment.state === 'attached' ? (
              <>
                <code title={editorAttachment.context.path}>{shortLabel(editorAttachment.context.path)}</code>
                <span>{editorAttachment.context.selection_chars} Zeichen</span>
                <span className="editor-attachment-status">
                  Inclusion-Status: akzeptiert · {editorAttachment.context.inclusion_report?.reason || 'validierter lokaler Kontext'}
                </span>
              </>
            ) : (
              <>
                {'context' in editorAttachment && editorAttachment.context?.path && (
                  <code title={editorAttachment.context.path}>{shortLabel(editorAttachment.context.path)}</code>
                )}
                <span className="editor-attachment-status">Inclusion-Status: nicht enthalten · {editorAttachment.reason}</span>
              </>
            )}
          </div>
        )}

        <ContextPlan
          project={project}
          objective={draft}
          onFocusModule={onFocusModule}
          resolveModule={resolveModule}
        />
      </form>
    </section>
  );
}
