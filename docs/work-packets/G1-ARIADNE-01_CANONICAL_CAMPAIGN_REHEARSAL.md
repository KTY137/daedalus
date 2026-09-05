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
existing `SpineLedger`, gives every canonical Attempt its own central
`python.attempt` lease/effect start, persists the authoritative candidate source tree in the
shared source-tree CAS, retains positive and negative outcomes, and stops at a
`NominationReceipt`.

This is the maximal Gate-1 rehearsal, not the later Gate-3/4 evolution lab.
There is no model operator, general GraphProposal/RoundTripReport, archive,
MAP-Elites, owner approval, merge, or promotion authority in scope.

## Reproduced negative baseline

- `CampaignContract` was the only canonical contract with no production
  producer; the producer census stated that no live campaign existed.
- The producer census was a ten-name tuple and therefore ignored all twelve
  registered Genesis contract types. `DeploymentPlan` and
  `DeploymentReceipt` had no producer and no explicit producer-less reason;
  the census could still report green.
- `python -m daedalus.ariadne` parsed arguments before any outer process-guard
  boundary, even though the inner campaign path later acquired its exact
  write/containment lease.
- Completed-run replay opened `SpineLedger(read_only=True)` before the campaign
  lease and `begin_effect`; SQLite documents and the ledger itself retains the
  measured fact that a WAL read-only open may create `-wal`/`-shm` companions.
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

- seeds/arms: exactly `(0, 1, 2)` = no-change baseline, deliberate negative
  control, deterministic exact-text repair;
- operator axis: `repair_variant` and no second moving axis;
- metrics: `exact_match` from one frozen external evaluator;
- attempt budget: exactly one attempt per arm, all with the same configured
  budget and retained realized usage;
- wall budget: `gate_timeout_s` per arm, checked at receipt construction;
- expiry: 15 minutes after the frozen campaign timestamp;
- selection: deterministic best passed non-baseline `(variant_id, seed)`;
  failed baseline/control trials remain beside the selected repair;
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
- one bounded controlled-repair nomination after independent evaluation;
- producer/status/tests/documentation needed to make the live path observable.

Exact production file set:

- `daedalus/schemas.py`
- `daedalus/kernel/campaigns.py`
- `daedalus/kernel/__init__.py`
- `daedalus/ariadne/__init__.py`
- `daedalus/ariadne/campaign.py`
- `daedalus/ariadne/__main__.py`
- `daedalus/spine/effect_boundary.py`
- `daedalus/interfaces/cli/entry.py` (thin dispatch only)

Exact test/document set:

- `tests/test_ariadne_campaign_v0.py`
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
3. Every trial Attempt carries the campaign id and seed and crosses the central
   `python.attempt` boundary with its own lease before workspace materialization.
4. The base and every candidate are scoped one-file trees containing only the
   exact target path and stable-read bytes; CRLF bytes round-trip unchanged.
5. Three deterministic arms use the same task/evaluator/budget ceiling; typed
   arm identity and configured/realized budget evidence bind every trial.
6. The receipt retains attempt ids, evidence, metrics, usage, blockers,
   baseline failure, negative control, and the selected repair.
7. A green campaign emits and persists one verified `NominationReceipt`; any
   blocker yields rejection and no nomination.
8. No code in the Ariadne package imports approval or promotion modules.
9. The outer Ariadne CLI refuses before parsing or writing when the central
   process guard is unavailable.
10. Re-running a completed campaign returns the persisted canonical receipt;
    it does not execute another trial, and the replay SQLite open occurs only
    after the canonical campaign lease and `begin_effect`.
11. The producer census is the exact 24-type closed parser registry; all twelve
    Genesis types are included, their ten live producer modules are exact, and
    the two deployment types remain explicitly producer-less while publishing
    is out of this Gate-1 packet.

## Pre-registered fault matrix

- same id plus changed seeds, budget, fixture, evaluator, or operator refuses;
- path-bearing campaign ids refuse before any path lookup or write;
- an unresolved run intent refuses automatic retry;
- two concurrent Genesis/Ariadne starts serialize on their repository-local
  shared OS file-lock primitive and produce at most one run intent; unrelated
  legacy candidate lanes are not claimed by this lock;
- CAS corruption or an unresolvable base/candidate/receipt locator refuses;
- source-tree/Fourfold provenance detachment refuses;
- a failed, inconclusive, cancelled, or missing EvidencePacket produces no
  nomination;
- aggregate usage not equal to the sum of trials refuses;
- attempt count or wall budget exhaustion stops before the next seed;
- evaluator drift between preparation and trial produces a retained blocker;
- central CLI refusal occurs before parsing, ledger, CAS, receipt, or trial;
- a denied campaign lease reaches neither replay SQLite nor WAL/SHM creation;
- a completed exact replay executes zero attempts and returns the stored bytes.

## Verification

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q `
  tests/test_ariadne_campaign_v0.py `
  tests/test_kernel_contracts_have_producers.py `
  tests/test_registry_new_doors.py `
  tests/kernel/test_source_tree_store.py `
  tests/kernel/test_contract_hierarchy.py
```

Rollback: remove the Ariadne package and campaign contract/facade additions,
then restore the bounded compiler, ignition, registry, status and census edits.
Retain this packet and every failed trial as negative evidence.

## V0 release boundary

This is a usable controlled one-file repair primitive, not yet a model operator,
a multi-file atomic Project Twin revision, a learned archive, or proof of
improvement on held-out tasks. Its repeatable unit is finite:

`frozen task -> equal-budget arms -> independent evidence -> nomination -> owner decision`

An operator may start another unit with newly frozen inputs and a new id. A
nominated candidate receives no authority over the next task, policy, evaluator,
evidence, merge, or promotion.

Iron Plan: **ALIGNED**  
Iron Gate: **1**  
Promotion: **forbidden by this packet**
