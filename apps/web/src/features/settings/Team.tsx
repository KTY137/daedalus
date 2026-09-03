import { useCallback, useEffect, useState } from 'react';
import { getHierarchy, updateTeam } from '@/shared/api';
import type { HierarchyPayload, TeamPayload } from '@/shared/contracts';
import {
  agentRowsFromPayload,
  ceilingFromPayload,
  draftFromPayload,
  lanesFromPayload,
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

export function TeamSettings({ project, enabled, ports = teamPorts }: TeamSettingsProps) {
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [lanes, setLanes] = useState<string[]>([]);
  const [ceiling, setCeiling] = useState(FALLBACK_CEILING);
  const [baseline, setBaseline] = useState<TeamDraft | undefined>();
  const [draft, setDraft] = useState<TeamDraft | undefined>();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    if (!project) return;
    setLoading(true);
    setError('');
    setNotice('');
    try {
      const payload = await ports.load(project);
      const next = draftFromPayload(payload);
      setAgents(agentRowsFromPayload(payload));
      setLanes(lanesFromPayload(payload, next.lane));
      setCeiling(ceilingFromPayload(payload));
      setBaseline(next);
      setDraft(next);
    } catch (e) {
      setBaseline(undefined);
      setDraft(undefined);
      setError(e instanceof Error ? e.message : 'Die Team-Einstellungen konnten nicht gelesen werden.');
    } finally {
      setLoading(false);
    }
  }, [project, ports]);

  useEffect(() => {
    if (enabled) void load();
  }, [enabled, load]);

  const changed = Boolean(draft && baseline && teamChanged(draft, baseline));

  const save = useCallback(async () => {
    if (!draft || !baseline || !teamChanged(draft, baseline)) return;
    setSaving(true);
    setError('');
    setNotice('');
    try {
      const result = await ports.save(project, teamPatch(draft, baseline));
      const saved: TeamDraft = {
        maxWorkers: result.team.max_workers,
        lane: result.team.default_lane,
        agents: result.team.active_agents
      };
      setBaseline(saved);
      setDraft(saved);
      const ignored = result.ignored_fields || [];
      setNotice(ignored.length ? `Gespeichert. Nicht übernommen: ${ignored.join(', ')}.` : 'Gespeichert.');
    } catch (e) {
      // save_team answers 400 with the field and the reason. Showing that
      // verbatim beats a generic failure line.
      setError(e instanceof Error ? e.message : 'Speichern fehlgeschlagen.');
    } finally {
      setSaving(false);
    }
  }, [draft, baseline, project, ports]);

  const toggleAgent = useCallback((name: string) => {
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

      {loading && !draft && <p className="settings-hint" role="status">Team wird gelesen …</p>}

      {!loading && !draft && (
        <div className="cap-load-state">
          <p className="settings-hint bad" role="alert">
            {error || 'Die Team-Einstellungen sind nicht verfügbar.'}
          </p>
          <button type="button" className="settings-refresh" onClick={() => void load()}>
            Erneut laden
          </button>
        </div>
      )}

      {draft && (
        <div className="team-card" aria-busy={saving}>
          <label className="team-field">
            <span>Max. Worker</span>
            <input
              type="number"
              min={1}
              max={ceiling}
              value={draft.maxWorkers}
              aria-describedby="team-workers-hint"
              onChange={(event) => setDraft({ ...draft, maxWorkers: Number(event.currentTarget.value) })}
            />
          </label>
          <p className="settings-hint" id="team-workers-hint">1 bis {ceiling}.</p>

          <label className="team-field">
            <span>Default-Lane</span>
            <select
              value={draft.lane}
              onChange={(event) => setDraft({ ...draft, lane: event.currentTarget.value })}
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
              onClick={() => void save()}
            >
              {saving ? 'Wird gespeichert …' : 'Team speichern'}
            </button>
            {changed && !saving && <span className="settings-hint">Ungespeicherte Änderung.</span>}
          </div>

          {error && <p className="settings-hint bad" role="alert">{error}</p>}
          {notice && <p className="settings-hint" role="status">{notice}</p>}
        </div>
      )}
    </section>
  );
}
