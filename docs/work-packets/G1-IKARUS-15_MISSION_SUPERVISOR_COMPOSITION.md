# G1-IKARUS-15 — Mission supervision on the canonical wave path

Packet ID: G1-IKARUS-15
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: Ikarus orchestration
Base revision: e6dbcc816008c22da280369156173feba2630fba
Dependencies: G1-ORCH-01, G1-IKARUS-01, G1-IKARUS-04, G1-IKARUS-05, G1-IKARUS-06, G1-IKARUS-10, G1-IKARUS-11

Authority is Master Plan Revision 11, SHA-256
`711DE9F0BDF0AB15011314528821B75ED5666906F4805EC9FF9C65386ED5A3B2`.
The packet does not amend the plan and requests no merge, promotion, provider,
network, EDA, or release operation.

## Primary acceptance claim

`daedalus.orchestration.run_mission` remains the only productive execution
composition and invokes the existing `WaveExecutor.run` exactly once. An
optional exact `MissionSupervisor` now projects planned and returned mission
state into its existing deletable chained ledger before and after that call.
The composition never calls `MissionSupervisor.run`, constructs a
`TaskAttempt`, executes a role harness, or treats the projection as replay,
receipt, scheduler, spend, evidence, or conversation authority.

Existing One-shot Request, Runtime Evidence, Tool Scope, Effect Lease Request,
and Effect Execution Request subjects may be supplied to the service only as
one exact bundle per canonical WorkItem. The service reconstructs and compares
their canonical projections, budget and identity bindings before execution.
Because Gate 1 has no centrally admitted Hermes/one-shot registry entry and no
WaveExecutor consumer for that authority, a valid bundle still fails closed
before projection or wave execution. This packet does not widen Codex, Ollama,
Hermes, or any provider row.

## Scope

In scope:

- opt-in resume/idempotent publication for the existing supervisor projection
  ledger while preserving historical `publish` behavior;
- disposable before/after projection functions over existing
  `BuildSession`, `MissionContract`, `BuildRunReport`, and `WaveResult` types;
- optional supervisor and exact One-shot subjects at the internal
  `run_mission` seam;
- File Bridge composition of a projection directory derived only from its
  observed, internal request filename identity through SHA-256;
- crash/replay, no-second-spend, one-call, idempotency, fail-closed and static
  boundary evidence.

Out of scope:

- any new scheduler, event store, attempt, receipt, provider client, admission
  owner, conversation state, evidence authority, or promotion path;
- changing CLI names, HTTP routes, JSON contracts, Mission/WorkItem IDs,
  canonical digests, SQLite formats, Effect Lease identities, or registry rows;
- production Hermes registration or import; it remains fixture-backed;
- resolving G1-ORCH-01's Loop identity blocker;
- chat/SSE behavior, frontend code, navigation, generated assets, or workflows.

## Contracts and behavior

The supervisor integration has only informational authority:

1. the exact session and mission are snapshotted and cross-bound;
2. `mission.json` is immutable and an existing different mission is refused;
3. the existing state ledger is re-verified before a resumed append;
4. identical planned or terminal state is not appended twice;
5. a terminal projection never regresses to planned during File Bridge replay;
6. the first immutable Mission bytes remain projected across crash replay;
   only `provenance.created_at`, which `run_mission` freshly owns per process,
   may differ, while every other Mission field must remain identical;
7. each result must carry the canonical WorkItem stamp written by
   `WaveExecutor`;
8. projected rows deliberately contain no invented attempt, receipt, or
   evidence digest;
9. projection I/O/integrity errors are bounded diagnostics and cannot suppress,
   replace, repeat, or downgrade a canonical executor report.

The production File Bridge derives the directory as
`<journal>/mission-supervisor/<sha256(filename-key)>`. Request JSON cannot
choose or broaden that filesystem path. The existing per-request process lock,
crash journal, Effect Lease ledger, provider terminal receipt, spend envelope,
report publication, and canonical Spine conversation projection keep their
current owners. The conversation projection remains idempotent and cannot
cause provider replay.

One-shot validation requires exactly one tuple of five exact existing objects
per WorkItem. Mission ID, attempt/WorkItem ID, trace, request/evidence/tool
digests, runtime identity, manifests, policy digest, scope, timeout, cost,
execution narrowing, and unique request/execution/idempotency identities are
checked. An absent registry row, any `inventory_only`/`local_guards` row, a
runtime mismatch, or the absence of a central WaveExecutor consumer refuses
before `WaveExecutor.run`. No fallback or ambient provider discovery exists.

