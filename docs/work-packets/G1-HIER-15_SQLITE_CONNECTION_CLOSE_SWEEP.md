# G1-HIER-15 — The eleven remaining leaked sqlite connections, closed with per-site write analysis and two detectors

> **This is a retroactive record.** G1-HIER-15 was built, verified and merged
> without a packet document. This file was written afterwards, on
> 2026-09-02, from the merged commits named below. It records measured
> history; it does not reconstruct intent. The sections a live packet freezes
> *pre-build* — acceptance matrix, forbidden paths, budget, review questions —
> did not exist while this packet ran, and each such section says so.

## Frozen packet metadata

- Packet ID: G1-HIER-15
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 74008fabad9c93b582f87e8ecac35f72938fa905
- Dependencies: G1-HIER-14
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

Status: builder-verified and **merged**. This metadata block is retroactive.
The base revision is recovered as `dc321950^` and is exact — it is the
G1-HIER-14 follow-up merge, which is also the sole dependency: `dc321950`
states it "completes the defect class opened by `e9254e12`, which fixed two
sites in `daedalus/kernel/effects.py` and reported eleven survivors."

Commits of record:

| role | commit |
| --- | --- |
| implementation | `dc3219506029fac6dc869af47cdb7a7f06f85e0e` |
| merge | `851ff43cc63dd788d1da63a6f7fa44fcc6ed0291` |

Digest provenance is identical to G1-HIER-14's: master-plan digest
`[MEASURED]` at `d17ea2fc`; effect-registry digest `[INHERITED]` as the
Revision-11 constant shared by 61 packet documents, not re-derived.

## Primary acceptance claim

All eleven remaining sites of the leaked-sqlite-connection defect are closed,
across four files: `daedalus/kernel/approvals.py` (3),
`daedalus/kernel/effect_recovery.py` (1),
`daedalus/runtimes/provider_observation.py` (2), and
`daedalus/runtimes/trust_store.py` (5). No behavioural change was needed at
any of them.

**Verified independently at `d17ea2fc`, not taken from the commit report**
`[MEASURED]`. All eleven `connection.close()` calls exist at the exact lines
the mutation matrix names:

```console
$ grep -rnE 'with .*connect\(' daedalus/ --include=*.py
daedalus/kernel/offload_lease.py:2204:        with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
```

The commit's own enumeration pattern now returns exactly **one** match — the
`contextlib.closing` site that was correctly classified as not-the-defect.
`dc321950` reported twelve matches at its base, eleven of them the defect.
Twelve minus eleven is one, and that one is still here. The enumeration
reconciles exactly.

## Scope

**Not frozen pre-build.** Recovered from the diff of `dc321950`
`[MEASURED: git show --stat]`: 8 files changed, 419 insertions, 11 deletions.

| file | ± | role |
| --- | --- | --- |
| `daedalus/kernel/approvals.py` | +28/-… | 3 sites |
| `daedalus/kernel/effect_recovery.py` | +14 | 1 site |
| `daedalus/runtimes/provider_observation.py` | +27 | 2 sites |
| `daedalus/runtimes/trust_store.py` | +53 | 5 sites |
| `tests/kernel/test_owner_approval.py` | +67 | new test |
| `tests/kernel/test_effect_recovery.py` | +77 | new test |
| `tests/runtimes/test_provider_observation_authority.py` | +69 | new test |
| `tests/runtimes/test_runtime_trust_store.py` | +95 | new test |

Four source files, four test files — one new test per affected file, each
executing the real path.

Forbidden paths were never declared. What the diff shows: nothing outside
these eight files changed, and `daedalus/kernel/effects.py` — the file fixed
by the parent commit and used here as the control — was not touched again.

## Contracts and behavior

### The defect

`with sqlite3.connect(p) as conn` is a **transaction** scope, not a closing
scope: it commits, it does **not** close. Re-measured in this packet on
Python 3.13.5 / SQLite 3.49.1 `[INHERITED: dc321950]`:

