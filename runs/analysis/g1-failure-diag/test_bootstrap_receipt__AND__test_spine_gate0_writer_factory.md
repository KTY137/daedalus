# Diagnosis: test_bootstrap_receipt.py / test_spine_gate0_writer_factory.py paired WAL-companion suspects

Base at start: `851ff43cc63dd788d1da63a6f7fa44fcc6ed0291` (main).
Interpreter: `.venv/Scripts/python.exe` -> `3.13.5 (tags/v3.13.5:6cb20a2, Jun 11 2025, ...) [MSC v.1943 64 bit (AMD64)]` [MEASURED].

**Tree-drift note (honesty, per protocol).** All solo runs (A x3, B x2/x3) were paired
with `git rev-parse HEAD` immediately before and after each pytest invocation; every
one of those 10 checks read `851ff43c` [MEASURED, `head_A1/A2/A3/B1/B2*.txt`]. The
shared checkout then moved (other agents on the box) to `b3cc415b` before the GC
sweep block started, and moved again to `54f0975398fd77120383c3af0ac5bb9291ef7064`
by the time this report was written. Checked whether that drift voids the GC sweep:

```
git diff --stat 851ff43c..HEAD
 docs/architecture/import-boundaries.json |  15 +-
 docs/architecture/target-layout.md       | 520 ++++++++++++++++++++
 tests/test_architecture_boundaries.py    |  70 +++-
```

None of the two subject files or their production dependencies are in that diff.
Confirmed byte-identical by blob hash between `851ff43c` and current HEAD for all
six files touched by this diagnosis:
`tests/test_bootstrap_receipt.py`, `tests/test_spine_gate0_writer_factory.py`,
`daedalus/kernel/offload_lease.py`, `daedalus/spine/durability.py`,
`tools/bootstrap_receipt.py`, `daedalus/ignition/gate1.py` — all `IDENTICAL`
[MEASURED, `git rev-parse 851ff43c:<path>` vs `git rev-parse HEAD:<path>`]. The GC
sweep is therefore treated as valid evidence for `851ff43c`, not void, because the
only unrelated drift happened in files this diagnosis never reads.

---

## Subject A — `tests/test_bootstrap_receipt.py::TheLeasedSingleAttempt::test_leased_single_run_terminalises_and_reports`

### Status at 851ff43c: FAILS, 100% reproducible, deterministic. NOT a WAL/GC artifact.

### Verdict + run table [MEASURED]

Command pattern:
`.venv/Scripts/python.exe -m pytest "tests/test_bootstrap_receipt.py::TheLeasedSingleAttempt::test_leased_single_run_terminalises_and_reports" -q`

| Run | HEAD before | HEAD after | Result | Time |
|---|---|---|---|---|
| solo 1 | 851ff43c | 851ff43c | FAILED — `AssertionError: 2 != 0` | 0.61s |
| solo 2 | 851ff43c | 851ff43c | FAILED — same | 0.63s |
| solo 3 | 851ff43c | 851ff43c | FAILED — same | 0.71s |

GC-threshold sweep, **full file** (`tests/test_bootstrap_receipt.py`, 28 tests),
`PYTHONPATH=/tmp/diag_walpair .venv/Scripts/python.exe -m pytest tests/test_bootstrap_receipt.py -q -p gcstress`
with `/tmp/diag_walpair/gcstress.py` reading `GCSTRESS_THRESHOLD` env var:

| GC regime | Result | Failing node(s) |
|---|---|---|
| default | 1 failed, 27 passed, 4 subtests passed (2.05s) | `TheLeasedSingleAttempt::test_leased_single_run_terminalises_and_reports` |
| (400,10,10) | 1 failed, 27 passed, 4 subtests passed (2.15s) | same |
| (300,10,10) | 1 failed, 27 passed, 4 subtests passed (2.25s) | same |
| (1,1,1) | 1 failed, 27 passed, 4 subtests passed (2.25s) | same |

The failing set is **identical across all four regimes** — one node, always the
same node, same message every time.

