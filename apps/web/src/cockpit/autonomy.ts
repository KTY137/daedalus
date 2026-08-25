/**
 * How much Ikarus may do without asking.
 *
 * Four levels, and the owner picks. The point of writing them down here rather
 * than as a boolean is that "automatically accept" means three different things
 * with three different blast radii, and a single switch would hide which one is
 * armed:
 *
 *   aus         nothing happens without a click. The default.
 *   vorschlaege a proposed TASK is queued without asking. A queued task still
 *               runs behind the same policy, still produces a draft, and that
 *               draft still waits for a person.
 *   entwuerfe   a draft is APPLIED without asking, but only under limits it
 *               cannot argue its way out of (see `withinLimits`).
 *   alles       every draft is applied without asking, limits included.
 *
 * `alles` writes to the repository with no click and no ceiling. The owner
 * asked for it explicitly and it exists; it is not the default, it is never
 * selected implicitly, and every automatic action is written to a log the
 * cockpit shows, because "it did it by itself" must never also mean "and
 * nobody can see what".
 */

export type AutonomyLevel = 'aus' | 'vorschlaege' | 'entwuerfe' | 'alles';

export const AUTONOMY_LEVELS: Array<{ id: AutonomyLevel; label: string; note: string }> = [
  { id: 'aus', label: 'Aus', note: 'Nichts passiert ohne deinen Klick.' },
  {
    id: 'vorschlaege',
    label: 'Vorschläge',
    note: 'Vorgeschlagene Aufgaben laufen sofort los. Was sie erzeugen, wartet weiter auf dich.'
  },
  {
    id: 'entwuerfe',
    label: 'Entwürfe mit Grenzen',
    note: 'Entwürfe werden auch angewandt — aber nur unter Grenzen: höchstens 8 Dateien, keine Risiken im Bericht, keine geschützten Pfade.'
  },
  {
    id: 'alles',
    label: 'Alles',
    note: 'Jeder Entwurf wird ohne Rückfrage in dein Repository geschrieben. Auch die mit gemeldeten Risiken.'
  }
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

/** What a draft has to look like before `entwuerfe` will apply it unasked. */
export const DRAFT_LIMITS = {
  maxFiles: 8,
  /** path fragments that always require a person, whatever the level says */
  guardedPaths: ['.agentenv', '.github', 'settings.json', 'tool-allowances', 'AGENTS.md', 'CLAUDE.md', '.git/']
};

export interface DraftShape {
  files: string[];
  risks: string[];
  status?: string;
}

export interface LimitVerdict {
  ok: boolean;
  /** the reason, in the interface's own words, when it is not ok */
  why: string;
}

export function withinLimits(draft: DraftShape): LimitVerdict {
  if (draft.files.length > DRAFT_LIMITS.maxFiles) {
    return { ok: false, why: `${draft.files.length} Dateien — die Grenze liegt bei ${DRAFT_LIMITS.maxFiles}` };
  }
  if (draft.risks.length > 0) {
    return { ok: false, why: `der Bericht meldet ${draft.risks.length} Risiko(s)` };
  }
  if (draft.status && draft.status !== 'done') {
    return { ok: false, why: `der Lauf endete als „${draft.status}“, nicht als „done“` };
  }
  const guarded = draft.files.find((f) =>
    DRAFT_LIMITS.guardedPaths.some((g) => f.replace(/\\/g, '/').includes(g))
  );
  if (guarded) return { ok: false, why: `berührt einen geschützten Pfad: ${guarded}` };
  return { ok: true, why: '' };
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