```text
with sqlite3.connect(p) as c: ...   -> c.execute() still works afterwards
-wal exists while a connection open -> True
-wal exists after an explicit close -> False
```

A leaked connection is unreachable garbage held in a reference cycle, so
refcounting never finalises it at method exit; only the generational collector
does, at a moment decided by unrelated allocation. Anything that stats a WAL
companion then sees a file that can vanish between an `exists()` check and a
`resolve(strict=True)`. That is the failure G1-HIER-14's follow-up
(`e9254e12`) diagnosed and fixed at two sites; this packet closes the rest.

### Enumeration, re-derived rather than inherited

`dc321950` did not take the site list from the parent commit's report. It
re-ran `with .*connect(` over `daedalus/`, got twelve matches, and classified
the twelfth (`offload_lease.py:2204`, already wrapped in
`contextlib.closing`) as correct. The eleven survivors were "exactly the
reported set, at the reported lines" — so the independent enumeration and the
inherited claim agreed, which is the only reason the inherited claim is
usable.

### Proven by execution, per file, before and after — with TWO detectors

This is the packet's methodological core. A companion-only probe would have
been vacuous on two of the four files, so a second detector was added: on
Windows an open SQLite handle blocks renaming the database file. The
already-fixed `EffectLeaseLedger` is the control.

`[INHERITED: dc321950]`:

```text
                                        pre-fix              post-fix
trust_store _initialize            -wal=T handle=T       -wal=F handle=F
approvals   _initialize            -wal=T handle=T       -wal=F handle=F
approvals   consumed               -wal=T handle=T       -wal=F handle=F
provider_observation _init         -wal=F handle=T       -wal=F handle=F
provider_observation load          -wal=F handle=T       -wal=F handle=F
effect_recovery _persisted_..      -wal=T handle=T       -wal=T handle=F
effects (already fixed, ctrl)      -wal=F handle=F       -wal=F handle=F
```

Two rows would have been missed by a companion-only probe, and the packet says
so explicitly rather than reporting a clean sweep:

- **`provider_observation` never sets `journal_mode=WAL`.** Its leak produces
  no `-wal` at all and is visible only as a held handle. A `-wal`-only test
  there would have passed against broken code — vacuous, in exactly the sense
  this repository keeps finding.
- **`effect_recovery` opens the lease store `mode=ro`.** A read-only
  connection cannot checkpoint or unlink the WAL on close, so its companions
  correctly remain on disk afterwards with no handle open. Note the post-fix
  row reads `-wal=T`, and that is the *correct* result — a naive "all
  companions gone" acceptance criterion would have failed a correct fix.

Both were corrections the builder made to its own method mid-packet, and the
merge commit `851ff43c` keeps them on the record: "Two method corrections from
the agent, both kept."

### Per-site write / commit analysis

A mechanical rewrite would have been wrong here, so each site was classified
individually. The classification depends on the isolation mode of each
`_connect`, which was measured first `[INHERITED: dc321950]`:

```text
default isolation, CREATE TABLE -> in_transaction False, survives close
default isolation, INSERT       -> in_transaction True,  LOST on close
isolation_level=None, INSERT    -> in_transaction False, survives close
```

Per site (line numbers as of the **pre-fix** tree, as the commit states them):

| site | classification |
| --- | --- |
| `approvals:454` `_initialize` | **writes** (DDL). `isolation_level=None`, no BEGIN: already autocommitted, the `with` commit was a no-op |
| `approvals:638` `verify_consumption` | read-only SELECT |
| `approvals:719` `consumed` | read-only SELECT |
| `effect_recovery:514` `_persisted_terminal` | read-only SELECT on a `mode=ro` URI; cannot write at all |
| `provider_observation:559` `_initialize` | **writes** (DDL), and the one connection **not** in autocommit — `_connect` omits `isolation_level=None`. The commit is preserved **explicitly** with `connection.commit()` rather than left to DDL autocommit semantics, which are version-dependent |
| `provider_observation:837` `load` | read-only SELECT |
| `trust_store:262` `_initialize` | **writes** (DDL), autocommit as above |
| `trust_store:449` `admit`, `:507` `require_active`, `:571` `quarantine` | **writes** (INSERT/UPDATE). Each opens an explicit `BEGIN IMMEDIATE` and reaches an explicit `COMMIT`/`ROLLBACK` on every exit path inside the block, so `in_transaction` is already False when control leaves it and the `with` commit was a no-op. On a path that raises before that point, `with` rolled back and `close()` also rolls back an open transaction — **measured, not assumed**. `require_active`'s expiry write commits by hand *before* raising `RuntimeTrustExpired`, so it survives that exception |
| `trust_store:603` `records` | read-only SELECT |

