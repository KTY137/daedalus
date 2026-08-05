# G0-RTC-07L — Provider Target Receipt Retention Recovery Decision

## Purpose

This packet adds a deterministic restart/replay projection for the exact
`ProviderTargetReceiptRetentionAdmissionReceipt` introduced by the predecessor
packet. It answers only which non-authorizing follow-up is required for the
observed persisted execution state.

The packet is pinned to admission revision
`b6d274a5c3d77cef9f9bc9fc0c272ef2d72eccc8` through the frozen parent branch
`g0/provider-target-receipt-retention-admission-frozen-b6d274a`. The live
admission PR may continue changing independently without silently changing this
packet's reviewed base.

## Closed state mapping

| Admission state | Decision | Meaning |
|---|---|---|
| `not_started` | `request_fresh_start_authorization` | A later effectful boundary must repeat admission and obtain fresh authority. |
| `started` | `manual_reconciliation_required` | The external outcome is unresolved. Automatic replay and retention are forbidden. |
| `COMPLETED` | `verify_completed_retention_evidence` | Existing terminal and retention evidence must be authenticated; no new execution is implied. |
| `FAILED` | `terminal_failure_refusal` | The execution is terminal and cannot be retried through this identity. |
| `CANCELLED` | `terminal_cancellation_refusal` | The execution is terminal and cannot be retried through this identity. |

## Security boundary

The projection accepts only the exact admission receipt type and an exact
40-hex expected source revision. It refuses stale revisions, reconstructs the
admission's canonical wire form before projection, and repeats the snapshot,
reconstruction, digest, revision, and execution-state checks after projection.

The output binds:

- source revision;
- admission digest;
- execution state;
- the single permitted state-specific decision;
- start and terminal receipt identities, where applicable.

It permanently records that it did not independently reverify persisted state.
It grants no Effect Lease, execution, retention, terminalization, approval,
promotion, registry, or Gate authority.

## Adversarial verification

The prepared batch covers all five states, malformed and stale revisions,
subclass and duck-typed inputs, frozen-dataclass mutation, inconsistent receipt
state, state/action substitution, receipt substitution, extra wire fields, and
claim escalation. An independent AST review refuses effectful imports, writers,
process/network surfaces, callbacks, ledgers, and lifecycle calls. A bounded
mutation campaign targets exact-type, revision, state/action, receipt, final
snapshot, and authority-claim fences.

CI requests focused tests on Ubuntu and Windows with Python 3.10 and 3.12 under
two hash seeds, predecessor regression, the complete suite, package build, and
isolated-wheel import.

## Explicitly excluded

This packet does not register a production entrypoint, re-read persisted state,
grant or start an Effect Lease, invoke `ProviderTargetReceiptLedger.retain`,
terminalize an effect, reconcile an unresolved external outcome, mutate the
Primary Checkout, create OwnerApproval, promote a candidate, or close Gate 0.

The effectful dependent path remains frozen until its predecessors have hard,
executable verification evidence and the exact production boundary can be
reviewed with the complete fault matrix.

## External verification blocker

Issue #67 records repository-wide GitHub Actions jobs terminating before Step 1
without logs or artifacts. Those runs are not product evidence. This packet
therefore remains `verification_requested`; no CI, platform, mutation,
packaging, or release claim is made until real workflow steps execute.
