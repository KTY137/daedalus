import { useEffect, useRef, useState, type FormEvent } from 'react';
import {
  startAriadne,
  type AriadneCampaignReceipt
} from '@/shared/api';
import {
  ARIADNE_TEXT_MAX_CHARACTERS,
  ariadneArmRows,
  ariadneDigestRows,
  ariadneIdentityFor,
  ariadneRequestFor,
  ariadneRequestSignature,
  ariadneStatusLabel,
  ariadneStatusTone,
  isAriadneCampaignReceipt,
  type AriadneFormValues,
  type AriadneRequestIdentity
} from './model';
import './ariadne.css';

export interface AriadneWorkbenchProps {
  project: string;
  sourceRevision: string;
  hidden?: boolean;
}

interface BoundValue<T> {
  binding: string;
  value: T;
}

interface RequestClaim {
  binding: string;
  token: symbol;
}

export function AriadneWorkbench({
  project,
  sourceRevision,
  hidden = false
}: AriadneWorkbenchProps) {
  const binding = JSON.stringify([project, sourceRevision]);
  const [targetPath, setTargetPath] = useState('');
  const [before, setBefore] = useState('');
  const [after, setAfter] = useState('');
  const [boundReceipt, setBoundReceipt] = useState<BoundValue<AriadneCampaignReceipt>>();
  const [boundPending, setBoundPending] = useState<BoundValue<boolean>>();
  const [boundError, setBoundError] = useState<BoundValue<string>>();
  const [boundIdentity, setBoundIdentity] = useState<BoundValue<AriadneRequestIdentity>>();
  const identityRef = useRef<BoundValue<AriadneRequestIdentity> | undefined>(undefined);
  const requestClaim = useRef<RequestClaim | null>(null);
  const targetInput = useRef<HTMLInputElement>(null);
  const previousBinding = useRef({ project, sourceRevision });
  const activeIdentity = identityRef.current?.binding === binding
    ? identityRef.current.value
    : undefined;
  const receipt = boundReceipt?.binding === binding && activeIdentity
    ? boundReceipt.value
    : undefined;
  const pending = Boolean(
    boundPending?.binding === binding
    && boundPending.value
    && requestClaim.current?.binding === binding
  );
  const error = boundError?.binding === binding ? boundError.value : '';
  const identity = boundIdentity?.binding === binding && boundIdentity.value === activeIdentity
    ? boundIdentity.value
    : undefined;

  useEffect(() => {
    if (!hidden) targetInput.current?.focus({ preventScroll: true });
  }, [hidden]);

  useEffect(() => {
    const previous = previousBinding.current;
    if (previous.project === project && previous.sourceRevision === sourceRevision) return;
    previousBinding.current = { project, sourceRevision };
    if (requestClaim.current?.binding !== binding) requestClaim.current = null;
    if (identityRef.current?.binding !== binding) identityRef.current = undefined;
    if (previous.project !== project) {
      setTargetPath('');
      setBefore('');
      setAfter('');
    }
  }, [binding, project, sourceRevision]);

  useEffect(() => {
    const current = identityRef.current?.binding === binding
      ? identityRef.current.value
      : undefined;
    if (!current) return;
    const signature = ariadneRequestSignature({ project, sourceRevision, targetPath, before, after });
    if (current.signature === signature) return;
    identityRef.current = undefined;
    setBoundIdentity(undefined);
    setBoundReceipt(undefined);
    setBoundError(undefined);
  }, [after, before, project, sourceRevision, targetPath]);

  useEffect(() => () => {
    requestClaim.current = null;
  }, []);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (pending || requestClaim.current?.binding === binding) return;

    const values: AriadneFormValues = {
      project,
      sourceRevision,
      targetPath,
      before,
      after
    };
    let nextIdentity: AriadneRequestIdentity;
    let request;
    try {
      const currentIdentity = identityRef.current?.binding === binding
        ? identityRef.current.value
        : undefined;
      nextIdentity = ariadneIdentityFor(values, currentIdentity);
      request = ariadneRequestFor(values, nextIdentity.campaignId);
    } catch (reason) {
      setBoundError({
        binding,
        value: reason instanceof Error ? reason.message : 'Die Reparaturangaben sind ungültig.'
      });
      return;
    }

    identityRef.current = { binding, value: nextIdentity };
    setBoundIdentity({ binding, value: nextIdentity });
    const claim = { binding, token: Symbol('ariadne-campaign') };
    requestClaim.current = claim;
    const isCurrent = () => requestClaim.current === claim;
    setBoundPending({ binding, value: true });
    setBoundError({ binding, value: '' });
    setBoundReceipt(undefined);
    try {
      const payload = await startAriadne(request);
      if (!isCurrent()) return;
      if (
        !payload.ok
        || payload.project !== request.project
        || !isAriadneCampaignReceipt(payload.ariadne)
        || payload.ariadne.campaign_id !== request.campaign_id
        || payload.ariadne.source_revision !== request.source_revision
      ) {
        throw new Error('Das Backend hat keine vollständig gebundene Ariadne-CampaignReceipt gemeldet.');
      }
      setBoundReceipt({ binding, value: payload.ariadne });
    } catch (reason) {
      if (!isCurrent()) return;
      setBoundError({
        binding,
        value: reason instanceof Error ? reason.message : 'Ariadne konnte die Kampagne nicht abschließen.'
      });
    } finally {
      if (!isCurrent()) return;
      requestClaim.current = null;
      setBoundPending({ binding, value: false });
    }
  };

  const unavailable = !project || !sourceRevision;
  return (
    <main
      className="cockpit-body ariadne"
      aria-label="Ariadne Campaign Workbench"
      hidden={hidden}
      inert={hidden ? ('' as unknown as boolean) : undefined}
    >
      <div className="ariadne-shell">
        <header className="ariadne-intro">
          <span className="ariadne-eyebrow">Kontrollierte Evolution</span>
          <h1>Eine Reparatur, drei gleich begrenzte Arme.</h1>
          <p>
            Ariadne vergleicht den unveränderten Stand, eine absichtlich falsche Negativkontrolle und die exakte
            Reparatur. Jeder ausgeführte Ausgang bleibt mit Kandidat und Evidenz erhalten.
          </p>
        </header>

        <section className="ariadne-boundary" role="note" aria-label="Ariadne Autoritätsgrenze">
          <strong>Nur Nomination.</strong>
          <span>
            Dieser Workbench wendet keine Datei an, merged nichts und promotet nichts. Eine nominierte Reparatur ist
            ein prüfbarer CAS-Kandidat, keine Freigabe und keine Änderung des Checkouts.
          </span>
        </section>

        <div className="ariadne-workbench">
          <section className="ariadne-card ariadne-intake" aria-labelledby="ariadne-intake-title">
            <header className="ariadne-card-head">
              <span>Exact repair</span>
              <h2 id="ariadne-intake-title">Kampagne festlegen</h2>
            </header>

            <dl className="ariadne-binding">
              <div>
                <dt>Projekt</dt>
                <dd>{project || 'kein Projekt ausgewählt'}</dd>
              </div>
              <div>
                <dt>Git-HEAD</dt>
                <dd><code>{sourceRevision || 'nicht bestätigt'}</code></dd>
              </div>
              <div>
                <dt>Kampagnen-ID</dt>
                <dd><code>{identity?.campaignId || 'wird beim ersten Start erzeugt'}</code></dd>
              </div>
            </dl>

            {unavailable ? (
              <p className="ariadne-error" role="alert">
                Wähle ein erreichbares Git-Projekt mit bestätigtem HEAD, bevor du eine Kampagne startest.
              </p>
            ) : null}

            <form onSubmit={(event) => void submit(event)} aria-busy={pending}>
              <fieldset disabled={pending || unavailable}>
                <label>
                  <span>Relative Zieldatei</span>
                  <input
                    ref={targetInput}
                    value={targetPath}
                    onChange={(event) => setTargetPath(event.target.value)}
                    placeholder="src/example.py"
                    maxLength={1_024}
                    autoComplete="off"
                    required
                  />
                  <small>Nur diese eine UTF-8-Datei wird als isolierter Kandidat erfasst.</small>
                </label>

                <div className="ariadne-replacement">
                  <label>
                    <span>Bisheriger Text</span>
                    <textarea
                      value={before}
                      onChange={(event) => setBefore(event.target.value)}
                      placeholder="Muss im eingefrorenen Ziel exakt einmal vorkommen"
                      maxLength={ARIADNE_TEXT_MAX_CHARACTERS}
                      spellCheck={false}
                      required
                    />
                  </label>
                  <label>
                    <span>Neuer Text</span>
                    <textarea
                      value={after}
                      onChange={(event) => setAfter(event.target.value)}
                      placeholder="Darf leer sein, muss aber verschieden sein"
                      maxLength={ARIADNE_TEXT_MAX_CHARACTERS}
                      spellCheck={false}
                    />
                  </label>
                </div>

                <div className="ariadne-submit">
                  <p>
                    Ein Timeout verwirft die Identität nicht. Ein Retry mit denselben sechs Eingaben verwendet
                    dieselbe Kampagnen-ID und liest die kanonische Receipt erneut.
                  </p>
                  <button type="submit" disabled={pending || !targetPath.trim() || !before || before === after}>
                    {pending ? 'Kampagne läuft …' : 'Kampagne starten'}
                  </button>
                </div>
              </fieldset>
            </form>

            {error ? <p className="ariadne-error" role="alert">{error}</p> : null}
          </section>

          {pending ? (
            <section className="ariadne-card ariadne-waiting" role="status" aria-live="polite">
              <span className="ariadne-pulse" aria-hidden="true" />
              <h2>Die drei Arme werden seriell ausgewertet.</h2>
              <p>Die Ansicht darf wechseln; Anfrage und Kampagnen-ID bleiben in diesem Workbench gebunden.</p>
            </section>
          ) : receipt ? (
            <AriadneReceiptView receipt={receipt} />
          ) : (
            <AriadneArmPreview />
          )}
        </div>
      </div>
    </main>
  );
}

