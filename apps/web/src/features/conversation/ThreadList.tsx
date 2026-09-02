import { useEffect, useRef, useState } from 'react';
import { listConversations, type ConversationListRow } from '@/shared/api';
import { relativeTime } from './model';

/**
 * VERLAUF — this project's threads, from the canonical spine.
 *
 * The cockpit could resume one thread per project because it remembered one
 * id; every other thread was unreachable. This list is read from
 * `GET /api/conversations?project=` (G1-UI-05), which derives it from the
 * `conversation.turn` facts already on the spine — no second registry, no
 * titles the browser made up. The title is the first thing the person said.
 *
 * Three states, all visible: read, reading, could not read. A list that
 * cannot be read says so and can be asked again; it never shows an empty
 * list as if nothing had ever been said.
 *
 * No motion: the list re-reads after every settled turn, and a rail that
 * staged a reveal each time would be a page load wearing a costume.
 */

export interface ThreadListProps {
  project: string;
  /** the thread currently open, so it can be marked */
  current: string;
  /** bump to re-read — after a turn settles, after a new thread's first turn */
  refreshKey: number;
  onPick: (conversationId: string) => void;
  onNew: () => void;
  /** a runtime id in the reader's words, or nothing when that is not known */
  labelOf: (id: string) => string | undefined;
}

type ListState =
  | { kind: 'reading' }
  | { kind: 'read'; rows: ConversationListRow[] }
  | { kind: 'failed'; reason: string };

function titleOf(row: ConversationListRow): string {
  const text = (row.first_message || '').trim().replace(/\s+/g, ' ');
  return text || 'Ohne Wortlaut';
}

export function ThreadList({ project, current, refreshKey, onPick, onNew, labelOf }: ThreadListProps) {
  const [state, setState] = useState<ListState>({ kind: 'reading' });
  const [serial, setSerial] = useState(0);

  // Rows belong to the project they were read for. On a project change the
  // list goes back to "reading" (review 2026-09-02: a still-visible row of the
  // previous project could otherwise be picked and bound to the new one); on
  // a mere refresh the old rows stay up until the new ones land.
  const lastProject = useRef(project);
  useEffect(() => {
    if (!project) {
      setState({ kind: 'read', rows: [] });
      return;
    }
    let alive = true;
    const switched = lastProject.current !== project;
    lastProject.current = project;
    setState((prev) => (prev.kind === 'read' && !switched ? prev : { kind: 'reading' }));
    listConversations(project)
      .then((payload) => {
        if (!alive) return;
        setState({ kind: 'read', rows: payload.conversations || [] });
      })
      .catch((reason: unknown) => {
        if (!alive) return;
        setState({ kind: 'failed', reason: reason instanceof Error ? reason.message : 'unbekannter Fehler' });
      });
    return () => {
      alive = false;
    };
  }, [project, refreshKey, serial]);

  const rows = state.kind === 'read' ? state.rows : [];
  // The open thread may be newer than the list (its first turn has not
  // settled yet). It is drawn at the top from what this page knows, so the
  // marker is never missing from its own list.
  const known = rows.some((r) => r.conversation_id === current);

  return (
    <nav className="threads" aria-label="Verläufe">
      <div className="threads-head">
        <span className="threads-role">Verlauf</span>
        <button type="button" className="threads-new" onClick={onNew}>
          Neuer Chat
        </button>
      </div>

      {state.kind === 'reading' && <p className="threads-note">Verläufe werden gelesen …</p>}
      {state.kind === 'failed' && (
        <div className="threads-note failed">
          <p>Die Verläufe konnten nicht gelesen werden: {state.reason}</p>
          <button type="button" onClick={() => setSerial((n) => n + 1)}>
            Erneut lesen
          </button>
        </div>
      )}
      {state.kind === 'read' && rows.length === 0 && !current && (
        <p className="threads-note">Noch kein Verlauf in diesem Projekt.</p>
      )}

      {(rows.length > 0 || (current && !known)) && (
        <ul className="threads-list" role="list">
          {current && !known && (
            <li className="threads-row current" aria-current="true">
              <span className="threads-title">Dieser Verlauf</span>
              <span className="threads-meta">noch ohne gespeicherten Turn</span>
            </li>
          )}
          {rows.map((row) => {
            const isCurrent = row.conversation_id === current;
            const route = row.last_provider_used
              ? row.last_provider_used === 'deterministic'
                ? 'lokaler Index'
                : labelOf(row.last_provider_used) || row.last_provider_used
              : '';
            const when = relativeTime(row.last_ts);
            return (
              <li key={row.conversation_id} className={isCurrent ? 'threads-row current' : 'threads-row'} aria-current={isCurrent ? 'true' : undefined}>
                <button type="button" onClick={() => onPick(row.conversation_id)} title={row.conversation_id}>
                  <span className="threads-title">{titleOf(row)}</span>
                  <span className="threads-meta">
                    <span>{row.turn_count} {row.turn_count === 1 ? 'Turn' : 'Turns'}</span>
                    {when && <span>{when}</span>}
                    {route && <span>{route}</span>}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}
