import type { LiveEventName } from '@/shared/contracts';

/**
 * The live event stream, reduced.
 *
 * This was eight lines inside a `useEffect` in Cockpit.tsx, which is why it
 * carried a bug nobody could see: the `queue` frame was decoded as `d.depth`
 * while the server has always sent `queue_depth`, so the queue counter froze
 * at the `hello` snapshot and every later change was dropped in silence. A
 * reducer that lives in a component cannot be fed a frame and asserted; this
 * one can, and the spec now pins every key name the server uses.
 *
 * Pure by construction: no fetch, no DOM, no React. `reduceLiveEvent` takes
 * the previous state and one decoded frame and returns the next state.
 *
 * WHAT IT REFUSES TO DO. It never invents a number. Every field is optional
 * and stays `undefined` until a frame carried it, because the difference
 * between "the bus says zero" and "nobody has told us yet" is the difference
 * the whole surface is built on. Incremental frames preserve prior values
 * when a field is absent. A new hello snapshot resets missing observations
 * to unknown, so a reconnect cannot present an old counter as fresh evidence.
 */

/** One finished run, as `report_brief` publishes it. */
export interface ReportBrief {
  id?: string;
  name: string;
  status: string;
  lane: string;
  project?: string;
  summary?: string;
  agent?: string;
  provider?: string;
  replay?: boolean;
  executionExecuted?: boolean;
  runtimeId?: string;
  workItemId?: string;
  attemptId?: string;
  phase?: string;
  terminalReceiptSha256?: string;
  createdAt?: string;
}

export interface LiveState {
  /** the stream is open; false means these numbers are last-known, not now */
  connected: boolean;
  /**
   * A FLAG, not a count. `projection.py` emits `1 if current["in_flight"]
   * else 0` from the watcher's single current task, so adding it to a number
   * of dispatches would count one task twice.
   */
  inFlight?: number;
  queued?: number;
  /**
   * Counted when the stream connected and never again: the bus publishes
   * deltas only for reports, the queue and the watcher, so neither of these
   * two moves until a reconnect. Any surface that draws them says when they
   * were counted.
   */
  unread?: number;
  quarantined?: number;
  watcher?: string;
  /**
   * The reports this session has seen arrive, newest first.
   *
   * `hello` carries only the latest one, so this starts at one row and grows
   * as the bus reports. It is a session view, never a claim about history —
   * the ledger is what remembers, and the activity log is where it is read.
   *
   * Keyed by report NAME: the bus republishes the tail of its report list, so
   * the same name can arrive again carrying a newer status. A second copy
   * would be a duplicate React key and a stale row side by side with a fresh
   * one, so an arrival replaces its predecessor rather than joining it.
   */
  recent: ReportBrief[];
  /** how many reports arrived since the reader last looked at the rail */
  unseen: number;
}

export const EMPTY_LIVE: LiveState = { connected: false, recent: [], unseen: 0 };

/** How many reports the session list keeps. Beyond this the ledger is the record. */
export const RECENT_LIMIT = 6;

function num(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : undefined;
}

function inFlightFlag(value: unknown): number | undefined {
  if (typeof value === 'boolean') return value ? 1 : 0;
  return value === 0 || value === 1 ? value : undefined;
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value ? value : undefined;
}

// Identity evidence is never trimmed or coerced into a stronger fact.
function canonicalText(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 && value.length <= 200
    && value === value.trim() ? value : undefined;
}

function exactBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined;
}

function receiptDigest(value: unknown): string | undefined {
  return typeof value === 'string' && /^[0-9a-f]{64}$/.test(value) ? value : undefined;
}

/** A report brief, or nothing. A frame without a name is not a report. */
export function briefFrom(value: unknown): ReportBrief | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const row = value as Record<string, unknown>;
  const name = text(row.name);
  if (!name) return undefined;
  return {
    name,
    id: text(row.id),
    status: text(row.status) || 'unbekannt',
    lane: text(row.lane) || '',
    project: text(row.project),
    summary: text(row.summary),
    agent: canonicalText(row.agent),
    provider: canonicalText(row.provider),
    replay: exactBoolean(row.replay),
    executionExecuted: exactBoolean(row.execution_executed),
    runtimeId: canonicalText(row.runtime_id),
    workItemId: canonicalText(row.work_item_id),
    attemptId: canonicalText(row.attempt_id),
    phase: canonicalText(row.phase),
    terminalReceiptSha256: receiptDigest(row.terminal_receipt_sha256),
    createdAt: text(row.created_at)
  };
}

