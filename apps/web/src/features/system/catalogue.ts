import type { CatalogueEntryRow as CatalogueEntry } from '@/shared/api';

export type { CatalogueEntry };

/**
 * WHAT THIS INTERFACE MAY BE BUILT FROM, AND WHAT IT MAY NOT COPY.
 *
 * `/api/catalogue` is the registry of UI sources this cockpit may draw on. It
 * carries, per entry, a `licence` string, a code-derived `use_mode`, and a
 * `vendorable` flag -- and `read.py` says why the refusals ride along with the
 * admissions: "a reader must see what was REFUSED and why, not just what was
 * admitted". Nothing in the cockpit has ever read it.
 *
 * Measured live, 2026-09-03: 17 entries, 0 rejected, from external.json and
 * glass.json.
 *
 *   vendorable  12 true, 5 false
 *   use_mode    12 copy_in, 4 reference_only, 1 reciprocal
 *
 * THE THREE THIS EXISTS FOR, in the catalogue's own words:
 *
 *   ext/react-bits   MIT-with-Commons-Clause
 *       "THE LICENCE TRAP THIS CATALOGUE EXISTS TO CATCH. The string starts
 *        with 'MIT'; the licence is not MIT. The Commons Clause removes
 *        exactly the right this repo would need."
 *
 *   ext/skiper-ui    NOASSERTION
 *       "the worked example of the honest third state. A missing licence
 *        FIELD is a refusal -- such an entry never loads. An explicitly
 *        recorded NOASSERTION loads and resolves to reference_only."
 *
 *   ext/origin-ui    AGPL-3.0
 *       "SPLIT LICENCE. Recorded as AGPL-3.0 so use_mode comes out
 *        'reciprocal' and a human is forced to look."
 *
 * TWO RULES THIS MODULE KEEPS.
 *
 * 1. THE LICENCE STRING IS NEVER SHORTENED. Truncating
 *    "MIT-with-Commons-Clause" at the first token produces "MIT", which is
 *    the precise error the catalogue was built to prevent. It is rendered
 *    whole or not at all.
 * 2. NOASSERTION IS NOT A LICENCE. It means nobody established one, which is
 *    not the same as permissive and not the same as absent. It reads as
 *    unknown and is drawn as the loudest state, because an unexamined licence
 *    is the one most likely to be assumed benign.
 */

export interface CatalogueBlock {
  schema?: string;
  sources?: string[];
  entries?: CatalogueEntry[];
  entry_count?: number;
  rejected?: Array<Record<string, unknown>>;
  rejected_count?: number;
}

/** What you may do with an entry, in the registry's own vocabulary. */
export const USE_WORD: Record<string, string> = {
  copy_in: 'darf übernommen werden',
  reference_only: 'nur als Vorlage, nicht kopieren',
  reciprocal: 'reziprok lizenziert — Übernahme färbt ab'
};

export interface CatalogueReading {
  name: string;
  /** the licence string, VERBATIM, never shortened */
  licence: string;
  licenceUrl: string;
  use: string;
  tone: string;
  /** true only when the registry says so explicitly */
  vendorable: boolean;
  /** set when the licence needs a second look, in the registry's terms */
  caution: string;
  notes: string;
}

/**
 * Whether the licence deserves a warning of its own, beyond `use_mode`.
 *
 * This does not re-derive permission -- `use_mode` is code-derived on the
 * backend and is the authority. It only names the two shapes a reader is
 * likeliest to misread at a glance.
 */
export function licenceCaution(licence: string | undefined): string {
  const text = String(licence || '').trim();
  if (!text) return 'Keine Lizenz gemeldet. Das ist keine Freigabe.';
  if (text.toUpperCase() === 'NOASSERTION') {
    return 'Lizenz nicht festgestellt. Das ist weder „keine Lizenz“ noch „freie Nutzung“.';
  }
  if (/commons[-\s]?clause/i.test(text)) {
    return 'Beginnt mit „MIT“, ist aber nicht MIT: die Commons Clause entzieht genau das Recht, '
      + 'das eine Übernahme hier bräuchte.';
  }
  return '';
}

export function readEntry(entry: CatalogueEntry): CatalogueReading {
  const licence = String(entry.licence || '').trim();
  const mode = String(entry.use_mode || '').trim();
  const vendorable = entry.vendorable === true;
  const caution = licenceCaution(licence);

  // `vendorable` is the operative flag and the backend derives it; a false
  // one is drawn as a refusal even when the mode word sounds mild.
  const tone = vendorable && !caution ? '' : caution || mode === 'reciprocal' ? 'bad' : 'warn';

  return {
    name: entry.name,
    licence: licence || 'nicht gemeldet',
    licenceUrl: String(entry.licence_url || ''),
    use: USE_WORD[mode] || mode || 'Nutzungsart nicht gemeldet',
    tone,
    vendorable,
    caution,
    notes: String(entry.notes || '')
  };
}

export function readEntries(block: CatalogueBlock | undefined): CatalogueReading[] {
  return (block?.entries || []).filter((e) => e && e.name).map(readEntry);
}

/**
 * The headline: how many sources may not be copied from.
 *
 * Stated as a count of refusals rather than of admissions, because the
 * refusals are the ones a builder has to know before reaching for something.
 */
export function catalogueSummary(block: CatalogueBlock | undefined): string {
  if (!block) return 'Katalog nicht gelesen';
  const entries = readEntries(block);
  if (entries.length === 0) return 'Keine Einträge gemeldet';
  const blocked = entries.filter((e) => !e.vendorable).length;
  const sources = (block.sources || []).join(', ');
  const from = sources ? ` aus ${sources}` : '';
  return blocked === 0
    ? `${entries.length} Quellen${from}, alle übernehmbar`
    : `${entries.length} Quellen${from} · ${blocked} davon nicht übernehmbar`;
}

/**
 * What the loader refused outright, and why.
 *
 * `read.py` keeps `rejected` beside `entries` on purpose. Zero is reported as
 * zero -- an empty refusal list is a fact about the load, and omitting it
 * would leave a reader unable to tell "nothing was refused" from "refusals
 * were not reported".
 */
export function rejectionNote(block: CatalogueBlock | undefined): string {
  if (!block) return '';
  const n = typeof block.rejected_count === 'number'
    ? block.rejected_count
    : (block.rejected || []).length;
  if (n === 0) return 'Kein Eintrag wurde beim Laden abgewiesen.';
  return n === 1 ? '1 Eintrag wurde abgewiesen.' : `${n} Einträge wurden abgewiesen.`;
}
