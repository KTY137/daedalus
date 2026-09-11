import { useState } from 'react';
import type { ProgressEvent, UnitProgress } from '@/shared/api';

/**
 * THE TIMELINE of one unit of work.
 *
 * `daedalus/progress.py` records every step of a run as an event with a kind,
 * an append timestamp and — mandatory, enforced in `__post_init__` — the
 * source that recorded it, because "an unattributed fact is exactly how a
 * self-report gets laundered into evidence". `_task_snapshot` has carried the
 * whole snapshot on every bus row it could build one for; the cockpit typed
 * it as an opaque record and drew none of it.
 *
 * TWO REFUSALS THIS COMPONENT INHERITS FROM THE BACKEND AND KEEPS.
 *
 * 1. There is no percentage. `fraction_hint` is the backend's own sentence
 *    explaining why a single unit has no honest denominator, and the surface
 *    states the refusal and quotes the sentence. (It is NOT always the same
 *    sentence: for a unit the log has never seen, `progress.py` answers
 *    "no events recorded for this unit_id" instead, which the not-found
 *    branch below renders on its own.) A bar here would be a picture of a
 *    measurement nobody made.
 * 2. `succeeded` and `applied` are tri-state. `null` means the run recorded no
 *    verdict — which is not failure, and above all not success. Each is drawn
 *    with its own word, and `null` says so. The colour of the terminal step
 *    follows that verdict, never the word `done`.
 */

/**
 * `EVENT_KINDS` from `daedalus/progress.py`, all ten, in the reader's words.
 *
 * There is no `failed` and no `cancelled` kind: a run that failed records
 * `done` with `succeeded: false`, which is exactly why the tone below is
 * taken from the verdict and not from the word. An earlier version of this
 * map invented those two and omitted four real ones, so the four rendered as
 * raw English identifiers in a German cockpit.
 */
const KIND_WORD: Record<string, string> = {
  queued: 'eingereiht',
  claimed: 'angenommen',
  heartbeat: 'Lebenszeichen',
  generating: 'erzeugt',
  tool_ran: 'Werkzeug gelaufen',
  gate_verdict: 'Gate-Urteil',
  disk_changed: 'Dateien geändert',
  no_change: 'nichts geändert',
  // A patch that exists is not a change that landed. The word says produced.
  patch_produced: 'Patch erzeugt',
  done: 'abgeschlossen'
};

function kindLabel(kind: string): { text: string; verbatim: boolean } {
  const known = KIND_WORD[(kind || '').toLowerCase()];
  return known ? { text: known, verbatim: false } : { text: kind || 'unbekannt', verbatim: true };
}

/**
 * The colour of a step.
 *
 * `done` is NOT green by itself. `progress.py` records a failure as `done`
 * with `succeeded: false`, so painting the word would tell a reader that a
 * failed run finished well — the "finished is not succeeded" collapse that
 * module's own docstring exists to prevent. The verdict decides; a `done`
 * with no verdict recorded is drawn as unproven (amber) rather than green.
 */
function kindTone(kind: string, succeeded: boolean | null | undefined): string {
  const k = (kind || '').toLowerCase();
  if (k === 'done') {
    if (succeeded === true) return 'ok';
    if (succeeded === false) return 'bad';
    return 'warn';
  }
  if (k === 'gate_verdict') return 'warn';
  if (k === 'disk_changed' || k === 'patch_produced') return 'warn';
  return '';
}

function clock(ts: string): string {
  const at = Date.parse(ts);
  if (!Number.isFinite(at)) return ts;
  try {
    return new Date(at).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return ts;
  }
}

/** How many detail keys one step prints before it says there are more. */
const DETAIL_LIMIT = 6;

/** A step's detail, as short key/value pairs. Objects print as JSON. */
function detailPairs(detail: Record<string, unknown> | undefined): Array<[string, string]> {
  if (!detail) return [];
  return Object.entries(detail).slice(0, DETAIL_LIMIT).map(([key, value]) => {
    if (value === null || value === undefined) return [key, '—'];
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      return [key, String(value)];
    }
    try {
      return [key, JSON.stringify(value)];
    } catch {
      return [key, '—'];
    }
  });
}