/** Put a report at the head, replacing any earlier copy of the same name. */
function place(recent: ReportBrief[], brief: ReportBrief): ReportBrief[] {
  const previous = recent.find((row) => row.name === brief.name);
  if (previous?.createdAt && brief.createdAt
    && Date.parse(previous.createdAt) > Date.parse(brief.createdAt)) return recent;
  const rest = recent.filter((row) => row.name !== brief.name);
  const ordered = [brief, ...rest];
  ordered.sort((a, b) => {
    const aTime = Date.parse(a.createdAt || '');
    const bTime = Date.parse(b.createdAt || '');
    return Number.isFinite(aTime) && Number.isFinite(bTime) ? bTime - aTime : 0;
  });
  return ordered.slice(0, RECENT_LIMIT);
}

function sameContent(a: ReportBrief | undefined, b: ReportBrief): boolean {
  return (
    !!a && a.name === b.name && a.status === b.status && a.lane === b.lane
    && a.project === b.project && a.summary === b.summary
    && a.id === b.id && a.agent === b.agent && a.createdAt === b.createdAt
    && a.provider === b.provider && a.replay === b.replay
    && a.executionExecuted === b.executionExecuted && a.runtimeId === b.runtimeId
    && a.workItemId === b.workItemId && a.attemptId === b.attemptId
    && a.phase === b.phase && a.terminalReceiptSha256 === b.terminalReceiptSha256
  );
}

function withReport(prev: LiveState, brief: ReportBrief, seen: boolean): LiveState {
  // The identical report arriving again (a reconnect replays `hello`, the bus
  // republishes its tail) is not a new arrival. The same NAME carrying new
  // content is: the row is replaced and, if nobody was looking, announced.
  if (sameContent(prev.recent[0], brief)) return prev;
  const recent = place(prev.recent, brief);
  if (recent === prev.recent) return prev;
  const known = prev.recent.some((row) => row.name === brief.name);
  const announce = !seen && !(known && sameContent(prev.recent.find((r) => r.name === brief.name), brief));
  return {
    ...prev,
    recent,
    unseen: announce ? prev.unseen + 1 : prev.unseen
  };
}

/**
 * Fold one frame into the state.
 *
 * `seen` is true when the reader is currently looking at the surface that
 * shows reports; an arrival they are watching is not an arrival they need to
 * be told about.
 */
export function reduceLiveEvent(
  prev: LiveState,
  name: LiveEventName | string,
  data: unknown,
  seen = false,
  project?: string
): LiveState {
  const d = (data && typeof data === 'object' && !Array.isArray(data) ? data : {}) as Record<string, unknown>;
  switch (name) {
    case 'hello': {
      const next: LiveState = {
        ...prev,
        connected: true,
        inFlight: inFlightFlag(d.in_flight),
        queued: num(d.queue_depth),
        unread: num(d.unread_count),
        quarantined: num(d.quarantined_count),
        watcher: text(d.watcher_state)
      };
      const brief = briefFrom(d.latest_report);
      // The snapshot's report is the state of the world on connect, not news:
      // it must not raise an unseen count for something that happened before
      // the reader arrived.
      // A named project requires exact attribution; missing is not local.
      if (!brief || (project !== undefined && brief.project !== project)) return next;
      return { ...next, recent: place(next.recent, brief) };
    }
    case 'heartbeat':
      return {
        ...prev,
        connected: true,
        inFlight: inFlightFlag(d.in_flight) ?? prev.inFlight,
        watcher: text(d.watcher_state) ?? prev.watcher
      };
    case 'queue':
      // `queue_depth`. The contract has always said so; the component read
      // `depth` and the counter never moved after `hello`.
      return { ...prev, queued: num(d.queue_depth) ?? prev.queued };
    case 'report': {
      const brief = briefFrom(d);
      return brief && !(project !== undefined && brief.project !== project)
        ? withReport(prev, brief, seen) : prev;
    }
    default:
      return prev;
  }
}

/** The reader looked. Nothing is new any more. */
export function markSeen(prev: LiveState): LiveState {
  return prev.unseen === 0 ? prev : { ...prev, unseen: 0 };
}

/** The stream dropped. The numbers stand, and stop claiming to be current. */
export function markDisconnected(prev: LiveState): LiveState {
  return prev.connected ? { ...prev, connected: false } : prev;
}

