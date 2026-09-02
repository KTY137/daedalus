# W3 — `daedalus/kernel/campaigns.py`: canonical kernel wiring or parallel control plane?

Scope: read-only, static. Source: `git show wip/g1-freeze-2026-08-31:<path>` only.
Comparison baseline: `main` @ current tip (merge-base with wip: `151b8d18`).

## Verdict

**CANONICAL** — with one real, fixable integration gap (stale relative to a
main-side refactor), not a parallel control plane. §13 release-blocking does
**not** apply to this file as written; it does apply, conditionally, only if
someone lands it onto `main` without the registration/import re-point noted
below (an unregistered effectful entrypoint would then be a real defect).

## Symbol inventory (`daedalus/kernel/campaigns.py`, 2164 lines)

Top-level, in file order (line numbers are `git show` line numbers):

- `_parse_utc` (110), `campaign_expiry_blocker` (120), `_assert_gate1_spec` (124),
  `evaluator_drift_blocker` (176), `_usage_body` (183), `_budget_body` (193),
  `_verify_evidence_locator` (202), `_load_attempt_registry_row` (222),
  `_verify_attempt_effect_receipt` (267)
- `class CampaignLifecycleError(RuntimeError)` (350)
- `class CampaignPendingReconciliation(CampaignLifecycleError)` (354)
- `class CampaignAlreadyTerminal(CampaignLifecycleError)` (358)
- `class CampaignBeginResult` (363, frozen dataclass; `.replayed` property at 368)
- `store_contract` (372), `campaign_contract_for_spec` (387),
  `_assert_contract_matches_spec` (437), `_strict_json_value` (490),
  `_strict_json_object` (513), `_resolved_declared_path` (520),
  `_paths_overlap` (532), `_verify_campaign_boundary_components` (540),
  `_load_contract` (705), `load_experiment_spec` (725),
  `load_campaign_contract` (729), `load_campaign_receipt` (733),
  `_sum_usage` (744), `campaign_usage` (754),
  `campaign_receipt_provenance_inputs` (762), `_conservative_tokens` (798),
  `_verify_tree_blobs` (806), `_gate1_metrics` (835),
  `_independent_tree_digest` (891), `_independent_fourfold_graph_delta` (905),
  `_independently_verify_gate1_fourfold` (929), `_verify_gate1_trial` (1060),
  `verify_campaign_trial` (1620), `verify_campaign_chain` (1667),
  `_intent_payload` (1889), `_assert_intent_integrity` (1906),
  **`begin_campaign`** (1918), **`complete_campaign`** (2032),
  **`fail_campaign`** (2110)

There is **no locally-defined `Trial`/`Mission`/`Attempt`/`Evidence`/`Campaign`
dataclass** anywhere in the file. Every place that touches a trial uses
`trial: Any` and reads attributes (`trial.mission_locator`,
`trial.candidate_tree_sha256`, …) that are the field names of
`daedalus.schemas.CampaignTrialReceipt` — a canonical, imported type. **No own
schema is minted.**

## Import classification

a) Canonical kernel / spine (all present, unmodified in shape, on `main` too — see below):
`daedalus.atomic.ExclusiveFileLock`; `daedalus.ignition.bundle.bundle_digest_from_body`;
`daedalus.kernel.artifacts.ArtifactRef`; `daedalus.kernel.fourfold_evidence.*`;
`daedalus.kernel.source_trees.{SourceTreeManifest,SourceTreeStore}`;
`daedalus.kernel.offload_lease.control_root`;
`daedalus.schemas.{AttemptContract,AttemptReceipt,CampaignContract,CampaignReceipt,
CanonicalContract,ContractProvenance,EvidencePacket,ExperimentSpec,MissionContract,
NominationReceipt,PolicyDecision,ResourceBudget,ResourceUsage,RuntimeManifest}`;
`daedalus.spine.envelope.{canonical_json,canonical_sha}`;
`daedalus.spine.effect_boundary.{REGISTRY_BY_ID,EffectStartReceipt,effect_boundary_bytes,registry_document}`;
`daedalus.spine.ledger.{Intent,SpineLedger}`; `daedalus.storage.{ArtifactStore,ArtifactStoreError}`;
`daedalus.twin.compile_reference_project`; `daedalus.twin.contracts.FourfoldSnapshot`.

