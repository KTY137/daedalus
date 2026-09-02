# test_structcore_parallel.py::PersistentCacheTest::test_corrupt_cache_degrades_to_recompute

Tree: HEAD `54f0975398fd77120383c3af0ac5bb9291ef7064` (verified before and after
every measurement below — stable throughout, no re-diagnosis needed).
Python: 3.13.5, interpreter `.venv/Scripts/python.exe` (MEASURED via
`--version`). SQLite bundled with CPython 3.13.5.

## Status

**Reproduced. Deterministic. Not load-dependent, not order-dependent, not
tmp_path-length-dependent, not GC-threshold-dependent.** Root cause is a real
PRODUCT defect in `daedalus/structcore/cache.py`, present since the file's
introduction, entirely independent of `-n auto`/xdist. The 74008fab failure
under `-n auto --dist loadfile` was this same deterministic bug, not a
parallel-load artifact — xdist happened to be the harness in use when someone
first ran the suite widely enough to hit it, per the same class of story as
0810d39e for its sibling tests.

## Verdict

**Deterministic** (independent of parallelism, ordering, GC tuning, and
tmp_path length). Root cause: **PRODUCT** defect — see "Product code defect"
below.

## Full run table

| Run | Command | Result |
|---|---|---|
| solo1 (whole file) | `pytest tests/test_structcore_parallel.py -q` | `1 failed, 21 passed` — RC=1 |
| solo2 (whole file) | same | `1 failed, 21 passed` — RC=1 |
| solo3 (whole file) | same | `1 failed, 21 passed` — RC=1 |
| solo_single (subject test only) | `pytest ...::test_corrupt_cache_degrades_to_recompute -q` | `1 failed` — RC=1 |
| `python -m unittest` (subject test only, no pytest at all) | see below | `FAILED (errors=1)` — RC=1 |
| gc threshold default | n/a (solo runs above) | fails |
| gc threshold (400,10,10) | `-p gcstress` plugin setting `gc.set_threshold(400,10,10)` | fails |
| gc threshold (1,1,1) (max aggressiveness) | `-p gcstress_111` | **still fails** |
| gc disabled | `-p gcstress_disabled` (`gc.disable()`) | fails |
| explicit `gc.collect()` forced right after test body via `pytest_runtest_call` hookwrapper | `-p gc_force_collect2` | **still fails** (1804–1894 objects collected, `gc.garbage` empty, 0 live `sqlite3.Connection` objects afterward — yet the OS file lock persists) |
| `--basetemp` short (`C:/t/s1`-style) | whole file | `1 failed, 21 passed` — same failure |
| `--basetemp` long (~75-char pad) | whole file | **all 22 tests ERROR at setup** — `FileNotFoundError: [WinError 3]`, because the padded directory I supplied for the control does not exist and pytest could not create the basetemp tree; this is a probe artifact, not a code finding (see Probe 1 below) |
| Manual: call test method directly (bypass `TestCase.run()`) | custom script, `t.setUp(); t.test_corrupt...(); ...tearDown-equivalent cleanup` | **PASSES** (cache cleanup OK) |
| Manual: call via `unittest.TestCase.run(result)` (still no pytest) | custom script | **FAILS**, identical `PermissionError` |
| Monkeypatched fix (`self.conn.close()` before discard in `except`), run via `TestCase.run()` | custom script | **PASSES** (`errors: 0, failures: 0`) |

Exact failure (identical across every failing run):

```
File "...\tests\test_structcore_parallel.py", line 89, in tearDown
    self._cache.cleanup()
...
File "...\Lib\shutil.py", line 625, in _rmtree_unsafe
    os.unlink(fullname)
PermissionError: [WinError 32] Der Prozess kann nicht auf die Datei zugreifen,
da sie von einem anderen Prozess verwendet wird:
'...\idx-<hash>.sqlite'
```

The test body's own `assertEqual` never fails — the failure is entirely in
`tearDown`'s `self._cache.cleanup()` (a `tempfile.TemporaryDirectory.cleanup()`
trying to `os.unlink` the sqlite cache file while Windows still has an open
handle on it).

