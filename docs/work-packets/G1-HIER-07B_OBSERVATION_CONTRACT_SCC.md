# G1-HIER-07B - Observation contract SCC cut

## Frozen packet metadata

- Packet ID: G1-HIER-07B
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: bce1066e7cd8c5c400ece963425bffdf47606a75
- Dependencies: G1-HIER-01, G1-HIER-06E, G1-HIER-07A
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The exact 19-module cross-domain SCC at the packet base no longer exists.
`daedalus.conversation` no longer imports the diagnostic implementation
`daedalus.health`; both stable public modules reexport the same five status
objects and the same closed tuple from
`daedalus.kernel.contracts.observations`. Conversation leaves every
non-trivial SCC, while persisted status values, validation, health rendering,
Registry targets, and HIER-07A behavior remain unchanged.

## Scope

- Recompute the tracked-only Python import graph from the exact packet base.
- Break exactly `conversation -> health` by extracting only their already
  shared immutable observation vocabulary to a neutral kernel contract.
- Preserve the public names `health.STATES`, `conversation.OUTCOME_STATES`,
  `WORKING`, `PRESENT`, `DEGRADED`, `ABSENT`, and `UNKNOWN` as exact shared
  objects with byte-identical string values and tuple order.
- Preserve Conversation SQLite/event payloads, validation errors and replay;
  health probe/render behavior; the HIER-07A ledger-path port and monkeypatch
  seam; admission; and all Registry targets, effects, wiring, anchors, and
  digest.
- Add no compatibility module, runtime registry, singleton, dynamic import,
  persistent migration, provider authority, or allowlist.
- Do not change the Masterplan, amendments, global packet index, architecture
  boundary contract, shim registry, historical runs, generated output, or
  distribution artifacts.

## Contracts and behavior

The census is the same deterministic tracked-only AST algorithm as HIER-07A:
Python paths come from `git ls-files -- daedalus`; import targets resolve to
the longest tracked module prefix. Direct root modules form the syntactic
domain `root`. The result is static evidence, not a runtime trace; dynamic
imports, runtime dispatch and monkeypatch behavior require separate tests.

Before the cut: 419 modules, 1,574 unique static edges, 12 non-trivial SCCs,
largest size 19. After the cut: 420 modules, 1,575 edges, 12 non-trivial SCCs,
largest size 18. One neutral leaf module is added. The old
`conversation -> health` edge becomes `conversation -> observations`, and
`health -> observations` records the same shared authority explicitly; the
one-edge increase is visible and introduces no return path. Only SCC 1 changes.

| # | Size before -> after | Domains | Remaining members after the cut |
|---:|---:|---|---|
| 1 | 19 -> 18 | `root,kairos,kernel,spine` | `build`, `build_exec`, `core`, `doctor`, `file_bridge`, `health`, `ikarus_supervisor`, `kairos.gated_writes`, `kairos.scheduler`, `kernel.attempt_execution`, `kernel.promotion`, `offload`, `progress`, `progress_sources`, `spine.attempt`, `spine.bootstrap`, `spine.picker`, `status`; removed from the SCC: `conversation` |
| 2 | 14 -> 14 | `runtimes` | `provider_executable_pre_admission`, `provider_executable_structure`, `provider_executable_targets`, `provider_invocation_abi`, `provider_invocation_authority`, `provider_invocation_identity`, `provider_invocation_resolution`, `provider_observation`, `provider_target_receipt_ledger`, `provider_target_receipt_retention_admission`, `provider_target_receipt_retention_completed_evidence`, `provider_target_receipt_retention_effect_terminal_evidence`, `provider_target_receipt_retention_recovery`, `provider_target_verification` |
| 3 | 7 -> 7 | `gates` | `repository_write_classification`, `repository_write_effect_lease`, `repository_write_evidence_materialization`, `repository_write_evidence_origin`, `repository_write_guard_structure`, `repository_write_runtime_conformance`, `repository_write_source_anchor_semantics` |
| 4 | 6 -> 6 | `structcore` | package root, `cache`, `cycles`, `index`, `perfile`, `slice` |
| 5 | 4 -> 4 | `eval` | package root, `harness`, `report`, `tier2` |
| 6 | 3 -> 3 | `mapping` | `drift`, `inventory`, `render` |
| 7 | 2 -> 2 | `runtimes` | `live_fault_collector`, `live_probe_drivers` |
| 8 | 2 -> 2 | `tools` | package root, `inventory` |
| 9 | 2 -> 2 | `wiki` | `qml_index`, `verify` |
| 10 | 1 -> 1 | `eval` | self-loop `graph_delta` |
| 11 | 1 -> 1 | `gates` | package-root self-loop |
| 12 | 1 -> 1 | `interfaces` | `bridge` package self-loop |

