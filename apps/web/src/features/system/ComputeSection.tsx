import { useCallback, useEffect, useState } from 'react';
import { ApiError, getAcceleratorStatus, type AcceleratorFramework, type AcceleratorPayload } from '@/shared/api';
import {
  FRAMEWORK_WORD,
  LANE_WORD,
  computeSummary,
  frameworkReading,
  frameworkTone,
  laneTone,
  sortLanes,
  wasDeepProbed
} from './accelerators';
import './compute.css';

/**
 * RECHENLAGE — what compute this machine can actually use.
 *
 * `/api/accelerators/status` has existed the whole time with no caller in this
 * cockpit. It is the only surface that can answer "will this run on the GPU",
 * and the module behind it is unusually careful: it separates visible hardware
 * from an installed backend from an applicable backend, and ships a `claims`
 * block stating that neither implication holds.
 *
 * This section draws all three levels and the claims. It adds no judgement of
 * its own — every state word, every "missing" item and every warning is a
 * field of the payload. See `./accelerators.ts` for the reading rules.
 *
 * THE DEEP PROBE IS A BUTTON, NOT A DEFAULT. `?deep=1` imports torch, cupy,
 * warp and friends to ask each whether CUDA really works. That is seconds of
 * work and real imports, so it happens when a person asks for it. The shallow
 * answer is labelled as shallow rather than quietly presented as a result.
 */

function Reading({ name, row }: { name: string; row: AcceleratorFramework }) {
  const reading = frameworkReading(row);
  return (
    <li className={`compute-fw ${frameworkTone(reading)}`}>
      <span className={`dot ${frameworkTone(reading)}`} aria-hidden="true" />
      <span className="compute-fw-name">{name}</span>
      <span className="compute-fw-state">{FRAMEWORK_WORD[reading]}</span>
      {/* The backend's own explanation, including "deep probe not requested" —
          which is the honest reason this row says nothing yet. */}
      {row.detail && <span className="compute-fw-detail">{row.detail}</span>}
    </li>
  );
}

export function ComputeSection({ enabled }: { enabled: boolean }) {
  const [payload, setPayload] = useState<AcceleratorPayload | undefined>();
  const [error, setError] = useState<string>('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (deep: boolean) => {
    setBusy(true);
    try {
      setPayload(await getAcceleratorStatus(deep));
      setError('');
    } catch (err) {
      // A failed read is a fact. It never becomes an empty inventory.
      setError(err instanceof ApiError ? `${err.kind}: ${err.message}` : String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (enabled) void load(false);
  }, [enabled, load]);

  const snapshot = payload?.accelerators;
  const deep = wasDeepProbed(payload);

  return (
    <section className="settings-section" aria-labelledby="compute-title">
      <div className="settings-title" id="compute-title">Rechenlage</div>
      <p className="settings-hint">{computeSummary(payload)}</p>

      {error && (
        <p className="settings-hint bad" role="alert">
          Die Rechenlage konnte nicht gelesen werden: {error}. Das ist nicht dasselbe wie „keine Beschleuniger“.
        </p>
      )}
      {!error && !snapshot && <p className="settings-hint" role="status">Rechenlage wird gelesen …</p>}

      {snapshot && (
        <div className="compute">
          {/* 1 — visible hardware. */}
          {snapshot.hardware.available ? (
            <ul className="compute-devices">
              {snapshot.hardware.devices.map((device, i) => (
                <li key={`${device.name}-${i}`}>
                  <span className="compute-dev-name">{device.name}</span>
                  <span>Compute {device.compute_capability}</span>
                  <span>{Math.round(device.memory_mib / 1024)} GiB</span>
                  <span>Treiber {device.driver_version}</span>
                </li>
              ))}
              {snapshot.hardware.devices.length === 0 && (
                <li className="settings-hint">nvidia-smi antwortete, nannte aber kein Gerät.</li>
              )}
            </ul>
          ) : (
            <p className="settings-hint">
              Keine NVIDIA-Hardware sichtbar{snapshot.hardware.error ? `: ${snapshot.hardware.error}` : '.'}
            </p>
          )}

          {/* 2 — installed backends. The shallow answer says it is shallow. */}
          <div className="compute-head">
            <span>Backends</span>
            {!deep && <span className="compute-shallow">nicht geprüft — flache Antwort</span>}
            <button type="button" className="settings-refresh" onClick={() => void load(true)} disabled={busy}>
              {busy ? 'Läuft …' : 'Tief prüfen'}
            </button>
          </div>
          <ul className="compute-fws">
            {Object.entries(snapshot.frameworks).map(([name, row]) => (
              <Reading key={name} name={name} row={row} />
            ))}
          </ul>

          {/* 3 — applicable lanes, with what each one is missing. */}
          <ul className="compute-lanes">
            {sortLanes(snapshot.lanes).map((lane) => (
              <li key={lane.id} className={`compute-lane ${laneTone(lane.state)}`}>
                <span className="compute-lane-head">
                  <span className={`dot ${laneTone(lane.state)}`} aria-hidden="true" />
                  <span className="compute-lane-name">{lane.label}</span>
                  <span className="compute-lane-state">{LANE_WORD[lane.state] || lane.state}</span>
                </span>
                {lane.applicable_to.length > 0 && (
                  <span className="compute-lane-for">für {lane.applicable_to.join(', ')}</span>
                )}
                {lane.missing.length > 0 && (
                  <span className="compute-lane-missing">fehlt: {lane.missing.join(', ')}</span>
                )}
                {lane.evidence.length > 0 && (
                  <span className="compute-lane-evidence">Beleg: {lane.evidence.join(', ')}</span>
                )}
                {/* The semantic caveat. Without it a reader could take
                    "einsatzbereit" for "and it is the right tool". */}
                {lane.warning && <span className="compute-lane-warn">{lane.warning}</span>}
              </li>
            ))}
          </ul>

          {/* Remote compute: unknown is not offline. */}
          {snapshot.remote_compute.configured ? (
            <p className="settings-hint">
              Entfernte Rechenleistung {snapshot.remote_compute.target}:{' '}
              {snapshot.remote_compute.available === true
                ? 'erreichbar'
                : snapshot.remote_compute.available === false
                  ? `nicht erreichbar${snapshot.remote_compute.error ? ` — ${snapshot.remote_compute.error}` : ''}`
                  : 'nicht geprüft'}
            </p>
          ) : (
            <p className="settings-hint">
              Keine entfernte Rechenleistung konfiguriert. {snapshot.remote_compute.hint}
            </p>
          )}

          {/* The claims block, verbatim in meaning. This is the reason the
              three levels above are drawn separately at all. */}
          <ul className="compute-claims">
            {snapshot.claims.hardware_visible_is_not_backend_ready && (
              <li>Sichtbare Hardware bedeutet nicht, dass ein Backend bereit ist.</li>
            )}
            {snapshot.claims.backend_ready_is_not_semantic_validity && (
              <li>Ein bereites Backend bedeutet nicht, dass das Verfahren fachlich gültig ist.</li>
            )}
            {snapshot.claims.dlss_general_tensor_backend === false && (
              <li>DLSS ist kein allgemeines Tensor-Backend und wird hier nicht als eines geführt.</li>
            )}
          </ul>
        </div>
      )}
    </section>
  );
}