export type LiveExecutionTone = 'ok' | 'warn' | 'muted';

export interface LiveExecutionInput {
  streamLive?: boolean;
  /**
   * `/api/events` has historically emitted this observation as either the
   * integer contract (0/1) or, on the legacy file-bridge projection still
   * used by the canonical Ikarus line, a JSON boolean. Both shapes mean the
   * same measured fact. Accept them here at the projection boundary instead
   * of letting a transport representation turn "one task is running" into
   * "counter unknown" in the cockpit.
   */
  inFlight?: number | boolean;
  queued?: number;
}

export interface LiveExecutionStatus {
  text: string;
  tone: LiveExecutionTone;
  stale: boolean;
}

/**
 * Turn raw event-stream counters into one honest execution sentence.
 *
 * The live SSE counters are observations, not durable workflow state. Once the
 * stream disconnects they become stale immediately: retaining the numbers is
 * useful evidence, but presenting them as current would make the Cockpit look
 * more certain than the runtime actually is. Invalid counters are discarded
 * rather than rendered as negative/NaN task counts.
 *
 * `in_flight` has two observed wire representations in this repository: the
 * canonical SSE contract says integer 0/1, while the legacy bridge projection
 * still returns `bool(st["in_flight"])`. A boolean is therefore normalized to
 * exactly 0/1 here. No other coercion is accepted: strings such as "1" remain
 * unknown evidence rather than being guessed into a count.
 */
export function liveExecutionStatus({ streamLive, inFlight, queued }: LiveExecutionInput): LiveExecutionStatus {
  const active = inFlightFlag(inFlight);
  const waiting = num(queued);
  const measured = active !== undefined || waiting !== undefined;

  const counts = [
    active !== undefined ? `${active} aktiv` : '',
    waiting !== undefined ? `${waiting} wartend` : ''
  ].filter(Boolean).join(' · ');

  if (streamLive) {
    if (!measured) {
      return { text: 'Ausführung live · Zähler unbekannt', tone: 'warn', stale: false };
    }
    if (active === 0 && waiting === 0) {
      return { text: 'Ausführung live · nichts aktiv', tone: 'ok', stale: false };
    }
    const incomplete = active === undefined || waiting === undefined;
    return {
      text: `Ausführung live · ${counts}${incomplete ? ' · teilweise unbekannt' : ''}`,
      tone: incomplete ? 'warn' : 'ok', stale: false
    };
  }

  if (measured) {
    return {
      text: `Ereignisstrom getrennt · letzter Stand: ${counts}`,
      tone: 'warn',
      stale: true
    };
  }
  return {
    text: 'kein Ereignisstrom · Ausführungsstand unbekannt',
    tone: 'muted',
    stale: true
  };
}

const SAFE_PROJECT_TOKEN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

export interface WatcherGuidance {
  message: string;
  command?: string;
}

function watcherStartCommand(project: string): string | undefined {
  if (!SAFE_PROJECT_TOKEN.test(project)) return undefined;
  return `python -m daedalus.file_bridge watch --project ${project}`;
}

/**
 * Turn a FRESH bridge heartbeat verdict into the smallest safe next action.
 *
 * This is guidance only: the cockpit does not acquire execution authority and
 * never restarts a runtime by itself. Most importantly, a disconnected stream
 * cannot turn cached watcher state into a fresh operational recommendation.
 *
 * `stale` is intentionally NOT treated like `stopped`: a stale heartbeat only
 * proves that no fresh heartbeat was observed. The old process may still be
 * alive or blocked, so showing a bare start command there can create a second
 * watcher and duplicate work/provider spend. Only a state that explicitly says
 * no watcher is running gets a start command.
 */
export function watcherGuidance(
  value: string | undefined,
  project: string,
  evidenceLive: boolean
): WatcherGuidance | undefined {
  if (!evidenceLive || !value) return undefined;
  const state = value.toLowerCase();
  if (state === 'none' || state === 'stopped') {
    const command = watcherStartCommand(project);
    return {
      message: 'Aktion empfohlen: Bridge-Wächter starten',
      ...(command ? { command } : {})
    };
  }
  if (state === 'stale') {
    return {
      message: 'Aktion empfohlen: Wächterprozess prüfen; erst nach bestätigtem Stillstand neu starten'
    };
  }
  if (state === 'wedged') {
    return {
      message: 'Aktion empfohlen: laufenden Auftrag und Provider prüfen; nicht erneut dispatchen'
    };
  }
  return undefined;
}
