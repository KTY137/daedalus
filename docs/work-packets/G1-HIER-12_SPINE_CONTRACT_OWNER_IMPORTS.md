# G1-HIER-12 — The spine names the contract owner, and the cold-import instrument's blind spot is measured rather than assumed

## Frozen packet metadata

- Packet ID: G1-HIER-12
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 4c370f2ad757da82eacb2b231d050d1baeb85212
- Dependencies: G1-HIER-01, G1-HIER-10, G1-HIER-11
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

Importing `daedalus.spine.receipts` or `daedalus.spine.picker` into a cold
interpreter loads no module under
`daedalus.{build,build_exec,chip_design,core,desktop_runtime,eval,file_bridge,ikarus,ikarus_os,integrations,kairos,loop,offload,orchestration,providers,runtimes,twin,web_api}`
and does not load `daedalus.schemas` at all, because the two `daedalus.spine`
modules that reached their canonical contracts through the legacy facade now
name the owning module under `daedalus.kernel.contracts` — with all twelve
moved bindings proven to be the same objects the facade exposes — and because
`spine-no-outer-layers` now forbids the facade itself.

MEASURED at the base revision and again after the change, with an explicit
`sys.path.insert(0, <worktree>)`:

| module | outer modules before | outer modules after | `daedalus.schemas` before | after |
| --- | --- | --- | --- | --- |
| `daedalus.spine.receipts` | 13 | 0 | loaded | not loaded |
| `daedalus.spine.picker` | 0 | 0 | not loaded | not loaded |

**The picker row is the packet.** It is unchanged, it was green at the base
revision, and it was green over a live violation. That is not a paradox to be
explained away — it is the measurement that says a cold-import test cannot
carry a layering claim on its own.

The regression instrument is `tests/contracts/test_spine_outer_ports.py`, and
the durable guard is the amended `spine-no-outer-layers` rule in
`docs/architecture/import-boundaries.json`.

### Secondary claim, found by adversarial review

`spine-no-outer-layers` is now at least as strict as `kernel-no-outer-layers`.
It was not: it named eighteen prefixes and omitted `daedalus.gates`, the one
prefix the kernel rule forbids and this one did not.

That matters for the reason `twin-no-outer-layers` already made binding one
layer up. `daedalus.kernel` imports `daedalus.spine` by **direct module-level
edge** — `kernel/approvals.py:30`, `kernel/artifacts.py:19`,
`kernel/attempt_contracts.py:24`, `kernel/attempt_ledger.py:13`/`:19`/`:20`
among others — so everything the spine can reach, the kernel reaches, and a
narrower spine set lets `kernel-no-outer-layers` be satisfied in syntax while
the layer it forbids loads in every kernel process anyway. This is the same
defect `twin-no-outer-layers` was written to close, in a layer that had no
such rule.

MEASURED, and it is larger than the leak this packet was dispatched for: a
plain module-scope `from daedalus.gates.report import …` inside
`daedalus/spine` — no dynamic trickery, an ordinary import a future packet
could write by reaching for a gate helper — transitively loads **20
`daedalus.runtimes` modules, 2 `daedalus.orchestration` modules and the
facade**, 22 outer modules against the 13 that motivated this packet. Both
instruments reported green on it.

MEASURED at the same revision: **zero** `daedalus.spine` modules import
`daedalus.gates` today, so the addition costs nothing now and is prospective,
exactly as `daedalus.orchestration` is listed in `kernel-no-outer-layers` for a
leak that has not happened yet. `test_spine_rule_is_at_least_as_strict_as_the_kernel_rule`
asserts the subset relation so the two sets cannot drift apart again.

This is a second claim, subordinate to the primary one and on the same axis —
the same rule's forbidden set — rather than a separate architectural change.
It is called out here instead of folded into the headline so an owner can
reverse it independently.

### The sweep this packet was dispatched for

The dispatching question was: the cold-import test family has scored this
refactor for two nights; how many violations can it not see?

The answer has two halves and only one of them is reassuring.

**Half one — under the rules, the exposure is one edge.** An AST pass over all
433 tracked `daedalus` Python files, attributing every `Import`/`ImportFrom`
node to its *nearest enclosing scope* (a class body nested in a function is
still deferred; a function nested in a function is still deferred), measured at
`4c370f2a`:

| rule set | forbidden edges | module scope | class scope | function scope |
| --- | --- | --- | --- | --- |
| as committed at `4c370f2a` | 0 | 0 | 0 | 0 |
| with `daedalus.schemas` added to the spine rule | 2 | 1 | 0 | 1 |

The two are `receipts.py:49` (module) and `picker.py:2880` (function, inside
`_default_attempt`). **`picker.py:2880` is the only function-scope forbidden
import in the tree**, across every rule in the contract. That is the good
reportable result the briefing hoped for, and it was measured, not assumed.