The Effect Registry file is not edited. Its source SHA-256 before this packet
is `FB060B3E32949A1911E920AE91AA0C883410CA5A36074DB9C338F5A64DE7F165` and
must remain identical at handoff. The measured runtime registry contains 108
rows and has digest
`ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.

## Acceptance matrix

| Claim | Positive evidence | Negative evidence |
| --- | --- | --- |
| One productive scheduler | exact `WaveExecutor` object returns the existing report | AST proves one `.run` and no `supervisor.run`, `dispatch`, new scheduler, or `TaskAttempt` |
| Disposable supervision | planned then landed revisions bind one Mission/WorkItem | deletion loses no Effect, Attempt, report, evidence, spend, or Spine authority |
| Idempotent restart | re-opened ledger returns the same terminal digest | no third revision and no terminal-to-planned regression |
| Unknown-outcome recovery | crash after provider terminal retains landed projection | restart opens no second spend envelope and calls provider once |
| Projection isolation | injected post-execution disk error is retained diagnostically | the exact canonical report is still returned and execution is not retried |
| Exact One-shot bridge | all five existing subjects rebuild byte/digest-equivalent | tampered tool/execution subject refuses before executor |
| Provider admission | registered wiring/runtime are inspected after exact validation | absent Hermes and inventory-only Codex both refuse before executor |
| Registry stability | source hash is recomputed after implementation | no ID, target, effect, wiring, anchor, or digest change |
| IKARUS-10/11 retention | Effect Lease replay and conversation projection suites remain green | no second spend and no conversation-triggered execution path |

Focused implementation evidence prepared in this branch includes:

- `tests/orchestration/test_ikarus_mission_integration.py`;
- the real crash-after-provider-before-report case in
  `tests/test_bridge_restart.py`;
- existing supervisor, One-shot, tool-scope, Effect Bridge, runtime-role,
  dynamic routing, conversation, Web, and execution-limit suites;
- static source scans and a registry source hash comparison.

No frontend file changes, so an npm build is not an acceptance signal for this
packet.

## Migration and rollback

The stable `MissionSupervisor.run` method remains for its existing tests and
compatibility callers, but production composition does not call it. The new
`StateLedger(resume=True)` and `publish_if_changed` behavior is opt-in; all old
constructors and `publish` calls retain their sequence behavior.

Rollback removes the optional `run_mission` projection/One-shot parameters and
delegation, restores File Bridge's two-argument internal call, and deletes the
new projection directories. No authoritative artifact, historical `runs/`
evidence, canonical Spine row, Effect Lease row, report, CAS object, Mission ID,
or digest requires migration or reversal. One-shot remains unexecutable before
and after rollback.

Shim retirement is not applicable: this packet adds no re-export facade and
moves no public target. Loop migration remains blocked until its single run ID
and iteration-created WorkItems can be reconciled without changing Mission,
Effect Lease, replay, or report identity.

## Evidence expected failures and review

The pre-change focused baseline produced `227 passed, 2 subtests passed` plus
one timing-sensitive cancellation assertion that passed immediately in
isolation. It is recorded as a baseline flake, not hidden as packet evidence.
No packet test is expected to fail. A repeatable cancellation failure, registry
hash change, second executor/provider/spend call, new terminal ledger revision
on exact replay, or One-shot execution is release-blocking.

Final combined focused verification on this branch produced `372 passed,
2 subtests passed` in 78.66 seconds. The only warning is Python's forward-looking
3.14 tar-extraction deprecation in an unchanged execution-limit test. Focused
`compileall` and staged-diff whitespace validation passed. No provider, model,
network, EDA, npm, merge, push, promotion, or release command ran.

The read-only ontology preflight used repository label `g1-ikarus-15`, created
no snapshot/workspace, executed no target code and used no network or LLM. It
counted 1,326 Python files, skipped 3 excluded-directory and 29 sensitive-name
entries, and classified the Python adapter as partial. Dynamic imports,
descriptor dispatch, generated code, monkey patching and runtime
metaprogramming remain statically unknown, so focused runtime and wheel audits
are still required before shim retirement or Gate closure. Static correlation
does not prove runtime causation.

Reviewer stop conditions are:

- any second Mission/Attempt/Effect/Evidence/Conversation authority;
- any call to `MissionSupervisor.run` or a role harness from production
  `run_mission`;
- any One-shot/provider call without a separate centrally admitted owner and
  exact canonical authorization consumer;
- any changed Effect Registry source digest or row;
- any provider replay, second spend envelope, hidden retry, moved historical
  evidence, or change to external routes/fields/IDs/digests.

At handoff, exact commands, counts, registry digest, commit identity, the named
baseline flake, and the retained Loop/admission blockers are reported. No Gate
closure, mergeability, promotion, or release claim follows from this packet.
