import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import type { AgentProfile, ControlPlanePayload } from '@/shared/contracts';
import type { CapabilityResult, SystemCapabilitiesSnapshot } from './contracts';
import {
  loadSystemCapabilities,
  systemCapabilityPorts,
  updateAgentAutonomy,
  type SystemCapabilityPorts
} from './api';
import { GATE_WORD, fallbackText, gateTone, safetyGates, staleText } from './safety';
import { watcherReading, watcherWhere } from './watchers';
import './system-capabilities.css';

export interface SystemCapabilitiesProps {
  project: string;
  enabled: boolean;
  ports?: SystemCapabilityPorts;
}

function errorText(result: CapabilityResult<unknown>): string | undefined {
  return result.status === 'error' ? `${result.error.kind}: ${result.error.message}` : undefined;
}

function RawContract({ label, value }: { label: string; value: unknown }) {
  const [open, setOpen] = useState(false);
  return (
    <details className="system-raw" onToggle={(event) => setOpen(event.currentTarget.open)}>
      <summary>{label}: vollständiger Antwortvertrag</summary>
      {open ? <pre>{JSON.stringify(value, null, 2)}</pre> : null}
    </details>
  );
}

function CapabilityCard({
  title,
  result,
  children
}: {
  title: string;
  result: CapabilityResult<unknown>;
  children?: ReactNode;
}) {
  const failure = errorText(result);
  return (
    <article className={`system-card ${failure ? 'failed' : ''}`} data-source-state={result.status}>
      <h3>{title}</h3>
      {failure ? (
        <p className="system-error" role="status">
          Quelle nicht lesbar — das ist kein leerer Datensatz. {failure}
        </p>
      ) : children}
    </article>
  );
}

function profileMode(profile: AgentProfile): string {
  const policy = profile.autonomy.read_files;
  const mode = policy && typeof policy.project_default === 'string' ? policy.project_default : '';
  return mode || 'manual';
}

