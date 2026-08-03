# G0-WP-05 — Runtime manifests and evidence-bound conformance

Status: builder-verified; system CI externally blocked  
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
`RuntimeConformanceReceipt` whose status is derived solely from check evidence.

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
- `tests/runtimes/__init__.py`
- `tests/runtimes/runtime_fixture_worker.py`
- `tests/runtimes/test_conformance.py`
- `tests/runtimes/test_conformance_adversarial.py`
- `tests/runtimes/test_conformance_lifecycle.py`
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

The harness proves that the evidence writer returns the content address of the
exact canonical bytes it was given. Durable read-back from the CAS is a later
integration assertion once G0-WP-04 is green; this packet does not claim storage
durability from a locator alone.

## Fail-closed invariants

1. Manifest runtime ID and expected source revision are checked before adapter
   execution.
2. Receipt ID, finite time bounds, workspace parent, and initial clock value are
   validated before adapter execution.
3. A successful normal lifecycle has the exact event shape
   `started → stream.delta → tool.started → tool.finished → structured-output → usage → finished`,
   contiguous sequence numbers, no parse errors, matching wait/observed exit
   codes, and a session already dead before fallback cleanup.
4. Tool events are ordered, paired by call ID, name the same tool, and refer to
   a tool declared by the manifest.
5. Observed behavior cannot compensate for a missing manifest capability.
6. Timeout success requires both a raised hard-bound timeout and a dead session
   before fallback cleanup.
7. Cancellation waits up to the configured normal-start bound, then requires a
   started and dead session after cancellation.
8. Any session that remains live after adapter completion is force-cancelled;
   an adapter that still reports it live causes a hard harness failure.
9. Workspace evidence is evaluated after normal, timeout, and cancellation
   phases so a later phase cannot mutate the canary unnoticed.
10. Cost evidence parses only integer `ResourceUsage` fields.
11. Frozen contract payloads are thawed through the canonical schema conversion
    before evidence serialization.
12. Every evidence locator is recomputed and must address the exact canonical
    bytes supplied to the writer.
13. Receipt status is `passed` only when all eight retained checks pass.

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
| malformed/duplicate/gapped/unknown lifecycle event | failed start check |
| wait returns success while session remains live | failed start and forced cleanup |
| hung runtime | bounded timeout kills session |
| started hung runtime | cancellation leaves no live session |
| slow but in-bound runtime startup | cancellation uses normal-start bound |
| outside canary mutation in any phase | failed workspace-isolation check |
| invalid usage payload | failed cost check |
| frozen nested structured output | canonical plain-JSON evidence |
| evidence writer returns wrong digest | hard refusal, no receipt |
| malformed receipt ID/naive clock/non-finite bound | refusal before adapter start |

## Independent adversarial review

A separate review perspective found and fixed four material issues:

1. `RuntimeProbeEvent` freezes nested dictionaries into mapping proxies, but the
   initial evidence serializer passed those proxies directly to `json.dumps`.
   A successful structured-output fixture therefore could not produce evidence.
2. Cancellation used a fixed one-second startup wait. A real clean Python
   subprocess required about 1.9 seconds in the available isolated environment,
   making the nominal pass path fail before cancellation was exercised.
3. A broken adapter could return a successful wait code while leaving its
   normal session alive. The initial start check neither rejected nor cleaned
   that state.
4. Contiguous but additional unknown events were not rejected by the lifecycle
   check.

The implementation now canonicalizes frozen observations, uses the configured
normal-start bound, records and compares observed exit/liveness state, forces
cleanup, and requires the exact provider-neutral lifecycle shape.

## Builder verification

A local isolated Python 3.13 contract-compatible harness executed both scripted
adversarial sessions and a real sanitized Python subprocess fixture:

- `12 passed` across the scripted and real-subprocess verification set;
- the positive subprocess fixture passed all eight checks;
- the deliberate outside-canary escape produced a failed isolation receipt;
- every started local subprocess was confirmed dead after the run.

The local mutation campaign used fresh module copies and restored the correct
implementation after every mutant. Nine targeted mutants were killed:

1. ignore stale source revision;
2. accept sorted-but-gapped event sequences;
3. accept duplicate lifecycle boundaries;
4. accept an undeclared tool;
5. count a timeout as safe only after fallback cleanup killed the process;
6. bypass the late workspace-canary comparison;
7. trust a false evidence locator;
8. derive receipt success from claims rather than checks;
9. serialize frozen observations without canonical thawing.

These are focused builder results, not a whole-repository mutation score. The
repository suite, package build, supported Python matrix, and Windows behavior
remain unverified until hosted CI can execute.

## System-CI blocker

GitHub Actions continues to create every matrix job but terminates it before its
first step. The latest runtime run `30790053225` contains ten failed jobs with
`steps=null` and `logs_url=null`; the concurrent pre-existing Iron Plan run
`30790053193` failed in the same pre-step state. This reproduces the external
runner/account condition previously observed by G0-WP-04 and the independent
checkout-export probe.

The packet remains draft and cannot be marked green while this condition
prevents the supported Python/platform matrix, full suite, and wheel smoke from
executing.

## Residual Gate-0 work

This packet does not make any existing provider/runtime conformant. Later small
packets must provide manifests and real fixtures for each required production
runtime, route every adapter start and evidence write through central Effect
Leases, prove durable evidence read-back through the CAS, add Docker sandbox
evidence, and feed missing/failed receipts into the machine-readable Gate-0
release report.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Promotion: **not requested**
