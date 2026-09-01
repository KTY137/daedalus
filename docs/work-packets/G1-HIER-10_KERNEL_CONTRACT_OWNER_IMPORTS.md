# G1-HIER-10 — Kernel imports name the contract owner, not the legacy facade

## Frozen packet metadata

- Packet ID: G1-HIER-10
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: aeef64bfb3a2cbb1bbafa38f6d0a1462c2b9e794
- Dependencies: G1-HIER-01, G1-HIER-02, G1-HIER-02A, G1-HIER-04B
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

Importing `daedalus.kernel.offload_lease` into a cold interpreter loads no
module under `daedalus.{chip_design,eval,gates,kairos,providers,runtimes}` and
no module under `daedalus.orchestration`, because the eighteen kernel modules
that reached their canonical contracts through the legacy `daedalus.schemas`
facade now name the owning module under `daedalus.kernel.contracts` — with
every moved symbol proven to be the same object it was before.

`tests/kernel/test_offload_lease_outer_ports.py::test_cold_kernel_import_loads_no_outer_implementation`
is the deterministic instrument for that claim, and it was red at the base
revision.

The claim is deliberately about **one entrypoint**. That test transitively
loads only 13 `daedalus.kernel.*` modules, so it does not exercise most of the
eighteen; what covers all eighteen is the static `kernel-no-outer-layers` rule,
which reads direct import syntax in every tracked kernel file. Neither
instrument makes a kernel-wide transitive claim, and this packet does not make
one either — `daedalus.kernel.fourfold_evidence` still reaches orchestration
and runtimes through `daedalus.twin`, which is recorded as an open item below
rather than papered over.

## Scope

In scope — repointed imports only, no behavior change:

- `daedalus/kernel/approvals.py`
- `daedalus/kernel/artifacts.py`
- `daedalus/kernel/attempt_clock.py`
- `daedalus/kernel/attempt_contracts.py`
- `daedalus/kernel/attempt_execution.py`
- `daedalus/kernel/attempt_ledger.py`
- `daedalus/kernel/attempt_workspace.py`
- `daedalus/kernel/authorization.py`
- `daedalus/kernel/effect_recovery.py`
- `daedalus/kernel/effect_replay.py`
- `daedalus/kernel/effects.py`
- `daedalus/kernel/fourfold_evidence.py`
- `daedalus/kernel/offload_lease.py`
- `daedalus/kernel/promotion.py`
- `daedalus/kernel/promotion_execution.py`
- `daedalus/kernel/runtime_conformance.py`
- `daedalus/kernel/runtime_effects.py`
- `daedalus/kernel/source_trees.py`

In scope — contract and census artifacts:

- `docs/architecture/import-boundaries.json` (two forbidden target prefixes)
- `docs/architecture/shim-registry.json` (one registered facade)
- `.gitattributes` (five closure members the repoint pulled into the Gate-1
  evaluator bundle), and the working-copy line endings of those five files
