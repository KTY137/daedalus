# kernel.promotion — SCC dossier

Module: `daedalus/kernel/promotion.py` (639 lines incl. trailing blank; [MEASURED] via Read)
Base: main @ 851ff43c (task brief); tree actually read at wip/g1-freeze-2026-08-31 working copy, no edits made.

## Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py kernel.promotion` [MEASURED]

```
### OUTGOING edges FROM kernel.promotion to other SCC members
  -> spine.attempt              FUNCTION-LOCAL (deferred)  in snapshot_promotion_candidates
       daedalus/kernel/promotion.py:174   from daedalus.spine.attempt import (

### INCOMING edges INTO kernel.promotion from other SCC members
  <- kairos.gated_writes        MODULE-LEVEL               in <module>
       daedalus/kairos/gated_writes.py:56   from daedalus.kernel.promotion import (
  <- kairos.gated_writes        FUNCTION-LOCAL (deferred)  in promote_candidates
       daedalus/kairos/gated_writes.py:231   from daedalus.kernel.promotion import (
  <- kairos.gated_writes        FUNCTION-LOCAL (deferred)  in promote_candidates
       daedalus/kairos/gated_writes.py:276   from daedalus.kernel.promotion import (
```

### Verification of the probe

- **Outgoing edge** (`promotion.py:174`, inside `snapshot_promotion_candidates`): read the full function
  body (lines 162–279). The import `from daedalus.spine.attempt import (AttemptResult, GateResult,
  PatchArtifact, STATE_CLEAN)` is real, unconditional inside the function (no `if TYPE_CHECKING`, no dead
  branch), and every one of the four names is actually used: `isinstance(result, AttemptResult)` (188),
  `isinstance(artifact, PatchArtifact)` (193), `result.state != STATE_CLEAN` (197), `isinstance(gate,
  GateResult)` (203). Enclosing function confirmed correct. [MEASURED]
- Not annotation-only: despite `from __future__ import annotations` at the top of the file (line 20), these
  four names are used in `isinstance()` calls and a value comparison, i.e. **runtime**, not just annotation
  positions — so this is not a free cut via lazy annotations. [MEASURED]
- **Incoming edges**: `kairos/gated_writes.py:56` is a genuine module-level import
  (`from daedalus.kernel.promotion import (PromotionAuthorizationError, snapshot_promotion_candidates as
  _snapshot_promotion_candidates)`), executed unconditionally as part of an `exec()`-materialized legacy
  source blob (see below) — still module-level from the SCC's point of view. Lines 231 and 276 are two
  separate function-local imports inside `promote_candidates`, one for `authorize_persisted_promotion` at
  the preauthorization stage, one (redundant re-import) for the sealed stage. All three confirmed real and
  reachable by reading `daedalus/kairos/gated_writes.py:1-70` and `:200-300`. [MEASURED]
- No `if TYPE_CHECKING:` guard anywhere in `promotion.py` (grepped; only `from typing import Any, Mapping,
  Sequence`, no `TYPE_CHECKING` import at all). [MEASURED]

### Dynamic references (AST-invisible)

