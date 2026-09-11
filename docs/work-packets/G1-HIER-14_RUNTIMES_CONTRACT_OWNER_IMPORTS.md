# G1-HIER-14 — The runtimes layer names the contract owner, and the census constant it moved is load-bearing

> **This is a retroactive record.** G1-HIER-14 was built, verified and merged
> without a packet document. This file was written afterwards, on
> 2026-09-02, from the merged commits named below. It records measured
> history; it does not reconstruct intent. Every section says whether its
> content was frozen before the build (almost none of it was) or recovered
> from the commit record afterwards. The sections that a live packet freezes
> *pre-build* — acceptance matrix, forbidden paths, budget, review questions —
> did not exist while this packet ran, and saying so is the reason this
> document exists.

## Frozen packet metadata

- Packet ID: G1-HIER-14
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 843367e38421d935dd68881ddaa4fa9ecaeb8262
- Dependencies: G1-HIER-01, G1-HIER-10, G1-HIER-11, G1-HIER-12
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

Status: builder-verified and **merged**. This metadata block is retroactive.
The base revision is recovered as `8d465e09^` and is exact; the dependency
list is inferred from the commit's own statement that it performs "the same
repoint G1-HIER-10 did for eighteen kernel modules and G1-HIER-12 did for
`daedalus/spine/{receipts,picker}.py`", plus G1-HIER-01 which owns the
boundary contract. It was never declared by the packet itself.

Commits of record:

| role | commit |
| --- | --- |
| implementation | `8d465e09d6fdb88d47ffb600567fde0ade756841` |
| merge | `3b78fe859570a093890eadeef4837b7465d1bcaf` |
| follow-up fix | `e9254e12f634ac45903aea281336a8865763c862` |
| follow-up merge | `74008fabad9c93b582f87e8ecac35f72938fa905` |

The master-plan digest is `[MEASURED]` at `d17ea2fc`: `sha256` of
`docs/IKARUS_ARIADNE_MASTER_PLAN.md` equals the value above, which is also the
constant `MASTER_PLAN_SHA256` pinned in `tools/index_work_packets.py:38`. The
effect-registry digest is `[INHERITED]` — it is the Revision-11 constant cited
identically by 61 packet documents `[MEASURED: grep -rl … | wc -l]`, and no
other effect-registry digest appears anywhere in `docs/work-packets/`. It was
not re-derived here.

## Primary acceptance claim

All 33 modules under `daedalus/runtimes/` that imported the `daedalus.schemas`
compatibility facade name the module that owns each symbol instead. Import
statements only: no logic moved, no symbol gained or lost, no module added or
deleted.

`daedalus/schemas.py` is neither widened nor deleted. Per `8d465e09`, 33
modules in other layers still import it, so it stays a facade rather than
becoming dead code.

**Verified independently at `d17ea2fc`, not taken from the commit report:**

```console
$ grep -rn 'daedalus\.schemas' daedalus/runtimes/ --include=*.py
$ echo $?
1
$ grep -rln 'daedalus\.schemas' daedalus/ --include=*.py \
    | grep -v '^daedalus/schemas.py$' | wc -l
33
```

`[MEASURED]`. The second command is the liveness control the commit specified:
the identical pattern still finds 33 files elsewhere under `daedalus/`, so the
first grep is genuinely empty rather than silently matching nothing. This is
the same construction the boundary contract's rationales insist on — an
instrument that returns zero must be shown capable of returning non-zero.

## Scope

**Not frozen pre-build.** Recovered from the diff of `8d465e09`
`[MEASURED: git show --stat]`: 34 files changed, 97 insertions, 49 deletions.

In scope — the 33 repointed `daedalus/runtimes` modules:

```text
admission/authorization.py           provider_invocation_registry.py
contracts/repository.py              provider_invocation_resolution.py
fault_matrix.py                      provider_observation.py
fixture_fault_collector.py           provider_observation_store.py
host_fault_runner.py                 provider_observation_store_contract.py
live_fault_collector.py              provider_runtime_executable_binding.py
live_probe_drivers.py                provider_target_receipt_retention_admission.py
profiles.py                          provider_target_receipt_retention_completed_evidence.py
provider_executable_object_registry.py  provider_target_receipt_retention_contract.py
provider_executable_pre_admission.py provider_target_receipt_retention_effect_terminal_evidence.py
provider_executable_structure.py     provider_target_receipt_retention_preflight.py
provider_executable_targets.py       provider_target_receipt_retention_recovery.py
provider_invocation.py               provider_target_verification.py
provider_invocation_abi.py           provider_target_verification_contracts.py
provider_invocation_authority.py     trust.py
provider_invocation_identity.py      trust_store.py
provider_invocation_payload.py
```

