# Work Packet: G1-HIER-04B Offload-lease outer ports

Packet ID: `G1-HIER-04B`
Artifact role: primary
Status: builder complete; independent review pending
Classification: `ALIGNED`
Active gate: 1
Owner: kernel/runtime/orchestration/chip-design maintainers
Base revision: `e9cf58a9e97db93d8f2627b52a59e2d58808db4b`
Dependencies: G1-HIER-01 import-boundary contract; G1-HIER-04 repository-head verifier port; G1-HIER-05 neutral receipt contracts
Master-plan authority: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` Revision 11
Master-plan SHA-256: `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`

## Primary acceptance claim

`daedalus.kernel.offload_lease` remains the single Effect-Lease issuer and
authorization owner while importing no chip-design, orchestration/Kairos,
provider, runtime, evaluator, or Gate implementation. Worktree topology,
provider endpoint/egress admission, and chip execution-plan/publication
verification enter the issuer only through explicit neutral ports composed by
their existing outer owners. No port may mint a lease, alter a registry row,
or broaden provider admission.

## Scope

Allowed:

- neutral port contracts and validation in `daedalus/kernel/offload_lease.py`;
- one deterministic worktree-topology adapter under `daedalus/orchestration`;
- one provider endpoint/egress adapter under `daedalus/runtimes/admission`;
- chip execution-plan and publication verification under
  `daedalus/chip_design`;
- existing production composition callers, focused tests, import-boundary
  debt reduction, and this packet.

Forbidden:

- Effect Registry IDs, targets, effects, wiring, anchors, or digest changes;
- lease/request/policy JSON, SQLite schema, record schema, CAS locator,
  evidence path, digest, lock, replay, or spend semantics changes;
- a second lease, event, artifact, policy, evaluator, publication, or
  promotion authority; ambient service locators, dynamic imports, global port
  registration, singleton state, or wider provider admission;
- Master Plan, amendment chain, historical `runs/`, live providers, network,
  EDA execution, merge, push, promotion, or generated distribution edits.

## Contracts and behavior

The kernel owns typed, side-effect-free observations for the facts needed by
authorization. An orchestration-owned workspace port resolves the same planned
root and applies the existing bidirectional overlap predicate. A runtime-owned
egress port resolves the existing lane endpoints and runs the existing Ollama
admission function before returning the same `GuardDecision` evidence. A
chip-owned plan validator preserves the exact `EdaExecutionPlan` type check,
and the chip publication verifier retains the existing canonical graph checks.

Ports are explicit call arguments. Missing, malformed, differently bound, or
contradictory observations fail closed before lease issuance or publication.
The kernel never discovers an outer implementation through imports,
environment-selected module names, entry points, registries, or mutable global
bindings. Existing production composition roots inject the concrete adapters.

The ten measured forbidden edges at the base are seven chip-design imports,
one `daedalus.kairos.worktree` import, and two
`daedalus.providers.ollama` imports, all in
`daedalus/kernel/offload_lease.py`. This packet removes those edges rather than
relocating them to another kernel module. The five pre-existing Spine edges
outside this packet remain visible architecture debt.

## Acceptance matrix

| Case | Evidence | Required result |
| --- | --- | --- |
| Kernel import direction | tracked AST boundary scan | no kernel import of chip design, Kairos, providers, runtimes, gates, or eval; no new edge |
| Cold kernel import | isolated interpreter | no chip-design, Kairos, provider, or runtime implementation loaded |
| Workspace composition | unit and caller tests | identical roots, allow/refusal and evidence; missing or forged binding refuses before issuer |
| Egress composition | unit and caller tests | identical ordered endpoints and guard evidence; unknown or rejected Ollama endpoint remains denied |
| Chip plan | exact-type and binding tests | only the existing `EdaExecutionPlan` validates; source root, cwd, and digest bindings remain exact |
| Chip publication | create/replay/fault tests | byte-identical record/index, CAS graph, replay and terminal authorization; no second execution |
| Lease contracts | golden and consumer suites | identical request, policy, lease, receipt JSON and digests for fixed inputs |
| Effect Registry | source hash, targets, anchors and digest | byte-identical source and digest `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec` |
| Wheel | isolated build/install/import smoke | packaged outer adapters import outside the checkout; kernel cold import remains outer-free |
| Negative execution | test instrumentation | no live provider, network, EDA, promotion, merge, or second-spend call |

## Migration and rollback

Production callers move first to explicit adapters while the kernel keeps the
same lease and authorization objects. Compatibility names that cannot remain
object-identical without reversing the dependency are retained only as
fail-closed port facades and entered in the shim registry with source,
runtime-string, wheel, documentation, Effect Registry and pickle retirement
criteria. No persistent data migration exists.

Rollback restores each caller to the previous kernel implementation and
removes the new adapters as one commit. Because registry, wire, ledger, CAS and
evidence formats are frozen, rollback performs no data rewrite and does not
move historical evidence.

## Evidence expected failures and review

Builder evidence must include the pre/post tracked import report, focused and
broad consumer suites, fixed-input golden JSON/digests, crash/replay and
publication recovery, registry source hash/digest, `uv build`, installation of
the wheel outside the checkout, and clean-worktree status. The exact commands,
counts, hashes and any inherited failures are appended after execution.

Expected static-analysis limitations are explicit: the deterministic ontology
preflight observes direct syntax only. Python adapter coverage is partial;
dynamic imports, descriptor dispatch, generated code, monkey-patching,
runtime imports and runtime dispatch remain unknown and require executable
tests. Static proximity does not establish execution or causation. No ontology
workspace or snapshot is created in this packet.

Independent review must check that no injected port can select a registry row,
issuer secret, lease scope, spend, writable root, authority root, or promotion
target; every outer result is bound to the kernel request before the first
write; provider denial is not weakened; and compatibility does not introduce
ambient mutable state.

### Builder evidence (2026-08-31)

The final tracked-source measurement is green for this packet:

- `daedalus/kernel/offload_lease.py` has zero direct imports of chip design,
  Kairos, providers, runtimes, gates, or evaluators, and its AST contains no
  dynamic-import call. A cold source import and a cold installed-wheel import
  both reported `COLD_OUTER=[]` for those outer implementation packages.
- The pre-packet source at `e9cf58a9` measured 15 current forbidden edges:
  ten in `kernel/offload_lease.py` plus five pre-existing Spine edges. The
  checked-in locator contract still carried 23 stale exact-line entries, so
  that base report was honestly red (`current=15`, `allowlisted=5`, `new=10`,
  `resolved=18`, `shims=9`). The final exact contract contains the five
  remaining Spine edges and reports `tracked=395`, `current=5`,
  `allowlisted=5`, `new=0`, `resolved=0`, `shims=10`, `passed=true`.
- The Effect Registry source is unchanged: Git blob
  `65b7c8891b5fab22f5e1bbb993e36e3b63292db0`, source SHA-256
  `fb060b3e32949a1911e920ae91aa0c883410ca5a36074db9c338f5a64de7f165`,
  and registry digest
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`.
- Final executable suites: chip publication/execution/CLI/lease
  `260 passed, 3 skipped`; lease/evidence callers `144 passed`;
  orchestration/bootstrap/restart/replay `189 passed, 4 subtests passed`;
  focused ports, repository inventory, and architecture `20 passed`.
  `compileall` passed. No live provider, network, EDA, merge, promotion, or
  second-spend call ran.
