# G1-GENESIS-REHEARSAL-01 — Genesis end-to-end on the Windows host with the base-interpreter gates

Packet ID: G1-GENESIS-REHEARSAL-01

Artifact role: primary

Classification: `EXPERIMENT`

Active gate: Gate 1

Owner: repository owner

Base revision: b59b2628ad6ed85a8b5e729a12c58512543e2e73

Working-tree context: executed from the isolated worktree branch `loop/stage3-failed-receipt` (commit 8e38333d) with a local clone of the repository at the release commit as authority root

Dependencies: `G1-GENESIS-02_KANBAN_BOARD_BLUEPRINT`, `G1-GENESIS-03_VERIFIED_SOURCE_DOWNLOAD`, `G1-KERNEL-01_STDLIB_INTERPRETER`

Stage: 7 of the owner-directed 2026-09-05 loop; a measurement toward the owner's "builds apps through Genesis" goal, not a code change.

## Primary acceptance claim

On this Windows 11 host, one owner-directed Genesis run (`daedalus genesis "kanban board" --target web`) reaches `preview-ready` through the unchanged production path, with every contained gate passing far inside its ceiling and without the launcher warning line, now that the gates spawn the base interpreter (G1-KERNEL-01). This measures product availability only; it closes no gate and is not a scientific baseline (plan section 11, Gate 1).

## Reproduced negative baseline (measured 2026-09-05, Codex, G1-GENESIS-03)

Codex's fresh browser runs earlier today recorded `test/runtime/package` timeouts at 30.9 to 31.5 s and a runtime exit `3221225786` (`STATUS_CONTROL_C_EXIT`) after `GENESIS_RUNTIME_OK` had already been printed, with `warning: Making stdin inheritable failed` in every gate output; the packet honestly kept the end-to-end matrix at 0/1. Those gates ran the venv launcher stub under containment (an extra process between containment and the interpreter, holding the log handle).

## Experiment record (plan section 15)

- Spec: the existing admitted `kanban-board-v1` blueprint (policy `12.1`), request key `loop-genesis-rehearsal-01`, target `web`, defaults visible in the retained result (one local user, no authentication, WCAG 2.2 AA, local-first storage).
- Budget: the gates' configured ceilings (unchanged); realized wall times below; no model, no vendor, no network egress.
- Evaluator: the kernel-owned checks (build, test, runtime, package, kanban template conformance) plus the round-trip report; nothing model-judged.
- Isolation: authority root = the scratch clone at `b59b2628`; control root = a fresh scratch `DAEDALUS_KILLSWITCH` root; the shared tree, its control root and spine were not touched.
- Expiry: single run, retained result; no re-runs claimed.
- Promotion: publication not requested; owner approval required; automatic promotion false (as recorded in the result).

## Measured result (2026-09-05, 14:56)

| Field | Value |
| --- | --- |
| status | `preview-ready`, run `genesis-c4b987ce12c2530ab365b5d6` |
| candidate source tree | `e3aa5901a6ef3274e3ee709f0a751faf08a5d9f99a90d5f8b24895a619543180` (13 files) |
| round-trip report | `passed`; build, code, containment, data, kanban_template_conformance, knowledge, package, runtime, test, type all true |
| blockers | none |
| publication | not requested; `owner_approval_required` true; `automatic_promotion` false |
| user-profile path in the result | none |

Per-gate observations from the run's evidence store (schema `daedalus-genesis-command-observation/2`, interpreter provenance recorded):

| Gate | passed | wall time | timed out | containment | launcher warning in output |
| --- | --- | --- | --- | --- | --- |
| build | true | 463 ms | false | mic-low+job+bounded-inherit | no |
| test | true | 1173 ms | false | mic-low+job+bounded-inherit | no |
| runtime | true | 1096 ms | false | mic-low+job+bounded-inherit | no |
| package | true | 462 ms | false | mic-low+job+bounded-inherit | no |
| kanban_template_conformance | true | 18 ms | false | in-process kernel-owned inspector | no |

