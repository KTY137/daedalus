# G0-PRM-25M — Promotion Recovery Consumption Inventory Delta

## Scope

This packet makes the new recovery-decision consumption writes mechanically
visible without silently patching the canonical registry at import time. It
provides a deterministic, canonically hashed integration delta for the next
small effect-boundary batch. The canonical `effect_boundary.ENTRYPOINTS`, guard
map and scanner remain unchanged in this packet.

## Exact write surfaces

The delta declares exactly two Python entrypoints:

| Entrypoint | Effect | Current wiring | Current guard |
| --- | --- | --- | --- |
| `PromotionRecoveryConsumptionLedger.__init__` | filesystem write | unguarded | none |
| `PromotionRecoveryConsumptionLedger.consume` | filesystem write | local guards | authenticated owner recovery decision |

The constructor is not mislabeled as owner-authorized: it creates the SQLite
schema before any decision exists. Its required migration is to split schema
creation into an explicit initializer under a persisted Effect Lease. The
`consume` method is genuinely bound to an authenticated owner recovery decision,
but it is not yet routed through the canonical Effect-Lease lifecycle and is
therefore not claimed as central.

## Scanner delta

The proposed static scanner hook is exact: only module
`daedalus.kernel.promotion_recovery_consumption`, class
`PromotionRecoveryConsumptionLedger`, and methods `__init__` and `consume` are
classified. `verify_consumption` and `consumed` remain excluded because they use
strict read-only SQLite connections and are not write starts.

The tests resolve both target methods and their source anchors directly from the
AST. They also run the current canonical scanner and prove that both targets and
the `promotion.owner_recovery_decision` guard contract are still absent. This is
an explicit machine-readable blocker, not a conformance claim.

## Integration boundary

The module imports neither `effect_boundary` nor SQLite, subprocess or Git
machinery. It cannot append, update or monkey-patch canonical registry state.
The next dependent packet must make a normal reviewed source edit to the
canonical effect boundary, extend its scanner, and update conformance tests.

## Prepared adversarial verification

Builder tests cover canonical delta hashing, exact row and guard contents, exact
scanner matching, source target and anchor resolution, current canonical gap
proof, uniqueness and ordering. A separate review rejects runtime registry
mutation and effectful imports/calls, verifies that no central/closed claim is
made, resolves every target and guard evidence function independently, checks
the exact blocker set and rejects wildcard scanner matching. Seven bounded
mutants attack false integration, hidden constructor exposure, fabricated
constructor guards, false centrality, read-only-method misclassification,
blocker removal and wildcard module matching.

Exact-head compilation, focused tests, mutation execution, full suite,
packaging and the supported platform/Python matrix remain pending. Repository
GitHub Actions issue #67 has repeatedly ended jobs before Step 1 with no logs or
artifacts; those runs are infrastructure observations only.

## Non-claims

No canonical registry row or guard contract was changed. No OwnerApproval or
owner recovery decision was issued. No Effect Lease was cancelled or
terminalized. No merge, promotion, automatic action or Gate transition occurred.
Gate 0 remains open.
