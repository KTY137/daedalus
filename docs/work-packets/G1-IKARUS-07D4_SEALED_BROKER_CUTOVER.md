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

## Sealed dependency authority

07D4 now binds an explicit dependency-manifest digest through the existing
authority chain rather than reinterpreting the provider target descriptor. The
executable-object admission records the digest; the provider invocation ABI
signs it; and the 07D3 runtime binding requires exact ABI/admission agreement
before Effect grant or start.

The registry admits only the fixed local imports used by the Claude operation
(`hashlib.sha256`, `json.dumps`/`loads`/`JSONDecodeError`, and
`subprocess.run`). It constructs private module views and detached function
objects with copied builtins. The production `subprocess.run` member is not
executed and no `Popen` object remains reachable from the sealed operation.
Instead, admission privately binds the exact native process leaf: retained
`_winapi.CreateProcess` plus an exact inherited-handle list on Windows, and
retained `_posixsubprocess.fork_exec` with no Python child work before exec on
POSIX. Both runners preserve exact argv/cwd/no-shell, UTF-8 replacement,
return-code, timeout, error-channel, and cleanup semantics needed by the
Claude adapter. There is no hidden output-size cap.

JSON decoding uses a detached pure-Python scanner and scanstring, frozen
decoder constants, cloned encoder/decoder classes, cloned default instances,
and the cloned `JSONDecodeError`; malformed JSON therefore raises the same
exception class exposed by the private sealed module view. Direct member,
class-method, default-instance, importer, verifier-builtin, and `sys.modules`
substitution after admission refuses before a fresh Effect. The native
process and detached JSON leaves remain unchanged by those ambient mutations.

This is a narrow in-process dependency seal, not a claim that Python process
memory is tamper-proof against arbitrary native memory mutation or hostile
mutation of private registry internals. The release boundary still depends on
normal process integrity and the independent Windows/Ubuntu system evidence in
the acceptance matrix. This is not a general process-memory security boundary.
Only CPython 3.10 and 3.12 carry closure evidence here. Known 3.10-3.13
`fork_exec` ABIs are explicitly mapped; an unknown future ABI refuses during
admission rather than falling through to a guessed call shape, and requires a
separate review/evidence update.

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

- The complete focused 07D4 selection passes on Windows CPython 3.10:
  `157 passed, 8 skipped in 5.87s`. This includes ABI/executable/runtime
  binding, registry, ordered observation authority, broker, replay, recovery,
  terminal fence, Claude-provider, adversarial dependency, native-runner, and
  wheel-reachability regressions.
- The identical selection passes on Windows CPython 3.12:
  `157 passed, 8 skipped in 7.65s`.
- The native runner plus registry/wheel reachability selection passes on Linux
  CPython 3.10 and 3.12: `30 passed, 4 skipped` on each interpreter. The
  native-runner subset is `11 passed, 4 skipped` on each and covers exact
  argv/cwd/no-shell, UTF-8 replacement, return code, timeout/reap, continuous
  output, a reaped child with grandchild-held pipes, child exec/chdir errors,
  cwd-relative PATH, and injected select/read/wait cleanup faults.
- A fresh wheel built from the working tree contains 344 entries and no
  `tests/` tree. Fresh isolated CPython 3.10 and 3.12 environments both install
  and import it, and confirm that the broker exposes no callback test helper,
  `tests` is unreachable, and the native-leaf factory is not module reachable.
- The changed registry and focused test modules compile with `py_compile`; the
  independent final code review is green for the bounded 3.10/3.12 claim.
- The independent bounded-claim code review is complete. Exact-head Python
  3.10/3.12 Windows/Ubuntu hosted evidence remains required before closing
  #188 or #278.

## Rollback and handoff

Revert broker, registry operation, provider projection, tests, workflow, and
this packet together. Preserve the callback-confusion and post-invoke unknown
tests as negative evidence. #188/#278 may be closed only after exact-head
system evidence and independent review; this implementation does not itself
perform a GitHub issue mutation or declare Gate 1 complete.
