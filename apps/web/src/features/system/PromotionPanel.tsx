import { useRef, useState } from 'react';
import { motion } from 'framer-motion';
import type { GovernanceGate, GovernancePayload } from '@/shared/contracts';
import { STATE_WORD, stateTone } from './promotion';
import { scrimVariants, surfaceVariants, useReducedMotionPref } from '@/shared/ui/motion';
import { useDialogFocus } from '@/shared/ui/useDialogFocus';

/**
 * PROMOTION — why not, in the system's own words.
 *
 * `/api/governance` answers the question the master plan makes central: may
 * this system promote anything right now, and why not. It carries a `verdict`
 * — a whole sentence naming the reason — a list of `blockers`, and for each
 * gate the QUESTION it asks, its state in the five-word vocabulary, its
 * provenance, and the evidence behind it. The status line rendered
 * "Promotion gesperrt · 2 Blocker" and dropped every word of the rest, so the
 * one thing a reader needs — which gate, and what would clear it — was the
 * one thing not on screen.
 *
 * THE REVISION IS PART OF THE VERDICT, not a footnote. Both blockers on this
 * machine today say the same thing in different words: the gate held at some
 * commit, and HEAD is not that commit. A verdict rendered without the two
 * revisions it compares is unfalsifiable, so `head` is drawn plainly.
 *
 * Nothing here decides anything. Promotion stays sealed behind explicit owner
 * approval; this only reads the refusal out loud.
 */

/** The vocabulary and the tone rule live with the chip that shares them. */
const tone = stateTone;

function short(revision: string | null | undefined): string {
  return revision ? revision.slice(0, 12) : 'unbekannt';
}

