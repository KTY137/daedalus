# G1-HIER-11 — The twin layer names the contract owner, closing the kernel's transitive facade leak

## Frozen packet metadata

- Packet ID: G1-HIER-11
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 515b5fce9a5a4392c6d7f6887fe4049f72f9cd53
- Dependencies: G1-HIER-01, G1-HIER-10
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

Importing `daedalus.kernel.fourfold_evidence` into a cold interpreter loads no
module under `daedalus.{chip_design,eval,gates,kairos,orchestration,providers,runtimes}`
and does not load `daedalus.schemas` at all, because the four `daedalus.twin`
modules that reached their canonical contracts through the legacy facade now
name `daedalus.kernel.contracts.base` — with all fifteen moved bindings proven
to be the same objects the facade exposes.

MEASURED at the base revision, and again after the change, with an explicit
`sys.path.insert(0, <worktree>)`:

| | `daedalus.runtimes` | `daedalus.orchestration` | `daedalus.schemas` |
| --- | --- | --- | --- |
| before | 11 | 2 | loaded |
| after | 0 | 0 | not loaded |

The regression instrument is
`tests/kernel/test_fourfold_evidence_outer_ports.py`, and the durable guard is
the new `twin-no-outer-layers` rule in
`docs/architecture/import-boundaries.json`.

This claim is about **one entrypoint plus one static rule**, exactly as
G1-HIER-10's was. The cold-import test proves the entrypoint; the rule proves
every tracked `daedalus.twin` file, because it reads direct import syntax in
all of them. Neither instrument makes a repository-wide transitive claim, and
this packet does not make one either — `daedalus.spine.receipts` still reaches
the same facade and is recorded as an open item below rather than papered over.

### Why this leak was invisible

`kernel-no-outer-layers` reads direct import syntax. The edge it needed to see
was `daedalus.kernel.fourfold_evidence` → `daedalus.twin.contracts` →
`daedalus.schemas` → `daedalus.orchestration.legacy_reports` and
`daedalus.runtimes.contracts.provider_report`. The first hop is a permitted
edge, so the rule saw nothing wrong and the remaining hops were not its
business. G1-HIER-10 flagged this and deliberately left it open.

## Scope

In scope — repointed imports only, no behavior change:

- `daedalus/twin/contracts.py` (9 symbols)
- `daedalus/twin/legacy_forest.py` (1 symbol)
- `daedalus/twin/reference_compiler.py` (4 symbols)
- `daedalus/twin/_reference_claims.py` (1 symbol)

In scope — contract, instrument, and census artifacts:

- `docs/architecture/import-boundaries.json` (one new rule; one rationale
  amended to record why `daedalus.twin` must **not** join the kernel rule)
- `tests/kernel/test_fourfold_evidence_outer_ports.py` (new, 5 tests)
- `tests/contracts/test_import_scc_hierarchy.py` (census comment only; both
  totals re-measured and both unchanged)
