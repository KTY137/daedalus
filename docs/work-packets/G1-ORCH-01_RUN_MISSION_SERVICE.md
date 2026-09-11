# G1-ORCH-01 — Canonical `run_mission` Service

Packet ID: `G1-ORCH-01`
Artifact role: `primary`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `151b8d180e321cfba48b4c7d62f9be56579d52a5`
Dependencies: `G1-HIER-02A at 575873fcbadeac7a82a2637e1cc232e3662bbd4a (9335643ea3053dfab0fcdef9c69a3b74da5a3b14 on the packet branch)`

## Authority and classification

- Iron Plan: `ALIGNED`
- Iron Gate: `1`
- Master Plan: Revision 11, SHA-256
  `711DE9F0BDF0AB15011314528821B75ED5666906F4805EC9FF9C65386ED5A3B2`
- Frozen common parent: `151b8d180e321cfba48b4c7d62f9be56579d52a5`
- Packet branch: `packet/g1-orch-01`
- Required prerequisite: lazy Kernel facade `575873fcbadeac7a82a2637e1cc232e3662bbd4a`
  (cherry-picked on this branch as `9335643e`)
- Promotion, merge, push, live provider, EDA, and network execution: not requested

## Scope

This packet changes composition only. It does not amend the plan, define a new
Mission/WorkItem/Effect/Attempt/Evidence contract, add an event store, add a
scheduler, add a promotion path, or claim Gate-1 completion.

## Primary acceptance claim

An already planned `BuildSession` now enters execution through one internal
`daedalus.orchestration.run_mission` service. The service re-derives the
session's existing WorkItem identities, creates the existing canonical
`MissionContract`, cross-binds existing `EffectBounds`, and calls the existing
`WaveExecutor.run` exactly once. Effect-Lease, Attempt, artifact, evidence,
replay, cancellation, and promotion behavior remain owned by their existing
implementations.

The service returns only existing objects: `(MissionContract, BuildRunReport)`.
It defines no request, scheduler, result, ledger, receipt, or state class.

## Tracked execution-path inventory

The frozen-parent inventory found these production composition points:

| Surface | Frozen-parent execution path | Packet result |
| --- | --- | --- |
| Web `POST /api/queue` | `web_api._handle_post -> core.queue_task -> file_bridge.enqueue` | unchanged external HTTP/JSON contract; transitively reaches the service when the durable watcher executes the request |
| File Bridge | `_process_request_claimed -> core.process_bridge_payload -> core._try_ikarus -> WaveExecutor.run_wave` | durable exactly-once journal remains owner; execution now reaches `run_mission`, with no extra BuildSession persistence |
| top-level CLI `spawn --live` | `KairosScheduler.spawn(..., dry_run=False) -> dispatch` | live execution now plans a bound BuildSession and calls `run_mission`; output remains the established flat per-task row list |
| top-level CLI `spawn` preview | `KairosScheduler.spawn(..., dry_run=True)` | retained as a read-only plan; `dry_run=True` is pinned and it has no live dispatch authority |
| build-executor CLI | `WaveExecutor.run` | delegates to `run_mission`; CLI flags and `BuildRunReport` rendering remain unchanged |
| Loop | one run ID plus a newly picked BuildSession/WorkItem per iteration, then direct `run_wave` | not migrated in this packet; exact blocker below |
| `MissionSupervisor` | tested vertical supervisor slice, no production caller | not silently substituted; later G1-IKARUS integration owns that composition |

`KairosScheduler.accept` remains usable as pure routing/classification. The
migration removes independent live `.dispatch`, `.run_wave`, and `.spawn(...,
dry_run=False)` calls from the migrated Web/File-Bridge/Core/CLI chain; it does
not rename or duplicate the scheduler.

## Contracts and behavior

Before `WaveExecutor.run` can classify or dispatch:

1. the service requires exact existing `BuildSession` and `WaveExecutor`
   objects;
2. `BuildSession.bind_work_items()` re-derives every settled WorkItem ID and
   substance digest;
3. changed objective, owner, path, ordinal, Mission ID, or WorkItem identity
   refuses before execution;
4. supplied `EffectBounds`, when present, must name the same Mission, source
   revision, and trace;
5. the Mission budget mirrors the existing lease issuer's configured fallback
   conversion (micro-USD and wall-time) and captures the executor's existing
   `ExecutionLimitPolicy`;
6. `mission_contract_for_build_session` binds the unchanged effect-registry
   digest and canonical provenance;
7. the returned existing `BuildRunReport` must name the same Mission.

The service owns its provenance timestamp. No caller-controlled Mission clock,
policy digest, WorkItem list, scheduler callback, or alternative executor port
is accepted.

## External and persistence compatibility

- CLI command names and flags are unchanged.
- Live `spawn` still renders a flat JSON list of per-task result rows.
- Web routes and request/response fields are unchanged.
- File-Bridge request, journal, report, archive, replay identity, and retry
  fields are unchanged.