function Gate({ gate }: { gate: GovernanceGate }) {
  const [open, setOpen] = useState(false);
  const extra = gate;
  return (
    <li className={`gate-row ${tone(gate.state)}`}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="gate-head">
          <span className={`dot ${tone(gate.state)}`} aria-hidden="true" />
          <span className="gate-name">{gate.id}</span>
          <span className="gate-state">{STATE_WORD[gate.state] || gate.state}</span>
          {/* Where this verdict came from. An unlabelled gate result is a
              rumour, and the backend labels every one. */}
          <span className={`health-prov ${String(gate.provenance || '').toLowerCase()}`}>{gate.provenance || 'OHNE STEMPEL'}</span>
        </span>
        <span className="gate-question">{gate.question}</span>
        <span className="gate-headline">{gate.headline || 'Ohne Schlagzeile'}</span>
      </button>

      {open && (
        <div className="gate-detail">
          {gate.reason && <p className="health-remedy">{gate.reason}</p>}
          {/* N3: the gate's OWN revision, which is the other half of every
              "held at X, but HEAD is Y" refusal. The panel printed the current
              head and left the reader to take the prose on trust. */}
          {(() => {
            const detail = (gate.detail || {}) as Record<string, unknown>;
            const at = detail.measured_head ?? detail.head;
            const when = detail.measured_at;
            if (!at && !when) return null;
            return (
              <p className="health-remedy">
                Gemessen an <code>{at ? short(String(at)) : 'unbekannter Revision'}</code>
                {when ? ` · ${String(when)}` : ' · ohne Zeitstempel'}
              </p>
            );
          })()}
          {typeof extra.kill_rate_floor === 'number' && (
            <p className="health-remedy">Mindest-Trefferquote {extra.kill_rate_floor}</p>
          )}
          {extra.receipt_path && (
            <p className="health-remedy">
              Quittung <code>{extra.receipt_path}</code>
            </p>
          )}
          {/* N6: an allow-list under an `absent` confinement gate reads as
              though those paths were guarded. The gate just said they are
              not, so the list is labelled as the declaration it is. */}
          {gate.write_allow && gate.write_allow.length > 0 && (
            <div className="work-detail-list">
              <span>{gate.state === 'absent' ? 'Deklariert, nicht durchgesetzt' : 'Schreiben erlaubt'}</span>
              <ul>
                {gate.write_allow.slice(0, 8).map((path) => (
                  <li key={path}>
                    <code>{path}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {extra.high_risk_paths && extra.high_risk_paths.length > 0 && (
            <div className="work-detail-list">
              <span>Hochrisiko</span>
              <ul>
                {extra.high_risk_paths.slice(0, 8).map((path) => (
                  <li key={path}>
                    <code>{path}</code>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {gate.controls && gate.controls.length > 0 && (
            <ul className="gate-controls">
              {gate.controls.map((control) => (
                <li key={control.name}>
                  <span className="gate-control-name">{control.name}</span>
                  <span>{control.status}</span>
                  <span className="gate-control-effect">{control.effect}</span>
                </li>
              ))}
            </ul>
          )}
          {!gate.reason
            && !extra.receipt_path
            && !gate.write_allow?.length
            && !gate.controls?.length
            && !extra.high_risk_paths?.length && (
              <p className="health-remedy">Keine weiteren Angaben zu diesem Gate.</p>
            )}
        </div>
      )}
    </li>
  );
}

export interface PromotionPanelProps {
  open: boolean;
  onClose: () => void;
  governance?: GovernancePayload;
}

export function PromotionPanel({ open, onClose, governance }: PromotionPanelProps) {
  const reduced = useReducedMotionPref();
  /** Focus enters the dialog, is trapped, and returns — see useDialogFocus. */
  const closeRef = useRef<HTMLButtonElement>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);
  useDialogFocus(open, surfaceRef, closeRef);
  if (!open) return null;

  const blockers = governance?.blockers || [];
  const gates = governance?.gates || [];

  return (
    <motion.div
      className="palette-scrim"
      onClick={onClose}
      initial="closed"
      animate="open"
      exit="closed"
      variants={scrimVariants(reduced)}
    >
      <motion.div
        ref={surfaceRef}
        className="palette health-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Promotion"
        initial="closed"
        animate="open"
        exit="closed"
        variants={surfaceVariants(reduced)}
      >
        <div className="health-head">
          <h2>Promotion</h2>
          <button ref={closeRef} type="button" className="health-close" onClick={onClose} aria-label="Schließen">
            Schließen
          </button>
        </div>

        {!governance ? (
          <p className="health-remedy">
            Der Promotionszustand wurde nicht gelesen. Das ist nicht dasselbe wie „nichts steht im Weg“.
          </p>
        ) : (
          <>
            {/* The verdict is a sentence the backend wrote. It is the answer
                to "why not", and it is quoted rather than summarised. */}
            <p className={`gate-verdict ${tone(governance.state)}`}>{governance.verdict}</p>

            {/* The two answers, side by side and never merged. `promotion_allowed`
                comes from the discrimination gate alone; `state` is the
                worst-of-five across every gate. A reader who sees only the
                first cannot tell an open promotion from a safe one. */}
            <p className="gate-aggregate">
              Promotion {governance.promotion_allowed ? 'offen' : 'gesperrt'} · Gates insgesamt{' '}
              <span className={tone(governance.state)}>{STATE_WORD[governance.state] || governance.state}</span>
            </p>

            {/* S3: the backend's own caveats. On this machine today it emits
                "the current revision could not be read, so every revision-tied
                claim below is reported as unknown" — which is precisely the
                sentence that makes the verdict below checkable. */}
            {governance.warnings?.length > 0 && (
              <ul className="gate-warnings" role="alert">
                {governance.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            )}

            {blockers.length > 0 && (
              <ul className="gate-blockers">
                {blockers.map((blocker) => (
                  <li key={`${blocker.gate}-${blocker.why}`}>
                    <span className="gate-name">{blocker.gate}</span>
                    <span className="gate-state">{STATE_WORD[blocker.state] || blocker.state}</span>
                    <span className="gate-why">{blocker.why}</span>
                  </li>
                ))}
              </ul>
            )}

            {gates.length > 0 ? (
              <ul className="health-list">
                {gates.map((gate) => (
                  <Gate key={gate.id} gate={gate} />
                ))}
              </ul>
            ) : (
              <p className="health-remedy">Keine Gates gemeldet.</p>
            )}

            {/* Both refusals on this machine compare two revisions. A verdict
                without them cannot be checked. */}
            <p className="health-foot">
              Beurteilt für <code>{short(governance.head)}</code>
              {governance.repo_root ? ` · ${governance.repo_root}` : ''} · Promotion bleibt in jedem Fall an die
              ausdrückliche Freigabe des Owners gebunden.
            </p>
          </>
        )}
      </motion.div>
    </motion.div>
  );
}
