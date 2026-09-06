import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { ApiError, getHierarchy, updateTeam } from '@/shared/api';
import type { HierarchyPayload, TeamPayload } from '@/shared/contracts';
import {
  agentRowsFromPayload,
  ceilingFromPayload,
  draftFromPayload,
  lanesFromPayload,
  sameAgentSet,
  teamChanged,
  teamPatch,
  FALLBACK_CEILING,
  type AgentRow,
  type TeamDraft
} from './teamModel';

/**
 * The team editor: how many workers, which lane, which agents.
 *
 * These three values are not decoration. `daedalus/core.py` picks agents from
 * `active_agents`, `daedalus/build.py` sizes its waves from `max_workers`, and
 * `core.routing_summary` honours `default_lane`. They have been steering the
 * system all along and, since the inline VS Code dashboard was retired, no
 * surface could change them — the backend endpoint existed with no caller.
 *
 * The lane list and the worker ceiling come from the hierarchy payload, not
 * from constants here: `save_team` validates against `daedalus.core.
 * KNOWN_LANES`, and a frontend holding its own copy eventually offers a choice
 * the validator refuses.
 */

export interface TeamPorts {
  load: (project: string) => Promise<HierarchyPayload>;
  save: (project: string, patch: Record<string, unknown>) => Promise<TeamPayload>;
}

export const teamPorts: TeamPorts = { load: getHierarchy, save: updateTeam };

export interface TeamSettingsProps {
  project: string;
  enabled: boolean;
  ports?: TeamPorts;
}

interface DeferredSaveError {
  detail: string;
  outcomeUncertain: boolean;
}

interface PendingTeamReconcile {
  baseline: TeamDraft;
  submitted: TeamDraft;
}

class UnconfirmedTeamWriteError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'UnconfirmedTeamWriteError';
  }
}

function confirmedTeamSave(
  result: TeamPayload,
  requestedProject: string,
  baseline: TeamDraft,
  submitted: TeamDraft
): { baseline: TeamDraft; draft: TeamDraft; ignored: string[]; retained: string[] } {
  const raw = result as unknown as Record<string, unknown> | null;
  const team = raw && typeof raw.team === 'object' && raw.team !== null && !Array.isArray(raw.team)
    ? raw.team as Record<string, unknown>
    : undefined;
  const ignored = raw?.ignored_fields;
  if (
    !team
    || raw?.project !== requestedProject
    || !Number.isSafeInteger(team.max_workers)
    || Number(team.max_workers) < 1
    || typeof team.default_lane !== 'string'
    || !team.default_lane
    || !Array.isArray(team.active_agents)
    || team.active_agents.some((name) => typeof name !== 'string' || !name)
    || (ignored !== undefined && (
      !Array.isArray(ignored)
      || ignored.some((field) => typeof field !== 'string')
    ))
  ) {
    throw new UnconfirmedTeamWriteError(
      'Das Team-Backend bestätigte den gespeicherten Projektstand nicht vollständig.'
    );
  }
  const confirmed: TeamDraft = {
    maxWorkers: team.max_workers as number,
    lane: team.default_lane,
    agents: [...team.active_agents] as string[]
  };
  const ignoredFields = (ignored || []) as string[];
  const confirmedOrIgnored = (
    changed: boolean,
    matches: boolean,
    field: string
  ) => !changed || matches || ignoredFields.includes(field);
  if (
    !confirmedOrIgnored(
      submitted.maxWorkers !== baseline.maxWorkers,
      confirmed.maxWorkers === submitted.maxWorkers,
      'max_workers'
    )
    || !confirmedOrIgnored(
      submitted.lane !== baseline.lane,
      confirmed.lane === submitted.lane,
      'default_lane'
    )
    || !confirmedOrIgnored(
      !sameAgentSet(submitted.agents, baseline.agents),
      sameAgentSet(confirmed.agents, submitted.agents),
      'active_agents'
    )
  ) {
    throw new UnconfirmedTeamWriteError(
      'Das Team-Backend bestätigte die angeforderten Änderungen nicht.'
    );
  }
  const retained: string[] = [];
  if (
    submitted.maxWorkers !== baseline.maxWorkers
    && ignoredFields.includes('max_workers')
  ) retained.push('max_workers');
  if (
    submitted.lane !== baseline.lane
    && ignoredFields.includes('default_lane')
  ) retained.push('default_lane');
  if (
    !sameAgentSet(submitted.agents, baseline.agents)
    && ignoredFields.includes('active_agents')
  ) retained.push('active_agents');

  return {
    baseline: confirmed,
    draft: {
      maxWorkers: retained.includes('max_workers') ? submitted.maxWorkers : confirmed.maxWorkers,
      lane: retained.includes('default_lane') ? submitted.lane : confirmed.lane,
      agents: retained.includes('active_agents')
        ? [...submitted.agents]
        : [...confirmed.agents]
    },
    ignored: ignoredFields,
    retained
  };
}