Interpreter provenance on the four contained gates: implementation cpython, version 3.13.14, one binary SHA-256 (`623f669041a9…`), the base interpreter, not the venv stub.

Retained under `docs/evidence/G1-GENESIS-REHEARSAL-01/`: the sanitized CLI result and the per-gate summary.

## Reading

The 16 to 31 s gate times and the runtime timeout of the morning are absent with the base interpreter: every contained gate finishes in about half a second to one second. This is one run on one host; it supports, but does not prove, the reading that the launcher stub (an extra process holding the merged log handle) caused the earlier slowness and the `STATUS_CONTROL_C_EXIT` on timeout. A controlled A/B (same run with `resolve_python_argv` disabled) is the discriminating follow-up if the claim is to be stated as cause.

## A/B against the launcher stub (stage 8, measured 2026-09-05, 15:14)

Same clone, same blueprint, same policy, a fresh control root and request key `loop-genesis-rehearsal-02-stub`; the only change is `daedalus.kernel.interpreter.stdlib_interpreter` patched to return `sys.executable` (the venv launcher stub), i.e. the exact spawn of the morning. Run in-process through `run_genesis` (the CLI door installs only the budget net, which prices no python spawn; the `python.genesis` lease and every kernel boundary are unchanged).

| Gate | A: base interpreter | B: launcher stub | B / A | warning line in B |
| --- | --- | --- | --- | --- |
| build | 463 ms | 1360 ms | 2.9x | yes |
| test | 1173 ms | 2530 ms | 2.2x | yes |
| runtime | 1096 ms | 2995 ms | 2.7x | yes |
| package | 462 ms | 1851 ms | 4.0x | yes |
| kanban_template_conformance (in-process) | 18 ms | 15 ms | 0.8x | no |

Arm B also reaches `preview-ready` (run `genesis-f550afe4b15265cf80f4c5d2`, round-trip passed, no blockers, no timeout, whole run 12.7 s). Interpreter provenance in B names a different binary SHA-256 (the stub) than in A.

Reading, narrowed by the A/B: the stub is a measurable, consistent cost (one extra process per gate, roughly 0.9 to 1.9 s here) and pollutes every gate output with the warning line; on a quiet host it does not by itself produce the 16 to 31 s gates or the runtime timeout of the morning. Those figures therefore need the stub plus host contention (Codex's own note: competing build/package work); the stub alone is not the proven cause of the timeout. What the base interpreter buys is proven: the cost and the pollution go away, and the exact-output contracts (Ariadne) become satisfiable.

## Scope and boundaries

In scope: one measured run and its retained evidence. Out of scope: any code change, browser end-to-end, the source-download flow, publication, and any claim beyond product availability on this host. Gate-3/Gate-5 obligations are untouched.

## Contracts and behavior

No contract changes. The run used `daedalus genesis` (registered CLI door), the `python.genesis` outer lease, the Attempt, source-tree CAS, the kernel-owned checks and the canonical RoundTripReport.

## Acceptance matrix

| Check | Result |
| --- | --- |
| run reaches `preview-ready` with no blockers | yes |
| every contained gate passed inside its ceiling without timeout or cancellation | yes (463, 1173, 1096, 462 ms) |
| A/B with the launcher stub | also preview-ready; 2.2x to 4.0x slower per contained gate, warning line in every contained gate output, no timeout on a quiet host |
| launcher warning line absent from every gate output | yes |
| interpreter provenance recorded, path-free | yes |
| no publication, no promotion | none requested; flags false/required as recorded |

## Migration and rollback

Nothing to roll back; evidence only.

## Evidence, expected failures, and review

Codex review requested as a free room turn. The A/B is retained under `docs/evidence/G1-GENESIS-REHEARSAL-01/ab-stub/`; single run per arm, one host.

Iron Plan: **EXPERIMENT** (measurement of product availability; no code change, no promotion)

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
