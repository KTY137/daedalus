import { useMemo, useRef, useState } from 'react';
import { motion } from 'framer-motion';
import type { HealthFact, HealthPayload, HealthSubsystem } from '@/shared/api';
import { scrimVariants, surfaceVariants, useReducedMotionPref } from '@/shared/ui/motion';
import { useDialogFocus } from '@/shared/ui/useDialogFocus';

/**
 * ZUSTAND — the health surface, opened.
 *
 * `/api/health` answers with twenty subsystems. Each one carries the QUESTION
 * it exists to answer ("which tree is every other answer about?"), its state
 * in the five-word vocabulary, a headline, a remedy, and its facts — each
 * fact stamped MEASURED, INHERITED or ASSUMED with its age. The status line
 * rendered the five counts and nothing else, so "7 beeinträchtigt" named
 * nothing a person could act on, and the chip that looked like it would tell
 * you was wired to close the theme studio.
 *
 * This panel is that button's missing other half. It invents nothing: every
 * line is a field of the payload the cockpit had already fetched.
 *
 * THE PROVENANCE STAMP IS THE POINT. This repository's rule is that an
 * unlabelled number is a rumour, and the backend already labels every one of
 * them. Rendering the value without its stamp would launder an ASSUMED
 * reading into a measurement, which is the exact defect the vocabulary exists
 * to prevent.
 */

const STATE_WORD: Record<HealthSubsystem['state'], string> = {
  working: 'läuft',
  present: 'vorhanden, ungeprüft',
  degraded: 'beeinträchtigt',
  absent: 'fehlt',
  unknown: 'unbekannt'
};

/** Attention first: what is broken, then what is unproven, then what holds. */
const ORDER: HealthSubsystem['state'][] = ['degraded', 'absent', 'unknown', 'present', 'working'];

/** Where a state the interface does not recognise sorts: with the unproven,
 *  never after the healthy ones. `indexOf` returns -1 for an unknown word,
 *  which would have sorted it FIRST and silently. */
function rank(state: HealthSubsystem['state']): number {
  const at = ORDER.indexOf(state);
  return at === -1 ? ORDER.indexOf('unknown') : at;
}

/**
 * Only `working` earns the healthy colour. A state word this interface does
 * not recognise is drawn as unproven, because the failure direction that
 * matters here is unknown-read-as-healthy, not the other way round.
 */
function tone(state: HealthSubsystem['state']): string {
  if (state === 'degraded' || state === 'absent') return 'bad';
  if (state === 'working') return 'ok';
  return 'warn';
}

