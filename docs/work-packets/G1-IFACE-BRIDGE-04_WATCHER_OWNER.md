# G1-IFACE-BRIDGE-04 - File Bridge watcher owner

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-04
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: bb33e72ca127477a48218ce59fdf66f23b3f3720
- Dependencies: G1-HIER-01, G1-IFACE-BRIDGE-01, G1-IFACE-BRIDGE-02,
  G1-IFACE-BRIDGE-03
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.file_bridge.watch` remains the only registered watcher effect door
and performs admission before delegation; OS ownership, process identity,
heartbeat publication/classification, and the polling loop are implemented by
`daedalus.interfaces.bridge.watcher` through explicit ports.

## Scope

This fourth bridge strangler stage moves watcher-lock implementation, fork-safe
process identity, watcher-lock locator, heartbeat write/read/restart policy, and
the admitted poll loop. Dispatch, conversation projection, poison recovery,
CLI parsing, and all four registered effect entries remain in the facade for
later packets.

## Contracts and behavior

- `WatcherOwnershipBusy` and `_BridgeWatcherLock` are exact aliases of the new
  owner objects; supported catches and private lock callers do not see a
  duplicate class authority.
- `HEARTBEAT_PATH`, thresholds, `_last_idle_beat`, PID, clock, atomic writer,
  output directories, dispatch, poison recovery, exceptions, stop event, and
  sleep are resolved from the facade per call and passed explicitly.
- Heartbeat JSON fields, throttle, states, ages, restart hints, owner token,
  process identity, startup markers, path ordering, pending-state messages,
  poison routing, interval behavior, and persistent lock path are unchanged.
- The implementation owner imports no Daedalus module and starts no effect,
  provider, process, network, SQLite store, scheduler, or second event source.
- The facade starts `file_bridge.watch` before the owner loop. Registry target,
  effects, wiring, anchors, and semantic digest are unchanged.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| One watcher owner | desktop/runtime lock races | second local owner refused; lock released on exit |
| Restart identity | process-identity tests | PID reuse/fork cannot adopt stale heartbeat identity |
| Liveness ABI | bridge signal, enqueue guard, health suites | same states, thresholds, JSON and restart hint |
| Crash recovery | bridge restart suite | pending bookkeeping/projection never redispatches provider work |
| Dynamic compatibility | facade aliases and existing patched seams | old module paths observe current paths, clocks, dispatch and poison ports |
| Effect authority | facade-order test and Registry digest | admission precedes owner loop; digest unchanged |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

No heartbeat, queue request, report, journal, SQLite row, historical evidence,
Registry row, or persistent path is migrated. The existing ignored
`runs/bridge_watcher.lock` remains the sole OS-claim file. Rollback restores the
watcher bodies in `daedalus.file_bridge` and removes the watcher owner.

The facade cannot retire until Dispatch and Conversation packets land and
source, runtime-string, wheel, documentation, Effect Registry, monkeypatch,
and pickle audits find no remaining implementation caller.

## Evidence expected failures and review

No watcher, bridge, desktop, health, Registry, compile, or compatibility failure
is expected. The generated Work-Packet index is intentionally refreshed after
all parallel packets integrate. Independent review must confirm that the owner
loop is unreachable through the production facade before `begin_effect` passes.
