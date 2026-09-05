import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { motion } from 'framer-motion';
import {
  ApiError,
  getDesktopSettingsDocument,
  getEnvStatus,
  getRuntimeStatus,
  putDesktopSettingsDocument,
  runDesktopServiceAction,
  testRuntime,
  type EnvStatusPayload
} from '@/shared/api';
import type { RuntimeRow } from '@/shared/contracts';
import { drawerVariants, useReducedMotionPref } from '@/shared/ui/motion';
import { useDialogFocus } from '@/shared/ui/useDialogFocus';
import { SystemCapabilities } from '@/features/system/SystemCapabilities';
import { ComputeSection } from '@/features/system/ComputeSection';
import { CatalogueSection } from '@/features/system/CatalogueSection';
import { trustNotes } from './runtimetrust';
import { TeamSettings } from './Team';
import './settings.css';

/**
 * Settings: brain, managed services/connections, and measured runtime
 * reachability.
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

const DESKTOP_SETTINGS_UPDATE_CONTRACT = 'section_updates_v1';

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
  settings_update_contract?: string;
  config_error?: string;
  startup_error?: string;
  credential_policy: {
    ssh_key_only: boolean;
    stores_passwords: boolean;
    stores_private_key_bytes: boolean;
    host_key_verification: string;
  };
  caps?: {
    ariadne_campaign_live?: boolean;
    [key: string]: unknown;
  };
  services: {
    bridge: {
      managed?: boolean;
      state?: string;
      age_s?: number | null;
      detail?: string;
      managed_start_available?: boolean;
      availability_reason?: string;
    };
    ollama: {
      mode: string;
      endpoint: string;
      physical_target?: string;
      observed?: boolean;
      reachable: boolean;
      last_error?: string;
      tunnel_running?: boolean;
      local_process_running?: boolean;
      managed_start_available?: boolean;
      remote_ssh_available?: boolean;
      availability_reason?: string;
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function optionalFieldIs(
  value: Record<string, unknown>,
  key: string,
  predicate: (candidate: unknown) => boolean
): boolean {
  return value[key] === undefined || predicate(value[key]);
}

function desktopEnvelopeOf(value: unknown): DesktopEnvelope {
  if (!isRecord(value)) {
    throw new Error('Desktop-Backend antwortete in einem ungültigen Format.');
  }
  return value as DesktopEnvelope;
}

function desktopWriteOutcomeUncertain(error: unknown): boolean {
  if (!(error instanceof ApiError)) return true;
  return (
    error.kind === 'network'
    || error.kind === 'timeout'
    || (error.kind === 'http' && error.status >= 500)
  );
}

function desktopSnapshotOf(value: unknown, missingMessage: string): DesktopSnapshot {
  if (!isRecord(value)) throw new Error(missingMessage);

  const config = value.config;
  const credentials = value.credential_policy;
  const services = value.services;
  if (!isRecord(config) || !isRecord(credentials) || !isRecord(services)) {
    throw new Error('Desktop-Backend meldete unvollständige Einstellungen.');
  }

  const bridge = config.bridge;
  const ollama = config.ollama;
  const bridgeService = services.bridge;
  const ollamaService = services.ollama;
  if (
    !isRecord(bridge)
    || typeof bridge.auto_start !== 'boolean'
    || !isRecord(ollama)
    || !['local', 'remote_ssh'].includes(String(ollama.mode))
    || typeof ollama.auto_start !== 'boolean'
    || typeof ollama.model !== 'string'
    || typeof ollama.local_host !== 'string'
    || !isRecord(ollama.remote)
    || !isRecord(bridgeService)
    || !isRecord(ollamaService)
  ) {
    throw new Error('Desktop-Backend meldete unvollständige Verbindungsdaten.');
  }

  const remote = ollama.remote;
  if (
    typeof remote.host !== 'string'
    || typeof remote.user !== 'string'
    || typeof remote.port !== 'number'
    || typeof remote.identity_file !== 'string'
    || typeof remote.host_key_fingerprint !== 'string'
    || typeof remote.local_port !== 'number'
    || typeof remote.remote_port !== 'number'
    || !['systemd', 'windows', 'none'].includes(String(remote.start_method))
    || typeof remote.trust_remote_host !== 'boolean'
    || typeof value.config_path !== 'string'
    || !optionalFieldIs(value, 'settings_update_contract', (candidate) => typeof candidate === 'string')
    || !optionalFieldIs(value, 'caps', (candidate) => (
      isRecord(candidate)
      && optionalFieldIs(candidate, 'ariadne_campaign_live', (flag) => typeof flag === 'boolean')
    ))
    || typeof credentials.ssh_key_only !== 'boolean'
    || typeof credentials.stores_passwords !== 'boolean'
    || typeof credentials.stores_private_key_bytes !== 'boolean'
    || typeof credentials.host_key_verification !== 'string'
    || !optionalFieldIs(bridgeService, 'managed', (candidate) => typeof candidate === 'boolean')
    || !optionalFieldIs(bridgeService, 'state', (candidate) => typeof candidate === 'string')
    || !optionalFieldIs(bridgeService, 'age_s', (candidate) => candidate === null || typeof candidate === 'number')
    || !optionalFieldIs(bridgeService, 'detail', (candidate) => typeof candidate === 'string')
    || !optionalFieldIs(bridgeService, 'managed_start_available', (candidate) => typeof candidate === 'boolean')
    || !optionalFieldIs(bridgeService, 'availability_reason', (candidate) => typeof candidate === 'string')
    || typeof ollamaService.mode !== 'string'
    || typeof ollamaService.endpoint !== 'string'
    || typeof ollamaService.reachable !== 'boolean'
    || !optionalFieldIs(ollamaService, 'physical_target', (candidate) => typeof candidate === 'string')
    || !optionalFieldIs(ollamaService, 'observed', (candidate) => typeof candidate === 'boolean')
    || !optionalFieldIs(ollamaService, 'last_error', (candidate) => typeof candidate === 'string')
    || !optionalFieldIs(ollamaService, 'tunnel_running', (candidate) => typeof candidate === 'boolean')
    || !optionalFieldIs(ollamaService, 'local_process_running', (candidate) => typeof candidate === 'boolean')
    || !optionalFieldIs(ollamaService, 'managed_start_available', (candidate) => typeof candidate === 'boolean')
    || !optionalFieldIs(ollamaService, 'remote_ssh_available', (candidate) => typeof candidate === 'boolean')
    || !optionalFieldIs(ollamaService, 'availability_reason', (candidate) => typeof candidate === 'string')
    || !optionalFieldIs(ollamaService, 'host_key_pinned', (candidate) => typeof candidate === 'boolean')
    || !optionalFieldIs(value, 'config_error', (candidate) => typeof candidate === 'string')
    || !optionalFieldIs(value, 'startup_error', (candidate) => typeof candidate === 'string')
  ) {
    throw new Error('Desktop-Backend meldete ungültige Einstellungsfelder.');
  }

  return value as unknown as DesktopSnapshot;
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

function rebaseValue<T>(draft: T, previous: T, next: T): T {
  return Object.is(draft, previous) ? next : draft;
}

function rebaseConnectionDraft(
  draft: DesktopConfig,
  previous: DesktopConfig,
  next: DesktopConfig
): DesktopConfig {
  const rebased = cloneConfig(next);
  rebased.bridge = {
    ...rebased.bridge,
    auto_start: rebaseValue(draft.bridge.auto_start, previous.bridge.auto_start, next.bridge.auto_start)
  };
  rebased.ollama = {
    ...rebased.ollama,
    mode: rebaseValue(draft.ollama.mode, previous.ollama.mode, next.ollama.mode),
    auto_start: rebaseValue(draft.ollama.auto_start, previous.ollama.auto_start, next.ollama.auto_start),
    model: rebaseValue(draft.ollama.model, previous.ollama.model, next.ollama.model),
    local_host: rebaseValue(draft.ollama.local_host, previous.ollama.local_host, next.ollama.local_host),
    remote: {
      ...rebased.ollama.remote,
      host: rebaseValue(draft.ollama.remote.host, previous.ollama.remote.host, next.ollama.remote.host),
      user: rebaseValue(draft.ollama.remote.user, previous.ollama.remote.user, next.ollama.remote.user),
      port: rebaseValue(draft.ollama.remote.port, previous.ollama.remote.port, next.ollama.remote.port),
      identity_file: rebaseValue(
        draft.ollama.remote.identity_file,
        previous.ollama.remote.identity_file,
        next.ollama.remote.identity_file
      ),
      host_key_fingerprint: rebaseValue(
        draft.ollama.remote.host_key_fingerprint,
        previous.ollama.remote.host_key_fingerprint,
        next.ollama.remote.host_key_fingerprint
      ),
      local_port: rebaseValue(
        draft.ollama.remote.local_port,
        previous.ollama.remote.local_port,
        next.ollama.remote.local_port
      ),
      remote_port: rebaseValue(
        draft.ollama.remote.remote_port,
        previous.ollama.remote.remote_port,
        next.ollama.remote.remote_port
      ),
      start_method: rebaseValue(
        draft.ollama.remote.start_method,
        previous.ollama.remote.start_method,
        next.ollama.remote.start_method
      ),
      trust_remote_host: rebaseValue(
        draft.ollama.remote.trust_remote_host,
        previous.ollama.remote.trust_remote_host,
        next.ollama.remote.trust_remote_host
      )
    }
  };
  return rebased;
}

function connectionDraftChanged(
  draft: DesktopConfig | undefined,
  confirmed: DesktopConfig | undefined
): boolean {
  if (!draft || !confirmed) return false;
  return (
    JSON.stringify(draft.bridge) !== JSON.stringify(confirmed.bridge)
    || JSON.stringify(draft.ollama) !== JSON.stringify(confirmed.ollama)
  );
}

function normalizedConnectionSections(config: DesktopConfig) {
  const trim = (value: string) => value.trim();
  return {
    bridge: { auto_start: config.bridge.auto_start },
    ollama: {
      mode: config.ollama.mode,
      auto_start: config.ollama.auto_start,
      model: trim(config.ollama.model),
      local_host: trim(config.ollama.local_host).replace(/\/+$/, ''),
      remote: {
        host: trim(config.ollama.remote.host),
        user: trim(config.ollama.remote.user),
        port: config.ollama.remote.port,
        identity_file: trim(config.ollama.remote.identity_file),
        host_key_fingerprint: trim(config.ollama.remote.host_key_fingerprint),
        local_port: config.ollama.remote.local_port,
        remote_port: config.ollama.remote.remote_port,
        start_method: config.ollama.remote.start_method,
        trust_remote_host: config.ollama.remote.trust_remote_host
      }
    }
  };
}

function connectionIntentConfirmed(
  submitted: DesktopConfig,
  confirmed: DesktopConfig
): boolean {
  return JSON.stringify(normalizedConnectionSections(submitted))
    === JSON.stringify(normalizedConnectionSections(confirmed));
}

function validTcpPort(value: number, minimum = 1): boolean {
  return Number.isSafeInteger(value) && value >= minimum && value <= 65535;
}

function connectionValidationError(config: DesktopConfig | undefined): string {
  if (!config || config.ollama.mode !== 'remote_ssh') return '';
  if (!validTcpPort(config.ollama.remote.port)) {
    return 'Der SSH-Port muss eine ganze Zahl zwischen 1 und 65535 sein.';
  }
  if (!validTcpPort(config.ollama.remote.local_port, 1024)) {
    return 'Der lokale Tunnel-Port muss eine ganze Zahl zwischen 1024 und 65535 sein.';
  }
  if (!validTcpPort(config.ollama.remote.remote_port)) {
    return 'Der Remote-Ollama-Port muss eine ganze Zahl zwischen 1 und 65535 sein.';
  }
  return '';
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

function capIntentConfirmed(
  editor: CapEditor,
  periodUsd: number,
  maxCalls: number,
  confirmed: DesktopConfig
): boolean {
  const policy = capPolicyOf(confirmed);
  return Boolean(
    policy
    && policy.caps.mode === editor.mode
    && CAP_AXIS_ORDER.every((axis) => (
      policy.caps.configured[axis] === editor.configured[axis]
    ))
    && policy.budget.period_ceiling_usd === periodUsd
    && policy.budget.max_calls === maxCalls
  );
}

function rebaseCapEditor(editor: CapEditor, policy: CapPolicy): CapEditor {
  const previous = editor.baseline;
  const periodChanged = parsePositiveNumber(editor.periodUsdText) !== previous.budget.period_ceiling_usd;
  const callsChanged = parsePositiveInteger(editor.maxCallsText) !== previous.budget.max_calls;
  return {
    baseline: policy,
    mode: editor.mode !== previous.caps.mode ? editor.mode : policy.caps.mode,
    configured: Object.fromEntries(CAP_AXIS_ORDER.map((axis) => [
      axis,
      editor.configured[axis] !== previous.caps.configured[axis]
        ? editor.configured[axis]
        : policy.caps.configured[axis]
    ])) as CapConfigured,
    periodUsdText: periodChanged ? editor.periodUsdText : String(policy.budget.period_ceiling_usd),
    maxCallsText: callsChanged ? editor.maxCallsText : String(policy.budget.max_calls)
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

export function Settings({ open, onClose, project, brain, onBrain }: SettingsProps) {
  const [runtimes, setRuntimes] = useState<RuntimeRow[]>([]);
  const [env, setEnv] = useState<EnvStatusPayload | undefined>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [testing, setTesting] = useState<ReadonlySet<string>>(() => new Set());
  const [testResult, setTestResult] = useState<Record<string, string>>({});
  const [brainDraft, setBrainDraft] = useState(brain);
  const [generalNotice, setGeneralNotice] = useState('');
  const runtimeLoadRequest = useRef(0);
  const previousBrain = useRef(brain);

  const [desktop, setDesktop] = useState<DesktopSnapshot | undefined>();
  const desktopRef = useRef<DesktopSnapshot | undefined>(undefined);
  const [desktopDraft, setDesktopDraft] = useState<DesktopConfig | undefined>();
  const desktopDraftDirtyRef = useRef(false);
  const desktopOperation = useRef(0);
  const desktopBusyRef = useRef('');
  const [desktopLoadError, setDesktopLoadError] = useState('');
  const [desktopError, setDesktopError] = useState('');
  const [desktopNotice, setDesktopNotice] = useState('');
  const [desktopBusy, setDesktopBusy] = useState('');
  const [desktopLoading, setDesktopLoading] = useState(false);
  const [capEditor, setCapEditor] = useState<CapEditor | undefined>();
  const [capError, setCapError] = useState('');
  const [capNotice, setCapNotice] = useState('');
  const [capConfirmed, setCapConfirmed] = useState(false);
  const settingsRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const desktopDraftDirty = connectionDraftChanged(desktopDraft, desktop?.config);
  const desktopWritesSupported = desktop?.settings_update_contract === DESKTOP_SETTINGS_UPDATE_CONTRACT;
  const generalDirty = brainDraft !== brain;
  const brainDraftVerificationPending = (
    brainDraft !== brain
    && brainDraft !== ''
    && (!loaded || loading)
  );
  const brainDraftVerificationFailed = (
    brainDraft !== brain
    && brainDraft !== ''
    && !loading
    && Boolean(error)
  );
  const brainDraftNeedsVerification = brainDraftVerificationPending || brainDraftVerificationFailed;
  const brainDraftValid = (
    brainDraft === brain
    || brainDraft === ''
    || (
      loaded
      && !loading
      && !error
      && runtimes.some((runtime) => runtime.available && runtime.id === brainDraft)
    )
  );
  const connectionError = connectionValidationError(desktopDraft);

  const adoptDesktop = useCallback((value: DesktopSnapshot | undefined) => {
    desktopRef.current = value;
    setDesktop(value);
  }, []);

  const load = useCallback(async () => {
    const request = ++runtimeLoadRequest.current;
    setLoading(true);
    setError('');
    try {
      const [rt, e] = await Promise.all([getRuntimeStatus(), getEnvStatus()]);
      if (request !== runtimeLoadRequest.current) return;
      setRuntimes(rt.runtimes || []);
      setEnv(e.env);
    } catch (e) {
      if (request !== runtimeLoadRequest.current) return;
      setError(e instanceof Error ? e.message : 'Der Zustand der Laufzeiten konnte nicht gelesen werden.');
    } finally {
      if (request === runtimeLoadRequest.current) {
        setLoading(false);
        setLoaded(true);
      }
    }
  }, []);

  const loadDesktop = useCallback(async (
    options: {
      preserveDirtyDraft?: boolean;
      preserveNotice?: boolean;
      preserveFeedback?: boolean;
      allowDuringBusy?: boolean;
      operation?: number;
    } = {}
  ): Promise<boolean> => {
    if (desktopBusyRef.current && !options.allowDuringBusy) return false;
    const request = options.operation ?? ++desktopOperation.current;
    if (request !== desktopOperation.current) return false;
    const mayPreserveDirtyDraft = options.preserveDirtyDraft === true;
    setDesktopLoadError('');
    if (!options.preserveFeedback) {
      setDesktopError('');
      setCapError('');
    }
    if (!options.preserveNotice) setDesktopNotice('');
    setCapNotice('');
    setCapConfirmed(false);
    setDesktopLoading(true);
    try {
      const payload = desktopEnvelopeOf(await getDesktopSettingsDocument());
      if (request !== desktopOperation.current) return false;
      const rawDesktop: unknown = payload.desktop;
      if (
        isRecord(rawDesktop)
        && typeof rawDesktop.config_error === 'string'
        && rawDesktop.config_error.trim()
      ) {
        throw new Error(`Desktop-Konfiguration ist ungültig: ${rawDesktop.config_error.trim()}`);
      }
      const nextDesktop = desktopSnapshotOf(rawDesktop, 'Desktop-Backend meldete keine Einstellungen.');
      const preserveDirtyDraft = mayPreserveDirtyDraft && desktopDraftDirtyRef.current;
      const previousConfirmed = desktopRef.current?.config;
      adoptDesktop(nextDesktop);
      if (preserveDirtyDraft) {
        setDesktopDraft((current) => {
          if (!current || !previousConfirmed) return cloneConfig(nextDesktop.config);
          return rebaseConnectionDraft(current, previousConfirmed, nextDesktop.config);
        });
      } else {
        setDesktopDraft(cloneConfig(nextDesktop.config));
      }
      setCapConfirmed(false);
      const canonicalPolicy = capPolicyOf(nextDesktop.config);
      if (!canonicalPolicy) {
        setCapEditor((prev) => (prev && capEditorChanged(prev) ? prev : undefined));
        setCapError('Dieses Desktop-Backend meldet keine gültige Ausführungs-Cap-Policy.');
      } else {
        setCapEditor((prev) => (
          prev && capEditorChanged(prev)
            ? rebaseCapEditor(prev, canonicalPolicy)
            : editorFromPolicy(canonicalPolicy)
        ));
      }
      return true;
    } catch (e) {
      if (request !== desktopOperation.current) return false;
      const preserveDirtyDraft = mayPreserveDirtyDraft && desktopDraftDirtyRef.current;
      if (!preserveDirtyDraft) {
        adoptDesktop(undefined);
        setDesktopDraft(undefined);
      }
      const detail = e instanceof Error
        ? e.message
        : 'Desktop-Serviceverwaltung ist in diesem Lauf nicht verfügbar.';
      setDesktopLoadError(`Desktop-Einstellungen konnten nicht geladen werden: ${detail}`);
      return false;
    } finally {
      if (request === desktopOperation.current) setDesktopLoading(false);
    }
  }, [adoptDesktop]);

  useEffect(() => {
    desktopDraftDirtyRef.current = desktopDraftDirty;
  }, [desktopDraftDirty]);

  useEffect(() => {
    const previous = previousBrain.current;
    previousBrain.current = brain;
    setBrainDraft((current) => (current === previous ? brain : current));
  }, [brain]);

  useEffect(() => {
    if (open) {
      void load();
      void loadDesktop({ preserveDirtyDraft: true });
    }
  }, [open, load, loadDesktop]);

  const applyGeneral = useCallback(() => {
    if (!generalDirty || !brainDraftValid) return;
    if (brainDraft !== brain) onBrain(brainDraft);
    setGeneralNotice('Brain wurde übernommen.');
  }, [brain, brainDraft, brainDraftValid, generalDirty, onBrain]);

  const discardGeneral = useCallback(() => {
    setBrainDraft(brain);
    setGeneralNotice('Nicht übernommene Auswahl verworfen.');
  }, [brain]);

  const runTest = useCallback(async (id: string) => {
    setTesting((prev) => new Set(prev).add(id));
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
      setTesting((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }, []);

  const patchBridge = useCallback((patch: Partial<DesktopConfig['bridge']>) => {
    setDesktopDraft((prev) => (
      prev ? { ...prev, bridge: { ...prev.bridge, ...patch } } : prev
    ));
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
    if (
      !desktop
      || !desktopDraft
      || !desktopDraftDirty
      || !desktopWritesSupported
      || desktopLoadError
      || connectionError
      || desktopLoading
      || desktopBusyRef.current
    ) return;
    const operation = ++desktopOperation.current;
    desktopBusyRef.current = 'save';
    setDesktopBusy('save');
    setDesktopError('');
    setDesktopNotice('');
    try {
      // The canonical owner merges these sections under its persistence lock.
      // Never replay an old caps/IDE snapshot from this connection editor.
      const payload = desktopEnvelopeOf(await putDesktopSettingsDocument({
        section_updates: {
          bridge: { ...desktopDraft.bridge },
          ollama: {
            ...desktopDraft.ollama,
            remote: { ...desktopDraft.ollama.remote }
          }
        }
      }));
      if (operation !== desktopOperation.current) return;
      const confirmedDesktop = desktopSnapshotOf(
        payload.desktop,
        'Desktop-Backend bestätigte die Einstellungen nicht.'
      );
      if (confirmedDesktop.settings_update_contract !== DESKTOP_SETTINGS_UPDATE_CONTRACT) {
        throw new Error('Desktop-Backend bestätigte den Vertrag für atomare Bereichs-Updates nicht.');
      }
      if (!connectionIntentConfirmed(desktopDraft, confirmedDesktop.config)) {
        throw new Error('Desktop-Backend bestätigte die angeforderten Verbindungsänderungen nicht.');
      }
      adoptDesktop(confirmedDesktop);
      setDesktopDraft(cloneConfig(confirmedDesktop.config));
      const canonicalPolicy = capPolicyOf(confirmedDesktop.config);
      if (canonicalPolicy) {
        setCapConfirmed(false);
        setCapEditor((prev) => (
          prev && capEditorChanged(prev)
            ? rebaseCapEditor(prev, canonicalPolicy)
            : editorFromPolicy(canonicalPolicy)
        ));
      }
      setDesktopNotice(
        confirmedDesktop.startup_error
          ? `Gespeichert. Autostart meldet: ${confirmedDesktop.startup_error}`
          : 'Gespeichert und auf den laufenden Desktop angewendet.'
      );
      void load();
    } catch (e) {
      if (operation !== desktopOperation.current) return;
      const detail = e instanceof Error ? e.message : 'Die Speicheranfrage wurde nicht eindeutig beantwortet.';
      if (!desktopWriteOutcomeUncertain(e)) {
        setDesktopError(`Speichern abgelehnt: ${detail}`);
        return;
      }
      const reconciled = await loadDesktop({
        preserveDirtyDraft: true,
        preserveNotice: true,
        preserveFeedback: true,
        allowDuringBusy: true,
        operation
      });
      if (operation !== desktopOperation.current) return;
      setDesktopError(
        reconciled
          ? `Speicherergebnis nicht eindeutig: ${detail} Der aktuelle Desktop-Stand wurde neu gelesen.`
          : `Speicherergebnis nicht eindeutig: ${detail} Ein bestätigender Desktop-Stand konnte nicht geladen werden.`
      );
    } finally {
      if (operation === desktopOperation.current) {
        desktopBusyRef.current = '';
        setDesktopBusy('');
      }
    }
  }, [adoptDesktop, connectionError, desktop, desktopDraft, desktopDraftDirty, desktopLoadError, desktopLoading, desktopWritesSupported, load, loadDesktop]);

  const discardDesktop = useCallback(() => {
    if (!desktop) return;
    const confirmed = cloneConfig(desktop.config);
    setDesktopDraft((current) => (
      current
        ? { ...current, bridge: confirmed.bridge, ollama: confirmed.ollama }
        : confirmed
    ));
    setDesktopError('');
    setDesktopNotice('Nicht gespeicherte Verbindungsänderungen verworfen.');
  }, [desktop]);

  const editCaps = useCallback((patch: Partial<Omit<CapEditor, 'baseline'>>) => {
    setCapEditor((prev) => (prev ? { ...prev, ...patch } : prev));
    setCapConfirmed(false);
    setCapError('');
    setCapNotice('');
  }, []);

  const discardCaps = useCallback(() => {
    if (!capEditor) return;
    setCapEditor(editorFromPolicy(capEditor.baseline));
    setCapConfirmed(false);
    setCapError('');
    setCapNotice('Nicht gespeicherte Cap- und Budgetänderungen verworfen.');
  }, [capEditor]);

  const saveCaps = useCallback(async () => {
    if (
      !desktop
      || !capEditor
      || !capPolicyOf(desktop.config)
      || !desktopWritesSupported
      || desktopLoadError
      || desktopLoading
      || desktopBusyRef.current
    ) return;
    const periodUsd = parsePositiveNumber(capEditor.periodUsdText);
    const maxCalls = parsePositiveInteger(capEditor.maxCallsText);
    if (periodUsd === undefined || maxCalls === undefined || !capEditorChanged(capEditor)) return;

    const widening = wideningReasons(capEditor);
    if (widening.length > 0 && !capConfirmed) return;

    const operation = ++desktopOperation.current;
    desktopBusyRef.current = 'caps-save';
    setDesktopBusy('caps-save');
    setCapError('');
    setCapNotice('');
    try {
      // Caps and budget form one consent owner. The backend merges this pair
      // under the same lock without replaying stale connection/IDE sections.
      const payload = desktopEnvelopeOf(await putDesktopSettingsDocument({
        section_updates: {
          caps: {
            mode: capEditor.mode,
            configured: { ...capEditor.configured },
            ...(widening.length > 0 ? { confirm_widening: true } : {})
          },
          budget: {
            period_ceiling_usd: periodUsd,
            max_calls: maxCalls
          }
        }
      }));
      if (operation !== desktopOperation.current) return;
      const confirmedDesktop = desktopSnapshotOf(
        payload.desktop,
        'Desktop-Backend bestätigte die Ausführungs-Cap-Policy nicht.'
      );
      if (confirmedDesktop.settings_update_contract !== DESKTOP_SETTINGS_UPDATE_CONTRACT) {
        throw new Error('Desktop-Backend bestätigte den Vertrag für atomare Bereichs-Updates nicht.');
      }
      if (!capIntentConfirmed(capEditor, periodUsd, maxCalls, confirmedDesktop.config)) {
        throw new Error('Desktop-Backend bestätigte die angeforderten Cap- und Budgetänderungen nicht.');
      }
      const canonicalPolicy = capPolicyOf(confirmedDesktop.config);
      if (!canonicalPolicy) throw new Error('Desktop-Backend gab keine gültige Ausführungs-Cap-Policy zurück.');

      adoptDesktop(confirmedDesktop);
      setDesktopDraft((prev) => {
        const next = prev
          ? rebaseConnectionDraft(prev, desktop.config, confirmedDesktop.config)
          : cloneConfig(confirmedDesktop.config);
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
      if (operation !== desktopOperation.current) return;
      const detail = e instanceof Error ? e.message : 'Die Speicheranfrage wurde nicht eindeutig beantwortet.';
      setCapConfirmed(false);
      if (!desktopWriteOutcomeUncertain(e)) {
        setCapError(`Speichern abgelehnt: ${detail}`);
        return;
      }
      const reconciled = await loadDesktop({
        preserveDirtyDraft: true,
        preserveNotice: true,
        preserveFeedback: true,
        allowDuringBusy: true,
        operation
      });
      if (operation !== desktopOperation.current) return;
      setCapError(
        reconciled
          ? `Speicherergebnis nicht eindeutig: ${detail} Der aktuelle Desktop-Stand wurde neu gelesen.`
          : `Speicherergebnis nicht eindeutig: ${detail} Ein bestätigender Desktop-Stand konnte nicht geladen werden.`
      );
    } finally {
      if (operation === desktopOperation.current) {
        desktopBusyRef.current = '';
        setDesktopBusy('');
      }
    }
  }, [adoptDesktop, capConfirmed, capEditor, desktop, desktopLoadError, desktopLoading, desktopWritesSupported, loadDesktop]);

  const serviceAction = useCallback(async (service: 'bridge' | 'ollama', verb: 'start' | 'stop' = 'start') => {
    if (desktopLoading || desktopBusyRef.current) return;
    if (desktopLoadError) {
      setDesktopNotice('');
      setDesktopError('Der Desktop-Stand ist nicht bestätigt. Bitte die Einstellungen zuerst erneut laden.');
      return;
    }
    if (desktopDraftDirtyRef.current) {
      setDesktopNotice('');
      setDesktopError(
        'Ungespeicherte Verbindungsänderungen: Bitte zuerst speichern, damit die Prüfung keinen veralteten Endpoint übernimmt.'
      );
      return;
    }
    const key = `${service}:${verb}`;
    const operation = ++desktopOperation.current;
    desktopBusyRef.current = key;
    setDesktopBusy(key);
    setDesktopError('');
    setDesktopNotice('');
    try {
      await runDesktopServiceAction(service, verb);
      if (operation !== desktopOperation.current) return;
      setDesktopNotice(
        service === 'bridge'
          ? 'Bridge läuft.'
          : verb === 'stop'
            ? 'Ollama-Tunnel beendet.'
            : 'Das bereits laufende lokale Ollama wurde geprüft und übernommen.'
      );
      desktopBusyRef.current = '';
      setDesktopBusy('');
      await loadDesktop({ preserveDirtyDraft: true, preserveNotice: true });
      void load();
    } catch (e) {
      if (operation !== desktopOperation.current) return;
      const detail = e instanceof Error ? e.message : 'Die Dienstaktion wurde nicht eindeutig beantwortet.';
      if (!desktopWriteOutcomeUncertain(e)) {
        setDesktopError(`Dienstaktion abgelehnt: ${detail}`);
        return;
      }
      const reconciled = await loadDesktop({
        preserveDirtyDraft: true,
        preserveNotice: true,
        preserveFeedback: true,
        allowDuringBusy: true,
        operation
      });
      if (operation !== desktopOperation.current) return;
      setDesktopError(
        reconciled
          ? `Ergebnis der Dienstaktion nicht eindeutig: ${detail} Der aktuelle Desktop-Stand wurde neu gelesen.`
          : `Ergebnis der Dienstaktion nicht eindeutig: ${detail} Ein bestätigender Desktop-Stand konnte nicht geladen werden.`
      );
    } finally {
      if (operation === desktopOperation.current) {
        desktopBusyRef.current = '';
        setDesktopBusy('');
      }
    }
  }, [desktopLoadError, desktopLoading, load, loadDesktop]);

  const handleBrainRadioKeyDown = useCallback((event: KeyboardEvent<HTMLDivElement>) => {
    if (!['ArrowRight', 'ArrowDown', 'ArrowLeft', 'ArrowUp', 'Home', 'End'].includes(event.key)) return;
    const radios = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>('button[role="radio"]:not(:disabled)')
    );
    if (radios.length === 0) return;
    const current = Math.max(0, radios.indexOf(event.target as HTMLButtonElement));
    let next = current;
    if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = radios.length - 1;
    else if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (current + 1) % radios.length;
    else next = (current - 1 + radios.length) % radios.length;
    event.preventDefault();
    radios[next].focus();
    radios[next].click();
  }, []);

  const reachable = runtimes.filter((r) => r.available);
  const reduced = useReducedMotionPref();
  const drawer = useMemo(() => drawerVariants(reduced), [reduced]);
  useDialogFocus(open, settingsRef, closeRef);

  const bridgeState = desktop?.services.bridge;
  const ollamaState = desktop?.services.ollama;
  const remoteMode = desktopDraft?.ollama.mode === 'remote_ssh';
  const localOllamaAdoptionAvailable = (
    !remoteMode
    && ollamaState?.managed_start_available === false
    && ollamaState.remote_ssh_available === false
  );
  const capPeriodUsd = capEditor ? parsePositiveNumber(capEditor.periodUsdText) : undefined;
  const capMaxCalls = capEditor ? parsePositiveInteger(capEditor.maxCallsText) : undefined;
  const capDirty = capEditor ? capEditorChanged(capEditor) : false;
  const capBaselineValid = Boolean(desktop && capPolicyOf(desktop.config));
  const capPolicyConfirmed = capBaselineValid && !desktopLoadError;
  const capWideningReasons = capEditor ? wideningReasons(capEditor) : [];
  const capEffective = capEditor ? effectiveCaps(capEditor.mode, capEditor.configured) : undefined;
  const disabledCapAxes = capEffective
    ? CAP_AXIS_ORDER.filter((axis) => !capEffective[axis])
    : [];
  const capSaveDisabled = (
    !desktop
    || !capEditor
      || !capBaselineValid
      || !desktopWritesSupported
    || capPeriodUsd === undefined
    || capMaxCalls === undefined
    || !capDirty
    || desktopBusy !== ''
    || desktopLoading
    || Boolean(desktopLoadError)
    || (capWideningReasons.length > 0 && !capConfirmed)
  );
  // React 18 drops `inert={true}` even though the current DOM typings expose
  // a boolean property. The empty-string presence form reaches the browser and
  // makes the still-mounted, animated drawer unfocusable while it is closed.
  const closedDrawerProps = !open ? { inert: '' as unknown as boolean } : {};

  return (
    <>
      {open && (
        <div
          className="settings-scrim"
          data-dialog-scrim=""
          aria-hidden="true"
          onMouseDown={(event) => {
            if (event.target !== event.currentTarget) return;
            // Closing during mousedown runs the focus-restoration cleanup
            // before the browser's default pointer focus step. Cancel that
            // step so it cannot move focus back to the document body.
            event.preventDefault();
            onClose();
          }}
        />
      )}
      <motion.aside
      ref={settingsRef}
      className={open ? 'settings open' : 'settings'}
      data-motion="drawer"
      variants={drawer}
      initial={false}
      animate={open ? 'open' : 'closed'}
      aria-hidden={!open}
      {...closedDrawerProps}
      role="dialog"
      aria-modal={open ? 'true' : undefined}
      aria-label="Einstellungen"
    >
      <header className="settings-head">
        <h2>Einstellungen</h2>
        <button ref={closeRef} type="button" className="settings-close" onClick={onClose} aria-label="Einstellungen schließen">
          ✕
        </button>
      </header>

      <div className="settings-body">
        <section className="settings-section">
          <div className="settings-title">Brain</div>
          <p className="settings-hint">
            Wer antwortet, wenn du Ikarus etwas fragst. Nur erreichbare Laufzeiten stehen zur Wahl.
          </p>
          <div
            className="choice-row"
            role="radiogroup"
            aria-label="Brain"
            onKeyDown={handleBrainRadioKeyDown}
          >
            <button
              type="button"
              role="radio"
              aria-checked={brainDraft === ''}
              tabIndex={
                brainDraft === ''
                || loading
                || Boolean(error)
                || !reachable.some((runtime) => runtime.id === brainDraft)
                  ? 0
                  : -1
              }
              className={brainDraft === '' ? 'on' : ''}
              onClick={() => {
                setBrainDraft('');
                setGeneralNotice('');
              }}
            >
              Automatisch
            </button>
            {reachable.map((r) => (
              <button
                key={r.id}
                type="button"
                role="radio"
                aria-checked={brainDraft === r.id}
                tabIndex={!loading && !error && brainDraft === r.id ? 0 : -1}
                className={brainDraft === r.id ? 'on' : ''}
                onClick={() => {
                  setBrainDraft(r.id);
                  setGeneralNotice('');
                }}
                disabled={loading || Boolean(error)}
              >
                {r.label || r.id}
              </button>
            ))}
            {brainDraft && !reachable.some((runtime) => runtime.id === brainDraft) && (
              <button type="button" role="radio" aria-checked className="on" tabIndex={-1} disabled>
                {brainDraft} (nicht erreichbar)
              </button>
            )}
          </div>
          {!loaded && <p className="settings-hint">Wird geprüft …</p>}
          {loaded && !loading && reachable.length === 0 && (
            <p className="settings-hint bad">
              Keine Laufzeit ist erreichbar. Ikarus antwortet dann aus dem lokalen Index — gemessen, aber ohne Modell.
            </p>
          )}
          <div className="settings-save-row general-settings-actions">
            <span
              className={`settings-hint ${brainDraftVerificationFailed || (!brainDraftValid && !brainDraftNeedsVerification) ? 'bad' : !generalDirty && generalNotice ? 'ok' : ''}`}
              role={brainDraftVerificationFailed || (!brainDraftValid && !brainDraftNeedsVerification) ? 'alert' : 'status'}
              aria-live="polite"
            >
              {brainDraftVerificationPending
                ? 'Die Erreichbarkeit des gewählten Brains wird noch bestätigt. Übernehmen ist bis dahin gesperrt.'
                : brainDraftVerificationFailed
                  ? 'Die Erreichbarkeit des gewählten Brains konnte nicht bestätigt werden. Prüfe die Laufzeiten erneut; Übernehmen bleibt gesperrt.'
                : !brainDraftValid
                  ? 'Der gewählte Brain ist nicht mehr erreichbar. Wähle einen erreichbaren Brain oder Automatisch.'
                : generalDirty
                  ? 'Der gewählte Brain ist noch nicht übernommen.'
                : generalNotice || 'Änderungen gelten erst nach dem Übernehmen.'}
            </span>
            <div className="settings-action-buttons">
              <button type="button" onClick={discardGeneral} disabled={!generalDirty}>
                Verwerfen
              </button>
              <button
                type="button"
                className="settings-primary"
                onClick={applyGeneral}
                disabled={!generalDirty || !brainDraftValid}
              >
                Brain übernehmen
              </button>
            </div>
          </div>
        </section>

        <TeamSettings project={project} enabled={open} />

        <SystemCapabilities project={project} enabled={open} />

        {/* What compute this machine can actually use. Read only while the
            panel is open: the shallow probe is cheap, but polling a closed
            panel would still be work nobody asked for. */}
        <ComputeSection enabled={open} />

        {/* What this interface may be built from, and what it may not copy.
            /api/catalogue had no caller; the licence traps it exists to catch
            were invisible. */}
        <CatalogueSection enabled={open} />

        <section className="settings-section" aria-labelledby="caps-settings-title">
          <div className="settings-title" id="caps-settings-title">Ausführungsgrenzen</div>
          <p className="settings-hint">
            Wähle den Master-Modus und die Daedalus-eigenen Ressourcenlimits für neu zugelassene Arbeit.
            Bereits ausgestellte Verträge werden nicht nachträglich geändert.
          </p>

          {desktopLoadError && (
            <div className="cap-load-state">
              <p className="settings-hint bad" role="alert">{desktopLoadError}</p>
              <button
                type="button"
                className="settings-refresh"
                onClick={() => void loadDesktop({ preserveDirtyDraft: true })}
                disabled={desktopLoading || desktopBusy !== ''}
              >
                Erneut laden
              </button>
            </div>
          )}
          {desktopLoading && !capEditor && !desktopLoadError && (
            <p className="settings-hint" role="status">Cap-Policy wird gelesen …</p>
          )}
          {!desktopLoading && !capEditor && !desktopLoadError && (
            <div className="cap-load-state">
              <p className="settings-hint bad" role="alert">
                {capError || 'Die Ausführungs-Cap-Policy ist nicht verfügbar.'}
              </p>
              <button
                type="button"
                className="settings-refresh"
                onClick={() => void loadDesktop({ preserveDirtyDraft: true })}
                disabled={desktopLoading || desktopBusy !== ''}
              >
                Erneut laden
              </button>
            </div>
          )}

          {capEditor && capEffective && (
            <div className="cap-card" aria-busy={desktopBusy === 'caps-save'}>
              {desktopLoading && <p className="settings-hint" role="status">Serverstand wird aktualisiert …</p>}
              {!desktopWritesSupported && (
                <p className="settings-hint bad" role="alert">
                  Dieses Desktop-Backend bestätigt keine atomaren Bereichs-Updates. Cap-Änderungen bleiben deshalb
                  lokal und können erst nach einem Backend-Update übernommen werden.
                </p>
              )}
              {!capPolicyConfirmed && (
                <p className="settings-hint bad" role="alert">
                  Server-Policy ist nicht bestätigt. Der angezeigte Entwurf ist nicht der aktuelle effektive
                  Stand; Laden, prüfen oder verwerfen ist nötig, bevor er gespeichert werden kann.
                </p>
              )}

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
                    {capPolicyConfirmed
                      ? 'Effektiver Zustand für neue Reservierungen, Missionen, Attempts, Leases, Provider-Aufrufe und Kampagnen.'
                      : 'Nicht bestätigter Entwurf; der aktuelle effektive Serverstand ist unbekannt.'}
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
                        disabled={desktopBusy !== '' || desktopLoading || !capPolicyConfirmed}
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
                            {capPolicyConfirmed ? 'Effektiv' : 'Entwurf'}: {capEffective[axis] ? 'aktiv' : 'aus'}
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
                            disabled={capEditor.mode !== 'custom' || desktopBusy !== '' || desktopLoading || !capPolicyConfirmed}
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
                              aria-invalid={capPeriodUsd === undefined}
                              aria-describedby={
                                capPeriodUsd === undefined
                                  ? 'cap-period-usd-help cap-period-usd-error'
                                  : 'cap-period-usd-help'
                              }
                              onChange={(event) => editCaps({ periodUsdText: event.target.value })}
                              disabled={desktopBusy !== '' || desktopLoading || !capPolicyConfirmed}
                            />
                            <small id="cap-period-usd-help">Bleibt positiv gespeichert, auch wenn diese Achse effektiv aus ist.</small>
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
                              aria-invalid={capMaxCalls === undefined}
                              aria-describedby={
                                capMaxCalls === undefined
                                  ? 'cap-max-calls-help cap-max-calls-error'
                                  : 'cap-max-calls-help'
                              }
                              onChange={(event) => editCaps({ maxCallsText: event.target.value })}
                              disabled={desktopBusy !== '' || desktopLoading || !capPolicyConfirmed}
                            />
                            <small id="cap-max-calls-help">Eine positive ganze Zahl; keine Null oder Großzahl als Unlimited-Sentinel.</small>
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
                      disabled={desktopBusy !== '' || desktopLoading || !capPolicyConfirmed}
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
                <p className="settings-hint bad" id="cap-period-usd-error" role="alert">Der USD-Fallback muss positiv und endlich sein.</p>
              )}
              {capMaxCalls === undefined && (
                <p className="settings-hint bad" id="cap-max-calls-error" role="alert">Der Aufruf-Fallback muss eine positive ganze Zahl sein.</p>
              )}
              {capError && <p className="settings-hint bad" role="alert">{capError}</p>}
              {capNotice && <p className="settings-hint cap-notice" role="status" aria-live="polite">{capNotice}</p>}

              <div className="settings-save-row cap-actions">
                <span className="settings-hint">Keine Grenze wird automatisch erhöht oder ausgeschaltet.</span>
                <div className="settings-action-buttons">
                  <button
                    type="button"
                    className="settings-refresh"
                    onClick={discardCaps}
                    disabled={!capDirty || desktopBusy !== '' || desktopLoading}
                  >
                    Verwerfen
                  </button>
                  <button
                    type="button"
                    className="settings-primary"
                    onClick={() => void saveCaps()}
                    disabled={capSaveDisabled}
                    aria-label="Cap-Policy speichern"
                  >
                    {desktopBusy === 'caps-save' ? 'Speichert …' : 'Cap-Policy speichern'}
                  </button>
                </div>
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
            {desktop?.caps?.ariadne_campaign_live === true ? (
              <>
                <b>Ariadne Campaign Workbench ist live</b>
                <p>
                  Der Workbench startet den kanonischen, kontrollierten Reparaturpfad. Er kann Kandidaten nur
                  nominieren; Apply, Merge und Promotion bleiben außerhalb dieses Pfads.
                </p>
              </>
            ) : desktop?.caps?.ariadne_campaign_live === false ? (
              <>
                <b>Ariadne-Campaign-Pfad ist nicht verfügbar</b>
                <p>Dieses Backend meldet keinen aktiven Campaign-Produzenten.</p>
              </>
            ) : (
              <>
                <b>Ariadne-Campaign-Status ist noch nicht bestätigt</b>
                <p>Die Desktop-Projektion wurde noch nicht gelesen; der Workbench erfindet daraus keinen Live-Status.</p>
              </>
            )}
          </div>
        </section>

        <section className="settings-section">
          <div className="settings-title">Dienste & Verbindungen</div>
          <p className="settings-hint">
            Der Desktop startet in v0.1.6 keine verwalteten Kindprozesse. Eine vorhandene Bridge und lokale
            Loopback-Dienste werden nur beobachtet oder übernommen; Remote-Ollama über SSH bleibt deaktiviert.
          </p>

          {!desktopDraft ? (
            desktopError ? (
              <p className="settings-hint bad" role="alert">{desktopError}</p>
            ) : desktopLoadError ? (
              <p className="settings-hint bad">Kein bestätigter Desktop-Stand. Bitte oben erneut laden.</p>
            ) : desktopLoading && !desktopLoadError ? (
              <p className="settings-hint">Desktop-Dienste werden gelesen …</p>
            ) : null
          ) : (
            <fieldset
              className="connection-stack"
              disabled={desktopLoading || desktopBusy !== ''}
              aria-busy={desktopLoading || desktopBusy === 'save'}
            >
              <div className="service-status">
                <div>
                  <b>Bridge</b>
                  <span className={bridgeState?.state === 'alive' || bridgeState?.state === 'busy' ? 'ok' : 'bad'}>
                    {bridgeState?.state || 'unbekannt'}
                  </span>
                </div>
                <button
                  type="button"
                  disabled
                  aria-label="Starten: Bridge — nicht verfügbar"
                >
                  Nicht verfügbar
                </button>
              </div>
              <p className="settings-hint">
                Der Desktop darf die Bridge in v0.1.6 nicht starten. Starte sie bei Bedarf explizit mit{' '}
                <code>{'python -m daedalus.file_bridge watch --project <registered-project>'}</code>.
              </p>

              <label className="settings-check">
                <input
                  type="checkbox"
                  checked={desktopDraft.bridge.auto_start}
                  onChange={(event) => patchBridge({ auto_start: event.target.checked })}
                  disabled
                />
                <span>
                  <b>Bridge automatisch starten — nicht verfügbar</b>
                  <small>Ein gespeicherter Altwert hat in v0.1.6 keine Startwirkung.</small>
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
                    disabled={desktopBusy !== '' || !localOllamaAdoptionAvailable}
                    aria-label="Prüfen und übernehmen: Ollama"
                  >
                    {desktopBusy === 'ollama:start' ? 'Prüft …' : 'Prüfen & übernehmen'}
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

              <p className="settings-hint">
                Daedalus startet keinen Ollama-Prozess. Die Aktion prüft und übernimmt ausschließlich ein bereits
                laufendes Ollama am bestätigten numerischen Loopback-Endpunkt.
              </p>

              <label className="settings-field">
                <span>Ollama-Modell</span>
                <input
                  value={desktopDraft.ollama.model}
                  onChange={(event) => patchOllama({ model: event.target.value })}
                  placeholder="qwen2.5-coder:7b"
                  disabled={remoteMode}
                />
              </label>

              <label className="settings-field">
                <span>Ollama läuft</span>
                <select
                  value={desktopDraft.ollama.mode}
                  onChange={(event) => patchOllama({ mode: event.target.value as DesktopConfig['ollama']['mode'] })}
                  aria-describedby="remote-ssh-unavailable"
                >
                  <option value="local">auf diesem Rechner</option>
                  <option value="remote_ssh" disabled>remote über SSH-Tunnel — nicht verfügbar</option>
                </select>
                <small id="remote-ssh-unavailable">
                  Remote über SSH ist in dieser Version nicht verfügbar: Der exakte Peer-/Fingerprint-Nachweis und
                  die Schlüsselverwahrung sind am Effekt-Gate noch nicht vollständig belegt. Lokales Ollama bleibt verfügbar.
                </small>
              </label>

              <label className="settings-check">
                <input
                  type="checkbox"
                  checked={desktopDraft.ollama.auto_start}
                  onChange={(event) => patchOllama({ auto_start: event.target.checked })}
                  disabled
                />
                <span>
                  <b>Ollama automatisch starten — nicht verfügbar</b>
                  <small>Ein gespeicherter Altwert hat in v0.1.6 keine Startwirkung.</small>
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
                <fieldset
                  className="remote-settings"
                  disabled
                  aria-label="Remote-SSH-Einstellungen — nicht verfügbar"
                >
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
                      aria-invalid={!validTcpPort(desktopDraft.ollama.remote.port)}
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
                      aria-invalid={!validTcpPort(desktopDraft.ollama.remote.local_port, 1024)}
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
                      aria-invalid={!validTcpPort(desktopDraft.ollama.remote.remote_port)}
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
                </fieldset>
              )}

              {ollamaState?.physical_target && (
                <p className="settings-hint">
                  Physisches Ziel der Egress-Policy: <code>{ollamaState.physical_target}</code>
                </p>
              )}
              {ollamaState?.last_error && !ollamaState.reachable && (
                <p className="settings-hint bad">{ollamaState.last_error}</p>
              )}
              {!desktopWritesSupported && (
                <p className="settings-hint bad" role="alert">
                  Dieses Desktop-Backend bestätigt keine atomaren Bereichs-Updates. Verbindungsänderungen bleiben
                  deshalb lokal und können erst nach einem Backend-Update übernommen werden.
                </p>
              )}
              {desktopError && <p className="settings-hint bad" role="alert">{desktopError}</p>}
              {connectionError && <p className="settings-hint bad" role="alert">{connectionError}</p>}
              {desktopNotice && <p className="settings-hint ok" role="status" aria-live="polite">{desktopNotice}</p>}
              {desktopLoadError && (
                <p className="settings-hint bad">
                  Dieser Entwurf bleibt erhalten, kann aber erst nach einem erfolgreichen Neuladen gespeichert werden.
                </p>
              )}
              {desktopDraftDirty && (
                <p className="settings-hint" role="status">
                  Verbindungsänderungen sind noch nicht gespeichert. Die Ollama-Prüfung verwendet erst den bestätigten Stand.
                </p>
              )}

              <div className="settings-save-row">
                <span className="settings-hint">
                  Verwaltete Starts und Remote-SSH: nicht verfügbar · lokales Ollama bleibt konfigurierbar
                </span>
                <div className="settings-action-buttons">
                  <button
                    type="button"
                    onClick={discardDesktop}
                    disabled={!desktopDraftDirty || desktopLoading || desktopBusy !== ''}
                  >
                    Verwerfen
                  </button>
                  <button
                    type="button"
                    className="settings-primary"
                    onClick={() => void saveDesktop()}
                    disabled={!desktopDraftDirty || remoteMode || !desktopWritesSupported || desktopLoading || desktopBusy !== '' || Boolean(desktopLoadError) || Boolean(connectionError)}
                    aria-label="Verbindungen speichern"
                  >
                    {desktopBusy === 'save' ? 'Speichert …' : 'Verbindungen speichern'}
                  </button>
                </div>
              </div>
            </fieldset>
          )}
        </section>

        <section className="settings-section">
          <div className="settings-title">
            Erreichbarkeit
            <button
              type="button"
              className="settings-refresh"
              onClick={() => { void load(); void loadDesktop({ preserveDirtyDraft: true }); }}
              disabled={loading || desktopLoading || desktopBusy !== ''}
            >
              {loading ? 'Prüft …' : 'Neu prüfen'}
            </button>
          </div>
          {error && <p className="settings-hint bad" role="alert">{error}</p>}
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
                    <button
                      type="button"
                      onClick={() => void runTest(r.id)}
                      disabled={testing.has(r.id)}
                      aria-busy={testing.has(r.id)}
                      aria-label={`Testen: ${r.label || r.id}`}
                    >
                      {testing.has(r.id) ? '…' : 'Testen'}
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

      </div>
      </motion.aside>
    </>
  );
}
