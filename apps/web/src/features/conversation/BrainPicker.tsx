import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import type { RuntimeRow } from '@/shared/contracts';
import { revealVariants, transitionFor, useReducedMotionPref } from '@/shared/ui/motion';
import { waitLabel } from './model';

/**
 * How long each route has taken to answer, in THIS session.
 *
 * The picker decides the shape of the wait — measured on this machine, the
 * local index answers a status question in 0.3s and the Claude CLI takes
 * 42.4s — and until now the control said nothing about that at all. This is
 * the honest version of those numbers: the page reports what it has actually
 * timed, keyed by the route that served it, and shows nothing for a route it
 * has never used. A number nobody measured is not printed.
 */
export type WaitLedger = Record<string, number>;

/**
 * Why a runtime is not available, in its own words.
 *
 * The backend already distinguishes these four; collapsing them to "nicht
 * verfügbar" throws away the only thing that tells the reader whether to start
 * Ollama or to put a key in a file. Unknown statuses fall through verbatim
 * rather than being rounded to a friendly lie.
 */
const AUTH_NOTE: Record<string, string> = {
  cli_detected: 'CLI gefunden',
  local_unreachable: 'nicht erreichbar',
  unavailable: 'nicht gefunden',
  not_configured: 'kein Schlüssel hinterlegt'
};

/** What a runtime row can honestly say about itself on one line. */
function runtimeNote(r: RuntimeRow): string {
  const bits = [r.mode];
  if (r.selected_model) bits.push(r.selected_model);
  else if (r.version) {
    // Versions arrive as `2.1.233 (Claude Code)` and `codex-cli 0.146.0`. The
    // product name is already the row's label, so only the number is new.
    const num = r.version.match(/\d[\w.+-]*/);
    if (num) bits.push(num[0]);
  }
  return bits.join(' · ');
}

/** The caret turns over when the menu opens — an acknowledgement, so the `ack` tier. */
function Chevron({ open, reduced }: { open: boolean; reduced: boolean }) {
  return (
    <motion.svg
      className="brain-caret"
      data-motion="caret"
      viewBox="0 0 12 12"
      width="12"
      height="12"
      aria-hidden="true"
      focusable="false"
      initial={false}
      animate={{ rotate: open ? 180 : 0 }}
      transition={transitionFor('ack', reduced)}
    >
      <path d="M3 4.75 6 7.75 9 4.75" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </motion.svg>
  );
}

/** Whether the runtime list could be read at all. */
export type RuntimeState = 'laden' | 'ok' | 'fehler';

export interface BrainPickerProps {
  runtimes: RuntimeRow[];
  /** whether that list is the answer or the absence of one */
  state: RuntimeState;
  /** the chosen runtime id; empty means the backend routes */
  value: string;
  onChange?: (id: string) => void;
  /** what each route has actually cost, timed in this session */
  waits: WaitLedger;
  /** which route the automatic setting last resolved to */
  lastRoute: string;
  /** a runtime id in the reader's words, or nothing when that is not known */
  labelOf: (id: string) => string | undefined;
  /** ask the backend again after the list could not be read */
  onRecheck?: () => void | Promise<void>;
  /** bump to open the menu from elsewhere (`/modell`) */
  openSignal?: number;
}

/**
 * WHO ANSWERS.
 *
 * It is not a preference — it decides the whole shape of the wait. Measured
 * on this machine against the live backend: a status question off the local
 * index comes back in 0.3s with no model in it, and the same question through
 * the Claude CLI takes 42.4s.
 *
 *  1. It sits INSIDE the composer well, first on the rail that says what will
 *     happen when you press send — who answers, what is on the stage, what
 *     would be read.
 *  2. It carries a role label (`Antwortet`), because a control that shows only
 *     its current value reads as a status readout.
 *  3. Every row shows what that runtime IS (`cli · 2.1.233`) and, once this
 *     session has actually timed it, what it COST. An untimed route shows
 *     nothing rather than a plausible number.
 *
 * Runtimes that are not available are listed with the reason, outside the
 * listbox where nothing can be clicked. A row you cannot pick is information,
 * never an affordance.
 */