### WAL hypothesis: **REFUTED** for this subject

No movement of the pass/fail set under any GC-threshold regime, solo or in the
full file. The failure is not timing-, order-, or load-dependent; it is a plain
deterministic assertion failure. The actual captured stdout on every run:

```
state              : lease_refused (no worktree, no runner)
  deny             : spine.intent_ledger: no repository-confined intent-ledger path
                      resolver port was composed; the lease is refused before any
                      SQLite access
```

i.e. the guard refuses **before any SQLite access happens at all** — there is no
sqlite3 connection, no `-wal` file, nothing for GC timing to touch in this path.

### First failing commit: `bce1066e` "refactor: inject intent ledger path port" (2026-08-31T19:43:51+02:00)

Archaeology (`git show`, `git log -S`, `git merge-base --is-ancestor`, no checkout):

- The guard that refuses is `daedalus/kernel/offload_lease.py::_intent_ledger_decision`
  (around line 2181): `if ledger_path_resolver is None: return GuardDecision(..., False, "no repository-confined intent-ledger path resolver port was composed; the lease is refused before any SQLite access")`.
- `git log --oneline -- daedalus/kernel/offload_lease.py | grep -i "intent.ledger"` finds
  exactly one commit: `bce1066e`.
- `git show --stat bce1066e`:
  ```
  daedalus/ignition/gate1.py                         |   4 +
  daedalus/kernel/offload_lease.py                   |  64 ++++++---
  .../G1-HIER-07A_IMPORT_SCC_LEDGER_PATH_PORT.md     | 149 ++++++++++
  tests/contracts/test_import_scc_hierarchy.py       | 146 ++++++++++
  tests/kernel/test_attempt_lease.py                 |  33 +++
  ```
  `bce1066e` made `intent_ledger_path_resolver` load-bearing (None => hard
  refusal) and wired the ONE production caller it updated,
  `daedalus/ignition/gate1.py:933` (`intent_ledger_path_resolver=(spine_picker.resolve_spine_db_path)`).
  It never touched `tools/bootstrap_receipt.py`.
- `bce1066e` is an ancestor of `851ff43c` and sits at first-parent index 39 from
  `851ff43c` — i.e. it is **older** than the entire 24-commit chain given in the
  task (which runs from `851ff43c` idx=1 back to `f60ffd3d` idx=24). It predates
  `74008fab` (idx=2) by more than a day.
