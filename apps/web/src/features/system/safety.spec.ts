import {
  GATE_WORD,
  fallbackText,
  gateReading,
  gateTone,
  safetyGates,
  staleText,
  worstGate,
  type GateReading,
  type QualityBlock
} from './safety';

/**
 * The safety gates, pinned.
 *
 * Values are the live `/api/dashboard` `quality` block on 2026-09-03. The
 * cases that matter are the two that are NOT true: a probe that ran and did
 * not verify, and a block that never arrived. core.py calls the first SAFETY;
 * neither may render as verified.
 */

interface Result {
  name: string;
  ok: boolean;
  detail?: string;
}

const ALL: GateReading[] = ['verified', 'failed', 'unreported'];

/** The live block, measured. */
const live: QualityBlock = {
  local_only_never_claude: true,
  schema_non_empty_summary: true,
  empty_reports_fail: true,
  stale_watchers: 0,
  fallback_alarm: false,
  fallback_rate: 0.0,
  recommendation: ''
};

export function runSafetySpec(): Result[] {
  const results: Result[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  // ---- 1. three readings, and only one is green --------------------------
  check('a probe that ran and held is verified', gateReading(true) === 'verified');
  check('a probe that ran and did not hold is a failure', gateReading(false) === 'failed');
  // THE direction that matters: an older server sends nothing here.
  check('a gate nobody reported is not a gate that held', gateReading(undefined) === 'unreported');
  check(
    'exactly one reading is green',
    ALL.filter((r) => gateTone(r) === 'ok').join() === 'verified'
  );
  check(
    'a failed safety probe is red, an unreported one amber',
    gateTone('failed') === 'bad' && gateTone('unreported') === 'warn'
  );
  for (const r of ALL) {
    check(`the word for "${r}" exists and is distinct`, Boolean(GATE_WORD[r]?.trim()));
  }
  check('the three words are distinct',
    new Set(ALL.map((r) => GATE_WORD[r])).size === 3,
    ALL.map((r) => GATE_WORD[r]).join(' | '));
  check('an unreported gate does not claim to have been checked',
    GATE_WORD.unreported.includes('nicht gemeldet'));

  // ---- 2. the gates themselves -------------------------------------------
  const green = safetyGates(live);
  check('both probes are reported', green.length === 2, String(green.length));
  check('and both are verified on this machine',
    green.every((g) => g.reading === 'verified'));
  check('the containment gate asks about local_only',
    green[0].question.includes('local_only'), green[0].question);
  // core.py's own escalation, carried through.
  check('a failed containment gate says to check before queueing',
    green[0].consequence.includes('vor dem Einreihen'), green[0].consequence);

  const broken = safetyGates({ ...live, local_only_never_claude: false });
  check('a failed gate reads as failed', broken[0].reading === 'failed');
  check('and the whole card takes the worst reading', worstGate(broken) === 'failed');

  const missing = safetyGates(undefined);
  check('a missing block still lists both gates', missing.length === 2);
  check('as unreported, never verified', missing.every((g) => g.reading === 'unreported'));
  check('and the card is not green', worstGate(missing) !== 'verified');
  check('a failure outranks an absence', worstGate([...broken, ...missing]) === 'failed');
  check('all-verified is verified', worstGate(green) === 'verified');

  // ---- 3. the numbers are never defaulted --------------------------------
  // "no fallbacks happened" and "nobody counted" are different, and 0 is the
  // reassuring one.
  check('a reported rate is shown', fallbackText(live) === '0,0 %', String(fallbackText(live)));
  check('a real rate is shown to one place',
    fallbackText({ fallback_rate: 0.125 }) === '12,5 %', String(fallbackText({ fallback_rate: 0.125 })));
  check('an unreported rate is not shown as zero', fallbackText({}) === null);
  check('an unreported rate on a missing block is not invented', fallbackText(undefined) === null);

  check('zero stale watchers is stated as zero', staleText(live).text === 'keiner');
  check('and is not alarming', staleText(live).tone === '');
  check('a stale watcher is alarming', staleText({ stale_watchers: 1 }).tone === 'bad');
  check('and is counted', staleText({ stale_watchers: 2 }).text.includes('2'));
  check('an unreported count is not zero',
    staleText({}).text === 'nicht gemeldet' && staleText({}).tone === 'warn');

  return results;
}