function canonicalTeamDraft(payload: HierarchyPayload, requestedProject: string): TeamDraft {
  const raw = payload as unknown as Record<string, unknown> | null;
  const nodes = raw?.nodes;
  const projectNodes = Array.isArray(nodes)
    ? nodes.filter((candidate) => {
        if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) return false;
        const node = candidate as Record<string, unknown>;
        return node.type === 'project';
      }) as Record<string, unknown>[]
    : [];
  const projectNode = projectNodes.length === 1 ? projectNodes[0] : undefined;
  const projectData = projectNode
    && typeof projectNode.data === 'object'
    && projectNode.data !== null
    && !Array.isArray(projectNode.data)
      ? projectNode.data as Record<string, unknown>
      : undefined;
  if (
    raw?.ok !== true
    || raw.project !== requestedProject
    || projectNode?.id !== `project:${requestedProject}`
    || !projectData
    || !Number.isSafeInteger(projectData.max_workers)
    || Number(projectData.max_workers) < 1
    || typeof projectData.default_lane !== 'string'
    || !projectData.default_lane
  ) {
    throw new Error(
      'Das Team-Backend lieferte keinen gültigen kanonischen Projektstand.'
    );
  }
  return draftFromPayload(payload);
}

function writeOutcomeUncertain(error: unknown): boolean {
  return (
    error instanceof UnconfirmedTeamWriteError
    || (
      error instanceof ApiError && (
        error.kind === 'network'
        || error.kind === 'timeout'
        || (error.kind === 'http' && error.status >= 500)
      )
    )
  );
}

function deferredSaveMessage(issue: DeferredSaveError): string {
  return issue.outcomeUncertain
    ? `Der Ausgang eines vorherigen Speicherversuchs ist unklar. Der kanonische Serverstand wurde danach neu gelesen. ${issue.detail}`
    : `Ein vorheriger Speicherversuch wurde abgelehnt: ${issue.detail}`;
}

function rebaseSubmittedTeamDraft(
  pending: PendingTeamReconcile,
  canonical: TeamDraft
): TeamDraft {
  return {
    maxWorkers: pending.submitted.maxWorkers !== pending.baseline.maxWorkers
      ? pending.submitted.maxWorkers
      : canonical.maxWorkers,
    lane: pending.submitted.lane !== pending.baseline.lane
      ? pending.submitted.lane
      : canonical.lane,
    agents: !sameAgentSet(pending.submitted.agents, pending.baseline.agents)
      ? [...pending.submitted.agents]
      : [...canonical.agents]
  };
}

