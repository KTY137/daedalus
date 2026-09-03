import { useCallback, useState } from 'react';
import { getTask, getTaskArtifacts, type DraftRow, type TaskArtifacts, type TaskDetail } from '@/shared/api';
import type { OpenDispatch } from '@/features/conversation/model';
import { relativeTime, taskStateLabel } from '@/features/conversation/model';
import { ActivityLog } from './ActivityLog';

/**
 * ARBEIT — what waits on you, what is running, what just happened.
 *
 * The oversight literature calls this the overview panel, and its three
 * questions are always the same: is the agent working, does anything need
 * me, and what did it just do. Daedalus could answer all three from the
 * first day — `/api/events` has carried the watcher state, the unread and
 * quarantined counts and the last report brief all along, and every resumed
 * conversation carries its open dispatches — and the cockpit threw every one
 * of those away. This rail is the consumer they never had.
 *
 * THE RULE IS THE SAME AS THE PROTOKOLL'S. Every row is a fact the backend
 * emitted. A count the backend did not send is not drawn; a state it could
 * not measure says "unbekannt" rather than picking the friendly reading.
 * Nothing here is a second source of truth: the drafts come from the card
 * that already fetched them, the dispatches from the conversation that
 * already resumed them, and the counters from the one event stream.
 */

/** The live counters, exactly as the stream reports them. */
export interface LiveState {
  /** the stream is open; false means these numbers are last-known, not now */
  connected: boolean;
  inFlight?: number;
  queued?: number;
  unread?: number;
  quarantined?: number;
  watcher?: string;
  report?: { name: string; status: string; lane: string; project?: string; summary?: string };
}

export interface WorkRailProps {
  project: string;
  /** every pending draft of this project, from the decision card's own read */
  drafts: DraftRow[];
  /** whether that list is this project's, or could not be scoped */
  draftsScoped: boolean;
  live: LiveState;
  openDispatches: OpenDispatch[];
  /** the conversation is on another page; this jumps to it */
  onGoDecision: () => void;
}

/**
 * The watcher's own words where they are known, its identifier where they
 * are not. Same rule as the runtime picker: a state nobody mapped is printed
 * as the identifier it is, never rounded to a friendlier one.
 */
const WATCHER: Record<string, string> = {
  running: 'läuft',
  idle: 'wartet',
  stopped: 'gestoppt',
  stale: 'veraltet',
  none: 'nicht gestartet'
};

function watcherLabel(state: string | undefined): { text: string; verbatim: boolean } {
  if (!state) return { text: 'unbekannt', verbatim: false };
  const known = WATCHER[state.toLowerCase()];
  return known ? { text: known, verbatim: false } : { text: state, verbatim: true };
}

/**
 * ONE DISPATCH, OPENED.
 *
 * The rail knows a dispatch exists because the conversation spine recorded
 * it; it knows nothing else until someone asks the bus. `GET /api/queue/<id>`
 * and its `/artifacts` sibling have both existed since the bus did and had no
 * caller in this frontend at all, so a task nobody happened to be streaming
 * was a reference number and nothing more.
 *
 * Read on demand, never on mount: a rail that fetched every dispatch as it
 * drew would turn a glance into a fan-out.
 */
type DetailState =
  | { kind: 'shut' }
  | { kind: 'reading' }
  | { kind: 'read'; task: TaskDetail; artifacts?: TaskArtifacts }
  | { kind: 'failed'; reason: string };

function List({ label, items }: { label: string; items: string[] | undefined }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="work-detail-list">
      <span>{label}</span>
      <ul>
        {items.slice(0, 6).map((item) => (
          <li key={item}>
            <code>{item}</code>
          </li>
        ))}
      </ul>
      {items.length > 6 && <span className="work-detail-more">und {items.length - 6} weitere</span>}
    </div>
  );
}