function age(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '';
  if (seconds < 90) return `${Math.round(seconds)} s alt`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min alt`;
  return `${Math.round(seconds / 3600)} h alt`;
}

/** A fact's value as text. Objects are printed as JSON rather than as
 *  "[object Object]", which is the shape this repo has shipped twice. */
function valueText(value: unknown): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return '—';
  }
}

function Fact({ fact }: { fact: HealthFact }) {
  const when = age(fact.age_s);
  return (
    <li className="health-fact">
      <span className="health-fact-label">{fact.label}</span>
      <span className="health-fact-value">{valueText(fact.value)}</span>
      <span className={`health-prov ${String(fact.provenance || '').toLowerCase()}`}>{fact.provenance || 'OHNE STEMPEL'}</span>
      {(fact.source || when) && (
        <span className="health-fact-meta">
          {fact.source ? <code>{fact.source}</code> : null}
          {when ? <span>{when}</span> : null}
        </span>
      )}
    </li>
  );
}

function Subsystem({ subsystem }: { subsystem: HealthSubsystem }) {
  const [open, setOpen] = useState(false);
  const facts = subsystem.facts || [];
  return (
    <li className={`health-row ${tone(subsystem.state)}`}>
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        <span className="health-row-head">
          <span className={`dot ${tone(subsystem.state)}`} aria-hidden="true" />
          <span className="health-name">{subsystem.name}</span>
          <span className="health-state">{STATE_WORD[subsystem.state] || subsystem.state}</span>
          {subsystem.required && <span className="health-required">erforderlich</span>}
        </span>
        {/* The question the subsystem exists to answer. It is in the payload
            and it is the one line that makes a name like `git.worktree`
            mean something. */}
        <span className="health-asks">{subsystem.asks}</span>
        <span className="health-headline">{subsystem.headline || 'Ohne Schlagzeile'}</span>
      </button>
      {subsystem.remedy && <p className="health-remedy">{subsystem.remedy}</p>}
      {open && (
        facts.length > 0 ? (
          <ul className="health-facts">
            {facts.map((fact, i) => (
              <Fact key={`${fact.label}-${i}`} fact={fact} />
            ))}
          </ul>
        ) : (
          <p className="health-remedy">Keine Einzelwerte gemeldet.</p>
        )
      )}
    </li>
  );
}

export interface HealthPanelProps {
  open: boolean;
  onClose: () => void;
  health?: HealthPayload;
  /** why the read failed, when it did — never collapsed into "nothing wrong" */
  error?: string;
}

export function HealthPanel({ open, onClose, health, error }: HealthPanelProps) {
  const reduced = useReducedMotionPref();
  const [onlyProblems, setOnlyProblems] = useState(true);
  const snapshot = health?.health;
  /**
   * Focus enters the dialog, is TRAPPED inside it, and returns to the opener
   * on close. The trap is the part that was missing: moving focus alone still
   * let Tab walk onto the theme controls behind the scrim, while
   * `aria-modal="true"` told assistive technology they were hidden.
   */
  const closeRef = useRef<HTMLButtonElement>(null);
  const surfaceRef = useRef<HTMLDivElement>(null);
  useDialogFocus(open, surfaceRef, closeRef);

  const rows = useMemo(() => {
    const all = snapshot?.subsystems || [];
    const shown = onlyProblems ? all.filter((s) => s.state !== 'working') : all;
    return [...shown].sort((a, b) => rank(a.state) - rank(b.state));
  }, [onlyProblems, snapshot]);

  if (!open) return null;

  const hidden = (snapshot?.subsystems?.length || 0) - rows.length;

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
        aria-label="Zustand"
        initial="closed"
        animate="open"
        exit="closed"
        variants={surfaceVariants(reduced)}
      >
        <div className="health-head">
          <h2>Zustand</h2>
          <button type="button" className="health-filter" onClick={() => setOnlyProblems((v) => !v)}>
            {onlyProblems ? 'Alle zeigen' : 'Nur Auffälliges'}
          </button>
          <button ref={closeRef} type="button" className="health-close" onClick={onClose} aria-label="Schließen">
            Schließen
          </button>
        </div>

        {error && (
          <p className="health-remedy bad" role="alert">
            Der Zustand konnte nicht gelesen werden: {error}
          </p>
        )}
        {!error && !snapshot && <p className="health-remedy">Der Zustand wird gelesen …</p>}

        {snapshot && (
          <>
            {snapshot.not_proven?.length > 0 && (
              <p className="health-remedy">
                Nicht bewiesen: {snapshot.not_proven.join(', ')}. Das ist nicht dasselbe wie fehlgeschlagen — diese
                Prüfungen sind in diesem Lauf nicht gelaufen.
              </p>
            )}
            {rows.length === 0 ? (
              <p className="health-remedy">
                {onlyProblems ? 'Nichts Auffälliges. Jede Prüfung, die lief, hielt.' : 'Keine Prüfungen gemeldet.'}
              </p>
            ) : (
              <ul className="health-list">
                {rows.map((subsystem) => (
                  <Subsystem key={subsystem.name} subsystem={subsystem} />
                ))}
              </ul>
            )}
            <p className="health-foot">
              {snapshot.subsystems?.length || 0} {snapshot.subsystems?.length === 1 ? 'Prüfung' : 'Prüfungen'} · gelesen{' '}
              {snapshot.generated_at || 'unbekannt'}
              {hidden > 0 ? ` · ${hidden} laufende ausgeblendet` : ''}
            </p>
          </>
        )}
      </motion.div>
    </motion.div>
  );
}
