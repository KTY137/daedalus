# G1-IFACE-BRIDGE-08 - Quarantine transaction owner

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-08
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: c15fed857dbf120bfe2940dd72a046f7c1bb107c
- Dependencies: G1-HIER-01, G1-IFACE-BRIDGE-01 through
  G1-IFACE-BRIDGE-07
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.interfaces.bridge.dispatch` owns quarantine publication, replay,
identity-conflict eviction, and final quarantine moves. The stable
`daedalus.file_bridge` facade reexports the exact exception objects and
constructs explicit operation ports on each call.

## Authority and preserved seams

- `IdentityConflictPorts` receives the inbox, quarantine locator, clock,
  atomic JSON writer, and move operations.
- `QuarantinePorts` receives the canonical request key/digest, existing crash
  journal, complete-report reader, trace stamping, canonical hash, report
  projector, arrival projection, atomic writer, and final move operation.
- The owner imports no Daedalus facade, effect boundary, provider, process,
  network, database, store, or second ledger.
- `RequestIdentityConflict`, `TerminalReportPreserved`, and
  `QuarantineMovePending` are canonical dispatch-owner classes reexported by
  the legacy facade. Old and new imports are identical objects and old pickle
  lookups remain available.
- Facade wrappers resolve all paths and monkeypatch seams per call.

## Preserved behavior

- A contradictory request is moved under its observed-digest suffix without
  overwriting the first request's journal or terminal report.
- Quarantine identity is the same canonical hash of request key, raw digest,
  reason, and detail. Journal states remain `quarantine_pending`,
  `quarantine_move_pending`, and `quarantined` in the same order.
- An existing whole report is never overwritten unless the exact retained
  quarantine record proves replay of that same report.
- A transient conversation projection leaves projection-only retry ownership;
  a permanent conflict is recorded but does not keep poison in the watcher.
- A failed final move remains pending after the report and sidecar are durable;
  replay retries only that move and never provider execution.
- Report/sidecar paths, fields, trace identity, exception messages, effect
  admission, Registry target, archive layout, and persistent formats are
  unchanged.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Exception identity | focused dispatch contract | old/new objects identical |
| Single owner | facade AST contract | one delegation per quarantine wrapper |
| Report authority | restart and conflict suites | terminal report never overwritten |
| Crash replay | restart and signal suites | no duplicate provider/report/projection |
| Directed owner | dispatch import contract | no reverse facade/effect authority |
| Registry stability | semantic digest assertion | exact existing digest |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration, rollback, and evidence

There is no persistent migration. Rollback restores the quarantine bodies and
exception definitions inside `file_bridge.py`; retained requests, reports,
journals, sidecars, conversation events, and archives stay in place.

- Python 3.13: 299 focused bridge, quarantine, conversation, crash, Effect,
  envelope, hardening, and HTTP-loop tests passed; 16 subtests passed.
- Python 3.10: the same 299 tests and 16 subtests passed.
- Changed modules compile and `git diff --check` reports no whitespace defect.
- The semantic Effect Registry digest remains exactly
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.
- G1-HIER-06E independently closes the architecture-contract drift inherited
  by this packet base. Integration verification reruns the zero-edge contract
  after both commits are present.

The generated Work-Packet index is refreshed centrally after parallel packet
integration. This packet does not edit the Master Plan, amendment chain,
historical `runs/`, generated web distribution, Registry target, provider
admission, or promotion state.
