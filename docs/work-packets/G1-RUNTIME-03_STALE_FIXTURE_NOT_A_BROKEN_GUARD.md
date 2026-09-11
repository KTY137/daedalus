# G1-RUNTIME-03 - A stale fixture, not a broken guard

## Frozen packet metadata

- Packet ID: G1-RUNTIME-03
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: aeef64bfb3a2cbb1bbafa38f6d0a1462c2b9e794
- Dependencies: G1-RUNTIME-02 introduced the runtime trust port and its guard at d30136e8e351e311fb9b72db7b3d1a3222b1c6e5; the contract locator export that made that commit importable landed at 59b28718
- Promotion authority: repository owner; no automatic merge, promotion, release, or Gate transition
- Master-plan authority: Revision 11
- Master-plan digest: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest: `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The two red tests in `tests/kernel/test_runtime_terminal_capability.py` were
failing because the **test fixture** injected a bare `object()` as the runtime
trust ledger, not because the guard rejects a valid ledger. The guard is
correct and is not relaxed. The fixture is replaced by a conforming recorder,
the guard is *narrowed* to close a real hole it still had, and the guard gains
the block/allow coverage whose absence is why the defect surfaced as an
unrelated `TypeError` instead of as a named failure.

Invariants touched: master plan §4 invariant 3 (isolation - candidate execution
cannot modify its evaluator or policy; the runtime trust ledger is the authority
that decides whether a runtime is still admitted) and §4 invariant 8 (bounded
effects enforced at effect boundaries, not entrusted to prompts or to type
annotations). No trust boundary is widened by this packet.

### Which reading was true

The brief offered two readings. Neither was exactly right, and the difference
matters, so it is recorded here rather than smoothed over.

Reading (b) - "the guard's check is wrong; a `runtime_checkable` Protocol no
longer matches after a symbol moved, or an `isinstance` against a class object
that is no longer the same object after a facade change" - is **false**, and was
falsified by direct measurement, not by reading:

- `daedalus.kernel.contracts.RuntimeTrustLedgerPort is
  daedalus.kernel.contracts.security.RuntimeTrustLedgerPort` -> `True`.
  The PEP 562 facade in `daedalus/kernel/contracts/__init__.py` resolves by
  `getattr` on the single owner module, so it yields one class object, not a
  copy.
- `runtime_effects.RuntimeTrustLedgerPort is
  contracts.security.RuntimeTrustLedgerPort` -> `True`.
- The real production `daedalus.runtimes.trust_store.RuntimeTrustLedger`,
  instantiated, **passes** the guard: `_require_runtime_trust_ledger_port(led)
  is led` -> `True`.

Reading (a) - "the guard is right and is doing its job" - is true in its
conclusion but wrong in its stated cause. Nothing regressed in any ledger
implementation, because no ledger implementation is involved. The value the
guard refuses is literally `<object object at 0x...>`: the fixture at
`tests/kernel/test_runtime_terminal_capability.py:40` passed
`runtime_trust_ledger=object()`.

The correct reading is a third one: **the fixture was always inert and only
became visible when a guard landed.** Before
`d30136e8 refactor(runtime): move authorization composition to admission`
(2026-08-31), the field carried the concrete annotation
`runtime_trust_ledger: RuntimeTrustLedger` and **nothing checked it at runtime**.
A bare `object()` sailed through, and the two tests passed for the wrong reason.
That commit replaced the concrete import with the `RuntimeTrustLedgerPort`
Protocol and added the first actual runtime check, including in
`RuntimeBoundEffectAuthorization.__post_init__`. The guard did not break a valid
ledger; it revealed an injection that was never valid.

Measured, not inferred:

| Tree | Result |
| --- | --- |
| `d30136e8^` (exported to scratch) | `3 passed` exit 0 |
| `d30136e8` (exported to scratch) | collection `ERROR`: the facade did not yet export `RuntimeTrustLedgerPort` |
| `aeef64bf` (base of this packet) | `2 failed, 1 passed` exit 1 |

### Was it caused by a commit from today

No commit dated 2026-09-01 exists in this branch's ancestry
(`git log --since=2026-09-01` on `aeef64bf` returns empty), so the brief's
statement that the failures were not introduced by *today's* refactor commits is
correct. But the failures are **not** pre-existing in the broader sense implied:
they were introduced on 2026-08-31 by `d30136e8`, a hierarchy-refactor commit,
and they did not exist at its parent. The distinction is recorded because
"pre-existing" would otherwise be inherited as a fact by the next reader.

A second historical defect is recorded in passing, and is not repaired here
because it is already repaired at `aeef64bf`: at `d30136e8` itself
`daedalus.kernel.runtime_effects` was **not importable at all** - `security.py`
gained `RuntimeTrustLedgerPort` but `_EXPORT_GROUPS` in
`daedalus/kernel/contracts/__init__.py` was not updated, so the whole module
raised `ImportError`. `59b28718 fix(integration): expose runtime trust through
contract locator` fixed it. This is exactly the PEP 562 facade failure mode the
brief suspected - it was real, it just was not the cause of these two tests.

## Scope

In scope:

- `daedalus/kernel/runtime_effects.py` - `_require_runtime_trust_ledger_port`
  only. A strict narrowing; no other function is touched.
- `tests/kernel/test_runtime_terminal_capability.py` - fixture repair and two
  added positive assertions.
- `tests/kernel/test_runtime_trust_ledger_port_guard.py` - new.
- `docs/work-packets/G1-RUNTIME-03_STALE_FIXTURE_NOT_A_BROKEN_GUARD.md`,
  `docs/work-packets/index.json`, and the pinned counts in
  `tests/contracts/test_work_packet_index.py`.

Forbidden and untouched:

- `tests/test_registry_new_doors.py`, `tests/test_registry_retired_rows.py` -
  another packet's territory, deliberately red.
- The Effect Registry and any registry row. The digest
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec` is
  unchanged. It is cited as a boundary that was respected, **not** as evidence
  that behaviour is unchanged: it hashes only the eleven declaration fields and
  nothing about the code the targets point at, so it is structurally incapable
  of noticing a moved or rewritten implementation.
