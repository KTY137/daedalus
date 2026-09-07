import { liveExecutionStatus } from './liveExecution';
import type { LiveReportBrief, LiveWorkState } from './liveWork';

const WATCHER: Record<string, string> = {
  running: 'läuft',
  idle: 'wartet',
  stopped: 'gestoppt',
  stale: 'veraltet',
  none: 'nicht gestartet'
};

function watcherWord(value: string | undefined): string {
  if (!value) return 'unbekannt';
  return WATCHER[value.toLowerCase()] || value;
}

function reportLine(report: LiveReportBrief): string {
  const lane = report.lane ? ` · ${report.lane}` : '';
  return `${report.name} · ${report.status}${lane}`;
}

/**
 * A compact JARVIS-style glance: what is running, what needs attention, and
 * what most recently finished. Every datum is a projection of the canonical
 * project event stream; this card owns no task state and can start nothing.
 */
export function WorkPulse({ project, live }: { project: string; live: LiveWorkState }) {
  const scoped = live.project === project ? live : { project, connected: null as const };
  const execution = liveExecutionStatus({
    streamLive: scoped.connected === true,
    inFlight: scoped.inFlight,
    queued: scoped.queued
  });
  const attentionKnown = scoped.unread !== undefined || scoped.quarantined !== undefined;
  const attention = (scoped.unread || 0) + (scoped.quarantined || 0);
  const stale = scoped.connected === false;

  return (
    <section className="focuscard workpulse" aria-label="Live-Arbeit" data-live-project={scoped.project}>
      <span className="focuscard-eyebrow">Gerade jetzt</span>
      <b className="focuscard-name">{execution.text}</b>
      <span className="focuscard-path">
        Wächter: {watcherWord(scoped.watcher)}
        {stale ? ' · letzter beobachteter Stand' : scoped.connected === null ? ' · Live-Evidenz ausstehend' : ''}
      </span>

      <span className="focuscard-counts">
        {attentionKnown
          ? attention > 0
            ? `${attention} braucht Aufmerksamkeit${scoped.unread ? ` · ${scoped.unread} ungelesen` : ''}${scoped.quarantined ? ` · ${scoped.quarantined} Quarantäne` : ''}`
            : 'Nichts als ungelesen oder quarantiniert gemeldet'
          : 'Aufmerksamkeitszähler noch nicht gemeldet'}
        {attentionKnown && stale ? ' · beim letzten Verbinden gezählt' : ''}
      </span>

      {scoped.latest ? (
        <div className="focuscard-counts" aria-label="Letzter Bericht">
          <span>Zuletzt berichtet: {reportLine(scoped.latest)}</span>
          {scoped.latest.summary ? <span> · {scoped.latest.summary}</span> : null}
        </div>
      ) : (
        <span className="focuscard-counts">Noch kein Abschlussbericht beobachtet</span>
      )}
    </section>
  );
}
