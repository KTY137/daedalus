import type { LiveEventName } from '../types';

/**
 * The project-scoped work facts already published by `/api/events`.
 *
 * This is deliberately an observation model, not workflow state. It has no
 * fetches, no timers and no execution authority: one decoded SSE frame goes
 * in, one immutable projection comes out. Missing or malformed fields stay
 * unknown instead of being rounded to zero.
 */
export interface LiveReportBrief {
  id?: string;
  name: string;
  project?: string;
  lane?: string;
  agent?: string;
  status: string;
  summary?: string;
  createdAt?: string;
}

export interface LiveWorkState {
  /** The project whose event stream produced every fact below. */
  project: string;
  /** null = no connection verdict yet, false = last-known evidence only. */
  connected: boolean | null;
  /** Legacy bridge emits a boolean; newer SSE contracts emit 0/1. */
  inFlight?: number | boolean;
  queued?: number;
  /** Snapshot counts: measured on hello and stale when the stream drops. */
  unread?: number;
  quarantined?: number;
  watcher?: string;
  /** Newest accepted report, kept for the compact one-line consumers. */
  latest?: LiveReportBrief;
  /** Bounded session projection; the durable ledger remains the history. */
  recent: LiveReportBrief[];
}

const RECENT_REPORT_LIMIT = 3;

export function emptyLiveWork(project = ''): LiveWorkState {
  return { project, connected: null, recent: [] };
}

function object(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function count(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 ? value : undefined;
}

function inFlight(value: unknown): number | boolean | undefined {
  if (typeof value === 'boolean') return value;
  return count(value);
}

function text(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

/**
 * Identity evidence must not be normalized while it crosses a trust boundary.
 * In particular, trimming a project string before the scope check would turn
 * `" project "` into evidence for `"project"` and defeat the byte-exact
 * attribution invariant documented by reduceLiveWork().
 */
function exactText(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

export function reportBrief(value: unknown): LiveReportBrief | undefined {
  const row = object(value);
  const name = text(row.name);
  if (!name) return undefined;
  return {
    id: text(row.id),
    name,
    project: exactText(row.project),
    lane: text(row.lane),
    agent: text(row.agent),
    status: text(row.status) || 'unbekannt',
    summary: text(row.summary),
    createdAt: text(row.created_at)
  };
}

/** Do not let a delayed older report replace a newer one when both are dated. */
function latestReport(previous: LiveReportBrief | undefined, next: LiveReportBrief): LiveReportBrief {
  if (!previous?.createdAt || !next.createdAt) return next;
  const previousAt = Date.parse(previous.createdAt);
  const nextAt = Date.parse(next.createdAt);
  if (!Number.isFinite(previousAt) || !Number.isFinite(nextAt)) return next;
  return nextAt >= previousAt ? next : previous;
}

/**
 * Keep the most recent observations without turning the UI into a second
 * history store. Report names are the bridge's stable one-line identity, so a
 * refreshed report replaces its older projection instead of appearing twice.
 */
function placeReport(previous: LiveReportBrief[], next: LiveReportBrief): LiveReportBrief[] {
  return [next, ...previous.filter((row) => row.name !== next.name)].slice(0, RECENT_REPORT_LIMIT);
}

/**
 * Fold one canonical project event into the projection.
 *
 * A project switch starts from an empty projection before applying the first
 * event, so counters can never be relabelled from project A to project B.
 * `hello` is an authoritative snapshot: absent fields clear older evidence on
 * reconnect instead of laundering it as freshly measured.
 *
 * Terminal reports have a stricter boundary than aggregate counters: their
 * project attribution must equal the selected project byte-for-byte. A
 * schemaless/legacy report with no project is not safe to assign to whichever
 * project happens to own the EventSource connection, and a foreign project is
 * never accepted even if a backend stream is accidentally misrouted.
 */
export function reduceLiveWork(
  previous: LiveWorkState,
  project: string,
  name: LiveEventName | string,
  data: unknown
): LiveWorkState {
  const prev = previous.project === project ? previous : emptyLiveWork(project);
  const d = object(data);

  if (name === 'hello') {
    const latest = reportBrief(d.latest_report);
    const scopedLatest = latest?.project === project ? latest : undefined;
    return {
      project,
      connected: true,
      inFlight: inFlight(d.in_flight),
      queued: count(d.queue_depth),
      unread: count(d.unread_count),
      quarantined: count(d.quarantined_count),
      watcher: text(d.watcher_state),
      latest: scopedLatest,
      recent: scopedLatest ? [scopedLatest] : []
    };
  }

  if (name === 'heartbeat') {
    return {
      ...prev,
      project,
      connected: true,
      inFlight: inFlight(d.in_flight) ?? prev.inFlight,
      watcher: text(d.watcher_state) ?? prev.watcher
    };
  }

  if (name === 'queue') {
    return { ...prev, project, queued: count(d.queue_depth) ?? prev.queued };
  }

  if (name === 'report') {
    const latest = reportBrief(d);
    if (!latest || latest.project !== project) return prev;
    const newest = latestReport(prev.latest, latest);
    if (newest !== latest) return { ...prev, project, latest: newest };
    return {
      ...prev,
      project,
      latest: newest,
      recent: placeReport(prev.recent, latest)
    };
  }

  return prev;
}

export function markLiveWorkDisconnected(previous: LiveWorkState, project: string): LiveWorkState {
  // A late `error` from a stream that was just closed during project switch
  // must never replace the new project's state with the old project's name.
  if (previous.project !== project) return previous;
  return previous.connected === false ? previous : { ...previous, connected: false };
}
