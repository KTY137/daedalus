# G0-RTC-07H — Provider-target receipt-retention inventory refresh

## Exact stack

- Parent branch: `g0/provider-target-receipt-retention-topology-hardening-linear`
- Parent revision: `0df759d1fd9bc5d83e9fc72f1c850756afa93fe5`
- Work branch: `g0/provider-target-receipt-retention-inventory-refresh-linear`
- Hardened ledger Git blob: `a5e3d1321e257c9ce1d70e9a68e4079445c6985a`

## Reason for the packet

The topology-hardening packet changed `daedalus/runtimes/provider_target_receipt_ledger.py`. The retained inventory scanner still discovered the seven intended write surfaces, but its main fixture supplied the older pre-hardening revision `b2bda280f8f98d6e977e092c5429da3c85427a33`. Because the scanner intentionally accepts a caller-supplied revision, that fixture could produce a byte-current but revision-stale report.

This packet replaces that fixture identity with the exact topology-hardened parent and checks the complete Git blob framing as well as the scanner's SHA-256 over the same bytes. The seven classified surfaces, malformed-source tests, source-redirection tests and anchor-bypass tests remain unchanged.

## Honest authority boundary

This is a refresh of prepared discovery evidence, not central admission. It does not change production behavior, the canonical effect registry, the guard contract or the retention ledger. Every discovered write remains `inventory_only`, blocking, without a consumed persisted Effect Lease.

The scanner does not authenticate Git HEAD. It binds exact bytes to revision text supplied by its caller. The test fixture now binds that text to the exact reviewed parent Git blob, but a future central packet must compose the authenticated repository-HEAD receipt before the inventory can participate in production admission or release closure.

## Adversarial checks prepared

- exact topology-hardened parent revision and Git blob identity;
- independent SHA-256 recomputation over the current ledger bytes;
- deterministic seven-surface inventory and permanent `closed=false`;
- malformed revision, UTF-8, BOM, NUL and syntax refusal;
- source and parent-directory symlink refusal;
- missing, duplicated, renamed and unclassified write-anchor refusal;
- separate static review of the Work Packet's non-authority and stale-revision disclosure;
- Ubuntu and Windows on Python 3.10 and 3.12, two hash seeds, predecessor regressions, full suite, package build and isolated-wheel import.

No source inspection or model statement is hard evidence. GitHub Actions issue #67 still prevents hosted jobs from reaching Step 1, so all executable verification remains pending. No change to `main` or `experimental`, no merge, promotion, OwnerApproval, PromotionReceipt or Gate transition is authorized.