- No new effectful entrypoint. No relaxation of any refusal.

## Contracts and behavior

**Guard, before.** `_require_runtime_trust_ledger_port` was a bare
`isinstance(value, RuntimeTrustLedgerPort)`.

**Guard, after.** It additionally requires `require_active` to be callable.

This is a narrowing, and it closes a hole that was measured, not imagined.
`@runtime_checkable` proves only that the member *name* resolves:

```python
class Broken:
    require_active = 42
isinstance(Broken(), RuntimeTrustLedgerPort)   ->  True
```

Before this packet, `Broken()` was **admitted** by the guard. Every caller would
then proceed believing runtime trust had been verified, and the object would
fail much later, from inside verification, as a `TypeError` unrelated to its
cause - after the lease had already been composed. `test_isinstance_alone_would_
have_admitted_the_non_callable_ledger` pins the reason this extra check exists,
so that a later reader who finds it redundant learns why it is not.

The check deliberately stops at callability and does **not** pin the signature.
Pinning it would refuse legitimate `**kwargs` forwarders and test doubles - that
would be a guard that blocks a valid ledger, which this repository's review rules
class as a release-blocking defect.

**Terminal receipts do not consult runtime trust, and that is deliberate.**
`finish_effect` verifies only that the start receipt belongs to this lease, then
delegates. The repaired fixture now asserts this positively
(`assert trust.lookups == []`) rather than leaving it unobserved. By the time a
terminal receipt is written the external effect has already happened; a trust
lookup there could only strand a durable start receipt permanently open. Trust
is rechecked where it can still *prevent* an effect: `verify`, `grant`, and both
sides of `begin_effect`.

**No behaviour change for any real ledger.** The production
`RuntimeTrustLedger` passed the guard before this packet and passes it after;
that is asserted directly, with the real class, in two of the new tests.

## Acceptance matrix

Every command below was run from
`C:\Users\Administrator\daedalus-worktrees\g1-runtime-03` with
`C:\Users\Administrator\daedalus\.venv\Scripts\python.exe`. Exit codes were read
directly, never through a pipe.

