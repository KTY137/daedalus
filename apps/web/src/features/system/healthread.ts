/**
 * WHAT THE HEALTH READ ACTUALLY ASKED, AND WHAT IT COST.
 *
 * `/api/health` takes parameters, and the endpoint's own comment says why the
 * expensive ones are off by default and why the answer reports them:
 *
 *   "`deep` and `probe_remote` are OFF unless asked for: the first calls the
 *    latent route (~7s cold) and the second embeds against a host that is not
 *    this machine. A browser tab must not be able to start either by accident,
 *    AND THE RESPONSE SAYS WHICH WERE SKIPPED rather than letting `present`
 *    read as `working`."
 *
 * The backend added `asked` for exactly that purpose. The cockpit dropped it,
 * so the last step of the intent never happened.
 *
 * ROOT CAUSE, and it is worth recording: `asked` was typed on `HealthPayload`
 * -- the envelope -- while the backend writes it inside `health`. Through the
 * typed path `payload.asked` was therefore always `undefined`. The field was
 * not forgotten; it was unreachable.
 *
 * THE SCOPED-READ HAZARD IS THE POINT. `?only=<name>` narrows the board.
 * Measured 2026-09-03: `GET /api/health?only=git` returns ONE subsystem with
 * `counts: {working: 1, present: 0, degraded: 0, absent: 0, unknown: 0}` -- a
 * perfect green board, and the panel's own summary line would read "1 Prüfung
 * · Nichts Auffälliges". Nineteen checks did not run, and nothing on screen
 * said so. A scoped read is not the system's health, and it must not be able
 * to look like it.
 */

export interface HealthAsked {
  deep: boolean;
  probe_remote: boolean;
  only: string | null;
}

/** How thorough the read was, in the backend's own terms. */
export function readMode(asked: HealthAsked | undefined): string {
  if (!asked) return 'Umfang nicht gemeldet';
  const parts = [asked.deep ? 'tief' : 'flach'];
  parts.push(asked.probe_remote ? 'entfernte Hosts geprüft' : 'entfernte Hosts nicht angestoßen');
  return parts.join(' · ');
}

/**
 * The warning for a scoped board, or null when the board is whole.
 *
 * This returns a sentence rather than a boolean because the reader needs the
 * filter that was applied: "scoped" without saying to WHAT is not actionable.
 */
export function scopeNote(asked: HealthAsked | undefined, shown: number): string | null {
  const only = (asked?.only || '').trim();
  if (!only) return null;
  const count = shown === 1 ? '1 Prüfung' : `${shown} Prüfungen`;
  return `Gefiltert auf „${only}“ — ${count} von allen. Das ist nicht der Zustand des Systems, `
    + 'sondern ein Ausschnitt davon.';
}

/** True when the expensive probes were skipped, which is the default. */
export function shallow(asked: HealthAsked | undefined): boolean {
  if (!asked) return false;
  return !asked.deep || !asked.probe_remote;
}

/**
 * A probe's cost, in seconds, as the backend measured it.
 *
 * German decimal comma, and two places because the interesting range here is
 * hundredths: measured 2026-09-03, the twenty subsystems ran from 0.00s to
 * 2.06s and summed to 10.62s -- which is the whole of the ~10.6s a health read
 * takes. Rounding to whole seconds would turn most rows into "0 s" and hide
 * exactly the distribution that explains the wait.
 */
export function costText(seconds: number | null | undefined): string {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return '';
  return `${seconds.toFixed(2).replace('.', ',')} s`;
}

/** What the whole board cost, summed from the rows that reported a cost. */
export function totalCost(subsystems: Array<{ seconds?: number | null }>): number {
  return subsystems.reduce(
    (sum, s) => sum + (typeof s.seconds === 'number' && Number.isFinite(s.seconds) && s.seconds > 0 ? s.seconds : 0),
    0
  );
}
