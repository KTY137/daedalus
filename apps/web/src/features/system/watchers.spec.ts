import { watcherReading, watcherWhere, type WatcherBlock } from './watchers';

/**
 * Who is consuming the queue, pinned.
 *
 * The two commands below are verbatim from `/api/dashboard` on 2026-09-03 --
 * two matches for one project, from two different interpreters, both
 * `stale: false`.
 */

interface Result {
  name: string;
  ok: boolean;
  detail?: string;
}

const LIVE_A = '"C:\\Users\\Administrator\\Desktop\\projects\\daedalus\\.claude\\worktrees\\g1-ui-ikarus\\.venv\\Scripts\\python.exe" -m daedalus.file_bridge watch --project daedalus_wt';
const LIVE_B = '"C:\\Users\\Administrator\\AppData\\Roaming\\uv\\python\\cpython-3.12-windows-x86_64-none\\python.exe"  -m daedalus.file_bridge watch --project daedalus_wt';

export function runWatcherSpec(): Result[] {
  const results: Result[] = [];
  const check = (name: string, ok: boolean, detail = '') => results.push({ name, ok, detail });

  const live: WatcherBlock = {
    running: true,
    stale_count: 0,
    watchers: [
      { pid: 45280, command: LIVE_A, stale: false },
      { pid: 9844, command: LIVE_B, stale: false }
    ]
  };

  // ---- 1. the basis travels with every answer ----------------------------
  // core.py finds watchers by matching command lines, so "running" cannot
  // mean "your outbox has an owner". Every reading carries that caveat.
  for (const [label, block] of [
    ['live', live], ['none', { running: false, watchers: [], stale_count: 0 }],
    ['missing', undefined], ['single', { running: true, watchers: [live.watchers![0]], stale_count: 0 }]
  ] as Array<[string, WatcherBlock | undefined]>) {
    check(`the ${label} reading says how detection works`,
      watcherReading(block).basis.includes('Kommandozeilen'), watcherReading(block).basis.slice(0, 50));
  }

  // ---- 2. an absent block is not "none" ----------------------------------
  // An unconsumed queue looks exactly like a healthy one until something
  // should have happened and did not.
  check('a dashboard with no watcher block is not reported as no watcher',
    watcherReading(undefined).text === 'nicht gemeldet', watcherReading(undefined).text);
  check('and is not green', watcherReading(undefined).tone === 'warn');

  // ---- 3. nothing running is the loud case -------------------------------
  const none = watcherReading({ running: false, watchers: [], stale_count: 0 });
  check('no matching process is a failure', none.tone === 'bad', none.tone);
  check('and says what that costs',
    none.basis.includes('bleiben liegen'), none.basis.slice(-40));
  // running:true with an empty list is the same fact, and reads the same.
  check('a claimed run with no processes is still no processes',
    watcherReading({ running: true, watchers: [], stale_count: 0 }).tone === 'bad');

  // ---- 4. more than one is stated, not hidden ----------------------------
  const two = watcherReading(live);
  check('two matches are counted', two.text.includes('2'), two.text);
  check('and flagged for a look', two.tone === 'warn', two.tone);
  // But NOT called a conflict: two checkouts each running their own watcher
  // is the ordinary case, and the lock is per-installation.
  check('without claiming they contend for one queue',
    two.basis.includes('mehrere Checkouts'), two.basis.slice(-45));
  const one = watcherReading({ running: true, watchers: [live.watchers![0]], stale_count: 0 });
  check('a single match is unremarkable', one.tone === '' && one.text.includes('1'), one.text);

  // ---- 5. staleness outranks the count -----------------------------------
  const stale = watcherReading({ ...live, stale_count: 1 });
  check('a stale watcher is the headline', stale.tone === 'bad', stale.tone);
  check('and both numbers are given', stale.text.includes('2') && stale.text.includes('1'), stale.text);

  // ---- 6. which tree each process belongs to -----------------------------
  // The distinguishing part of a 150-character command is the checkout.
  check('a worktree watcher names its worktree',
    watcherWhere(LIVE_A) === 'g1-ui-ikarus', watcherWhere(LIVE_A));
  // The uv path's last segment IS "python.exe", so the identifying part is
  // the one before it. Naming only the filename would distinguish nothing.
  check('a uv-managed interpreter is named by its build, not just "python.exe"',
    watcherWhere(LIVE_B) === 'cpython-3.12-windows-x86_64-none/python.exe',
    watcherWhere(LIVE_B));
  check('the two live watchers are distinguishable',
    watcherWhere(LIVE_A) !== watcherWhere(LIVE_B));
  check('an unreported command is not invented',
    watcherWhere('') === 'Kommandozeile nicht gemeldet');
  check('an unrecognised command is truncated rather than dropped',
    watcherWhere('some other command').length > 0);

  return results;
}