- `uv build` produced `dist/daedalus-0.1.3.tar.gz` and
  `dist/daedalus-0.1.3-py3-none-any.whl`. Installing the wheel outside the
  checkout and importing every new adapter passed; the imported kernel path
  was below the isolated target and its registry digest matched exactly. The
  build-instance SHA-256 values are
  `a16e6dcc8cf07bb5fde76c2246815c7522bc663f6d79694a38a94e86c1e7b20e`
  (sdist) and
  `31149eb1f01cef81d67a67ac332bfe13946ad204cd169990d5b593278efbbcf5`
  (wheel); these generated artifacts are evidence, not committed source.
- The two new evaluator-bundle dependencies have explicit `-text` declarations
  in `.gitattributes`. The inherited bundle debt improved from 20 missing
  declarations at the base to 18; this packet does not rewrite the remaining
  predecessor files.
- The Work Packet itself passes the post-index metadata parser (canonical ID,
  primary role, Gate 1, ALIGNED, owner, full base revision, dependencies, and
  all six required sections). The global index was deliberately not regenerated
  in this isolated packet.

The deterministic ontology preflight was read-only and created neither a
workspace nor a snapshot. It covered direct Python syntax only; runtime import
and dispatch, descriptors, generated code, monkey-patching, and metaprogramming
remain executable-test obligations. Static proximity is not execution or
causation. No RDF was persisted; if later required, Turtle is the portable
export with the store-extension mapping retained separately.

