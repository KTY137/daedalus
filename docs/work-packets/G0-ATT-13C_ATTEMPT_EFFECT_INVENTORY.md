# G0-ATT-13C — Canonical Attempt lifecycle effect inventory

## Scope

This packet is stacked on the selected persisted isolated-Attempt lifecycle. It
registers and statically discovers the three newly exposed effectful kernel
methods without claiming that they are already centrally leased:

- `AttemptLedger.begin`;
- `AttemptLedger.complete`;
- `IsolatedAttemptCoordinator.prepare`.

It adds no runtime invocation, Effect Lease issuance, sandbox execution,
EvidencePacket, OwnerApproval, merge, promotion, or primary-checkout mutation.

## Finding

The parent packet correctly documented these methods in its Work-Packet
inventory, but the canonical `daedalus.spine.effect_boundary` registry and
static drift detector did not own them. They could therefore remain invisible
to the machine-readable release report or appear only as an external JSON
exception. Gate 0 requires one canonical registry owner for every production
capable effect boundary; a side inventory is not authority.

## Registration

Each method is represented exactly once as a discoverable Python entrypoint:

| ID | Target | Effects | Current wiring |
|---|---|---|---|
| `python.attempt_lifecycle_begin` | `AttemptLedger.begin` | filesystem write | `local_guards` |
| `python.attempt_lifecycle_complete` | `AttemptLedger.complete` | filesystem write | `local_guards` |
| `python.attempt_workspace_prepare` | `IsolatedAttemptCoordinator.prepare` | filesystem write | `local_guards` |

The retained guards are the canonical Event-Store intent ledger and Attempt
containment contracts. Anchors require the start path to call `record_intent`,
the terminal path to call `mark_completed`, and workspace preparation to call
both `begin` and `materialize_tree`.

`local_guards` is intentional and blocking for Gate closure. These rows may be
upgraded to `central` only after one dependent execution packet mechanically
requires the exact persisted Effect Lease, Runtime Manifest, current Runtime
Conformance Receipt, kill-switch generation and Docker sandbox before workspace
or Event-Store effects.

## Static classifier

The conservative AST inventory explicitly recognizes the two authority classes
and only their public lifecycle methods. It does not classify every method in
`daedalus.kernel` as effectful and does not broaden generic Python discovery.
The discovered effect remains filesystem write; no process, network, spend or
repository-mutation effect is inferred for this non-executing lifecycle packet.

## Adversarial specification

Focused tests require:

- one and only one canonical owner per target;
- exact effects, guards, anchors and honest non-central wiring;
- actual static rediscovery of all three methods;
- no target, anchor, duplicate-owner or unregistered blocker for the methods;
- explicit source-level classifier ownership rather than a hidden exemption.

The bounded mutation runner removes the AttemptLedger classifier and substitutes
the canonical begin target. Both mutations must be killed after a green focused
baseline and production bytes must be restored exactly.

## Remaining boundary

This packet resolves inventory ownership only. It does not authorize execution.
The next dependent packet must compose lifecycle start/terminal and workspace
materialization with the selected Effect-Lease/runtime/sandbox authorities
without replacing the canonical Event Store, source-tree CAS or compatibility
imports.

GitHub Actions issue #67 may still terminate hosted jobs before Step 1. A
zero-step run is infrastructure evidence only and is neither a green result nor
a product failure.

Iron Plan: **ALIGNED BY SCOPE; EXACT-HEAD EXECUTION REQUIRED**  
Iron Gate: **0**  
Promotion: **not requested**