In scope — census artifact: `tests/contracts/test_import_scc_hierarchy.py`
(+27/-1), which carries the constant update and its hand-computed
justification.

Out of scope, and explicitly named as untouched by `8d465e09`: the six
non-facade import edges from `daedalus/runtimes/` to flat root modules — 3 to
`daedalus.budget`, 1 to `daedalus.sensitivity`, 1 to `daedalus.resources`, and
1 to the `daedalus.runtimes` package itself.

**A correction the packet made to its own brief, recorded rather than
hidden.** From `8d465e09`: "The brief's baseline said `daedalus/runtimes/`
makes 37 import edges to flat root modules. Measured here it is 39." The extra
two are the `daedalus.resources` and self-package edges the brief omitted.

Forbidden paths were **never declared** — there is no pre-build scope freeze
for this packet. What can be said is what the diff shows: nothing outside the
33 modules and the one census test was modified.

## Contracts and behavior

### The repoint

Each of the 33 modules had **exactly one** module-scope
`from daedalus.schemas import …` statement `[INHERITED: 8d465e09]`. Each now
names the owning `daedalus.kernel.contracts.*` module or modules for the
symbols it uses. This is the fourth application of the same operation:
G1-HIER-10 (18 kernel modules), G1-HIER-11 (4 twin modules), G1-HIER-12
(2 spine modules), G1-HIER-14 (33 runtimes modules).

The contract that makes the repoint durable rather than cosmetic is
`docs/architecture/import-boundaries.json`: `daedalus.schemas` is in the
forbidden set of `kernel-no-outer-layers`, `spine-no-outer-layers` and
`twin-no-outer-layers`, which is what stops the facade returning to those
three layers. **Note the asymmetry this packet did not close:** the
`runtimes-no-gates` rule forbids only `daedalus.gates` and has an empty
allowlist, so nothing in the boundary contract forbids `daedalus/runtimes`
from importing `daedalus.schemas` again. `[MEASURED]` at `d17ea2fc` by
parsing the four rules. The runtimes layer is clean today by fact, not by
rule.

### The census delta, and why it is +6 and not +33

This is the load-bearing part of the packet, because
`tests/contracts/test_import_scc_hierarchy.py:118` asserts
`CENSUS_EDGES = 1630` and lines 94–117 attribute the `1624 -> 1630` move to
G1-HIER-14 **by name**. Until this document existed, that attribution pointed
at a packet with no record.

Measured on the tracked-module import graph, base `843367e3` to `8d465e09`
`[INHERITED: 8d465e09]`:

| quantity | before | after |
| --- | --- | --- |
| modules | 433 | 433 |
| edges | 1624 | **1630** (+6) |
| non-trivial SCCs | 12 | 12 |
| max SCC | 18 | 18 (component digest unchanged) |

The graph holds a **set** of targets per module, so a file that trades its one
facade edge for symbols owned by a single module spends one edge and moves the
total by zero. The delta is the sum of *(owners named − 1)* over the 33 files:

```text
profiles.py                                 3 owners  = +2
    .contracts.{base,resources,runtime}
live_probe_drivers.py                       2 owners  = +1
trust.py                                    2 owners  = +1
    both .contracts.{base,runtime}
..._retention_admission.py                  2 owners  = +1
..._retention_effect_terminal_evidence.py   2 owners  = +1
    both .contracts.{base,policy}
the other 28 files                          1 owner   =  0
                                                        ---
                                                        +6
```

Twenty-eight of the 33 need only `daedalus.kernel.contracts.base`, which owns
the shared validators (`_sha256`, `_identifier`, `_revision`, `_repo_path`, …)
that most of these modules were reaching through the facade to get. That is
why a 33-file change moves the edge count by 6 and not by 33.

Two methodological guards, both stated in `8d465e09`:

