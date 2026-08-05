# G0-RTC-07I — Repository HEAD Receipt Integration

## Exact stack

- Parent branch: `g0/provider-target-receipt-retention-inventory-refresh-linear`
- Parent revision: `c0e1a378ce560d25d2225c8ea67f9bb2122be3db`
- Integration branch: `g0/provider-target-receipt-retention-head-receipt-integration-linear`
- Reviewed source branch: `g0/repository-head-revision-receipt-linear`
- Reviewed source revision: `8171be198b4e14308b41abd002ea34e94eed7a88`

## Bounded change

This packet ports the generic process-free repository `HEAD` verifier, its exact schema, adversarial tests and bounded mutation runner onto the provider-target receipt-retention line. The seven transferred files retain their exact Git blob identities from the reviewed sibling branch. A separate integration review recomputes every Git blob identity from checkout bytes and records that equality only as transfer provenance.

The verifier supports a stable detached `HEAD`, one loose symbolic ref or one exact packed-ref row. It refuses malformed or multiline metadata, nested symbolic refs, duplicate packed rows, symlinked metadata, unsupported worktree gitfiles, stale revisions and changing observations. Its receipt permanently states that commit-object validity and worktree cleanliness were not verified and that no process was spawned or repository mutation performed.

## Adversarial review boundary

The integration review checks the exact transferred blobs and independently parses the verifier to reject direct process, network and filesystem-write surfaces. The original builder, malformed-input, stale-revision, race, symlink, wire-claim, schema and mutation suites are retained unchanged.

No execution result is claimed. Source inspection, blob equality and model statements are not hard evidence. Exact-head CI remains blocked by repository issue #67, where hosted jobs terminate before Step 1 without logs or artifacts.

## Deliberate next boundary

This packet does not compose the generic `HEAD` receipt with the provider-target verification receipt, refreshed retention inventory, signed retention operation authority, persisted Effect Lease or retention ledger. A later small central-admission packet must live-reverify the receipt and require exact revision equality across those subjects before any effect transition or write.

No direct change to `main` or `experimental`; no merge, automatic promotion, OwnerApproval, PromotionReceipt, provider execution or Gate transition.