### Inherited and order-dependent full-suite failures

The compact final full suite completed with `10209 passed, 310 skipped,
9 xfailed, 2189 subtests passed, 23 failed, 14 warnings` in `2471.37s`.
A clean clone of the exact base revision reproduced 22 of those names in the
targeted comparison (`22 failed, 1 passed`); the remaining cancellation test
fails only in full-suite ordering and passed immediately in isolation. None of
the 23 failures names a changed HIER-04B implementation or focused test:

- Forest-v2 pins:
  `test_kernel_row_is_the_retracted_headline_restated` reports
  `assert 5606 == 5285` after the packet (the exact base reports
  `assert 5588 == 5285`); `test_the_corpus_set_actually_spans_annotation_postures`
  reports `assert 3 >= 4`; and the BM25 pin ranks `index_work_packets.py`
  before the expected `docs_reference_check.py`.
- Work-Packet index pins:
  `test_committed_registry_validates_and_matches_the_tracked_index` and
  `test_check_is_read_only_and_effect_registry_digest_is_unchanged` both stop
  at the predecessor artifact
  `docs/work-packets/G1-HIER-01_ARCHITECTURE_LOCATOR_CONTRACT.md`, which lacks
  its canonical explicit post-index ID. No global index write was attempted.
- Runtime/desktop/interface pins:
  `test_runtime_authorization_refuses_foreign_terminal_receipt_before_ledger`,
  `test_runtime_authorization_delegates_own_terminal_receipt_exactly_once`,
  `VsCodeExtensionTests::test_extension_dashboard_supports_team_and_environment_controls`,
  `test_desktop_backend_readiness_is_child_nonce_bound`, and the full-order-only
  `test_cancel_is_requested_then_confirmed_only_after_worker_stops`.
- Existing inventory/reference pins:
  `InventedImports::test_no_false_positives_across_the_real_tree`, all three
  `test_docs_reference_check.py` failures, the Hermes-owned
  `test_no_caller_keeps_its_own_copy_of_the_host_predicate`, both ignition
  `.gitattributes` closure tests, and
  `test_no_workflow_names_a_script_that_is_gone`.
- Existing compatibility/runtime pins:
  both `test_ikarus_llm_voice.py` failures (the old monkeypatch functions do
  not accept `additional_context`),
  `test_no_declared_effect_is_painted_on`,
  `test_factory_is_only_an_opening_profile_not_a_second_ledger_authority`,
  and `PersistentCacheTest::test_corrupt_cache_degrades_to_recompute` (Windows
  holds the temporary SQLite file open during cleanup).

The clean-base comparison is retained as negative evidence rather than
misreported as a green repository. Independent review and integration remain
pending; this builder result grants no merge or promotion authority.