Grepped `promotion.py` for `importlib.import_module`, `__import__`, and string literals naming other SCC
members: **none found**. The only hits for `daedalus.kernel.promotion` in the file itself are docstring
prose (module's own name) and the `from daedalus.kernel.promotion_trust_root import (...)` line — not a
dynamic reference to another SCC member. [MEASURED]

## What it actually does

`promotion.py` validates and freezes ("snapshots") a batch of candidate `AttemptResult`/`PatchArtifact`
objects — recomputing the patch digest, requiring a clean/non-cancelled/non-timed-out passed gate, and
rejecting non-canonical paths/revisions — before anything is allowed near a Git mutation. It then exposes
two binding primitives: `authorize_promotion` (a pure comparison of a consumed `OwnerApproval`,
`EvidencePacket`, and freshly re-read live target revision) and `authorize_persisted_promotion`, which is
the **sole** caller of `daedalus.kernel.promotion_trust_root.evaluate_promotion_trust` (the D5 owner-signed
trust root) and additionally re-checks the demoted HMAC second factor, recording — but never obeying — any
divergence. Nothing in this module spawns a process, acquires a lock, or touches a worktree; it only
produces or refuses a `PromotionAuthorization` value that a caller (`kairos.gated_writes`) must separately
act on.

## Layer

**kernel.** This is by behaviour, not by path, the textbook definition of the target `kernel` layer: it is
the sealed trust boundary for promotion (evidence binding, owner-approval consumption, no auto-merge). Every
module-level import it has is already kernel-internal and non-cyclic — `daedalus.kernel.approvals`,
`daedalus.kernel.contracts.base`, `daedalus.kernel.contracts.evidence`, `daedalus.kernel.promotion_trust_root`
— plus one cross-layer import to `daedalus.spine.envelope` (`canonical_sha`, a pure hashing helper, not an
SCC member per the probe). The one SCC-crossing import (`spine.attempt`) is a deferred, function-local
convenience import of inert result/record types, not a structural dependency of the module's own identity.
Verdict: correctly sited; not mis-sited.

## Severance

**Is `kernel.promotion` a pure pass-through or a real coupling point?** Real coupling point, not a
pass-through. It performs actual validation logic — digest recomputation (`hashlib.sha256`), gate-state
checks, and rebuilding immutable snapshots via `dataclasses.replace` — using the *shape* of
`AttemptResult`/`PatchArtifact`/`GateResult`. It does not merely forward calls into `spine.attempt`.

**Symbols crossing the edge:** exactly 4 — `AttemptResult`, `GateResult`, `PatchArtifact`, `STATE_CLEAN`.
Combined occurrence count of these 4 names in `promotion.py`: 13 [MEASURED, grep count]. All 13 are inside
one function, `snapshot_promotion_candidates`; none of the effectful doors (`TaskAttempt`, `run_attempt`,
`command_gate`, `pytest_gate`) are imported. The import is already function-local/deferred (cost of moving it
is therefore zero for module-import-time ordering).

**Cheapest severance — (a) port/protocol extraction.** Move the 4 crossing symbols (`AttemptResult`,
`GateResult`, `PatchArtifact`, `STATE_CLEAN`, and ideally the sibling `STATE_*` constants for consistency)
into a new `daedalus/kernel/contracts/attempt.py`, matching the *already-established* pattern
`promotion.py` uses for `daedalus.kernel.contracts.base` and `daedalus.kernel.contracts.evidence`. Have
`daedalus/kernel/attempt_execution.py` (which currently defines these dataclasses) either move its
definitions there and re-import them, or import-and-re-export them from the new contracts module.
`daedalus/spine/attempt.py`'s `_AttemptFacade.__getattr__` keeps working unchanged (it forwards *any*
attribute lookup to `_owner = daedalus.kernel.attempt_execution`, so nothing there needs to change).
`promotion.py:174` then becomes `from daedalus.kernel.contracts.attempt import (AttemptResult, GateResult,
PatchArtifact, STATE_CLEAN)`. This is cheapest because: only 4 symbols cross, all 4 are inert
dataclasses/a string constant (no methods, no capability objects), the import is already deferred/isolated
to one function, and it reuses an existing non-cyclic module family (`kernel.contracts.*`) rather than
inventing a new Protocol or wiring a callback/registry.

**Why not (b)/(c)/(d):** callback/parameter injection would require every caller of
`snapshot_promotion_candidates` (today only `kairos.gated_writes` and `candidate_batch_sha256`/
`authorize_promotion` internally) to thread an extra parameter for four type checks — more churn than
extracting 4 dataclasses. Event/registry late-binding is the wrong shape for compile-time type contracts
used in `isinstance()` checks. Genuine merge with `spine.attempt` is wrong: `spine.attempt` is explicitly
documented (its own docstring) as a *compatibility facade*, not an owner of these types either — merging
would just relocate the SCC membership, not remove it.

**Sealed-promotion-boundary question:** cutting/keeping this edge is structurally harmless to the D5 trust
boundary, argued from the symbols, not the names. The 4 crossing symbols are pure data/record types used
only to confirm that a result *already produced* by a prior, independently effect-bounded Attempt (with its
own `begin_effect`/`EffectBoundaryError` guard in `spine/attempt.py:208-241`) is structurally clean —
`promotion.py` never imports or calls `TaskAttempt`, `run_attempt`, or either gate constructor, so it gains
no execution authority through this edge. The actual sealed-approval logic (`authorize_persisted_promotion`,
the D5 root call, the single-caller invariant) has zero dependency on `spine.attempt`/`kernel.attempt_execution`
at all — that whole apparatus lives in `promotion_trust_root.py` and `approvals.py`, both already outside
the SCC. Severing the edge (moving the 4 types to `kernel.contracts.attempt`) changes nothing about trust
semantics; it only changes where four dataclasses are defined.

**Facade verification — is the edge really `kernel.promotion -> kernel.attempt_execution` wearing a
`spine.attempt` costume?** Yes, confirmed by reading `daedalus/spine/attempt.py` in full. None of
`AttemptResult`, `GateResult`, `PatchArtifact`, `STATE_CLEAN` are defined locally in that file — the only
locally defined names are the "composition" seams `TaskAttempt`, `run_attempt`, `command_gate`,
`pytest_gate`, `_remove_gate_tmpdir` (see `_COMPOSITION_NAMES`, lines 258-267). At import time the module
rebinds its own class: `_module.__class__ = _AttemptFacade` (line 292), and `_AttemptFacade.__getattr__`
(line 273-274) does `return getattr(_owner, name)` where `_owner = daedalus.kernel.attempt_execution`
(line 24). So `from daedalus.spine.attempt import AttemptResult` triggers Python's normal
"attribute not found on module → call `__getattr__`" path and resolves to
`daedalus.kernel.attempt_execution.AttemptResult`. The sibling analyst's claim is correct: the measured edge
`kernel.promotion -> spine.attempt` is, at runtime, `kernel.promotion -> kernel.attempt_execution`
(itself also an SCC member) wearing a `spine.attempt` costume. This matters for severance: renaming the
import target from `spine.attempt` to `kernel.attempt_execution` directly would **not** shrink the SCC
(both are members), which is exactly why the port-extraction target must be a *non-member* module
(`kernel.contracts.attempt`), not a same-cycle rename.