| # | Check | Command | Result |
| --- | --- | --- | --- |
| 1 | The two target tests pass | `-m pytest tests/kernel/test_runtime_terminal_capability.py -q` | `3 passed` exit 0 |
| 2 | New guard suite passes | `-m pytest tests/kernel/test_runtime_trust_ledger_port_guard.py -q` | `15 passed` exit 0 |
| 3 | New suite FAILS without the tightening (scratch copy, guard reverted to bare `isinstance`) | same, in `daedalus-scratch/g1r03/nofix` | `2 failed, 13 passed` exit 1 |
| 4 | New suite catches a silently UNGUARDED surface (scratch copy, guard call deleted from `__post_init__`) | same, in `daedalus-scratch/g1r03/unguarded` | `3 failed, 12 passed` exit 1, naming `RuntimeBoundEffectAuthorization` |
| 5 | Pre-existing tests do NOT catch that unguarded surface | `-m pytest tests/kernel/test_runtime_terminal_capability.py tests/kernel/test_runtime_effect_admission.py -q` in the same scratch copy | `12 passed` exit 0 |
| 6 | The surface test catches a DECOY: guard removed from `__post_init__` but the same call left in a never-invoked helper method | `daedalus-scratch/g1r03/tighten` | `2 failed, 13 passed` exit 1 - see "a defect in this packet's own test" below |
| 7 | Same tightened test on the real tree | `daedalus-scratch/g1r03/clean` | `15 passed` exit 0 |
| 8 | Both changed kernel test files together | `-m pytest tests/kernel/test_runtime_trust_ledger_port_guard.py tests/kernel/test_runtime_terminal_capability.py -q` | `18 passed` exit 0 |
| 9 | Kernel and runtime suites | `-m pytest tests/kernel/ tests/runtimes/ -q` | `1 failed, 1858 passed, 67 skipped, 8 xfailed` exit 1; the one failure is pre-existing (row 10) |
| 10 | That failure is pre-existing at base | same single test in a scratch export of `aeef64bf` | `1 failed, 6 passed` exit 1, identical assertion |
| 11 | g1 gate | `tools/run_gate_checks.py g1` | `5 failed, 132 passed, 1 skipped, 28 subtests passed` exit 1 - exactly the five foreign registry failures |
| 12 | Import SCC census unmoved | `-m pytest tests/contracts/test_import_scc_hierarchy.py -q` | `3 passed` exit 0 |
| 13 | Work packet index | `-m pytest tests/contracts/test_work_packet_index.py -q` | `22 passed` exit 0 |
| 14 | Index checker and doc references | `tools/index_work_packets.py --check`; `tools/docs_reference_check.py` | `274 tracked files, 208 packet IDs` exit 0; `current pages: clean` exit 0 |
| 15 | Full suite (committed tree) | `-m pytest -q` | `20 failed, 10529 passed, 276 skipped, 9 xfailed, 2224 subtests passed` exit 1 - all 20 pre-existing; see evidence section |

Rows 5 and 6 are the load-bearing ones. With the constructor surface silently
unguarded, the entire pre-existing kernel coverage of this boundary is green.
That is the defect class this packet exists to make impossible.

### A defect in this packet's own test, found in review and fixed

The first version of `test_every_ledger_accepting_surface_routes_through_the_guard`
used `ast.walk` over the whole class body and asserted only that *some* call to
`_require_runtime_trust_ledger_port` existed somewhere in scope. An adversarial
review flagged it as reasoning; it was then falsified by measurement rather than
accepted on argument. The mutation: delete the real guard call from
`__post_init__` and leave an identically-named call in a helper method that
construction never invokes. Result:

```text
SURFACE_TESTS_EXIT=0
4 passed in 0.35s
```

The test passed while the boundary was gone - the exact failure mode this packet
was written to eliminate, reproduced inside the packet's own new test. It is
replaced by `_guards_unconditionally`, which requires a direct, unconditional
statement of the admitting scope (`__post_init__` for the dataclass, the function
body otherwise) whose single argument is the injected ledger itself. Against the
same mutation the replacement fails, naming the surface; against the real tree it
passes.

