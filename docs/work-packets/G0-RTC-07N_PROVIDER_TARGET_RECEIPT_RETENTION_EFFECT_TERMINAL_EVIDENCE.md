# G0-RTC-07N — Provider Target Receipt Retention Effect Terminal Evidence

## Exact parent

- frozen branch: `g0/provider-target-receipt-retention-completed-evidence-frozen-fad88f6`
- frozen revision: `fad88f62bb6f4065fd21a666e9d2697a7c85c91d`
- parent evidence packet: PR #224
- this packet: PR #225

## Scope

This additive read-only packet binds the completed provider-target receipt-retention evidence to the exact persisted `COMPLETED` Effect-Lease execution. It accepts only exact typed subjects, reconstructs the completed evidence canonically, verifies that request, policy and lease provenance use the same exact 40-hex revision, rebuilds the retention entrypoint and narrowed execution-scope bindings, and performs two query-only replay projections.

The concrete Effect-Lease SQLite file is fenced by resolved path, device and inode before, between and after those projections. Symlinked or hard-linked store topology is refused. The two replay projections must be identical and must contain exact start and terminal receipts with `COMPLETED` state and outcome. The packet independently reconstructs the start and terminal receipt authority, execution, chronology and canonical digest bindings instead of trusting the returned dataclasses. Their receipt digests must equal the identities retained by the completed-retention evidence, and the terminal output set must contain exactly the retained receipt artifact digest.

## Adversarial review corrections

The first draft trusted exact replay dataclasses as sufficient proof of their internal receipt bindings. Independent review treated that as a real composition gap. The verifier now independently rebinds the lease, execution, idempotency key, start receipt, terminal receipt, outcome, timestamps, sorted output set and both canonical receipt digests.

The first mutation runner also selected an exact-type seam that appeared in two verifier layers and would have aborted before executing a mutant. It now targets a unique public-verifier block. Explicit stale nested-authority provenance and both Effect-Lease store identity windows were added to the builder batch.

## Non-authority

This packet does not grant, start, repeat or finish an Effect Lease. It does not retain a receipt, execute a provider, register a production entrypoint, mutate the Primary Checkout, issue OwnerApproval or PromotionReceipt, merge, promote, or change a Gate. The evidence receipt permanently reports every such claim as false and keeps `closed=false`.

## Prepared adversarial verification

The batch includes exact top-level and nested authority type refusal, subclass refusal, malformed and stale revision tests, stale request/policy/lease provenance, wrong entrypoint and scope detachment, absent/started/failed execution tests, internally malformed receipt tests, start/terminal/output substitution tests, double-read state races, both store-identity race windows, hard-link ambiguity, strict Draft 2020-12 schema checks, independent no-effect/no-promotion AST review, sixteen bounded mutants, predecessor regressions, the full suite, package build, isolated-wheel import, and Ubuntu/Windows Python 3.10/3.12 with two hash seeds.

## Remaining boundary

A later small packet must register the exact production entrypoint and guard centrally. The executable packet must replay admission immediately before durable `begin_effect`, perform retention only when `execute=true`, terminalize with exactly the retained receipt artifact digest, reconcile retained `STARTED` state without automatic re-execution, and execute the complete cross-store fault matrix. Only after that may the semantic evidence chain be considered for the canonical Gate-0 release report.

## External verification status

Repository issue #67 remains open. Hosted GitHub Actions jobs terminate before Step 1 with no logs or artifacts. Such runs are external infrastructure evidence only and may not be represented as builder, review, mutation, packaging, platform, full-suite, or release evidence.

Automatic merge and automatic promotion are not authorized. No OwnerApproval has been issued.
