import { HONESTY_DE, type OfferSubject } from './model';

/**
 * THE CONFIRM AFFORDANCE — what will actually run, before it runs.
 *
 * Ikarus proposing a task used to be two bare buttons: one click queued work
 * whose project, lane and objective were visible only behind the collapsed
 * Protokoll. This panel states them, in the exact shape the request will use
 * (`offerSubject` is the single derivation for both), and states the ceiling
 * that never changes — a nomination is not a promotion.
 *
 * Three rules this component exists to hold:
 *
 * 1. `requires_confirmation` is DESCRIPTIVE DATA, never this surface's
 *    authority. `false` does not auto-run anything; it earns a sentence
 *    saying the browser asks anyway.
 * 2. An action kind this cockpit has no endpoint for is drawn, not guessed.
 *    Nothing is sent and the primary control is disabled.
 * 3. A revision is a 40-character hex string or it is not a revision. A
 *    shortened or malformed value is reported as unreadable, never trimmed
 *    into something that looks canonical.
 */
export function OfferConfirm({
  subject,
  onAccept,
  onDecline
}: {
  subject: OfferSubject;
  onAccept: () => void;
  onDecline: () => void;
}) {
  return (
    <>
      <div className="offer-confirm">
        <dl>
          <dt>Aktion</dt>
          <dd>{subject.kind || 'nicht benannt'}</dd>
          <dt>Projekt</dt>
          <dd>{subject.project || 'nicht benannt'}</dd>
          <dt>Lane</dt>
          <dd>{subject.lane}</dd>
          <dt>Ziel</dt>
          <dd>{subject.objective || 'ohne Ziel'}</dd>
          <dt>Revision</dt>
          {subject.revisionState === 'valid' ? (
            <dd title={subject.sourceRevision}>{subject.sourceRevision!.slice(0, 12)}</dd>
          ) : subject.revisionState === 'unreadable' ? (
            <dd className="warn">unlesbar übermittelt</dd>
          ) : (
            <dd>nicht übermittelt</dd>
          )}
        </dl>
        <p className="offer-nomination">{HONESTY_DE.nomination}</p>
        {!subject.requiresConfirmation && <p className="offer-note">{HONESTY_DE.flagIgnored}</p>}
        {!subject.executable && (
          <p className="offer-note warn">
            {`Diese Oberfläche kennt für „${subject.kind || 'diese Aktion'}“ keinen Ausführungsweg. Nichts wurde gesendet.`}
          </p>
        )}
      </div>
      <div className="offer-acts" role="group" aria-label="Vorgeschlagene Aktion beantworten">
        <button type="button" className="primary" disabled={!subject.executable} onClick={onAccept}>
          Loslegen
        </button>
        <button type="button" onClick={onDecline}>
          Nicht jetzt
        </button>
      </div>
    </>
  );
}