- `persist_session=False` suppresses only the legacy BuildSession snapshot for
  the File-Bridge-owned durable flow; it does not suppress Effect, Attempt,
  artifact, evidence, or report persistence.
- Existing IDs, canonical JSON, SQLite formats, CAS/evidence locations, Effect
  Registry targets/effects, and promotion behavior are unchanged.

The effect registry source SHA-256 at baseline is
`FB060B3E32949A1911E920AE91AA0C883410CA5A36074DB9C338F5A64DE7F165` and
must remain identical at the packet commit.

## Explicit Loop blocker

The frozen Loop cannot honestly construct one immutable `MissionContract` for
its current identity. `LoopDriver` creates one `run_id`, places that value in
every wave's `EffectBounds.mission_id`, and only then picks a new candidate and
derives a new one-item `BuildSession` on each iteration. Consequently the full
WorkItem set does not exist when the Mission starts.

Creating a fresh `MissionContract` per iteration under the same `run_id` would
create contradictory canonical Missions. Changing the Mission ID per iteration
would alter persistent Effect-Lease/Attempt/report identities. Pre-freezing the
queue would change the Loop's re-pick semantics. All three are outside a
structure-only packet, so the direct Loop seam is retained and named rather
than hidden.

A dependent packet must either freeze a complete Mission DAG before the first
iteration or explicitly migrate the Loop's identity/replay contract with
golden ID, ledger, runtime-string, report, and recovery evidence. Until then,
the Loop is the measured remaining scheduler-path blocker; this packet does not
claim the repository-wide no-duplicate-scheduler exit criterion.

The common parent also lacks its tracked Campaign implementation. This packet
does not synthesize or substitute one.

## Static ontology preflight

The Code Ontology Companion 0.5.3 ran only `doctor` and `preflight` against the
authorized local repository label `g1-orch-01` after the prerequisite. Evidence
is current, deterministic, static source evidence; no snapshot/workspace was
created and no files were written. It observed 1,322 Python source files,
skipped 3 excluded-directory and 29 sensitive-name entries, and reported the
Python adapter as `partial` for declarations/imports/calls/inheritance and
pipeline roles. Dynamic imports, descriptor dispatch, generated code,
monkey-patching, and runtime metaprogramming remain unsupported/runtime-unknown.

The analyzer did not import, build, test, or execute target code and made no
direct network request. Optional Ollama enrichment was not used. RDF 1.1
Turtle remains the portable export if a later owner-authorized snapshot is
created; store-specific extensions would require mapping. Static proximity and
call correlation do not establish runtime causation, so focused runtime tests
remain mandatory.

## Acceptance matrix

Prepared focused evidence covers:

- public import identity of `daedalus.orchestration.run_mission`;
- one exact Mission and WorkItem set passed to one existing executor call;
- Mission/Effect binding drift refusal before executor entry;
- absence of parallel contract, scheduler, store, dispatch, or `run_wave`
  implementation in the service;
- transitive Web/File-Bridge/Core delegation;
- CLI live delegation while dry planning stays pinned to `dry_run=True`;
- unchanged dynamic bridge routing/refusal behavior;
- unchanged build vocabulary and Loop behavior;
- unchanged registry digest and zero registry diff.

Baseline before implementation:

- `tests/test_dynamic.py`: 20 passed;
- `tests/test_build_vocabulary.py`: 19 passed;
- `tests/test_loop.py`: 30 passed;
- `tests/test_web_api.py`: 29 passed, 2 subtests passed.

Measured after implementation with the main checkout's repository virtual
environment against this isolated worktree:

- `tests/orchestration/test_run_mission.py` plus the affected Dynamic,
  Build-Vocabulary, Web, Loop, Bridge-Restart, CLI-Effect-Boundary, and lazy
  Kernel-facade suites: `356 passed, 2 subtests passed`;
- focused production/test `compileall`: passed;
- Effect Registry source SHA-256: unchanged at the value recorded above;
- source scan: the migrated chain has no live `.dispatch`, `.run_wave`, or
  `.spawn(..., dry_run=False)` call; the direct Loop seam remains visible.

No live provider, model, network, EDA, merge, push, or promotion operation was
part of verification.

## Migration and rollback

Rollback restores the migrated callers to their previous direct executor call;
no persistent data migration is required. G1-IKARUS-15 remains responsible for
composing `MissionSupervisor`, One-shot Effect Bridge, WaveExecutor, durable
Mission projection, and accepted IKARUS behavior into the single production
flow. Loop identity migration remains a separately reviewable prerequisite.

## Evidence expected failures and review

The retained expected blockers are the Loop identity mismatch and the frozen
parent's absent Campaign implementation; neither is represented as a green
repository-wide scheduler claim. Independent review must verify single
executor entry, exact Mission/WorkItem/Effect binding, unchanged external and
persistent contracts, and the continued visibility of the direct Loop seam.