function DispatchRow({ dispatch }: { dispatch: OpenDispatch }) {
  const [state, setState] = useState<DetailState>({ kind: 'shut' });

  const toggle = useCallback(async () => {
    if (state.kind !== 'shut') {
      setState({ kind: 'shut' });
      return;
    }
    setState({ kind: 'reading' });
    try {
      const payload = await getTask(dispatch.ref);
      const task = payload.task;
      // Artifacts exist only once the run finished; asking earlier answers
      // `available: false` with a reason, which is worth showing but is not
      // worth a second request while the task is plainly still running.
      let artifacts: TaskArtifacts | undefined;
      if (task.found && task.state !== 'queued' && task.state !== 'running') {
        try {
          artifacts = (await getTaskArtifacts(dispatch.ref)).artifacts;
        } catch {
          /* the snapshot is the answer; artifacts are the bonus */
        }
      }
      setState({ kind: 'read', task, artifacts });
    } catch (reason) {
      setState({ kind: 'failed', reason: reason instanceof Error ? reason.message : 'unbekannter Fehler' });
    }
  }, [dispatch.ref, state.kind]);

  const open = state.kind !== 'shut';

  return (
    <li className="work-row live">
      <button type="button" onClick={() => void toggle()} aria-expanded={open}>
        <span className="work-row-what">{dispatch.summary || 'Aufgabe übergeben'}</span>
        <span className="work-row-meta">
          <code>{dispatch.ref}</code>
          {dispatch.since && <span>seit {relativeTime(dispatch.since) || dispatch.since}</span>}
          <span>noch kein Bericht</span>
        </span>
      </button>

      {state.kind === 'reading' && <p className="work-detail-note">Zustand wird vom Bus gelesen …</p>}
      {state.kind === 'failed' && (
        <p className="work-detail-note bad">Der Bus konnte nicht gelesen werden: {state.reason}</p>
      )}
      {state.kind === 'read' && (
        <div className="work-detail">
          {!state.task.found ? (
            <p className="work-detail-note">
              Auf dem Bus nicht auffindbar.
              {state.task.applied_reason ? ` ${state.task.applied_reason}` : ''}
            </p>
          ) : (
            <>
              <span className="work-row-meta">
                <span>
                  Zustand <b>{taskStateLabel(state.task)}</b>
                </span>
                {(state.task.requested_lane || state.task.lane) && (
                  <span>
                    Lane <code>{state.task.requested_lane || state.task.lane}</code>
                  </span>
                )}
                {state.task.actual_providers && state.task.actual_providers.length > 0 && (
                  <span>über {state.task.actual_providers.join(', ')}</span>
                )}
                {typeof state.task.age_s === 'number' && <span>{Math.round(state.task.age_s)} s alt</span>}
                <span>Quelle {state.task.source}</span>
              </span>
              {state.task.summary && <p className="work-detail-summary">{state.task.summary}</p>}
              {state.task.error && <p className="work-detail-note bad">Fehler: {state.task.error}</p>}
              {state.artifacts && !state.artifacts.available && (
                <p className="work-detail-note">
                  Noch kein Ergebnis: {state.artifacts.reason || 'der Lauf ist nicht abgeschlossen'}
                </p>
              )}
              {state.artifacts?.available && (
                <>
                  <List label="Geändert" items={state.artifacts.files_changed} />
                  <List label="Zurückgerollt" items={state.artifacts.rolled_back} />
                  <List label="Tests" items={state.artifacts.tests_run} />
                  <List label="Entwürfe" items={state.artifacts.draft_ids} />
                  <List label="Risiken" items={state.artifacts.risks} />
                </>
              )}
            </>
          )}
        </div>
      )}
    </li>
  );
}

function Section({
  title,
  count,
  tone,
  children
}: {
  title: string;
  count?: number;
  tone: 'wait' | 'live' | 'past';
  children: React.ReactNode;
}) {
  return (
    <section className={`work-section ${tone}`}>
      <h3 className="work-head">
        <span className="work-title">{title}</span>
        {count !== undefined && count > 0 && <span className="work-count">{count}</span>}
      </h3>
      {children}
    </section>
  );
}

