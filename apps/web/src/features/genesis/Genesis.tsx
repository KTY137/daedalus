import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import { startGenesis, type GenesisRun } from '@/shared/api';
import { fetchGenesisSourceArchive, genesisSourceDownload, saveGenesisSourceArchive } from './download';
import {
  createGenesisRequestKey,
  displayGenesisValue,
  genesisArtifactRows,
  genesisBlockers,
  genesisFactRows,
  genesisRequestFor,
  genesisStatusLabel,
  genesisStatusTone,
  isGenesisRun,
  previewUrlFrom,
  retainsGenesisRetryIdentity,
  safeGenesisPreviewUrl
} from './model';

interface RetryIdentity {
  signature: string;
  requestKey: string;
}

export function GenesisWorkspace({ hidden = false }: { hidden?: boolean }) {
  const [prompt, setPrompt] = useState('');
  const [target, setTarget] = useState('');
  const [stack, setStack] = useState('');
  const [run, setRun] = useState<GenesisRun>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const retryIdentity = useRef<RetryIdentity | undefined>(undefined);
  const promptInput = useRef<HTMLTextAreaElement>(null);
  /** React state cannot close a same-render double-submit window. */
  const requestClaim = useRef<symbol | null>(null);
  /** Invalidates every callback that outlives its owning request or mount. */
  const requestGeneration = useRef(0);

  useEffect(() => {
    if (!hidden) promptInput.current?.focus({ preventScroll: true });
  }, [hidden]);

  useEffect(() => () => {
    requestGeneration.current += 1;
    requestClaim.current = null;
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending || requestClaim.current !== null || !prompt.trim()) return;

    const claim = Symbol('genesis-request');
    requestClaim.current = claim;
    const generation = ++requestGeneration.current;
    const isCurrent = () => requestClaim.current === claim && requestGeneration.current === generation;

    try {
      // Request-key generation is part of taking this synchronous claim.
      // WebCrypto can be unavailable or throw before the first network await;
      // keeping it inside this try/finally prevents that failure from leaving
      // an invisible claim that refuses every later submit.
      const signature = JSON.stringify({ prompt: prompt.trim(), target: target.trim(), stack: stack.trim() });
      const requestKey = retryIdentity.current?.signature === signature
        ? retryIdentity.current.requestKey
        : createGenesisRequestKey();
      retryIdentity.current = { signature, requestKey };

      setPending(true);
      setError('');
      setRun(undefined);
      const payload = await startGenesis(genesisRequestFor(prompt, target, stack, requestKey));
      if (!isCurrent()) return;
      if (!payload.ok || !isGenesisRun(payload.genesis, requestKey)) {
        throw new Error('Das Backend hat keinen vollständigen Genesis-Lauf gemeldet.');
      }
      retryIdentity.current = retainsGenesisRetryIdentity(payload.genesis.status)
        ? { signature, requestKey }
        : undefined;
      setRun(payload.genesis);
    } catch (reason) {
      if (!isCurrent()) return;
      setError(reason instanceof Error ? reason.message : 'Genesis konnte nicht gestartet werden.');
    } finally {
      if (!isCurrent()) return;
      requestClaim.current = null;
      setPending(false);
    }
  };

  return (
    <main className="cockpit-body genesis" aria-label="Genesis" hidden={hidden}>
      <div className="genesis-shell">
        <header className="genesis-intro">
          <span className="genesis-eyebrow">Neues Produkt</span>
          <h1>Von der Idee zum isolierten Kandidaten.</h1>
          <p>
            Genesis baut lokale, offline nutzbare Ein-Personen-Listen für Aufgaben/Todos, Notizen, Inventar oder
            Sammlungen – und Kanban-Boards. Enthalten sind Titel/Details, Anlegen, Bearbeiten, Löschen sowie optional Suche.
            Listen lassen sich abhaken; Kanban-Karten wechseln zwischen Backlog, In Progress und Done.
          </p>
        </header>

        <div className="genesis-workbench">
          <section className="genesis-card genesis-intake" aria-labelledby="genesis-intake-title">
            <div className="genesis-card-head">
              <span>Intake</span>
              <h2 id="genesis-intake-title">Was soll entstehen?</h2>
            </div>
            <form onSubmit={(event) => void submit(event)} aria-busy={pending}>
              <label className="genesis-prompt">
                <span>Produktbeschreibung</span>
                <textarea
                  ref={promptInput}
                  value={prompt}
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder="Zum Beispiel: Eine lokale Aufgabenliste mit Suche"
                  aria-describedby="genesis-prompt-help"
                  required
                  maxLength={8_000}
                  disabled={pending}
                />
                <small id="genesis-prompt-help">
                  Für ein Board verwende „kanban board“ oder „kanban-board“ in der Beschreibung, zum Beispiel
                  „Build a local kanban board with search“. Kanban unterstützt Web und installierbare PWA; CLI unterstützt Listen.
                  Externe Dienste, Logins, native Pakete und andere Frameworks sind noch nicht verfügbar.
                </small>
              </label>

              <div className="genesis-fields">
                <label>
                  <span>Ziel <small>optional</small></span>
                  <select
                    value={target}
                    onChange={(event) => setTarget(event.target.value)}
                    disabled={pending}
                  >
                    <option value="">Backend-Default</option>
                    <option value="web">Web</option>
                    <option value="cli">CLI</option>
                    <option value="desktop">Desktop (installierbare PWA)</option>
                    <option value="mobile">Mobile (installierbare PWA)</option>
                  </select>
                </label>
                <label>
                  <span>Stack <small>optional</small></span>
                  <input
                    value={stack}
                    onChange={(event) => setStack(event.target.value)}
                    placeholder="python-stdlib, vanilla-js oder pwa"
                    maxLength={240}
                    disabled={pending}
                    autoComplete="off"
                  />
                </label>
              </div>

              <div className="genesis-submit">
                <p>Ohne Basis-Repository · nur terminale Belege werden wiedergegeben; blockierte/laufende Antworten behalten ihren Request-Key.</p>
                <button type="submit" disabled={pending || !prompt.trim()}>
                  {pending ? 'Genesis arbeitet …' : 'Genesis starten'}
                </button>
              </div>
            </form>

            {error && <p className="genesis-error" role="alert">{error}</p>}
          </section>

          {pending ? (
            <section className="genesis-card genesis-waiting" role="status" aria-live="polite">
              <span className="genesis-pulse" aria-hidden="true" />
              <h2>Der Lauf wird aufgebaut.</h2>
              <p>Die Antwort bleibt offen, bis das Backend den aktuellen Mission- und Artefaktstand bestätigt.</p>
            </section>
          ) : run ? (
            <GenesisRunView run={run} />
          ) : (
            <GenesisBoundary />
          )}
        </div>
      </div>
    </main>
  );
}

