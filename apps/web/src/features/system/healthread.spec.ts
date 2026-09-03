import { costText, readMode, scopeNote, shallow, totalCost, type HealthAsked } from './healthread';

/**
 * What the health read asked, and what it cost — pinned.
 *
 * Every value here was measured against the live endpoint on 2026-09-03. The
 * scoped case in particular is not hypothetical: `GET /api/health?only=git`
 * really does return one subsystem with an all-green count.
 */

interface Result {
  name: string;
  ok: boolean;
  detail?: string;
}

function asked(over: Partial<HealthAsked> = {}): HealthAsked {
  // The live default: both expensive probes off, no filter.
  return { deep: false, probe_remote: false, only: null, ...over };
}

export function runHealthReadSpec(): Result[] {
  const results: Result[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  // ---- 1. the scoped board announces itself -------------------------------
  // THE hazard: a filter that produces a perfect green board.
  const scoped = scopeNote(asked({ only: 'git' }), 1);
  check('a filtered board says it is filtered', Boolean(scoped), String(scoped));
  check('and names the filter that was applied', String(scoped).includes('git'), String(scoped));
  check(
    'and refuses to be read as the system state',
    String(scoped).includes('nicht der Zustand des Systems'),
    String(scoped)
  );
  check('an unfiltered board carries no such warning', scopeNote(asked(), 20) === null);
  check('an empty filter is not a filter', scopeNote(asked({ only: '' }), 20) === null);
  check('whitespace is not a filter', scopeNote(asked({ only: '   ' }), 20) === null);
  check(
    'a payload that reported no asked-block is not claimed to be filtered',
    scopeNote(undefined, 20) === null
  );

  // ---- 2. which read this was --------------------------------------------
  check('the default read is named as shallow', readMode(asked()).includes('flach'));
  check(
    'and says the remote hosts were not touched',
    readMode(asked()).includes('nicht angestoßen'),
    readMode(asked())
  );
  check('a deep read says so', readMode(asked({ deep: true })).includes('tief'));
  check(
    'a remote-probing read says so',
    readMode(asked({ probe_remote: true })).includes('entfernte Hosts geprüft')
  );
  // A missing block is an unknown scope, never silently "full".
  check(
    'a missing asked-block is reported as unknown, not as a full read',
    readMode(undefined) === 'Umfang nicht gemeldet'
  );

  check('the default read is flagged shallow', shallow(asked()) === true);
  check('deep alone is still shallow: the remote hosts were skipped',
    shallow(asked({ deep: true })) === true);
  check('only both probes together are a full read',
    shallow(asked({ deep: true, probe_remote: true })) === false);
  // Nothing is claimed about a read that did not report its scope.
  check('an unreported scope is not asserted to be shallow', shallow(undefined) === false);

  // ---- 3. what it cost ----------------------------------------------------
  // Measured: rows ran 0.00s..2.06s and summed to 10.62s -- the whole of the
  // ~10.6s a health read takes.
  check('a probe cost is shown to hundredths', costText(2.06) === '2,06 s', costText(2.06));
  check('a free probe is stated as free, not hidden', costText(0) === '0,00 s');
  check('a German decimal comma is used', costText(10.62) === '10,62 s', costText(10.62));
  check('a missing cost is not invented', costText(null) === '' && costText(undefined) === '');
  check('a nonsense cost is not rendered', costText(Number.NaN) === '' && costText(-1) === '');

  const live = [
    { name: 'embed.bench', seconds: 2.06 },
    { name: 'embed.local', seconds: 2.04 },
    { name: 'bench.residency', seconds: 2.04 },
    { name: 'hand.executor', seconds: 2.03 },
    { name: 'picker.queue', seconds: 0.96 }
  ];
  check(
    'the board cost is summed from the rows themselves',
    Math.abs(totalCost(live) - 9.13) < 0.005,
    String(totalCost(live))
  );
  check('rows with no cost do not corrupt the sum',
    Math.abs(totalCost([...live, { seconds: null }, {}]) - 9.13) < 0.005);
  check('an empty board costs nothing rather than NaN', totalCost([]) === 0);

  return results;
}
