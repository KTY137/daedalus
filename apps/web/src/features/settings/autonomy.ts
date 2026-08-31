/**
 * How much Ikarus may do without asking.
 *
 * Two levels, and the owner picks. A task can be suggested for automatic
 * dispatch, but every draft it creates remains an explicit human handoff:
 *
 *   aus         nothing happens without a click. The default.
 *   vorschlaege a proposed TASK is queued without asking. A queued task still
 *               runs behind the same policy, still produces a draft, and that
 *               draft still waits for a person.
 * Automatic dispatches are recorded in the local log; a handoff is never
 * recorded as a repository write, evaluation, or promotion.
 */

export type AutonomyLevel = 'aus' | 'vorschlaege';

export const AUTONOMY_LEVELS: Array<{ id: AutonomyLevel; label: string; note: string }> = [
  { id: 'aus', label: 'Aus', note: 'Nichts passiert ohne deinen Klick.' },
  { id: 'vorschlaege', label: 'Vorschläge', note: 'Vorgeschlagene Aufgaben laufen sofort los. Jeder erzeugte Entwurf wartet weiter auf deine explizite Übergabe.' }
];

const KEY = 'daedalus-autonomy';
const LOG_KEY = 'daedalus-autonomy-log';
const MAX_LOG = 60;

export function loadAutonomy(): AutonomyLevel {
  try {
    const raw = localStorage.getItem(KEY);
    return AUTONOMY_LEVELS.some((l) => l.id === raw) ? (raw as AutonomyLevel) : 'aus';
  } catch {
    return 'aus';
  }
}

export function saveAutonomy(level: AutonomyLevel): void {
  try {
    localStorage.setItem(KEY, level);
  } catch {
    /* storage blocked — the choice still holds for this session */
  }
}

export interface AutonomyEntry {
  at: string;
  what: string;
  detail: string;
  level: AutonomyLevel;
}

export function readAutonomyLog(): AutonomyEntry[] {
  try {
    const raw = localStorage.getItem(LOG_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? (parsed as AutonomyEntry[]) : [];
  } catch {
    return [];
  }
}

/** Every automatic action lands here. Nothing happens by itself unrecorded. */
export function recordAutonomy(entry: Omit<AutonomyEntry, 'at'>): AutonomyEntry[] {
  const next = [{ ...entry, at: new Date().toISOString() }, ...readAutonomyLog()].slice(0, MAX_LOG);
  try {
    localStorage.setItem(LOG_KEY, JSON.stringify(next));
  } catch {
    /* storage blocked — the entry is still returned to the caller */
  }
  return next;
}
