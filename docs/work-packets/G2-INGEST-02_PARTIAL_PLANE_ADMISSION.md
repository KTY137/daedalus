# G2-INGEST-02 — wire the `partial` plane status into the reference compiler

Packet ID: `G2-INGEST-02`
Artifact role: `primary`
Status: `goal WITHDRAWN on measurement; the fail-closed KeyError it uncovered is fixed and tested`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `094f3567fed318154f73b3f326ff150a4221f323`
Dependencies: `G2-INGEST-01`
Master-plan authority: `Revision 13`
Promotion: not requested; automatic merge, promotion, and Gate transition are
forbidden. This packet fixes one defect and retires one design; it does not
advance Gate 2.

> **OUTCOME 2026-09-09: GOAL WITHDRAWN.** The TOLERANT mode planned below was
> built, verified working, and removed before commit. Its output has no consumer
> (every non-`complete` plane is refused by `relation_compiler.py:193` and
> `fourfold_evidence.py:592`), and the measurements it prompted showed admission
> was never the blocker: this compiler's type extraction covers 3.40 % of
> black's and 1.60 % of fastapi's annotation sites. Acceptance row A9 was
> unreachable from the start because `_reference_claims.py:36` forbids empty
> `claims`. What shipped is the fail-closed `KeyError` bug the work uncovered.
> Full record: `docs/G2_INGEST_02_RESULT_20260909.md`.

## Primary acceptance claim

**As planned:** `compile_reference_project` can admit a repository with per-file
content defects, emitting `status="partial"` with a mandatory `reason`, without
changing default behaviour.

**As delivered:** that claim is **withdrawn, unproven by choice** — the design
was measured to be unshippable before it was committed. The delivered claim is
narrower and fully proven: *a Markdown link to an undeclared but on-disk `.md`
page refuses with `ReferenceCompileError` instead of a bare `KeyError`.*

## Scope

In scope: `daedalus/twin/reference_compiler.py`, `tests/twin/`.

Planned but not used: `daedalus/twin/_reference_inventory.py` (the probe helper
was written here and reverted).

Forbidden paths: `daedalus/spine/**`, `daedalus/kernel/**`,
`docs/IKARUS_ARIADNE_MASTER_PLAN.md`, the amendment chain, `AGENTS.md`, and
`daedalus/twin/contracts.py` — the plane-status contract is already correct;
this packet consumes it and must not relax it. All were respected.

## Contracts and behavior

`twin/contracts.py:102` defines plane status `complete | partial | absent`;
`partial` requires a `reason` (`:138`) and `absent` forbids nodes and relations
(`:134`). `reference_compiler.py:207` hardcodes `"complete"`, so no other value
is reachable from any call site. `G2-INGEST-01` measured that gap.

Behaviour change delivered: `compile_reference_project` now refuses, with
`ReferenceCompileError`, when any compiled edge references a node that was never
built. Previously the plane lookup raised `KeyError`, which is outside the
module's documented failure type and therefore escaped callers guarding with
`except ReferenceCompileError`.

Compatibility: no signature change, no new parameter, no new export. All four
snapshot digests are unchanged for both manifested projects, so no stored
snapshot identity moves.

## Acceptance matrix

| # | criterion | outcome |
| --- | --- | --- |
| A1 | STRICT default byte-identical to base | **PASS** — four digests × two projects unchanged against a baseline recorded before implementation |
| A2 | existing suite unchanged | **PASS** — `tests/twin/` 385 passed, 3 skipped (382 + 3 new) |
| A3 | TOLERANT excludes a defective `.py`, `code` → `partial` | **WITHDRAWN** — implemented and working, then reverted |
| A4 | TOLERANT excludes a `.md` with an unresolvable link | **WITHDRAWN** — as A3 |
| A5 | empty declared plane → `absent` | **WITHDRAWN** — as A3 |
| A6 | a claim referencing an excluded file REFUSES | **CONFIRMED BY READING, not shipped** — `_reference_claims.py:56/:101` raise on non-membership |
| A7 | TOLERANT deterministic across three compiles | **WITHDRAWN** — as A3 |
| A8 | structural violations stay fatal | **PASS for the shipped change** — no refusal was relaxed |
| A9 | `black` compiles under TOLERANT | **UNREACHABLE** — `_reference_claims.py:36` forbids empty `claims`; the row was impossible when written |
| A10 | undeclared link target refuses with `ReferenceCompileError` | **PASS** — three new regression tests |

## Migration and rollback

No migration. The change is a new refusal on an input that previously crashed,
so no tree that compiled before stops compiling: a project reaching the new
error already raised `KeyError` at the same point.

Rollback is `git revert` of the single commit; nothing is persisted, no schema
or stored digest changes, and no consumer contract is touched.

## Evidence, expected failures and review

Evidence: `docs/G2_INGEST_02_RESULT_20260909.md`. Suites — `tests/twin/` 385
passed, 3 skipped; `tests/twin/ tests/contracts/ tests/gates/ tests/ignition/`
1 481 passed, 78 skipped, 28 subtests, 0 failed.

Expected failure modes that actually fired, all three predicted in the review
before implementation rather than found by tests:

1. Excluding a file leaves dangling `links_to` edges, and the plane lookup dies
   on a raw `KeyError`. Confirmed by execution, and then found to pre-exist on
   unmodified `daedalus/` at `cb16d7f0` — which is what turned it into the
   shipped fix.
2. "The probe cannot diverge from the builder" was false: three `build_inventory`
   preconditions (`:186` type plane, `:199` link set, `:213` node uniqueness) are
   whole-corpus, not per-file, so a per-file probe cannot evaluate them.
3. A zero-binding four-plane snapshot publishes as `verdict="passed"`, because
   `fourfold_evidence.py:592` gates only on plane status and nothing requires
   `bindings` non-empty. That object is the "four separate indices" configuration
   plan §11 lists as a Gate-3 baseline to beat and §14 as a kill criterion.

Review questions and their answers:

1. *Is the structural-versus-content fatal line principled?* **No.** It cuts both
   ways: the Markdown link check is content whose verdict depends on the
   manifest, and the suffix contracts are called authoring errors while the goal
   requires generated manifests.
2. *Can a consumer read `partial` as `complete`?* **No** — and that is the
   problem, not the reassurance. Both consumers refuse it, so the output is inert.
3. *Does `reason` in `PlaneSnapshot.digest` create a hazard?* **Yes** — the cap
   raises rather than truncates, so a many-exclusion plane would abort exactly
   when the feature is needed, and prose wording would be snapshot identity.