The `provider_observation:559` row is the one place where "close instead of
`with`" was not sufficient and an explicit `commit()` was added. A blanket
rewrite would have silently dropped that schema write.

**Line-number caution for future readers.** The commit states pre-fix line
numbers in this analysis and post-fix line numbers in its mutation matrix. The
two sets differ because the fix inserts lines. The post-fix numbers are the
ones that resolve against `main` today, and they are verified below.

## Acceptance matrix

**Not frozen pre-build.** Reconstructed from the verification actually
performed, as recorded in `dc321950`. A matrix assembled after the fact is
weaker than one frozen before, and this row of the record should be read that
way.

| # | claim | check | result | provenance |
| --- | --- | --- | --- | --- |
| 1 | enumeration is complete | `with .*connect(` over `daedalus/` | 12 matches, 11 defects + 1 correct `contextlib.closing` | `[MEASURED]` re-run at `d17ea2fc`: now exactly 1 match remains |
| 2 | all four files leaked before, clean after | two detectors, per file, with control | table above; 7 rows | `[INHERITED: dc321950]` |
| 3 | no guard is decoration | 11 mutations, one site at a time | 11/11 RED | `[INHERITED: dc321950]`; sites `[MEASURED]` present at `d17ea2fc` |
| 4 | assertions are facts of the code, not of GC timing | 4 files × 4 GC regimes | green in all 16 combinations | `[INHERITED: dc321950]` |
| 5 | per-file determinism | each touched test file alone, 3× | 12/12/12, 23/23/23, 15/15/15, 16/16/16, exit 0 every time | `[INHERITED: dc321950]` |
| 6 | g1 gate profile | `tools/run_gate_checks.py g1` | exit 1: 5 failed, **147** passed, 1 skipped, 28 subtests | `[INHERITED: dc321950]` |
| 7 | zero regressions | full suite `-n auto --dist loadfile` vs same-tree baseline with the 8 files reverted | 18F/9571P vs 18F/9567P; **identical failing node IDs**; +4 is exactly the four new tests | `[INHERITED: dc321950]` |
| 8 | EOL durability | `tests/test_byte_pin_eol_durability.py` | 17 passed, exit 0 | `[INHERITED: dc321950]` |

### Mutation matrix

Each `close()` was replaced by `pass` in isolation and the owning test file
re-run `[INHERITED: dc321950]`. All eleven line numbers **verified present and
containing `connection.close()` at `d17ea2fc`** `[MEASURED]`:

```text
trust_store.py:302  _initialize             exit=1 RED
trust_store.py:508  admit                   exit=1 RED
trust_store.py:588  require_active          exit=1 RED
trust_store.py:636  quarantine              exit=1 RED
trust_store.py:658  records                 exit=1 RED
approvals.py:510    _initialize             exit=1 RED
approvals.py:666    verify_consumption      exit=1 RED
approvals.py:746    consumed                exit=1 RED
provider_observation.py:587 _initialize     exit=1 RED
provider_observation.py:864 load            exit=1 RED
effect_recovery.py:532 _persisted_terminal  exit=1 RED
```