- The +6 was computed **by hand from the edit list before the census was
  re-run**, and the two agree. A number derived from the instrument it is
  meant to check proves nothing.
- Each of the five decomposed files was checked against the **resolved graph**,
  not just its import text, to confirm it did not already name the owner it
  was about to gain — so no line of the +6 is double-counted.

Independently confirmed at `d17ea2fc` `[MEASURED]`: re-running the graph
builder `_tracked_module_graph` from
`tests/contracts/test_import_scc_hierarchy.py:128` standalone yields 433
modules, **1630** edges, 12 components, max size 18, and component digest
`36d80ea6d701892c1cbb08057c2715477fbfcad972aa36b9f331d3065f3434a1`, matching
the constants at lines 57, 118, 205, 206 and 49 respectively.

### What was deliberately not done

- The facade was not deleted. 33 callers remain in other layers.
- No boundary rule was added for `daedalus/runtimes` (see the asymmetry above).
- No logic, symbol, or module changed. Import statements only.

## Acceptance matrix

**Not frozen pre-build.** This packet ran without a document, so no acceptance
matrix was declared in advance. The table below is *reconstructed from the
verification actually performed*, as recorded in `8d465e09`, and is labelled
accordingly. Reconstructing a matrix after the fact is weaker evidence than
freezing one before, and this row of the record should be read that way.

| # | claim | check | result | provenance |
| --- | --- | --- | --- | --- |
| 1 | no facade reference remains under `daedalus/runtimes/` | `grep -rn 'daedalus\.schemas' daedalus/runtimes/` | exit 1, zero matches | `[MEASURED]` re-run at `d17ea2fc` |
| 2 | that grep is live, not vacuous | same pattern over `daedalus/` | 33 files | `[MEASURED]` re-run at `d17ea2fc` |
| 3 | census constant is correct | graph re-computation | 1624 → 1630, hand-computed +6 agrees | `[MEASURED]` re-run at `d17ea2fc` |
| 4 | the new constant is a live assertion | revert `CENSUS_EDGES` to 1624 | test goes RED against measured 1630 | `[INHERITED: 8d465e09]` |
| 5 | g1 gate profile | `tools/run_gate_checks.py g1` | exit 1: 5 failed, 140 passed, 1 skipped, 28 subtests | `[INHERITED: 8d465e09]` |
| 6 | no new failure | full suite `-n auto --dist loadfile` | 22 failed, 9556 passed, 276 skipped, 9 xfailed; **identical node IDs** to base `843367e3` | `[INHERITED: 8d465e09]` |

Claim 4 is the one that matters most and is the one this document cannot
re-verify without running tests: it is the difference between a constant that
asserts something and a number pasted in from test output. It is recorded as
inherited from the commit that claims it.

The five failures in claim 5 are the known deliberately-red registry tests
(`test_registry_new_doors` ×3, `test_registry_retired_rows` ×2). `8d465e09`
states explicitly: "No sixth."

### Two corrections made during the packet, recorded rather than hidden

Both are quoted from `8d465e09` and both are Windows/host artifacts of the
class this repository keeps hitting:

- "the first rewrite used `Path.write_text`, which translated LF to CRLF and
  turned a two-line change into a whole-file diff. Redone with `newline=""` on
  both read and write."
- "the first ordering pass inserted `.runtime`/`.policy` before `.base` in the
  five multi-owner files, breaking those files' sorted import block. The
  rewriter now asserts the block is still sorted afterwards."

## Migration and rollback

Migration: none required. The repoint preserves object identity — the facade
re-exported the same objects the owner modules define, so no caller observes a
different value. No serialized identity, pickle global, or registry anchor
changes.

Rollback: revert `8d465e09` and restore `CENSUS_EDGES = 1624`. The two must
move together; reverting the source without the constant leaves the census
test red, and reverting the constant without the source leaves it red in the
other direction. `[ASSUMED]` — no rollback was performed or rehearsed; this is
the mechanical inverse of the recorded change, not a tested procedure.

## Evidence, expected failures, and review

### The follow-up defect this packet surfaced but did not cause

`tests/runtimes/test_provider_target_receipt_retention_admission.py` became
nondeterministic after the repoint. Run alone it could report 1 failed / 9
passed with `FileNotFoundError: …\effect-leases.sqlite3-wal`.

