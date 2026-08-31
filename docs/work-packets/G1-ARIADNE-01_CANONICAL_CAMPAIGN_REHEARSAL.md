# G1-ARIADNE-01 — Canonical campaign rehearsal

Classification: `ALIGNED`  
Active gate: Gate 1 — Renovation ignition slice  
Base revision: `52b4baa5f7b065c54779cafd6a35b2411eeb5e84`  
Parents: `G1-WP-01_VOLTAGE_IGNITION`, `G0-ATT-13A_SOURCE_TREE_CAS_PORT`,
`G1-IGNITION-02_OUTER_EFFECT_BOUNDARY`

## Primary claim

Ariadne may run one production-reachable, deterministic Gate-1 campaign
rehearsal through the canonical Daedalus kernel. The campaign freezes an
`ExperimentSpec` and `CampaignContract`, records intent before trials in the
existing `SpineLedger`, runs every variant through the already-central
`TaskAttempt` path, persists the authoritative candidate source tree in the
shared source-tree CAS, retains positive and negative outcomes, and stops at a
`NominationReceipt`.

This is the maximal Gate-1 rehearsal, not the later Gate-3/4 evolution lab.
There is no model operator, general GraphProposal/RoundTripReport, archive,
MAP-Elites, owner approval, merge, or promotion authority in scope.

## Reproduced negative baseline

- `CampaignContract` was the only canonical contract with no production
  producer; the producer census stated that no live campaign existed.
- Desktop status reported `ariadne_campaign_live: false`.
- Gate-1 evidence named a synthetic candidate locator derived from the bounded
  compiler source-bundle digest; no test resolved that locator to an
  authoritative candidate source tree.
- `assemble_fourfold_nomination_receipt()` had no live caller.
- Legacy `kairos.evolution` and `kairos.archive` were isolated/advisory islands
  and did not use Campaign, TaskAttempt, the event spine, source-tree CAS, or
  sealed evidence.

## Frozen scope

Frozen protocol:

- seeds: exactly `(0, 1)` for the shipped rehearsal;
- operator axis: `literal-rename-operator` and no second moving axis;
- metrics: `baseline_pass`, `candidate_pass`, `negative_controls_red`;
- attempt budget: exactly two Gate-1 work items per seed (`max_attempts=4`);
- wall budget: `4 * gate_timeout_s`, checked before each seed and at terminal;
- expiry: 24 hours after the frozen campaign timestamp;
- selection: seed `0` only after every seed passes and all Candidate Source
  Tree manifests agree; the selected seed is retained in the receipt;
- outcome vocabulary: `nominated`, `rejected`, `failed`, `cancelled`; an empty
  trial set is valid only for a terminal error/cancellation before trial start.

The parent outer-boundary packet is green at build start: nine exact registry
derivation/conformance probes and the focused refusal-before-run probe passed.

Allowed:

- canonical `ExperimentSpec`, trial, and `CampaignReceipt` records;
- a typed campaign facade over the existing `SpineLedger` and
  `SourceTreeStore`;
- one `daedalus.ariadne` composition root and centrally registered CLI;
- source-tree identity binding in the bounded reference compiler and Gate-1
  ignition result;
- a real Fourfold nomination after all deterministic replay trials agree;
- producer/status/tests/documentation needed to make the live path observable.

Exact production file set:

- `daedalus/schemas.py`
- `daedalus/kernel/campaigns.py`
- `daedalus/kernel/__init__.py`
- `daedalus/ariadne/__init__.py`
- `daedalus/ariadne/campaign.py`
- `daedalus/ariadne/__main__.py`
- `daedalus/twin/reference_compiler.py`
- `daedalus/ignition/gate1.py`
- `daedalus/spine/effect_boundary.py`
- `daedalus/desktop_runtime.py` (status projection only)

Exact test/document set:

- `tests/kernel/test_campaign_contracts.py`
- `tests/test_ariadne_campaign.py`
- `tests/test_kernel_contracts_have_producers.py`
- `tests/test_registry_new_doors.py`
- `tests/test_cli_effect_boundary.py`
- this Work Packet.

Forbidden:

- another database, artifact identity, graph authority, evaluator, or runtime;
- use of `kernel.attempt.*` while those rows remain `LOCAL_GUARDS`;
- candidate access to policy/evaluator mutation;
- stochastic or model-generated candidates;
- automatic OwnerApproval, merge, or promotion;
- edits to unrelated dirty worktree files.

## Acceptance matrix

1. Spec and campaign are frozen before the first trial and mutually exact.
2. The campaign run intent is durably committed before any trial begins; a
   pending identical campaign refuses automatic replay.
3. Every Gate-1 attempt carries the campaign id and seed and still crosses the
   central `python.attempt` boundary with a lease.
4. Baseline and candidate trees resolve byte-for-byte from `SourceTreeStore`;
   Fourfold provenance and EvidencePacket bind the candidate manifest digest.
5. Two deterministic seeds use the same task/evaluator/budget/operator axis;
   candidate identity must agree before nomination.
6. The receipt retains per-seed mission, attempt ids, Gate-1 receipt, evidence,
   metrics, usage, blockers, baseline failure, and negative controls.
7. A green campaign emits and persists one verified `NominationReceipt`; any
   blocker yields rejection and no nomination.
8. No code in the Ariadne package imports approval or promotion modules.
9. The outer Ariadne CLI refuses before parsing or writing when the central
   process guard is unavailable.
10. Re-running a completed campaign returns the persisted canonical receipt;
    it does not execute another trial.

## Pre-registered fault matrix

- same id plus changed seeds, budget, fixture, evaluator, or operator refuses;
- an unresolved run intent refuses automatic retry;
- two concurrent starts serialize on the repository's shared OS file-lock
  primitive and produce at most one run intent;
- CAS corruption or an unresolvable base/candidate/receipt locator refuses;
- source-tree/Fourfold provenance detachment refuses;
- a failed, inconclusive, cancelled, or missing EvidencePacket produces no
  nomination;
- aggregate usage not equal to the sum of trials refuses;
- attempt count or wall budget exhaustion stops before the next seed;
- evaluator drift between preparation and trial produces a retained blocker;
- central CLI refusal occurs before parsing, ledger, CAS, receipt, or trial;
- a completed exact replay executes zero attempts and returns the stored bytes.

## Verification

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q `
  tests/kernel/test_campaign_contracts.py `
  tests/test_ariadne_campaign.py `
  tests/test_kernel_contracts_have_producers.py `
  tests/test_registry_new_doors.py `
  tests/kernel/test_source_tree_store.py `
  tests/kernel/test_fourfold_evidence.py `
  tests/test_ignition_gate1.py
```

Rollback: remove the Ariadne package and campaign contract/facade additions,
then restore the bounded compiler, ignition, registry, status and census edits.
Retain this packet and every failed trial as negative evidence.

Iron Plan: **ALIGNED**  
Iron Gate: **1**  
Promotion: **forbidden by this packet**
