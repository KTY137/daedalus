import { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { getEnvStatus, getRuntimeStatus, testRuntime, type EnvStatusPayload } from '@/shared/api';
import type { RuntimeRow } from '@/shared/contracts';
import { drawerVariants, useReducedMotionPref } from '@/shared/ui/motion';
import { SystemCapabilities } from '@/features/system/SystemCapabilities';
import { ComputeSection } from '@/features/system/ComputeSection';
import { trustNotes } from './runtimetrust';
import {
  AUTONOMY_LEVELS,
  readAutonomyLog,
  type AutonomyEntry,
  type AutonomyLevel
} from './autonomy';
import './settings.css';

/**
 * Settings: brain, autonomy, managed services/connections, measured runtime
 * reachability, and the local autonomy log.
 *
 * Desktop service controls are additive. A source/dev web_api that does not
 * install the Tauri sidecar extension still renders every older section and
 * reports the desktop controls as unavailable instead of breaking Settings.
 */

export interface SettingsProps {
  open: boolean;
  onClose: () => void;
  project: string;
  brain: string;
  onBrain: (id: string) => void;
  autonomy: AutonomyLevel;
  onAutonomy: (level: AutonomyLevel) => void;
  logSignal?: number;
}

interface RemoteOllamaSettings {
  host: string;
  user: string;
  port: number;
  identity_file: string;
  host_key_fingerprint: string;
  local_port: number;
  remote_port: number;
  start_method: 'systemd' | 'windows' | 'none';
  trust_remote_host: boolean;
}

type CapMode = 'bounded' | 'custom' | 'unbounded_execution';
type CapAxis =
  | 'period_usd'
  | 'billable_calls'
  | 'mission_spend'
  | 'tokens'
  | 'wall_time'
  | 'attempts'
  | 'concurrency'
  | 'work_scope';

type CapConfigured = Record<CapAxis, boolean>;

interface CapsConfig {
  mode: CapMode;
  configured: CapConfigured;
}

interface BudgetConfig {
  period_ceiling_usd: number;
  max_calls: number;
}

interface CapPolicy {
  caps: CapsConfig;
  budget: BudgetConfig;
}

interface CapEditor {
  baseline: CapPolicy;
  mode: CapMode;
  configured: CapConfigured;
  periodUsdText: string;
  maxCallsText: string;
}

const CAP_AXIS_ORDER: CapAxis[] = [
  'period_usd',
  'billable_calls',
  'mission_spend',
  'tokens',
  'wall_time',
  'attempts',
  'concurrency',
  'work_scope'
];

const CAP_AXIS_COPY: Record<CapAxis, { label: string; description: string }> = {
  period_usd: {
    label: 'Globale Periodenkosten (USD)',
    description: 'Kumulative Modellkosten innerhalb der Budgetperiode.'
  },
  billable_calls: {
    label: 'Bezahlte Modellaufrufe',
    description: 'Anzahl abrechenbarer Provider-Aufrufe pro Budgetperiode.'
  },
  mission_spend: {
    label: 'Mission-, EffectLease- und SpendEnvelope-Beträge',
    description: 'Geldgrenzen einzelner Missionen, Leases und SpendEnvelopes.'
  },
  tokens: {
    label: 'Input-, Kontext- und Output-Tokens',
    description: 'Tokenbudgets der neu zugelassenen Modellarbeit.'
  },
  wall_time: {
    label: 'Ausführungs-, Provider-, Gate- und Evaluationszeit',
    description: 'Daedalus-eigene Zeitlimits und Timeouts.'
  },
  attempts: {
    label: 'Retries, Attempts, Iterationen und Agent-Schritte',
    description: 'Wiederholungs- und Schrittgrenzen einer Arbeit.'
  },
  concurrency: {
    label: 'Read-only Worker, Fan-out und Kandidaten-Evaluation',
    description: 'Parallelität ausschließlich dort, wo die Schreibisolation sicher bleibt.'
  },
  work_scope: {
    label: 'Queue-Batch, Zerlegung, Rewrite-Umfang und Kandidatenmenge',
    description: 'Daedalus-eigene Grenzen für Arbeits- und Suchumfang.'
  }
};

const CAP_GROUPS: Array<{ title: string; axes: CapAxis[] }> = [
  { title: 'Kosten & Provider-Nutzung', axes: ['period_usd', 'billable_calls', 'mission_spend', 'tokens'] },
  { title: 'Laufzeit & Wiederholungen', axes: ['wall_time', 'attempts'] },
  { title: 'Parallelität & Arbeitsumfang', axes: ['concurrency', 'work_scope'] }
];

interface DesktopConfig {
  [key: string]: unknown;
  bridge: { auto_start: boolean };
  caps?: CapsConfig & { confirm_widening?: boolean };
  budget?: BudgetConfig;
  ollama: {
    mode: 'local' | 'remote_ssh';
    auto_start: boolean;
    model: string;
    local_host: string;
    remote: RemoteOllamaSettings;
  };
}

interface DesktopSnapshot {
  config: DesktopConfig;
  config_path: string;
  startup_error?: string;
  credential_policy: {
    ssh_key_only: boolean;
    stores_passwords: boolean;
    stores_private_key_bytes: boolean;
    host_key_verification: string;
  };
  services: {
    bridge: {
      managed?: boolean;
      state?: string;
      age_s?: number | null;
      detail?: string;
    };
    ollama: {
      mode: string;
      endpoint: string;
      physical_target?: string;
      reachable: boolean;
      last_error?: string;
      tunnel_running?: boolean;
      local_process_running?: boolean;
      host_key_pinned?: boolean;
    };
  };
}

interface DesktopEnvelope {
  ok?: boolean;
  error?: string;
  desktop?: DesktopSnapshot;
  service?: Record<string, unknown>;
}

async function desktopRequest(url: string, init?: RequestInit): Promise<DesktopEnvelope> {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init
  });
  let payload: DesktopEnvelope = {};
  try {
    payload = await response.json();
  } catch {
    // The status below still distinguishes an unavailable/old backend.
  }
  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `Desktop-Dienst antwortete mit HTTP ${response.status}.`);
  }
  return payload;
}

