# G1-IFACE-BRIDGE-02 - File Bridge crash-journal owner

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-02
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 1d13176180cd60f0f7ddffd8e161186f9f1f7cbb
- Dependencies: G1-HIER-01, G1-ORCH-01, G1-IFACE-BRIDGE-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.file_bridge` remains the only registered File Bridge effect facade,
while deterministic request identity, report binding, Effect-Lease identity,
crash-journal paths, reads, precondition checks, and writes are implemented by
`daedalus.interfaces.bridge.journal` through explicit ports.

## Scope

This second bridge strangler stage moves twelve journal and identity
implementations. Queue admission, request dispatch, conversation projection,
poison recovery, watcher ownership, heartbeat policy, CLI parsing, and all four
registered effect entries remain in the facade for later packets. The atomic
publisher remains the dependency-free `daedalus.atomic` implementation and is
injected by the facade; this packet creates no second persistence authority.

## Contracts and behavior

- Public and private legacy names remain callable at the same module path and
  delegate once to the hierarchy owner.
- `ARCHIVE`, `_journal_dir`, `_journal_path`, `_write_json_atomic`, `_now_iso`,
  and canonical hashing are resolved from the facade on each call, preserving
  tests and supported dynamic callers that patch those seams.
- Request keys, digests, report validation errors, Effect-Lease IDs and
  canonical timestamps, journal filenames, mission projection paths, atomic
  publication, and corrupt-journal fail-safe behavior are unchanged.
- Registry targets and real `begin_effect` anchors remain
  `file_bridge.enqueue`, `file_bridge.process_request`, `file_bridge.watch`,
  and `file_bridge.main`; the semantic Registry digest is unchanged.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Stable effect authority | Registry and facade-anchor suites | unchanged targets, anchors, and digest |
| Restart safety | bridge restart/recovery suites | no second provider execution or spend |
| Dynamic compatibility | facade-port monkeypatch tests | patched paths, clock, and writer observed per call |
| Directed hierarchy | implementation AST/import test | no reverse facade, dispatch, process, or provider authority |
| Malformed state | journal unit and restart tests | corrupt journal reads empty and replay remains fail closed |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

No queue file, report, journal, heartbeat, SQLite row, historical evidence,
Registry row, or persistent path is migrated. Rollback restores the twelve
function bodies in `daedalus.file_bridge` and removes the journal owner.

The facade cannot retire until Queue, Dispatch, Conversation, and Watcher
packets land and source, runtime-string, wheel, documentation, Effect Registry,
monkeypatch, and pickle audits find no remaining legacy caller.

## Evidence expected failures and review

No bridge, Registry, compile, or compatibility failure is expected. The known
integration painted-effect diagnostic and generated Work-Packet index drift are
outside this journal-only packet and remain retained negative evidence.
Independent review must confirm that the owner exposes no effect entrypoint,
provider call, scheduler, process spawn, network operation, or second store.
