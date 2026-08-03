# G0-WP-05 — Runtime manifests and evidence-bound conformance

Status: builder candidate  
Classification: ALIGNED  
Active gate: Gate 0 — Canonical Kernel  
Base revision: `9d7a34a2f15a2a21ecb193fb0c56fb23f0c8c34d` (`g0/effect-leases`)  
Dependency: canonical `RuntimeManifest` and `RuntimeConformanceReceipt` contracts

## Why this packet is independent

G0-WP-04 source-tree CAS is awaiting GitHub-hosted CI execution. Runtime
conformance depends on the canonical contracts and Effect Lease foundation, not
on candidate-tree storage, so this packet proceeds on its own short-lived
branch from G0-WP-03. No result from the blocked CAS packet is assumed.

## Primary acceptance claim

Given one revision-bound `RuntimeManifest`, one adapter implementing the
provider-neutral probe session protocol, and one content-addressed evidence
writer, Daedalus executes the exact Gate-0 runtime fixture matrix and emits a
`RuntimeConformanceReceipt` whose status is derived solely from retained check
evidence.

The exact checks are:

1. `start`;
2. `stream`;
3. `tool-events`;
4. `structured-output`;
5. `timeout`;
6. `cancellation`;
7. `workspace-isolation`;
8. `cost`.

## In scope

- `daedalus/runtimes/__init__.py`
- `daedalus/runtimes/conformance.py`
- `tests/runtimes/test_conformance.py`
- `tests/runtimes/runtime_fixture_worker.py`
- `.github/workflows/gate0-runtime-conformance.yml`
- this packet

## Forbidden scope

- modifying the legacy runtime registry or provider implementations
- claiming Claude, Codex, Ollama, API, MCP, or File Bridge conformance
- opening network connections or making paid model calls
- writing the primary checkout
- creating or consuming OwnerApproval
- promotion, merge, or deployment
- adding a new production subprocess entrypoint

## Architectural boundary

The production package contains only the provider-neutral harness, event/request
shapes, and adapter/session protocols. The real Python subprocess fixture lives
under `tests/`; moving it into production would create another effectful start
surface before centralized leasing exists.

Production adapters remain responsible for their process/API effects and must
be routed through the canonical effect boundary before this harness is used in
a production-capable path. This packet therefore proves conformance semantics,
not final central effect wiring.

## Fail-closed invariants

1. Manifest runtime ID and expected source revision are checked before adapter
   execution.
2. Receipt ID, time bounds, workspace parent, and initial clock value are
   validated before adapter execution.
3. A successful lifecycle contains exactly one first `started` event, exactly
   one final successful `finished` event, contiguous event sequence numbers,
   no parse errors, and process/API success.
4. Tool events are ordered, paired by call ID, name the same tool, and refer to
   a tool declared by the manifest.
5. Observed behavior cannot compensate for a missing manifest capability.
6. Timeout success requires both a raised hard-bound timeout and a dead session.
7. Cancellation success requires a started session and a dead session after
   cancellation.
8. Workspace evidence is evaluated after normal, timeout, and cancellation
   phases so a later phase cannot mutate the canary unnoticed.
9. Cost evidence parses only integer `ResourceUsage` fields.
10. Every evidence locator is recomputed and must address the exact canonical
    bytes supplied to the writer.
11. Receipt status is `passed` only when all eight retained checks pass.

## Test fixture

The fixture starts a real Python subprocess with a sanitized environment and a
strict JSON-lines event stream. It performs an in-workspace write, streams one
delta, emits paired tool events, emits structured output and usage, supports a
hung mode for timeout/cancellation, and can deliberately modify an outside
canary for the negative isolation test.

The fixture is deterministic, local, zero-cost, and performs no network access.
It is evidence for the harness and Python subprocess adapter shape only.

## Acceptance matrix

| Case | Expected result |
| --- | --- |
| correct manifest and subprocess fixture | all eight checks pass |
| repeated fresh runs | identical per-check evidence bytes/digests |
| stale source revision | refusal before adapter start |
| manifest/adapter runtime mismatch | refusal before adapter start |
| observed streaming with `streaming=false` | failed stream check |
| tool not declared or events unpaired | failed tool-events check |
| malformed/duplicate/gapped lifecycle | failed start check |
| hung runtime | bounded timeout kills session |
| started hung runtime | cancellation leaves no live session |
| outside canary mutation | failed workspace-isolation check |
| invalid usage payload | failed cost check |
| evidence writer returns wrong digest | hard refusal, no receipt |
| malformed receipt ID/naive clock/non-finite bound | refusal before adapter start |

## Required adversarial mutations

Before handoff, focused tests must kill at least:

1. ignore stale source revision;
2. accept non-contiguous event sequences;
3. accept duplicate lifecycle events;
4. accept undeclared tool events;
5. treat timeout exception as sufficient while session remains alive;
6. check workspace canary before timeout/cancellation phases;
7. trust the evidence writer's locator without recomputing the digest;
8. derive `passed` from manifest capabilities instead of observed checks.

## Residual Gate-0 work

This packet does not make any existing provider/runtime conformant. Later small
packets must provide manifests and real fixtures for each required production
runtime, route every adapter start and evidence write through central Effect
Leases, add Docker sandbox evidence, and feed missing/failed receipts into the
machine-readable Gate-0 release report.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Promotion: **not requested**
