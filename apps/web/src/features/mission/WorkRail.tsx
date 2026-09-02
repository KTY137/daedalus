import type { DraftRow } from '@/shared/api';
import type { OpenDispatch } from '@/features/conversation/model';
import { relativeTime } from '@/features/conversation/model';

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
            <li key={d.ref} className="work-row live">
              <span className="work-row-what">{d.summary || 'Aufgabe übergeben'}</span>
              <span className="work-row-meta">
                <code>{d.ref}</code>
                {d.since && <span>seit {relativeTime(d.since) || d.since}</span>}
                <span>noch kein Bericht</span>
              </span>
            </li>
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
      </Section>
    </div>
  );
}
