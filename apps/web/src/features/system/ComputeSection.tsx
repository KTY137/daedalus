import { useCallback, useEffect, useState } from 'react';
import { ApiError, getAcceleratorStatus, type AcceleratorFramework, type AcceleratorPayload } from '@/shared/api';
import {
  FRAMEWORK_WORD,
  LANE_WORD,
  computeSummary,
  frameworkReading,
  frameworkTone,
  laneTone,
  memoryText,
  sortLanes
} from './accelerators';
import './compute.css';

/**
 * RECHENLAGE — what compute this machine can actually use.
 *
 * `/api/accelerators/status` had no caller in this cockpit. It is the only
 * surface that can answer "will this run on the GPU", and the module behind it
 * separates visible hardware from an installed backend from an applicable
 * backend, then ships a `claims` block stating that neither implication holds.
 *
 * This section draws all three levels and the claims. It adds no judgement of
 * its own — every state word, every "missing" item and every warning is a
 * field of the payload. See `./accelerators.ts` for the reading rules.
 *
 * WHY THERE IS NO "DEEP PROBE" BUTTON.
 *
 * `?deep=1` makes the server run
 * `subprocess.run([sys.executable, "-c", _DEEP_PROBE], timeout=30)`, importing
 * torch, cupy, warp, cuvs, cugraph and newton. This section briefly offered a
 * button for it, and that was wrong: `do_GET` in
 * `daedalus/interfaces/http/read.py` carries no `effect_boundary` row, and the
 * same file says so explicitly twenty lines below, refusing to expose the
 * latent store on a GET because "a GET that opened a store would be an
 * undeclared effect". Spawning a 30-second subprocess is strictly more
 * effectful than opening a store, and CORS does not prevent a page from
 * ISSUING the request — only from reading the reply.
 *
 * The route is older than this surface, but a dead route is not an entrypoint;
 * a button is. Making it reachable would be "a new effectful entrypoint that
 * bypasses policy", which AGENTS.md classes as a release-blocking defect. So
 * the shallow read — a pure read, no subprocess — is all this section does,
 * and the deep answer waits for the route to move behind the effect boundary.
 * That is an owner decision and its own Work Packet, not a side effect of a
 * UI change.
 */

function Reading({ name, row }: { name: string; row: AcceleratorFramework }) {
  const reading = frameworkReading(row);
  return (
    <li className={`compute-fw ${frameworkTone(reading)}`}>
      <span className={`dot ${frameworkTone(reading)}`} aria-hidden="true" />
      <span className="compute-fw-name">{name}</span>
      <span className="compute-fw-state">{FRAMEWORK_WORD[reading]}</span>
      {/* The backend's own explanation, when it wrote one and it says
          something this row does not already. "deep probe not requested" is
          on every shallow row and is stated once in the header above; six
          copies of it would be noise, not evidence. A probed row with no
          detail at all is a fill-in, which the reading already refuses to
          call an absence. */}
      {row.detail && row.detail !== 'deep probe not requested' && (
        <span className="compute-fw-detail">{row.detail}</span>
      )}
    </li>
  );
}

export interface ComputeSectionProps {
  enabled: boolean;
  /** Injected so the loading, failure and staleness paths have a seam. */
  read?: typeof getAcceleratorStatus;
}

export function ComputeSection({ enabled, read = getAcceleratorStatus }: ComputeSectionProps) {
  const [payload, setPayload] = useState<AcceleratorPayload | undefined>();
  const [error, setError] = useState<string>('');

  const load = useCallback(async () => {
    try {
      setPayload(await read());
      setError('');
    } catch (err) {
      // A failed read is a fact. It never becomes an empty inventory — but it
      // also must not leave the previous answer looking current, so the
      // banner below is rendered ABOVE the retained rows and says they are
      // the older reading rather than this one.
      setError(err instanceof ApiError ? `${err.kind}: ${err.message}` : String(err));
    }
  }, [read]);

  useEffect(() => {
    if (enabled) void load();
  }, [enabled, load]);

  const snapshot = payload?.accelerators;
  const remote = snapshot?.remote_rtx_ollama;

  return (
    <section className="settings-section" aria-labelledby="compute-title">
      <div className="settings-title" id="compute-title">Rechenlage</div>
      <p className="settings-hint">{computeSummary(payload)}</p>

      {error && (
        <p className="settings-hint bad" role="alert">
          Die Rechenlage konnte nicht gelesen werden: {error}. Das ist nicht dasselbe wie „keine Beschleuniger“.
          {payload ? ' Was unten steht, ist der vorherige Stand und nicht dieser.' : ''}
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
                  <span>{memoryText(device.memory_mib)}</span>
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

          {/* 2 — backends. Nothing here was EXECUTED: this is a find_spec
              answer plus an open CUDA question, and it says so. */}
          <div className="compute-head">
            <span>Backends</span>
            <span className="compute-shallow">nur Import geprüft, nichts ausgeführt</span>
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
                {/* The semantic caveat. Without it "einsatzbereit" reads as
                    "and it is the right tool for this". */}
                {lane.warning && <span className="compute-lane-warn">{lane.warning}</span>}
              </li>
            ))}
          </ul>

          {/* A configured remote model endpoint, and above all its warning.
              The backend emits "remote endpoint uses plaintext HTTP; prefer a
              private tunnel or TLS" — a sentence a compute panel has no
              business swallowing. */}
          {remote?.configured && (
            <p className={`settings-hint ${remote.warning ? 'bad' : ''}`}>
              Entferntes Ollama {remote.endpoint || '(Endpunkt nicht gemeldet)'}:{' '}
              {remote.available ? `erreichbar, ${remote.models.length} Modelle` : `nicht erreichbar${remote.error ? ` — ${remote.error}` : ''}`}
              {remote.warning ? ` · ${remote.warning}` : ''}
            </p>
          )}

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
              three levels above are drawn separately at all. Any claim this
              interface does not recognise is shown raw rather than dropped:
              silently swallowing an anti-laundering assertion is the wrong
              failure mode for an anti-laundering block. */}
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
            {Object.entries(snapshot.claims)
              .filter(([key]) => ![
                'hardware_visible_is_not_backend_ready',
                'backend_ready_is_not_semantic_validity',
                'dlss_general_tensor_backend'
              ].includes(key))
              .map(([key, value]) => (
                <li key={key} className="compute-claim-raw">
                  <code>{key}</code> = {String(value)}
                </li>
              ))}
          </ul>

          {/* The hardware read is `@lru_cache(maxsize=1)` on the server and
              carries no probe timestamp, so this cannot be dated. Saying so is
              cheaper than implying it is live. */}
          <p className="settings-hint">
            Die Hardware-Abfrage wird serverseitig zwischengespeichert und meldet keinen Messzeitpunkt; sie kann
            älter sein als diese Anzeige. Die Backend-Zeile ist bei jedem Aufruf frisch geprüft.
          </p>
        </div>
      )}
    </section>
  );
}