## Migration and rollback

No migration. No data, schema, contract wire format, or persisted artifact
changes. No caller changes. The guard's accepting set is a strict subset of what
it accepted before, and the only objects newly refused are objects that could
never have answered a trust lookup.

Rollback is `git revert` of the single commit. Reverting restores the two red
tests and re-opens the non-callable hole; it does not corrupt any state.

Deliberately **not** done, and why:

- The guard was not relaxed to make the tests green. That was the available
  shortcut and it is the release-blocking defect class named in `AGENTS.md`;
  an independent review already blocked this branch over that exact shape.
- The `class-not-instance` hole (below) was not closed, because the available
  fix - refusing every `type` - would also refuse a legitimate ledger exposing
  `require_active` as a `staticmethod` or `classmethod`. Blocking a valid
  implementation to catch a caller error is the wrong trade at a boundary that
  no production composition site can currently reach.

## Evidence expected failures and review

### Expected failures that must remain

`tools/run_gate_checks.py g1` exits 1 by design at this revision. The five
failures belong to another packet and were not touched:

```text
FAILED tests/test_registry_new_doors.py::test_no_declared_effect_is_painted_on
FAILED tests/test_registry_new_doors.py::test_the_derivation_is_not_vacuous
FAILED tests/test_registry_new_doors.py::test_a_planted_effect_and_a_deleted_one_are_both_caught
FAILED tests/test_registry_retired_rows.py::test_the_ollama_rollback_body_only_delegates
FAILED tests/test_registry_retired_rows.py::test_the_ollama_rollback_row_equals_the_ast_derived_effect_set
5 failed, 132 passed, 1 skipped, 28 subtests passed
```

`tests/kernel/test_offload_lease_outer_ports.py::test_cold_kernel_import_loads_
no_outer_implementation` fails identically at `aeef64bf` and after this packet.
A cold kernel import loads eleven outer implementation modules, `daedalus.runtimes`
first. It is a hierarchy-refactor regression in another lead's territory and is
**not** repaired here; it is named so it is not silently inherited as green.

### Full suite: the briefed number was right, once the scope is stated

The packet was briefed to expect `19 -> 17`. The suite was run twice from the
repository root. The **authoritative run is the second**, on the committed tree:

```text
20 failed, 10529 passed, 276 skipped, 9 xfailed, 14 warnings,
2224 subtests passed in 2987.55s (0:49:47)
```

`20 -> 17` is the same number seen through a different collection scope, and the
gap is fully accounted for. None of it is caused by this packet; the two target
tests appear in no failure list after it.

- The briefed `19` was measured over `tests/` only. `pytest -q` from the
  repository root also collects `experiments/`, which contributes exactly **3**
  further pre-existing failures (two in
  `experiments/forest_v2/s02_types/test_external_corpora.py`, one in
  `experiments/forest_v2/s07_bm25/test_bm25_index.py`). `20 - 3 = 17`, exactly
  the briefed post-packet count. Base was `22` from the root, `19` within
  `tests/`.
- The **first** run reported `22 failed, 10527 passed` in 2994.12s. The two extra
  failures were load-sensitive timing tests that did not recur in the second run
  and pass in isolation on both trees:
  `tests/test_conversation_requests.py::test_cancel_is_requested_then_confirmed_only_after_worker_stops`
  and `tests/test_killswitch.py::test_latency_latch_within_one_poll_interval`
  (`2 passed in 0.77s` at HEAD with this packet applied). Both assert wall-clock
  timing and were measured while the box was under sustained load. They are
  reported as an instrument problem, not as a result, and the disagreement
  between the two runs is recorded rather than resolved by picking the nicer one.
- Baseline arithmetic, all measured: 15 misc + 5 registry + 2 target = 22 at
  `aeef64bf` from the root. This packet fixes the 2 target failures and touches
  nothing else, predicting 20. The final run measured 20.

The earlier claim in this section that "the expected number was wrong" was itself
wrong, and is corrected here rather than deleted: the discrepancy was collection
scope plus two flakes, not a bad baseline.

