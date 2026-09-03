import {
  APPLIED_WORD,
  appliedReading,
  appliedTone,
  isTerminalState,
  laneReading,
  providerReading,
  type AppliedReading
} from './outcome';

/**
 * What the detail view says about a finished run, pinned.
 *
 * Every case here comes from a REAL dispatch made on 2026-09-03 -- the first
 * work attempt this cockpit had ever run -- or from the contract that dispatch
 * exposed. Nothing is invented.
 */

interface Result {
  name: string;
  ok: boolean;
  detail?: string;
}

const ALL: AppliedReading[] = ['applied', 'not_applied', 'unproven'];

export function runOutcomeSpec(): Result[] {
  const results: Result[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  // ---- 1. applied is tri-state, and null is not "no" ----------------------
  check('a measured application reads as applied', appliedReading(true) === 'applied');
  check('a measured non-application reads as not_applied', appliedReading(false) === 'not_applied');
  // The direction that matters. `_derive_applied` returns null when it cannot
  // tell; rendering that as "nicht übernommen" asserts a measurement nobody
  // made, in the reassuring direction -- "nothing was written" sounds like a
  // clean tree.
  check('an unknown application is unproven, not a denial', appliedReading(null) === 'unproven');
  check('a missing field is unproven, not a denial', appliedReading(undefined) === 'unproven');
  check(
    'the three readings are three distinct words',
    new Set(ALL.map((r) => APPLIED_WORD[r])).size === 3,
    ALL.map((r) => APPLIED_WORD[r]).join(' | ')
  );
  check('unproven does not claim a denial', APPLIED_WORD.unproven === 'nicht nachweisbar');
  check(
    'only a measured application is green',
    ALL.filter((r) => appliedTone(r) === 'ok').join() === 'applied'
  );
  check('an unproven outcome is never green', appliedTone('unproven') !== 'ok');

  // ---- 2. the lane, and the lane that actually ran ------------------------
  // The old rendering was `requested_lane || lane`: one value, so a divergence
  // was invisible. local_only exists to keep work OFF external providers.
  const same = laneReading({ requested_lane: 'local_only', lane: 'local_only' });
  check('a matching lane is stated once', same?.diverged === false && same?.requested === 'local_only');

  const drift = laneReading({ requested_lane: 'local_only', lane: 'anthropic_api' });
  check(
    'a lane that ran elsewhere is reported as a divergence',
    drift?.diverged === true && drift?.requested === 'local_only' && drift?.actual === 'anthropic_api',
    JSON.stringify(drift)
  );
  check('a task with no lane at all is not invented', laneReading({}) === null);
  check(
    'an unrequested lane still names what ran',
    laneReading({ lane: 'local_only' })?.requested === 'local_only'
  );
  check(
    'an empty string is not a lane',
    laneReading({ requested_lane: '', lane: '' }) === null
  );

  // ---- 3. "nobody accepted it" is a fact, not silence ---------------------
  // Measured: the real failed dispatch had actual_providers: [] and an error
  // reading "the trusted local bench did not accept the task".
  const none = providerReading([], true);
  check('a finished task with no provider says so', none?.none === true, JSON.stringify(none));
  check(
    'and does not phrase it as though something ran',
    !String(none?.text).startsWith('über'),
    String(none?.text)
  );
  // An absence that is merely early is not evidence.
  check('an unfinished task with no provider stays silent', providerReading([], false) === null);
  const one = providerReading(['claude_code_cli'], true);
  check('a named provider is reported', one?.none === false && one?.text === 'claude_code_cli');
  check(
    'blank entries are not counted as providers',
    providerReading(['', ''], true)?.none === true
  );

  // ---- 4. the terminal vocabulary matches the endpoint's own --------------
  for (const s of ['done', 'completed', 'succeeded', 'failed', 'quarantined']) {
    check(`"${s}" is terminal`, isTerminalState(s));
  }
  for (const s of ['queued', 'running', 'claimed', 'dispatched', 'unknown', '']) {
    check(`"${s || '(empty)'}" is not terminal`, !isTerminalState(s));
  }
  check('the terminal check is case-insensitive', isTerminalState('FAILED'));

  return results;
}
