# G1-IKARUS-03 — Provider-neutral runtime event projection

Status: **IMPLEMENTED / DRAFT INTEGRATION** (2026-08-30)  
Authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, Revision 8  
Active gate: **Gate 1**  
Iron Plan: **ALIGNED**

## Objective

Port the remaining bounded Hermes/ACP callback motif needed by Ikarus without importing Hermes as a competing agent product: parallel tool calls must correlate unambiguously and cancellation must preserve unfinished plan entries instead of silently dropping them.

This packet deliberately does **not** make a provider executable. G1-IKARUS-02 remains the runtime-selection boundary; `hermes_agent`, `claude_cli`, and `codex_cli` stay `source-only` until a later packet supplies canonical runtime/effect/observation authority through the existing Daedalus broker.

## Implementation

`daedalus/ikarus_runtime_events.py` adds one per-run, in-memory `RuntimeEventProjector`.

- A declared `plan_entry_id` is bound to a runtime `call_id` exactly once at tool start.
- Terminal callbacks resolve **only** through the bound `call_id`; tool names are descriptive and never a fallback identity. Parallel calls with the same tool name therefore remain unambiguous even when terminal callbacks arrive out of order.
- The projector allocates a contiguous local callback sequence under one lock, so concurrent callback threads cannot race call-id uniqueness or half-apply a transition.
- Tool completion retains only a SHA-256 observation digest, never arbitrary provider stdout/stderr or transcript text.
- Run cancellation freezes every unfinished planned/running row as `cancelled`, preserving a started call id when one exists and retaining not-yet-started plan entries explicitly.
- The immutable snapshot has a canonical digest and stable declared-plan ordering.

The module imports only Python standard-library data/locking/hash/JSON primitives. It opens no file, database, socket or subprocess and defines no event store, provider, runtime registry, tool registry, scheduler or policy engine.

## Hermes provenance and improvement boundary

The behavior is derived from the pinned upstream study recorded in `docs/research/hermes-agent-v2026.8.19-provenance.json`, especially ACP event forwarding, same-name parallel tool correlation and cancelled-plan projection. No upstream code is copied.

The Daedalus port is intentionally stricter than a name-based callback adapter: correlation requires an explicit plan-entry-to-call-id binding, and terminal observations are content-digest-only. This is an architectural improvement for auditability, not a claim that Ikarus already has whole-product Hermes parity.

## Adversarial coverage

`tests/test_ikarus_runtime_events.py` covers:

1. parallel same-name calls finishing in reverse order;
2. duplicate call-id refusal without state mutation;
3. unknown terminal call refusal with no name fallback;
4. planned tool-name substitution refusal;
5. cancellation retaining succeeded, running and never-started rows;
6. frozen state after cancellation;
7. deterministic projection digest for the same logical callback sequence;
8. malformed terminal observation digests;
9. a source-level boundary check excluding subprocess/network/database/filesystem authority.

Authoring smoke against the exact packet contents: `12 passed` for the focused test file in an isolated temporary package. This is not a substitute for repository exact-head pytest, full-suite, package, platform or Gate evidence.

## Deferred integration

A later small packet may connect this projector to an actually admitted runtime adapter only after that adapter is behind `daedalus.runtimes.broker.run_runtime_provider(...)` with its exact `RuntimeBoundEffectAuthorization`, `EffectExecutionRequest`, provider-observation authority, isolated workspace/container boundary and content-addressed output evidence.

The future adapter should retain the projection digest in its observation/evidence bundle; it must not turn this in-memory projection into a second canonical event store. `TaskAttempt` and the shared Spine/Event Store remain authoritative for execution lifecycle state.

## Non-goals

- no Hermes gateway, messaging, cron or scheduler;
- no Hermes memory, learning graph, SessionDB/FTS or checkpoint database;
- no plugin/skill mutation;
- no provider subprocess or network call;
- no new approval, evaluator or promotion authority;
- no change to the authoritative Master Plan;
- no Gate transition or automatic merge/promotion.
