import { useEffect, useState } from 'react';
import { getConversation } from '../api';
import {
  dispatchPulseFromConversation,
  type DispatchDescriptionSource,
  type DispatchPulseItem,
  type DispatchPulseProjection
} from './dispatchPulse';
import { liveExecutionStatus } from './liveExecution';
import { emptyLiveWork, type LiveReportBrief, type LiveWorkState } from './liveWork';

/** Canonical heartbeat states from file_bridge. Unknown values stay verbatim. */
const WATCHER: Record<string, string> = {
  alive: 'bereit',
  busy: 'arbeitet',
  wedged: 'möglicherweise festgefahren',
  stale: 'veraltet',
  none: 'nicht gestartet',
  // Compatibility aliases for older bridge projections.
  running: 'läuft',
  idle: 'wartet',
  stopped: 'gestoppt'
};

const THREAD_KEY = 'daedalus-thread';
const SAFE_PROJECT_TOKEN = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;

type DispatchReadPhase = 'idle' | 'loading' | 'ready' | 'error';

interface DispatchRead {
  project: string;
  phase: DispatchReadPhase;
  pulse: DispatchPulseProjection;
}

export interface WatcherGuidance {
  message: string;
  command?: string;
}

function emptyDispatchRead(project = '', phase: DispatchReadPhase = 'idle'): DispatchRead {
  return { project, phase, pulse: { total: 0, unresolved: 0, items: [] } };
}

function watcherWord(value: string | undefined): string {
  if (!value) return 'unbekannt';
  return WATCHER[value.toLowerCase()] || value;
}

/**
 * Build a copy/paste command only for a project identifier that is safe as one
 * shell token on every shell we support. Project labels are still rendered by
 * React, but they must never be interpolated into executable-looking guidance
 * when whitespace, option prefixes or metacharacters could change argv.
 */
function watcherStartCommand(project: string): string | undefined {
  if (!SAFE_PROJECT_TOKEN.test(project)) return undefined;
  return `python -m daedalus.file_bridge watch --project ${project}`;
}

/**
 * Turn a FRESH bridge heartbeat verdict into the smallest safe next action.
 *
 * This is guidance only: the cockpit does not acquire execution authority and
 * never restarts a runtime by itself. Most importantly, a disconnected stream
 * cannot turn cached watcher state into a fresh operational recommendation.
 *
 * `stale` is intentionally NOT treated like `stopped`: a stale heartbeat only
 * proves that no fresh heartbeat was observed. The old process may still be
 * alive or blocked, so showing a bare start command there can create a second
 * watcher and duplicate work/provider spend. Only a state that explicitly says
 * no watcher is running gets a start command.
 */
export function watcherGuidance(
  value: string | undefined,
  project: string,
  evidenceLive: boolean
): WatcherGuidance | undefined {
  if (!evidenceLive || !value) return undefined;
  const state = value.toLowerCase();
  if (state === 'none' || state === 'stopped') {
    const command = watcherStartCommand(project);
    return {
      message: 'Aktion empfohlen: Bridge-Wächter starten',
      ...(command ? { command } : {})
    };
  }
  if (state === 'stale') {
    return {
      message: 'Aktion empfohlen: Wächterprozess prüfen; erst nach bestätigtem Stillstand neu starten'
    };
  }
  if (state === 'wedged') {
    return {
      message: 'Aktion empfohlen: laufenden Auftrag und Provider prüfen; nicht erneut dispatchen'
    };
  }
  return undefined;
}

function reportLine(report: LiveReportBrief): string {
  const agent = report.agent ? ` · Agent ${report.agent}` : '';
  const lane = report.lane ? ` · ${report.lane}` : '';
  return `${report.name} · ${report.status}${agent}${lane}`;
}

/**
 * Confidence label for dispatch identity. A bound versioned snapshot is
 * durable evidence on the dispatch fact itself; legacy action/turn text is a
 * compatibility reconstruction from the bounded conversation window and must
 * never look equally authoritative.
 */
export function dispatchEvidenceLabel(source: DispatchDescriptionSource): string {
  if (source === 'bound') return 'gebundene Evidenz';
  if (source === 'action' || source === 'turn') return 'aus Chatverlauf rekonstruiert';
  return 'Identität nicht gebunden';
}

function currentThread(project: string): string {
  try {
    return localStorage.getItem(`${THREAD_KEY}:${project}`) || '';
  } catch {
    return '';
  }
}

function shortRef(ref: string): string {
  if (ref.length <= 28) return ref;
  return `${ref.slice(0, 14)}…${ref.slice(-9)}`;
}