function stateOf(r: RuntimeRow): { word: string; tone: 'ok' | 'warn' | 'bad' } {
  if (r.available) return { word: 'erreichbar', tone: 'ok' };
  if (r.auth_status === 'not_configured') return { word: 'kein Schlüssel', tone: 'warn' };
  return { word: 'nicht erreichbar', tone: 'bad' };
}

function measuredLabel(r: RuntimeRow): string {
  if (typeof r.measured_at !== 'string' || !r.measured_at) return '';
  const age = typeof r.measured_age_s === 'number' ? r.measured_age_s : 0;
  if (age < 5) return 'gerade gemessen';
  if (age < 90) return `gemessen vor ${Math.round(age)} s`;
  const when = new Date(r.measured_at);
  if (Number.isNaN(when.getTime())) return `gemessen vor ${Math.round(age)} s`;
  const hh = String(when.getHours()).padStart(2, '0');
  const mm = String(when.getMinutes()).padStart(2, '0');
  return `gemessen ${hh}:${mm}`;
}

function cloneConfig(config: DesktopConfig): DesktopConfig {
  return JSON.parse(JSON.stringify(config)) as DesktopConfig;
}

function capPolicyOf(config: DesktopConfig): CapPolicy | undefined {
  const caps = config.caps;
  const budget = config.budget;
  if (
    !caps
    || !['bounded', 'custom', 'unbounded_execution'].includes(caps.mode)
    || !caps.configured
    || CAP_AXIS_ORDER.some((axis) => typeof caps.configured[axis] !== 'boolean')
    || !budget
    || typeof budget.period_ceiling_usd !== 'number'
    || !Number.isFinite(budget.period_ceiling_usd)
    || budget.period_ceiling_usd <= 0
    || typeof budget.max_calls !== 'number'
    || !Number.isSafeInteger(budget.max_calls)
    || budget.max_calls <= 0
  ) {
    return undefined;
  }
  return {
    caps: {
      mode: caps.mode,
      configured: Object.fromEntries(
        CAP_AXIS_ORDER.map((axis) => [axis, caps.configured[axis]])
      ) as CapConfigured
    },
    budget: {
      period_ceiling_usd: budget.period_ceiling_usd,
      max_calls: budget.max_calls
    }
  };
}

function editorFromPolicy(policy: CapPolicy): CapEditor {
  return {
    baseline: policy,
    mode: policy.caps.mode,
    configured: { ...policy.caps.configured },
    periodUsdText: String(policy.budget.period_ceiling_usd),
    maxCallsText: String(policy.budget.max_calls)
  };
}

function parsePositiveNumber(value: string): number | undefined {
  if (!value.trim()) return undefined;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : undefined;
}

function parsePositiveInteger(value: string): number | undefined {
  const parsed = parsePositiveNumber(value);
  return parsed !== undefined && Number.isSafeInteger(parsed) ? parsed : undefined;
}

function capEditorChanged(editor: CapEditor): boolean {
  const periodUsd = parsePositiveNumber(editor.periodUsdText);
  const maxCalls = parsePositiveInteger(editor.maxCallsText);
  return (
    periodUsd === undefined
    || maxCalls === undefined
    || editor.mode !== editor.baseline.caps.mode
    || CAP_AXIS_ORDER.some((axis) => editor.configured[axis] !== editor.baseline.caps.configured[axis])
    || periodUsd !== editor.baseline.budget.period_ceiling_usd
    || maxCalls !== editor.baseline.budget.max_calls
  );
}

function effectiveCaps(mode: CapMode, configured: CapConfigured): CapConfigured {
  const forced = mode === 'bounded' ? true : mode === 'unbounded_execution' ? false : undefined;
  return Object.fromEntries(
    CAP_AXIS_ORDER.map((axis) => [axis, forced ?? configured[axis]])
  ) as CapConfigured;
}

function wideningReasons(editor: CapEditor): string[] {
  const reasons = new Set<string>();
  const previousEffective = effectiveCaps(editor.baseline.caps.mode, editor.baseline.caps.configured);
  const nextEffective = effectiveCaps(editor.mode, editor.configured);

  if (editor.baseline.caps.mode === 'bounded' && editor.mode === 'custom') {
    reasons.add('Wechsel vom Standardmodus in den individuell abschaltbaren Modus');
  }
  if (editor.mode === 'unbounded_execution' && editor.baseline.caps.mode !== 'unbounded_execution') {
    reasons.add('Eintritt in die unbegrenzte Daedalus-Ausführung');
  }
  for (const axis of CAP_AXIS_ORDER) {
    if (
      (editor.baseline.caps.configured[axis] && !editor.configured[axis])
      || (previousEffective[axis] && !nextEffective[axis])
    ) {
      reasons.add(CAP_AXIS_COPY[axis].label);
    }
  }

  const periodUsd = parsePositiveNumber(editor.periodUsdText);
  if (periodUsd !== undefined && periodUsd > editor.baseline.budget.period_ceiling_usd) {
    reasons.add(`Perioden-USD von ${formatBudgetUsd(editor.baseline.budget.period_ceiling_usd)} auf ${formatBudgetUsd(periodUsd)}`);
  }
  const maxCalls = parsePositiveInteger(editor.maxCallsText);
  if (maxCalls !== undefined && maxCalls > editor.baseline.budget.max_calls) {
    reasons.add(`bezahlte Aufrufe von ${editor.baseline.budget.max_calls} auf ${maxCalls}`);
  }
  return [...reasons];
}

function formatBudgetUsd(value: number): string {
  return `${value.toLocaleString('de-DE', { maximumFractionDigits: 6 })} USD`;
}