- **Detail of the flake investigation.** The 15 non-registry
  failing files were re-run against a pristine scratch export of `aeef64bf`:
  `15 failed, 292 passed, 14 skipped` in 62s. Two tests that failed inside the
  50-minute full run **passed** there, and pass again at HEAD with this packet
  applied (`2 passed in 0.77s`):
  `tests/test_conversation_requests.py::test_cancel_is_requested_then_confirmed_only_after_worker_stops`
  and `tests/test_killswitch.py::test_latency_latch_within_one_poll_interval`.
  Both assert wall-clock timing. They fail under sustained load and pass idle.

The two target tests are absent from every failure list after this packet.

### Residual holes not closed by this packet

Written down because nobody else can reconstruct them.

1. **The ledger class itself is still admitted.** Passing
   `RuntimeTrustLedger` (the class, not an instance) satisfies both halves of
   the guard: the class object has a `require_active` attribute and it is
   callable. The mistake surfaces later as a missing-`self` `TypeError` at the
   first lookup. Left open deliberately, for the reason in the migration
   section, and pinned by `test_known_residual_hole_the_ledger_class_itself_is_
   still_admitted` so it is visible rather than forgotten.

2. **The guard proves shape, never authenticity.** It cannot distinguish the
   real trust ledger from any object with a callable `require_active` that
   returns a well-shaped record. Anything able to choose what is injected at
   `daedalus/runtimes/admission/authorization.py` can supply an always-`active`
   ledger and every runtime trust check becomes a no-op. `_require_runtime_record`
   validates the returned record's *shape* against `RuntimeTrustRecordPort`, not
   its HMAC. This is a type guard, not an authentication boundary, and must
   never be described as one.

3. **`RuntimeTrustRecordPort` is a data-member protocol**, so its `isinstance`
   check is `hasattr` over seven names. A `SimpleNamespace` with the right seven
   attributes passes - as the repaired test fixture itself demonstrates. Same
   class of limit as (2), on the return path rather than the injection path.

4. **The surface census is AST-scoped to `runtime_effects.py`.** A fourth
   module-level surface added *there* is caught. A trust ledger accepted by a
   different module is not. The census is also static: it proves the guard call
   is written in the admitting scope, not that it executed.

5. **A raising property escapes as the wrong exception type.** Measured: an
   object whose `require_active` is a `property` raising `ValueError` makes
   `_require_runtime_trust_ledger_port` propagate that raw `ValueError`, not the
   documented `TypeError`. `isinstance` against this one-method protocol does not
   invoke the getter, so it returns `True`; the subsequent
   `getattr(value, "require_active", None)` does invoke it, and the three-argument
   `getattr` swallows only `AttributeError`. Every
   `pytest.raises(TypeError, match="RuntimeTrustLedgerPort")` in the suite would
   miss this input. It is **fail-closed** - the object is refused, never admitted
   - so the invariant holds and it is a failure-mode wart, not a boundary hole.
   Left open deliberately: normalizing it needs a broad `except Exception` inside
   a fence, which is a swallow path that could mask a genuine error from a real
   ledger's attribute access. No ledger in this repository uses a property here.

6. **Not re-verified:** whether `daedalus/runtimes/broker.py:185`
   (`getattr(authorization, "runtime_trust_ledger", None)`) and `:331` reach the
   ledger by a path that bypasses this guard. Out of this packet's scope, read
   but not tested. Flagged for the runtime owner.

### Review questions

- Is the callability check a narrowing in every case, or is there a legitimate
  ledger shape it refuses? (Claim: narrowing only; the real ledger and a
  `**kwargs` forwarder are both asserted to pass.)
- Is `assert trust.lookups == []` in `finish_effect` pinning correct behaviour
  or freezing a bug? (Claim: correct - a trust recheck after a durable start
  receipt could only strand the receipt open.)
- Should residual hole 1 be closed after all?

Kayn reviews this packet. The fence's owner does not review her own fence.

`Iron Plan: ALIGNED`
`Iron Gate: 1`
`Evidence: acceptance matrix rows 1-11 above; scratch falsification in daedalus-scratch/g1r03/{before,nofix,unguarded,base}`
