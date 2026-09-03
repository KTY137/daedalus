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
 * the whole surface is built on. A malformed frame leaves the previous state
 * untouched rather than blanking a counter that was true a second ago.
 */

/** One finished run, as `report_brief` publishes it. */
export interface ReportBrief {
  name: string;
  status: string;
  lane: string;
  project?: string;
  summary?: string;
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
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value ? value : undefined;
}

/** A report brief, or nothing. A frame without a name is not a report. */
export function briefFrom(value: unknown): ReportBrief | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  const row = value as Record<string, unknown>;
  const name = text(row.name);
  if (!name) return undefined;
  return {
    name,
    status: text(row.status) || 'unbekannt',
    lane: text(row.lane) || '',
    project: text(row.project),
    summary: text(row.summary)
  };
}

/** Put a report at the head, replacing any earlier copy of the same name. */
function place(recent: ReportBrief[], brief: ReportBrief): ReportBrief[] {
  const rest = recent.filter((row) => row.name !== brief.name);
  return [brief, ...rest].slice(0, RECENT_LIMIT);
}

function sameContent(a: ReportBrief | undefined, b: ReportBrief): boolean {
  return (
    !!a && a.name === b.name && a.status === b.status && a.lane === b.lane
    && a.project === b.project && a.summary === b.summary
  );
}

function withReport(prev: LiveState, brief: ReportBrief, seen: boolean): LiveState {
  // The identical report arriving again (a reconnect replays `hello`, the bus
  // republishes its tail) is not a new arrival. The same NAME carrying new
  // content is: the row is replaced and, if nobody was looking, announced.
  if (sameContent(prev.recent[0], brief)) return prev;
  const known = prev.recent.some((row) => row.name === brief.name);
  const announce = !seen && !(known && sameContent(prev.recent.find((r) => r.name === brief.name), brief));
  return {
    ...prev,
    recent: place(prev.recent, brief),
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
  seen = false
): LiveState {
  const d = (data && typeof data === 'object' && !Array.isArray(data) ? data : {}) as Record<string, unknown>;
  switch (name) {
    case 'hello': {
      const next: LiveState = {
        ...prev,
        connected: true,
        inFlight: num(d.in_flight) ?? prev.inFlight,
        queued: num(d.queue_depth) ?? prev.queued,
        unread: num(d.unread_count) ?? prev.unread,
        quarantined: num(d.quarantined_count) ?? prev.quarantined,
        watcher: text(d.watcher_state) ?? prev.watcher
      };
      const brief = briefFrom(d.latest_report);
      // The snapshot's report is the state of the world on connect, not news:
      // it must not raise an unseen count for something that happened before
      // the reader arrived.
      if (!brief) return next;
      return { ...next, recent: place(next.recent, brief) };
    }
    case 'heartbeat':
      return {
        ...prev,
        connected: true,
        inFlight: num(d.in_flight) ?? prev.inFlight,
        watcher: text(d.watcher_state) ?? prev.watcher
      };
    case 'queue':
      // `queue_depth`. The contract has always said so; the component read
      // `depth` and the counter never moved after `hello`.
      return { ...prev, queued: num(d.queue_depth) ?? prev.queued };
    case 'report': {
      const brief = briefFrom(d);
      return brief ? withReport(prev, brief, seen) : prev;
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
