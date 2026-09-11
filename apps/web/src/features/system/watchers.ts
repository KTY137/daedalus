/**
 * WHO IS ACTUALLY CONSUMING THE QUEUE.
 *
 * `/api/dashboard` carries a `watcher` block that `daedalus/core.py` builds by
 * SCANNING PROCESS COMMAND LINES:
 *
 *     for row in _process_rows():
 *         cmd = row["command"]
 *         if "daedalus.file_bridge" not in cmd or "watch" not in cmd:
 *             continue
 *
 * That is the whole detection. It means `running: true` says "a process whose
 * command line matches exists on this machine" -- NOT "something owns your
 * outbox". The two are different, and the difference is not academic:
 *
 *   - `file_bridge.watch()` runs "under one OS-held watcher claim"
 *     (`with watcher_lock(watcher_lock_path)`), and that lock lives beside
 *     HEARTBEAT_PATH, which is derived from the installation ROOT. Two
 *     checkouts have two locks, two outboxes, and two heartbeats -- and both
 *     processes match this scan.
 *   - Measured on this machine 2026-09-03: two matches for one project, from
 *     two different interpreters (`.venv/Scripts/python.exe` and a uv-managed
 *     one), both `stale: false`.
 *
 * So the honest statement is the count plus the commands, labelled as what it
 * is. Claiming "2 watchers on your queue" would assert an ownership this data
 * cannot establish; claiming "running" and stopping there hides that there is
 * more than one.
 *
 * `stale` is the backend's own flag, and its rule is narrow: a command with
 * `--repo-root` but no `--project`, or one naming neither this project nor its
 * repo root. core.py escalates it -- "Stop it before queueing more work."
 */

export interface WatcherProcess {
  pid: number;
  command: string;
  stale: boolean;
}

export interface WatcherBlock {
  running?: boolean;
  watchers?: WatcherProcess[];
  stale_count?: number;
}

export interface WatcherReading {
  /** the headline, phrased as what the scan can actually support */
  text: string;
  tone: string;
  /** the caveat, always present: this is a process scan */
  basis: string;
}

/**
 * The headline.
 *
 * `undefined` is not "none": a dashboard that never carried the block has not
 * told us there is no consumer, and an unconsumed queue looks exactly like a
 * healthy one until something should have happened and did not.
 */
export function watcherReading(block: WatcherBlock | undefined): WatcherReading {
  const basis = 'Erkannt durch Abgleich der Prozess-Kommandozeilen, nicht durch '
    + 'Besitz der Outbox: Prozesse aus anderen Checkouts passen auf dieselbe Suche.';

  if (!block || block.running === undefined) {
    return { text: 'nicht gemeldet', tone: 'warn', basis };
  }
  const found = (block.watchers || []).length;
  const stale = typeof block.stale_count === 'number' ? block.stale_count : 0;

  if (!block.running || found === 0) {
    return {
      text: 'kein passender Prozess gefunden',
      tone: 'bad',
      basis: basis + ' Eingereihte Aufgaben bleiben liegen, bis einer läuft.'
    };
  }
  if (stale > 0) {
    return {
      text: found === 1
        ? '1 Prozess, hängengeblieben'
        : `${found} Prozesse, davon ${stale} hängengeblieben`,
      tone: 'bad',
      basis
    };
  }
  if (found > 1) {
    return {
      text: `${found} passende Prozesse`,
      tone: 'warn',
      basis: basis + ' Mehr als einer ist hier normal, wenn mehrere Checkouts laufen.'
    };
  }
  return { text: '1 passender Prozess', tone: '', basis };
}

/**
 * A watcher's command, shortened to the part that identifies WHICH tree it
 * belongs to.
 *
 * The full line is an absolute interpreter path plus module and flags; on this
 * machine that is over 150 characters and the distinguishing part -- the
 * checkout -- sits in the middle. The interpreter is kept because it is what
 * actually differed between the two live matches.
 */
export function watcherWhere(command: string): string {
  const text = String(command || '');
  if (!text) return 'Kommandozeile nicht gemeldet';
  // A checkout name is the best anchor: it says which tree this watcher
  // serves. `<tree>/.venv/Scripts/python.exe` and `worktrees/<tree>/` both
  // yield it.
  const worktree = text.match(/[\\/]([^\\/"]+)[\\/]\.venv[\\/]/)
    || text.match(/worktrees[\\/]([^\\/"]+)/);
  if (worktree) return worktree[1];

  // Otherwise name the interpreter by its PARENT directory as well as its
  // filename, and get there by PARSING rather than matching. Two regex
  // attempts got this wrong in opposite ways: one required a character before
  // "python.exe" and so never fired on a uv path whose last segment is
  // exactly that; the next matched the FIRST `.../uv/python/...` and returned
  // "uv/python", which identifies nothing. The distinguishing part of
  // `...\Roaming\uv\python\cpython-3.12-windows-x86_64-none\python.exe` is
  // the second-to-last segment, so take the tail and stop guessing.
  const executable = (text.match(/^\s*"([^"]+)"/) || [])[1] || text.split(/\s+/)[0] || '';
  const segments = executable.split(/[\\/]/).filter(Boolean);
  if (segments.length >= 2) return segments.slice(-2).join('/');
  if (segments.length === 1) return segments[0];

  return text.slice(0, 60);
}
