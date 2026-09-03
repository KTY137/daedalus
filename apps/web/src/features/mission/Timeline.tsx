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
 * 1. `fraction_hint` is a SENTENCE, not a number. A single unit has no honest
 *    denominator, so the backend answers in words and this draws the words. A
 *    progress bar here would be a picture of a measurement nobody made.
 * 2. `succeeded` and `applied` are tri-state. `null` means the run recorded no
 *    verdict — which is not failure, and above all not success. Each is drawn
 *    with its own word, and `null` says so.
 */

/** The event kinds `progress.py` recognises, in the reader's words. */
const KIND_WORD: Record<string, string> = {
  queued: 'eingereiht',
  claimed: 'angenommen',
  heartbeat: 'Lebenszeichen',
  progress: 'Fortschritt',
  disk_changed: 'Dateien geändert',
  no_change: 'nichts geändert',
  done: 'abgeschlossen',
  failed: 'fehlgeschlagen',
  cancelled: 'abgebrochen'
};

function kindLabel(kind: string): { text: string; verbatim: boolean } {
  const known = KIND_WORD[(kind || '').toLowerCase()];
  return known ? { text: known, verbatim: false } : { text: kind || 'unbekannt', verbatim: true };
}

function kindTone(kind: string): string {
  const k = (kind || '').toLowerCase();
  if (k === 'failed' || k === 'cancelled') return 'bad';
  if (k === 'done') return 'ok';
  if (k === 'disk_changed') return 'warn';
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

/** A step's detail, as short key/value pairs. Objects print as JSON. */
function detailPairs(detail: Record<string, unknown> | undefined): Array<[string, string]> {
  if (!detail) return [];
  return Object.entries(detail).slice(0, 6).map(([key, value]) => {
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

function Step({ event }: { event: ProgressEvent }) {
  const kind = kindLabel(event.kind);
  const pairs = detailPairs(event.detail);
  return (
    <li className={`step ${kindTone(event.kind)}`.trim()}>
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
        {/* The backend's own sentence about how far along this is. It is a
            sentence because a single unit has no honest denominator. */}
        <span>{progress.fraction_hint}</span>
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
                <Step key={`${event.ts}-${event.kind}-${i}`} event={event} />
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