export function GenesisRunView({ run }: { run: GenesisRun }) {
  const blockers = genesisBlockers(run.blockers);
  const defaults = genesisFactRows(run.defaults, 'Default');
  const mission = genesisFactRows(run.mission, 'Mission');
  const artifacts = genesisArtifactRows(run);
  const previewReady = run.status === 'preview-ready';
  const previewUrl = previewReady
    ? safeGenesisPreviewUrl(run.preview, run.run_id)
    : undefined;
  const reportedPreviewUrl = previewReady ? previewUrlFrom(run.preview) : '';
  const tone = genesisStatusTone(run.status);
  const sourceDownload = genesisSourceDownload(run);

  return (
    <section className="genesis-result" aria-labelledby="genesis-result-title">
      <header className="genesis-result-head">
        <div>
          <span className="genesis-eyebrow">Genesis-Lauf</span>
          <h2 id="genesis-result-title">{run.run_id}</h2>
        </div>
        <span className="genesis-status" data-tone={tone} role="status" aria-live="polite" aria-atomic="true">
          <span className="genesis-status-dot" aria-hidden="true" />
          {genesisStatusLabel(run.status)}
          <code>{run.status || 'nicht gemeldet'}</code>
        </span>
      </header>

      <dl className="genesis-summary">
        <div>
          <dt>Ziel</dt>
          <dd>{displayGenesisValue(run.target)}</dd>
        </div>
        <div>
          <dt>Basis</dt>
          <dd>kein Repository</dd>
        </div>
      </dl>

      {sourceDownload && (
        <GenesisSourceArchive key={`${run.run_id}:${sourceDownload.candidateSha256}`} run={run} />
      )}

      <div className="genesis-result-grid">
        <GenesisFacts title="Verwendete Defaults" rows={defaults} empty="Keine Defaults gemeldet." />
        <section className={blockers.length ? 'genesis-section genesis-blockers has-items' : 'genesis-section genesis-blockers'}>
          <h3>Blocker</h3>
          {blockers.length ? (
            <ul>
              {blockers.map((blocker, index) => <li key={`${blocker}:${index}`}>{blocker}</li>)}
            </ul>
          ) : (
            <p>Keine Blocker gemeldet.</p>
          )}
        </section>
      </div>

      {mission.length > 0 && <GenesisFacts title="Mission" rows={mission} />}

      <section className="genesis-section genesis-artifacts">
        <div className="genesis-section-head">
          <h3>Artefakte</h3>
          <span>{artifacts.length}</span>
        </div>
        {artifacts.length ? (
          <ul>
            {artifacts.map((artifact) => (
              <li key={artifact.key}>
                <span className="genesis-artifact-kind">{artifact.label}</span>
                {artifact.digest ? (
                  <code className="genesis-digest" title={artifact.digest}>{artifact.digest}</code>
                ) : (
                  <span className="genesis-digest missing">Digest nicht gemeldet</span>
                )}
                {artifact.reference && (
                  <span className="genesis-reference">
                    Referenz <code>{artifact.reference}</code>
                  </span>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p>Noch keine Artefakte gemeldet.</p>
        )}
      </section>

      <section className="genesis-section genesis-preview">
        <div className="genesis-section-head">
          <h3>Isolierte Vorschau</h3>
          {previewUrl && <span>Loopback</span>}
        </div>
        {previewUrl ? (
          <iframe
            src={previewUrl}
            title={`Genesis-Vorschau ${run.run_id}`}
            sandbox="allow-scripts allow-forms"
            allow="camera 'none'; microphone 'none'; geolocation 'none'; clipboard-read 'none'; clipboard-write 'none'"
            referrerPolicy="no-referrer"
            loading="lazy"
            aria-describedby="genesis-preview-boundary"
          />
        ) : reportedPreviewUrl ? (
          <p className="genesis-preview-refused" role="alert">
            Die gemeldete Preview-URL wurde abgelehnt. Erlaubt ist nur der vom Backend für diesen Lauf bestätigte
            numerische HTTP-Loopback-Endpunkt mit Port.
          </p>
        ) : (
          <p>Noch keine sichere Preview-URL gemeldet.</p>
        )}
        {previewUrl && (
          <p id="genesis-preview-boundary">
            Sicherheitsisolierte Sicht: Änderungen bleiben nur bis zum Neuladen sichtbar; Browser-Speicher und Service
            Worker sind deaktiviert.
          </p>
        )}
      </section>
    </section>
  );
}

function GenesisSourceArchive({ run }: { run: GenesisRun }) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState('');
  const [downloadStarted, setDownloadStarted] = useState(false);
  const request = useRef<AbortController | null>(null);

  useEffect(() => () => {
    request.current?.abort();
    request.current = null;
  }, []);

  const download = async () => {
    if (request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setPending(true);
    setError('');
    setDownloadStarted(false);
    try {
      const archive = await fetchGenesisSourceArchive(run, controller.signal);
      if (request.current !== controller) return;
      saveGenesisSourceArchive(archive.blob, archive.filename);
      setDownloadStarted(true);
    } catch (reason) {
      if (request.current !== controller) return;
      setError(reason instanceof Error ? reason.message : 'Quellcode konnte nicht heruntergeladen werden.');
    } finally {
      if (request.current === controller) {
        request.current = null;
        setPending(false);
      }
    }
  };

  return (
    <section className="genesis-section genesis-source" aria-labelledby="genesis-source-title">
      <div className="genesis-section-head">
        <h3 id="genesis-source-title">Quellcode nutzen</h3>
        <span>ZIP</span>
      </div>
      <p>
        Entpacke das Archiv in einen neuen Ordner. Die Startanleitung steht in <code>source/README.md</code>;
        <code> source-tree.json</code> und <code>genesis-run.json</code> enthalten die Herkunftsnachweise.
      </p>
      <button type="button" onClick={() => void download()} disabled={pending} aria-busy={pending}>
        {pending ? 'Quellcode wird geladen …' : 'Quellcode herunterladen'}
      </button>
      <p role="status" aria-live="polite" aria-atomic="true">
        {pending ? 'Das Quellarchiv wird geprüft und geladen.'
          : downloadStarted ? 'Download an den Browser übergeben. Prüfe deinen Download-Ordner.' : ''}
      </p>
      {error && <p className="genesis-error" role="alert">{error}</p>}
      <p>
        Für die weitere Arbeit mit Ariadne: Initialisiere <code>source/</code> als Git-Projekt mit einem ersten Commit
        und registriere diesen Ordner über „Projekt hinzufügen“.
      </p>
    </section>
  );
}

function GenesisFacts({ title, rows, empty }: {
  title: string;
  rows: Array<{ label: string; value: string }>;
  empty?: string;
}) {
  return (
    <section className="genesis-section genesis-facts">
      <h3>{title}</h3>
      {rows.length ? (
        <dl>
          {rows.map((row, index) => (
            <div key={`${row.label}:${index}`}>
              <dt>{row.label}</dt>
              <dd>{row.value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        empty && <p>{empty}</p>
      )}
    </section>
  );
}

function GenesisBoundary() {
  return (
    <section className="genesis-card genesis-boundary" aria-labelledby="genesis-boundary-title">
      <div className="genesis-card-head">
        <span>Arbeitsgrenze</span>
        <h2 id="genesis-boundary-title">Ein neuer, überprüfbarer Kandidat.</h2>
      </div>
      <ol>
        <li><b>Absicht schließen</b><span>Fehlende Angaben werden als sichtbare Defaults zurückgegeben.</span></li>
        <li><b>Isoliert bauen</b><span>Die Quelle entsteht außerhalb eines bestehenden Produkt-Checkouts.</span></li>
        <li><b>Nachweise zeigen</b><span>Candidate, Evidenz und Round-trip bleiben über ihre Digests prüfbar.</span></li>
      </ol>
      <p className="genesis-boundary-note">Dieser Arbeitsbereich übernimmt oder veröffentlicht keinen Kandidaten.</p>
    </section>
  );
}
