# G1-IKARUS-10 — Leased queue execution

## Frozen packet metadata

- Packet ID: `G1-IKARUS-10`
- Active gate: **Gate 1 — Renovation ignition slice**
- Classification: `ALIGNED`
- Owner: repository owner; no automatic merge, promotion, or Gate transition
- Base revision: `52b4baa5`
- Master-plan authority: Revision 10
- Master-plan digest: `5e269de9857940cd1d6162eaf9236d4db8e77427d189122db178812b49b259dc`
- Dependency: canonical WaveExecutor, Effect Lease, Kairos scheduler, offload,
  runtime registry, and file bridge already present at the base revision
- Primary claim: one queued Ikarus task reaches the existing local agent loop
  through the canonical lease-bearing execution path, while `local_only`
  exposes no external or untrusted runtime and never falls back.

## Baseline reproduced

`core._try_ikarus()` calls `KairosScheduler.dispatch()` directly. The hardened
offload path requires an Effect Lease, so the scheduler returns
`effect_lease_required`; `_try_ikarus()` then collapses the refusal to `None`.
For `local_only` that becomes a generic failure report, which looks like an
unavailable assistant rather than a missing authorization-bearing caller.

The current availability projection is also too broad for a repaired
`local_only` path: it can advertise Claude, Codex, or DeepSeek to the scheduler,
and an expressly admitted remote Ollama host remains an untrusted egress lane.
The absent lease currently masks that potential routing violation.

## Scope and acceptance

In scope: `daedalus/core.py`, use of the existing `daedalus/build_exec.py`
one-task WaveExecutor seam, focused queue/lease/lane tests, and this packet.

| Claim/refusal | Evidence | Expected |
|---|---|---|
| One queued task | mocked integration test | canonical leased wave reaches offload; no `effect_lease_required` |
| Crash after effect/provider completion but before report | fault-injection restart test | filename-derived lease/execution identity replays; provider and spend are not started twice |
| Lease/admission refusal | fault test | retained and reported, never collapsed into fake success |
| `local_only` with external runtimes available | routing test | only trusted local Ollama visible |
| Remote/untrusted Ollama | lane test | unavailable to `local_only` even when endpoint consent exists |
| Local run fails | integration test | no Claude/Codex/DeepSeek fallback |
| Explicit Claude/Codex lane without broker authority | affected tests | visible fail-closed report; no legacy direct provider call |
| Requested versus executed lane/provider | report/snapshot tests | requested lane retained; actual providers only when evidenced |
| Provider/process/network budget | mocked tests | zero live starts/calls |

Forbidden: no second scheduler, broker, lease issuer, event store, artifact
identity, or promotion path; no caller-minted fake lease; no weakening of Effect,
egress, budget, verification, rollback, or promotion policy; no live provider
test; no Master Plan/amendment/evaluator edit.

Rollback is restoration of the direct scheduler call. That restores the known
fail-closed refusal but also restores the product defect; retained tests must
continue to make that visible. System CI and live provider evidence are not part
of this local builder packet and remain an owner/release prerequisite.
