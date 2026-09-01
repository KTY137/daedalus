# G1-IFACE-BRIDGE-12 - Queue admission owner

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-12
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 17288bb9b17c55644ff0c640a9cbba2a2b8c7dc7
- Dependencies: G1-HIER-01, G1-HIER-06E, G1-IFACE-BRIDGE-01 through
  G1-IFACE-BRIDGE-11
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.interfaces.bridge.queue.admit_enqueue` owns consumer-liveness and
retained Codex-brief admission before queue publication. The registered root
facade injects the current heartbeat, thresholds, warning projection, and
stderr emitter, then starts the unchanged effect before atomic publication.

## Scope

This packet extracts queue admission ownership into a dedicated module under
`daedalus.interfaces.bridge.queue`. The scope covers consumer-liveness checks
and Codex-brief admission logic before a request is published to the queue.

## Contracts and behavior

### Authority and preserved seams

- `WatcherNotRunning` is the canonical queue-owner class reexported by
  `daedalus.file_bridge`; old and new imports are identical objects.
- Heartbeat state is an injected snapshot port. The queue owner imports no
  watcher implementation, effect boundary, provider, process, network,
  database, randomness, or filesystem authority.
- Stale and busy thresholds are supplied from the facade on each call, so
  patched policy constants and heartbeat/brief helpers remain observable.
- The facade retains the registered `file_bridge.enqueue` effect start and
  injects the canonical trace stamper plus atomic publisher into
  `publish_request`.

### Preserved behavior

- Admission runs before the effect and before any outbox write. A default
  refusal therefore leaves no ambiguous queued artifact.
- `stale` and `none` refuse unless `require_watcher=False`; the forced path
  emits the same restart instruction. `wedged` remains admitted with the same
  warning and busy-budget detail.
- The historical Codex inline-brief warning remains non-blocking and precedes
  watcher admission.
- Public constructor compatibility for `WatcherNotRunning(heartbeat,
  objective)` remains; the facade additionally injects its live stale limit.
- Request filename, JSON fields, trace, warning/refusal text, exception fields,
  effect ID/order, Registry target, and persistent paths are unchanged.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Admission order | facade AST contract | admission, effect, publication |
| No dead queue | enqueue guard suite | refusal leaves no file |
| Compatibility identity | focused queue contract | old/new exception identical |
| Live seams | runtime monkeypatch test | current facade ports injected |
| Directed owner | queue import contract | no reverse watcher/effect authority |
| Registry stability | semantic digest assertion | exact existing digest |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

There is no persistent migration. Rollback restores the admission body and
exception definition inside `file_bridge.py`; queued and archived requests are
not moved.

## Evidence, expected failures and review

- Python 3.13: 303 focused bridge, queue admission, crash, Effect, envelope,
  hardening, and HTTP-loop tests passed; 16 subtests passed.
- Python 3.10: the same 303 tests and 16 subtests passed.
- Changed modules compile and `git diff --check` reports no whitespace defect.
- G1-HIER-06E's zero forbidden-edge architecture contract is unchanged.
- The semantic Effect Registry digest remains exactly
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

The generated Work-Packet index is refreshed centrally after parallel packet
integration. This packet does not edit the Master Plan, amendment chain,
historical `runs/`, generated web distribution, Registry target, provider
admission, or promotion state.
