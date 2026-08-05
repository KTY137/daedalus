# G0-RTC-07M — Provider Target Receipt Retention Completed Evidence

## Status

Verification requested on draft PR #224. The packet is stacked on the frozen exact parent revision `91496022a6a43749487f882c4071b953761eca74` from PR #223.

GitHub Actions issue #67 still prevents executable repository-hosted evidence: jobs terminate before Step 1 without logs or artifacts. Those zero-step failures are infrastructure evidence only.

## Purpose

The recovery decision introduced by the predecessor packet maps a retained `COMPLETED` execution to `verify_completed_retention_evidence`. This packet implements that read-only verification step without crossing into the effectful retention entrypoint.

The verifier accepts the exact completed admission and recovery decision, reauthenticates the provider-target verification receipt against its signed authorities and exact source tree, and then verifies the canonical retention Event-Store row and receipt-CAS object twice. Concrete filesystem identities for the Primary Checkout, Event Store, CAS root and retained artifact are fenced around the reads so path replacement, symlink ambiguity, hard-link ambiguity and read-window races fail closed.

## Ordering contract

1. Require exact structured input types, a positive non-boolean source-byte bound and an exact lowercase 40-hex commit revision.
2. Canonically reconstruct the admission and recovery decision.
3. Bind completed state, recovery action, admission digest, provider-target receipt digest and both Effect receipt identities.
4. Validate the retention topology and capture concrete path/device/inode identities.
5. Capture the retained receipt artifact file identity and require one regular-file identity.
6. Authenticate the provider-target verification receipt and exact source tree.
7. Repeat the topology and artifact identity fence.
8. Strictly read and validate the completed Event-Store intent and retained CAS bytes.
9. Repeat topology, artifact, Event-Store and CAS verification.
10. Compare the two retained-state observations and reconstruct both input receipts again.
11. Emit a strict non-authorizing evidence receipt.

## Evidence boundary

The resulting receipt may claim that the exact provider-target receipt authenticated, the canonical retention intent is complete, the retained bytes are present and canonical, the Primary Checkout is disjoint, and the observed topology and artifact identities remained stable through verification.

It cannot claim that the persisted Effect terminal receipt was verified. It grants no Effect Lease, start, write, terminalization, replay, production registration, promotion, OwnerApproval, Gate transition or Gate closure authority.

## Same-package adapter debt

The packet reuses the retention ledger's strict read-only helpers for effect-key construction, Event-Store reads, receipt canonicalization, topology validation and completed-state validation. This is a bounded strangler adapter, not a new public ledger API. Source review asserts that the composition contains no call to `retain`, `record_intent`, `put_bytes`, `mark_completed`, Effect start/finish, process execution or network APIs. A later responsibility-boundary refactor may expose these read projections publicly without changing the evidence receipt.

## Prepared adversarial review

The batch includes malformed and stale revisions, exact-type/subclass refusal, detached admission/recovery identities, non-completed states, CAS substitution, terminal-detail substitution, artifact hard links, two independent topology race windows, a two-read Event-Store race, strict schema/claim tests, an independent AST/source review and twelve bounded mutations.

The dedicated workflow requests Ubuntu and Windows coverage on Python 3.10 and 3.12 with two hash seeds, predecessor regressions, the full suite, package build and isolated-wheel import. None of those checks may be marked verified until Actions records real steps and artifacts on the exact head.

## Frozen dependent work

The following remains out of scope until a later packet:

- authenticate the exact persisted Effect terminal receipt and bind its outputs to this evidence;
- register the exact production retention entrypoint and guard contract;
- re-run admission immediately before `begin_effect`;
- execute retention only when the persisted lease returns `execute=true`;
- reconcile `STARTED` without automatic re-execution;
- execute the complete intent/CAS/Event-Store/Effect-Lease fault matrix;
- compose the final semantic evidence into the Gate-0 release report.

Automatic merge and promotion are not authorized. OwnerApproval has not been issued or fabricated.