- The test class itself, `TheLeasedSingleAttempt`, was added by `eae9f72e`
  (2026-08-24T07:45:59+02:00, "spine: the attempt door consumes the lease it is
  handed..."), confirmed an ancestor of `bce1066e`
  (`git merge-base --is-ancestor eae9f72e bce1066e` -> yes). So the test passed
  for about a week, then broke at `bce1066e` and has stayed broken through every
  commit up to and including `851ff43c`.

Net: this is a stale, **long-standing** regression (11+ days old at `851ff43c`),
not something newly exposed by the `0810d39e` parallelization commit or by the
`dc321950` sqlite-leak sweep. It only *looks* like a fresh WAL-companion flake
because it was caught in the same `-n auto --dist loadfile` run as Subject B.

### Root cause: PRODUCT code (missing wiring), not the test

`tools/bootstrap_receipt.py`'s `--leased` path (around line 531) calls:

```python
lease = acquire_attempt_lease(
    target, source_revision=str(head), mission_id=f"bootstrap-{task_id}",
    attempt_id=attempt.branch, effect_key=attempt.branch,
    writable_paths=tuple(paths or ()), contained=True,
    containment_evidence=(...), worktree_root=attempt._manager.worktree_root,
)
```

No `intent_ledger_path_resolver=` keyword. `acquire_attempt_lease` forwards
`**kwargs` to `acquire_effect_lease`, whose `intent_ledger_path_resolver`
parameter defaults to `None` (`daedalus/kernel/offload_lease.py:2406`), which
`_intent_ledger_decision` then refuses outright (`daedalus/kernel/offload_lease.py:2181-2187`).
The one other production caller, `daedalus/ignition/gate1.py:906-939`, passes
`intent_ledger_path_resolver=spine_picker.resolve_spine_db_path` and is fine —
confirmed by `grep -rn ledger_path_resolver daedalus/` returning exactly those
two call sites (`gate1.py` composed, `offload_lease.py` the guard) and zero
matches in `tools/`.

### Fix sketch

Add `intent_ledger_path_resolver=<repo-confined spine-db path resolver>` to the
`acquire_attempt_lease(...)` call in `tools/bootstrap_receipt.py` (~line 531),
following the `gate1.py:933` pattern (`spine_picker.resolve_spine_db_path` or the
equivalent picker already used to locate `target`'s spine DB). Not a `gc.collect()`
fix — there is no leaked resource involved in this failure at all.

### Owner

`tools/bootstrap_receipt.py` / `daedalus/kernel/offload_lease.py` wiring —
spine/kernel owner (core-dev lane).

---

## Subject B — `tests/test_spine_gate0_writer_factory.py::test_factory_is_only_an_opening_profile_not_a_second_ledger_authority`

### Status at 851ff43c: FAILS, 100% reproducible, deterministic. NOT a WAL/GC artifact.

### Verdict + run table [MEASURED]

Command pattern:
`.venv/Scripts/python.exe -m pytest "tests/test_spine_gate0_writer_factory.py::test_factory_is_only_an_opening_profile_not_a_second_ledger_authority" -q`

| Run | HEAD before | HEAD after | Result | Time |
|---|---|---|---|---|
| solo 1 | 851ff43c | 851ff43c | FAILED — `AssertionError` on dunder set diff | 0.42s |
| solo 2 | 851ff43c | 851ff43c | FAILED — same | 0.33s |

GC-threshold sweep, **full file** (`tests/test_spine_gate0_writer_factory.py`, 8 tests):

| GC regime | Result | Failing node(s) |
|---|---|---|
| default | 1 failed, 7 passed (0.42s) | `test_factory_is_only_an_opening_profile_not_a_second_ledger_authority` |
| (400,10,10) | 1 failed, 7 passed (0.40s) | same |
| (300,10,10) | 1 failed, 7 passed (0.47s) | same |
| (1,1,1) | 1 failed, 7 passed (0.39s) | same |

Identical failing set across all four regimes; the leaking neighbour in the same
file, `test_factory_writer_remains_compatible_with_canonical_transactions`
(line 171, `with sqlite3.connect(path) as connection:`), never turns red in any
regime either, and the subject fails solo (before that neighbour ever runs in
file order) exactly as often as in the full file.

### WAL hypothesis: **REFUTED** for this subject

The failing assertion is:

```python
assert set(subclass.__dict__) - {
    "__module__", "__doc__", "_apply_pragmas",
} == set()
# AssertionError: assert {'__firstlineno__', '__static_attributes__'} == set()
```

`subclass` here is `daedalus.spine.durability._Gate0OpeningSpineLedger`, a plain
Python class — no sqlite3 connection, no file I/O, no WAL companion anywhere in
this test. Confirmed the extra keys are unconditional CPython 3.13 behavior, not
anything the repository or its tests control:

```
.venv/Scripts/python.exe -c "
class Empty: pass
print(sorted(Empty.__dict__.keys()))"
-> ['__dict__', '__doc__', '__firstlineno__', '__module__', '__static_attributes__', '__weakref__']
```

Every class body compiled under this interpreter gets `__firstlineno__` and
`__static_attributes__` injected into `__dict__`, empty class or not. The test's
allowlist (`{"__module__", "__doc__", "_apply_pragmas"}`) does not account for
either, so it fails on every run, on every worker, under any scheduling — GC
threshold is structurally irrelevant to this code path.

### First failing commit / interpreter dependency

`git log -S"test_factory_is_only_an_opening_profile_not_a_second_ledger_authority" -- tests/test_spine_gate0_writer_factory.py`
finds exactly one commit: `bde0d0e1` "test(g0): verify pre-migration FULL writer
factory" (2026-08-04T02:40:17+02:00). `git show bde0d0e1 -- tests/test_spine_gate0_writer_factory.py`
shows the same allow-set (missing both dunders) was present at introduction.

This is **not bisected** in the commit sense the task otherwise asks for: the
proximate cause is the fixed, pinned CPython 3.13.5 interpreter's class-creation
behavior (an environment property external to any commit in the given
`851ff43c .. f60ffd3d` chain, and external to `bde0d0e1` too), not a code change
in this repository. Determining whether the test ever passed historically would
require running the introducing revision under a *different* Python version,
which this task's read-only/no-checkout constraint does not permit and which
falls outside "diagnose two test failures at 851ff43c" scope. What is measured:
the exact same broken allow-set has existed unchanged since `bde0d0e1`
(2026-08-04), so on the currently installed interpreter (3.13.5) this test has
never passed at any commit between `bde0d0e1` and `851ff43c`.

### Root cause: TEST expectation (stale for the installed interpreter), not product code

`daedalus/spine/durability.py::_Gate0OpeningSpineLedger` itself is fine — the
test is asserting a property of Python's own class machinery that changed
between interpreter versions, and the assertion was written for an interpreter
that doesn't add `__firstlineno__`/`__static_attributes__`. Product code is not
implicated.

### Fix sketch

Add `"__firstlineno__"` and `"__static_attributes__"` to the allowed set at
`tests/test_spine_gate0_writer_factory.py:145-149`, e.g.:

```python
assert set(subclass.__dict__) - {
    "__module__", "__doc__", "_apply_pragmas",
    "__firstlineno__", "__static_attributes__",
} == set()
```

(or derive the baseline dynamically from an empty control class defined in the
same file, so a future interpreter bump can't silently reintroduce this drift).
Not a `gc.collect()` fix — there is no leaked resource in this failure either.

### Owner

`tests/test_spine_gate0_writer_factory.py` — test-dev lane (whoever owns the
Gate-0 durability test suite).

---

## Cluster

Both subjects are red at `851ff43c`, both are **100% deterministic** (identical
result across 3 solo runs each and across all four GC-threshold regimes,
full-file), and the canonical WAL/GC-timing mechanism (`with sqlite3.connect(p) as conn:`
leaving a live `-wal` companion until the generational collector runs) is
**REFUTED as the cause for both**. Neither failing test's code path opens a
sqlite3 connection or stats a `-wal` file at the point of failure. The two were
paired as "WAL-companion suspects" purely because they co-failed in the same
`-n auto --dist loadfile` run at `74008fab`; that pairing conflated two
unrelated, unrelated-in-cause, independently-reproducible defects:

- **A** — an 11-day-old product wiring gap (`bce1066e`, 2026-08-31): a new
  mandatory `intent_ledger_path_resolver` port was added to the lease guard and
  wired into `daedalus/ignition/gate1.py`, but `tools/bootstrap_receipt.py`'s
  `--leased` path was never updated to compose it, so every leased bootstrap
  attempt is refused before touching SQLite at all.
- **B** — a test assertion stale against the pinned CPython 3.13.5 interpreter
  since its introduction (`bde0d0e1`, 2026-08-04): Python 3.13 unconditionally
  adds `__firstlineno__` and `__static_attributes__` to every class `__dict__`,
  which the test's hard-coded allowlist never accounted for.

Subject B's own file does contain a leaking `with sqlite3.connect(path) as
connection:` (line 171, `test_factory_writer_remains_compatible_with_canonical_transactions`),
matching the sweep's "39 sites / 21 files" population — but it is a different
test, runs after the subject in file order, and was confirmed (solo run, GC
sweep) to have zero effect on the subject. The `dc321950` sqlite-leak sweep
merged into `851ff43c` is therefore orthogonal to both failures reported here:
it did not cause them, and it will not fix them. Both need code fixes, not a
GC/WAL remediation, and are unrelated to each other beyond having been observed
in the same historical parallel run.
