# Gate-0 trunk reconnaissance — verified findings

2026-08-17. Ten parallel read-only lanes over `work/g0-trunk-20260817` at `60b2bfe`,
every blocking or major claim then attacked by an independent refuter. 83 agents,
87 minutes, 5.1M tokens. Full transcript:
`.claude/.../workflows/wf_8adbe892-854/journal.jsonl`.

Everything below marked CONFIRMED was re-read by me directly at the cited lines,
not accepted on an agent's word.

## The single best thing about this trunk

Gate 0 declares itself **open, honestly**. `build_gate0_report` returns 60
blockers and `gate0_closed` is `False`. Nothing in the tree claims otherwise.
There is no false green anywhere in the release surface.

## Two production defects on the Gate-0 exit path

### 1. Read-only inspection fails closed on 100% of valid inputs — CONFIRMED

The exit criterion is "fail-closed protected effects **and fail-open read-only
inspection**". The second half does not work.

`daedalus/kernel/runtime_effect_replay.py:91` downgrades a runtime-bound
authorization by constructing a `NonRuntimeEffectAuthorization` from its lease.
That class refuses exactly this:

```python
# authorization.py:73-77
def __post_init__(self) -> None:
    if self.lease.runtime_id:
        raise EffectLeaseBindingMismatch(
            "runtime-bearing leases require RuntimeBoundEffectAuthorization"
        )
```

and `runtime_effects.py:263-265` makes `runtime_id` **mandatory** for runtime-bound
issuance:

```python
if not lease.runtime_id:
    raise RuntimeLeaseBindingMismatch(
        "runtime-bound issuance requires a runtime-bearing central entrypoint"
    )
```

Every well-formed runtime-bound lease therefore hits the raise. There is no input
for which `inspect_runtime_effect_execution` succeeds.

The comment above the defect reads *"Reuse the strict read-only persisted
EffectLease projection"* — the intent is right, the mechanism is wrong. Fix by
reaching the strict read-only path without the non-runtime facade. **Do not relax
the `authorization.py` guard**; it is correct and it is the thing that caught this.

Takes two live callers with it: `daedalus/runtimes/recovery.py:150` and
`daedalus/gates/repository_write_effect_lease.py:647` (≥13 failing tests).

### 2. A verified fault-matrix run can never become Gate evidence — CONFIRMED

`daedalus/gates/fault_matrix.py:802`:

```python
return FaultMatrixEvidence(
    matrix_id=self.matrix_id,
    status="passed",
    scenario_ids=tuple(item.scenario_id for item in manifest.scenarios),
    failure_count=0,                      # not a field
    source_revision=self.source_revision,
)
```

`FaultMatrixEvidence` (`evidence.py:251-258`) declares `matrix_id`,
`source_revision`, `status`, `matrix_sha256`, `scenario_ids`, `executed_at`,
`provenance`. There is no `failure_count`, and three required fields are omitted.
Unconditional `TypeError`.

Fail-closed — it cannot emit false evidence — but it is the *only* path from a
verified run to Gate evidence, so the exit-evidence pipeline is dead end to end.
Note `tests/gates/test_fault_matrix_contract_review.py:180` asserts the literal
string `failure_count=0` against unparsed source, so the test pins the defect and
must change with the fix.

### 3. `verify_fault_matrix_run` never checks exact durable state — reported

`fault_matrix.py:892-895` checks expected ⊆ observed and forbidden ∩ observed = ∅,
never equality, and `to_dict()` emits no `exact_durable_states_verified`. A
scenario leaving an **undeclared** durable side effect reports pass.

Not a regression: `git log -S` shows the implementation never existed — the tests
and the mutation harness landed ahead of it. Bounded today because the single
manifest's expected ∪ forbidden covers the whole 5-marker vocabulary and it
declares `faults_executed=false`, so no false evidence has been minted. Close it
before the first real receipts, or they will read stronger than they are.

## The guard, corrected

`iron_plan_guard.py verify` exits **1** on this trunk, blocking every commit and
`AGENTS.md` step 1. It is a **false positive**: `AUTO_PROMOTE_LEVELS` and
`run_write_wave` both live in the exec'd blob `_gated_writes_legacy.py.src`
(lines 1048 and 1081), which an AST parse cannot see. At runtime the value reads
`('never',)`. **Nothing is unsealed.**

The serious half is the sibling check: `_function_calls_name(gated_tree,
'run_write_wave', 'promote_candidates')` is vacuously `False` for the same reason,
so the static seal on invariant 4.5 is unenforced and has been silently.

I had this partly wrong in the first revision of proposal 005 — I grepped only
`.py` and concluded the constant did not exist. See the correction there.

## Effect boundary

- **52 of 53** registered effect entrypoints are not `Wiring.CENTRAL`. Only
  `python.offload` is.
- `tools/effect_boundary_check.py` discovers **66** targets against a **53-row**
  registry, so the true migration population is not even known.
- `mcp.runtime` wiring is ABSENT; `Effect.SECRETS` is claimed by **zero** of 53 rows.
- Separately measured by me: `EffectScope` is defined, deserialised, annotated and
  consumed in `daedalus/` — and **never constructed** there. See
  `GATE0_TRUNK_FAILURE_TAXONOMY.md`.

## Fault matrix coverage

- 24 catalog scenarios; **8** name pytest node ids that no longer resolve (rename
  drift) and **2** declare an `expected_outcome` their surviving tests contradict.
- The fail-open side *is* genuinely proven by `tests/test_gate0_faults_atalanta.py`
  (57 passed, mutation-verified) — but it is registered in no matrix, so it cannot
  be cited as exit evidence. That is a bookkeeping gap, not a coverage gap.

## Deliverables

Gate 0 §10 lists eight deliverables. **Zero are complete.** Canonical schemas are
at 7/9 — `graph-proposal` and `round-trip-report` exist nowhere. No live
runtime-conformance receipts are retained.

## What the survey did NOT establish

Recorded so it is not mistaken for coverage:

- **My own edits polluted the survey.** The uncommitted fixture patch moved
  `tests/gates` from 122 to 57 failures *between two lanes reading it*. One lane
  reported 122, a later one 57, and both were right at the moment they looked. I
  should have frozen the tree before fanning out. The trunk-wide numbers in
  `GATE0_TRUNK_FAILURE_TAXONOMY.md` are mine, measured on a quiet tree, and are
  the ones to trust.
- Nobody separated Windows-only fixture artifacts from genuine defects in
  `tests/runtimes` on Linux. Several of the remaining failures are probably
  environmental; that is unmeasured, not established.
- One refuter agent (`refute:guard-defects`) was stopped by a safety check and
  returned nothing, so the guard findings carry one fewer independent attack than
  the rest.

## Measured suite movement today

```
before   265 failed, 6186 passed, 51 skipped, 1 xfailed   30:20
after    199 failed, 6252 passed, 51 skipped, 1 xfailed   29:03
```

**66 tests recovered**, from two fixture fixes, no production code touched.
Neither can land until the guard is repaired.
