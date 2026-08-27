# ADR-022: Bounded reuse of NousResearch Hermes Agent

## Status

Accepted for source/design reuse; runtime execution deferred (2026-08-27)

## Context

ADR-002 rejected code merely labelled “Hermes”: it was an unauthenticated
WebSocket server with a second scheduler and event vocabulary. Reconsideration
therefore requires an exact upstream, version, license, threat model,
integration seam and replacement cost.

The evaluated upstream is
[`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent),
release `v0.20.5`, annotated tag `v2026.8.19`, tag object
`b05e680e63d39d5a8e3ec0f5842a41d1c4209c03`, dereferenced commit
`fcbd1076a93841fa88855acce810e342a5b78101`, tree
`cc9f987a403a1d02b8b17cc527a57b54402e864b`. It is MIT-licensed, copyright
2025 Nous Research. Exact hashes and inspected files are retained in
`docs/research/hermes-agent-v2026.8.19-provenance.json`.

Hermes is a whole agent product: model loop, tool/plugin registry, terminal
backends, gateway, cron, sessions, SQLite/FTS memory, learning features and ACP
transport. Importing it wholesale would create competing orchestration,
memory, policy and event authorities inside Daedalus.

## Decision

We reuse only bounded, attributable motifs:

- per-run backend/tool selection;
- explicit iteration and wall-time budgets;
- one-shot invocation as a future live-runtime constraint;
- callback/event normalization, including correlation of parallel same-name
  tool calls;
- loss-aware projection of cancelled plan entries.

The first implementation is `RuntimeRoleRegistry`: immutable, caller-local,
duplicate-rejecting, data-only and vendor-neutral. It binds a role to a
versioned runtime descriptor before Ikarus dispatch. Unlike Hermes'
process-level runtime, it is not a second tool, policy, trust or effect
registry. Only fixtures injected through the existing `RoleHarness` seam are
executable in G1-IKARUS-02; any Hermes descriptor is permitted only in
`source-only` mode.

No Hermes source code is copied or vendored by this decision. If a later packet
copies a substantial portion, it must retain the upstream copyright and MIT
permission notice with the copied material and record exact file-level
provenance.

A future executable Hermes adapter is allowed only as a pinned, stateless
one-shot/container runtime behind the canonical provider broker. It must:

- run in the attempt-owned isolated worktree and a container/user namespace
  with ephemeral `HOME`, `USERPROFILE` and `HERMES_HOME`;
- disable session recall/database, memory, background review, learning,
  gateway, cron, checkpoint, automatic context/plugin/skill loading and all
  skill mutation;
- receive a sanitized environment with an explicit secret allowlist;
- receive a Daedalus-owned tool allowlist, deadline, iteration/cost bounds,
  egress policy and cancellation signal;
- treat stdout/ACP callbacks solely as observations; source-tree/CAS artifacts
  and canonical receipts remain authoritative;
- pass exact-version runtime conformance, containment and unknown-outcome tests
  before its effect-registry row can become central.

## Threat model

The upstream code is trusted neither as a sandbox nor as policy. A configured
or compromised Hermes runtime can spawn processes, write outside an intended
scope through host tools, use network credentials, load plugins, retain session
or memory state, create background work and emit incomplete/misleading events.
Its default agent loop may also run far longer than a mission budget. Therefore
CLI flags, prompts, upstream approvals and local-terminal deny rules are defense
in depth only; Daedalus runtime trust, leases, worktree containment, broker
receipts and independent gates remain the boundary.

## Excluded upstream surfaces

Gateway/messaging, cron, scheduler/delegation, SessionDB/FTS5, memory and
learning graph, plugin/skill mutation, terminal sandbox authority, batch
checkpoints/statistics, approval policy, evaluator and promotion are excluded.
None may silently become Ikarus state.

## Replacement cost

The current reuse is documentation plus a small local dispatch port with zero
runtime dependency. Removal means deleting that port and its source-only
descriptor/provenance; the existing deterministic supervisor continues to
work. A future executable adapter must remain separately deletable and cannot
own mission, attempt, artifact, policy or memory state.

## Consequences

Claude CLI, Codex CLI and Hermes can share one Ikarus selection vocabulary
without making any of them the harness. This ADR does not claim live Hermes
support, runtime isolation, security equivalence or production admission.

Iron Plan: ALIGNED
Iron Gate: 1
