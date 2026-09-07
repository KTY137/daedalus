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
  latest?: LiveReportBrief;
}

export function emptyLiveWork(project = ''): LiveWorkState {
  return { project, connected: null };
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
  return typeof value === 'string' && value.trim() ? value : undefined;
}

export function reportBrief(value: unknown): LiveReportBrief | undefined {
  const row = object(value);
  const name = text(row.name);
  if (!name) return undefined;
  return {
    id: text(row.id),
    name,
    project: text(row.project),
    lane: text(row.lane),
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
 * Fold one canonical project event into the projection.
 *
 * A project switch starts from an empty projection before applying the first
 * event, so counters can never be relabelled from project A to project B.
 * `hello` is an authoritative snapshot: absent fields clear older evidence on
 * reconnect instead of laundering it as freshly measured.
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
    return {
      project,
      connected: true,
      inFlight: inFlight(d.in_flight),
      queued: count(d.queue_depth),
      unread: count(d.unread_count),
      quarantined: count(d.quarantined_count),
      watcher: text(d.watcher_state),
      latest: latest && (!latest.project || latest.project === project) ? latest : undefined
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
    if (!latest || (latest.project && latest.project !== project)) return prev;
    return { ...prev, project, latest: latestReport(prev.latest, latest) };
  }

  return prev;
}

export function markLiveWorkDisconnected(previous: LiveWorkState, project: string): LiveWorkState {
  // A late `error` from a stream that was just closed during project switch
  // must never replace the new project's state with the old project's name.
  if (previous.project !== project) return previous;
  return previous.connected === false ? previous : { ...previous, connected: false };
}
