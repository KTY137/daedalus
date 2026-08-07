# G0-FLT-07A — Canonical Gate-0 Fault Matrix Contract

## Purpose

This Work Packet defines the machine contract required before a process-kill fault harness can produce Gate evidence. It does not inject a fault or call the receipt-retention entrypoint. It fixes the exact scenario inventory, durable-state expectations, restart semantics, revision and runtime bindings, receipt shape, and mechanical pass/fail rules.

The packet is based on exact parent revision `e12bd7467db6a6f64c405d5877e37f7f2c7e24fd` from the receipt-retention admission branch. No commit targets `main` or `experimental` directly.

## Exact fault identity

Each scenario has one canonical `scenario_id` and one canonical `injection_point`. The expected injection fingerprint is derived mechanically from:

- schema `daedalus-fault-injection-fingerprint/1`;
- exact 40-hex source revision;
- exact scenario ID;
- exact injection point.

Changing any one of those subjects changes the fingerprint. A harness receipt with an arbitrary digest therefore cannot satisfy verification merely because it has the right length.

## Exact run identity

Every scenario receipt binds:

- the exact scenario-spec digest;
- source and harness revisions;
- harness-runtime and toolchain-manifest digests;
- deterministic injection fingerprint;
- observed outcome and restart policy;
- whether process termination was actually observed;
- durable markers after restart or replay;
- Primary Checkout digests before and after execution;
- one unique hard run-artifact digest.

Automatic re-execution and LLM-generated hard evidence are permanently forbidden by the wire contract.

## Pinned receipt-retention inventory

The manifest contains twelve sorted and unique scenarios covering the effect start, retention intent, CAS publication, canonical Event Store, Effect terminal receipt, stale revision, Primary Checkout mutation, retained `STARTED` replay, and terminal replay boundaries.

The durable marker vocabulary is intentionally narrow:

- `effect.start`
- `retention.intent`
- `cas.object`
- `retention.event`
- `effect.terminal`

Each scenario states which markers must exist, which must not exist, the expected outcome, the restart policy, and whether the process must be killed. A process-kill scenario cannot pass with a receipt that merely reports the right durable state but says no termination occurred.

## Mechanical verification

`verify_fault_matrix_run` fails closed unless all of the following hold:

1. The manifest, receipt tuple, and every receipt have exact contract types.
2. The manifest is pinned to the requested source revision.
3. There are no duplicate, missing, or extra scenario IDs.
4. Each scenario has a unique run artifact.
5. Scenario digest, source revision, harness revision, runtime digest, toolchain digest, and injection fingerprint all match.
6. Outcome, restart policy, and process-termination observation match the scenario.
7. Every required durable marker exists and every forbidden marker is absent.
8. The Primary Checkout before and after digests are identical.
9. No automatic re-execution or LLM hard evidence is reported.

A `FaultMatrixVerificationReceipt` can project the existing `FaultMatrixEvidence` only by re-running the exact verifier over the supplied manifest and receipts and obtaining the same verification receipt. Constructing a superficially passing receipt is insufficient.

## Claims deliberately kept false

The manifest always reports:

- `inventory_complete_claimed=false`
- `faults_executed=false`
- `gate_transition_authorized=false`
- `closed=false`

Every scenario reports:

- `automatic_reexecution_allowed=false`
- `primary_checkout_mutation_allowed=false`
- `llm_evidence_allowed=false`

This Work Packet therefore provides a complete contract inventory, not completed fault evidence. Gate 0 remains open.

## Adversarial verification prepared

Behavior tests cover exact round trips, stale revision, missing and extra scenarios, duplicate scenario and artifact identities, fingerprint detachment, runtime and toolchain detachment, wrong restart policy, missing process termination, durable-state mismatches, Primary Checkout mutation, unsupported claims, and forged passing verification receipts.

A separate review perspective checks that the module has no process, filesystem mutation, network, database, Effect, provider, promotion, or retention execution capability. It also pins the exact fingerprint inputs and all verification comparisons. Draft 2020-12 schema tests reject claim escalation and inconsistent passing or failing verification receipts. A nineteen-mutant campaign targets the highest-risk bypasses.

The packet workflow requests focused Ubuntu and Windows tests on Python 3.10 and 3.12 under two hash seeds, predecessor regressions, the full suite, package build, and isolated-wheel import.

## Remaining dependent work

A later Work Packet must implement the process-kill harness outside the Primary Checkout, instrument the canonical retention entrypoint at every exact injection point, bind concrete runtime and toolchain manifests, execute all scenarios against the pinned revision, persist hard artifacts and receipts, and verify deterministic fresh and replay runs. Only an exact passing run may be bound into the Gate-0 release report, and Gate 0 still cannot close while any other release blocker remains.

Hosted GitHub Actions currently has a repository-wide zero-step infrastructure incident tracked in issue #67. A run ending before Step 1 with `steps=null`, no logs, and no artifacts is external infrastructure evidence only and cannot satisfy this packet's builder, review, mutation, full-suite, packaging, or platform checks.
