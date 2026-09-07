export type LiveExecutionTone = 'ok' | 'warn' | 'muted';

export interface LiveExecutionInput {
  streamLive?: boolean;
  inFlight?: number;
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
 */
export function liveExecutionStatus({ streamLive, inFlight, queued }: LiveExecutionInput): LiveExecutionStatus {
  const count = (value: number | undefined): number | undefined =>
    typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.floor(value) : undefined;
  const active = count(inFlight);
  const waiting = count(queued);
  const measured = active !== undefined || waiting !== undefined;

  const counts = [
    active !== undefined ? `${active} aktiv` : '',
    waiting !== undefined ? `${waiting} wartend` : ''
  ].filter(Boolean).join(' · ');

  if (streamLive) {
    if (!measured) {
      return { text: 'Ausführung live · Zähler unbekannt', tone: 'warn', stale: false };
    }
    if ((active ?? 0) === 0 && (waiting ?? 0) === 0) {
      return { text: 'Ausführung live · nichts aktiv', tone: 'ok', stale: false };
    }
    return { text: `Ausführung live · ${counts}`, tone: 'ok', stale: false };
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
