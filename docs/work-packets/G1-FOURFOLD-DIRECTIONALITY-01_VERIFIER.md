# G1-FOURFOLD-DIRECTIONALITY-01 - Refuse lossy cross-plane verification

Packet ID: `G1-FOURFOLD-DIRECTIONALITY-01`
Artifact role: `primary`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `97e5e66a07028060005e071270d201a31a28b98b`
Dependencies: `G1-EXP-TENSOR-GPU-54 directionality contract and the existing canonical projection verifier`

## Primary acceptance claim

The existing Forest/Fourfold verifier cannot certify an undirected cross-plane
Forest edge as a directed verified binding. This closes a correctness gap in
the canonical verifier without promoting the Tensor experiments or advancing
the active delivery gate.

## Scope

Only `daedalus/twin/projection_verifier.py`,
`tests/twin/test_projection_verifier.py`, this packet, and its generated
`docs/work-packets/index.json` metadata may change. Historical experiments,
their negative evidence, policy, evaluator authority, the master plan and its
amendment chain remain outside this packet.

Iron Plan: **ALIGNED**; Iron Gate: **1**. The unchanged authority is master-plan
Revision 13 / version 2.4.0, SHA-256
`04e8cbf9441134e22b97fe1cb5e7ebcbcfedac64cda2f3e4e5086d82bb628639`.

## Contracts and behavior

Cross-plane direction comes from `ForestEdge.directed`, not endpoint storage
order or an evidence digest. The verifier records a deterministic
`undirected-cross-plane-edge` finding and does not admit that edge as a source
of directed bindings. `require_forest_projection` consequently refuses the
same subject. Same-plane undirected relations remain losslessly retained as
canonical relation digests, and directed cross-plane evidence projections
continue to verify.

## Acceptance matrix

Frozen before the regression and implementation changes:

1. A manually constructed, revision-bound Fourfold snapshot containing a
   directed binding for an undirected cross-plane Forest edge is invalid for
   both supported evidence forms: original edge evidence and the legacy
   Forest/edge digest wrapper.
2. Both `verify_forest_projection` and `require_forest_projection` retain that
   refusal after canonical snapshot serialization and deserialization.
3. Directed cross-plane edges verify with either supported evidence form.
4. An undirected same-plane edge remains valid when its exact canonical digest
   is retained by that plane.
5. Existing projection, legacy adapter, relation compiler and Twin contracts
   remain green. Run `tests/twin` with the repository venv, without `pytest -x`.
6. Validate tracked packet metadata and report any pre-existing registry
   failures separately. No unrelated historical metadata is rewritten here.

Verification budget: one local Python interpreter, at most ten minutes of
focused/Twin contract execution. No provider or effectful application action
is needed. Independent integration review remains required.

## Migration and rollback

There is no schema or persisted-data migration. Existing lossy snapshots remain
readable but can no longer receive a valid projection report. Rollback is an
explicit revert of this verifier change and its regression tests; it reopens
the named defect. Historical experiment evidence is retained in either case.

## Evidence expected failures and review

The initial read-only reproduction returned `valid=True, findings=()` from
the verifier while the legacy adapter refused the same undirected cross-plane
Forest edge. The frozen acceptance matrix requires a failing regression before
the implementation changes.

On the unchanged base, `tools/index_work_packets.py --check` already refuses:
`new Work Packet artifact lacks artifact_role:
docs/work-packets/G1-EXP-TENSOR-GPU-66.json`. This failure is pre-existing and
prevents a canonical registry refresh without a separate metadata repair.

Review should check that only cross-plane directionality is refused, both
evidence forms remain supported for directed edges, read-only reports stay
available, and no graph authority, effect path or gate claim is introduced.

Implementation and measured regression results will be appended below; the
acceptance matrix above remains frozen.

### Measured results, 2026-09-08

All pytest commands used
`C:/Users/Administrator/Desktop/projects/daedalus/.venv/Scripts/python.exe`
on Windows / Python 3.12.13 from the isolated
`daedalus-tensor-verifier-20260908` worktree.

- Unchanged verifier suite: `-m pytest -q
  tests/twin/test_projection_verifier.py` -> **8 passed in 18.91s**.
- New regressions with the unchanged implementation: the same command ->
  **2 failed, 11 passed in 1.82s**. Both undirected cross-plane cases produced
  `ProjectionVerificationReport(..., findings=())`; `assert not report.valid`
  failed for original edge evidence and for the legacy digest wrapper. The
  directed and same-plane controls passed. This negative result is retained.
- After adding the directionality finding to the existing cross-plane edge
  loop: `-m pytest -q tests/twin` -> **363 passed, 3 skipped in 7.53s**.
- `git diff --check` passed. The only executable change is seven lines in the
  existing verifier; focused tests cover the frozen acceptance matrix.

The full repository suite, additional interpreters and independent review were
not run by this packet's builder. Registry regeneration remains blocked by the
pre-existing GPU-66 metadata failure named above and is delegated to the
integration metadata repair. No full-suite, promotion or gate-closure claim is
made.