export function AriadneReceiptView({ receipt }: { receipt: AriadneCampaignReceipt }) {
  const arms = ariadneArmRows(receipt);
  const digests = ariadneDigestRows(receipt);
  const budget = receipt.budget_equality;
  return (
    <section className="ariadne-result" aria-labelledby="ariadne-result-title">
      <header className="ariadne-result-head">
        <div>
          <span className="ariadne-eyebrow">CampaignReceipt</span>
          <h2 id="ariadne-result-title">{receipt.campaign_id}</h2>
        </div>
        <span
          className="ariadne-status"
          data-tone={ariadneStatusTone(receipt.outcome)}
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          {ariadneStatusLabel(receipt.outcome)}
          <code>{receipt.outcome}</code>
        </span>
      </header>

      <div className="ariadne-arms" aria-label="Kampagnenarme">
        {arms.map((arm, index) => {
          const trial = arm.trial;
          const expected = trial && (
            (arm.id === 'repair' && trial.status === 'passed')
            || (arm.id !== 'repair' && trial.status === 'failed')
          );
          const tone = expected ? 'ok' : ariadneStatusTone(trial?.status || '');
          return (
            <article className="ariadne-arm" data-arm={arm.id} data-tone={tone} key={arm.id}>
              <header>
                <span>{index + 1}</span>
                <div>
                  <h3>{arm.label}</h3>
                  <p>{arm.purpose}</p>
                </div>
                <b>{ariadneStatusLabel(trial?.status || '')}</b>
              </header>
              {trial ? (
                <dl>
                  <div><dt>Seed</dt><dd>{trial.seed}</dd></div>
                  <div><dt>Kandidat</dt><dd><code>{trial.candidate_tree_sha256 || 'nicht erfasst'}</code></dd></div>
                  <div><dt>Evidenz</dt><dd><code>{trial.evidence_packet_sha256 || 'nicht erfasst'}</code></dd></div>
                  <div><dt>Budget</dt><dd><code>{trial.configured_budget_sha256 || 'nicht erfasst'}</code></dd></div>
                </dl>
              ) : (
                <p className="ariadne-arm-empty">Nicht ausgeführt; die terminale Receipt erfindet keinen Ausgang.</p>
              )}
              {trial?.negative_outcomes.length ? (
                <div className="ariadne-negative">
                  <b>Retained negative outcomes</b>
                  <ul>{trial.negative_outcomes.map((item) => <li key={item}>{item}</li>)}</ul>
                </div>
              ) : null}
              {trial?.blockers.length ? (
                <div className="ariadne-blockers">
                  <b>Blocker</b>
                  <ul>{trial.blockers.map((item) => <li key={item}>{item}</li>)}</ul>
                </div>
              ) : null}
            </article>
          );
        })}
      </div>

      <section className="ariadne-evidence" aria-labelledby="ariadne-evidence-title">
        <div className="ariadne-section-head">
          <div>
            <span>CAS-Kette</span>
            <h3 id="ariadne-evidence-title">Kandidat, Evidenz und Nominierung</h3>
          </div>
          <span>{digests.filter((row) => row.digest).length} / 3 belegt</span>
        </div>
        <ul>
          {digests.map((row) => (
            <li key={row.id}>
              <b>{row.label}</b>
              <code className={row.digest ? '' : 'missing'}>{row.digest || 'nicht ausgestellt'}</code>
              {row.locator ? <small>{row.locator}</small> : null}
            </li>
          ))}
        </ul>
      </section>

      <div className="ariadne-result-grid">
        <section className="ariadne-evidence">
          <div className="ariadne-section-head">
            <div><span>Negative Evidenz</span><h3>Alle Kampagnenausgänge</h3></div>
            <span>{receipt.negative_outcomes.length}</span>
          </div>
          {receipt.negative_outcomes.length ? (
            <ul className="ariadne-outcomes">
              {receipt.negative_outcomes.map((item) => <li key={item}>{item}</li>)}
            </ul>
          ) : (
            <p>Keine negativen Ausgänge gemeldet.</p>
          )}
          {receipt.blockers.length ? (
            <div className="ariadne-blockers">
              <b>Campaign-Blocker</b>
              <ul>{receipt.blockers.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          ) : null}
        </section>

        <section className="ariadne-evidence">
          <div className="ariadne-section-head">
            <div><span>Budgetvergleich</span><h3>Gleiche konfigurierte Grenzen</h3></div>
          </div>
          {budget ? (
            <dl className="ariadne-budget">
              <div><dt>Konfiguriert gleich</dt><dd>{budget.configured_equal ? 'ja' : 'nein'}</dd></div>
              <div><dt>Nutzung festgehalten</dt><dd>{budget.realized_usage_recorded ? 'ja' : 'nein'}</dd></div>
              <div><dt>Innerhalb Budget</dt><dd>{budget.within_budget ? 'ja' : 'nein'}</dd></div>
              <div><dt>Budget-Digest</dt><dd><code>{budget.configured_budget_sha256}</code></dd></div>
            </dl>
          ) : (
            <p>Für diesen terminalen Ausgang wurde kein vollständiger Gleichheitsnachweis ausgestellt.</p>
          )}
        </section>
      </div>

      <footer className="ariadne-nomination-boundary">
        <strong>{receipt.outcome === 'nominated' ? 'Nominiert, nicht übernommen.' : 'Keine Nominierung ausgestellt.'}</strong>
        <span>
          Kein Apply, kein Merge, keine Promotion. Der Checkout bleibt unverändert; eine spätere Übernahme braucht
          den separaten, owner-kontrollierten Freigabepfad.
        </span>
      </footer>
    </section>
  );
}

function AriadneArmPreview() {
  return (
    <section className="ariadne-card ariadne-preview" aria-labelledby="ariadne-preview-title">
      <header className="ariadne-card-head">
        <span>Frozen protocol</span>
        <h2 id="ariadne-preview-title">Was ausgeführt wird</h2>
      </header>
      <ol>
        {ariadneArmRows().map((arm) => (
          <li key={arm.id}>
            <b>{arm.label}</b>
            <span>{arm.purpose}</span>
          </li>
        ))}
      </ol>
      <p>
        Evaluator, Kommando, Laufzeitgrenze und Promotion sind bewusst keine Browser-Regler. Sie bleiben im
        kanonischen Backend eingefroren.
      </p>
    </section>
  );
}
