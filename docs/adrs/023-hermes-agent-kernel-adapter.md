# ADR-023: Hermes Agent as a Daedalus-governed Ikarus userspace runtime

## Status

Selected for adapter implementation and fixture-backed verification by
`G1-IKARUS-13` on the current Gate-1 checkout (2026-08-31). This is an
implementation candidate, not an owner merge, promotion or Gate decision.

Live model invocation and production admission remain deferred until the full
containment, unknown-outcome and exact-upstream compatibility evidence is green.
This ADR extends ADR-022; it does not weaken its threat model.

## Context

Ikarus already owns a deterministic `MissionSupervisor`, `TaskAttempt`, runtime
role bindings, a canonical effect bridge and the sealed provider broker. Its
self-built conversational/agent surface is still substantially less mature than
Hermes Agent and would require months of parallel development to reach comparable
model-loop, context, tool-call and streaming behaviour.

Copying Hermes wholesale into Daedalus would be faster initially but would create
competing authorities for scheduling, memory, policy, tools, sessions and side
effects. Calling an unrestricted Hermes CLI would be equally unsafe: the runtime
could load ambient state, retain memory, start background work or execute host
tools outside Daedalus receipts and leases.

The evaluated upstream remains the ADR-022 source:

- repository: `NousResearch/hermes-agent`;
- release: `v0.20.5`;
- annotated tag: `v2026.8.19`;
- commit: `fcbd1076a93841fa88855acce810e342a5b78101`;
- tree: `cc9f987a403a1d02b8b17cc527a57b54402e864b`;
- license: MIT.

## Decision

Hermes is admitted only as a replaceable **userspace agent runtime**. Daedalus
remains the kernel and the sole source of authority.

```text
MissionSupervisor / TaskAttempt
        |
RuntimeRoleRegistry + 07D3 invocation binding
        |
sealed 07D4 ProviderRuntimeOperation
        |
HermesRuntimeAdapter
        |
pinned, isolated Hermes AIAgent worker
        |
authenticated loopback tool gateway
        |
Daedalus-owned tool invoker / capability broker / effects
        |
canonical observations, receipts and output digests
```

The adapter is implemented under `daedalus/integrations/hermes/`. Importing the
package performs no I/O, registers no operation and opens no model connection.
Registration and execution are explicit caller actions.

### Authority ownership

| Surface | Owner |
| --- | --- |
| Mission, work item and attempt identity | Daedalus |
| Runtime selection and exact executable binding | Daedalus |
| Capability policy, approvals, leases and cancellation | Daedalus |
| Tool allowlist and argument schema | Daedalus |
| Repository/worktree effects and receipts | Daedalus |
| Artifact/CAS state, verification, promotion and rollback | Daedalus |
| Canonical memory and learning | Daedalus |
| One-shot model loop and model-facing tool-call syntax | Hermes worker |
| Model-facing context assembly from explicit inputs | Hermes worker through the adapter |
| Worker stdout/stderr | Observation only; never authority |

Hermes must not become a second scheduler, policy engine, memory database,
artifact store, evaluator or promotion system.

## Exact source and replacement boundary

The adapter verifies the upstream Git commit, tree, `run_agent.py` digest,
`LICENSE` digest and clean checkout before every run. The worker verifies the
`run_agent.py` digest again immediately before importing it. A dirty checkout,
wrong tree, wrong file bytes or missing license is refused before model work.

No upstream source is vendored by this packet. The runtime is an external pinned
checkout, so removal means deleting the adapter package and its registration;
the deterministic Ikarus supervisor and other runtimes remain functional.

## Process and state containment

Each invocation uses:

- an attempt/caller-supplied workspace;
- a separate ephemeral runtime root;
- disjoint checkout, workspace and runtime roots;
- ephemeral `HOME`, `USERPROFILE`, `HERMES_HOME`, `TMP`, `TEMP` and `TMPDIR`;
- `PYTHONNOUSERSITE=1` and `PYTHONDONTWRITEBYTECODE=1`;
- an explicit ordinary environment allowlist;
- a separate explicit secret allowlist;
- explicit wall-time, iteration, tool-call and output bounds;
- process-group termination on cancellation or timeout;
- a production-required outer sandbox command.

The uncontained profile exists only for fixture-backed tests. It is not a
production default or an admission claim.

Hermes memory, learning, gateway, cron and checkpoint surfaces are disabled in
the child environment. The adapter supplies only caller-authenticated context
fragments and a read-only memory snapshot. Memory mutation raises rather than
falling back to an upstream database.

## Tool boundary

The sealed 07D4 registry receives a fixed, module-level operation and independent
output-digest verifier. No callback, closure or arbitrary callable crosses the
provider registry.

Nested model tool calls use a one-shot loopback gateway owned by the caller. Its
descriptor binds:

- request and task identity;
- the immutable tool-scope digest;
- an expiry;
- a maximum call count;
- a random bearer token stored in an exclusive mode-0600 file.

The gateway validates the exact tool name and a conservative JSON-schema subset
before invoking the caller-supplied Daedalus tool boundary. Unknown tools,
invalid arguments, exhausted budgets and tool failures produce explicit,
digest-bound refusals. Hermes receives text observations only. Daedalus retains
receipt, invocation and observation digests.

## Protocol and observations

Parent and worker communicate through a strict bounded JSONL protocol with exact
message fields, contiguous sequence numbers and correlated tool-call IDs.
Protocol drift, oversized output, malformed JSON, task-identity drift or a
terminal event with open tool calls is a failure.

Worker stdout is reserved for the protocol. Upstream prints are redirected to
stderr, which is bounded and represented by a digest. Neither stream can replace
canonical Daedalus state.

## Production admission

The adapter can be merged while remaining non-production. Production admission
requires all of the following evidence:

1. sealed broker and exact executable binding verified;
2. real outer containment verified on supported hosts;
3. gateway fault matrix verified;
4. unknown-outcome reconciliation verified;
5. exact pinned upstream compatibility verified;
6. no inherited Claude, Codex, fixture, supervisor or broker regression.

`HermesAdmissionEvidence.production_admitted` is true only when every evidence
bit is true. This packet intentionally leaves the evidence default false.

## Rejected alternatives

### Deep Hermes fork

Rejected because long-lived upstream divergence would make security review,
upgrades and removal expensive.

### Hermes owns Daedalus tools directly

Rejected because it bypasses capability policy, leases, receipts and independent
verification.

### Reuse Hermes sessions, memory, cron or learning

Rejected because those surfaces would create a second canonical state and
background authority.

### Replace `MissionSupervisor`

Rejected. Hermes is a runtime selected by the existing supervisor, not the
Ikarus harness.

## Consequences

Ikarus can reuse a mature agent loop without rebuilding Hermes feature-for-feature.
The integration remains vendor-neutral at the runtime-role and invocation-binding
layers. Claude, Codex, fixtures and future runtimes continue to share the same
Daedalus contracts.

The cost is a stricter adapter and a larger fault matrix. That cost is accepted
because Daedalus, not an upstream agent, must remain the system of record.

Iron Plan: ALIGNED
Iron Gate: 1
