# G0-PRM-25L — Durable One-Use Promotion Recovery Decision Consumption

## Scope

This packet persists the one-use consumption of an externally supplied,
authenticated owner recovery decision. It records authority only. It does not
cancel or terminalize the retained Effect Lease, invoke Git, mutate a worktree,
retry promotion, issue OwnerApproval, or synthesize an owner decision.

## Two-stage current-state verification

`PromotionRecoveryConsumptionLedger.consume(...)` first verifies the decision's
owner signature, validity interval, source revision, promotion authorization,
recovery-plan digest and retained effect-start receipt against the current strict
cross-ledger state. It then opens `BEGIN IMMEDIATE` and performs the full
verification again before inserting anything.

The two verified projections and their exact expectations must be equal. The
ledger refuses a backwards clock, a changed recovery subject and a decision that
expires before persistence. A final canonical receipt binds the verified owner
decision, the current recovery expectation and the exact consumption timestamp.

## One-use constraints

The durable table independently constrains:

- decision digest and decision ID;
- owner/key/nonce tuple;
- promotion-authorization digest;
- recovery-plan digest;
- retained effect-start receipt digest;
- expectation, verified-decision and consumption digests.

A second decision for the same promotion recovery subject is therefore not an
alternate replay channel. SQLite integrity failures are translated into a
specific replay refusal and the transaction is rolled back.

## Strict retained verification

`verify_consumption(...)` opens the database with `mode=ro`, requires SQLite
`query_only`, rejects symlink database paths, re-authenticates the persisted
owner signature and maximum TTL, reconstructs all canonical JSON contracts and
checks every redundant security column. `consumed(...)` uses the same strict
read-only connection. Only ledger initialization and `consume(...)` are write
surfaces.

## Deliberate writer boundary

The receipt is not cancellation authority by itself. A later packet must verify
the persisted receipt, reproject the current Effect-Lease/promotion state again
inside the cancellation writer, and prove that the resulting terminal receipt
belongs to the retained effect start while no promotion start exists. The new
initialization and consumption write surfaces must also be added to the
machine-readable effect-entrypoint registry before Gate 0 can close.

## Prepared adversarial verification

Builder tests cover durable round trip, same-decision replay, independently
re-signed same-subject replay, forged signatures before ledger reads, a changed
effect-start between preflight and transaction, backwards clocks, expiry before
persistence, redundant-column tampering, canonical-JSON corruption and malformed
inputs. A separate review verifies authority limits, exact parser fields,
read-only inspection, two-stage transaction ordering, one-use constraints and
all persisted security-column comparisons. Ten bounded mutants attack deferred
transactions, stale-state bypass, authority-equality removal, expiry removal,
subject replay, persisted-signature removal, redundant-column omission, unbound
fields and read-only connection hardening.

Exact-head compilation, focused tests, mutation execution, full suite,
packaging and the supported platform/Python matrix remain pending. Repository
GitHub Actions issue #67 has repeatedly ended jobs before Step 1 with no logs or
artifacts; those runs are infrastructure observations only.

## Non-claims

No OwnerApproval or owner recovery decision was issued. No Effect Lease was
cancelled or terminalized. No merge, promotion, registry centralization or Gate
transition occurred. Gate 0 remains open.