function briefText(value: string): string {
  return value.length <= 120 ? value : `${value.slice(0, 117)}…`;
}

function timeLabel(value: string | undefined): string {
  if (!value) return '';
  const when = new Date(value);
  if (!Number.isFinite(when.getTime())) return '';
  return when.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
}

function unresolvedDispatchText(total: number): string {
  return `${total} ${total === 1 ? 'projektgebundene Dispatch-Evidenz ist' : 'projektgebundene Dispatch-Evidenzen sind'} nicht sicher interpretierbar`;
}

function dispatchStatus(read: DispatchRead): string {
  const total = read.pulse.total;
  const unresolved = read.pulse.unresolved;
  const count = `${total} ${total === 1 ? 'offener Auftrag' : 'offene Aufträge'}`;
  const unresolvedText = unresolved > 0 ? unresolvedDispatchText(unresolved) : '';
  if (read.phase === 'loading') {
    const base = total > 0
      ? `${count} · wird mit dem kanonischen Verlauf abgeglichen`
      : 'Offene Aufträge werden mit dem kanonischen Verlauf abgeglichen';
    return unresolvedText ? `${base} · ${unresolvedText}` : base;
  }
  if (read.phase === 'error') {
    const base = total > 0
      ? `${count} · letzter lesbarer Stand; aktueller Verlauf nicht lesbar`
      : 'Offene Aufträge konnten aus dem aktuellen Verlauf nicht gelesen werden';
    return unresolvedText ? `${base} · ${unresolvedText}` : base;
  }
  if (total > 0) {
    const base = `${count} · warten auf Bericht`;
    return unresolvedText ? `${base} · ${unresolvedText}` : base;
  }
  return unresolvedText
    ? `Keine verifizierbaren offenen Aufträge · ${unresolvedText}`
    : 'Keine offenen Aufträge im aktuellen Verlauf';
}

/**
 * Render only execution facts that were frozen on the versioned dispatch
 * evidence itself. Lane or chat wording never gets promoted into an agent,
 * runtime, phase, WorkItem or Attempt identity.
 */
export function boundExecutionLine(item: DispatchPulseItem): string | undefined {
  if (item.descriptionSource !== 'bound') return undefined;
  const parts: string[] = [];
  if (item.agent) parts.push(`Agent ${briefText(item.agent)}`);
  if (item.tool) parts.push(`Tool ${briefText(item.tool)}`);
  if (item.runtimeId) parts.push(`Runtime ${briefText(item.runtimeId)}`);
  if (item.phase) parts.push(`Phase ${briefText(item.phase)}`);
  if (item.workItemId) parts.push(`WorkItem ${shortRef(item.workItemId)}`);
  if (item.attemptId) parts.push(`Attempt ${shortRef(item.attemptId)}`);
  return parts.length > 0 ? parts.join(' · ') : undefined;
}

/**
 * A compact JARVIS-style glance: what is running, what needs attention, what
 * has not reported back yet, and what most recently finished.
 *
 * Live counters/reports remain projections of the project event stream. Open
 * dispatch identity comes from the already-canonical conversation spine read;
 * this card owns no task state, starts nothing and never treats the derived
 * `open_dispatches` display as a recovery/work queue.
 */
