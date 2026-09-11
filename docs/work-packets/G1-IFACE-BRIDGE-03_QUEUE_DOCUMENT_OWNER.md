# G1-IFACE-BRIDGE-03 - File Bridge queue-document owner

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-03
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 2ed9678b27a6cf5b9933c0a7fc9997b8c78488f8
- Dependencies: G1-HIER-01, G1-IFACE-BRIDGE-01, G1-IFACE-BRIDGE-02
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.file_bridge.enqueue` remains the sole registered queue effect door
and continues to own consumer-liveness admission and `begin_effect`; request
normalization, naming, trace stamping, and atomic publication are implemented
by `daedalus.interfaces.bridge.queue` through explicit ports.

## Scope

This third bridge strangler stage moves the retained Codex brief warning,
request-document construction, collision-free filename generation, atomic
publication, and fail-closed legacy request parsing. Dispatch, conversation
projection, poison recovery, watcher ownership, heartbeat policy, CLI parsing,
and all four registered effect entries remain in the facade for later packets.

## Contracts and behavior

- The liveness refusal happens before the registered effect and before any
  outbox write, exactly as before.
- `OUTBOX`, `_stamp`, randomness, `envelope.stamp`, and `write_text_atomic` are
  resolved from the facade on every call and injected into the queue owner.
- Filename stamp, 48-character slug, UUID prefix, JSON field order and values,
  optional project/category fields, trace omission/stamping, two-space JSON,
  atomic visibility, and hand-dropped request defaults are unchanged.
- The implementation owner imports no Daedalus authority and exposes no
  watcher, dispatch, provider, process, network, store, or effect entrypoint.
- Registry targets, effects, wiring, anchors, and semantic digest are unchanged.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Liveness before write | enqueue-guard suite | stale/missing watcher leaves no request |
| Queue identity | collision and parallel-producer suites | every enqueue has a unique readable name |
| Atomic publication | bridge signal/hardening suites | no partial `*.json` is observable |
| Trace and wire ABI | envelope-join and queue golden tests | identical canonical fields and trace behavior |
| Dynamic compatibility | facade-port test | patched path, clock, trace and writer observed per call |
| Effect authority | Effect Registry suites and digest | unchanged facade target and anchor |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

No outbox request, report, journal, heartbeat, SQLite row, historical evidence,
Registry row, or persistent path is migrated. Rollback restores the three
function bodies in `daedalus.file_bridge` and removes the queue owner.

The facade cannot retire until Dispatch, Conversation, and Watcher packets land
and source, runtime-string, wheel, documentation, Effect Registry, monkeypatch,
and pickle audits find no remaining implementation caller.

## Evidence expected failures and review

No queue, bridge, Registry, compile, or compatibility failure is expected. The
generated Work-Packet index is intentionally refreshed only after all parallel
packets integrate. Independent review must confirm that liveness and the
registered effect remain in the facade and publication occurs only afterward.
