/**
 * DID THE WORK LAND, AND IF NOBODY KNOWS, WHY NOT.
 *
 * `_derive_applied` in `daedalus/interfaces/http/web_api.py` is careful in a
 * way the cockpit was throwing away. It reads whichever signals a report
 * actually carries and returns `None` -- not `True` -- when it cannot tell,
 * "the same discipline health.py applies to its own five-state vocabulary, at
 * this layer". Alongside that verdict it writes `applied_reason`: a sentence
 * saying which signal it read, or which one was missing.
 *
 * The detail view rendered `applied_reason` in exactly one place: the branch
 * for a task the bus could not find at all. For a task it DID find -- the case
 * where the sentence is the actual explanation -- the field was dropped, and
 * the surface said "Übernommen nicht gemeldet" without ever saying why nobody
 * reported it.
 *
 * Measured on a real failed dispatch, 2026-09-03:
 *
 *   applied         null
 *   applied_reason  "bridge_status=failed, but the on-disk outcome is unproven
 *                    because no write/rollback evidence was retained"
 *
 * That sentence is the difference between "we looked and nothing was written"
 * and "nobody retained the evidence either way". The first invites a reader to
 * move on; the second tells them the run is unaudited.
 */

export type AppliedReading = 'applied' | 'not_applied' | 'unproven';

export const APPLIED_WORD: Record<AppliedReading, string> = {
  applied: 'übernommen',
  not_applied: 'nicht übernommen',
  unproven: 'nicht nachweisbar'
};

/**
 * Tri-state, and `null` is NOT "no".
 *
 * `null` means the endpoint could not tell. Drawing it as "nicht übernommen"
 * would assert a measurement nobody made -- and in the direction that reads as
 * reassuring, because "nothing was written" sounds like a clean tree.
 */
export function appliedReading(applied: boolean | null | undefined): AppliedReading {
  if (applied === true) return 'applied';
  if (applied === false) return 'not_applied';
  return 'unproven';
}

/** Only a positive, measured application is green. Unproven is never green. */
export function appliedTone(reading: AppliedReading): string {
  if (reading === 'applied') return 'ok';
  if (reading === 'not_applied') return 'warn';
  return 'warn';
}

export interface LaneReading {
  /** what the caller asked for */
  requested: string;
  /** what actually ran, when the backend named it and it differs */
  actual: string | null;
  /** true when the two disagree — never collapsed to one line */
  diverged: boolean;
}

/**
 * The lane, and the lane that actually ran.
 *
 * The detail view rendered `requested_lane || lane`, which shows ONE value and
 * silently hides the case where they differ. A task requested on `local_only`
 * that actually ran somewhere else is the single most important thing that
 * could be said about it -- `local_only` exists to keep work off external
 * providers, so a divergence there is a containment question, not a detail.
 */
export function laneReading(
  task: { lane?: string | null; requested_lane?: string | null }
): LaneReading | null {
  const requested = (task.requested_lane || '').trim();
  const actual = (task.lane || '').trim();
  if (!requested && !actual) return null;
  if (!requested) return { requested: actual, actual: null, diverged: false };
  if (!actual || actual === requested) return { requested, actual: null, diverged: false };
  return { requested, actual, diverged: true };
}

/**
 * Who actually ran it — including the answer "nobody", which the surface used
 * to render as nothing at all.
 *
 * `actual_providers: []` on a task that has reached a terminal state is a
 * FACT: no provider accepted the work. On the real failed dispatch above it is
 * the crux, and the error says so in words ("the trusted local bench did not
 * accept the task"). Rendering the empty list as silence left the reader to
 * infer it.
 *
 * On a task that has NOT finished, an empty list means only "not yet", so it
 * stays silent — an absence that is merely early is not evidence.
 */
export function providerReading(
  providers: string[] | undefined,
  terminal: boolean
): { text: string; none: boolean } | null {
  const named = (providers || []).filter(Boolean);
  if (named.length > 0) return { text: named.join(', '), none: false };
  if (!terminal) return null;
  return { text: 'kein Provider hat den Auftrag angenommen', none: true };
}

/** Terminal in the task-state vocabulary this endpoint uses. */
export function isTerminalState(state: string | undefined): boolean {
  const s = (state || '').toLowerCase();
  return s === 'done' || s === 'completed' || s === 'succeeded'
    || s === 'failed' || s === 'quarantined';
}