## Tests that pin this

Grep `daedalus.kernel.promotion|kernel import promotion` over `tests/`: **20 files, 28 matching lines**
[MEASURED, ripgrep count]. Files:

`tests/contracts/test_import_scc_hierarchy.py`, `tests/test_promotion_trust_root_claim_ledger.py`,
`tests/test_ignition_gate1.py`, `tests/kernel/test_live_promotion_legacy_retirement.py`,
`tests/kernel/test_contract_hierarchy.py`, `tests/test_promotion_trust_root_adversarial.py`,
`tests/test_promotion_trust_root_single_caller.py`, `tests/test_promotion_trust_root_truth_table.py`,
`tests/test_killswitch_profile_root.py`, `tests/kernel/test_sealed_promotion.py`,
`tests/kernel/test_promotion_material_review.py`, `tests/kernel/test_promotion_execution_adversarial.py`,
`tests/kernel/test_promotion_execution_index_contract.py`,
`tests/kernel/test_promotion_execution_reader_integrity.py`, `tests/kernel/test_promotion_execution_reader.py`,
`tests/kernel/test_promotion_fingerprint.py`, `tests/kernel/test_live_promotion_seam.py`,
`tests/kernel/test_persisted_promotion_authorization_review.py`,
`tests/kernel/test_persisted_promotion_authorization.py`, `tests/kernel/test_promotion_execution.py`.

No `mock.patch("daedalus...kernel.promotion...")` string targets found (grepped, 0 matches) [MEASURED].

Governance/architecture tests that would specifically break if the module's import edges were rewired
(not just its behaviour):

- `tests/contracts/test_import_scc_hierarchy.py` — hardcodes `"daedalus.kernel.promotion"` (line 31) inside
  `OLD_CROSS_DOMAIN_COMPONENT`/`CURRENT_CROSS_DOMAIN_COMPONENT`, and asserts a component digest
  `CURRENT_COMPONENTS_SHA256` computed via `daedalus.structcore.cycles.nontrivial_components`. Cutting the
  `-> spine.attempt` edge changes the SCC membership set and would break this test **by design** — it must
  be re-measured and updated in the same packet, per the file's own comment ("Moving census, not an
  architecture invariant... Re-measure and update them in the packet that moves them").
- `tests/test_promotion_trust_root_single_caller.py` — `test_the_live_promotion_seam_reaches_the_canonical_caller`
  and the module-scan tests asserting exactly one caller of `evaluate_promotion_trust`/
  `authorize_persisted_promotion`; `CANONICAL_CALLER = kernel/promotion.py` (line 32) is pinned by path.
- `tests/kernel/test_promotion_material_review.py` — `test_noncanonical_declared_digest_is_a_promotion_refusal`,
  `test_missing_result_revision_is_a_promotion_refusal`, `test_malformed_artifact_revision_is_a_promotion_refusal`,
  `test_noncanonical_changed_path_is_a_promotion_refusal` — all call `snapshot_promotion_candidates` directly
  and would need the 4 relocated symbols to remain import-compatible.
- `tests/kernel/test_sealed_promotion.py`, `tests/kernel/test_persisted_promotion_authorization.py`,
  `tests/kernel/test_persisted_promotion_authorization_review.py`, `tests/kernel/test_promotion_fingerprint.py`,
  `tests/kernel/test_live_promotion_seam.py`, `tests/kernel/test_live_promotion_legacy_retirement.py`,
  `tests/kernel/test_promotion_execution*.py` (4 files) — exercise `kairos.gated_writes.promote_candidates`
  end-to-end, which imports `kernel.promotion` both module-level and function-local.
- `tests/test_promotion_trust_root_claim_ledger.py`, `tests/test_promotion_trust_root_adversarial.py`,
  `tests/test_promotion_trust_root_truth_table.py` — exercise the D5 trust-root call chain through
  `authorize_persisted_promotion`.
- `tests/test_ignition_gate1.py` — `test_promotion_status_is_never_promoted`,
  `test_the_slice_imports_no_promotion_machinery` — pin absence of promotion machinery in the Gate-1
  Renovation slice; relevant as a boundary check, not directly to this edge.

Not run (STATIC ANALYSIS ONLY per task rules); pass/fail after a severance edit is UNVERIFIED until
`.venv/Scripts/python.exe -m pytest` is actually executed by an authorized step.
