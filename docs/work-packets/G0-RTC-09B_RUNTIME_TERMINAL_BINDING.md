# G0-RTC-09B — Runtime terminal capability binding

## Purpose

This small independent Gate-0 security packet closes one capability-ownership
hole in `RuntimeBoundEffectAuthorization`. It is based directly on the selected
release-assessment line and does not depend on the unverified non-runtime facade
packet.

No provider row changes wiring, no external provider is invoked, no trust record
is admitted, no owner decision is produced, and no merge, promotion or Gate
closure is requested.

## Finding

`RuntimeBoundEffectAuthorization.begin_effect()` durably binds a start receipt
to the exact signed runtime-bearing Effect Lease. Its previous
`finish_effect()` method delegated any supplied start receipt to the shared
`EffectLeaseLedger` without first proving that the receipt belonged to the
capability's own lease.

The ledger correctly validates a retained execution row, but a caller holding a
shared ledger and one runtime authorization could otherwise attempt to
terminalize a valid start receipt created under another lease. Ledger validity
is not capability ownership.

## Correction

Before any ledger call, `finish_effect()` now requires:

```text
start_receipt.lease_sha256 == capability.lease.digest
```

A mismatch raises `EffectLeaseBindingMismatch`; no terminal ledger method is
called. Exact receipts continue to delegate once with unchanged outcome,
outputs and detail identity.

The check intentionally does not require active runtime trust for every terminal
outcome. A failed or quarantined runtime must still be able to durably record
`FAILED` or `CANCELLED`. The provider broker's separate terminal trust fence
continues to govern `COMPLETED` output release.

## Adversarial verification requested

A focused independent test surface uses a recording ledger to prove:

- a foreign lease digest is refused before ledger delegation;
- an exact receipt is delegated exactly once without argument drift;
- the ownership comparison is the first statement of `finish_effect()`;
- only one terminal delegation exists in the method.

The bounded mutation runner replaces the ownership comparison with `if False`
after a green baseline, requires the focused tests to kill it, and verifies
source restoration.

Dedicated CI requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds,
Iron Plan verification, compile-all, the parent Effect-Lease and runtime
admission suites, provider-broker and terminal-fence regressions, the mutation,
full repository pytest and an isolated-wheel import.

## Independent review boundary

This finding was derived by reviewing capability authority separately from
ledger persistence authority. It is model-generated review support, not a human
security approval, RuntimeFaultAttestation, OwnerApproval or Gate evidence.

## External verification blocker

GitHub Actions issue #67 remains active: hosted jobs have been terminating before
Step 1 with empty step lists and no logs. Such conclusions cannot validate this
head. The packet remains draft until real commands execute on the exact revision.

## Gate state

- Iron Plan: aligned by scope; exact-head execution required
- Active gate: Gate 0
- Promotion: not requested
- Gate closure: not claimed
