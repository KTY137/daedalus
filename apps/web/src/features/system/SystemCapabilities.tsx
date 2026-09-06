import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction
} from 'react';
import { ApiError } from '@/shared/api';
import type { AgentProfile, ControlPlanePayload } from '@/shared/contracts';
import type { CapabilityResult, SystemCapabilitiesSnapshot } from './contracts';
import {
  loadSystemCapabilities,
  systemCapabilityPorts,
  UnconfirmedAutonomyWriteError,
  updateAgentAutonomy,
  type SystemCapabilityPorts
} from './api';
import { GATE_WORD, fallbackText, gateTone, safetyGates, staleText } from './safety';
import { watcherReading, watcherWhere } from './watchers';
import { readCapabilities, unclassifiedNote, type CapabilityEntry } from './capabilities';
import './system-capabilities.css';

export interface SystemCapabilitiesProps {
  project: string;
  enabled: boolean;
  ports?: SystemCapabilityPorts;
}

function errorText(result: CapabilityResult<unknown>): string | undefined {
  return result.status === 'error' ? `${result.error.kind}: ${result.error.message}` : undefined;
}

function writeOutcomeUncertain(error: unknown): boolean {
  return (
    error instanceof UnconfirmedAutonomyWriteError
    || (
      error instanceof ApiError && (
        error.kind === 'network'
        || error.kind === 'timeout'
        || (error.kind === 'http' && error.status >= 500)
      )
    )
  );
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
  const override = policy && typeof policy.agent_override === 'string' ? policy.agent_override : '';
  const projectDefault = policy && typeof policy.project_default === 'string' ? policy.project_default : '';
  const mode = override || projectDefault;
  return ['manual', 'semi_auto', 'autonomous'].includes(mode) ? mode : 'manual';
}