export function BrainPicker({ runtimes, state, value, onChange, waits, lastRoute, labelOf, onRecheck, openSignal }: BrainPickerProps) {
  const [open, setOpen] = useState(false);
  const reduced = useReducedMotionPref();
  const reveal = useMemo(() => revealVariants(reduced), [reduced]);
  const box = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const options = useRef<(HTMLLIElement | null)[]>([]);

  const ready = runtimes.filter((r) => r.available);
  const off = runtimes.filter((r) => !r.available);
  /**
   * '' (automatic), then the local index, then every available runtime in API
   * order. The local index is a route, not an absence of one.
   */
  const ids = ['', 'deterministic', ...ready.map((r) => r.id)];
  const chosen = ready.find((r) => r.id === value);
  // A value we cannot resolve is reported as itself, not rounded to
  // "Automatisch" — a control must be able to say it does not recognise its
  // own state.
  const label = !value ? 'Automatisch' : value === 'deterministic' ? 'Lokaler Index' : chosen?.label || value;

  const close = useCallback((refocus: boolean) => {
    setOpen(false);
    if (refocus) trigger.current?.focus();
  }, []);

  useEffect(() => {
    if (openSignal && onChange) setOpen(true);
  }, [openSignal, onChange]);

  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('pointerdown', away);
    return () => document.removeEventListener('pointerdown', away);
  }, [open]);

  // Opening puts focus on the row that is already selected, so the first
  // ArrowDown moves from where you are rather than from the top.
  useEffect(() => {
    if (!open) return;
    const at = Math.max(0, ids.indexOf(value));
    options.current[at]?.focus();
    // ids is derived from runtimes/value, both in the dep list already
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const pick = useCallback(
    (id: string) => {
      onChange?.(id);
      close(true);
    },
    [close, onChange]
  );

  const onOptionKey = useCallback(
    (e: React.KeyboardEvent, index: number) => {
      const last = ids.length - 1;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp' || e.key === 'Home' || e.key === 'End') {
        e.preventDefault();
        const to =
          e.key === 'Home' ? 0 : e.key === 'End' ? last : e.key === 'ArrowDown' ? Math.min(last, index + 1) : Math.max(0, index - 1);
        options.current[to]?.focus();
      } else if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        pick(ids[index]);
      } else if (e.key === 'Escape' || e.key === 'Tab') {
        close(true);
      }
    },
    [close, ids, pick]
  );

  /**
   * The measured wait for one row, or nothing. `Automatisch` has no fixed
   * cost of its own — it borrows the cost of whichever route it last
   * resolved to.
   */
  const waitFor = (id: string): string => {
    const route = id || lastRoute;
    const seconds = route ? waits[route] : undefined;
    return seconds === undefined ? '' : waitLabel(seconds);
  };

  /** What `Automatisch` has to say for itself, once it has done something. */
  const autoNote = lastRoute && waits[lastRoute] !== undefined
    ? `zuletzt ${labelOf(lastRoute) || lastRoute}`
    : 'wählt ein verfügbares Modell';

  const row = (id: string, name: string, note: string, index: number) => (
    <li
      key={id || 'auto'}
      ref={(el) => {
        options.current[index] = el;
      }}
      role="option"
      aria-selected={value === id}
      tabIndex={-1}
      className={value === id ? 'brain-opt on' : 'brain-opt'}
      onClick={() => pick(id)}
      onKeyDown={(e) => onOptionKey(e, index)}
    >
      <span className="brain-opt-name">{name}</span>
      <span className="brain-opt-note">{note}</span>
      <span className="brain-opt-wait">{waitFor(id)}</span>
    </li>
  );

  const chosenWait = value ? waitFor(value) : '';

  return (
    <div className="brain" ref={box}>
      <button
        ref={trigger}
        type="button"
        className="brain-btn"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Wer antwortet: ${label}`}
        disabled={!onChange}
        onClick={() => setOpen((v) => !v)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            setOpen(true);
          }
        }}
      >
        <span className="brain-btn-role">Antwortet</span>
        <span className="brain-btn-name">{label}</span>
        {chosenWait && <span className="brain-btn-wait">{chosenWait}</span>}
        <Chevron open={open} reduced={reduced} />
      </button>

      <AnimatePresence>
        {open && (
          <motion.div
            className="brain-menu"
            data-motion="menu"
            variants={reveal}
            initial="hidden"
            animate="visible"
            exit="hidden"
          >
            <ul className="brain-list" role="listbox" aria-label="Wer antwortet">
              {row('', 'Automatisch', autoNote, 0)}
              {row('deterministic', 'Lokaler Index', 'ohne Modell', 1)}
              {ready.map((r, i) => row(r.id, r.label || r.id, runtimeNote(r), i + 2))}
            </ul>
            {Object.keys(waits).length > 0 && (
              <p className="brain-legend">Zuletzt gemessen, auf diesem Rechner</p>
            )}
            {state !== 'ok' && (
              <div className="brain-off">
                <p className="brain-off-note">
                  {state === 'laden'
                    ? 'Laufzeiten werden geprüft …'
                    : 'Der Zustand der Laufzeiten konnte nicht gelesen werden. Nur die automatische Route steht fest.'}
                </p>
                {state === 'fehler' && onRecheck && (
                  <button type="button" className="brain-recheck" onClick={() => void onRecheck()}>
                    Erneut prüfen
                  </button>
                )}
              </div>
            )}
            {state === 'ok' && off.length > 0 && (
              <div className="brain-off">
                <p className="brain-off-head">Stehen nicht zur Wahl</p>
                {off.map((r) => (
                  <p key={r.id} className="brain-off-row">
                    <span>{r.label || r.id}</span>
                    <span>{AUTH_NOTE[r.auth_status] || r.auth_status}</span>
                  </p>
                ))}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
