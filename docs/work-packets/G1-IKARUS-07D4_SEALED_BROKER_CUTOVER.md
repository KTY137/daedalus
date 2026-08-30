# G1-IKARUS-07D4 — Sealed provider broker cutover

## Frozen packet metadata

- Packet ID: `G1-IKARUS-07D4`
- Active gate: **Gate 1 — Renovation ignition slice**
- Classification: `ALIGNED`
- Owner: repository owner; no automatic merge, promotion, or Gate transition
- Base revision: `98833bf71e53eec184a7db2a065aec1469a9b8c7`
- Master-plan digest: `7cccda0fb75ff60af846b0c7eb697f6f3fd9fdd76ca2f4ae3aa5670ee2f3c704`
- Dependencies: merged 07D1/07D2/07D3 evidence, executable-object registry,
  provider-observation ledger, runtime-bound Effect authorization, #188, #278
- Primary claim: the production broker accepts no caller-supplied callable and
  executes only the fixed registered operation whose authenticated ABI,
  payload, executable bytes, runtime, Effect Lease, and provider identity agree
  before durable start.

## Scope

In scope:

- `daedalus/runtimes/broker.py`;
- the narrow post-start sealed-operation method in
  `daedalus/runtimes/provider_executable_object_registry.py`;
- `daedalus/providers/claude_cli.py` and the compatibility bridge argument
  projection;
- focused D4, broker, recovery, and Claude-provider tests;
- this packet and the unified runtime-admission workflow.

Forbidden:

- no second broker, registry, store, policy engine, Effect ledger, receipt
  identity, recovery authority, promotion path, or provider-specific bypass;
- no callback/default/closure compatibility in the production
  `run_runtime_provider` signature;
- no provider resolution or execution on exact replay;
- no execution without an exact persisted STARTED receipt bound to the same
  runtime authorization, execution request, payload, and pre-admission subject;
- no Master Plan, amendment-chain, evaluator, OwnerApproval, or Gate mutation.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Production signature has no `invoke` or `output_digests` callable | AST/source review | pass |
| 07D3 conjunction runs before grant/start | ordered trace and no-effect refusal tests | pass |
| Provider A authority plus Provider B executable/payload | focused adversarial test | refuse before grant/start/provider call |
| Payload/ABI/source/loaded-object mutation | focused adversarial tests | refuse before grant/start/provider call |
| Fixed registered operation consumes canonical payload | D4 execution test | exactly one call, terminal evidence persisted |
| Output-evidence failure after provider commit | fault test | retained STARTED + reconciliation required |
| Exact replay | replay test | no executable verification, resolution, invocation, or evidence extraction |
| Recovery | existing recovery suite | no callable accepted; retained authenticated evidence only |
| Legacy callback fixtures | source/reachability review | private test-only helper, no production caller/export |
| Platform/interpreter/system evidence | Python 3.10/3.12, Windows/Ubuntu, affected + full suites | required before issue closure/release |

Budgets: zero provider/process/network calls for every refusal; one provider
call for a fresh accepted execution; zero provider calls for replay; focused
local suite under 120 seconds.

## Baseline

At the frozen base, the four 07D2/07D3 focused files pass (`38 passed in
0.80s`, Windows CPython 3.10), but `run_runtime_provider` still accepts two
independently supplied callables and `ClaudeCLIProvider.run` creates two
per-call lambdas. This is retained negative evidence, not a closure claim.

## Local evidence - 2026-08-30

- The exact unified-runtime-admission workflow selection passes on Windows
  CPython 3.10: `207 passed in 15.42s`.
- The focused broker, recovery, observation-authority, and Claude-provider
  selection passes: `84 passed in 7.11s`.
- The changed Python modules compile with `py_compile`; both changed workflow
  files parse as YAML; `git diff --check` reports no whitespace error.
- The broad repository run is not green in the concurrently modified working
  tree. Its last-failed reproduction leaves eight failures in agent-path
  inference, Windows short-path expectations, envelope/entrypoint registries,
  registry confinement, and the unified-profile surface. None names a D4
  implementation or focused-test path.
- Exact-head Python 3.10/3.12 and Windows/Ubuntu hosted evidence plus an
  independent review remain required before closing #188 or #278.

## Rollback and handoff

Revert broker, registry operation, provider projection, tests, workflow, and
this packet together. Preserve the callback-confusion and post-invoke unknown
tests as negative evidence. #188/#278 may be closed only after exact-head
system evidence and independent review; this implementation does not itself
perform a GitHub issue mutation or declare Gate 1 complete.