- `tests/test_architecture_boundaries.py` (moved shim count)
- `tests/contracts/test_import_scc_hierarchy.py` (moved edge census)
- `tests/kernel/test_contract_hierarchy.py` (two added tests: the eighteen
  modules' bindings, and `base` as the owner locator for private validators)
- `docs/work-packets/index.json`, `tests/contracts/test_work_packet_index.py`
  (this document enters the registry)

Forbidden paths, untouched:

- `daedalus/schemas.py`. The facade keeps existing and keeps re-exporting. It
  was NOT made lazy: a lazy facade would turn the cold-import test green while
  leaving the dependency in place until first attribute access, which hides the
  violation instead of removing it. It is also not deleted — roughly eighty-five
  non-kernel callers still import through it, and `test_contract_hierarchy.py`
  resolves a legacy pickle `GLOBAL` opcode against it.
- The Effect Registry and its rows (`daedalus/spine/effect_boundary.py`,
  `tests/test_registry_new_doors.py`, `tests/test_registry_retired_rows.py`).
- `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, its amendment chain, `AGENTS.md`, and
  the guards under `daedalus/spine/`.

## Contracts and behavior

**Object identity is the property that makes the repoint safe.** `daedalus/
schemas.py` is a pure re-export: every symbol the kernel took from it is bound
by `daedalus.kernel.contracts.canonical`, and the domain modules under
`daedalus/kernel/contracts/` re-export from that same nucleus. So
`daedalus.schemas.X is daedalus.kernel.contracts.<owner>.X` holds for every
moved symbol, and no serialization authority, digest, or `isinstance` check
moves. This was verified for all 25 moved symbols and all 91 module-level
bindings across the eighteen files, not sampled.

**Owner selection.** Symbols are imported from the domain module that
`daedalus/kernel/contracts/__init__.py` names as their owner, not from
`canonical` directly. That file calls the domain modules "stable hierarchy
locators" and `canonical` "the single implementation nucleus during the
strangler split". Binding eighteen kernel modules to the nucleus would bind
them to the part that is explicitly transitional; binding them to the locator
means the eventual split of `canonical.py` is invisible to them.

The mapping used, all of it already declared in `_EXPORT_GROUPS`:

| Owner module | Symbols taken by the kernel |
| --- | --- |
| `contracts.attempts` | `AttemptContract` |
| `contracts.base` | `CanonicalContract`, `ContractProvenance`, `_artifact_locator`, `_egress_endpoint`, `_identifier`, `_locator_sha256`, `_record_payload`, `_repo_path`, `_require_provenance_inputs`, `_revision`, `_sha256`, `_sorted_strings`, `_utc_timestamp` |
| `contracts.evidence` | `EvidenceItem`, `EvidencePacket` |
| `contracts.policy` | `PolicyDecision` |
| `contracts.promotion` | `NominationReceipt` |
| `contracts.resources` | `EffectScope`, `ResourceBudget`, `ResourceUsage` |
| `contracts.runtime` | `RUNTIME_CONFORMANCE_CHECKS`, `ConformanceCheck`, `RuntimeConformanceReceipt`, `RuntimeManifest` |

**No symbol was orphaned and no module was created.** The eleven private
validators (`_sha256`, `_utc_timestamp`, `_artifact_locator`, `_locator_sha256`,
`_identifier`, `_revision`, `_repo_path`, `_record_payload`, `_egress_endpoint`,
`_sorted_strings`, `_require_provenance_inputs`) all have an owner already:
`daedalus/kernel/contracts/base.py` imports the full validator set from
`canonical` under the docstring "Base wire language and validators", and its
`__all__` deliberately lists only the three public names. `__all__` does not
gate an explicit `from … import`, so `base` is a real owner for the private
helpers rather than a place they merely pass through. G1-HIER-02 did not stop
short here.

**Boundary rule: both prefixes, for two different reasons.** `kernel-no-outer-
layers` gains `daedalus.schemas` and `daedalus.orchestration`.

- `daedalus.schemas` is the load-bearing one. It is the edge that actually
  existed, and it is a facade whose entire purpose is to serve three layers at
  once — it imports `daedalus.orchestration.legacy_reports` and
  `daedalus.runtimes.contracts.provider_report` beside the kernel contracts.
  A kernel module importing it imports the union of three layers. Forbidding
  the facade is what closes the measured leak.
- `daedalus.orchestration` closes a gap between the rule's own text and its
  enforcement. The rationale already said the kernel "cannot depend on
  verification, provider, **orchestration**, runtime, or product-domain
  implementations", but `daedalus.orchestration` was absent from the target
  list, so a direct kernel-to-orchestration import would have passed. No kernel
  module imports it today, so the addition is clean rather than aspirational.

Forbidding only `daedalus.orchestration` would have left the test green with
the leak live, because the checker reads direct import syntax and the leak was
transitive. Forbidding only `daedalus.schemas` would have closed today's leak
and left tomorrow's direct one unenforced. Neither prefix is redundant.

**What the static rule still cannot see.** `tools/architecture_boundaries.py`
matches direct import statements in tracked source. It is not a transitive
closure: a future kernel import of some third module that itself reaches
`daedalus.runtimes` would be invisible to it. That limitation is not repaired
here and is not claimed to be. The transitive instrument in this repository is
the cold-import test, which really imports and then reads `sys.modules`; it
covers `daedalus.kernel.offload_lease` and nothing else.

**Shim registry.** `daedalus.schemas` is now a registered facade with an owner
and removal criteria. It was the only compatibility facade of its class missing
from the registry while its structural siblings — `daedalus.orchestration.
legacy_reports`, `daedalus.providers.base`, `daedalus.kernel.attempts` — were
all listed. A boundary rule that forbids importing a facade should be readable
next to the row that says who owns that facade and when it retires.

**Line endings.** Twelve of the eighteen files are `-text` byte-pin subjects in
`.gitattributes`. The edit was applied to the committed blob bytes rather than
to the working copy, so no file received an incidental end-of-line rewrite;
`git diff --numstat` shows between one and five changed lines per file.

## Acceptance matrix

| # | Claim | Instrument | Base revision | After |
| --- | --- | --- | --- | --- |
| 1 | Cold kernel import loads no outer implementation | `tests/kernel/test_offload_lease_outer_ports.py` | 1 failed, 6 passed | 7 passed |
| 2 | Leaked module set is empty | `python -I -c "import daedalus.kernel.offload_lease"` + `sys.modules` | 11 outer + 2 orchestration + `daedalus.schemas` | `[]`, `[]`, `False` |
| 3 | Every moved symbol is the same object | identity probe over 25 symbols and 91 module bindings, then made permanent in `tests/kernel/test_contract_hierarchy.py` | n/a | 0 mismatches |
| 4 | Kernel, orchestration and contract suites | `pytest tests/kernel/ tests/orchestration/ tests/contracts/ tests/test_architecture_boundaries.py -q` | 4 failed, 879 passed | 3 failed, 989 passed |
| 4b | Kernel bindings hold the one contract object; `base` really owns the private validators | `tests/kernel/test_contract_hierarchy.py` (2 new parametrized tests, 102 cases) | 54 passed | 156 passed |
| 4c | Those two new tests can go red | one kernel module rebound to a wrapper; one validator removed from `base` | n/a | 31 failed, including the exact rebound case |
| 5 | Boundary contract green with the new rule | `pytest tests/test_architecture_boundaries.py -q` | 7 passed | 7 passed |
| 6 | The new rule can go red | two probe modules staged under `daedalus/kernel/` | n/a | FAIL, 2 new violations, one per added prefix |
| 7 | Effect boundary instruments | `pytest tests/test_effect_boundary.py tests/test_cli_effect_boundary.py tests/test_ikarus_os_boundary.py -q` | — | 103 passed |
| 8 | Gate profile does not regress | `tools/run_gate_checks.py g1` | 5 failed, 132 passed, 1 skipped | 5 failed, 132 passed, 1 skipped |
| 9 | Byte-pin end-of-line durability | `pytest tests/test_byte_pin_eol_durability.py -q` | — | 17 passed |
| 10 | Effect Registry digest unchanged | `test_check_is_read_only_and_effect_registry_digest_is_unchanged` | `ac020278…` | `ac020278…` |
| 11 | Import census re-measured, cycle structure unchanged | `tests/contracts/test_import_scc_hierarchy.py` | 1603 edges | 1618 edges; modules, component count, max size and digest all unchanged |
| 12 | Gate-1 bundle closure members are all EOL-declared | `tests/test_ignition_bundle_gitattributes.py` + `tests/test_byte_pin_eol_durability.py` | 8 passed / 17 passed | 2 failed on 5 undeclared closure members, then 25 passed after the `.gitattributes` repair |
| 13 | Full suite, `tests/` only | `pytest -q` | 19 failed (inherited, not measured by me) | 18 failed (21 total, 3 of them under `experiments/`) |

Row 13 carries the one number in this matrix I did not establish end to end
myself: the 19-failure `tests/` baseline is INHERITED from the instruction that
opened this packet. What I measured is the after-state and, for the twelve
files carrying every non-obvious failure, an isolated baseline at `aeef64bf`.

## Migration and rollback

There is no data migration, no schema change, no wire-format change and no
persisted-state change. The change is which module name each `from … import`
statement spells; the objects bound are identical, so no producer, consumer,
receipt, ledger row or digest is affected.

Rollback is `git revert` of the single commit. Because `daedalus/schemas.py`
was never modified, a revert restores the previous imports without any ordering
constraint against other packets, and the facade continues to serve its
remaining callers either way. The two boundary-contract prefixes and the shim
row revert with it; nothing outside the repository depends on them.

The forward direction has one ordering obligation for later packets: any packet
that adds a kernel module must take its contracts from
`daedalus.kernel.contracts.<owner>`. That obligation is now mechanical rather
than advisory — `kernel-no-outer-layers` fails the build on the facade import,
with `baseline: []` and no allowlist row available.

## Evidence expected failures and review

### Measured, in this worktree, at `aeef64bfb3a2cbb1bbafa38f6d0a1462c2b9e794`

All runs used `.venv/Scripts/python.exe -m pytest`. Bare `pytest` on this host
resolves to a foreign Python 3.10 installation that runs and reports success
against an environment nobody selected; bare `python` is a different
interpreter again.

- `tests/kernel/test_offload_lease_outer_ports.py`: 1 failed / 6 passed before,
  7 passed after.
- `tests/kernel/ tests/orchestration/ tests/contracts/ tests/test_architecture_boundaries.py`:
  4 failed / 879 passed before, 3 failed / 989 passed after. The passed count
  rises by more than the one repaired test because this packet adds 102
  parametrized identity cases to `tests/kernel/test_contract_hierarchy.py` and
  the selection gained `tests/test_architecture_boundaries.py`.
- `tests/kernel/test_contract_hierarchy.py`: 54 passed before, 156 passed
  after. Red-proofed twice. Probe one rebound
  `daedalus.kernel.attempt_clock._utc_timestamp` to a wrapper: 1 failed / 155
  passed, the failure being exactly
  `test_kernel_modules_bind_the_one_contract_object[daedalus.kernel.attempt_clock-_utc_timestamp]`.
  Probe two additionally deleted `_egress_endpoint` from
  `daedalus/kernel/contracts/base.py`: 31 failed / 125 passed. The 31 is
  probe one's single failure plus 30 from probe two, which cascades through
  every module whose import chain reaches `daedalus/kernel/effects.py`. An
  independent reviewer running probe two alone measured 30 / 126 and reported
  the 31 as unreproducible; both numbers are correct and the difference is
  that the two probes were live together here. This document previously stated
  the 31 without saying that, which made it unreproducible as written.
  Both probes were removed and the file returned to 156 passed.
- `tests/test_effect_boundary.py tests/test_cli_effect_boundary.py
  tests/test_ikarus_os_boundary.py`: 103 passed, exit 0.
- `tests/gates/ tests/runtimes/ tests/test_kernel_contracts_have_producers.py
  tests/test_spine_writer_inventory.py tests/test_write_surface_coverage.py
  tests/test_wave_spend_reservation.py
  tests/test_wave_spend_reservation_concurrency.py tests/test_loop_lease.py`:
  1967 passed, 75 skipped, exit 0.
- `tools/run_gate_checks.py g1`: 5 failed / 132 passed / 1 skipped, before and
  after, identically.
- `tests/test_ignition_bundle_gitattributes.py tests/test_byte_pin_eol_durability.py`:
  25 passed, after the `.gitattributes` repair described below.
- Full suite, `pytest -q` from the worktree root, run twice.
  - Before the `.gitattributes` repair, 44m05s: 23 failed / 10613 passed /
    276 skipped / 9 xfailed. Three of the 23 are under `experiments/` and
    outside the `tests/` count this packet is judged on, leaving 20 — two of
    them introduced here.
  - After the repair, 51m03s: **21 failed** / 10615 passed / 276 skipped /
    9 xfailed. The same three `experiments/` failures, leaving **18 under
    `tests/`** — the expected 19 → 18, with the one repaired test accounting
    for the whole difference and no new failure anywhere.

### One regression this packet introduced, and the guard that caught it

`tests/test_ignition_bundle_gitattributes.py` recomputes the Gate-1 evaluator
bundle's transitive import closure from source on every run. Pointing the
kernel at `daedalus.kernel.contracts.{base,evidence,policy,promotion,resources}`
pulled those five modules into that closure for the first time, and none of
them carried the explicit `-text` declaration the D7 section of
`.gitattributes` requires of every closure member. Two tests went red:
`test_every_bundle_file_has_a_filter_stable_declaration` and
`test_the_gitattributes_pin_is_an_explicit_list_not_a_wildcard`, both naming
the same five files.

This is exactly the recurrence that `.gitattributes` section predicts in
prose — "every new member arrives unlisted" — and it was caught by the
mechanical guard, not by review. The fix is the one the guard's own docstring
prescribes: five explicit `<path> -text` lines, no wildcard. The section's
count moves 46 → 51 although no file was added.

The five files were CRLF in this worktree over LF-committed blobs. `-text`
disables the conversion that had been hiding that, so their working copies
were normalized to their blob bytes in the same change; otherwise the next
`git add` to touch one of them would have silently committed CRLF, which is
the "CRLF daemon" the D7 header describes. `git diff HEAD` shows no content
change for the five — only `.gitattributes` moves.

Baseline discipline for this claim: the twelve test files carrying every
non-obvious full-suite failure were re-run against `aeef64bf` materialized
into an isolated `git archive` copy, giving 13 failed / 208 passed. The same
twelve on this branch gave 14 before the `.gitattributes` repair. That
one-failure delta — two test cases in one file — is how the regression was
attributed to this packet rather than assumed away.

### Expected failures, named separately

The gate profile is deliberately red at this base revision. Commit `aeef64bf`
put `tests/test_registry_new_doors.py` (3) and
`tests/test_registry_retired_rows.py` (2) into the `g1` profile precisely so
their redness is visible rather than unmeasured. Those five are not this
packet's, are not touched by it, and are unchanged by it. The gate is therefore
judged on the difference — same five names, `132 passed` not reduced — and not
on the exit code.

Three further failures pre-date this packet and survive it unchanged:

- `tests/kernel/test_runtime_terminal_capability.py` (2), `RuntimeTrustLedgerPort`.
- `tests/orchestration/test_run_mission.py::test_migrated_surfaces_delegate_without_a_second_execution_path`.

### Deliberate count movements

Three pinned numbers move because this packet moved them, each re-measured
rather than incremented:

- `tests/contracts/test_import_scc_hierarchy.py`: `CENSUS_EDGES` 1603 → 1618.
  No module was added or removed, so `CENSUS_MODULES` stays 433. The +15 is
  exactly the sum over the eighteen files of (distinct owner modules named − 1):
  a file that needs contracts from three owners now spends three edges where it
  spent one. Component count (12), maximum component size (18), the component
  digest and every membership assertion are unchanged — the cycle structure did
  not move, only the leaf-edge census.
- `tests/test_architecture_boundaries.py`: `shim_entry_count` 20 → 21, for the
  registered `daedalus.schemas` row.
- `docs/work-packets/index.json` and `tests/contracts/test_work_packet_index.py`:
  re-rendered and re-pinned for this document.

### The `registry_sha256` caveat

`ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec` is verified
unchanged, but it is cited narrowly. That digest hashes the eleven declaration
fields of the `ENTRYPOINTS` tuple and nothing about the code the `target`
strings point at. It is structurally incapable of noticing moved
implementation, so it is evidence that no registry row was edited — not
evidence that the effect surface is unchanged. The evidence for the latter is
the 1967-test targeted run and the identity proof.

### Retained negative evidence — refused shortcuts

- **Making `daedalus/schemas.py` lazy** would have turned the cold-import test
  green while leaving the orchestration and runtime dependency intact until
  first attribute access. The test would then be measuring import timing, not
  layering. Refused.
- **Replacing a module in `sys.modules`** to satisfy the cold import would have
  produced exactly the class of construct that has already blinded this
  repository's static registry derivation. Refused.
- **Adding a `baseline` row** to `import-boundaries.json` to make the new
  prefixes pass would be appending to an allowlist to go green. The contract
  carries `"baseline": []` and still does.
- **Importing everything from `daedalus.kernel.contracts.canonical`** would
  have been one edge per file instead of up to four, and a smaller census
  delta. Refused because it binds eighteen modules to the nucleus the split is
  meant to dissolve.

### Measured open items, not fixed here

- Five Sphinx cross-references still name the facade for symbols whose owner is
  now spelled in the import line: `daedalus/kernel/attempt_execution.py:2467`,
  `daedalus/kernel/contracts/security.py:3`,
  `daedalus/kernel/offload_lease.py:316` and `:1842`,
  `daedalus/kernel/promotion_execution.py:3`. They resolve — the facade does
  re-export those names — so they are imprecise, not false. Left alone
  deliberately: `daedalus/kernel/contracts/security.py` is the file another
  investigation is currently working in, and prose edits inside byte-pin
  subjects buy no acceptance here.
- The boundary checker remains non-transitive. The only transitive instrument
  covers one kernel module. Extending either is a separate packet with its own
  measurement, not a side effect of this one.
- 148 non-kernel files still import through `daedalus.schemas` — 58 under
  `daedalus/` and 90 under `tests/`, measured with
  `grep -rlE "^(from daedalus\.schemas import|import daedalus\.schemas)"
  --include="*.py" daedalus tests tools`, excluding the facade itself and
  `daedalus/kernel/`. An earlier draft of this document said "roughly
  eighty-five", a number inherited from a delegate's report and never
  measured; the independent review caught it. That is the exact failure mode
  this repository's rules name — an inference stamped as a measurement — and
  the corrected figure nearly doubles the blast radius the facade's removal
  criteria have to characterise.
- **The kernel still reaches orchestration and runtimes, one hop further out,
  and this packet does not close it.** `daedalus/kernel/fourfold_evidence.py:41`
  imports `daedalus.twin.contracts`, and four modules under `daedalus/twin/`
  import the facade by *relative* import (`from ..schemas import ...`):
  `contracts.py:20`, `_reference_claims.py:6`, `legacy_forest.py:14`,
  `reference_compiler.py:14`. A cold `import daedalus.kernel.fourfold_evidence`
  therefore still loads the same eleven `daedalus.runtimes` modules, both
  `daedalus.orchestration` modules and `daedalus.schemas` — measured, not
  inferred. This predates the packet (the `daedalus.twin` import is unchanged
  at `aeef64bf`) and is out of its declared scope, but it means the class of
  defect is closed for **one entrypoint**, not kernel-wide.
  `kernel-no-outer-layers` does not catch it because `daedalus.kernel` →
  `daedalus.twin` is a permitted direct edge and the leak is transitive. Adding
  `daedalus.twin` to the forbidden list would go red immediately and cannot be
  done without first repointing those four `daedalus/twin/` modules — which is
  the obvious next packet, and the reason this one does not add the prefix and
  does not baseline it.

### Review

- Independent review question 1: does any test depend on the *route* rather
  than the object? Swept — no `monkeypatch`/`mock.patch` target string mentions
  `daedalus.schemas`; the twelve patches aimed at these eighteen modules all
  target module-local names (`_utc_now`, `issue_effect_lease`,
  `acquire_wave_offload_lease`, `os.walk`). The legacy pickle test resolves
  through the untouched facade.
- Independent review question 2: can the new rule be satisfied vacuously?
  No — proven red by staging two probe modules under `daedalus/kernel/`, one
  per added prefix, and observing two new violations and a failing test before
  removing them.
- Independent review question 3: does the repoint create an import cycle?
  No — the nine owner modules import only `from .canonical import …`, and
  `canonical` reaches only `daedalus.kernel.policy.limits` and
  `daedalus.spine.envelope`, both stdlib-only leaves. The new edge set is a
  strict subset of what `daedalus.schemas` already pulled in. The SCC component
  digest is unchanged, which is the mechanical form of the same answer.
- No automatic merge, no promotion, no gate transition. This packet is a
  candidate for owner decision.