export function TeamSettings({ project, enabled, ports = teamPorts }: TeamSettingsProps) {
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [lanes, setLanes] = useState<string[]>([]);
  const [ceiling, setCeiling] = useState(FALLBACK_CEILING);
  const [baseline, setBaseline] = useState<TeamDraft | undefined>();
  const [draft, setDraft] = useState<TeamDraft | undefined>();
  const [draftProject, setDraftProject] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const loadRequest = useRef(0);
  const saveRequest = useRef(0);
  const activeSaveRequest = useRef(0);
  const projectRef = useRef(project);
  const draftProjectRef = useRef(draftProject);
  const lastLoadProject = useRef('');
  const observedProject = useRef(project);
  const wasEnabled = useRef(false);
  const deferredSaveErrors = useRef<Record<string, DeferredSaveError>>({});
  const pendingReconciles = useRef<Record<string, PendingTeamReconcile>>({});

  useLayoutEffect(() => {
    if (projectRef.current !== project) {
      projectRef.current = project;
      loadRequest.current += 1;
      saveRequest.current += 1;
    }
    draftProjectRef.current = draftProject;
  }, [draftProject, project]);

  const load = useCallback(async () => {
    if (!project) return;
    const requestedProject = project;
    const request = ++loadRequest.current;
    lastLoadProject.current = requestedProject;
    if (draftProjectRef.current !== requestedProject) {
      setBaseline(undefined);
      setDraft(undefined);
      setDraftProject('');
    }
    setLoading(true);
    setError('');
    setNotice('');
    try {
      const payload = await ports.load(requestedProject);
      if (request !== loadRequest.current || projectRef.current !== requestedProject) return;
      const next = canonicalTeamDraft(payload, requestedProject);
      const pendingReconcile = pendingReconciles.current[requestedProject];
      const nextDraft = pendingReconcile
        ? rebaseSubmittedTeamDraft(pendingReconcile, next)
        : next;
      setAgents(agentRowsFromPayload(payload));
      setLanes(lanesFromPayload(payload, nextDraft.lane));
      setCeiling(ceilingFromPayload(payload));
      setBaseline(next);
      setDraft(nextDraft);
      setDraftProject(requestedProject);
      if (pendingReconcile) delete pendingReconciles.current[requestedProject];
      const deferredSaveError = deferredSaveErrors.current[requestedProject];
      if (deferredSaveError) {
        delete deferredSaveErrors.current[requestedProject];
        setError(deferredSaveMessage(deferredSaveError));
      }
    } catch (e) {
      if (request !== loadRequest.current || projectRef.current !== requestedProject) return;
      setBaseline(undefined);
      setDraft(undefined);
      setDraftProject('');
      const readError = e instanceof Error ? e.message : 'Die Team-Einstellungen konnten nicht gelesen werden.';
      const deferredSaveError = deferredSaveErrors.current[requestedProject];
      setError(
        deferredSaveError?.outcomeUncertain
          ? `Der Ausgang des Speicherversuchs ist unklar und der kanonische Serverstand konnte noch nicht bestätigt werden. ${deferredSaveError.detail} Lesen: ${readError}`
          : readError
      );
    } finally {
      if (request === loadRequest.current && projectRef.current === requestedProject) setLoading(false);
    }
  }, [project, ports]);

  const changed = Boolean(
    draft
    && baseline
    && draftProject === project
    && teamChanged(draft, baseline)
  );

  useEffect(() => {
    const opened = enabled && !wasEnabled.current;
    wasEnabled.current = enabled;
    const projectChanged = observedProject.current !== project;
    observedProject.current = project;
    if (projectChanged) {
      lastLoadProject.current = '';
      setBaseline(undefined);
      setDraft(undefined);
      setDraftProject('');
      setLoading(false);
      setError('');
      setNotice('');
    }
    if (!project) {
      lastLoadProject.current = '';
      setBaseline(undefined);
      setDraft(undefined);
      setDraftProject('');
      setLoading(false);
      setError('');
      setNotice('');
      return;
    }
    if (!enabled) return;
    const projectNeedsLoad = lastLoadProject.current !== project;
    if (projectNeedsLoad || (opened && !changed)) void load();
  }, [changed, enabled, load, project]);

  const maxWorkersValid = Boolean(
    draft
    && Number.isSafeInteger(draft.maxWorkers)
    && draft.maxWorkers >= 1
    && draft.maxWorkers <= ceiling
  );

  const save = useCallback(async () => {
    if (
      !draft
      || !baseline
      || draftProject !== project
      || !maxWorkersValid
      || !teamChanged(draft, baseline)
      || saving
      || activeSaveRequest.current !== 0
    ) return;
    const requestedProject = draftProject;
    const request = ++saveRequest.current;
    activeSaveRequest.current = request;
    let reloadAfterSettle = false;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const result = await ports.save(requestedProject, teamPatch(draft, baseline));
      if (request !== saveRequest.current || projectRef.current !== requestedProject) {
        reloadAfterSettle = projectRef.current === requestedProject;
        return;
      }
      const confirmed = confirmedTeamSave(
        result,
        requestedProject,
        baseline,
        draft
      );
      setBaseline(confirmed.baseline);
      setDraft(confirmed.draft);
      setDraftProject(requestedProject);
      const ignored = confirmed.ignored;
      setNotice(
        confirmed.retained.length
          ? `Nicht übernommen: ${confirmed.retained.join(', ')}. Der Entwurf bleibt zum erneuten Speichern erhalten.`
          : ignored.length
            ? `Gespeichert. Nicht übernommen: ${ignored.join(', ')}.`
            : 'Gespeichert.'
      );
    } catch (e) {
      const detail = e instanceof Error ? e.message : 'Speichern fehlgeschlagen.';
      const superseded = request !== saveRequest.current || projectRef.current !== requestedProject;
      const outcomeUncertain = writeOutcomeUncertain(e);
      if (superseded || outcomeUncertain) {
        deferredSaveErrors.current[requestedProject] = { detail, outcomeUncertain };
        if (outcomeUncertain) {
          pendingReconciles.current[requestedProject] = {
            baseline: { ...baseline, agents: [...baseline.agents] },
            submitted: { ...draft, agents: [...draft.agents] }
          };
        }
        reloadAfterSettle = true;
        return;
      }
      // save_team answers 400 with the field and the reason. Showing that
      // verbatim beats a generic failure line.
      setError(detail);
    } finally {
      if (activeSaveRequest.current === request) {
        try {
          // A project round-trip or an ambiguous transport failure can leave
          // the PUT effectful without a usable response. Keep the write lock
          // until a same-project canonical read has settled; otherwise the
          // user could discard or apply another draft against the old base.
          if (reloadAfterSettle && projectRef.current === requestedProject) await load();
        } finally {
          if (activeSaveRequest.current === request) {
            activeSaveRequest.current = 0;
            setSaving(false);
          }
        }
      }
    }
  }, [baseline, draft, draftProject, load, maxWorkersValid, ports, project, saving]);

  const discard = useCallback(() => {
    if (!baseline || draftProject !== project) return;
    setDraft({ ...baseline, agents: [...baseline.agents] });
    setError('');
    setNotice('Nicht gespeicherte Team-Änderungen verworfen.');
  }, [baseline, draftProject, project]);

  const toggleAgent = useCallback((name: string) => {
    setError('');
    setNotice('');
    setDraft((prev) =>
      prev
        ? {
            ...prev,
            agents: prev.agents.includes(name)
              ? prev.agents.filter((a) => a !== name)
              : [...prev.agents, name]
          }
        : prev
    );
  }, []);

  return (
    <section className="settings-section" aria-labelledby="team-settings-title">
      <div className="settings-title" id="team-settings-title">Team</div>
      <p className="settings-hint">
        Wie viele Worker parallel laufen, welche Lane voreingestellt ist und welche Agents
        überhaupt Arbeit bekommen. Diese Werte steuern Routing und Wellengröße bereits —
        hier sind sie zum ersten Mal wieder änderbar.
      </p>

      {enabled && !project && (
        <p className="settings-hint" role="status">Kein Projekt ausgewählt.</p>
      )}

      {loading && !draft && <p className="settings-hint" role="status">Team wird gelesen …</p>}

      {project && !loading && !draft && (
        <div className="cap-load-state">
          <p className="settings-hint bad" role="alert">
            {error || 'Die Team-Einstellungen sind nicht verfügbar.'}
          </p>
          <button type="button" className="settings-refresh" onClick={() => void load()}>
            Erneut laden
          </button>
        </div>
      )}

      {draft && draftProject === project && (
        <fieldset className="team-card" disabled={loading || saving} aria-busy={loading || saving}>
          <label className="team-field">
            <span>Max. Worker</span>
            <input
              type="number"
              min={1}
              max={ceiling}
              value={draft.maxWorkers}
              aria-invalid={!maxWorkersValid}
              aria-describedby={maxWorkersValid ? 'team-workers-hint' : 'team-workers-hint team-workers-error'}
              onChange={(event) => {
                setError('');
                setNotice('');
                setDraft({ ...draft, maxWorkers: Number(event.currentTarget.value) });
              }}
            />
          </label>
          <p className="settings-hint" id="team-workers-hint">1 bis {ceiling}.</p>
          {!maxWorkersValid && (
            <p className="settings-hint bad" id="team-workers-error" role="alert">
              Max. Worker muss eine ganze Zahl zwischen 1 und {ceiling} sein.
            </p>
          )}

          <label className="team-field">
            <span>Default-Lane</span>
            <select
              value={draft.lane}
              onChange={(event) => {
                setError('');
                setNotice('');
                setDraft({ ...draft, lane: event.currentTarget.value });
              }}
            >
              {lanes.map((lane) => (
                <option key={lane} value={lane}>{lane}</option>
              ))}
            </select>
          </label>

          <div className="team-agents" role="group" aria-label="Aktive Agents">
            {agents.length === 0 && (
              <p className="settings-hint">Für dieses Projekt sind keine Agents registriert.</p>
            )}
            {agents.map((agent) => {
              const on = draft.agents.includes(agent.name);
              return (
                <button
                  key={agent.name}
                  type="button"
                  className={on ? 'on' : ''}
                  aria-pressed={on}
                  data-agent={agent.name}
                  onClick={() => toggleAgent(agent.name)}
                >
                  {agent.label}
                </button>
              );
            })}
          </div>
          <p className="settings-hint">
            {draft.agents.length === 0
              ? 'Keine Auswahl bedeutet: alle registrierten Agents sind wählbar.'
              : `${draft.agents.length} von ${agents.length} aktiv.`}
          </p>

          <div className="team-actions">
            <button
              type="button"
              className="settings-refresh"
              disabled={!changed || saving}
              onClick={discard}
            >
              Verwerfen
            </button>
            <button
              type="button"
              className="settings-refresh"
              disabled={!changed || !maxWorkersValid || saving}
              onClick={() => void save()}
            >
              {saving ? 'Wird gespeichert …' : 'Team speichern'}
            </button>
            {changed && !saving && <span className="settings-hint">Ungespeicherte Änderung.</span>}
          </div>

          {error && <p className="settings-hint bad" role="alert">{error}</p>}
          {notice && <p className="settings-hint" role="status">{notice}</p>}
        </fieldset>
      )}
    </section>
  );
}