- `tests/contracts/test_work_packet_index.py` and
  `docs/work-packets/index.json` (this document's registry entry)

Forbidden paths — untouched, and verified untouched in the final diff:

- `daedalus/schemas.py`. The facade keeps existing and keeps re-exporting. It
  is not deleted, not narrowed, and deliberately **not** made lazy.
- Every consumer of `daedalus.schemas` outside `daedalus/twin/`. 69 tracked
  modules still import it and all 69 are out of scope here.
- `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, its amendment chain, `AGENTS.md`, and
  the guard modules under `daedalus/spine/`.
- `tests/test_registry_new_doors.py`, `tests/test_registry_retired_rows.py` —
  another packet's open CRITICAL, red on purpose in the `g1` profile.

## Contracts and behavior

### The repoint

All nine symbols — `CanonicalContract`, `ContractProvenance`, `_identifier`,
`_non_empty`, `_record_payload`, `_require_provenance_inputs`, `_revision`,
`_sha256`, `_sorted_strings` — have one owner, `daedalus.kernel.contracts.base`,
which is the domain locator G1-HIER-10 chose over `canonical`, the package's own
"transitional implementation nucleus". No module was added and none deleted.

Object identity is what makes a repoint safe, and it is asserted rather than
assumed. Over the **full** moved set, not a sample: 15 bindings across 9
distinct names, each identical to the object on the facade, on the new owner,
and in the nucleus. Additionally all 15 non-dunder module-level bindings shared
between any `daedalus.twin` module and the facade are the same objects.

The diff is provably nothing but the import target. MEASURED by parsing the
pre-change and post-change source of **all eight** twin modules and rewriting
only the `ImportFrom` module name on the facade nodes: `ast.dump` is then equal
for 8 of 8 files, 0 differing.

### The rule, and the move that does not work

The briefing's suggested guard was to add `daedalus.twin` to
`kernel-no-outer-layers` once twin was clean. **That move is not available and
this packet measured why.** `daedalus/kernel/fourfold_evidence.py:41` imports
`daedalus.twin.contracts` deliberately — projecting a `FourfoldSnapshot` into
the `EvidencePacket` chain is the module's entire reason to exist. With the
prefix added, `scan_repository` returns exactly one violation:

```text
kernel-no-outer-layers  daedalus.kernel.fourfold_evidence  line 41  daedalus.twin.contracts
```

`baseline` is `[]`, so there is no allowlist to absorb it. The rule would go
red on the one edge this packet exists to protect.

The correct owner of a transitive leak through a permitted edge is the rule for
the **intermediate** layer. Hence `twin-no-outer-layers`:

```text
source_prefixes:            ["daedalus.twin"]
forbidden_target_prefixes:  daedalus.{chip_design,eval,gates,kairos,
                            orchestration,providers,runtimes,schemas}
```

The forbidden set is **exactly** `kernel-no-outer-layers`', and that equality is
the argument, not a coincidence: the kernel imports twin, so everything twin can
reach the kernel reaches. A narrower twin set would let the kernel rule pass in
syntax while the layer it names loads in every kernel process regardless — which
is precisely the state this packet found. `test_twin_boundary_rule_is_registered_and_at_least_as_strict_as_the_kernel`
asserts the subset relation so the two cannot drift apart silently.

### What was deliberately not done

No module was made lazy and no module was swapped in `sys.modules`. Both
constructs turn a cold-import test green while leaving the dependency in place
until first attribute access, and both are what blinded the Effect Registry's
derivation on this branch. `test_twin_layer_has_no_lazy_or_sys_modules_escape`
now refuses them mechanically across the layer: module `__getattr__`,
`importlib`, `__import__`, `sys.modules`, and function-scope imports. The two
extractor adapters are excluded by name — they probe for an optional
third-party parser, which is a capability question, not a layering one.

## Acceptance matrix

Interpreter for every row: `.venv/Scripts/python.exe -m pytest`. Exit codes
read directly, never through a pipe.

| # | Check | Command | Result |
| --- | --- | --- | --- |
| 1 | Cold import, before | probe on `daedalus.kernel.fourfold_evidence` at base | runtimes 11, orchestration 2, schemas loaded |
| 2 | Cold import, after | same probe | `{"leaked": [], "facade": false}` |
| 3 | Object identity, full set | in-process `is` over the moved set | 15 bindings / 9 names, 0 mismatches |
| 4 | Diff is import-target only | AST compare of all 8 twin modules | 8 compared, 0 differing |
| 5 | No lazy or `sys.modules` escape | AST sweep of `daedalus/twin` | 0 offenders |
| 6 | New rule green | `evaluate_repository` | `passed: true`, `new: []`, `baseline: []` |
| 7 | New rule can go RED (historical) | rule applied to pre-change twin source | 4 violations at lines 6, 20, 14, 14 |
| 8 | New rule can go RED (fresh) | staged probe module, then removed | 2 violations (runtimes, orchestration) |
| 9 | Focused suite | `pytest tests/kernel/ tests/twin/ tests/contracts/ tests/test_architecture_boundaries.py -q` | 1025 passed, 11 skipped, 8 xfailed, 28 subtests, exit 0 |
| 10 | Boundary instruments | `pytest tests/test_effect_boundary.py tests/test_cli_effect_boundary.py tests/test_ikarus_os_boundary.py -q` | 103 passed, exit 0 |
| 11 | Import census | re-measured | 433 modules, 1618 edges, 12 components, max 18, digest unchanged |
| 12 | Effect-registry digest | `registry_sha256()` | `ac02027836…96211ec`, unchanged |
| 13 | Gate profile | `tools/run_gate_checks.py g1` | exit 1, the same 5 pre-existing failures, 132 passed |
| 14 | Full suite | `pytest -q` (44m57s) | 19 failed, 10637 passed, 276 skipped, 9 xfailed, 2224 subtests |
| 15 | All 19 failures are pre-existing | same 19 node IDs at `515b5fce` | 19 failed — none introduced here |

Row 13 is deliberately non-zero. The five failures in
`tests/test_registry_new_doors.py` (3) and `tests/test_registry_retired_rows.py`
(2) are another agent's open CRITICAL and are in the profile on purpose. The
criterion for this packet is that **exactly** those five remain and the passed
count does not drop. MEASURED before and after: `5 failed, 132 passed,
1 skipped, 28 subtests passed` both times, same five test IDs.

The passed count is unchanged rather than higher, and that is the honest
reading: the `g1` profile selects `tests/kernel/` by individual filename, not by
directory, so this packet's new file is not in it. The count would have moved
only if this packet had also edited the profile, which it did not — see the
residual risk below.

Rows 7 and 8 exist because a boundary rule that cannot go red is decoration.
Row 7 is the stronger of the two: it reruns the new rule against the exact
pre-change source and gets back the four leaks at the four line numbers, which
independently confirms the reported chain.

Every assertion in the new test file was mutation-checked and each fired on the
test that should catch it:

| Mutation | Failing tests |
| --- | --- |
| revert `twin/contracts.py` to base | facade sweep, cold import, rule (3 of 5) |
| hide the import behind a module `__getattr__` | facade sweep, lazy sweep, cold import, rule (4 of 5) |
| delete the `twin-no-outer-layers` rule | rule (1 of 5) |
| drop `daedalus.runtimes` from the twin rule | rule (1 of 5) |
| give `contracts/base.py` its own `_identifier` | identity (1 of 5) |
| `sys.modules` swap inside `tree_sitter_adapter.py` | lazy sweep (1 of 5) |

The first row is the honest one to read carefully: a plain revert fails 3 of 5,
not 5 of 5. The identity test does not detect the repoint and its docstring now
says so — see the review findings below.

## Migration and rollback

There is no migration. No contract, schema, serialization, digest, event, or
effect changed; four import statements now name a different module for the same
objects. `daedalus.schemas` is untouched and its 69 remaining importers are
unaffected.

Rollback is `git revert` of the single commit. It restores the leak and the
rule together, which is the correct coupling: the rule is only satisfiable in
the repointed state, so a partial rollback fails loudly at
`tests/test_architecture_boundaries.py` instead of leaving a rule that quietly
allows what it was written to forbid.

The `daedalus.schemas` shim-registry entry is unchanged (21 entries), because
this packet removes four of its consumers but not the facade or its ownership.

## Evidence, expected failures, and review

### Expected failures at hand-off

- `tools/run_gate_checks.py g1` exits 1 with 5 failures. Pre-existing at the
  base revision, unrelated to this packet, and named here separately so they
  cannot be folded into one total that hides a regression. Verified identical
  before and after: same 5 test IDs, both runs.
- The full suite (`pytest -q`, 44m57s) ends `19 failed, 10637 passed,
  276 skipped, 9 xfailed, 2224 subtests passed`, exit 1.

**Zero of the 19 belong to this packet, and that is measured rather than
asserted.** The 19 failing node IDs were re-run in a detached worktree at the
base revision `515b5fce` with none of this packet's changes present, and all 19
failed there too: `19 failed in 42.76s`. Since 19 is also the complete failure
set of the run on this branch, no failure exists on this branch that does not
exist at the base.

The briefing for this packet expected 16 pre-existing failures at `515b5fce`.
That number did not reproduce; the measured count is 19, and the extra three
are pre-existing all the same. Recorded here rather than rounded to the
expected figure. One of the 19,
`tests/test_structcore_parallel.py::PersistentCacheTest::test_corrupt_cache_degrades_to_recompute`,
fails with `PermissionError: [WinError 32]` on a temp SQLite file, which reads
like host contention rather than a deterministic defect — it may be why the
count moves between runs. Not investigated further; out of scope.

### Open items this packet found and did not fix

1. **`daedalus.spine.receipts` is the same defect, one layer down.**
   `daedalus/spine/receipts.py:49` imports `daedalus.schemas` at module level.
   MEASURED: a cold `import daedalus.spine.receipts` loads 13 outer modules and
   the facade. `spine-no-outer-layers` does not list `daedalus.schemas`, so it
   passes. This is the third instance of one pattern and the fix is the same
   shape as this packet's. It is a separate packet, not a widening of this one.
2. **`daedalus/spine/picker.py:2880` imports `daedalus.schemas` inside a
   function.** Its cold import therefore measures clean while the dependency is
   real at first use — the exact laziness this packet refuses inside
   `daedalus/twin`. It should be repointed, not left as evidence that the layer
   is clean.
3. **69 tracked modules still import `daedalus.schemas`.** Explicitly out of
   scope; listed so the number is on record rather than implied to be small.

### Residual risks

- `tests/kernel/test_fourfold_evidence_outer_ports.py` is **not** in the `g1`
  gate profile, following G1-HIER-10's precedent for its equivalent file. The
  durable guard is `twin-no-outer-layers`, which **is** gate-scored through
  `tests/test_architecture_boundaries.py`. The cold-import test adds depth, not
  the load-bearing coverage.
- The static rule reads direct import syntax only. It constrains twin's own
  imports and cannot see a further leak through `daedalus.spine` or
  `daedalus.structcore`; item 1 above is exactly that gap in a neighbouring
  layer.
- The effect-registry digest is verified unchanged, but it is **not** offered as
  evidence that the effect surface is unchanged. It hashes eleven declaration
  fields and nothing about the code its targets point at.

### Independent review findings and their resolution

An independent reviewer read the staged diff without this document's reasoning
and returned two defects in the new test file. Both were real and both are
fixed in this packet rather than argued away.

1. **The identity test was capable of passing vacuously, and its docstring
   overstated what it proved.** `daedalus/schemas.py` and
   `daedalus/kernel/contracts/base.py` both re-export from
   `daedalus.kernel.contracts.canonical`, so `bound is getattr(_facade, …)`
   holds whether or not the twin modules were repointed. The test never
   detected the repoint. Resolved two ways: the docstring now states plainly
   that the AST sweep and the cold-import test are what detect the repoint, and
   the test gained the assertion that actually earns its name — `base.py`
   re-exports these nine names and **defines** none of them, read from source
   so a runtime rebinding cannot satisfy it. Mutation-checked: adding a local
   `_identifier` definition to `base.py` now turns it red.
2. **The lazy-escape sweep excluded two files from every check, not one.** The
   two extractor adapters needed relief from the `importlib` check only, but
   the exemption was keyed on the filename and skipped the whole loop —
   `__getattr__`, `__import__`, `sys.modules` and function-scope imports were
   unchecked in exactly the two files most likely to acquire a dynamic import.
   Resolved by narrowing the exemption to the `importlib` check alone.
   MEASURED before narrowing: the other four checks find zero offenders in
   those two files, so the fix costs nothing today. Mutation-checked: a
   `sys.modules` swap inside `tree_sitter_adapter.py` now turns it red.

The reviewer also observed, correctly, that `spine-no-outer-layers` forbids ten
prefixes that neither `kernel-no-outer-layers` nor `twin-no-outer-layers`
names — `daedalus.build`, `build_exec`, `core`, `desktop_runtime`,
`file_bridge`, `ikarus`, `ikarus_os`, `integrations`, `loop`, `offload`,
`web_api`. That gap is inherited from the kernel rule, is currently inert (no
twin module imports any of them), and is review question 2 below rather than a
silent widening in this packet.

### Review questions

1. Is `daedalus.kernel.contracts.base` the right owner for the twin layer, or
   does twin importing a `daedalus.kernel` module invert an intended layering?
   The packet's position: twin already depended on the kernel transitively
   through the facade, so this makes an existing dependency honest rather than
   creating one. No new module-level SCC appears (census row 11).
2. Should `twin-no-outer-layers` forbid more than the kernel's eight prefixes?
   The packet took exactly eight with a stated principle. A larger set would be
   defensible but would not follow from this packet's argument.
3. Does any `daedalus.twin` module legitimately need an orchestration or
   runtime shape? MEASURED answer: no. The entire layer's non-stdlib imports
   are `daedalus.spine.envelope`, `daedalus.structcore.forest`, sibling twin
   modules, and — before this packet — the facade. Nothing in twin consumed
   `AgentTask`, `RunState`, `AgentReport`, or any other outer record; the leak
   was pure facade convenience, not a real dependency on an outer layer.