**The mutation harness itself had to be repaired, and the repair is the
finding.** `[INHERITED: dc321950]`: its first version round-tripped through
`read_text`/`write_text`, which rewrote `trust_store.py` from LF to CRLF on
this host (`core.autocrlf` is true and `.gitattributes` byte-pins that file to
`-text`), and the `==` check on decoded text could not see it. It was caught
by `git diff --stat` showing **671 changed lines**, repaired, and the harness
made byte-exact. A mutation harness that silently rewrites the file it is
mutating cannot be trusted to report which mutation caused which failure.

### The trap that was avoided by construction

None of the four new tests calls `gc.collect()` before asserting absence. A
collect finalises the leaked connection itself and makes the test pass against
unfixed code. `dc321950`: "That is the trap that nearly shipped with the
parent commit and it was avoided by construction here." The parent's first
draft did exactly that and passed against the pre-fix tree (`e9254e12`).

### A contradiction of the brief, benign, recorded

`dc321950`: the brief expected the g1 gate to read 146 passed; it reads **147**.
`tests/kernel/test_owner_approval.py` is in `G1_TESTS` and gained exactly one
test here. The failure count, skip count and subtest count are unchanged.

## Migration and rollback

Migration: none. Effect semantics, error handling and statement ordering are
untouched at all eleven sites. No schema, no serialized identity, no registry
anchor changes. The only behavioural difference is that connections close when
the method returns instead of when the garbage collector happens to run — which
is the point.

Rollback: revert `dc321950`. The four new test files revert with it; leaving
them behind would leave four tests asserting a guarantee the reverted code no
longer provides, so they must move together. `[ASSUMED]` — no rollback was
performed or rehearsed; this is the mechanical inverse of the recorded change.

## Evidence, expected failures, and review

### Expected failures at hand-off

Five, all pre-existing and deliberately red in the `g1` profile:
`test_registry_new_doors` ×3, `test_registry_retired_rows` ×2. `dc321950`:
"unchanged and untouched. There is no sixth failure." `[INHERITED]`

### Iron-Plan footer as recorded in `dc321950`

> Iron Plan: ALIGNED
> Iron Gate: 1
> Evidence: defect re-measured (sqlite `with` does not close; -wal/-shm and the
> OS handle exist exactly while a connection is open); all four files proven
> leaking by execution before the fix and clean after, with the already-fixed
> effects.py as control; per-site write/commit analysis backed by measured
> isolation-mode behaviour; all 11 guards mutation-verified RED one at a time;
> 4 touched files green alone 3x each and across 4 GC regimes; g1 gate
> 5F/147P with no sixth failure; full suite 18F/9571P vs a 18F/9567P baseline,
> identical failing node IDs [MEASURED 2026-09-02]

### Review questions

**Never frozen.** No review questions were posed before this build and none
were answered on the record. The open items a reviewer would reasonably raise
*now*, derived from the material above:

1. The defect class was found by a test flake, not by a guard. Nothing in the
   tree refuses a *new* `with sqlite3.connect(...)` site. Should the
   enumeration pattern become a test, now that the tree is at zero and the
   single legitimate `contextlib.closing` exception is identifiable?
   `[MEASURED]` that no such test exists: `with .*connect(` appears in no
   test file as a guard pattern.
2. `provider_observation` still does not set `journal_mode=WAL`. That is why
   its leak was companion-invisible. Is the absence of WAL there deliberate?
3. The node-ID full-suite comparison (claim 7) is the same method `e9254e12`
   showed to be blind to a failure that trades places between GC regimes. It
   is used here as primary regression evidence, mitigated by the per-file
   3×-and-4-regimes runs of claim 5 — but only for the four touched files.

### Residual risks

- **No guard against recurrence.** See review question 1. The eleven sites are
  fixed by fact; nothing refuses a twelfth.
- The two-detector method is host-specific: the handle-rename detector depends
  on Windows file-locking semantics and would not fire on Linux, where the
  companion-only probe would again be vacuous for `provider_observation`. The
  evidence is sound on this host and is not portable as written.
- `effect_recovery`'s post-fix `-wal=T` row is correct but fragile as
  documentation: a future reader applying "companions should be gone" as an
  acceptance rule would call a correct fix broken.
