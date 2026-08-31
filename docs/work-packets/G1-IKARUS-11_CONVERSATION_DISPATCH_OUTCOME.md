# G1-IKARUS-11 — Conversation dispatch outcome projection

## Frozen packet metadata

- Packet ID: `G1-IKARUS-11`
- Active gate: **Gate 1 — Renovation ignition slice**
- Classification: `ALIGNED`
- Owner: repository owner; no automatic merge, promotion, or Gate transition
- Base revision: `52b4baa5`
- Master-plan authority: Revision 10
- Master-plan digest: `5e269de9857940cd1d6162eaf9236d4db8e77427d189122db178812b49b259dc`
- Dependency: existing conversation dispatch link, canonical conversation
  spine, file-bridge task id, and terminal report publication
- Primary claim: a terminal report for a task linked to a conversation is
  projected exactly once onto the existing conversation spine, so a later
  turn may learn the observed outcome without making chat orchestration state.

## Baseline reproduced

`POST /api/queue` can link a task id to a conversation turn and
`ConversationStore.record_dispatch_event()` already exists, but the report
producer never calls it. The browser can observe task SSE while it remains
open; after reload, the durable conversation does not reliably say how the
linked task ended.

## Scope and acceptance

In scope: the existing file-bridge report-arrival seam,
`daedalus/conversation.py` only where its existing API/idempotency needs a
narrow correction, focused temp-store tests, and this packet.

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Linked task terminal report | temp-store test | one outcome event with task id/state/summary/detail |
| Retry/restart/same report replay | idempotency test | no duplicate authoritative outcome |
| Task without conversation link | regression test | no conversation mutation |
| Failed/quarantined/unknown application | projection test | honest state; never promoted to applied/success |
| Projection failure after report publication | fault test | report retained; failure visible/best-effort, never rewrites result |
| Transient SQLite/I/O projection failure | fault test | projection-only retry; terminal report prevents provider rerun |
| Permanent projection conflict | watcher fault test | original report retained, request archived/flagged, no quarantine overwrite or retry spin |
| Provider/process/network budget | local tests | zero live starts/calls |

Forbidden: no new event kind, conversation database, task identity, report
identity, orchestration authority, or promotion path; no polling thread; no use
of assistant prose as task truth; no Master Plan/amendment/evaluator edit.

Rollback removes only the report-to-conversation projection. Queue reports and
task SSE remain authoritative and unchanged; old conversations remain readable.
