// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-License-Identifier: Apache-2.0

import { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { getEnvStatus, getRuntimeStatus, testRuntime, type EnvStatusPayload } from '../api';
import type { RuntimeRow } from '../types';
import { drawerVariants, useReducedMotionPref } from '../motion';
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

interface DesktopConfig {
  bridge: { auto_start: boolean };
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

export function Settings({ open, onClose, brain, onBrain, autonomy, onAutonomy, logSignal = 0 }: SettingsProps) {
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
    try {
      const payload = await desktopRequest('/api/desktop/settings');
      if (!payload.desktop) throw new Error('Desktop-Backend meldete keine Einstellungen.');
      setDesktop(payload.desktop);
      setDesktopDraft(cloneConfig(payload.desktop.config));
    } catch (e) {
      setDesktop(undefined);
      setDesktopDraft(undefined);
      setDesktopError(
        e instanceof Error
          ? e.message
          : 'Desktop-Serviceverwaltung ist in diesem Lauf nicht verfügbar.'
      );
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
          {autonomy === 'alles' && (
            <p className="settings-hint bad">
              Auf dieser Stufe schreibt jeder Entwurf ohne Klick in dein Repository — auch die mit gemeldeten Risiken.
            </p>
          )}
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
