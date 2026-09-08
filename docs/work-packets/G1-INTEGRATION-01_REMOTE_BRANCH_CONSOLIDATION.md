# G1-INTEGRATION-01 - Remote branch consolidation

Packet ID: `G1-INTEGRATION-01`
Artifact role: `primary`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `1ba5b66f3a95f215f905fe4b46e3db9d3ec26be0`
Dependencies: `Master Plan Revision 13; reviewed tensor packets GPU-48 through GPU-85; current canonical provider and conversation contracts`
Promotion: owner requested integration into main in the 2026-09-08 session

## Primary acceptance claim

Integrate new remote work into the existing kernel and frontend without
reintroducing retired authorities or losing the stronger contracts on main.
The owner's request explicitly authorizes this source integration; it does
not fabricate a Daedalus candidate approval or change a delivery gate.

Initially frozen remote inputs are tensor `97e5e66a` and runtime `1c3c6028`.
The tensor input descends from the base by 94 commits; its experiments and
negative scientific results retain their existing classification. The runtime
input has 268 unique commits and conflicts with the subsequent package
consolidation and durable conversation implementation on main.

The pre-acceptance remote refresh found three further tensor commits through
`d0ede21fa097869b311098e3f9591626f1a524bf` (GPU-86). Two independent
reviewers checked the scalar semantic-count accumulation and retained separate
receipt validation. It adds no authority or performance claim and will be
included in the combined source verification.

## Scope

Allowed: files changed by these remote inputs, their canonical relocated
counterparts in `daedalus/orchestration/`, `daedalus/runtimes/provider/`,
`daedalus/interfaces/`, and `apps/web/src/app/`; related regression tests;
affected CI workflows; this packet, its registry, and integration evidence.
Keep stronger current contracts when remote changes are superseded. Preserve
all experimental failures and document any unintegrated branch scope.

Forbidden: the master plan, amendment chain, AGENTS.md, policy widening,
scheduler activation, candidate promotion, unrelated user changes, and new
event stores, graph authorities, or effectful entrypoints outside the kernel.

## Contracts and behavior

Keep the callback-free provider broker and exact invocation admission on main.
Keep durable conversation and cancellation identities. Consolidate upstream
child-stop evidence and live work/report projections into these contracts.
Preserve current package boundaries and frontend feature availability.

## Acceptance matrix

1. Reproduce the base twin/integration contracts before integration: 376 passed,
   3 skipped with the repository venv; retained raw log and JUnit under
   `runs/integration-20260908/tensor-baseline.*` in the integration worktree.
2. Retain the full unmodified-base suite result separately from post-integration
   tests. No `-x`, silent failure filtering, or green claim for unavailable tests.
3. Run affected twin, provider/runtime, integration, cancellation, conversation,
   project, and HTTP suites, including malformed inputs and refusal ordering.
4. Build the frontend and exercise affected live-state, project-switch,
   cancellation, and evidence-rendering browser flows against the canonical API.
5. Check tracked work-packet registry, whitespace, complete test collection,
   isolated package imports, and the combined regression suite.
6. Independent review examines preserved trust boundaries, conflict resolution,
   cancellation reconciliation, stale evidence, and omitted branch changes.

## Migration and rollback

No live store migration or service activation. Prepare and verify in an isolated
worktree. After checks, advance main only against its freshly checked head and
preserve unrelated WIP. Rollback uses explicit revert commits, never reset or
history rewriting; remote branches and retained failures remain inspectable.

## Evidence expected failures and review

The initial runtime merge preview reports 53 conflicted paths, including old
modules deleted by consolidation. Its obsolete Hermes adapter and old registry
cannot replace the corrected main implementations. Initial upstream desktop
CI fails because its pinned Rust installation omits rustfmt; repair the setup
without weakening the formatting check. Tensor review found no new blocking
defect; a pre-existing undirected cross-plane projection-verifier gap is assigned
to a separate bounded correctness packet.

The full unmodified-base measurement completed with 13,162 passed, 1 failed,
419 skipped, 23 xfailed and 2,237 passing subtests. The failed materialization
lifecycle test encountered a trusted-clock/Event-Store timestamp inversion.
A focused follow-up passed 23 tests and skipped 2; it does not erase the full
baseline failure or establish a repair. Raw JUnit/log bytes are compressed
without alteration in `docs/evidence/G1-INTEGRATION-01/`, with hashes and
commands in `baseline.json`. Timing is diagnostic under concurrent load.

GPU-66 through GPU-72 lack current registry metadata. Added `registry_contract`
projections point into their existing evidence fields, retain the original
payload, and preserve the EXPERIMENT/non-promotion classification. The remote
Hermes packet reused G1-IKARUS-08, already assigned to portable CLI discovery.
Its exact bytes are archived at
`docs/research/hermes-kernel-adapter-remote-work-packet-20260831.md`; current
adapter claims are judged by main's corrected implementations and tests.

The initial transport review found that a late HTTP error response could outlive
cancellation and that normal error responses were not explicitly closed. The
builder corrected the worker's stop check, bounded error reads and explicit
response disposal. The final transport suite passed 101 tests, including late
error disposal, bounded bodies, real stalled connections and no automatic replay.
The reviewer rechecked the corrected source and regression cases. Local
cancellation and observed child exit do not attest remote generation or billing.

The affected backend suite passed 1,742 tests, skipped 104 and retained 14
expected failures. A final import/whitespace cleanup passed 115 focused tests.
The imported historical Hermes Markdown keeps three intentional hard line
breaks (two trailing spaces) to preserve its exact original blob; these are
reviewed exceptions to Git whitespace diagnostics, not source-code defects.
The remote failed patch traceback is retained in the integration evidence
directory instead of being left as a GitHub configuration file.

Frontend baseline: 536 app tests and build passed. Integrated: 549 app tests,
build and 51 browser cases passed. The browser cases use the built preview
with mocked canonical HTTP contracts; full owned-server acceptance is separate.
Independent review rejected contradictory child-stop receipts. A corrected DOM
selector also exposed executable action offers after interrupted generation;
canonical `settleTurn` now keeps partial text and refuses the offer. The initial
49-pass/2-fail browser run and final green run are retained. Generated Three.js
shader whitespace is left exactly as emitted by the reproducible Vite build.

The MAP selective port and independent review correction are included. The
final 311-test mapping run passes, and the independent reviewer passes 130
focused cases. Stale supplied scope refuses before ranking; portable consumed
scope remains in drift/inventory evidence and the existing snapshot acceptance
path. The deliberate two-case mutation failure and corrected run are retained.

The unchanged-main real-server GUI baseline ran 225 cases: 223 passed and two
failed. Both are stale test contracts: substring Dusk also matched Spatial Dusk,
and the resume fixture lacked the canonical project-binding receipt. The tests
now require exact theme names and carry authentic bound fixture shape. Queue
assertions retain their numeric/project-switch negatives with the new displayed
label. No retries, sleeps or skips hide these failures. Full integrated real-API
GUI and whole Python acceptance are pending separately from the focused passes.

Scientific Gate-2/3 evidence is not supplied by this integration. No gate
closure, full security boundary, or performance superiority is claimed.