function ControlPlaneCard({
  project,
  result,
  onUpdated,
  ports
}: {
  project: string;
  result: CapabilityResult<ControlPlanePayload>;
  onUpdated: (value: ControlPlanePayload) => void;
  ports: SystemCapabilityPorts;
}) {
  const profiles = result.status === 'ready' ? result.data.profiles || [] : [];
  const [selected, setSelected] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState('');
  const activeName = profiles.some((row) => row.name === selected) ? selected : profiles[0]?.name || '';
  const profile = profiles.find((row) => row.name === activeName);

  const setMode = useCallback(async (mode: string) => {
    if (!profile || result.status !== 'ready') return;
    setSaving(true);
    setSaveError('');
    try {
      onUpdated(await updateAgentAutonomy(project, result.data, profile.name, mode, ports));
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }, [onUpdated, ports, profile, project, result]);

  return (
    <CapabilityCard title="Control Plane & Agenten" result={result}>
      {result.status === 'ready' && (
        <>
          <p>{profiles.length} Profile · {result.data.capability_gates?.length || 0} Capability Gates</p>
          {profile ? (
            <div className="system-agent">
              <label>
                <span>Agentenprofil</span>
                <select value={profile.name} onChange={(event) => setSelected(event.target.value)}>
                  {profiles.map((row) => <option key={row.name} value={row.name}>{row.display_name} · {row.name}</option>)}
                </select>
              </label>
              <dl>
                <div><dt>Status</dt><dd>{profile.sync_status} · {profile.active ? 'aktiv' : 'inaktiv'}</dd></div>
                <div><dt>Kategorie</dt><dd>{profile.category_label || profile.category || 'nicht gemeldet'}</dd></div>
                <div><dt>Squads</dt><dd>{profile.squads.join(', ') || 'keine'}</dd></div>
                <div><dt>Ownership</dt><dd>{profile.ownership.join(', ') || 'keine'}</dd></div>
              </dl>
              <label>
                <span>Projekt-Autonomie</span>
                <select
                  aria-label={`Projekt-Autonomie für ${profile.display_name}`}
                  value={profileMode(profile)}
                  onChange={(event) => void setMode(event.target.value)}
                  disabled={saving}
                >
                  <option value="manual">manual</option>
                  <option value="semi_auto">semi_auto</option>
                  <option value="autonomous">autonomous</option>
                </select>
              </label>
              <p className="system-small">Capabilities: {profile.capabilities.join(', ') || 'keine gemeldet'}</p>
              {saveError && <p className="system-error" role="status">Autonomie nicht gespeichert: {saveError}</p>}
            </div>
          ) : <p>Keine Agentenprofile gemeldet.</p>}
          <RawContract label="Control Plane" value={result.data} />
        </>
      )}
    </CapabilityCard>
  );
}

export function SystemCapabilities({
  project,
  enabled,
  ports = systemCapabilityPorts
}: SystemCapabilitiesProps) {
  const [snapshot, setSnapshot] = useState<SystemCapabilitiesSnapshot>();
  const [loading, setLoading] = useState(false);
  const serial = useRef(0);

  const reload = useCallback(async () => {
    if (!project) return;
    const mine = ++serial.current;
    setLoading(true);
    const next = await loadSystemCapabilities(project, ports);
    if (mine === serial.current) {
      setSnapshot(next);
      setLoading(false);
    }
  }, [ports, project]);

  useEffect(() => {
    if (!enabled || !project) return;
    void reload();
    return () => { serial.current += 1; };
  }, [enabled, project, reload]);

  const failureCount = snapshot
    ? Object.entries(snapshot)
      .filter(([key]) => key !== 'project')
      .filter(([, value]) => (value as CapabilityResult<unknown>).status === 'error')
      .length
    : 0;

  const updateControlPlane = useCallback((value: ControlPlanePayload) => {
    setSnapshot((current) => current ? {
      ...current,
      controlPlane: { status: 'ready', data: value, loadedAt: Date.now() }
    } : current);
  }, []);

  return (
    <section className="settings-section system-capabilities" aria-labelledby="system-capabilities-title">
      <div className="settings-title" id="system-capabilities-title">
        System & Orchestrierung
        <button type="button" className="settings-refresh" onClick={() => void reload()} disabled={!project || loading}>
          {loading ? 'Lädt …' : 'Neu lesen'}
        </button>
      </div>
      <p className="settings-hint">
        Bestehende Dashboard-, Control-Plane-, Claude-, Provider- und Loop-Verträge für das registrierte Projekt.
        Diese Ansicht besitzt keine eigene Ausführungsautorität.
      </p>
      {!project && <p className="settings-hint bad">Kein registriertes Projekt ausgewählt.</p>}
      {loading && !snapshot && <p className="settings-hint" role="status">Acht Quellen werden unabhängig gelesen …</p>}
      {snapshot && snapshot.project !== project && (
        <p className="settings-hint" role="status">Projektwechsel: alter Stand wird nicht als neuer Stand ausgegeben.</p>
      )}
      {snapshot && snapshot.project === project && (
        <div className="system-grid" data-testid="system-capabilities">
          {failureCount > 0 && (
            <p className="system-failure-summary" role="status">
              {failureCount} {failureCount === 1 ? 'Quelle war' : 'Quellen waren'} nicht lesbar; erfolgreiche Antworten bleiben separat sichtbar.
            </p>
          )}

          <CapabilityCard title="Dashboard & Governance" result={snapshot.dashboard}>
            {snapshot.dashboard.status === 'ready' && (
              <>
                <p>
                  Projekt {snapshot.dashboard.data.selected_project || snapshot.dashboard.data.project || project}
                  {' · '}Verdikt {snapshot.dashboard.data.governance?.verdict || 'nicht gemeldet'}
                </p>
                {/* THE SAFETY GATES. core.py runs both probes and calls
                    either failure SAFETY; this card had the answers in hand
                    and showed a JSON blob, so a failed gate was visible only
                    to someone who expanded it and knew the key. */}
                <ul className="safety-gates">
                  {safetyGates(snapshot.dashboard.data.quality).map((gate) => (
                    <li key={gate.question} className={gateTone(gate.reading)}>
                      <span className="safety-question">{gate.question}</span>
                      <span className={`safety-verdict ${gateTone(gate.reading)}`}>
                        {GATE_WORD[gate.reading]}
                      </span>
                      {gate.reading !== 'verified' && (
                        <span className="safety-consequence">{gate.consequence}</span>
                      )}
                    </li>
                  ))}
                </ul>
                <p className="system-small">
                  Hängengebliebene Watcher:{' '}
                  <span className={staleText(snapshot.dashboard.data.quality).tone}>
                    {staleText(snapshot.dashboard.data.quality).text}
                  </span>
                  {fallbackText(snapshot.dashboard.data.quality) && (
                    <> · Fallback-Rate {fallbackText(snapshot.dashboard.data.quality)}</>
                  )}
                  {snapshot.dashboard.data.quality?.fallback_alarm && (
                    <span className="bad"> · Fallback-Alarm aktiv</span>
                  )}
                </p>
                {/* WHO IS ACTUALLY CONSUMING THE QUEUE. core.py finds
                    watchers by matching process command lines, so `running`
                    means "a matching process exists", not "your outbox has an
                    owner". The caveat travels with the count -- and more than
                    one match is stated rather than hidden behind a single
                    word. See ./watchers.ts. */}
                <p className="system-small watcher-head">
                  Watcher:{' '}
                  <span className={watcherReading(snapshot.dashboard.data.watcher).tone}>
                    {watcherReading(snapshot.dashboard.data.watcher).text}
                  </span>
                </p>
                {(snapshot.dashboard.data.watcher?.watchers || []).length > 0 && (
                  <ul className="watcher-list">
                    {(snapshot.dashboard.data.watcher?.watchers || []).map((w) => (
                      <li key={w.pid} className={w.stale ? 'bad' : ''}>
                        <code>pid {w.pid}</code>
                        <span>{watcherWhere(w.command)}</span>
                        {w.stale && <span className="bad">hängengeblieben</span>}
                      </li>
                    ))}
                  </ul>
                )}
                <p className="system-small watcher-basis">
                  {watcherReading(snapshot.dashboard.data.watcher).basis}
                </p>
                {/* core.py writes this only when a watcher is stale, so it is
                    rendered only when it says something. */}
                {snapshot.dashboard.data.quality?.recommendation && (
                  <p className="system-error" role="status">
                    {snapshot.dashboard.data.quality.recommendation}
                  </p>
                )}
                <RawContract label="Dashboard" value={snapshot.dashboard.data} />
              </>
            )}
          </CapabilityCard>

          <ControlPlaneCard
            project={project}
            result={snapshot.controlPlane}
            onUpdated={updateControlPlane}
            ports={ports}
          />

          <CapabilityCard title="Claude Session Bootstrap" result={snapshot.claudeBootstrap}>
            {snapshot.claudeBootstrap.status === 'ready' && (
              <pre className="system-prompt">{snapshot.claudeBootstrap.data.prompt || 'Kein Bootstrap-Prompt gemeldet.'}</pre>
            )}
          </CapabilityCard>

          <CapabilityCard title="Provider-Status" result={snapshot.providerStatus}>
            {snapshot.providerStatus.status === 'ready' && (
              <>
                <ul className="system-providers">
                  {(snapshot.providerStatus.data.providers || []).map((row) => (
                    <li key={row.name}>
                      <b>{row.display_name || row.name}</b>
                      <span>konfiguriert: {row.configured ? 'ja' : 'nein'}</span>
                      <span>erreichbar: {row.available ? 'ja' : 'nein'}</span>
                      {row.last_error && <small>{row.last_error}</small>}
                    </li>
                  ))}
                </ul>
                {(snapshot.providerStatus.data.providers || []).length === 0 && <p>Keine Provider-Zeilen gemeldet.</p>}
                <RawContract label="Provider-Status" value={snapshot.providerStatus.data} />
              </>
            )}
          </CapabilityCard>

          <CapabilityCard title="Agenten-Hierarchie" result={snapshot.hierarchy}>
            {snapshot.hierarchy.status === 'ready' && (
              <>
                <p>{snapshot.hierarchy.data.nodes.length} Knoten · {snapshot.hierarchy.data.edges.length} Kanten</p>
                <RawContract label="Hierarchie" value={snapshot.hierarchy.data} />
              </>
            )}
          </CapabilityCard>

          <CapabilityCard title="Loop Queue" result={snapshot.loopQueue}>
            {snapshot.loopQueue.status === 'ready' && (
              <>
                <p>
                  {snapshot.loopQueue.data.queue.n_candidates} Kandidaten
                  {snapshot.loopQueue.data.queue.incomplete ? ' · unvollständig' : ' · vollständig gelesen'}
                </p>
                {snapshot.loopQueue.data.queue.degraded_sources.length > 0 && (
                  <p className="system-error">Nicht gelesen: {snapshot.loopQueue.data.queue.degraded_sources.join(', ')}</p>
                )}
                <RawContract label="Loop Queue" value={snapshot.loopQueue.data} />
              </>
            )}
          </CapabilityCard>

          <CapabilityCard title="Loop Attempts" result={snapshot.loopAttempts}>
            {snapshot.loopAttempts.status === 'ready' && (
              <>
                <p>{snapshot.loopAttempts.data.attempts.intents.length} Attempts · Ledger {snapshot.loopAttempts.data.attempts.ledger.read_only ? 'read-only' : 'nicht read-only gemeldet'}</p>
                <RawContract label="Loop Attempts" value={snapshot.loopAttempts.data} />
              </>
            )}
          </CapabilityCard>

          <CapabilityCard title="Loop-Architektur" result={snapshot.loopArchitecture}>
            {snapshot.loopArchitecture.status === 'ready' && (
              <>
                <p>
                  Digest {snapshot.loopArchitecture.data.architecture.digest || 'nicht gemeldet'}
                  {' · '}{snapshot.loopArchitecture.data.architecture.trusted ? 'trusted' : snapshot.loopArchitecture.data.architecture.trust_reason || 'nicht trusted'}
                </p>
                <RawContract label="Loop-Architektur" value={snapshot.loopArchitecture.data} />
              </>
            )}
          </CapabilityCard>
        </div>
      )}
    </section>
  );
}
