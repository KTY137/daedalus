# G1-IFACE-BRIDGE-01 - File Bridge report projection strangler

## Frozen packet metadata

- Packet ID: G1-IFACE-BRIDGE-01
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: e9cf58a9e97db93d8f2627b52a59e2d58808db4b
- Dependencies: G1-HIER-01, G1-WEB-01, G1-ORCH-01, G1-IFACE-HTTP-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

`daedalus.file_bridge` remains the only registered File Bridge effect facade,
while report read-state and status/SSE projections are implemented under
`daedalus.interfaces.bridge.projection` with paths and cross-projection calls
injected explicitly.

## Scope

This first bridge strangler stage moves seven projection implementations:
unread reports, acknowledgement markers, quarantine summaries, report briefs,
project-filtered report ordering, aggregate bridge status, and compact stream
state. Queue admission, crash journal, request dispatch, conversation
projection, poison recovery, watcher ownership, heartbeat policy, CLI parsing,
and all four registered effect entries deliberately remain in the facade for
later packets.

The facade decreases from 2,404 to 2,323 lines. The new 230-line owner imports
only JSON, paths, and typing; it owns no watcher, scheduler, process, network,
SQLite, provider, mission, or effect-boundary entrypoint.

## Contracts and behavior

- Public and private legacy function names remain callable at the same module
  paths and delegate once to the hierarchy owner.
- `INBOX`, `OUTBOX`, `_seen_dir`, `_quarantine_dir`, `heartbeat_status`, and
  other monkeypatch-sensitive seams are resolved from the facade for every
  call and passed as values or callables.
- Report filename order, arrival `(mtime_ns, name)` ordering, project filters,
  summary normalization, missing/malformed JSON handling, acknowledgement
  behavior, and quarantine sidecar interpretation are unchanged.
- `stream_state` retains additive Web packet fields: numeric `in_flight`,
  `queue_depth`, and project-exact `reports_total`/`latest_report`.
- Registry targets and real `begin_effect` anchors remain
  `file_bridge.enqueue`, `file_bridge.process_request`, `file_bridge.watch`,
  and `file_bridge.main`; the semantic Registry digest is unchanged.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Stable effect authority | Registry and facade-anchor suites | unchanged targets, anchors, and digest |
| Stable projections | bridge signal/restart, Web, health and desktop suites | identical status/read/SSE behavior |
| Dynamic compatibility | injected facade-seam test plus existing monkeypatch matrix | patched legacy seams observed per call |
| Directed hierarchy | implementation AST/import test | no reverse facade import or process/effect authority |
| Project isolation | existing WEB-01 projection tests | exact project counts and newest report |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

Rollback restores the seven function bodies in `daedalus.file_bridge` and
removes `interfaces.bridge`. No queue file, report, journal, heartbeat, SQLite
row, historical evidence, Registry row, or persistent path is migrated.

The facade cannot retire until later Queue, Journal, Dispatch, Conversation,
and Watcher packets land and source, runtime-string, wheel, docs, Effect
Registry, and monkeypatch audits find no remaining legacy caller.

## Evidence expected failures and review

No projection, Registry, compile, or compatibility failure is expected. The
known integration painted-effect diagnostic and frozen import-baseline drift
are outside this projection-only packet and remain retained negative evidence.
Independent review must confirm that the implementation owner contains no
effect start, process spawn, scheduler, provider, or new store and that every
legacy path remains the live compatibility seam.
