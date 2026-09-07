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
  const count = (value: number | undefined): number | undefined =>
    typeof value === 'number' && Number.isFinite(value) && value >= 0 ? Math.floor(value) : undefined;
  const active = typeof inFlight === 'boolean' ? (inFlight ? 1 : 0) : count(inFlight);
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