export function WorkRail({ project, drafts, draftsScoped, live, openDispatches, onGoDecision }: WorkRailProps) {
  const watcher = watcherLabel(live.watcher);
  const quarantined = live.quarantined || 0;
  const unread = live.unread || 0;
  /**
   * What genuinely waits on a person: a draft that is this project's, a
   * quarantined task (a run that failed in a way nobody has looked at), and
   * unread reports. `draftsScoped` is load-bearing — an unscoped draft pile
   * is real data but it is not this project's decision, so it is not counted
   * under this project's name.
   */
  const waiting = (draftsScoped ? drafts.length : 0) + quarantined + unread;
  const running = openDispatches.length + (live.inFlight || 0);

  return (
    <div className="work" aria-label="Arbeit">
      <Section title="Wartet auf dich" count={waiting} tone="wait">
        {waiting === 0 ? (
          <p className="work-none">
            {draftsScoped || !project
              ? 'Nichts. Entwürfe, zurückgestellte Läufe und ungelesene Berichte erscheinen hier.'
              : 'Projekt wird ermittelt …'}
          </p>
        ) : (
          <ul className="work-list">
            {draftsScoped &&
              drafts.map((d) => (
                <li key={d.id} className="work-row">
                  <button type="button" onClick={onGoDecision} title={d.id}>
                    <span className="work-row-what">{d.objective || d.id}</span>
                    <span className="work-row-meta">
                      <span>Entwurf</span>
                      <span>{d.agent || 'unbekannt'}</span>
                      {d.paths?.length ? <span>{d.paths.length} Pfade</span> : null}
                      {d.created && <span>{relativeTime(d.created) || d.created}</span>}
                    </span>
                  </button>
                </li>
              ))}
            {quarantined > 0 && (
              <li className="work-row bad">
                <span className="work-row-what">
                  {quarantined} {quarantined === 1 ? 'Lauf zurückgestellt' : 'Läufe zurückgestellt'}
                </span>
                <span className="work-row-meta">
                  <span>
                    In Quarantäne, bis jemand hinsieht. <code>daedalus bridge status</code> zeigt sie.
                  </span>
                </span>
              </li>
            )}
            {unread > 0 && (
              <li className="work-row">
                <span className="work-row-what">
                  {unread} {unread === 1 ? 'Bericht ungelesen' : 'Berichte ungelesen'}
                </span>
                <span className="work-row-meta">
                  <span>Auf dem Datei-Bus eingetroffen, hier noch nicht geöffnet.</span>
                </span>
              </li>
            )}
          </ul>
        )}
      </Section>

      <Section title="Läuft gerade" count={running} tone="live">
        <ul className="work-list">
          {openDispatches.map((d) => (
            <DispatchRow key={d.ref} dispatch={d} />
          ))}
          {running === 0 && openDispatches.length === 0 && (
            <li className="work-row">
              <span className="work-row-what">Nichts in Arbeit</span>
            </li>
          )}
          <li className="work-row quiet">
            <span className="work-row-meta">
              {/* Never a friendly zero: an unread stream reports what it last
                  knew, and says that it is not current. */}
              <span>
                Wächter <b className={watcher.verbatim ? 'mono' : undefined}>{watcher.text}</b>
              </span>
              {live.queued !== undefined && <span>Warteschlange {live.queued}</span>}
              {live.inFlight !== undefined && <span>{live.inFlight} in Bearbeitung</span>}
              {!live.connected && <span className="work-stale">Strom unterbrochen — Stand von zuletzt</span>}
            </span>
          </li>
        </ul>
      </Section>

      <Section title="Zuletzt" tone="past">
        {live.report ? (
          <ul className="work-list">
            <li className="work-row">
              <span className="work-row-what">{live.report.summary || 'Ohne Zusammenfassung'}</span>
              <span className="work-row-meta">
                <span>{live.report.status || 'unbekannt'}</span>
                {live.report.lane && <span>Lane {live.report.lane}</span>}
                {live.report.project && <span>{live.report.project}</span>}
                <code>{live.report.name}</code>
              </span>
            </li>
          </ul>
        ) : (
          <p className="work-none">Noch kein Bericht auf diesem Bus.</p>
        )}
        <ActivityLog />
      </Section>
    </div>
  );
}
