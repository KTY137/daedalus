# G1-IFACE-HTTP-03 - SSE delivery owner

## Frozen packet metadata

- Packet ID: G1-IFACE-HTTP-03
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 81bc5670f67d1482ab9523a9498a9bdd90467194
- Dependencies: G1-IFACE-HTTP-01, G1-IFACE-HTTP-02, G1-WEB-01, G1-IKARUS-14
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`
- Assessment date: 2026-08-31

## Primary acceptance claim

`daedalus.interfaces.http.sse` is the sole implementation owner for SSE
snapshot reads, live-event delta selection, frame encoding, bounded dashboard
streaming, common response headers, frame writes, and disconnect control flow.
`daedalus.web_api` remains the stable router/effect facade and resolves its
legacy projection ports at every call.

## Scope

This is the next bounded strangler stage after G1-IFACE-HTTP-01. It separates
the previously interleaved dashboard stream into these responsibilities:

| Owner member | Responsibility |
|---|---|
| `snapshot_events` | call the injected project-scoped `stream_state` port |
| `event_changes` | select report, queue, and heartbeat deltas without changing fields |
| `encode_event` | preserve the legacy JSON and SSE byte framing, including event IDs |
| `_open_stream` | write the existing SSE headers and connection mode |
| `_write_frame` / `_ClientDisconnected` | isolate transport writes and client disconnects |
| `stream_events` | run the bounded snapshot/poll/keep-alive loop |

The three task-subscription timing values, used only by SSE delivery, move from
`daedalus.web_api` to this owner. `_task_snapshot` deliberately does not move:
it is the shared read projection for `GET /api/queue/<id>`, task artifacts, and
task SSE. The facade injects that projection, its task-ID rule, terminal-source
rule, and `stream_state` on each call so established monkeypatch seams remain
live.

No route, handler class, server, socket, store, scheduler, singleton, effect
entrypoint, provider permission, UI source, generated web artifact, persistent
format, historical evidence, Master Plan record, or amendment is added or
changed.

## Contracts and behavior

The following public behavior is frozen:

- `/api/events` remains a five-minute keep-alive SSE feed and reads the exact
  requested project on every snapshot.
- The initial `hello` event retains the complete compact bridge projection.
- A report event is emitted only when that project's `reports_total` advances,
  and carries that project's `latest_report`.
- Queue events retain the field `queue_depth`.
- Heartbeats retain `watcher_state` and numeric `in_flight`; `queue_depth` and
  `in_flight` remain JSON integers and the latter remains exactly `0` or `1`.
- JSON serialization remains `json.dumps(..., default=str)` and SSE bytes
  remain `id`, `event`, and `data` lines followed by one blank line.
- Headers remain status `200`, `Content-Type: text/event-stream`,
  `Cache-Control: no-cache`, the existing keep-alive/close connection mode,
  and `X-Accel-Buffering: no`.
- A broken/reset/closed client ends delivery locally. It does not reread the
  snapshot, reopen the stream, or replay provider/task work.
- Ikarus, task, and conversation-request streams use the same encoder and
  disconnect boundary without changing their one-shot behavior or fields.

### Compatibility-shim register

| Shim | Owner/target | Removal criterion |
|---|---|---|
| `web_api.DaedalusHandler._handle_events` | `interfaces.http.sse.handle_events`; injects `web_api.stream_state` per call | an approved Registry/router target migration plus source, runtime-string, monkeypatch, wheel, docs, and Effect-Registry audits find no legacy handler caller |
| `web_api.DaedalusHandler._handle_task_events` | `interfaces.http.sse.handle_task_events`; injects shared task projection/validation per call | the shared queue read projection has a separate hierarchical owner and the same caller audits prove the facade seam removable |
| Other `web_api` SSE handler methods | matching `interfaces.http.sse` handler | the G1-IFACE-HTTP-01 facade retirement criteria are met |

The semantic Effect Registry digest and all registered targets remain exactly
unchanged. The SSE literal contract now covers both the handlers and their
extracted helpers: 174 literals with digest
`e4a3de4ae47c3d648d2ffb690288002079b3c6588c63f9ddad2c0d1bb74e44c7`.
Read and effect literal digests remain their frozen-parent values. Behavioral
tests, rather than the structural digest alone, pin the exact frame bytes and
additive field names/types.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Project isolation | actual file-bridge project-filter suite plus SSE snapshot-port test | every read uses the requested project; another project's report cannot advance this stream |
| Additive live fields | decoded SSE frame test | `queue_depth` and `in_flight` are integers; report/latest values remain project exact |
| Wire compatibility | exact encoder bytes, headers, event ordering, and literal-contract tests | no route, JSON key, SSE line, header, or status drift |
| Disconnect safety | broken-pipe test | one snapshot and one failed write; no reread or replay |
| Dynamic compatibility | facade monkeypatch test | replacement `web_api.stream_state` is passed by identity on that call |
| Directed ownership | AST responsibility/import test | no owner import of `web_api`/`file_bridge`; stream loop does not encode or write directly |
| Shared read projection | facade AST test | `_task_snapshot` remains outside the SSE owner; SSE-only timings do not |
| Effect stability | Registry digest and target tests | exact digest above and unchanged facade targets |
| Interpreter support | focused Python 3.13 and 3.10 tests/cold imports | same passing behavior on both supported interpreters |
| Provider/network budget | builder-only test matrix | zero live provider, network, or EDA calls |

Frontend sources are outside this packet, so npm, Playwright, Tauri, package,
lock, navigation, and visual checks are not applicable. The global Work Packet
index is intentionally not regenerated on this isolated branch.

## Migration and rollback

There is no persisted-data migration. Rollback restores the previous inline
header/encoder/write blocks in `interfaces.http.sse`, restores the three task
timing constants and keyword injection in `web_api`, and removes this packet's
tests. The facade, routes, stores, Registry, CAS locators, evidence paths, and
JSON/SSE contracts do not need rollback translation.

## Evidence expected failures and review

No failure is expected in this packet's focused compile, cold-import, wire,
project-filter, Registry, or worktree-scope matrix. A deliberately broader
conversation-manager probe retained one pre-existing timing race:
`test_cancel_is_requested_then_confirmed_only_after_worker_stops` can observe
state `cancelled` just before its cancellation projection advances from
`requested` to `confirmed`. Five isolated Python 3.13 repetitions failed once
on this packet and twice in a temporary, unmodified exact-parent worktree at
`81bc5670f67d1482ab9523a9498a9bdd90467194`. Neither
`conversation_requests.py`, `conversation.py`, nor that test is changed here;
the negative evidence is not allowlisted as a packet pass and belongs to its
conversation-state owner.

No provider, network, browser, frontend build, EDA, merge, promotion, or live
server operation is authorized.

The packet document itself passes the repository parser's complete post-index
metadata/section validator. A whole-repository `--render` remains blocked on
the exact parent by the already tracked
`G1-HERMES-01_SHARED_LOOPBACK_PREDICATE.md`, which lacks the canonical
`Scope`, `Contracts and behavior`, and
`Evidence expected failures and review` sections. This packet does not edit
that unrelated artifact or regenerate the global index.

Independent review must confirm that project filtering still originates in
the canonical file-bridge projection, that the SSE owner receives that port
instead of importing the bridge facade, that `bool` is not accepted as proof
of numeric `in_flight`, that disconnect handling cannot repeat a snapshot or
generation, and that `_task_snapshot` was not forced into an SSE-only owner.