The first row deserves a caveat rather than applause: it is 0 because
`baseline` is `[]` and the rules were green by construction. A green rule set
proves nothing about the runtime instrument, which is why the counterfactual
row exists.

**Half two — the instrument's blindness is far wider than its current
exposure.** The same pass found **495 function-scope `daedalus.*` imports** in
the tracked tree at `4c370f2a`. A cold-import test cannot observe a single one
of them, because a deferred import is not in `sys.modules` at the moment the
test looks. By importing layer:

| count | layer | count | layer |
| --- | --- | --- | --- |
| 53 | `daedalus/cli.py` | 21 | `daedalus/eval` |
| 42 | `daedalus/ikarus_os.py` | 16 | `daedalus/build_exec.py` |
| 35 | `daedalus/spine` | 15 | `daedalus/offload.py` |
| 33 | `daedalus/kernel` | 15 | `daedalus/web_api.py` |
| 28 | `daedalus/mapping` | 14 | `daedalus/structcore` |
| 25 | `daedalus/core.py` | … | 43 further layers |

81 of the 495 sit in the four rule-governed layers: 35 in `daedalus/spine`
(34 after this packet), 33 in `daedalus/kernel`, 13 in `daedalus/runtimes`, and
**0 in `daedalus/twin`** — the last because G1-HIER-11's
`test_twin_layer_has_no_lazy_or_sys_modules_escape` bans them outright there.

So: today exactly one deferred edge was a violation, and this packet removes
it. The correct reading is not "the hole was one wide". It is that the runtime
instrument is blind across 495 edges and was *load-bearing on none of them by
luck*, and that the static checker — not the cold import — is what has actually
been holding the line.

### Which instrument was blind, precisely

Not `tools/architecture_boundaries.py`. It builds its node list with
`ast.walk`, so it observes an import at any scope. It missed both edges for a
different reason: `daedalus.schemas` was absent from `spine-no-outer-layers`'s
forbidden set. Replaying the amended rule against the exact `4c370f2a` source
returns both, with the column offsets that prove the second came from inside a
function body:

```text
spine-no-outer-layers  daedalus/spine/picker.py:2880:4    -> daedalus.schemas
spine-no-outer-layers  daedalus/spine/receipts.py:49:0    -> daedalus.schemas
```

The blind instrument is the runtime one — `import X`, then inspect
`sys.modules`. This packet demonstrates that mechanically rather than arguing
it: mutation **M2** below reverts `picker.py` to a function-scope facade import
and turns four tests red, while
`test_cold_spine_picker_import_loads_no_outer_implementation` **stays green**.

## Scope

In scope — repointed imports only, no behavior change:

- `daedalus/spine/receipts.py` (11 symbols, module scope, one facade import
  replaced by seven owner imports)
- `daedalus/spine/picker.py` (1 symbol, `ResourceBudget`, moved from function
  scope in `_default_attempt` to module scope and repointed)

In scope — a consequence of the repoint, not an independent change:

- `.gitattributes` (three lines). The repoint pulled
  `daedalus/kernel/contracts/{attempts,missions,runtime}.py` into the ignition
  bundle's computed import closure, and
  `tests/test_ignition_bundle_gitattributes.py` requires one explicit
  `<path> -text` declaration per closure file. **This packet introduced that
  failure and this packet fixes it** — see the regression note under Evidence.

In scope — contract, instrument, and census artifacts:

- `docs/architecture/import-boundaries.json` (one prefix added to
  `spine-no-outer-layers`; rationale and `target_owner` amended)
- `tests/contracts/test_spine_outer_ports.py` (new, 8 tests)
- `tests/contracts/test_import_scc_hierarchy.py` (census comment and
  `CENSUS_EDGES` only; both totals re-measured)