/**
 * A step's own verdict, preferred over the unit's.
 *
 * `progress.py` derives the unit-level `succeeded` FROM a done event's
 * `detail.succeeded`. Colouring every step from the unit verdict meant that a
 * run with two `done` events painted both with the later one's colour. The
 * event's own detail is the truer source; the unit verdict is the fallback
 * for a `done` that recorded none.
 */
function stepVerdict(
  event: ProgressEvent,
  unit: boolean | null | undefined
): boolean | null | undefined {
  const own = (event.detail || {}).succeeded;
  if (own === true || own === false) return own;
  return unit;
}

function Step({ event, succeeded }: { event: ProgressEvent; succeeded: boolean | null | undefined }) {
  const kind = kindLabel(event.kind);
  const pairs = detailPairs(event.detail);
  const total = Object.keys(event.detail || {}).length;
  return (
    <li className={`step ${kindTone(event.kind, stepVerdict(event, succeeded))}`.trim()}>
      <span className="step-when">{clock(event.ts)}</span>
      <span className={kind.verbatim ? 'step-kind mono' : 'step-kind'}>{kind.text}</span>
      {/* The source is never optional: the log refuses an event without one. */}
      <span className="step-source">{event.source}</span>
      {pairs.length > 0 && (
        <span className="step-detail">
          {pairs.map(([key, value]) => (
            <span key={key}>
              {key} <code>{value}</code>
            </span>
          ))}
          {/* Several recorders land at exactly the limit, so one more key
              would drop silently. Truncation says so. */}
          {total > pairs.length && <span>und {total - pairs.length} weitere</span>}
        </span>
      )}
    </li>
  );
}

/** Tri-state, in words. `null` is a recorded absence of a verdict. */
function verdict(label: string, value: boolean | null | undefined, yes: string, no: string): string {
  if (value === true) return `${label} ${yes}`;
  if (value === false) return `${label} ${no}`;
  return `${label} nicht gemeldet`;
}

export function Timeline({ progress }: { progress: UnitProgress }) {
  const [open, setOpen] = useState(false);
  const steps = progress.narrative || [];

  if (!progress.found) {
    return <p className="work-detail-note">{progress.fraction_hint || 'Für diese Einheit ist nichts aufgezeichnet.'}</p>;
  }

  return (
    <div className="timeline">
      <span className="work-row-meta">
        {/* Why there is no percentage here, in the backend's own words.
            This was briefly a `title` on a bare span, which is mouse-only:
            keyboard users could never reach it and screen-reader exposure of
            `title` is inconsistent. In a surface whose rule is that the REASON
            must be on screen, that put the honest half off screen. */}
        <span className="work-no-fraction">
            ohne Prozentangabe{progress.fraction_hint ? ` — ${progress.fraction_hint}` : ''}
        </span>
        {progress.latest_kind && <span>zuletzt {kindLabel(progress.latest_kind).text}</span>}
        {typeof progress.age_s === 'number' && <span>vor {Math.round(progress.age_s)} s</span>}
        {progress.stalled && <span className="work-stale">festgefahren</span>}
        {typeof progress.claimed_age_s === 'number' && <span>angenommen vor {Math.round(progress.claimed_age_s)} s</span>}
        <span>{verdict('Erfolg', progress.succeeded, 'ja', 'nein')}</span>
        <span>{verdict('Übernommen', progress.applied, 'ja', 'nein')}</span>
      </span>

      {steps.length > 0 ? (
        <>
          <button type="button" className="timeline-toggle" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open
              ? 'Schritte verbergen'
              : `${progress.events_seen} ${progress.events_seen === 1 ? 'Schritt' : 'Schritte'} zeigen`}
          </button>
          {open && (
            <ol className="steps">
              {steps.map((event, i) => (
                <Step key={`${event.ts}-${event.kind}-${i}`} event={event} succeeded={progress.succeeded} />
              ))}
            </ol>
          )}
        </>
      ) : (
        <p className="work-detail-note">
          {progress.events_seen > 0
            ? `${progress.events_seen} Schritte gezählt, aber keiner mitgeliefert.`
            : 'Keine Schritte aufgezeichnet.'}
        </p>
      )}
    </div>
  );
}