**The root cause is not the repoint** `[INHERITED: e9254e12]`.
`EffectLeaseLedger._initialize` used `with self._connect() as conn:`. For
`sqlite3` that is a **transaction** scope, not a closing scope: it commits and
leaves the connection open. A WAL companion exists exactly while a connection
is open. The leaked connection was unreachable garbage held in a **reference
cycle**, so refcounting never finalised it at method exit; only the
generational collector did, at a moment decided by how many objects the
process had allocated.

Measured on the pre-fix tree `[INHERITED: e9254e12]`:

```text
after EffectLeaseLedger.__init__ : -wal exists = True
after gc.collect()               : -wal exists = False
live sqlite3.Connection objects tracked by gc: 0
the ledger holds no connection attribute
```

`_verify_topology` stats those companions: `_sqlite_companion_paths` selects
them with `exists()`, then `_identity` resolves them with `strict=True`. A
`-wal` finalised between those two calls is the reported `FileNotFoundError`.

**Why the coordinator's bisect found no culprit module.** Pre-importing any of
eleven modules made the file pass; none of them is required. They only change
the allocation count, and therefore when the collector runs. Demonstrated by
varying nothing but the GC thresholds on the pre-fix tree
`[INHERITED: e9254e12]`:

```text
default      -> 10 passed
(400,10,10)  ->  1 failed  "Effect-Lease store companion cannot be resolved"
(300,10,10)  ->  3 failed
(1,1,1)      ->  2 failed
```

The failing test is a **different one in each regime**. That is precisely why
a full-suite node-ID diff could not see this: the failure trades places, so
the set can match while the file is broken. This is a genuine limitation of
the node-ID comparison method that claim 6 above relies on, and it is recorded
here because this packet is the case that found it.

The fix closed the connection at both `with`-form sites in
`daedalus/kernel/effects.py`, matching that module's own dominant idiom (four
of its six connection sites already used `try/finally` + `conn.close()`; the
two that used `with` are the two that leaked). It deliberately did **not**
restore the facade import — that would have re-hidden the defect and undone
the packet — and did not relax `_identity`, because that is an admission
boundary and skipping it would be a fail-open weakening.

**A test that nearly shipped passing against unfixed code**
`[INHERITED: e9254e12]`: "The first draft of that test called `gc.collect()`
before asserting absence and therefore PASSED against the pre-fix tree" — the
collect finalised the leaked connection itself. The shipped test pins the
precondition in both directions: no connection open → the companion is
deterministically absent; a connection really open → the companion exists and
the scan binds it. The second direction matters because that branch previously
ran only by accident; its only other coverage greps the **source** for
`"sqlite_companions"` and `"-wal"` and never executes the branch.

`e9254e12` also reported, and did not fix, 11 further sites of the same defect
class. Those are G1-HIER-15.

### Expected failures at hand-off

Five, all pre-existing and deliberately red in the `g1` profile:
`test_registry_new_doors` ×3, `test_registry_retired_rows` ×2. Unchanged by
this packet. `[INHERITED: 8d465e09]`

### Review questions

**Never frozen.** This packet ran without a document, so no review questions
were posed before the build and none were answered on the record. Recording
that absence is more useful than inventing questions retroactively. The open
items a reviewer would reasonably raise *now*, derived from the material above
and not from any contemporaneous review:

1. `runtimes-no-gates` has an empty allowlist and does not forbid
   `daedalus.schemas`. Should the runtimes layer get the same forbidden-set
   entry the kernel, spine and twin layers have, now that it is clean?
   `[MEASURED]` that it does not have one.
2. Claim 6's node-ID comparison was shown by `e9254e12` to be blind to a
   failure that trades places between regimes. What else has that method
   passed?
3. 33 callers of the facade remain in other layers, and 94 in `tests/`. No
   packet currently owns them.

### Residual risks

- The runtimes layer's cleanliness is a fact, not a rule; nothing refuses a
  regression. See review question 1.
- The +6 decomposition is hand-verified against the resolved graph, which is
  strong, but the census itself "had no opinion about when an import ran"
  (`tests/contracts/test_import_scc_hierarchy.py:88-92`) and cannot detect a
  deferred re-introduction of the facade at module or function scope. The
  static boundary checker is what would catch that, and for this layer it is
  not configured to.
