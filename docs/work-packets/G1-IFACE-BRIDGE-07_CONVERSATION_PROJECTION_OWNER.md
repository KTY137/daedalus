# G1-IFACE-BRIDGE-07 - Conversation projection owner

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-07
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 24f5102b8704794f7434064788361889344d5423
- Dependencies: G1-HIER-01, G1-IFACE-BRIDGE-01 through
  G1-IFACE-BRIDGE-06B
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.interfaces.bridge.conversation` owns linked terminal-report
projection, transient-failure classification, reconciliation validation, and
projection-only requeue. `daedalus.file_bridge` remains the registered effect
facade and reexports the exact owner exception objects.

## Scope

- The owner receives the canonical Conversation database path/store, report
  field derivation, SQLite exception type, completed-report reader, journal,
  archive/outbox paths, and move operations as explicit ports.
- It imports no Daedalus facade, Effect Registry, conversation store,
  SQLite implementation, provider, process, or network module.

## Contracts and behavior

- The facade resolves `_conversation_report_fields`,
  `_is_transient_projection_failure`, `_completed_report`,
  `_project_report_to_conversation`, `_requeue_for_projection`, paths, and
  filesystem operations on every call, preserving existing monkeypatch seams.
- `ConversationProjectionPending` and `ConversationProjectionFailed` are
  canonical owner classes reexported by the old module. Old and new imports
  therefore reference the same class objects; old pickle lookups remain
  resolvable through the facade.
- Unlinked work remains a strict no-op and does not create the canonical
  database.
- Stable source identity remains `file_bridge.report:<request-key>` and the
  canonical store remains the only event authority.
- Only SQLite busy/locked, bounded OS transient errors, and Windows sharing
  violations own automatic projection retry. Integrity, attribution, schema,
  and unknown-dispatch failures remain permanent.
- A retry can return an archived request to the existing outbox only when the
  existing crash journal proves the terminal report step. It cannot dispatch
  provider work a second time.
- Reconciliation validates the fixed inbox locator before the facade starts
  the unchanged `file_bridge.process` effect and delegates projection.
- No database row, request, report, journal, archive, path, JSON field,
  source-event ID, effect ID, Registry target, or persistent format changes.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Object identity | focused owner contract | old/new exceptions are identical objects |
| Effect admission | facade AST contract | begin precedes reconciliation projection |
| Fixed locator | owner validation test | traversal and drive paths refused |
| No second spend | restart/reconciliation suite | report proof required before requeue |
| Directed owner | import contract | no reverse facade/store/effect imports |
| Registry stability | semantic digest assertion | exact existing digest |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

There is no persistent migration. Rollback restores the projection and retry
bodies plus exception definitions inside `file_bridge.py` and removes the
conversation owner target from the shim registry.

The generated Work-Packet index is refreshed centrally after parallel packet
integration. This packet does not edit the Master Plan, amendment chain,
historical `runs/`, generated web distribution, Registry target, provider
admission, or promotion state.

## Evidence, expected failures and review

- Python 3.13: 296 focused bridge, conversation, crash, Effect, envelope,
  hardening, and HTTP-loop tests passed; 16 subtests passed.
- Python 3.10: the same 296 tests and 16 subtests passed.
- Changed modules compile, shim JSON parses, and `git diff --check` reports no
  whitespace defect.
- The semantic Effect Registry digest remains exactly
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.
- The packet base still carries the previously identified dangling budget shim
  locator. G1-HIER-06E owns that independent architecture-contract repair;
  this packet neither changes nor weakens its baseline.