b) stdlib: `hashlib, json, tempfile, dataclasses, datetime, pathlib, typing`.

c) other: none.

100% of non-stdlib imports are canonical-kernel/spine modules. There is no
import of any local/duplicate contract, ledger, or store module.

## Storage

Grep for `sqlite3`, `open(`, `write_text`, `json.dump`, `.jsonl` inside
`campaigns.py`: **zero hits**. The only persistence calls are:

- `store.put_bytes(...)` / `store.read_bytes(...)` / `store.materialize_tree(...)`
  — i.e. `SourceTreeStore`/`ArtifactStore`, the canonical content-addressed store
  (`store_contract`, line 372‑384; `_verify_campaign_boundary_components`, 540‑702).
- `ledger.record_intent(...)` (2023), `ledger.mark_completed(...)` (2096),
  `ledger.mark_failed(...)` (2136) — all on the injected `SpineLedger` instance,
  the one canonical event spine. `Path(` only appears for read-side resolution
  and boundary-safety checks (`_resolved_declared_path`, 520), never as an
  independent write target the module owns.

The module opens **no database of its own** and writes **no bespoke files**.
Every effect it performs is a call into an object the *caller* constructs
(`ledger: SpineLedger`, `store: SourceTreeStore`) — this file is a pure
library over caller-owned canonical storage.

## Effects and the lease/policy boundary

`campaigns.py` itself performs **no live effectful call** (no subprocess, no
network, no filesystem write outside the injected stores). Its three
state-transition functions are:

- `begin_campaign` (1918‑2029): under an `ExclusiveFileLock`, calls
  `ledger.intents_by_effect_key` / `ledger.record_intent` — this **is** the
  canonical intent-first admission pattern used by `daedalus/spine/attempt.py`
  on `main` (compare `main:daedalus/spine/attempt.py`, which likewise records
  an `Intent` via `SpineLedger` before any effect). Before admitting, it calls
  `_verify_campaign_boundary_components` (540), which cross-checks the
  *running* `REGISTRY_BY_ID["python.ariadne_campaign"]` row against a frozen,
  stored copy — i.e. it refuses to admit if the live effect-boundary registry
  disagrees with what was frozen. This is the same registry object
  `main:daedalus/spine/effect_boundary.py` defines (`REGISTRY_BY_ID`,
  `ENTRYPOINTS`) — not a second registry.
- `complete_campaign` (2032‑2107): re-verifies the full chain
  (`verify_campaign_chain`) before calling `ledger.mark_completed`.
- `fail_campaign` (2110‑2139): calls `ledger.mark_failed`.

Live effectful work (spawning attempts, writing worktrees, running pytest) is
**not in this file**. It lives in the composition root
`daedalus/ariadne/campaign.py` (`run_campaign`, line 1027), whose *first* call
is `begin_effect("python.ariadne_campaign", REGISTRY_BY_ID["python.ariadne_campaign"].effects, (...))`
from `daedalus.spine.effect_boundary` (1042‑1058) — the same canonical
gate `main:daedalus/spine/effect_boundary.py` implements for every other
entrypoint (compare `id="python.attempt"` at `main_effect_boundary.py:306`,
guarded the same way). Per-attempt work is delegated to
`daedalus.ignition.gate1.run_gate1_ignition` (imported, not reimplemented),
and `kernel/campaigns.py`'s own `_load_attempt_registry_row` /
`_verify_attempt_effect_receipt` (222‑347) independently re-verify that each
retained attempt crossed `daedalus.spine.attempt:run_attempt` with the exact
guard contracts `budget.process_guard`, `containment.attempt`,
`containment.worktree`, `provider.write_policy`, `spine.intent_ledger` — i.e.
it *proves* the canonical attempt boundary was used rather than trusting the
caller's claim.