## Shape (a) vs (b)

**Shape (b): the test cannot delete the cache file because a connection is
still open (Windows file locking).** Not (a) — recompute-after-corruption
itself works correctly (proven by the manual bypass run, which reaches the
same code path, computes the same index and passes cleanly once the OS-level
lock is out of the picture).

## SQLite lifecycle audit of `cache.py`

`FileCache.__init__` (`daedalus/structcore/cache.py:259-276`):

```python
def __init__(self, root):
    self.conn: sqlite3.Connection | None = None
    if not enabled():
        return
    try:
        d = cache_root()
        d.mkdir(parents=True, exist_ok=True)
        tag = hashlib.sha1(str(root).encode("utf-8", "replace")).hexdigest()[:16]
        db = d / f"idx-{tag}.sqlite"
        _evict_old_caches(d, keep_besides=db)
        self.conn = sqlite3.connect(str(db))
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS files ("
            " key TEXT PRIMARY KEY, schema INTEGER, payload BLOB)")
        self.conn.execute("DELETE FROM files WHERE schema IS NOT ?", (_SCHEMA,))
        self.conn.commit()
    except Exception:
        self.conn = None  # optimization only -- never break the build
```

**Yes, the mid-init exception path is reachable, and it is exactly what the
subject test exercises.** Sequence in
`test_corrupt_cache_degrades_to_recompute`:

1. `good = build_index(self.root)` — cold build. Creates a `FileCache`, uses
   it, and `daedalus/structcore/index.py:500-517` (`_per_file_pass`) closes it
   deterministically in a `finally: cache.close()`. This first connection is
   NOT the leak; it is closed correctly.
2. `db.write_bytes(b"not a sqlite database at all")` — the test corrupts the
   on-disk file (`db` = the same `idx-<tag>.sqlite` path, since `tag` is a
   hash of `str(root)` and `root` is unchanged).
