# G1-IFACE-BRIDGE-06A - File Bridge dispatch-claim owner

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-06A
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: b6ee91eb0cb7129fbfdef6239ef5ed00e9a67f23
- Dependencies: G1-HIER-01, G1-IFACE-BRIDGE-01, G1-IFACE-BRIDGE-02,
  G1-IFACE-BRIDGE-03, G1-IFACE-BRIDGE-04, G1-IFACE-BRIDGE-05
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.file_bridge.process_request` remains the only registered request
effect facade and starts `file_bridge.process` before delegation; filename-key
resolution, the cross-process request claim, and loser recovery are implemented
by `daedalus.interfaces.bridge.dispatch` through explicit ports.

## Scope

This first dispatch stage moves only the outer claim transaction. The claimed
request state machine, report publication, provider dispatch, conversation
projection, poison recovery, watcher, and CLI remain behind the facade for
subsequent packets.

## Contracts and behavior

- Every watcher, CLI `once`, and direct recovery call starts the registered
  effect before acquiring the same filename-derived blocking OS lock.
- `INBOX`, request-key and lock-path derivation, lock implementation, complete
  report reader, and claimed state machine are resolved from the facade on each
  call and injected.
- A consumer that loses the claim race returns the winner's complete fixed-path
  report when the request was archived while it waited. Missing source plus no
  complete report remains `FileNotFoundError`, never invented success.
- No effect ID, target, effects, wiring, anchor, report path, lock path, request
  key, JSON field, digest, provider admission, or persistent format changes.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Admission order | facade AST and Registry suite | `begin_effect` precedes owner call |
| Single consumer | bridge concurrency/restart tests | one provider call and one report |
| Crash-race loser | focused owner and existing bridge tests | reuse complete report; never redispatch |
| Missing authority | focused owner test | no report means `FileNotFoundError` |
| Directed owner | implementation import test | no reverse facade, effect, process, network or store authority |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

No request, report, journal, lock, conversation row, historical evidence,
Registry row, or persistent path is migrated. Rollback restores the claim body
inside `process_request` and removes the dispatch owner.

The facade remains until the claimed state machine and Conversation ownership
land and source, runtime-string, wheel, documentation, Effect Registry,
monkeypatch, and pickle audits prove the compatibility path can retire.

## Evidence expected failures and review

No bridge, desktop, Registry, compile, or compatibility failure is expected.
The generated Work-Packet index is refreshed centrally after parallel
integration. Review must confirm the owner is unreachable in production before
the facade's registered effect admission succeeds.