**Gap found**: `main:daedalus/spine/effect_boundary.py` (3728 lines, current)
registers `id="python.attempt"` but has **no** `id="python.ariadne_campaign"`
row (confirmed by grep — 0 hits vs. wip's registration at
`wip_effect_boundary.py:371`). `run_campaign`'s `begin_effect` call and
`campaigns.py`'s `_verify_campaign_boundary_components` would both raise
`KeyError`/`CampaignLifecycleError` against `main` as it stands today. This is
an **unmerged registration**, not a bypass: the code adds its entrypoint to
the one shared `ENTRYPOINTS`/`REGISTRY_BY_ID` table in the canonical file,
exactly where the architecture says new effectful entrypoints belong. It is
currently absent from `main`'s evolved copy of that same file and would need
to be replayed there before this code could run.

## Types: does it mint its own Mission/Attempt/Evidence/Campaign?

No. `CampaignContract`, `CampaignReceipt`, `CampaignTrialReceipt`,
`ExperimentSpec`, `MissionContract`, `AttemptContract`, `AttemptReceipt`,
`EvidencePacket`, `PolicyDecision`, `ResourceBudget`, `ResourceUsage`,
`RuntimeManifest`, `ContractProvenance`, `CanonicalContract`,
`NominationReceipt` are all **imported** from `daedalus.schemas` — on wip,
that module is still the pre-refactor monolith that defines these classes
directly (`wip:daedalus/schemas.py:1604` `class CampaignContract(CanonicalContract)`,
etc.). Byte-for-byte comparison of the `CampaignContract` class body between
`wip:daedalus/schemas.py` (lines 1604‑1838) and
`main:daedalus/kernel/contracts/canonical.py` (lines 1591‑1826, where `main`
now defines the same class after an independent hierarchy refactor) is
**identical** (`diff` returns only a 1-line docstring offset from a sed
boundary, not a real content difference). `main:daedalus/schemas.py` is now a
5-line-per-symbol *compatibility facade* re-exporting these exact same names
from `daedalus.kernel.contracts.canonical` (`main:daedalus/schemas.py:9-52`).
So the import `from daedalus.schemas import (...)` in `campaigns.py` would
**still resolve to the same canonical objects on `main` today** — the type
lineage was never forked, only relocated.

## Promotion / candidate-evaluator access