SCC 1 remains the sole top-level syntactic domain crossing. More numerically
powerful cuts were rejected because they cross production or compatibility
seams: `doctor -> file_bridge` carries heartbeat output and monkeypatches;
`offload -> doctor` owns default availability probing; `file_bridge -> core`
is claimed effect dispatch; `kernel.attempt_execution -> offload` carries the
exact public runner seam; `core -> build_exec` is the live orchestration
composition; `spine.attempt -> kernel.attempt_execution` is the object-identical
legacy facade; and `build_exec -> progress` records the live attempt lifecycle.
The selected edge carries only immutable status values and therefore provides
the next measurable reduction without changing execution or effect ownership.

The canonical contract defines each value once. `health.STATES` and
`conversation.OUTCOME_STATES` are the identical contract tuple; all five
module-level constants are likewise identical across both old paths and the
new owner. The existing lazy `kernel.contracts` package exposes the additive
`observations` domain module without eagerly loading it. Conversation
validation still persists only the strings
`working`, `present`, `degraded`, `absent`, and `unknown` in the same order and
with the same error text. No class or callable changes its module or pickle
locator.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Base inventory | exact-base tracked AST census | 419 modules, 1,574 edges, 12 SCCs, largest 19 |
| Selected split | current tracked AST regression | 420 modules, 1,575 edges, 12 SCCs, largest 18 |
| Removed edge | source/graph contract | no `conversation -> health`; conversation acyclic |
| One authority | AST definition and exact-object tests | values defined once; all old paths identical |
| Persistent behavior | conversation replay and bridge suites | same SQLite/event payloads and validation |
| Diagnostic behavior | health surface suite | same states, probes, coercion and rendering |
| HIER-07A preservation | prior architecture and attempt-lease tests | kernel lease/runtime egress remain acyclic; port seam green |
| Architecture contract | Python 3.13 and 3.10 report | current/allowlisted/new/resolved all zero; 14 shims |
| Effect authority | Registry target/anchor/digest checks | `cli.health` unchanged; digest above |
| Live activity | builder tests only | no provider, network, EDA or paid call |

## Migration and rollback

No persistent migration exists because every stored and serialized value is
unchanged. Rollback redefines the five strings and tuple in `health.py` and
restores Conversation's direct health import; it does not rewrite Conversation
SQLite, event payloads, Registry rows, evidence, CAS, or runtime state. No shim
retirement entry is created: neither stable module becomes a compatibility-only
facade, and the neutral value owner has no legacy implementation path to retire.

## Evidence expected failures and review

At the base revision the new architecture assertion is intentionally red:
`conversation -> health` exists, Conversation belongs to the exact 19-member
component, the graph has 419 modules/1,574 edges, and largest SCC size is 19.
After the cut the exact old component must be absent, Conversation must be
acyclic, and the other 11 SCCs must remain byte-for-byte the membership listed
above.

The repository-wide packet-index contract retains two inherited failures:
`test_committed_registry_validates_and_matches_the_tracked_index` and
`test_check_is_read_only_and_effect_registry_digest_is_unchanged` both stop at
`G1-HERMES-01_SHARED_LOOPBACK_PREDICATE.md`, whose parsed artifact lacks
`contracts_and_behavior`, `evidence_expected_failures_and_review`, and `scope`.
This G1-HIER-07B artifact is validated independently as one complete post-index
primary; the HERMES artifact and global index remain out of scope.

The focused lazy-kernel suite retains the byte-identical base failure
`test_one_reexport_loads_only_its_owner_and_keeps_identity`: its expected module
list omits the already-loaded `kernel.policy.ledger` and
`kernel.policy.pricing` modules. G1-HIER-07B does not change the failing test or
those policy owners. The broad Python 3.13 run also retains
`test_runtime_authorization_refuses_foreign_terminal_receipt_before_ledger` and
`test_runtime_authorization_delegates_own_terminal_receipt_exactly_once`; both
fixtures pass a plain `object` where the base enforces
`RuntimeTrustLedgerPort`. The run has 982 passes, 8 skips, 8 expected failures,
and 2 passing subtests alongside these three inherited failures. A narrower
lazy-facade/hierarchy run has 136 passes on each supported Python version.

No observation-identity, Conversation replay, health behavior, HIER-07A,
architecture, Registry, or supported-Python failure is expected. Independent
review must compare all 12 component memberships, prove definitions occur only
in the neutral contract, inspect public identity and persisted values, and
confirm protected files and effect targets did not change. The ontology
preflight is deterministic and read-only; its Python adapter is partial and
marks dynamic imports, runtime dispatch, generated code, descriptor dispatch,
monkeypatching, and runtime metaprogramming as unsupported/runtime-unknown.