function ControlPlaneCard({
  project,
  result,
  onUpdated,
  saving,
  refreshing,
  deferredSaveError,
  onSaveStarted,
  onSaveFinished,
  onClearDeferredSaveError,
  ports,
  registry,
  draftModes,
  setDraftModes
}: {
  project: string;
  result: CapabilityResult<ControlPlanePayload>;
  onUpdated: (value: ControlPlanePayload) => void;
  saving: boolean;
  refreshing: boolean;
  deferredSaveError: string;
  onSaveStarted: (project: string) => boolean;
  onSaveFinished: (project: string, refresh: boolean, deferredError?: string) => Promise<void>;
  onClearDeferredSaveError: (project: string) => void;
  ports: SystemCapabilityPorts;
  /** `hierarchy.capabilities` — byte-identical to /api/capabilities, and
   *  already in hand, so reading it costs no extra request. */
  registry: CapabilityEntry[] | undefined;
  draftModes: Record<string, Record<string, string>>;
  setDraftModes: Dispatch<SetStateAction<Record<string, Record<string, string>>>>;
}) {
  const profiles = result.status === 'ready' ? result.data.profiles || [] : [];
  const [selected, setSelected] = useState('');
  const [saveError, setSaveError] = useState('');
  const [saveNotice, setSaveNotice] = useState('');
  const saveRequest = useRef(0);
  const activeSaveRequest = useRef(0);
  const mounted = useRef(false);
  const projectRef = useRef(project);
  const activeName = profiles.some((row) => row.name === selected) ? selected : profiles[0]?.name || '';
  const profile = profiles.find((row) => row.name === activeName);
  const baselineMode = profile ? profileMode(profile) : '';
  const draftMode = profile ? draftModes[project]?.[profile.name] ?? baselineMode : '';
  const modeDirty = Boolean(profile && draftMode !== baselineMode);

  useLayoutEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useLayoutEffect(() => {
    projectRef.current = project;
    saveRequest.current += 1;
    return () => { saveRequest.current += 1; };
  }, [project, result]);

  useEffect(() => {
    // A failed read is not evidence that profiles were deleted. Keep every
    // local draft until a ready control-plane snapshot can reconcile it.
    if (result.status !== 'ready') return;
    setSaveError('');
    setDraftModes((current) => {
      const currentProjectDrafts = current[project];
      if (!currentProjectDrafts) return current;
      const nextProjectDrafts = { ...currentProjectDrafts };
      let changed = false;
      for (const [name, mode] of Object.entries(currentProjectDrafts)) {
        const currentProfile = profiles.find((row) => row.name === name);
        if (!currentProfile || profileMode(currentProfile) === mode) {
          delete nextProjectDrafts[name];
          changed = true;
        }
      }
      if (!changed) return current;
      const next = { ...current };
      if (Object.keys(nextProjectDrafts).length > 0) next[project] = nextProjectDrafts;
      else delete next[project];
      return next;
    });
  }, [profiles, project, result.status]);

  const applyMode = useCallback(async () => {
    if (
      !profile
      || result.status !== 'ready'
      || !modeDirty
      || saving
      || refreshing
      || activeSaveRequest.current !== 0
    ) return;
    const requestedProject = project;
    const requestedProfile = profile.name;
    const requestedMode = draftMode;
    if (!onSaveStarted(requestedProject)) return;
    const request = ++saveRequest.current;
    activeSaveRequest.current = request;
    let reloadAfterSettle = false;
    let deferredError = '';
    setSaveError('');
    setSaveNotice('');
    try {
      const updated = await updateAgentAutonomy(
        requestedProject,
        requestedProfile,
        requestedMode,
        ports
      );
      if (request !== saveRequest.current || projectRef.current !== requestedProject) {
        reloadAfterSettle = true;
        return;
      }
      setDraftModes((current) => {
        const nextProjectDrafts = { ...(current[requestedProject] || {}) };
        delete nextProjectDrafts[requestedProfile];
        const next = { ...current };
        if (Object.keys(nextProjectDrafts).length > 0) next[requestedProject] = nextProjectDrafts;
        else delete next[requestedProject];
        return next;
      });
      onUpdated(updated);
      setSaveNotice('Projekt-Autonomie gespeichert.');
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      const superseded = request !== saveRequest.current || projectRef.current !== requestedProject;
      const outcomeUncertain = writeOutcomeUncertain(error);
      if (superseded || outcomeUncertain) {
        deferredError = outcomeUncertain
          ? `Der Ausgang des Autonomie-Speicherns ist unklar; Erfolg und Ablehnung sind beide möglich. ${detail}`
          : `Autonomie nicht gespeichert: ${detail}`;
        reloadAfterSettle = true;
        return;
      }
      setSaveError(detail);
    } finally {
      if (activeSaveRequest.current !== request) return;
      try {
        // The PUT itself cannot be cancelled. The persistent parent retains
        // this project-scoped lock even if this card unmounts during A→B→A,
        // and owns the confirming reload for every superseded response.
        await onSaveFinished(requestedProject, reloadAfterSettle, deferredError || undefined);
        if (reloadAfterSettle && mounted.current && projectRef.current === requestedProject) {
          setSaveNotice('Kanonischer Serverstand nach dem Speicherversuch erneut gelesen.');
        }
      } finally {
        if (activeSaveRequest.current === request) {
          activeSaveRequest.current = 0;
        }
      }
    }
  }, [draftMode, modeDirty, onSaveFinished, onSaveStarted, onUpdated, ports, profile, project, refreshing, result, saving]);

  const discardMode = useCallback(() => {
    if (!profile) return;
    setDraftModes((current) => {
      const nextProjectDrafts = { ...(current[project] || {}) };
      delete nextProjectDrafts[profile.name];
      const next = { ...current };
      if (Object.keys(nextProjectDrafts).length > 0) next[project] = nextProjectDrafts;
      else delete next[project];
      return next;
    });
    setSaveError('');
    onClearDeferredSaveError(project);
    setSaveNotice('Nicht gespeicherte Projekt-Autonomie verworfen.');
  }, [onClearDeferredSaveError, profile, project]);

  return (
    <CapabilityCard title="Control Plane & Agenten" result={result}>
      {result.status === 'ready' && (
        <>
          <p>{profiles.length} Profile · {result.data.capability_gates?.length || 0} Capability Gates</p>
          {profile ? (
            <div className="system-agent">
              <label>
                <span>Agentenprofil</span>
                <select
                  value={profile.name}
                  onChange={(event) => {
                    setSelected(event.target.value);
                    setSaveError('');
                    onClearDeferredSaveError(project);
                    setSaveNotice('');
                  }}
                  disabled={saving || refreshing}
                >
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
                  value={draftMode}
                  onChange={(event) => {
                    const mode = event.target.value;
                    setDraftModes((current) => {
                      const nextProjectDrafts = { ...(current[project] || {}) };
                      if (mode === baselineMode) delete nextProjectDrafts[profile.name];
                      else nextProjectDrafts[profile.name] = mode;
                      const next = { ...current };
                      if (Object.keys(nextProjectDrafts).length > 0) next[project] = nextProjectDrafts;
                      else delete next[project];
                      return next;
                    });
                    setSaveError('');
                    onClearDeferredSaveError(project);
                    setSaveNotice('');
                  }}
                  disabled={saving || refreshing}
                >
                  <option value="manual">manual</option>
                  <option value="semi_auto">semi_auto</option>
                  <option value="autonomous">autonomous</option>
                </select>
              </label>
              <div className="system-agent-actions">
                <span className="system-small" role="status" aria-live="polite">
                  {saving
                    ? 'Projekt-Autonomie wird gespeichert …'
                    : refreshing
                      ? 'Projekt-Autonomie wird neu gelesen …'
                    : saveNotice || (modeDirty ? 'Projekt-Autonomie ist noch nicht gespeichert.' : '')}
                </span>
                <div className="settings-action-buttons">
                  <button type="button" className="settings-refresh" onClick={discardMode} disabled={!modeDirty || saving || refreshing}>
                    Verwerfen
                  </button>
                  <button type="button" className="settings-primary" onClick={() => void applyMode()} disabled={!modeDirty || saving || refreshing}>
                    Projekt-Autonomie übernehmen
                  </button>
                </div>
              </div>
              {/* WHAT THIS AGENT MAY DO, and whether anyone classified it.
                  The grants used to print as a flat comma list in which every
                  entry looked alike. Measured here: five of the seven granted
                  across 24 profiles carry no declared risk class at all, and
                  they include `bash` and `file_write`. Nothing below invents a
                  class for them — unassessed is drawn as unassessed. */}
              {profile.capabilities.length === 0 ? (
                <p className="system-small">Berechtigungen: keine gemeldet</p>
              ) : (
                <>
                  <ul className="cap-grants">
                    {readCapabilities(profile.capabilities, registry).map((cap) => (
                      <li key={cap.id} className={cap.tone} title={cap.description || undefined}>
                        <code>{cap.id}</code>
                        <span className={`cap-risk ${cap.tone}`}>{cap.text}</span>
                        {cap.requiresSecret && <span className="cap-secret">braucht ein Geheimnis</span>}
                      </li>
                    ))}
                  </ul>
                  {unclassifiedNote(readCapabilities(profile.capabilities, registry)) && (
                    <p className="system-small warn">
                      {unclassifiedNote(readCapabilities(profile.capabilities, registry))}
                    </p>
                  )}
                </>
              )}
              {saveError && (
                <p className="system-error" role="alert">
                  Autonomie nicht gespeichert: {saveError}
                </p>
              )}
              {!saveError && deferredSaveError && (
                <p className="system-error" role="alert">
                  {deferredSaveError}
                </p>
              )}
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
  const [autonomySavingProjects, setAutonomySavingProjects] = useState<ReadonlySet<string>>(() => new Set());
  const [autonomySaveErrors, setAutonomySaveErrors] = useState<Record<string, string>>({});
  const [autonomyDraftModes, setAutonomyDraftModes] = useState<Record<string, Record<string, string>>>({});
  const serial = useRef(0);
  const projectRef = useRef(project);
  const autonomySavingRef = useRef<ReadonlySet<string>>(new Set());

  useLayoutEffect(() => {
    projectRef.current = project;
  }, [project]);

  const reloadProject = useCallback(async (requestedProject: string, allowDuringSave = false) => {
    if (!requestedProject || (!allowDuringSave && autonomySavingRef.current.has(requestedProject))) return;
    const mine = ++serial.current;
    setLoading(true);
    const next = await loadSystemCapabilities(requestedProject, ports);
    if (mine === serial.current) {
      setSnapshot(next);
      setLoading(false);
    }
  }, [ports]);

  const reload = useCallback(
    () => reloadProject(project),
    [project, reloadProject]
  );

  const startAutonomySave = useCallback((requestedProject: string): boolean => {
    if (autonomySavingRef.current.has(requestedProject)) return false;
    const next = new Set(autonomySavingRef.current);
    next.add(requestedProject);
    autonomySavingRef.current = next;
    setAutonomySavingProjects(next);
    setAutonomySaveErrors((current) => {
      if (!(requestedProject in current)) return current;
      const errors = { ...current };
      delete errors[requestedProject];
      return errors;
    });
    return true;
  }, []);

  const finishAutonomySave = useCallback(async (
    requestedProject: string,
    refresh: boolean,
    deferredError?: string
  ) => {
    try {
      if (deferredError) {
        setAutonomySaveErrors((current) => ({ ...current, [requestedProject]: deferredError }));
      }
      if (refresh && projectRef.current === requestedProject) {
        await reloadProject(requestedProject, true);
      }
    } finally {
      if (autonomySavingRef.current.has(requestedProject)) {
        const next = new Set(autonomySavingRef.current);
        next.delete(requestedProject);
        autonomySavingRef.current = next;
        setAutonomySavingProjects(next);
      }
    }
  }, [reloadProject]);

  const clearAutonomySaveError = useCallback((requestedProject: string) => {
    setAutonomySaveErrors((current) => {
      if (!(requestedProject in current)) return current;
      const next = { ...current };
      delete next[requestedProject];
      return next;
    });
  }, []);

  useEffect(() => {
    if (!enabled || !project) {
      serial.current += 1;
      setLoading(false);
      return;
    }
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
    // A confirmed PUT is newer than every full reload that was already in
    // flight. Invalidate those GETs before publishing the mutation response;
    // otherwise a slow pre-PUT read can overwrite this canonical snapshot.
    serial.current += 1;
    setLoading(false);
    setSnapshot((current) => current ? {
      ...current,
      controlPlane: { status: 'ready', data: value, loadedAt: Date.now() }
    } : current);
  }, []);

  const autonomySaving = autonomySavingProjects.has(project);

  return (
    <section className="settings-section system-capabilities" aria-labelledby="system-capabilities-title">
      <div className="settings-title" id="system-capabilities-title">
        System & Orchestrierung
        <button type="button" className="settings-refresh" onClick={() => void reload()} disabled={!project || loading || autonomySaving}>
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
      {autonomySaving && snapshot?.project !== project && (
        <p className="settings-hint" role="status">Projekt-Autonomie wird gespeichert; danach wird der Projektstand neu gelesen.</p>
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
            saving={autonomySaving}
            refreshing={loading}
            deferredSaveError={autonomySaveErrors[project] || ''}
            onSaveStarted={startAutonomySave}
            onSaveFinished={finishAutonomySave}
            onClearDeferredSaveError={clearAutonomySaveError}
            ports={ports}
            draftModes={autonomyDraftModes}
            setDraftModes={setAutonomyDraftModes}
            registry={
              snapshot.hierarchy.status === 'ready'
                ? snapshot.hierarchy.data.capabilities
                : undefined
            }
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