export function WorkPulse({ project, live }: { project: string; live: LiveWorkState }) {
  const scoped = live.project === project ? live : emptyLiveWork(project);
  const [dispatchRead, setDispatchRead] = useState<DispatchRead>(() => emptyDispatchRead());
  const execution = liveExecutionStatus({
    streamLive: scoped.connected === true,
    inFlight: scoped.inFlight,
    queued: scoped.queued
  });
  const attentionComplete = scoped.unread !== undefined && scoped.quarantined !== undefined;
  const attentionKnown = scoped.unread !== undefined || scoped.quarantined !== undefined;
  const attention = (scoped.unread || 0) + (scoped.quarantined || 0);
  const stale = scoped.connected === false;
  const guidance = watcherGuidance(scoped.watcher, project, scoped.connected === true);

  /**
   * Read the durable attribution seam whenever the cheap live bus says work
   * changed shape. Queue depth, in-flight ownership and terminal reports cover
   * both slow tasks and tasks that move through the queue between two snapshots.
   * A failed read preserves the last projection but labels it as such.
   */
  useEffect(() => {
    let alive = true;
    const thread = currentThread(project);
    if (!thread) {
      setDispatchRead(emptyDispatchRead(project, 'ready'));
      return () => {
        alive = false;
      };
    }

    setDispatchRead((previous) =>
      previous.project === project
        ? { ...previous, phase: 'loading' }
        : emptyDispatchRead(project, 'loading')
    );

    getConversation(thread, 50)
      .then((payload) => {
        if (!alive) return;
        setDispatchRead({
          project,
          phase: 'ready',
          pulse: dispatchPulseFromConversation(payload.conversation, project)
        });
      })
      .catch(() => {
        if (!alive) return;
        setDispatchRead((previous) =>
          previous.project === project
            ? { ...previous, phase: 'error' }
            : emptyDispatchRead(project, 'error')
        );
      });

    return () => {
      alive = false;
    };
  }, [project, scoped.connected, scoped.inFlight, scoped.queued, scoped.latest?.id, scoped.latest?.name]);

  const dispatches = dispatchRead.project === project ? dispatchRead : emptyDispatchRead(project);

  return (
    <section className="focuscard workpulse" aria-label="Live-Arbeit" data-live-project={scoped.project}>
      <span className="focuscard-eyebrow">Gerade jetzt</span>
      <b className="focuscard-name">{execution.text}</b>
      <span className="focuscard-path">
        Wächter: {watcherWord(scoped.watcher)}
        {stale ? ' · letzter beobachteter Stand' : scoped.connected === null ? ' · Live-Evidenz ausstehend' : ''}
      </span>
      {guidance && (
        <span className="focuscard-counts" aria-label="Empfohlene Wächter-Aktion">
          {guidance.message}
          {guidance.command ? (
            <>
              {' · '}
              <code>{guidance.command}</code>
            </>
          ) : null}
        </span>
      )}

      <span className="focuscard-counts">
        {attentionComplete
          ? attention > 0
            ? `${attention} braucht Aufmerksamkeit${scoped.unread ? ` · ${scoped.unread} ungelesen` : ''}${scoped.quarantined ? ` · ${scoped.quarantined} Quarantäne` : ''}`
            : 'Nichts als ungelesen oder quarantiniert gemeldet'
          : attentionKnown
            ? `Aufmerksamkeitsstatus unvollständig${scoped.unread !== undefined ? ` · ${scoped.unread} ungelesen` : ' · ungelesen unbekannt'}${scoped.quarantined !== undefined ? ` · ${scoped.quarantined} Quarantäne` : ' · Quarantäne unbekannt'}`
            : 'Aufmerksamkeitszähler noch nicht gemeldet'}
        {attentionKnown && stale ? ' · beim letzten Verbinden gezählt' : ''}
      </span>

      <div aria-label="Offene Aufträge">
        <div className="focuscard-counts">{dispatchStatus(dispatches)}</div>
        {dispatches.pulse.items.map((item) => {
          const started = timeLabel(item.startedAt);
          const description = item.description ? briefText(item.description) : '';
          const executionEvidence = boundExecutionLine(item);
          return (
            <div key={item.ref}>
              <div className="focuscard-counts">
                {description
                  ? `${item.descriptionSource === 'turn' ? 'Auslöser' : 'Auftrag'}: ${description}`
                  : `Auftrag · ${item.kind}`}
                {item.lane ? ` · Lane ${item.lane}` : ''}
                {` · ${dispatchEvidenceLabel(item.descriptionSource)}`}
                {' · auf Bericht wartend'}
                {started ? ` · seit ${started}` : ''}
                {' · '}
                <code title={item.ref}>{shortRef(item.ref)}</code>
              </div>
              {executionEvidence && (
                <div className="focuscard-counts" aria-label="Gebundene Ausführungsevidenz">
                  {executionEvidence}
                </div>
              )}
            </div>
          );
        })}
        {dispatches.pulse.total > dispatches.pulse.items.length && (
          <div className="focuscard-counts">
            +{dispatches.pulse.total - dispatches.pulse.items.length} weitere im kanonischen Verlauf
          </div>
        )}
      </div>

      {scoped.recent.length > 0 ? (
        <div aria-label="Letzte Berichte">
          {scoped.recent.map((report, index) => (
            <div className="focuscard-counts" key={report.id || `${report.name}:${report.createdAt || index}`}>
              {index === 0 ? 'Zuletzt berichtet: ' : 'Davor: '}
              {reportLine(report)}
              {report.summary ? ` · ${report.summary}` : ''}
            </div>
          ))}
        </div>
      ) : (
        <span className="focuscard-counts">Noch kein Abschlussbericht beobachtet</span>
      )}
    </section>
  );
}
