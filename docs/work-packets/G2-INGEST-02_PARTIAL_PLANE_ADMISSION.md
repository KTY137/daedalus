# G2-INGEST-02 — wire the `partial` plane status into the reference compiler

> **OUTCOME 2026-09-09: GOAL WITHDRAWN.** The TOLERANT mode below was built,
> verified working, and removed before commit. Its output has no consumer (every
> non-`complete` plane is refused by `relation_compiler.py:193` and
> `fourfold_evidence.py:592`), and the measurements it prompted showed admission
> was never the blocker: this compiler's type extraction covers 3.40 % of
> black's and 1.60 % of fastapi's annotation sites. Acceptance row A9 was
> unreachable from the start because `_reference_claims.py:36` forbids empty
> `claims`. What shipped is the fail-closed `KeyError` bug the work uncovered.
> Full record: `docs/G2_INGEST_02_RESULT_20260909.md`. The plan below is
> retained unedited as the frozen pre-implementation statement.

| field | value |
| --- | --- |
| packet id | `G2-INGEST-02` |
| active gate | Gate 1 (work serves Gate 2's corpus obligation) |
| classification | `ALIGNED` |
| base revision | `094f3567` (`origin/main`) |
| depends on | `G2-INGEST-01` (`docs/G2_INGEST_01_RESULT_20260909.md`) |
| owner | repository owner |

## GOAL

One primary claim: **`compile_reference_project` can admit a repository with
per-file content defects, emitting `status="partial"` with a mandatory `reason`,
without changing default behaviour.**

## Why this is wiring, not a new subsystem

`G2-INGEST-01` measured that the vocabulary already exists and has no consumer:

- `twin/contracts.py:102` — status is `complete | partial | absent`; `partial`
  requires a `reason` (`:138`), `absent` forbids nodes/relations (`:134`).
- `reference_compiler.py:207` — hardcodes `"complete"`; no other value is
  reachable from any call site.

`AGENTS.md` §3 asks for wiring before a new subsystem. This packet adds no
store, no authority, no second compiler.

## In scope

`daedalus/twin/reference_compiler.py`, `daedalus/twin/_reference_inventory.py`,
`tests/twin/`.

## Forbidden paths

`daedalus/spine/**`, `daedalus/kernel/**`, `docs/IKARUS_ARIADNE_MASTER_PLAN.md`,
the amendment chain, `AGENTS.md`, `daedalus/twin/contracts.py` (the contract is
already correct; this packet consumes it and must not relax it).

## DONE — acceptance matrix

| # | criterion | how it is checked |
| --- | --- | --- |
| A1 | STRICT is the default and is byte-identical to `094f3567` | the four digests per project in `runs-baseline.json`, both fixtures, must be unchanged |
| A2 | existing suite unchanged | `tests/twin/` — 384 passed, 3 skipped at base |
| A3 | TOLERANT excludes a defective `.py` and marks `code` `partial` with a reason naming it | new test |
| A4 | TOLERANT excludes a `.md` with an unresolvable link and marks `knowledge` `partial` | new test |
| A5 | an empty declared plane becomes `absent` with a reason, not a fatal | new test |
| A6 | **a `claims` entry referencing an excluded file REFUSES** | new test — see INVARIANT 1 |
| A7 | TOLERANT is deterministic: same tree → identical `snapshot.digest` ×3, including `reason` | new test |
| A8 | structural violations stay fatal in BOTH modes | new refusal tests for schema, disjointness, suffix contracts, symlink, path escape, `max_files` |
| A9 | `black` @ `c3cc5a95` compiles under TOLERANT | measured, reported with its exclusion counts |

## INVARIANTS

1. **Exclusion must never weaken claim verification.** A claim whose evidence
   file was excluded must fail, not skip and not silently pass. This is the
   property most likely to be quietly wrong and is the packet's main review
   question.
2. **STRICT digests do not move.** Any change to a `complete` plane's digest is
   a regression, not an improvement.
3. `partial` and `absent` are never inferred by a consumer as `complete`; the
   status is on the plane and enters its digest.
4. No new effectful entrypoint, event store, or promotion path.
5. The contract in `twin/contracts.py` is consumed, never relaxed.

## OUT OF SCOPE

- Automatic manifest derivation. This packet makes a *supplied* manifest
  admissible; it does not discover planes. `LANGUAGE_SPECS` stays unwired.
- Widening the data-plane vocabulary beyond `.csv`/`.json`. fastapi's empty
  data plane is therefore expected to become `absent`, not populated.
- Read-boundary failures (missing file, symlink, path escape, oversize) stay
  fatal in both modes. Deliberate: a file that cannot be read is a manifest
  error, not a repository property.
- Claim *generation*. A TOLERANT compile of an un-authored repository carries
  `claims: []` and therefore no cross-plane hypotheses at all.

## EVIDENCE

`runs-baseline.json` (recorded before implementation), the new tests above, the
full `tests/twin/` run, and a measured `black` compile with its exclusion
report.

## Expected failure modes

- The probe diverging from the builder, so a file passes the probe and then
  aborts the build. Mitigated by having the probe call the *same* per-file
  functions rather than reimplementing their checks.
- `reason` exceeding the 2000-character contract limit on a repository with
  many exclusions; requires bounded, deterministic truncation.
- `build_inventory:187` ("at least one dataclass-backed type") interacting
  badly with an excluded `.py` — a 15th precondition not catalogued in
  `G2-INGEST-01`'s table.

## Review questions

1. Is the structural-versus-content fatal line principled or arbitrary?
2. Can a consumer read a `partial` Twin as if it were `complete`?
3. Does the `reason` string's presence in `PlaneSnapshot.digest` create an
   ordering or truncation hazard?