- `tests/contracts/test_work_packet_index.py` and
  `docs/work-packets/index.json` (this document's registry entry)

Forbidden paths — untouched, and verified untouched in the final diff:

- `daedalus/schemas.py`. The facade keeps existing and keeps re-exporting. It
  is not deleted, not narrowed, and deliberately **not** made lazy.
- Every consumer of `daedalus.schemas` outside the two files above.
- `daedalus/spine/effect_boundary.py`, `killswitch.py`, `containment.py`,
  `writer_inventory.py`, `docref_gate.py`, `cancel.py` — other owners' guard
  files, out of this packet's write set.
- `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, its amendment chain, `AGENTS.md`.
- `tests/test_registry_new_doors.py`, `tests/test_registry_retired_rows.py` —
  another packet's open CRITICAL, red on purpose in the `g1` profile.

## Contracts and behavior

### The repoint

All 11 symbols are defined in `daedalus.kernel.contracts.canonical`, the
package's "single implementation nucleus during the strangler split". Following
the house style G1-HIER-10 established — never import `canonical` directly,
take shared base helpers from `.contracts.base` and every other symbol from its
domain locator — `receipts.py` now names seven owners:

| owner | symbols |
| --- | --- |
| `.contracts.attempts` | `AttemptContract`, `AttemptReceipt` |
| `.contracts.base` | `ContractProvenance` |
| `.contracts.evidence` | `EvidencePacket` |
| `.contracts.missions` | `MissionContract` |
| `.contracts.policy` | `PolicyDecision` |
| `.contracts.resources` | `EffectScope`, `ResourceBudget`, `ResourceUsage`, `RuntimeCapabilities` |
| `.contracts.runtime` | `RuntimeManifest` |

`picker.py` names one, `.contracts.resources`, for `ResourceBudget`.

Object identity is asserted over the **full** moved set rather than sampled: 12
bindings across 11 distinct names (`ResourceBudget` is taken by both files),
each identical to the object on the facade, on the new owner, and in the
nucleus. No module was added and none deleted.

### The deferred import, and why the cycle hypothesis did not hold

The briefing allowed that moving `picker.py:2880` to module level might
reintroduce a cycle, which would have made the honest fix a different one. It
does not, and that was measured three ways before the edit:

1. **Static.** The module-level-only transitive closure of
   `daedalus.kernel.contracts.resources` never reaches `daedalus.spine.picker`.
2. **Empirical.** Both import orders — owner-then-picker and picker-then-owner
   — exit 0, with no `ImportError` and no partially-initialised module.
3. **Cost.** Hoisting adds **zero** new modules to a cold
   `import daedalus.spine.picker`: `daedalus.kernel.contracts.resources` is
   already resident via the two `..kernel` ports the file imports at line 72.

The function-scope placement was never cycle-avoidance. The surrounding
comment block at `picker.py:2858–2877` documents a genuine and unrelated
constraint — the picker must not spawn a subprocess, enforced structurally by
`test_there_is_no_apply_path_in_this_module`, which greps the source for
`subprocess`, `shutil` and write verbs. That guard has no opinion about
module-level imports of `daedalus` modules and is unaffected. The facade import
was simply convenient at the call site.

Because there is no cycle and no cost, module scope is strictly better than a
deferred repoint: a deferred import would have satisfied the amended static
rule while leaving the runtime instrument reporting a clean layer, which is the
exact defect this packet exists to remove.

### The rule, and why `daedalus.schemas` belongs in the spine set

`spine-no-outer-layers` gains one prefix, `daedalus.schemas`, and the argument
is narrower and stronger than the kernel's rather than a copy of it:

> The rule **already** forbids `daedalus.orchestration` and
> `daedalus.runtimes`. The facade's own entry in
> `docs/architecture/shim-registry.json` declares its targets to be
> `daedalus.kernel.contracts.canonical`,
> `daedalus.orchestration.legacy_reports` and
> `daedalus.runtimes.contracts.provider_report`. Importing the facade
> therefore loads exactly the prefixes this rule already names, one hop away.
> The facade is a one-hop launder of the rule's own forbidden set, so listing
> it closes a bypass rather than widening the rule.

That is not hypothetical: at `4c370f2a` a cold `import daedalus.spine.receipts`
loaded 13 modules under those two forbidden prefixes and the rule reported
`PASS`.

Unlike G1-HIER-11, no intermediate-layer rule is needed. Both offending edges
were **direct** `daedalus.spine` imports of the facade, which this checker sees
— at any scope, because it walks the whole AST. One prefix therefore owns both
`receipts.py:49` and `picker.py:2880`, and no separate anti-lazy rule is
required for forbidden targets.

`baseline` stays `[]`. Nothing was allowlisted, and appending to the allowlist
was not available in any case.

### The guard that was considered and deliberately NOT adopted

G1-HIER-11 added `test_twin_layer_has_no_lazy_or_sys_modules_escape`, which
bans *every* function-scope import in `daedalus/twin`. Copying it to
`daedalus/spine` would go red on legitimate edges and is therefore not
available: the layer has **34** deferred `daedalus.*` imports after this
packet, and they are load-bearing intra-layer cycle avoidance —
`bootstrap` → `picker` (4 sites), `picker` → `attempt`, `containment` →
`cancel`, `attempt` → `effect_boundary`, and the `main` entrypoints' budget and
effect-boundary imports.

Per the briefing's instruction not to baseline a rule that goes red on a
legitimate edge, the shape that **does** own it is the one already in place:
the static checker sees every scope, so the forbidden-prefix rule covers
deferred imports without needing to forbid deferral itself.
`test_the_layer_still_defers_imports_the_cold_import_test_cannot_see` pins the
34 as a moving census and asserts that none of them is a forbidden target, so
the division of labour between the two instruments is mechanical rather than
documented.

### What was deliberately not done

No module was made lazy, no module `__getattr__` was added, and no module was
swapped in `sys.modules`. The change moves an import *earlier*, never later.

## Acceptance matrix

Interpreter for every row: `.venv/Scripts/python.exe -m pytest`. Exit codes
read directly, never through a pipe.

| # | Check | Command | Result |
| --- | --- | --- | --- |
| 1 | Cold import `receipts`, before | probe at base | 13 outer, facade loaded |
| 2 | Cold import `receipts`, after | same probe | `{"leaked": [], "facade": false}` |
| 3 | Cold import `picker`, before | probe at base | `{"leaked": [], "facade": false}` — green over a live violation |
| 4 | Cold import `picker`, after | same probe | `{"leaked": [], "facade": false}` |
| 5 | Deferred-import sweep, whole tree | AST scope pass over 433 files | 495 deferred `daedalus.*`; 2 forbidden under the proposed rule (1 module, 1 function); 0 under the committed rule |
| 6 | Object identity, full set | in-process `is` over the moved set | 12 bindings / 11 names, 0 mismatches |
| 7 | Owners re-export and define nothing | AST read of 7 locator modules | 0 shadowing definitions |
| 8 | No cycle from hoisting | static closure + both import orders + cost | no cycle; exit 0 both orders; +0 modules |
| 9 | Amended rule green | `evaluate_repository` | `PASS`, `current=0`, `new=0`, `baseline=[]`, 433 files |
| 10 | Rule can go RED (historical) | amended rule vs. `4c370f2a` source | 2 violations at `picker.py:2880:4`, `receipts.py:49:0` |
| 11 | Rule can go RED (fresh) | staged tracked probe module, then removed | `FAIL`, 2 new violations at `4:0` (module) and `8:4` (function) |
| 12 | New test file | `pytest tests/contracts/test_spine_outer_ports.py -q` | 8 passed, exit 0 |
| 13 | Mutation matrix | 5 mutations, applied and reverted | each fired on the right test; see below |
| 14 | Import census | re-measured after `git add` | 433 modules, **1618 → 1624** edges, SCC claims unchanged |
| 15 | Focused suite | `pytest tests/kernel/ tests/contracts/ tests/test_architecture_boundaries.py tests/test_spine_attempt.py -q` | 1037 passed, 8 skipped, 8 xfailed, 28 subtests, exit 0 |
| 16 | Boundary instruments | `pytest tests/test_effect_boundary.py tests/test_cli_effect_boundary.py tests/test_ikarus_os_boundary.py -q` | 103 passed, exit 0 |
| 17 | Spine suites | `pytest tests/test_spine_picker.py tests/test_spine_ledger.py tests/test_spine_map_source.py -q` | 99 passed, 1 xfailed, exit 0 |
| 18 | Effect-registry digest | `registry_sha256()` | `ac02027836…96211ec`, unchanged |
| 19 | Gate profile | `tools/run_gate_checks.py g1` | exit 1, same 5 IDs, 132 -> 140 passed |
| 20 | Full suite | `pytest tests/ -q` | 15 failed, 9563 passed, 276 skipped, 9 xfailed, 2200 subtests, exit 1 |
| 21 | `daedalus.gates` addition is free today | grep + `evaluate_repository` | 0 spine modules import it; rule stays `PASS` |
| 22 | `daedalus.gates` leak is real | cold `import daedalus.gates.report` | 20 runtimes + 2 orchestration + facade = 22 outer |
| 23 | `daedalus.gates` rule can go RED | staged tracked probe, then removed | `FAIL`, 1 new violation at `4:0 -> daedalus.gates.report` |
| 24 | Spine set ⊇ kernel set | `test_spine_rule_is_at_least_as_strict_as_the_kernel_rule` | subset holds, 0 missing |
| 25 | Ignition-closure regression found | full suite run 1, compared by node ID to base | 17 failed; 2 introduced by this packet |
| 26 | Ignition-closure regression fixed | `pytest tests/test_ignition_bundle_gitattributes.py tests/test_ignition_bundle.py tests/test_ignition_gate1.py -q` | 102 passed, exit 0 |

Row 19 is deliberately non-zero. The five failures in
`tests/test_registry_new_doors.py` (3) and `tests/test_registry_retired_rows.py`
(2) are another agent's open CRITICAL and are in the profile on purpose. The
criterion for this packet is that **exactly** those five remain and the passed
count does not drop.

Rows 10 and 11 exist because a boundary rule that cannot go red is decoration.
Row 10 is the stronger of the two: it replays the amended rule against the
exact pre-change source and returns both leaks at both line **and column**
offsets, which independently confirms that the static checker was never the
blind instrument.

### Mutation matrix

Every assertion in the new test file was mutation-checked. Baseline 8 passed. M1-M5 were run before the daedalus.gates prefix was added and are reported against the 7 tests that existed then; M6 was run after, against 8.

| Mutation | Tests that went red |
| --- | --- |
| M1 `receipts.py` reverted to the facade | cold-import `receipts`, facade sweep, rule (3 of 7) |
| M2 `picker.py` reverted to a function-scope facade import | facade sweep, rule, deferred census, identity (4 of 7) |
| M3 `daedalus.schemas` dropped from the spine rule | rule, function-scope-visibility (2 of 7) |
| M4 checker stops walking into function bodies | function-scope-visibility (1 of 7) |
| M5 `resources.py` defines `ResourceBudget` instead of re-exporting | identity (1 of 8) |
| M6 `daedalus.gates` dropped from the spine rule | kernel-subset (1 of 8) |

**M2 is the row to read carefully, and it is this packet's central evidence.**
Reverting `picker.py` to exactly the construct that existed at `4c370f2a`
turns four tests red — and
`test_cold_spine_picker_import_loads_no_outer_implementation` stays **green**.
The cold-import instrument does not merely fail to catch the violation in
principle; it was measured failing to catch it, here, on this branch, against
the real construct.

M4 mutates the shared checker rather than this packet's code, and is included
because the claim "one prefix owns both edges" rests entirely on
`_import_references` walking function bodies. If that ever changes, this packet's
argument becomes false and a test says so.

## Migration and rollback

There is no migration. No contract, schema, serialization, digest, event, or
effect changed. Twelve bindings now come from a different module and one of
them is bound earlier in time; all twelve are the same objects.
`daedalus.schemas` is untouched and its remaining importers are unaffected.

Rollback is `git revert` of the single commit. It restores the two imports and
the rule together, which is the correct coupling: the rule is only satisfiable
in the repointed state, so a partial rollback fails loudly at
`tests/test_architecture_boundaries.py` and
`tests/contracts/test_spine_outer_ports.py` instead of leaving a rule that
quietly allows what it was written to forbid.

The `daedalus.schemas` shim-registry entry is unchanged (21 entries): this
packet removes two of its consumers, not the facade or its ownership. Its
`removal_criteria` remains unmet.

## Evidence, expected failures, and review

### Expected failures at hand-off

- `tools/run_gate_checks.py g1` exits 1 with 5 failures, pre-existing at the
  base revision and unrelated to this packet. Named separately here so they
  cannot be folded into one total that hides a regression. Verified identical
  before and after by node ID: `5 failed, 132 passed` at `4c370f2a` and
  `5 failed, 140 passed` here, same five IDs, `diff` of the two sorted lists
  empty. The +8 is exactly this packet's new test file, which the profile picks
  up because it selects `tests/contracts/` as a directory.
- The pre-existing full-suite failure set at `4c370f2a` is **15**, re-run by
  exact node ID in a detached worktree at the base revision with none of this
  packet's changes present: `15 failed, 3 passed in 48.70s`. That reproduces
  the figure this packet's briefing carried, which is worth stating because the
  briefing also noted a broader baseline had measured 19–20 depending on scope,
  and G1-HIER-11 measured 19 at `515b5fce`. The 15 here is the count of
  candidate node IDs re-run at base, not an independent full-suite baseline.

The 15 pre-existing failures, by node ID:

```text
tests/orchestration/test_run_mission.py::test_migrated_surfaces_delegate_without_a_second_execution_path
tests/test_bootstrap_receipt.py::TheLeasedSingleAttempt::test_leased_single_run_terminalises_and_reports
tests/test_comms.py::VsCodeExtensionTests::test_extension_dashboard_supports_team_and_environment_controls
tests/test_deepseek_substitution_guard.py::InventedImports::test_no_false_positives_across_the_real_tree
tests/test_desktop_packaging.py::test_desktop_backend_readiness_is_child_nonce_bound
tests/test_gate_discrimination.py::CorpusDesignTests::test_anchors_are_present_and_unique_in_the_current_tree
tests/test_ikarus_llm_voice.py::test_chat_auto_route_uses_llm_client_and_records_resolved_provider
tests/test_ikarus_llm_voice.py::test_chat_unbounded_policy_removes_attempt_timeout_and_token_caps
tests/test_registry_new_doors.py::test_a_planted_effect_and_a_deleted_one_are_both_caught
tests/test_registry_new_doors.py::test_no_declared_effect_is_painted_on
tests/test_registry_new_doors.py::test_the_derivation_is_not_vacuous
tests/test_registry_retired_rows.py::test_the_ollama_rollback_body_only_delegates
tests/test_registry_retired_rows.py::test_the_ollama_rollback_row_equals_the_ast_derived_effect_set
tests/test_spine_gate0_writer_factory.py::test_factory_is_only_an_opening_profile_not_a_second_ledger_authority
tests/test_structcore_parallel.py::PersistentCacheTest::test_corrupt_cache_degrades_to_recompute
```

`tests/test_spine_gate0_writer_factory.py` is the only one of the 15 under
`daedalus/spine`'s test surface, and it fails identically at the base
revision with none of this packet's changes present. It exercises the writer
factory and the ledger authority, neither of which this packet touches.

- The final full suite at the committed state, `pytest tests/ -q` (34:28),
  ends `15 failed, 9563 passed, 276 skipped, 9 xfailed, 2200 subtests passed`,
  exit 1. The 15 failing node IDs are **byte-identical** to the base-revision
  set above — `diff` of the two sorted lists is empty.

**Zero of the 15 belong to this packet.** That is the second full-suite run.
The first, against the same tree before the `.gitattributes` fix, returned 17,
and the two extras were this packet's own regression rather than pre-existing
noise. Both runs are reported; the first is not hidden because it is the one
that found the defect.

| run | result | verdict |
| --- | --- | --- |
| contaminated (05:10, discarded) | 18 failed, 9552 passed, 57:58 | not evidence |
| clean run 1 (pre-fix) | 17 failed, 9561 passed, 34:47 | 2 introduced by this packet |
| clean run 2 (committed state) | **15 failed, 9563 passed, 34:28** | identical to base set |

The arithmetic is consistent across the two clean runs: 9561 + 17 = 9563 + 15 =
9578 non-skipped, non-xfailed outcomes. The two tests moved from failed to
passed and nothing else moved.

### Measurement hygiene notes

- **A contaminated run is named, not counted.** A full-suite run was started in
  this worktree at 05:10, and both a source edit and — later — an adversarial
  reviewer's probe files under `daedalus/spine/` landed while it was running.
  It finished `18 failed, 9552 passed, 276 skipped, 9 xfailed, 2200 subtests
  in 57:58`. That result is **discarded**. It is named here only because its
  failure list was reused as the candidate set for the base-revision re-run
  above, and because the difference is instructive: 15 of its 18 reproduce at
  `4c370f2a`, and the 3 that do not
  (`test_ignition_bundle_gitattributes.py` ×2 and
  `test_registry_new_doors.py::test_the_new_rows_add_no_conformance_blocker`)
  are all tree-scanning tests that would see exactly the probe files that
  existed in the tree during that window. That is an explanation, not a
  measurement; the clean run at the committed state is what settles them.
- **The original baseline attempt was contaminated by my own sequencing, not by
  the box.** It was started before the first edit rather than in a separate
  worktree. The correct method — a detached worktree at the base revision —
  was used for the numbers that are actually reported, following G1-HIER-11's
  method.
- **The box was under load throughout.** Two other sessions ran full suites
  concurrently with every measurement in this packet — one plain
  `pytest tests -q` from 04:34, and one `pytest tests -q -n auto --dist
  loadfile` from 05:26 that saturates every core. Nothing here is a timing
  claim and none should be read as one; the wall-clock figures quoted are
  recorded for provenance, not for comparison.
- **One instrument in this packet could not be killed when it should have
  been.** The contaminated run was identified as contaminated within minutes,
  but the attempt to terminate it was refused by the environment's command
  classifier, so it ran to completion competing for the box. Recorded because
  it affects every duration above.
- **The effect-registry digest is verified unchanged but is NOT offered as
  evidence that the effect surface is unchanged.** It hashes eleven declaration
  fields and nothing about the code its targets point at.

### Corrections to figures this packet inherited

- The briefing's two cold-import measurements — `receipts` 13 outer with the
  facade loaded, `picker` 0 outer without it — both reproduced exactly at
  `4c370f2a`.
- A delegate reported that only 10 of the 13 modules load, which would have
  meant the "13" was stale. It was an artifact of an abbreviation in the brief
  it was given (`daedalus.runtimes(+ … .profiles, .trust, .trust_store)` read as
  three top-level modules). Re-measured directly: `import daedalus.schemas`
  alone loads all 13, and the three are `daedalus.runtimes.profiles`,
  `daedalus.runtimes.trust`, `daedalus.runtimes.trust_store`. The briefing's
  figure stands; the delegate's brief was at fault, not the measurement.

### A regression this packet introduced, and how it was caught

The first clean full-suite run at the committed state returned **17 failures**,
two more than the 15 that reproduce at `4c370f2a`. The two extras were
`tests/test_ignition_bundle_gitattributes.py::test_every_bundle_file_has_a_filter_stable_declaration`
and `::test_the_gitattributes_pin_is_an_explicit_list_not_a_wildcard`.

They were **mine**:

```text
AssertionError: 3 closure files have no explicit .gitattributes line:
daedalus/kernel/contracts/attempts.py,
daedalus/kernel/contracts/missions.py,
daedalus/kernel/contracts/runtime.py
```

`test_every_bundle_file_has_a_filter_stable_declaration` recomputes the
ignition bundle's import closure from source on every run and requires one
explicit `<path> -text` line in `.gitattributes` per closure file — a
deliberate design choice, documented in that test, over a `daedalus/**/*.py`
wildcard whose blast radius was measured and rejected. Repointing
`receipts.py` off the facade onto seven owners added three of those owners to
the closure for the first time. Four (`base`, `evaluation`, `evidence`,
`policy`, `resources`) were already declared; three were not.

The fix is three lines in `.gitattributes`, in the alphabetical position the
file already uses, which is exactly the remediation the test's own comment
prescribes. MEASURED after: `pytest tests/test_ignition_bundle_gitattributes.py
tests/test_ignition_bundle.py tests/test_ignition_gate1.py -q` →
**102 passed, exit 0**.

Two things are worth saying plainly about this:

1. **It was only caught because the full-suite total was not rounded.** 17
   against an expected 15 is a two-test discrepancy that would have vanished
   into "roughly the pre-existing set" if the failures had been compared as a
   count instead of by node ID. The base-revision re-run is what turned "17 is
   about right" into "these two are new".
2. **A third failure in the same neighbourhood was NOT mine, and the
   distinction had to be measured, not guessed.** The discarded contaminated
   run also failed
   `tests/test_registry_new_doors.py::test_the_new_rows_add_no_conformance_blocker`,
   which does not appear in the clean run at all. Both that test and the two
   real ones scan the tree; only two of the three were caused by this packet.
   Assuming either way would have been wrong.

The full suite was then re-run in full against the corrected state rather than
patched-and-asserted, because a targeted re-run of two node IDs would only have
proved those two.

### Adversarial probe: what still evades both instruments

An independent adversary was asked to make a `daedalus/spine` module genuinely
depend on the facade while both the checker and this packet's test file stayed
green. Eleven attacks, each verified to produce a **real** dependency by cold
import, not merely dead code. The guard caught four; seven evaded.

| attack | checker | test file | evades |
| --- | --- | --- | --- |
| function-scope `from daedalus.schemas import X` | FAIL | 3 red | no |
| relative `from ..schemas import X` | FAIL | 2 red | no |
| `if TYPE_CHECKING:` guarded import | FAIL | 2 red | no |
| module-scope `from daedalus.gates.report import …` | **FAIL (after this packet)** | green | **closed here** |
| `importlib.import_module("daedalus.schemas")` | PASS | green | yes |
| `importlib.import_module` with a runtime-built name | PASS | green | yes |
| `__import__("daedalus.schemas", …)` | PASS | green | yes |
| module-level `__getattr__` importing on access | PASS | green | yes |
| `sys.modules` population by string key | PASS | green | yes |
| `exec(compile(<assembled import>))` | PASS | green | yes |
| untracked file under `daedalus/spine/`, never `git add`ed | PASS | green | yes |

Three honest conclusions:

1. **The permitted-intermediate attack was a real, static, ordinary-looking
   hole and it is now closed** — that is the secondary claim above. It was the
   only evasion in the set requiring no dynamic mechanism at all, and the only
   one a future packet would plausibly write by accident.
2. **The dynamic-import family is outside the checker's declared observation
   boundary and remains so.** `tools/architecture_boundaries.py` says as much
   in its own module docstring ("Dynamic imports, runtime dispatch,
   monkey-patching and generated code remain outside the observation
   boundary"). This packet does not extend it and does not claim to. Of the
   six, the module-level `__getattr__` is the one worth watching, because it is
   shaped like a legitimate PEP 562 lazy-import optimisation rather than like
   an attack.
3. **The untracked-file evasion is total and is inherent to the design.** Both
   the checker and this file's `_tracked_spine_files()` enumerate through
   `git ls-files`, so a file that Python imports normally but that was never
   staged is invisible to both while reporting a spotless PASS. This needs no
   adversarial intent — a forgotten `git add` is enough. It is recorded, not
   fixed: changing the source-of-truth from the git index to the filesystem is
   a change to the contract's `tracked_source_command`, which is a different
   packet with a different argument about reproducibility.

None of these is advertised as covered. Per this repository's review rules, a
guard presented as a complete guarantee is itself a defect, so the boundaries
are written into the rule's rationale as well as here.

### Open items this packet found and did not fix

1. **`spine-no-outer-layers` does not forbid `daedalus.mapping` or
   `daedalus.structcore`, and `picker.py` reaches both from function scope** —
   `picker.py:1032` → `daedalus.mapping.drift`, `picker.py:2344` →
   `daedalus.mapping`, `picker.py:1747` → `daedalus.structcore.index`. Whether
   those are outer layers relative to the spine or sibling infrastructure is a
   question this packet did not settle, and adding them would be a widening
   with a different argument than the facade's. Recorded, not acted on.
2. **495 function-scope `daedalus.*` imports remain tree-wide**, 461 of them
   outside `daedalus/spine`. None is a forbidden target today. They are
   invisible to every cold-import test in the repository, and the only
   instrument that covers them is the static checker — which covers a layer
   only if that layer has a rule. `daedalus/cli.py` (53) and
   `daedalus/ikarus_os.py` (42) have none.
3. **`daedalus/kernel` has 33 deferred `daedalus.*` imports and no anti-lazy
   guard**, where `daedalus/twin` has 0 and one. Two of them —
   `attempt_execution.py:1209` → `daedalus.offload` and the several
   `→ daedalus.spine.*` — are not forbidden by `kernel-no-outer-layers` today,
   so this is a gap in the rule's forbidden set rather than a live violation.
4. **The remaining `daedalus.schemas` importers.** Explicitly out of scope.
5. **`runtimes-no-gates` forbids exactly one prefix and `daedalus/runtimes` has
   13 deferred `daedalus.*` imports**, including
   `live_fault_collector.py:691` → `daedalus.spine.effect_boundary`. That rule
   was written for one specific inversion (runtime admission must not call its
   gate producers) and makes no claim to be a layer rule. Whether
   `daedalus/runtimes` needs a full forbidden set is a question this packet
   raises and does not answer.
6. **The subset relation this packet asserted for spine⊇kernel is not asserted
   for `runtimes-no-gates`.** `tests/kernel/test_fourfold_evidence_outer_ports.py`
   asserts kernel ⊆ twin; this packet adds kernel ⊆ spine. Nothing asserts a
   relation for the runtimes rule, and given that the kernel imports
   `daedalus.runtimes` nowhere at module level today, it is not obviously the
   same argument. Named rather than assumed either way.

### Residual risks

- `tests/contracts/test_spine_outer_ports.py` **is** in the `g1` gate profile,
  because the profile selects `tests/contracts/` as a directory. This differs
  from G1-HIER-10's and G1-HIER-11's equivalent files, which live under
  `tests/kernel/` and are selected there by individual filename and so were
  not gate-scored. The consequence is that this packet's passed count rises
  rather than staying flat, which is the intended direction.
- The static rule reads direct import syntax only. It constrains
  `daedalus.spine`'s own imports and cannot see a further leak through a
  permitted edge into a layer without its own rule — the same limitation
  G1-HIER-11 recorded, now one layer further out.
- `SPINE_DEFERRED_DAEDALUS_IMPORTS = 34` is a moving census, not an invariant.
  A later packet that legitimately adds or removes a deferred import inside the
  layer must re-measure it. Its comment says so.
- **Adding `daedalus.gates` constrains future packets, and that is the point of
  it, but it is the one change here an owner might want to reverse.** It is
  prospective: nothing needs it today, and if a future packet has a legitimate
  reason for `daedalus/spine` to consume a gate producer, this rule will refuse
  it and the argument will have to be had then rather than now. The packet's
  position is that this is the correct default given `kernel → spine` is a
  module-level edge, but it is a judgement, not a measurement, and it is
  isolated to one line of `import-boundaries.json` plus one test so it can be
  reverted on its own.
- The whole boundary contract's observation is the **git index**, not the
  filesystem. A file present under `daedalus/spine/` but never staged is
  imported normally by Python and seen by neither instrument. Confirmed by
  probe. This is inherent to `tracked_source_command` and is not fixed here.

### Review questions

1. Should `daedalus.mapping` and `daedalus.structcore` join
   `spine-no-outer-layers`? Open item 1. The packet's position is that this
   needs its own argument about what those layers are, and inheriting the
   facade argument would be wrong.
2. Should `daedalus/kernel` acquire an anti-lazy guard like `daedalus/twin`'s,
   or is 33 deferred imports evidence that the blanket form is only workable in
   a leaf layer? The packet's position is the latter, which is why the spine
   got the census assertion instead.
3. Is the cold-import test family worth keeping now that its blind spot is
   measured? The packet's position: yes, but only as depth. It proves what one
   entrypoint loads. Every claim about a *layer* in this programme should rest
   on the static rule, and
   `test_cold_spine_picker_import_loads_no_outer_implementation` carries a
   docstring saying exactly that, against the day someone reads a green cold
   import as a clean layer again.
4. **Was adding `daedalus.gates` this packet's business, or a second packet's?**
   It was found by adversarial review of this packet's own change, it is the
   same rule's forbidden set, it is measured free today, and it closes a leak
   larger than the one this packet was dispatched for. Against that: the packet
   was scoped to the facade, and G1-HIER-11 declined an analogous widening and
   made it a review question instead. The packet chose to include it because
   `kernel → spine` is a direct module-level edge, which makes
   `spine ⊇ kernel` the same argument `twin-no-outer-layers` already settled
   rather than a new one. An owner who disagrees can revert exactly one JSON
   line and one test without touching the primary claim.
5. Should the boundary contract observe the filesystem rather than the git
   index? Residual risk 4. It would close the untracked-file evasion and would
   cost reproducibility, which is why the current design chose the index.