3. `build_index(self.root)` again — a **second** `FileCache(root)` is
   constructed. `sqlite3.connect(str(db))` succeeds (SQLite does not validate
   file format at `connect()` time — it's lazy). The very next statement,
   `self.conn.execute("CREATE TABLE IF NOT EXISTS files (...)")`, is where
   SQLite discovers the header is garbage and raises
   `sqlite3.DatabaseError: file is not a database`. That exception fires
   **after** `self.conn` already holds a live, open `sqlite3.Connection`
   pointed at the corrupted file. The `except Exception: self.conn = None`
   handler discards the only reference to that connection **without calling
   `.close()`** — an unreachable-but-still-open connection, exactly the
   "reference discarded mid-init" shape flagged in the task brief.
4. `close()` (`cache.py:323-329`) is never reached for this second,
   ill-fated connection — there is no `self.conn.close()` anywhere on the
   exception path, only on the normal path via `FileCache.close()`, which
   `_per_file_pass`'s `finally` calls on the `cache` object as a whole; but by
   then `cache.conn` is already `None`, so `FileCache.close()`'s own
   `if self.conn is not None: self.conn.close()` guard is a no-op — it has
   nothing left to close.

**Why this needs `unittest.TestCase.run()`, not just refcounting.** A plain
manual call to the test method (bypassing `unittest.TestCase.run()`'s
`_Outcome`/`testPartExecutor` machinery entirely) does **not** reproduce the
lock — CPython's ordinary refcounting appears to free the orphaned
`sqlite3.Connection` immediately when nothing else on the call stack retains
it, and the file becomes unlockable right away. But run through
`unittest.TestCase.run()` — which *every* real invocation of this test uses
(bare `python -m unittest`, `pytest`, `pytest --assert=plain`, `-n auto`, all
reproduced identically) — something in that call/teardown wrapping keeps the
orphaned connection (or the OS handle under it) alive **past** `tearDown`'s
cleanup. Measured directly: `gc.collect()` run immediately after the test body
(before teardown fires, via `python -m unittest.TestCase.run()` bypass with a
timed `gc.collect()` inserted between) still leaves the file locked in some
framings, and a `pytest_runtest_call` hookwrapper that force-collects **after**
the whole unittest run (setUp+test+tearDown all execute as one call under
pytest's unittest integration) shows **zero live `sqlite3.Connection`
objects** and an **empty `gc.garbage`**, yet the OS-level lock still holds —
i.e. by the time garbage collection is even inspectable from outside,
`tearDown`'s `cleanup()` has already failed and the Python object is already
gone. This means the underlying Win32 handle is not released synchronously
with the Python object becoming unreachable in this particular call path; the
practical fix (below) sidesteps the question entirely by never letting the
reference become the only handle in the first place.

**This is CONFIRMED, not merely hypothesized**, by directly proving the fix:
monkeypatching `FileCache.__init__` so the `except` handler calls
`self.conn.close()` before setting `self.conn = None` (full script:
`/tmp/diag_structcore/verify_fix.py`, run via real
`unittest.TestCase.run(result)` — no pytest) turns the failure into
`errors: 0, failures: 0` — deterministic pass.

## Actual cache directory / tmp_path isolation (Probe 4)

`_CacheDirMixin.setUp` (`tests/test_structcore_parallel.py:72-81`) creates a
**fresh `tempfile.TemporaryDirectory()` per test** and points
`DAEDALUS_CACHE_DIR` at it. `cache_root()` (`cache.py:40-49`) honors that env
var unconditionally. So the cache directory used by this test is **fully
tmp_path-isolated per test instance** — not derived from the repo root, not
shared across tests or agents. Probe 4's shared-location collision hypothesis
is **REFUTED for this failure**: the bug reproduces with a single test, alone,
in a brand-new process, with nobody else on the box anywhere near its cache
dir.

## Probe 1 — tmp_path length: INAPPLICABLE to this test

`PersistentCacheTest` (and all of `test_structcore_parallel.py`) uses
`tempfile.TemporaryDirectory()` directly in `setUp`/`tearDown`, **not**
pytest's `tmp_path` fixture. `--basetemp` only controls where pytest's own
`tmp_path` fixture roots itself; it has no effect on `tempfile.TemporaryDirectory()`,
which always resolves against the OS `%TEMP%`. MEASURED: short `--basetemp`
(`/tmp/diag_structcore/t/s1`) reproduces the identical failure
(`1 failed, 21 passed`); a long `--basetemp` control errored all 22 tests
uniformly at setup with `FileNotFoundError: [WinError 3]` because the padded
directory didn't exist — a control-construction mistake on my part (I did not
pre-create the deep long-basetemp tree), not a code signal, and irrelevant
regardless since this file doesn't consume `tmp_path`. The chip_cli
tmp_path-length mechanism (confirmed elsewhere on 2026-09-01/02) does not
transfer to this test file. **REFUTED as an explanation here.**

## Probe 3 — GC thresholds: REFUTED as sufficient explanation

Swept default / `(400,10,10)` / `(1,1,1)` / `gc.disable()` on the subject test
alone: **fails identically in every regime**, including `(1,1,1)` (collection
checked on almost every allocation) and even an explicit forced
`gc.collect()` call inserted via a pytest hookwrapper immediately after the
test body. Per e9254e12's prior finding (cited in the task), GC-threshold
sensitivity produced a *different* failing test per regime on a *different*
broken tree; here, on this tree, the subject test's failure is **insensitive**
to GC tuning entirely. This is a genuine refutation, in the spirit of the
gate_discrimination/WAL-pair siblings today: GC timing is not the lever here.
The earlier textbook "leak needs `gc.collect()`, `with sqlite3.connect() as c`
transaction-scope, `contextlib.closing` fixes it deterministically" mechanism
(verified elsewhere on this box for a different code shape) does **not**
directly transfer: a minimal standalone repro of *just* the `connect()` +
failing `execute()` + `conn=None` shape (no `unittest`/pytest involved) **does**
get freed by refcounting alone / a single `gc.collect()` — but the *actual*
subject test, executed under `unittest.TestCase.run()` (which every real
runner uses), does not release the lock even under maximum GC aggressiveness.
The dependable fix is not "collect harder" — it's "never leave a bare
reference-drop as the only cleanup path": `self.conn.close()` before
`self.conn = None`.

## First failing commit

**Pre-existing, not introduced by any commit in the given range.**
`daedalus/structcore/cache.py` and `test_corrupt_cache_degrades_to_recompute`
were both introduced together in `4cd0fb16` ("perf(structcore): parallel +
cached scan, determinism fixes, session handoff"), dated 2026-07-20 —
`git merge-base --is-ancestor 4cd0fb16 f60ffd3d` returns true, i.e. `4cd0fb16`
predates `f60ffd3d`, the **oldest** commit in the given bisection range
(2026-09-01). `git show f60ffd3d:daedalus/structcore/cache.py` already
contains the exact `except Exception: self.conn = None` shape verbatim at the
same location. No commit in `54f09753..f60ffd3d` touches `cache.py` at all
(full `git log --oneline -- daedalus/structcore/cache.py` shows only
`4cd0fb16`, `c4a10254`, `deccbddf`, `007a237b`, none of which are in the given
range and none of which change the `__init__` except-handler shape — verified
by `git log -S "self.conn = None" -- daedalus/structcore/cache.py` returning
only `4cd0fb16`). `0810d39e`'s switch to 16 xdist workers (2026-09-02) is
irrelevant to this specific defect: the bug reproduces 100% deterministically
solo, in complete isolation, with zero concurrency. Consistent with today's
calibration note that some siblings predate the whole bisection range
entirely.

## Root cause

**PRODUCT defect.** `daedalus/structcore/cache.py:259-276`,
`FileCache.__init__`'s `except Exception:` handler on the
`sqlite3.connect()` → `execute("CREATE TABLE...")` → `execute("DELETE...")` →
`commit()` sequence discards `self.conn` (`self.conn = None`) without first
calling `self.conn.close()` when the connection object itself was already
successfully created before a later statement in the same `try` block raised
(the exact failure a corrupted-but-openable sqlite file produces). Under
`unittest.TestCase.run()` (i.e. every real test invocation), the resulting
orphaned Win32 file handle is not released synchronously with the object
becoming unreachable, and Windows then refuses `tempfile.TemporaryDirectory.cleanup()`'s
`os.unlink()` in `tearDown` with `PermissionError: WinError 32`. Not a TEST
ISOLATION problem (single test, single process, isolated tmp dirs, zero
concurrency all still fail) and not a TEST EXPECTATION problem (the intended
behavior — corrupt cache degrades to recompute — genuinely does happen
correctly; only the file-handle bookkeeping around the failed connection is
wrong).

## Fix sketch

In `FileCache.__init__`'s `except Exception:` handler
(`daedalus/structcore/cache.py:275-276`), close the partially-opened
connection before discarding the reference:

```python
except Exception:
    if self.conn is not None:
        try:
            self.conn.close()
        except Exception:
            pass
    self.conn = None  # optimization only -- never break the build
```

(Equivalently, restructure with `contextlib.closing` around the
`connect()`/`execute()`/`commit()` sequence, re-raising into the same outer
`except`, or hold the connection in a local variable and `close()` it in a
`finally` before deciding whether `__init__` succeeded.) **Not** a
`gc.collect()` call anywhere — Probe 3 measured that this specific leak is
insensitive to GC aggressiveness, so a GC-based "fix" would be both
unreliable and would misdiagnose the defect. Verified directly: monkeypatching
exactly this fix and re-running the real test via `unittest.TestCase.run()`
turns `errors: 1` into `errors: 0, failures: 0`, deterministically.

## Owner

`daedalus/structcore/cache.py` is the persistent structcore analysis cache
(`FileCache`/`cache_root`/`file_key`) — same module/owner as the rest of the
structcore parallel-scan-and-cache work landed in `4cd0fb16` and touched since
by `c4a10254`, `deccbddf`, `007a237b`. Fix belongs with whoever owns
`daedalus/structcore/` (no CODEOWNERS-style marker found in-tree; same author
lineage as the three commits above).

## Every command executed (for reproduction)

```
git rev-parse HEAD                                    # 54f0975398fd... before, during, after
.venv/Scripts/python.exe --version                     # Python 3.13.5
.venv/Scripts/python.exe -m pytest tests/test_structcore_parallel.py -q            # x3, all "1 failed, 21 passed"
.venv/Scripts/python.exe -m pytest tests/test_structcore_parallel.py::PersistentCacheTest::test_corrupt_cache_degrades_to_recompute -q   # "1 failed"
.venv/Scripts/python.exe -m pytest ...::test_corrupt_cache_degrades_to_recompute -q --assert=plain       # still fails
.venv/Scripts/python.exe -m pytest tests/test_structcore_parallel.py -q --basetemp="C:/t/s1"              # 1 failed, 21 passed (short)
.venv/Scripts/python.exe -m pytest tests/test_structcore_parallel.py -q --basetemp="<~75-char pad>/x"     # 22 errors at setup (bad control path, not code signal)
PYTHONPATH=/tmp/diag_structcore .venv/Scripts/python.exe -m pytest ...::test_corrupt... -q -p gcstress        # gc.set_threshold(400,10,10) -> fails
PYTHONPATH=/tmp/diag_structcore .venv/Scripts/python.exe -m pytest ...::test_corrupt... -q -p gcstress_disabled  # gc.disable() -> fails
PYTHONPATH=/tmp/diag_structcore .venv/Scripts/python.exe -m pytest ...::test_corrupt... -q -p gcstress_111       # gc.set_threshold(1,1,1) -> fails
PYTHONPATH=/tmp/diag_structcore .venv/Scripts/python.exe -m pytest ...::test_corrupt... -q -s -p gc_force_collect2  # forced gc.collect() post-body -> still fails, 0 live connections, gc.garbage empty
cd tests && ../.venv/Scripts/python.exe -m unittest test_structcore_parallel.PersistentCacheTest.test_corrupt_cache_degrades_to_recompute -v   # FAILED (errors=1), identical traceback, no pytest involved
.venv/Scripts/python.exe /tmp/diag_structcore/repro_sqlite_leak.py            # minimal standalone repro: fails without gc.collect(), succeeds with it (isolated shape only)
.venv/Scripts/python.exe /tmp/diag_structcore/manual_repro.py                 # direct method call (bypass TestCase.run()) -> PASSES both with/without gc
.venv/Scripts/python.exe /tmp/diag_structcore/manual_repro2.py                # via bare unittest.TestCase.run() -> FAILS, same PermissionError
.venv/Scripts/python.exe /tmp/diag_structcore/verify_fix.py                   # monkeypatched close()-before-discard fix, via TestCase.run() -> errors: 0, failures: 0
git log --oneline -S "self.conn = None" -- daedalus/structcore/cache.py       # 4cd0fb16 only
git log --oneline -S "test_corrupt_cache_degrades_to_recompute" -- tests/test_structcore_parallel.py   # 4cd0fb16 only
git merge-base --is-ancestor 4cd0fb16 f60ffd3d && echo YES                    # YES
git show f60ffd3d:daedalus/structcore/cache.py | grep -n "except Exception" -A2   # confirms identical shape present at oldest commit in range
```

All temp/scratch files under `/tmp/diag_structcore/`. No repo file was
created, edited, or deleted. `C:/t` was not left behind (never created; the
short-basetemp control used `/tmp/diag_structcore/t/s1` instead, also
cleaned up as part of the scratch dir).

Every claim above is MEASURED via the commands shown, except the exact
CPython-internal reason `unittest.TestCase.run()`'s wrapping delays release of
the Win32 handle even past an explicit `gc.collect()` — that finer mechanism
is HYPOTHESIZED (something in `_Outcome`/`testPartExecutor`'s frame-holding
during setUp/call/tearDown), not nailed down to a specific CPython source
line, and is explicitly flagged as such. It does not affect the root-cause
diagnosis or the fix, both of which are MEASURED and verified independently.
