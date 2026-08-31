# G1-HIER-07A - Import SCC ledger-path port

## Frozen packet metadata

- Packet ID: G1-HIER-07A
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 526e867b3a2091826adc915de46e3ab391dc959b
- Dependencies: G1-HIER-01, G1-HIER-03B, G1-HIER-04B, G1-HIER-06E
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The exact 21-module cross-domain SCC at the packet base no longer exists.
`daedalus.kernel.offload_lease` no longer imports
`daedalus.spine.picker`: the kernel consumes an explicit neutral ledger-path
resolver port, while Gate1 composes the unchanged canonical picker resolver at
the existing attempt-lease door. The former component has 19 members after the
cut; both `kernel.offload_lease` and the transitively attached runtime egress
module are outside every non-trivial SCC.

## Scope

- Recompute the tracked-only Python import graph at the exact base revision.
- Inventory all 12 non-trivial SCCs and their syntactic domain crossings.
- Break exactly the selected `kernel.offload_lease -> spine.picker` edge by
  dependency injection; add no allowlist, dynamic import, facade, store, or
  alternate ledger resolver.
- Preserve `spine.picker.resolve_spine_db_path` as the sole canonical resolver
  and preserve its public identity, configuration, confinement, and monkeypatch
  seam.
- Keep SQLite read-only mode, query, timeout, state interpretation, evidence
  strings after path resolution, JSON, digests, persistent paths, effect
  Registry targets/anchors, and provider admission unchanged.
- Do not change the Masterplan, amendments, global packet index, historical
  runs, generated output, or distribution artifacts.

## Contracts and behavior

The census uses only Python files returned by `git ls-files -- daedalus`. An
import target is the longest tracked module prefix resolved from Python AST
`Import` and `ImportFrom` nodes. The syntactic domain is the first component
after `daedalus`; direct root modules are reported as `root`. Dynamic runtime
dispatch is outside this static census and is covered by focused source and
cold/import behavior rather than claimed as statically complete.

Before the cut: 419 modules, 1,574 unique static edges, 12 non-trivial SCCs,
largest size 21. After the cut: 419 modules, 1,574 edges, 12 non-trivial SCCs,
largest size 19. The total edge count is unchanged because the forbidden
kernel edge moves to the existing outer Gate1 composition
`ignition.gate1 -> spine.picker`; no edge is hidden. Only SCC 1 changes.

| # | Size before -> after | Domains before -> after | Members (after; removed members noted) |
|---:|---:|---|---|
| 1 | 21 -> 19 | `root,kairos,kernel,runtimes,spine` -> `root,kairos,kernel,spine` | `build`, `build_exec`, `conversation`, `core`, `doctor`, `file_bridge`, `health`, `ikarus_supervisor`, `kairos.gated_writes`, `kairos.scheduler`, `kernel.attempt_execution`, `kernel.promotion`, `offload`, `progress`, `progress_sources`, `spine.attempt`, `spine.bootstrap`, `spine.picker`, `status`; removed from the SCC: `kernel.offload_lease`, `runtimes.admission.offload_egress` |
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

SCC 1 is the only top-level syntactic domain crossing. Numerically larger
single-edge splits were rejected because they cross preserved production
seams: `doctor -> file_bridge` carries heartbeat monkeypatch/output behavior;
`offload -> doctor` carries default availability probing;
`file_bridge -> core` carries claimed dispatch; and
`kernel.attempt_execution -> offload` carries the exact public
`offload_runner` identity. The selected edge owns only locator discovery. Its
read-only authorization query remains in the kernel and its existing resolver
remains in the spine owner, so the cut is the highest-leverage candidate that
does not migrate an effect target or compatibility object.

When the `spine.intent_ledger` contract is declared but no resolver port is
composed, authorization denies before importing or opening SQLite. Gate1 looks
up `spine_picker.resolve_spine_db_path` at lease-call time, preserving existing
monkeypatches of that exact module attribute. Rows without the intent-ledger
contract do not require the new port.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Base inventory | exact-revision tracked AST census | 419 modules, 1,574 edges, 12 SCCs, largest 21 |
| Selected split | current tracked AST regression | 12 SCCs, largest 19; exact old SCC absent |
| Kernel boundary | graph and source AST | no `kernel.offload_lease -> spine.picker`, no dynamic escape |
| Transitive leverage | non-trivial component membership | kernel lease and runtime egress both acyclic |
| Missing composition | attempt-lease guard test | deny before SQLite access |
| Existing behavior | attempt lease and Gate1 suites | grant/deny/replay and picker monkeypatch remain green |
| Persistent authority | source diff and lease tests | same resolver, read-only query, formats, and paths |
| Effect authority | Registry digest on Python 3.13 and 3.10 | unchanged digest above |
| Live activity | builder tests only | no provider, network, or EDA calls |

## Migration and rollback

No persistent migration exists. The new keyword is additive and the public
attempt-lease signature remains keyword-extensible. Rollback removes the port
argument and restores the direct in-kernel picker import; no SQLite, JSON,
ledger, evidence, Registry, or CAS state is rewritten. Shim retirement is not
applicable because no compatibility facade was added.

## Evidence expected failures and review

At the base revision the focused architecture claim is intentionally red: the
graph contains `kernel.offload_lease -> spine.picker`, the exact 21-member SCC
is present, its largest size is 21, and both the kernel lease module and runtime
egress admission are cyclic. The post-cut contract must instead report the
19-member component above without changing the other 11 SCCs.

No attempt replay, workspace, resolver-monkeypatch, Registry, Python-version,
or packet-schema failure is expected after the patch. Independent review must
confirm the resolver is obtained only by outer composition, exercise the
fail-closed missing-port decision, compare all 12 SCC rows with the tracked
census, and verify the Effect Registry file and digest did not change. Static
AST evidence cannot prove runtime string dispatch or monkeypatch behavior by
itself; the focused behavior tests are therefore required alongside it.

The repository-wide packet-index contract has two inherited failures unrelated
to this packet:
`test_committed_registry_validates_and_matches_the_tracked_index` and
`test_check_is_read_only_and_effect_registry_digest_is_unchanged` both stop at
`G1-HERMES-01_SHARED_LOOPBACK_PREDICATE.md`, which is missing the parsed
sections `contracts_and_behavior`, `evidence_expected_failures_and_review`, and
`scope`. The G1-HIER-07A artifact itself parses as a post-index primary with all
six required sections. Per packet scope, neither the HERMES artifact nor the
global index is changed here.

The broad Python 3.13 kernel/attempt/effect run also retains three unrelated
base failures: `test_one_reexport_loads_only_its_owner_and_keeps_identity`
(the lazy-kernel loaded-module expectation drifts), plus
`test_runtime_authorization_refuses_foreign_terminal_receipt_before_ledger` and
`test_runtime_authorization_delegates_own_terminal_receipt_exactly_once` (their
fixture passes a plain `object` where the base now enforces
`RuntimeTrustLedgerPort`). None of the failing tests or their production owners
is changed by this packet; the same run has 839 passes, 8 skips, and 8 expected
failures in addition to those three inherited failures.
