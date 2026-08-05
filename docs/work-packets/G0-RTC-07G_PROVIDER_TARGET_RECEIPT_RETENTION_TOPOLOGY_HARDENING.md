# G0-RTC-07G — Provider-target receipt-retention topology hardening

## Exact stack position

- Parent branch: `g0/provider-target-receipt-retention-contract-linear`
- Parent revision: `dc800f931f1a90be4b3c7b846d3650d4b3091fd8`
- Packet branch: `g0/provider-target-receipt-retention-topology-hardening-linear`
- Gate: 0
- State: prepared, not exactly executed or accepted

## Adversarial finding

The retention ledger previously proved only resolved path disjointness between the Primary Checkout, receipt CAS and SQLite Event Store. A hard link inside the Primary Checkout can name the same inode as the checkout-external Event Store while those resolved paths remain different. Subsequent SQLite writes would then mutate bytes visible through a Primary-Checkout path.

This is a source-review finding. It is not represented as an executed exploit or as proof that the complete Gate-0 mutation boundary is closed.

## Bounded correction

The packet keeps the existing retention design and adds only topology hardening:

1. The Primary Checkout, receipt-CAS root and Event-Store path must contain no symlink components.
2. The receipt CAS must resolve to a real directory.
3. The Event Store must resolve to a regular file with link count exactly one.
4. The existing pairwise resolved-path disjointness checks remain mandatory.
5. Topology is checked at construction and rechecked after receipt authentication immediately before the first schema or data write.

No provider execution, central entrypoint, Effect-Lease start, promotion, OwnerApproval or Gate transition is added.

## Builder and adversarial evidence prepared

The focused tests cover an Event-Store hard-link alias present at ledger construction and an alias introduced after construction but before `retain(...)`. The late-alias case must refuse before the retention uniqueness index, Event-Store intent or receipt artifact is written.

The separate source-review test requires the regular-file and single-link checks and proves that the post-authentication topology revalidation precedes schema, intent, CAS and terminal writes. The bounded mutation campaign now includes removal of the hard-link check and removal of the prewrite revalidation.

The dedicated workflow requests:

- Ubuntu and Windows with Python 3.10 and 3.12 under two hash seeds;
- focused builder and independent-review tests;
- bounded mutations;
- predecessor inventory, contract and ledger regressions;
- full suite;
- package build and isolated-wheel import.

## Inventory consequence

This packet changes `provider_target_receipt_ledger.py` source bytes. Any predecessor retention-inventory report is therefore stale for this branch. A dependent centralization packet must regenerate and bind the exact-head inventory; the old report cannot be reused for release closure.

## Residual boundary

A hostile process retaining concurrent ambient filesystem authority can create an alias after the last userspace preflight. Full exclusion requires the later leased target and sandbox boundary to remove that authority rather than relying only on repeated path inspection.

GitHub hosted Actions remain blocked by issue #67 before Step 1. Until jobs execute real steps on the exact head, this packet claims prepared verification only. It does not authorize merge, promotion, owner approval, modification of `main` or `experimental`, or Gate closure.