Grep and read confirm no promotion path: `campaigns.py` never imports
`daedalus.kernel.promotion*`, `daedalus.kernel.approvals`, or anything
resembling merge/publish. The module docstring states it explicitly ("The
module owns no scheduler, database, artifact dialect, evaluator, approval, or
promotion path... may stop at nomination"), and `run_campaign` in
`ariadne/campaign.py` stops at `assemble_fourfold_nomination_receipt` (its
own docstring: "It never imports or calls approval, merge, or promotion.").
No candidate ever receives its own evaluator or policy object — the evaluator
bundle is read back and hash-verified (`_verify_gate1_trial`, 1148‑1187),
never handed to the thing being evaluated.

## Runner: does it contain its own scheduler/executor/retry loop?

`kernel/campaigns.py` itself: no. `begin_campaign`/`complete_campaign`/
`fail_campaign` are single-shot admission/terminal-write functions, not a loop.

`daedalus/ariadne/campaign.py`'s `run_campaign` (1027‑1600s) **does** contain
a `for index, seed in enumerate(spec.seeds): ...` loop with retry/cancellation
handling (kill-switch checkpoints, budget checks, per-seed trial execution via
`run_gate1_ignition`). This is a bespoke Python loop, not a LangGraph node,
and `CLAUDE.md`'s repo-local rule requires new multi-stage execution
(attempts, verifier cascades, repair loops) to be modelled in the existing
`daedalus/langgraph_adapter.py`. Grep for `langgraph` across both files:
**zero hits**. However, `spec.seeds` is hard-frozen to exactly
`ARIADNE_GATE1_SEEDS = (0, 1)` by `_assert_gate1_spec` (124‑173), which
rejects any `ExperimentSpec` that isn't the one pre-registered, 2-seed,
non-evolving Gate-1 rehearsal — this is the exact "single, bounded,
deterministic, non-promoting rehearsal" that master-plan Revision 3
explicitly pre-authorized ("A single Gate-1 Voltage-rename Renovation slice
may be implemented as an isolated, deterministic, non-promoting rehearsal
stacked on a green Gate-0 Work Packet"). It is not a general campaign
scheduler/search loop; it cannot run more than two fixed, frozen seeds. This
narrows but does not erase the CLAUDE.md LangGraph-adapter deviation — it is
a real, citable gap against the repo's own orchestration rule, scoped to one
already-authorized rehearsal rather than a general parallel executor.

## Duplication check: does `main` already have a campaigns implementation?

`git ls-tree -r main --name-only | grep -i campaign` →
`daedalus/kernel/contracts/campaigns.py`,
`docs/work-packets/G1-ARIADNE-01_CANONICAL_CAMPAIGN_REHEARSAL.md`,
`runs/watchdog/.../campaign.lock`.

`main:daedalus/kernel/contracts/campaigns.py` is a **5-line re-export shim**:

```python
"""Frozen experiment and campaign description contracts."""
from .canonical import CampaignContract, CampaignReceipt, CampaignTrialReceipt, ExperimentSpec
__all__ = ["CampaignContract", "CampaignReceipt", "CampaignTrialReceipt", "ExperimentSpec"]
```

`main` has the **frozen contract types only** — no `begin_campaign`,
`complete_campaign`, `run_campaign`, or any lifecycle producer. `main` has
**no `daedalus/ariadne/` directory at all** (`git ls-tree -r main --name-only
-- daedalus/ariadne/` → empty). There is **no competing implementation on
`main`** for `kernel/campaigns.py` to duplicate.

Decisively: `git show main:docs/work-packets/G1-ARIADNE-01_CANONICAL_CAMPAIGN_REHEARSAL.md`
is the **same work packet**, present on `main` because it was added at the
shared merge-base commit `151b8d18 chore(wip): freeze Gate-1 dirty tree before
hierarchy refactor`. Its "Exact production file set" names precisely
`daedalus/schemas.py`, `daedalus/kernel/campaigns.py`, `daedalus/kernel/__init__.py`,
`daedalus/ariadne/{__init__,campaign,__main__}.py`,
`daedalus/twin/reference_compiler.py`, `daedalus/ignition/gate1.py`,
`daedalus/spine/effect_boundary.py` — exactly the files wip built. `main`
kept the doc (historical/planning) but never landed the implementation; its
own "hierarchy refactor" (the `kernel/contracts/` package split) proceeded on
an independent track. `wip`'s commit `a02f230c feat(ariadne): land canonical
Gate-1 campaign rehearsal` is the one that actually updated the doc to match
a real build and shipped the named files. **`kernel/campaigns.py` is not
inventing new territory; it is the delivery of an already-approved,
shared-history Work Packet that `main` still lists as outstanding.**

## `campaigns.py` vs. `daedalus/ariadne/campaign.py` — competing planes?

No — layered, not competing. `ariadne/campaign.py`'s own docstring: "This is
intentionally the currently implementable slice of Ariadne... It uses the
canonical spine, TaskAttempt path, source-tree CAS, Fourfold evidence and
nomination contract." It **imports `kernel/campaigns.py` directly**
(`from daedalus.kernel.campaigns import (ARIADNE_GATE1_*, begin_campaign,
campaign_contract_for_spec, complete_campaign, fail_campaign,
verify_campaign_chain, verify_campaign_trial, ...)`, `ariadne_campaign.py:36-65`)
and calls `begin_campaign`/`complete_campaign` as the terminal admission/commit
steps around its own seed loop (`ariadne_campaign.py:1196` `begin_campaign(...)`,
and `complete_campaign` is called later in the same function for the terminal
receipt — confirmed via the same import list). `kernel/campaigns.py` is the
**canonical lifecycle/verification layer**; `ariadne/campaign.py` is the
**composition root** that drives Gate-1 ignition attempts and calls into that
layer. One writer (`kernel/campaigns.py`'s `complete_campaign` via
`store_contract` + `ledger.mark_completed`), one caller
(`ariadne/campaign.py`'s `run_campaign`). This is the sanctioned
plan/execute split, not two control planes.

## Tests: real kernel wiring or self-referential?

`tests/kernel/test_campaign_contracts.py` (1682 lines, 24 `def test_`
functions) imports and drives **real** canonical objects: `SpineLedger`
(9 references — real ledger, not a stub), `SourceTreeStore`, `ArtifactStore`,
`daedalus.spine.effect_boundary.{ENTRYPOINTS,REGISTRY_BY_ID,begin_effect,
effect_boundary_bytes,registry_document}`, `daedalus.spine.receipts.{
attempt_policy_decision,attempt_runtime_manifest}`, and
`daedalus.twin.compile_reference_project` (the real Fourfold compiler, not a
mock). Only **1** `monkeypatch` use across the whole file
(`tests/kernel/test_campaign_contracts.py:1120,1136`), the rest construct real
`tmp_path`-backed stores and ledgers and exercise `begin_campaign` /
`complete_campaign` / `verify_campaign_chain` against them. This is
integration-shaped contract testing against the real kernel primitives, not a
module testing itself in isolation.

`tests/kernel/` is collectable: it has `tests/kernel/conftest.py` and ~65
sibling test files already exercising the same kernel (`test_attempt_lease.py`,
`test_effect_leases.py`, `test_sealed_promotion.py`, `test_source_tree_store.py`,
etc.) — this is an established, populated test package, not an orphaned
directory. (No test run was executed per the read-only constraint on this
task; collectability is a structural/static finding, not a pass/fail claim.)

## Summary of strongest cited evidence

1. **No parallel storage.** `campaigns.py` opens zero databases/files of its
   own; all persistence is through the caller-injected `SpineLedger`
   (`begin_campaign` → `ledger.record_intent`, line 2023;
   `complete_campaign` → `ledger.mark_completed`, line 2096) and
   `SourceTreeStore`/`ArtifactStore` (`store_contract`, 372‑384).
2. **No parallel types.** `CampaignContract` body is byte-identical between
   `wip:daedalus/schemas.py:1604-1838` and
   `main:daedalus/kernel/contracts/canonical.py:1591-1826` — same class, only
   relocated by `main`'s later refactor.
3. **Effect boundary extended, not duplicated.** `run_campaign` calls
   `begin_effect("python.ariadne_campaign", REGISTRY_BY_ID[...].effects, ...)`
   from the one canonical `daedalus.spine.effect_boundary`
   (`ariadne_campaign.py:1043-1058`), and `kernel/campaigns.py` independently
   re-verifies every retained attempt crossed `daedalus.spine.attempt:run_attempt`
   with canonical guard contracts (`_verify_attempt_effect_receipt`, 267-347).
   The only gap is that `main`'s evolved copy of `effect_boundary.py` (3728
   lines today) does not yet have the `python.ariadne_campaign` row that wip
   added to the same file (`wip_effect_boundary.py:371` vs. zero hits on
   `main`) — an unmerged registration, not a second registry.
4. **No duplicate implementation exists on `main` to compete with.**
   `main:daedalus/kernel/contracts/campaigns.py` is a 5-line type re-export;
   `main` has no `daedalus/ariadne/` at all; the work packet doc on `main`
   still describes this as unimplemented.
5. **No promotion/merge path; nomination-only, explicitly and by two
   independent docstrings** (`kernel/campaigns.py:1-7`,
   `ariadne/campaign.py:1-7`), consistent with master-plan Rev. 3's explicit
   authorization of exactly one bounded, non-promoting Gate-1 rehearsal.

## What is not settled by reading alone

- **Runtime correctness is UNVERIFIED.** No test was executed (task is
  read-only/static). The 24 tests in `test_campaign_contracts.py` read as
  real integration tests against real kernel primitives, but whether they
  currently pass against wip's own tree — let alone against `main`'s
  refactored `kernel/contracts/` package — is unmeasured. The one fact that
  would settle "does it actually still work" is a real pytest run of
  `tests/kernel/test_campaign_contracts.py` (and, for the composition root,
  `tests/test_ariadne_campaign.py`, which the task did not ask to fetch) on
  wip's own commit — none of that evidence exists yet per the task's own
  framing ("UNVERIFIED preservation commit... No test run backs it").
- **Integration onto `main` needs real work, not just a copy.** The
  `python.ariadne_campaign` registry row is absent from `main`'s current
  `effect_boundary.py` and must be replayed there; `main`'s independent
  103-commit hierarchy refactor (`kernel/contracts/` package split) means a
  literal `git cherry-pick`/copy of `c23c0df8` would need import-path
  reconciliation even though the underlying types are unchanged.
