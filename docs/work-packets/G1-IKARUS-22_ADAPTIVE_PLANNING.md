# G1-IKARUS-22 — Bounded advisory planning and correction

Packet ID: G1-IKARUS-22
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: approved master plan revision 12; G1-IKARUS-COMPUTER-01; G1-WP-IKARUS-COMPUTER-LOOP-01; current path-I/O release fence

Owner direction: continue implementing more autonomy in the 2026-09-05
conversation. This is aligned implementation within the existing policy;
it does not amend the plan or release disabled workspace path operations.
Unrelated user changes remain retained.

## Primary acceptance claim

The existing computer mission loop can retain a typed advisory plan and repair
local malformed proposals within the same admitted call and time budget.
Plans grant no authority. Runtime refusals, unknown effects and failed
postconditions stop the mission without model-directed effect replay.

## Scope

Only the planning portion of `daedalus/orchestration/ikarus/computer_loop.py`
before `is_computer_command`, `tests/test_ikarus_computer_autonomy.py` and this
packet. The parent owns chat commands and the optional native cancellation
probe; the scheduling packet owns durable job changes. No new scheduler,
event store, artifact identity, provider transport, policy, host adapter,
resume path, model-owned configuration or promotion capability is introduced.

## Contracts and behavior

The advisory proposal is exactly `{type: "plan", steps: [short text, ...]}`
with 1–12 nonempty single-line steps of at most 240 characters. Accepted plans
and raw proposals bind the canonical Mission, authority root, CAS and spine;
progress and terminal reports expose their advisory status and provenance.

Each actual planner invocation, including planning and correction, consumes
the same `max_steps` and mission timeout. Tool attempts retain a separate
sequence so an intervening plan never changes the tool idempotency convention.
When the attempts axis is enforced, there are at most two consecutive
correction chances after deterministic JSON, proposal-shape, advertised
argument-shape or unavailable-tool rejection. Owner-disabled attempts remove
that numeric retry cap; three identical invalid responses still establish a
measured lack of correction progress. The short plan shape is a bounded data
format, not a cap on how many mission actions the owner may admit. A
valid proposal clears the bounded, explicitly untrusted correction context.
Secret-floor refusals and every adapter failure remain terminal.

Three consecutive identical read observations stop as `stalled`. A new receipt
or freshness token alone is not progress; changed target/content evidence and
intervening input operations preserve their distinct meaning. This detector
is a deterministic delivery rule, not a claim that useful model reasoning or
the overall task has been verified. Task success remains unverified.

Cancellation is checked before and after each model call, and the owner's
callback is wired into an optional trusted-service checkpoint probe. Owned
services close even when capability or frozen-policy validation fails before
admission. Mission replay requires the exact authority root; historical
unscoped records cannot disclose a prior result through another root.

## Acceptance matrix

| Case | Required evidence |
| --- | --- |
| Plan shape and authority | Exact fields and bounds; extra policy fields refuse |
| Plan persistence | Canonical Mission/authority/CAS/spine binding and progress |
| Shared budget | Plans and correction calls consume the same total caps |
| Repair bounds | Two consecutive chances; valid proposals clear correction data |
| Invalid evidence | Exact response and hash retained; secret content withheld |
| Runtime failures | Denial, unknown effect and failed postcondition never retry |
| No progress | Three identical read results stall despite new receipt tokens |
| Meaningful changes | Different content/target or input resets repetition |
| Cancellation | Before/after model checks and callback cleanup reach the service |
| Early failure | Owned service closes without a mission on invalid capabilities |
| Root scope | Another or historically absent authority cannot replay an ID |
| Release fence | Workspace file/path tools remain unavailable in runtime projection |

## Migration and rollback

This extends existing mission/proposal records without changing the canonical
schema or introducing another state authority. Old terminal records remain
retained; missing-root replay refuses rather than inferring authority. Rollback
removes the additive advisory/correction handling and keeps all evidence.
Interrupted work remains reconciliation-only and is never resumed here.

## Evidence, expected failures and review

Baseline legacy loop suite after implementation: **29 passed in 3.79 seconds**
using the project's `.venv` Python and canonical temporary storage. The new
matrix uses deterministic proposal and host fixtures, never live desktop
input, remote providers or actual workspace path operations. This measures
orchestration behavior, not improved model quality or Hermes parity.

The initial new autonomy and legacy loop matrix completed with **67 passed in
12.20 seconds**. After the execution-limit review, the expanded loop,
scheduling and watcher run completed with **90 passed and 1 failed in 28.29
seconds**. The retained failure was
`test_competing_dispatchers_make_one_committed_claim`: its test-only barrier
expected two concurrent entrants into `_claim`, while the new scheduler
serialized dispatch outside that point, producing `BrokenBarrierError`.
The scheduling packet owns the concurrency-contract correction and its
independent revalidation; this packet did not change that test.

Independent vision reviewer accepted the loop's shared call/time accounting,
local pre-effect correction boundary, secret withholding, native cancellation
probe cleanup, exact root-bound replay and semantic observation signatures.
Review clarified revision 12 section 4.1: the two-correction numeric cap is
conditional on attempts enforcement; owner-disabled retries instead retain
only the separate identical-invalid-output progress criterion. Focused
regressions cover both modes and the unchanged wall-time axis.

Final owned integration command:
`.\.venv\Scripts\python.exe -m pytest -q tests/test_ikarus_computer_autonomy.py tests/test_ikarus_computer_loop.py tests/interfaces/test_computer_watcher.py tests/test_llm_client.py`
completed with **80 passed in 95.55 seconds**. This includes all 42 new autonomy
cases, 29 legacy loop cases, the watcher and LLM-client tests. No live model or
host action was used. The eight earlier packets were not rewritten. Direct
`tools.index_work_packets._artifact(..., set())` validation recognizes this
packet as a new `primary`, `ALIGNED`, Gate-1 artifact with all six contract
sections; no index regeneration or staging was performed.

A final parent review aligned source identity with the existing trusted
adapters: frozen distributions hash `sys.executable`, while source execution
hashes this module. This packaging-only fallback was added after the measured
matrix; no additional broad suite or frozen-distribution claim is inferred.

Expected negative outcomes include exhausted shared budget, malformed proposals,
withheld secrets, scope drift, runtime refusal, stalled observations and
reconciliation-required effects. Existing release-lock evidence is retained.

Final parent integration on 2026-09-05 completed with **355 passed and 34
subtests passed in 490.55 seconds** on the final source, including the frozen
source-identity fallback. This is the joint matrix for packets 21-23, not an
additional count to add to the overlapping measurements above. The matrix
covers planning/loop/history/scheduling, independent authority and cancellation
review, runtime/browser/policy, watcher, conversation/LLM, ledger and two
effect-inventory/conformance checks. All 389 JUnit records have zero failures,
errors or skips: `docs/evidence/ikarus-autonomy-final-regression.xml`.
`docs/evidence/ikarus-autonomy-validation.json` records the command, environment,
source hashes and limits. The source-mode regression does not claim an actual
frozen-distribution run, live-model improvement or Hermes feature parity.