export function Settings({ open, onClose, project, brain, onBrain, autonomy, onAutonomy, logSignal = 0 }: SettingsProps) {
  const [runtimes, setRuntimes] = useState<RuntimeRow[]>([]);
  const [env, setEnv] = useState<EnvStatusPayload | undefined>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [testing, setTesting] = useState('');
  const [testResult, setTestResult] = useState<Record<string, string>>({});
  const [log, setLog] = useState<AutonomyEntry[]>([]);

  const [desktop, setDesktop] = useState<DesktopSnapshot | undefined>();
  const [desktopDraft, setDesktopDraft] = useState<DesktopConfig | undefined>();
  const [desktopError, setDesktopError] = useState('');
  const [desktopNotice, setDesktopNotice] = useState('');
  const [desktopBusy, setDesktopBusy] = useState('');
  const [desktopLoading, setDesktopLoading] = useState(false);
  const [capEditor, setCapEditor] = useState<CapEditor | undefined>();
  const [capError, setCapError] = useState('');
  const [capNotice, setCapNotice] = useState('');
  const [capConfirmed, setCapConfirmed] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const [rt, e] = await Promise.all([getRuntimeStatus(), getEnvStatus()]);
      setRuntimes(rt.runtimes || []);
      setEnv(e.env);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Der Zustand der Laufzeiten konnte nicht gelesen werden.');
    } finally {
      setLoading(false);
      setLoaded(true);
    }
  }, []);

  const loadDesktop = useCallback(async () => {
    setDesktopError('');
    setCapError('');
    setCapNotice('');
    setCapConfirmed(false);
    setDesktopLoading(true);
    try {
      const payload = await desktopRequest('/api/desktop/settings');
      if (!payload.desktop) throw new Error('Desktop-Backend meldete keine Einstellungen.');
      setDesktop(payload.desktop);
      setDesktopDraft(cloneConfig(payload.desktop.config));
      const canonicalPolicy = capPolicyOf(payload.desktop.config);
      if (!canonicalPolicy) {
        setCapEditor((prev) => (prev && capEditorChanged(prev) ? prev : undefined));
        setCapError('Dieses Desktop-Backend meldet keine gültige Ausführungs-Cap-Policy.');
      } else {
        setCapEditor((prev) => (
          prev && capEditorChanged(prev)
            ? { ...prev, baseline: canonicalPolicy }
            : editorFromPolicy(canonicalPolicy)
        ));
      }
    } catch (e) {
      setDesktop(undefined);
      setDesktopDraft(undefined);
      const message = e instanceof Error
        ? e.message
        : 'Desktop-Serviceverwaltung ist in diesem Lauf nicht verfügbar.';
      setDesktopError(message);
      setCapError(message);
      setCapEditor((prev) => (prev && capEditorChanged(prev) ? prev : undefined));
    } finally {
      setDesktopLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) {
      void load();
      void loadDesktop();
    }
  }, [open, load, loadDesktop]);

  useEffect(() => {
    setLog(readAutonomyLog());
  }, [open, logSignal]);

  const runTest = useCallback(async (id: string) => {
    setTesting(id);
    try {
      const payload = await testRuntime(id);
      setTestResult((prev) => ({
        ...prev,
        [id]: payload.test?.ok
          ? `antwortet · ${payload.test.detail || payload.test.mode}`
          : `fehlgeschlagen: ${payload.test?.detail || 'ohne Angabe'}`
      }));
    } catch (e) {
      setTestResult((prev) => ({
        ...prev,
        [id]: `fehlgeschlagen: ${e instanceof Error ? e.message : 'unbekannt'}`
      }));
    } finally {
      setTesting('');
    }
  }, []);

  const patchOllama = useCallback((patch: Partial<DesktopConfig['ollama']>) => {
    setDesktopDraft((prev) => (
      prev ? { ...prev, ollama: { ...prev.ollama, ...patch } } : prev
    ));
  }, []);

  const patchRemote = useCallback((patch: Partial<RemoteOllamaSettings>) => {
    setDesktopDraft((prev) => (
      prev
        ? {
            ...prev,
            ollama: {
              ...prev.ollama,
              remote: { ...prev.ollama.remote, ...patch }
            }
          }
        : prev
    ));
  }, []);

  const saveDesktop = useCallback(async () => {
    if (!desktopDraft) return;
    setDesktopBusy('save');
    setDesktopError('');
    setDesktopNotice('');
    try {
      const payload = await desktopRequest('/api/desktop/settings', {
        method: 'PUT',
        body: JSON.stringify(desktopDraft)
      });
      if (!payload.desktop) throw new Error('Desktop-Backend bestätigte die Einstellungen nicht.');
      setDesktop(payload.desktop);
      setDesktopDraft(cloneConfig(payload.desktop.config));
      const canonicalPolicy = capPolicyOf(payload.desktop.config);
      if (canonicalPolicy) {
        setCapEditor((prev) => (
          prev && capEditorChanged(prev)
            ? { ...prev, baseline: canonicalPolicy }
            : editorFromPolicy(canonicalPolicy)
        ));
      }
      setDesktopNotice(
        payload.desktop.startup_error
          ? `Gespeichert. Autostart meldet: ${payload.desktop.startup_error}`
          : 'Gespeichert und auf den laufenden Desktop angewendet.'
      );
      void load();
    } catch (e) {
      setDesktopError(e instanceof Error ? e.message : 'Einstellungen konnten nicht gespeichert werden.');
    } finally {
      setDesktopBusy('');
    }
  }, [desktopDraft, load]);

  const editCaps = useCallback((patch: Partial<Omit<CapEditor, 'baseline'>>) => {
    setCapEditor((prev) => (prev ? { ...prev, ...patch } : prev));
    setCapConfirmed(false);
    setCapError('');
    setCapNotice('');
  }, []);

  const saveCaps = useCallback(async () => {
    if (!desktop || !capEditor) return;
    const periodUsd = parsePositiveNumber(capEditor.periodUsdText);
    const maxCalls = parsePositiveInteger(capEditor.maxCallsText);
    if (periodUsd === undefined || maxCalls === undefined || !capEditorChanged(capEditor)) return;

    const widening = wideningReasons(capEditor);
    if (widening.length > 0 && !capConfirmed) return;

    setDesktopBusy('caps-save');
    setCapError('');
    setCapNotice('');
    try {
      const nextConfig = cloneConfig(desktop.config);
      nextConfig.caps = {
        mode: capEditor.mode,
        configured: { ...capEditor.configured },
        ...(widening.length > 0 ? { confirm_widening: true } : {})
      };
      nextConfig.budget = {
        period_ceiling_usd: periodUsd,
        max_calls: maxCalls
      };
      const payload = await desktopRequest('/api/desktop/settings', {
        method: 'PUT',
        body: JSON.stringify(nextConfig)
      });
      if (!payload.desktop) throw new Error('Desktop-Backend bestätigte die Ausführungs-Cap-Policy nicht.');
      const canonicalPolicy = capPolicyOf(payload.desktop.config);
      if (!canonicalPolicy) throw new Error('Desktop-Backend gab keine gültige Ausführungs-Cap-Policy zurück.');

      setDesktop(payload.desktop);
      setDesktopDraft((prev) => {
        const next = prev ? cloneConfig(prev) : cloneConfig(payload.desktop!.config);
        next.caps = canonicalPolicy.caps;
        next.budget = canonicalPolicy.budget;
        return next;
      });
      setCapEditor(editorFromPolicy(canonicalPolicy));
      setCapConfirmed(false);
      const disabled = CAP_AXIS_ORDER.filter((axis) => (
        !effectiveCaps(canonicalPolicy.caps.mode, canonicalPolicy.caps.configured)[axis]
      ));
      setCapNotice(
        canonicalPolicy.caps.mode === 'bounded'
          ? 'Gespeichert: Alle acht Daedalus-Ausführungsgrenzen sind für neue Arbeit aktiv.'
          : canonicalPolicy.caps.mode === 'unbounded_execution'
            ? 'Gespeichert: Unbegrenzte Daedalus-Ausführung für neue Arbeit. Ledger und Evidenzaufzeichnung bleiben aktiv.'
            : `Gespeichert: Individuelle Cap-Policy mit ${disabled.length} deaktivierten ${disabled.length === 1 ? 'Achse' : 'Achsen'}.`
      );
    } catch (e) {
      setCapConfirmed(false);
      setCapError(e instanceof Error ? e.message : 'Ausführungs-Cap-Policy konnte nicht gespeichert werden.');
    } finally {
      setDesktopBusy('');
    }
  }, [capConfirmed, capEditor, desktop]);

  const serviceAction = useCallback(async (service: 'bridge' | 'ollama', verb: 'start' | 'stop' = 'start') => {
    const key = `${service}:${verb}`;
    setDesktopBusy(key);
    setDesktopError('');
    setDesktopNotice('');
    try {
      await desktopRequest(`/api/desktop/services/${service}/${verb}`, {
        method: 'POST',
        body: '{}'
      });
      setDesktopNotice(service === 'bridge' ? 'Bridge läuft.' : verb === 'stop' ? 'Ollama-Tunnel beendet.' : 'Ollama gestartet.');
      await loadDesktop();
      void load();
    } catch (e) {
      setDesktopError(e instanceof Error ? e.message : 'Dienstaktion fehlgeschlagen.');
    } finally {
      setDesktopBusy('');
    }
  }, [load, loadDesktop]);

  const reachable = runtimes.filter((r) => r.available);
  const reduced = useReducedMotionPref();
  const drawer = useMemo(() => drawerVariants(reduced), [reduced]);

  const bridgeState = desktop?.services.bridge;
  const ollamaState = desktop?.services.ollama;
  const remoteMode = desktopDraft?.ollama.mode === 'remote_ssh';
  const capPeriodUsd = capEditor ? parsePositiveNumber(capEditor.periodUsdText) : undefined;
  const capMaxCalls = capEditor ? parsePositiveInteger(capEditor.maxCallsText) : undefined;
  const capDirty = capEditor ? capEditorChanged(capEditor) : false;
  const capWideningReasons = capEditor ? wideningReasons(capEditor) : [];
  const capEffective = capEditor ? effectiveCaps(capEditor.mode, capEditor.configured) : undefined;
  const disabledCapAxes = capEffective
    ? CAP_AXIS_ORDER.filter((axis) => !capEffective[axis])
    : [];
  const capSaveDisabled = (
    !desktop
    || !capEditor
    || capPeriodUsd === undefined
    || capMaxCalls === undefined
    || !capDirty
    || desktopBusy !== ''
    || (capWideningReasons.length > 0 && !capConfirmed)
  );

  return (
    <motion.aside
      className={open ? 'settings open' : 'settings'}
      data-motion="drawer"
      variants={drawer}
      initial={false}
      animate={open ? 'open' : 'closed'}
      aria-hidden={!open}
      aria-label="Einstellungen"
    >
      <header className="settings-head">
        <h2>Einstellungen</h2>
        <button type="button" className="settings-close" onClick={onClose} aria-label="Einstellungen schließen">
          ✕
        </button>
      </header>

      <div className="settings-body">
        <section className="settings-section">
          <div className="settings-title">Brain</div>
          <p className="settings-hint">
            Wer antwortet, wenn du Ikarus etwas fragst. Nur erreichbare Laufzeiten stehen zur Wahl.
          </p>
          <div className="choice-row" role="radiogroup" aria-label="Brain">
            <button
              type="button"
              role="radio"
              aria-checked={brain === ''}
              className={brain === '' ? 'on' : ''}
              onClick={() => onBrain('')}
            >
              Automatisch
            </button>
            {reachable.map((r) => (
              <button
                key={r.id}
                type="button"
                role="radio"
                aria-checked={brain === r.id}
                className={brain === r.id ? 'on' : ''}
                onClick={() => onBrain(r.id)}
              >
                {r.label || r.id}
              </button>
            ))}
          </div>
          {!loaded && <p className="settings-hint">Wird geprüft …</p>}
          {loaded && !loading && reachable.length === 0 && (
            <p className="settings-hint bad">
              Keine Laufzeit ist erreichbar. Ikarus antwortet dann aus dem lokalen Index — gemessen, aber ohne Modell.
            </p>
          )}
        </section>

        <section className="settings-section">
          <div className="settings-title">Ohne Rückfrage</div>
          <p className="settings-hint">
            Was Ikarus tun darf, ohne dich zu fragen. Jede automatische Aktion steht unten im Protokoll.
          </p>
          <div className="autonomy">
            {AUTONOMY_LEVELS.map((level) => (
              <button
                key={level.id}
                type="button"
                className={autonomy === level.id ? 'on' : ''}
                aria-pressed={autonomy === level.id}
                onClick={() => onAutonomy(level.id)}
              >
                <b>{level.label}</b>
                <span>{level.note}</span>
              </button>
            ))}
          </div>
        </section>

        <SystemCapabilities project={project} enabled={open} />

        {/* What compute this machine can actually use. Read only while the
            panel is open: the shallow probe is cheap, but polling a closed
            panel would still be work nobody asked for. */}
        <ComputeSection enabled={open} />

        <section className="settings-section" aria-labelledby="caps-settings-title">
          <div className="settings-title" id="caps-settings-title">Ausführungsgrenzen</div>
          <p className="settings-hint">
            Wähle den Master-Modus und die Daedalus-eigenen Ressourcenlimits für neu zugelassene Arbeit.
            Bereits ausgestellte Verträge werden nicht nachträglich geändert.
          </p>

          {desktopLoading && !capEditor && (
            <p className="settings-hint" role="status">Cap-Policy wird gelesen …</p>
          )}
          {!desktopLoading && !capEditor && (
            <div className="cap-load-state">
              <p className="settings-hint bad" role="alert">
                {capError || 'Die Ausführungs-Cap-Policy ist nicht verfügbar.'}
              </p>
              <button type="button" className="settings-refresh" onClick={() => void loadDesktop()}>
                Erneut laden
              </button>
            </div>
          )}

          {capEditor && capEffective && (
            <div className="cap-card" aria-busy={desktopBusy === 'caps-save'}>
              {desktopLoading && <p className="settings-hint" role="status">Serverstand wird aktualisiert …</p>}

              <div className={`cap-policy-status ${disabledCapAxes.length ? 'widened' : ''}`}>
                <div>
                  <b>
                    {capEditor.mode === 'bounded'
                      ? 'Begrenzt · alle acht Cap-Achsen aktiv'
                      : capEditor.mode === 'unbounded_execution'
                        ? 'Unbegrenzte Daedalus-Ausführung'
                        : `Individuell · ${disabledCapAxes.length} ${disabledCapAxes.length === 1 ? 'Achse' : 'Achsen'} deaktiviert`}
                  </b>
                  <small>
                    Effektiver Zustand für neue Reservierungen, Missionen, Attempts, Leases, Provider-Aufrufe und Kampagnen.
                  </small>
                </div>
                <code>{capEditor.mode}</code>
              </div>

              <fieldset className="cap-mode-fieldset">
                <legend>Master-Modus</legend>
                <div className="cap-mode-grid">
                  {([
                    {
                      id: 'bounded' as const,
                      label: 'Begrenzt (Standard)',
                      note: 'Alle acht Daedalus-Cap-Achsen werden erzwungen.'
                    },
                    {
                      id: 'custom' as const,
                      label: 'Individuell',
                      note: 'Die acht Achsen unten einzeln ein- oder ausschalten.'
                    },
                    {
                      id: 'unbounded_execution' as const,
                      label: 'Unbegrenzte Ausführung',
                      note: 'Alle Daedalus-eigenen Ausführungs-Caps für neue Arbeit ausschalten.'
                    }
                  ]).map((mode) => (
                    <label
                      className={`cap-mode-option ${capEditor.mode === mode.id ? 'selected' : ''} ${mode.id === 'unbounded_execution' ? 'danger' : ''}`}
                      key={mode.id}
                    >
                      <input
                        type="radio"
                        name="cap-mode"
                        value={mode.id}
                        checked={capEditor.mode === mode.id}
                        onChange={() => editCaps({ mode: mode.id })}
                        disabled={desktopBusy !== ''}
                      />
                      <span><b>{mode.label}</b><small>{mode.note}</small></span>
                    </label>
                  ))}
                </div>
              </fieldset>

              {disabledCapAxes.length > 0 && (
                <div className="cap-disabled-disclosure" role="note">
                  <b>
                    {capEditor.mode === 'unbounded_execution'
                      ? 'Unbegrenzte Daedalus-Ausführung: alle acht Cap-Achsen sind aus'
                      : `${disabledCapAxes.length} Daedalus-${disabledCapAxes.length === 1 ? 'Cap-Achse ist' : 'Cap-Achsen sind'} aus`}
                  </b>
                  <p>
                    Diese Achsen verweigern neu zugelassene Arbeit nicht mehr. Nutzung, Kosten, Ledger und Evidenz
                    werden weiterhin gemessen und aufgezeichnet.
                  </p>
                  <ul>
                    {disabledCapAxes.map((axis) => <li key={axis}>{CAP_AXIS_COPY[axis].label}</li>)}
                  </ul>
                </div>
              )}

              <div className="cap-groups">
                {CAP_GROUPS.map((group, groupIndex) => (
                  <section className="cap-group" key={group.title} aria-labelledby={`cap-group-${groupIndex}`}>
                    <h3 id={`cap-group-${groupIndex}`}>{group.title}</h3>
                    {group.axes.map((axis) => (
                      <div className="cap-axis" key={axis}>
                        <div className="cap-axis-head">
                          <div>
                            <b>{CAP_AXIS_COPY[axis].label}</b>
                            <small>{CAP_AXIS_COPY[axis].description}</small>
                          </div>
                          <span className={`cap-effective ${capEffective[axis] ? 'on' : 'off'}`}>
                            Effektiv: {capEffective[axis] ? 'aktiv' : 'aus'}
                          </span>
                        </div>
                        <label className="spend-switch cap-axis-switch">
                          <input
                            type="checkbox"
                            role="switch"
                            checked={capEditor.configured[axis]}
                            onChange={(event) => editCaps({
                              configured: { ...capEditor.configured, [axis]: event.target.checked }
                            })}
                            disabled={capEditor.mode !== 'custom' || desktopBusy !== ''}
                            aria-label={`${CAP_AXIS_COPY[axis].label} begrenzen`}
                          />
                          <span className="spend-switch-track" aria-hidden="true"><span /></span>
                          <span>Im individuellen Modus begrenzen</span>
                        </label>

                        {axis === 'period_usd' && (
                          <label className="settings-field cap-value-field">
                            <span>Gespeicherter USD-Fallback pro Budgetperiode</span>
                            <input
                              type="number"
                              min="0.01"
                              step="any"
                              inputMode="decimal"
                              value={capEditor.periodUsdText}
                              onChange={(event) => editCaps({ periodUsdText: event.target.value })}
                              disabled={desktopBusy !== ''}
                            />
                            <small>Bleibt positiv gespeichert, auch wenn diese Achse effektiv aus ist.</small>
                          </label>
                        )}
                        {axis === 'billable_calls' && (
                          <label className="settings-field cap-value-field">
                            <span>Gespeicherter Aufruf-Fallback pro Budgetperiode</span>
                            <input
                              type="number"
                              min="1"
                              max={Number.MAX_SAFE_INTEGER}
                              step="1"
                              inputMode="numeric"
                              value={capEditor.maxCallsText}
                              onChange={(event) => editCaps({ maxCallsText: event.target.value })}
                              disabled={desktopBusy !== ''}
                            />
                            <small>Eine positive ganze Zahl; keine Null oder Großzahl als Unlimited-Sentinel.</small>
                          </label>
                        )}
                      </div>
                    ))}
                  </section>
                ))}
              </div>

              <p className="settings-hint cap-contract-note">
                Token-, Zeit-, Attempt-, Parallelitäts- und Umfangswerte bleiben als positive Fallbacks in ihren
                jeweiligen Mission-/Runtime-Verträgen erhalten; dieses Menü ändert deren Durchsetzung.
              </p>

              {capWideningReasons.length > 0 && (
                <div className="cap-widening-warning">
                  <b>Diese Änderung erweitert die Ausführungsautorität</b>
                  <p>Betroffen:</p>
                  <ul>{capWideningReasons.map((reason) => <li key={reason}>{reason}</li>)}</ul>
                  <label className="settings-check danger cap-confirm">
                    <input
                      type="checkbox"
                      checked={capConfirmed}
                      onChange={(event) => setCapConfirmed(event.target.checked)}
                      disabled={desktopBusy !== ''}
                    />
                    <span>
                      <b>Risiko bewusst bestätigen</b>
                      <small>
                        Ich bestätige die genannten deaktivierten oder erhöhten Ausführungsgrenzen und das Risiko
                        deutlich höherer Kosten, Laufzeit, Parallelität und Arbeitsmenge.
                      </small>
                    </span>
                  </label>
                </div>
              )}

              {capPeriodUsd === undefined && (
                <p className="settings-hint bad" role="alert">Der USD-Fallback muss positiv und endlich sein.</p>
              )}
              {capMaxCalls === undefined && (
                <p className="settings-hint bad" role="alert">Der Aufruf-Fallback muss eine positive ganze Zahl sein.</p>
              )}
              {capError && <p className="settings-hint bad" role="alert">{capError}</p>}
              {capNotice && <p className="settings-hint cap-notice" role="status" aria-live="polite">{capNotice}</p>}

              <div className="settings-save-row cap-actions">
                <span className="settings-hint">Keine Grenze wird automatisch erhöht oder ausgeschaltet.</span>
                <button
                  type="button"
                  className="settings-primary"
                  onClick={() => void saveCaps()}
                  disabled={capSaveDisabled}
                >
                  {desktopBusy === 'caps-save' ? 'Speichert …' : 'Cap-Policy speichern'}
                </button>
              </div>
            </div>
          )}

          <div className="cap-boundary-grid">
            <div className="cap-boundary-card">
              <b>Bleibt immer erzwungen</b>
              <p>
                Kill-Switch, Egress-Zulassung, begrenzte Schreibwurzeln, Secret-/Tool-Rechte, Authentifizierung,
                Evaluator-Isolation, Provenienz, Evidenz-Gates, explizite Owner-Freigabe und das Verbot von
                Auto-Merge/Auto-Promotion. Unsichere parallele Schreibzugriffe bleiben verweigert; Sandbox-CPU-,
                RAM-, PID- und Dateisystemquoten bleiben Host-Containment.
              </p>
            </div>
            <div className="cap-boundary-card external">
              <b>Externe Grenzen bleiben real</b>
              <p>
                Provider-Kontextfenster, API-Quoten und Rate-Limits, Hardware, Datenträger und Betriebssystem setzen
                weiterhin physische Grenzen. Daedalus kann sie nicht abschalten und behauptet das hier auch nicht.
              </p>
            </div>
          </div>
          <div className="cap-ariadne-notice" role="note">
            <b>Ariadne ist noch nicht live</b>
            <p>
              Auf dem Live-Pfad existiert aktuell kein Evolution-Campaign-Produzent. Diese Policy bereitet
              Kampagnenkontrollen vor, startet aber keine Kampagne.
            </p>
          </div>
        </section>

        <section className="settings-section">
          <div className="settings-title">Dienste & Verbindungen</div>
          <p className="settings-hint">
            Der Desktop hält Bridge und Ollama selbst am Leben. Remote-Ollama läuft durch einen SSH-Loopback-Tunnel;
            Port 11434 muss nicht ins LAN oder Internet geöffnet werden.
          </p>

          {!desktopDraft ? (
            <p className={`settings-hint ${desktopError ? 'bad' : ''}`}>
              {desktopError || 'Desktop-Dienste werden gelesen …'}
            </p>
          ) : (
            <div className="connection-stack">
              <div className="service-status">
                <div>
                  <b>Bridge</b>
                  <span className={bridgeState?.state === 'alive' || bridgeState?.state === 'busy' ? 'ok' : 'bad'}>
                    {bridgeState?.state || 'unbekannt'}
                  </span>
                </div>
                <button
                  type="button"
                  onClick={() => void serviceAction('bridge')}
                  disabled={desktopBusy !== ''}
                >
                  {desktopBusy === 'bridge:start' ? 'Startet …' : 'Starten'}
                </button>
              </div>

              <label className="settings-check">
                <input
                  type="checkbox"
                  checked={desktopDraft.bridge.auto_start}
                  onChange={(event) => setDesktopDraft((prev) => (
                    prev ? { ...prev, bridge: { auto_start: event.target.checked } } : prev
                  ))}
                />
                <span>
                  <b>Bridge mit Daedalus starten</b>
                  <small>Dann braucht `python -m daedalus.file_bridge watch …` kein eigenes Terminal mehr.</small>
                </span>
              </label>

              <div className="service-status">
                <div>
                  <b>Ollama</b>
                  <span className={ollamaState?.reachable ? 'ok' : 'bad'}>
                    {ollamaState?.reachable ? 'erreichbar' : 'offline'}
                  </span>
                  {ollamaState?.endpoint && <code>{ollamaState.endpoint}</code>}
                </div>
                <div className="service-actions">
                  <button
                    type="button"
                    onClick={() => void serviceAction('ollama')}
                    disabled={desktopBusy !== ''}
                  >
                    {desktopBusy === 'ollama:start' ? 'Startet …' : 'Starten'}
                  </button>
                  {remoteMode && ollamaState?.tunnel_running && (
                    <button
                      type="button"
                      onClick={() => void serviceAction('ollama', 'stop')}
                      disabled={desktopBusy !== ''}
                    >
                      Tunnel stoppen
                    </button>
                  )}
                </div>
              </div>

              <label className="settings-field">
                <span>Ollama-Modell</span>
                <input
                  value={desktopDraft.ollama.model}
                  onChange={(event) => patchOllama({ model: event.target.value })}
                  placeholder="qwen2.5-coder:7b"
                />
              </label>

              <label className="settings-field">
                <span>Ollama läuft</span>
                <select
                  value={desktopDraft.ollama.mode}
                  onChange={(event) => patchOllama({ mode: event.target.value as DesktopConfig['ollama']['mode'] })}
                >
                  <option value="local">auf diesem Rechner</option>
                  <option value="remote_ssh">remote über SSH-Tunnel</option>
                </select>
              </label>

              <label className="settings-check">
                <input
                  type="checkbox"
                  checked={desktopDraft.ollama.auto_start}
                  onChange={(event) => patchOllama({ auto_start: event.target.checked })}
                />
                <span>
                  <b>Ollama automatisch starten</b>
                  <small>Lokal mit `ollama serve`, remote über den unten gewählten festen Startmechanismus.</small>
                </span>
              </label>

              {!remoteMode ? (
                <label className="settings-field">
                  <span>Lokaler Endpoint</span>
                  <input
                    value={desktopDraft.ollama.local_host}
                    onChange={(event) => patchOllama({ local_host: event.target.value })}
                    placeholder="http://127.0.0.1:11434"
                  />
                  <small>Nur numerisches Loopback wird akzeptiert.</small>
                </label>
              ) : (
                <div className="remote-settings">
                  <div className="settings-grid two">
                    <label className="settings-field">
                      <span>SSH Host</span>
                      <input
                        value={desktopDraft.ollama.remote.host}
                        onChange={(event) => patchRemote({ host: event.target.value })}
                        placeholder="192.168.1.50"
                      />
                    </label>
                    <label className="settings-field">
                      <span>SSH Benutzer</span>
                      <input
                        value={desktopDraft.ollama.remote.user}
                        onChange={(event) => patchRemote({ user: event.target.value })}
                        placeholder="kaya"
                      />
                    </label>
                  </div>

                  <div className="settings-grid three">
                    <label className="settings-field">
                      <span>SSH Port</span>
                      <input
                        type="number"
                        min={1}
                        max={65535}
                        value={desktopDraft.ollama.remote.port}
                        onChange={(event) => patchRemote({ port: Number(event.target.value) })}
                      />
                    </label>
                    <label className="settings-field">
                      <span>Lokaler Tunnel</span>
                      <input
                        type="number"
                        min={1024}
                        max={65535}
                        value={desktopDraft.ollama.remote.local_port}
                        onChange={(event) => patchRemote({ local_port: Number(event.target.value) })}
                      />
                    </label>
                    <label className="settings-field">
                      <span>Remote Ollama</span>
                      <input
                        type="number"
                        min={1}
                        max={65535}
                        value={desktopDraft.ollama.remote.remote_port}
                        onChange={(event) => patchRemote({ remote_port: Number(event.target.value) })}
                      />
                    </label>
                  </div>

                  <label className="settings-field">
                    <span>SSH Private-Key-Pfad</span>
                    <input
                      value={desktopDraft.ollama.remote.identity_file}
                      onChange={(event) => patchRemote({ identity_file: event.target.value })}
                      placeholder="C:\Users\du\.ssh\id_ed25519"
                    />
                    <small>Daedalus speichert nur den Pfad, niemals den privaten Schlüssel oder ein SSH-Passwort.</small>
                  </label>

                  <label className="settings-field">
                    <span>Server Host-Key-Fingerprint</span>
                    <input
                      value={desktopDraft.ollama.remote.host_key_fingerprint}
                      onChange={(event) => patchRemote({ host_key_fingerprint: event.target.value })}
                      placeholder="SHA256:…"
                    />
                    <small>Beim ersten Connect Pflicht. Der gescannte Host-Key muss exakt zu diesem Fingerprint passen.</small>
                  </label>

                  <label className="settings-field">
                    <span>Remote starten mit</span>
                    <select
                      value={desktopDraft.ollama.remote.start_method}
                      onChange={(event) => patchRemote({ start_method: event.target.value as RemoteOllamaSettings['start_method'] })}
                    >
                      <option value="systemd">Linux / systemd</option>
                      <option value="windows">Windows / PowerShell</option>
                      <option value="none">bereits laufend — nur Tunnel öffnen</option>
                    </select>
                    <small>
                      systemd verwendet ausschließlich `sudo -n systemctl start ollama`; es werden keine frei editierbaren Remote-Befehle ausgeführt.
                    </small>
                  </label>

                  <label className="settings-check danger">
                    <input
                      type="checkbox"
                      checked={desktopDraft.ollama.remote.trust_remote_host}
                      onChange={(event) => patchRemote({ trust_remote_host: event.target.checked })}
                    />
                    <span>
                      <b>Remote-Rechner gehört zu meiner Trust Boundary</b>
                      <small>
                        Aus bedeutet Default-Deny-Egress. An erlaubt auch nicht öffentlich freigegebenen Source-Code zum Remote-Modell und ist nur für eine numerische IP möglich.
                      </small>
                    </span>
                  </label>
                </div>
              )}

              {ollamaState?.physical_target && (
                <p className="settings-hint">
                  Physisches Ziel der Egress-Policy: <code>{ollamaState.physical_target}</code>
                </p>
              )}
              {ollamaState?.last_error && !ollamaState.reachable && (
                <p className="settings-hint bad">{ollamaState.last_error}</p>
              )}
              {desktopError && <p className="settings-hint bad">{desktopError}</p>}
              {desktopNotice && <p className="settings-hint">{desktopNotice}</p>}

              <div className="settings-save-row">
                <span className="settings-hint">
                  SSH: Key-only · Host-Key {desktop?.credential_policy.host_key_verification || 'strict'}
                </span>
                <button
                  type="button"
                  className="settings-primary"
                  onClick={() => void saveDesktop()}
                  disabled={desktopBusy !== ''}
                >
                  {desktopBusy === 'save' ? 'Speichert …' : 'Verbindungen speichern'}
                </button>
              </div>
            </div>
          )}
        </section>

        <section className="settings-section">
          <div className="settings-title">
            Erreichbarkeit
            <button type="button" className="settings-refresh" onClick={() => { void load(); void loadDesktop(); }} disabled={loading}>
              {loading ? 'Prüft …' : 'Neu prüfen'}
            </button>
          </div>
          {error && <p className="settings-hint bad">{error}</p>}
          <ul className="reach">
            {runtimes.map((r) => {
              const s = stateOf(r);
              const measured = measuredLabel(r);
              return (
                <li key={r.id}>
                  <div className="reach-row">
                    <span className={`dot ${s.tone}`} aria-hidden="true" />
                    <span className="reach-name">{r.label || r.id}</span>
                    <span className={`reach-state ${s.tone}`}>{s.word}</span>
                    {measured && <span className="reach-age">{measured}</span>}
                    <button type="button" onClick={() => void runTest(r.id)} disabled={testing === r.id}>
                      {testing === r.id ? '…' : 'Testen'}
                    </button>
                  </div>
                  {/* WHERE YOUR SOURCE GOES IF YOU PICK THIS ONE.
                      Six capability and trust flags have been sent by this
                      endpoint since it shipped and were undeclared in the
                      contract until 2026-09-03, so nothing could read them.
                      `trusted_with_ip` is enforced at the egress gate, not
                      advisory: a picker that offers runtimes without saying
                      which the gate treats as untrusted asks the operator to
                      choose where their code goes while withholding the one
                      fact that makes the choice meaningful. */}
                  <div className="reach-trust">
                    {trustNotes(r).map((note) => (
                      <span key={note.text} className={`trust-chip ${note.tone}`} title={note.why}>
                        {note.text}
                      </span>
                    ))}
                  </div>
                  {(r.last_error || testResult[r.id] || r.selected_model) && (
                    <div className="reach-detail">
                      {r.selected_model ? <code>{r.selected_model}</code> : null}
                      {r.last_error ? <span className="bad">{r.last_error}</span> : null}
                      {testResult[r.id] ? <span>{testResult[r.id]}</span> : null}
                    </div>
                  )}
                </li>
              );
            })}
            {!loaded && <li className="settings-hint">Laufzeiten werden geprüft …</li>}
            {loaded && !loading && runtimes.length === 0 && (
              <li className="settings-hint">Keine Laufzeiten gemeldet.</li>
            )}
          </ul>
          {env && (
            <p className="settings-hint">
              API-Schlüssel bleiben auf deiner Maschine: die API gibt nur zurück, OB einer gesetzt ist, nie welcher.
            </p>
          )}
        </section>

        <section className="settings-section">
          <div className="settings-title">Protokoll</div>
          {log.length === 0 ? (
            <p className="settings-hint">Nichts ist bisher ohne deinen Klick passiert.</p>
          ) : (
            <ul className="autolog">
              {log.slice(0, 12).map((e, i) => (
                <li key={i}>
                  <span className="autolog-when">{new Date(e.at).toLocaleString('de-DE')}</span>
                  <span className="autolog-what">{e.what}</span>
                  <span className="autolog-detail">{e.detail}</span>
                  <span className="autolog-level">Stufe {e.level}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </motion.aside>
  );
}
