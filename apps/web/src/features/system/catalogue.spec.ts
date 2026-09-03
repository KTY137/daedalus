import {
  USE_WORD,
  catalogueSummary,
  licenceCaution,
  readEntries,
  readEntry,
  rejectionNote,
  type CatalogueBlock
} from './catalogue';

/**
 * The component catalogue, pinned.
 *
 * Every entry below is verbatim from `/api/catalogue` on 2026-09-03. The three
 * that carry cautions are the three the catalogue's own notes single out.
 */

interface Result {
  name: string;
  ok: boolean;
  detail?: string;
}

const LIVE: CatalogueBlock = {
  schema: 'daedalus-gui-catalogue/1',
  sources: ['external.json', 'glass.json'],
  entry_count: 17,
  rejected: [],
  rejected_count: 0,
  entries: [
    { name: 'ext/react-bits', licence: 'MIT-with-Commons-Clause', licence_url: 'https://github.com/DavidHDev/react-bits/blob/main/LICENSE.md', use_mode: 'reference_only', vendorable: false },
    { name: 'ext/skiper-ui', licence: 'NOASSERTION', licence_url: '', use_mode: 'reference_only', vendorable: false },
    { name: 'ext/origin-ui', licence: 'AGPL-3.0', licence_url: 'https://github.com/origin-space/originui/blob/main/LICENSING.md', use_mode: 'reciprocal', vendorable: false },
    { name: 'ext/shadcn-ui', licence: 'MIT', licence_url: '', use_mode: 'copy_in', vendorable: true },
    { name: 'ext/tremor', licence: 'Apache-2.0', licence_url: '', use_mode: 'copy_in', vendorable: true }
  ]
};

export function runCatalogueSpec(): Result[] {
  const results: Result[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  const read = readEntries(LIVE);
  const by = (n: string) => read.find((e) => e.name === n)!;

  // ---- 1. THE LICENCE TRAP -----------------------------------------------
  // "The string starts with 'MIT'; the licence is not MIT."
  const bits = by('ext/react-bits');
  check('the Commons Clause licence is rendered WHOLE',
    bits.licence === 'MIT-with-Commons-Clause', bits.licence);
  check('and is never shortened to its first token',
    bits.licence !== 'MIT' && bits.licence.includes('Commons'), bits.licence);
  check('and carries the caution that it is not MIT',
    bits.caution.includes('nicht MIT'), bits.caution);
  check('and is drawn as a refusal', bits.tone === 'bad' && !bits.vendorable, bits.tone);

  // ---- 2. NOASSERTION IS NOT A LICENCE -----------------------------------
  const skiper = by('ext/skiper-ui');
  check('an unestablished licence says so',
    skiper.caution.includes('nicht festgestellt'), skiper.caution);
  // The two readings it must NOT collapse into.
  check('and is neither "no licence" nor "free to use"',
    skiper.caution.includes('keine Lizenz') && skiper.caution.includes('freie Nutzung'),
    skiper.caution);
  check('and is drawn loudly, not quietly', skiper.tone === 'bad', skiper.tone);

  // ---- 3. RECIPROCAL SPREADS ---------------------------------------------
  const origin = by('ext/origin-ui');
  check('a reciprocal licence says adoption spreads it',
    origin.use === USE_WORD.reciprocal && origin.use.includes('färbt ab'), origin.use);
  check('and is not offered as copyable', origin.vendorable === false && origin.tone === 'bad');

  // ---- 4. the permissive ones stay quiet ---------------------------------
  const shadcn = by('ext/shadcn-ui');
  check('a plain MIT entry is unremarkable', shadcn.tone === '' && shadcn.caution === '');
  check('and says it may be taken', shadcn.use === USE_WORD.copy_in);
  check('an Apache entry likewise', by('ext/tremor').tone === '');

  // ---- 5. the summary counts REFUSALS, not admissions --------------------
  const summary = catalogueSummary(LIVE);
  check('the summary names how many may not be copied',
    summary.includes('3 davon nicht übernehmbar'), summary);
  check('and names where the catalogue came from',
    summary.includes('external.json'), summary);
  check('an unread catalogue is not summarised as empty',
    catalogueSummary(undefined) === 'Katalog nicht gelesen');
  check('a catalogue with no entries says so rather than claiming all is well',
    catalogueSummary({ entries: [] }) === 'Keine Einträge gemeldet');
  check('an all-permissive catalogue says so plainly',
    catalogueSummary({ entries: [LIVE.entries![3]] }).includes('alle übernehmbar'));

  // ---- 6. zero refusals is reported as zero ------------------------------
  // An empty refusal list is a fact about the load; omitting it would leave a
  // reader unable to tell "nothing was refused" from "not reported".
  check('no rejections is stated, not omitted',
    rejectionNote(LIVE).includes('Kein Eintrag'), rejectionNote(LIVE));
  check('one rejection is counted', rejectionNote({ rejected_count: 1 }).startsWith('1 Eintrag'));
  check('several are counted', rejectionNote({ rejected_count: 4 }).startsWith('4 Einträge'));
  check('an unread catalogue reports no rejection line', rejectionNote(undefined) === '');

  // ---- 7. degenerate and hostile inputs ----------------------------------
  check('a missing licence is not a permission',
    licenceCaution('').includes('keine Freigabe'), licenceCaution(''));
  check('a missing licence entry is not vendorable',
    readEntry({ name: 'x' }).tone !== '' && readEntry({ name: 'x' }).vendorable === false);
  check('lower-case noassertion is caught too',
    licenceCaution('noassertion').includes('nicht festgestellt'));
  check('a spaced Commons Clause is caught too',
    licenceCaution('MIT with Commons Clause').includes('nicht MIT'));
  check('an unknown use_mode is shown raw rather than dropped',
    readEntry({ name: 'y', use_mode: 'brand_new', vendorable: true }).use === 'brand_new');
  check('a missing use_mode says so',
    readEntry({ name: 'z', vendorable: true }).use === 'Nutzungsart nicht gemeldet');
  // vendorable is the operative flag: absent means not granted.
  check('an entry that does not claim vendorable is not treated as vendorable',
    readEntry({ name: 'w', licence: 'MIT', use_mode: 'copy_in' }).vendorable === false);
  check('an entry with no name is dropped rather than rendered nameless',
    readEntries({ entries: [{ name: '' }, { name: 'ok' }] }).length === 1);

  return results;
}
