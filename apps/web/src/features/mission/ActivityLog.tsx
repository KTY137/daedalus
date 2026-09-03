import { useCallback, useState } from 'react';
import { getLoopAttempts, type LoopAttempt, type LoopAttemptsBlock } from '@/shared/api';
import { relativeTime } from '@/features/conversation/model';

/**
 * ZULETZT VERSUCHT — the activity log.
 *
 * The oversight literature's third surface: a reverse-chronological record of
 * what the agent attempted, so a person can audit a failure instead of
 * inferring it. `/api/loop/attempts` has served exactly this since it shipped
 * — a fixed allowlist over the canonical spine ledger — and the cockpit
 * rendered `intents.length` as a number inside a settings panel and nothing
 * else. Not one row was ever drawn.
 *
 * TWO HONESTY PROBLEMS THIS SURFACE HAS TO SOLVE, both of them in the data
 * rather than in the styling:
 *
 * 1. The endpoint is NOT project-scoped. It reads the whole ledger for this
 *    machine. Drawing it under a project's name would repeat the defect the
 *    drafts card was rebuilt for in August, so the heading says whose history
 *    this is, every time.
 * 2. The endpoint reports on its own reading. `ledger.exists:false` with no
 *    error is a fresh checkout; an `error` is a source that failed;
 *    `read_only`, `incomplete`, `degraded_sources` and `dropped_for_size` each
 *    mean the list in front of you is not the whole list. All of them are
 *    printed. An empty list under a failed read would be the exact collapse of
 *    "could not look" into "nothing to see" this repository refuses.
 *
 * Read on demand. The call is bounded at 30s by the client and walks a SQLite
 * ledger; a rail that loaded it on mount would pay for it on every glance.
 */

type LogState =
  | { kind: 'shut' }
  | { kind: 'reading' }
  | { kind: 'read'; block: LoopAttemptsBlock }
  | { kind: 'failed'; reason: string };

/** The attempt's own state, in the reader's words where they exist. */
const STATE_WORD: Record<string, string> = {
  open: 'offen',
  closed: 'abgeschlossen',
  failed: 'fehlgeschlagen',
  cancelled: 'abgebrochen'
};

function stateLabel(state: string): { text: string; verbatim: boolean } {
  const known = STATE_WORD[(state || '').toLowerCase()];
  return known ? { text: known, verbatim: false } : { text: state || 'unbekannt', verbatim: !!state };
}

function tone(attempt: LoopAttempt): string {
  if (attempt.error) return 'bad';
  if (attempt.gates_passed === false) return 'bad';
  if (attempt.state === 'open') return 'live';
  if (attempt.gates_passed === true) return 'ok';
  return '';
}

function Row({ attempt }: { attempt: LoopAttempt }) {
  const state = stateLabel(attempt.state);
  const when = relativeTime(attempt.created_ts);
  return (
    <li className={`work-row ${tone(attempt)}`.trim()}>
      <span className="work-row-what">{attempt.instruction || attempt.task_id || `Versuch ${attempt.intent_id}`}</span>
      <span className="work-row-meta">
        <span>{attempt.kind}</span>
        <span className={state.verbatim ? 'mono' : undefined}>{state.text}</span>
        {/* `outcome` is projected, not stored: absent means the ledger row
            carried no verdict, which is not the same as a failure. */}
        <span>{attempt.outcome || 'ohne Ergebnis'}</span>
        {attempt.gates_passed !== null && <span>Gates {attempt.gates_passed ? 'bestanden' : 'nicht bestanden'}</span>}
        {typeof attempt.changed_paths === 'number' && attempt.changed_paths > 0 && (
          <span>
            {attempt.changed_paths} {attempt.changed_paths === 1 ? 'Pfad' : 'Pfade'}
          </span>
        )}
        {when && <span>{when}</span>}
      </span>
      {attempt.error && <p className="work-detail-note bad">{attempt.error}</p>}
    </li>
  );
}

/** What the endpoint says about its own reading, printed rather than assumed. */
function Provenance({ block }: { block: LoopAttemptsBlock }) {
  const notes: string[] = [];
  if (!block.ledger.exists && !block.ledger.error) notes.push('Noch kein Ledger auf dieser Maschine.');
  if (block.ledger.error) notes.push(`Ledger nicht lesbar: ${block.ledger.error}`);
  if (block.ledger.note) notes.push(block.ledger.note);
  if (block.ledger.read_only) notes.push('Ledger nur lesbar.');
  if (block.incomplete) notes.push('Die Liste ist unvollständig.');
  if (block.degraded_sources.length > 0) notes.push(`Beeinträchtigt: ${block.degraded_sources.join(', ')}.`);
  if (block.dropped_for_size) notes.push(`${block.dropped_for_size} Zeilen wegen Größe weggelassen.`);
  if (notes.length === 0) return null;
  return (
    <p className={`work-detail-note${block.ledger.error ? ' bad' : ''}`}>{notes.join(' ')}</p>
  );
}

export function ActivityLog({ limit = 8 }: { limit?: number }) {
  const [state, setState] = useState<LogState>({ kind: 'shut' });

  const toggle = useCallback(async () => {
    if (state.kind !== 'shut') {
      setState({ kind: 'shut' });
      return;
    }
    setState({ kind: 'reading' });
    try {
      const payload = await getLoopAttempts(limit);
      setState({ kind: 'read', block: payload.attempts });
    } catch (reason) {
      setState({ kind: 'failed', reason: reason instanceof Error ? reason.message : 'unbekannter Fehler' });
    }
  }, [limit, state.kind]);

  const open = state.kind !== 'shut';

  return (
    <div className="work-log">
      <button type="button" className="work-log-toggle" onClick={() => void toggle()} aria-expanded={open}>
        {open ? 'Versuche verbergen' : 'Zuletzt versucht'}
      </button>

      {state.kind === 'reading' && <p className="work-detail-note">Das Ledger wird gelesen …</p>}
      {state.kind === 'failed' && (
        <p className="work-detail-note bad">Die Versuche konnten nicht gelesen werden: {state.reason}</p>
      )}
      {state.kind === 'read' && (
        <>
          {/* Whose history this is. The endpoint reads the machine's ledger,
              not this project's, and saying so is the whole reason this line
              exists. */}
          <p className="work-detail-note">Alle Versuche auf dieser Maschine, nicht nur in diesem Projekt.</p>
          <Provenance block={state.block} />
          {state.block.intents.length === 0 ? (
            <p className="work-detail-note">Keine Versuche verzeichnet.</p>
          ) : (
            <ul className="work-list">
              {state.block.intents.map((attempt) => (
                <Row key={attempt.intent_id} attempt={attempt} />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}
