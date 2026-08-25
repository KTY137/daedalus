import { useCallback, useEffect, useState } from 'react';
import { getEnvStatus, getRuntimeStatus, testRuntime, type EnvStatusPayload } from '../api';
import type { RuntimeRow } from '../types';
import {
  AUTONOMY_LEVELS,
  readAutonomyLog,
  type AutonomyEntry,
  type AutonomyLevel
} from './autonomy';
import './settings.css';

/**
 * Settings: which brain answers, how much may happen without a click, and what
 * is actually reachable.
 *
 * Four sections, and no fifth. The owner's constraint was "intelligent, nicht
 * zu overloaded", so this panel answers only the questions a person actually
 * asks of a running agent: who is thinking, what may it do alone, what can it
 * reach, and what did it already do by itself.
 *
 * The reachability table is a MEASUREMENT, not a badge wall. Every row shows
 * what the runtime registry reports — including the error text when a runtime
 * is not reachable — because "not configured" and "configured and broken" are
 * different problems with different fixes, and a green/grey dot cannot tell
 * them apart.
 */

export interface SettingsProps {
  open: boolean;
  onClose: () => void;
  brain: string;
  onBrain: (id: string) => void;
  autonomy: AutonomyLevel;
  onAutonomy: (level: AutonomyLevel) => void;
  /** bumped when something happened automatically, so the log re-reads */
  logSignal?: number;
}

function stateOf(r: RuntimeRow): { word: string; tone: 'ok' | 'warn' | 'bad' } {
  if (r.available) return { word: 'erreichbar', tone: 'ok' };
  if (r.auth_status === 'not_configured') return { word: 'kein Schlüssel', tone: 'warn' };
  return { word: 'nicht erreichbar', tone: 'bad' };
}

export function Settings({ open, onClose, brain, onBrain, autonomy, onAutonomy, logSignal = 0 }: SettingsProps) {
  const [runtimes, setRuntimes] = useState<RuntimeRow[]>([]);
  const [env, setEnv] = useState<EnvStatusPayload | undefined>();
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  /** false until the first attempt has finished, either way */
  const [loaded, setLoaded] = useState(false);
  const [testing, setTesting] = useState('');
  const [testResult, setTestResult] = useState<Record<string, string>>({});
  const [log, setLog] = useState<AutonomyEntry[]>([]);

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

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  useEffect(() => {
    setLog(readAutonomyLog());
  }, [open, logSignal]);

  const runTest = useCallback(async (id: string) => {
    setTesting(id);
    try {
      const payload = await testRuntime(id);
      setTestResult((prev) => ({
        ...prev,
        [id]: payload.test?.ok ? `antwortet · ${payload.test.detail || payload.test.mode}` : `fehlgeschlagen: ${payload.test?.detail || 'ohne Angabe'}`
      }));
    } catch (e) {
      setTestResult((prev) => ({ ...prev, [id]: `fehlgeschlagen: ${e instanceof Error ? e.message : 'unbekannt'}` }));
    } finally {
      setTesting('');
    }
  }, []);

  const reachable = runtimes.filter((r) => r.available);

  return (
    <aside className={open ? 'settings open' : 'settings'} aria-hidden={!open} aria-label="Einstellungen">
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
            Wer antwortet, wenn du Ikarus etwas fragst. Nur erreichbare Laufzeiten stehen zur Wahl — eine Liste, die
            nicht erreichbare Optionen anbietet, ist eine Liste, die lügt.
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
          <div className="settings-title">
            Erreichbarkeit
            <button type="button" className="settings-refresh" onClick={() => void load()} disabled={loading}>
              {loading ? 'Prüft …' : 'Neu prüfen'}
            </button>
          </div>
          {error && <p className="settings-hint bad">{error}</p>}
          <ul className="reach">
            {runtimes.map((r) => {
              const s = stateOf(r);
              return (
                <li key={r.id}>
                  <div className="reach-row">
                    <span className={`dot ${s.tone}`} aria-hidden="true" />
                    <span className="reach-name">{r.label || r.id}</span>
                    <span className={`reach-state ${s.tone}`}>{s.word}</span>
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
            {/* "not looked yet" is not "nothing there". The registry call takes
                seconds; until it lands this says what is actually true. */}
            {!loaded && <li className="settings-hint">Laufzeiten werden geprüft …</li>}
            {loaded && !loading && runtimes.length === 0 && (
              <li className="settings-hint">Keine Laufzeiten gemeldet.</li>
            )}
          </ul>
          {env && (
            <p className="settings-hint">
              Schlüssel bleiben auf deiner Maschine: die API gibt nur zurück, OB einer gesetzt ist, nie welcher.
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
    </aside>
  );
}
