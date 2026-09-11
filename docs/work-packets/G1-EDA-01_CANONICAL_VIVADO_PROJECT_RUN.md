# G1-EDA-01 - Canonical Vivado project run

Status: implementation packet; sanitized supplied-project static planning succeeds, canonical live execution remains operator-refused
Classification: `ALIGNED`
Active gate: Gate 1 - renovation ignition slice
Owner: repository owner
Base branch: `main`
Base revision: `98833bf71e53eec184a7db2a065aec1469a9b8c7`
Dependencies: scoped Gate-0 closure and the canonical Effect-Lease and Artifact
Store contracts present at the exact base revision
Base master-plan blob SHA-256 (raw bytes): `1EFD536FF28813B55F4E095125A1132B843AA51FE08513418DCD72516CBA9F88`
Reviewed working-tree master-plan SHA-256 (raw bytes, Revision 10): `5E269DE9857940CD1D6162EAF9236D4DB8E77427D189122DB178812B49B259DC`
Promotion: not requested

The base digest is reproducible from `git show <base>:<plan-path>` without
newline conversion. The reviewed digest records the later owner-amended plan
that governed implementation; the packet does not edit that plan or its
amendment chain.

## Purpose

Turn the existing dry-run-first `daedalus-chip` prototype into one bounded
Gate-1 vertical slice for an existing AMD Vivado project. The slice inventories
the authoritative project inputs, executes only static package-owned batch Tcl,
consumes the canonical non-runtime Effect-Lease authority before starting Vivado,
retains outputs in the existing content-addressed Artifact Store, and emits a
structured run receipt. It does not create a second event store, artifact
identity, policy system, graph authority, evaluator, or promotion path.

The motivating bench is the supplied `tdc_light_version` archive. Earlier
isolated evidence proved that Vivado 2025.1.1 can synthesize, implement, report
positive setup/hold slack under the declared constraint set, and emit a
bitstream. It also retained negative evidence: the original generic live CLI
bypassed the kernel,
the first report command failed after successful synthesis, the project
contains stale absolute generated-run paths, two OOC IP results were restored
from cache, and timing/methodology/CDC/testbench/AXI findings prevent a signoff
claim.

## Authority and invariant touched

This packet strengthens the existing Mission / Policy / Execution / Evidence
spine at one previously bypassing process boundary. Models and project scripts
do not authorize execution. The selected canonical Effect Lease, its concrete
guard decisions, the live kill switch, and the canonical registry do.

Sources and the project manifest remain authoritative input identity. Vivado
run directories, checkpoints, reports, and bitstreams are derived artifacts.
No derived forest/graph representation becomes candidate identity.
Source Identity `/3` binds authored input bytes, declared generated-output
roots, vendor-catalog resource declarations and semantic Vivado run
configuration (strategies, ordered steps, options and reports). It excludes
relocation/run activity and compiler products below declared generated/cache/
run roots; the exact workspace manifest binds those bytes separately.
Inputs that cannot yet be transitively content-bound remain visible in
read-only inspection but make the manifest incomplete and prevent planning or
execution.

## In-scope paths

- `daedalus/chip_design/**`
- `daedalus/spine/effect_boundary.py`
- `daedalus/kernel/contracts.py`
- `daedalus/kernel/effects.py`
- `daedalus/kernel/offload_lease.py`
- `pyproject.toml` (package the static trusted Tcl resource)
- `tests/test_chip_design.py`
- focused new chip/effect tests under `tests/`, including the generic optional
  operation-digest compatibility and authority-confined policy resolver
- `docs/chip-design/**`
- `tools/docs_reference_check.py` (only the two documented operator-owned EDA
  policy-path classifications)
- this Work Packet

No other production path is in scope. If a required fix crosses that boundary,
the packet stops for a new packet rather than expanding silently.

## Acceptance matrix

1. `scan` recognizes `.xpr`, `.bd` and `.xci` distinctly from generated run
   output. The XPR manifest additionally detects and refuses opaque `.xcix`/
   `.xco` references. One bounded XPR manifest binds project bytes, target
   part/board/top, FileSets, ordered direct inputs, in-root BD/XCI dependency
   trees, exact generated/cache/run-product bytes and semantic project/fileset/
   file/run configuration. Authored Source Identity `/3` excludes documented
   relocation/activity state and compiler products below declared output roots,
   while the exact manifest retains those product bytes. Custom IP/board repositories,
   include-directory roots, path-bearing run arguments, FileSet/BD/XCI path
   escapes, unsafe `DefaultLaunch`/run/`GeneratedRun` paths, links/junctions,
   missing or unbound dependency members, Verilog include directives and
   `$readmemh`/`$readmemb`, VHDL TextIO file input and opaque core
   containers make the manifest incomplete and fail closed for `plan`/`run`.
2. Vivado synthesis/implementation uses the static packaged
   `daedalus/chip_design/tcl/vivado_project_flow.tcl`; no temporary or
   project-selected Tcl becomes the flow authority. Active automation ending
   in `.tcl`, `.bat`, `.cmd`, `.exe` or `.ps1`, every active
   `FILE_TYPE=Tcl`, custom IP/board/include repositories, path-bearing run
   overrides, opaque core containers and non-vendor IP definitions are
   refused or rechecked before launch. Declared `.xdc` is executable,
   operator-trusted constraint Tcl and explicitly not a security boundary.
   User values travel as separate Tcl argv items, and selected paths plus
   project, FileSet, default-launch, run and IP-output roots remain
   workspace-confined. Selected synthesis/implementation runs require concrete
   workspace-local `DIRECTORY` values, and derived outputs must be proper
   descendants of the dedicated workspace `.daedalus-chip/` namespace.
3. Every live chip process consumes an injected
   `NonRuntimeEffectAuthorization` and exact `EffectExecutionRequest`; durable
   `STARTED` precedes constructor/spawn. A safely proven pre-spawn failure may
   terminalize. Once `STARTED`, an ambiguous `ManagedProcess` constructor or
   spawn exception, `KeyboardInterrupt`, `SystemExit` or other outcome where
   child existence cannot be disproved stays `STARTED` for explicit
   reconciliation. Known completed outcomes receive one terminal receipt;
   terminal replay is inert and ambiguous work is never silently retried or
   relabelled failed.
4. The externally reachable chip entrypoint has exactly one central registry
   owner. It declares the actual filesystem-write, process-spawn, and
   process-control effects and requires executable process-budget,
   write-policy, and containment decisions. The executor cannot mint its own
   lease or policy.
5. The CLI's explicit live composition uses the existing canonical lease
   issuer and operator control root. `run` requires a stable operator-supplied
   `--attempt-id` and exactly one `--writable-path .`. `--write-policy` must
   resolve inside that root and contain a non-empty, confining `write_allow`;
   the explicit whole-workspace example is
   `{"policy":{"write_allow":["."]}}`. A stopped/missing kill switch,
   outside/missing/malformed/unconfined/denying policy, denied write path,
   missing authority, or failed containment refuses before process spawn.
   Planning and read-only inspection remain effect-free.
   Source/workspace/authority roots are pairwise disjoint. The CLI's
   `--source-revision` is exactly the authority checkout's lowercase 40-hex
   Git HEAD, distinct from the design manifest and Source Identity `/3`
   SHA-256 values (64 hex).
6. Timeout, revocation and cancellation reap the managed process tree.
   Authority and kill-switch readability/state are rechecked continuously
   while it runs. Execution uses argv with `shell=False`; no shell command
   string or refused archive automation is launched.
   Write-policy/containment decisions are admission evidence, not an OS
   filesystem or network boundary around Vivado.
7. Console logs, native reports, checkpoints, and bitstreams are hashed and
   retained with provenance through the existing `ArtifactStore`. The
   canonical chip-run receipt binds the input manifest, trusted Tcl template,
   tool/version, phase, effect start/terminal receipts, native artifacts,
   parsed metrics and explicit `not_run` dimensions. Before execution, an
   exact `EdaExecutionPlan` digest binds argv, cwd, declared artifacts,
   Artifact Store/CAS root, timeout, sanitized environment, source/workspace
   manifests and trusted Tcl. It also byte-binds the standard Vivado launcher
   and, on Windows, the resolved system `cmd.exe`. Transitive Vivado binaries,
   device data and built-in catalogs remain declared vendor-installation
   trust; launcher hashing is not called a hermetic toolchain. Declared output
   hashing requires stable regular-file identity/size/mtime before and after
   the opened-handle read; mutation becomes reconciliation evidence. Every
   spawned phase also retains an exact post-run workspace manifest. Success
   requires that manifest to be complete with unchanged authored Source
   Identity `/3`; product changes may alter the exact manifest SHA-256.
8. Parsers distinguish missing/unparseable reports from zero violations.
   Timing, utilization, DRC, methodology, routing, message counts, and artifact
   identity are exposed when present. DRC/methodology passes require
   `checks_found=0` and zero counts at every retained severity; warning-only
   reports are not passes. Console artifact binding requires a parsed
   cumulative Vivado summary with zero critical warnings and zero errors. The
   strict phase summary must match the exact
   phase/project/part/top/runs, parseable Vivado version, phase-specific
   cache/generation and completion facts. Timing prose must agree with numeric
   setup/hold/pulse, total-negative-slack and failing-endpoint values. Process
   success alone cannot produce a signoff verdict.
9. Vivado discovery accepts a parseable official version banner even when the
   Windows launcher returns 1, while retaining the nonzero probe code as a
   warning. An unparseable nonzero probe remains unavailable.
10. Windows long-path versus 8.3 spelling, spaces/special characters, path
    escape, launcher/interpreter tamper, missing tool, failed tool, timeout,
    interrupt, replay, safe pre-spawn refusal, ambiguous spawn, artifact
    mutation and report-absence/summary-timing disagreement are executable
    tests.
11. The untouched supplied project can be inspected read-only: the CLI emits
    its manifest and returns nonzero to signal `complete=false`. The original
    XPR inside the supplied ZIP and the later Vivado-rewritten working XPR are
    separate byte identities. Inspection of the current working XPR has
    exactly three active refusal classes: its mutable `BoardPartRepoPaths`, the
    non-empty `impl_1` run override `LaunchOptions=-jobs 4`, and the active
    checkpoint
    `tdc_light_version.srcs/utils_1/imports/synth_1/system_wrapper.dcp`.
    Historical `ImportPath` attributes remain visible provenance but are not
    followed and are not a fourth active refusal when the corresponding
    current `File Path` resolves inside the project. That negative original/
    working-project result is retained. A separate non-destructive sanitized
    derivation removes those active inputs only in its copied trees; its
    authoritative source and disjoint workspace inspect as complete with
    identical manifest and Source Identity `/3` digests, and static `full`
    planning succeeds for synthesis plus implementation. A canonical live run
    additionally requires the operator-created policy and an already armed
    kill switch. The measured live preflight refused while `STOP` was active
    and the policy was absent; this packet never changes `STOP` to `RUN`.

## Supplied-project evidence at 2026-08-30

The supplied `tdc_light_version.zip` has SHA-256
`2170893265CAE54678E217BA9777ADA278D826C02923A5D237082F7E251DD517`.
Inside that immutable archive, entry
`tdc_light_version/tdc_light_version.xpr` has size 69,273 bytes and SHA-256
`17E03D70D41990130258CF5DA111A9C0259508E8068170CABEAAC510187C5977`.
That is the original uploaded XPR identity. It records Vivado 2025.1,
`impl_1 LaunchOptions=-jobs 14`, and `synth_1` with automatic incremental
checkpoint reuse enabled against `utils_1/imports/synth_1/system_wrapper.dcp`.

The XPR inspected in the later working extraction is not byte-identical: it
has size 68,712 bytes and SHA-256
`DEF8FC6B833B5C0A962BD497FF3116A01E598FCB90140E37DA9B2CB8D2A367A4`.
It records Vivado 2025.1.1, `impl_1 LaunchOptions=-jobs 4` and disabled
automatic incremental reuse, although the DCP remains an active project file.
Vivado had rewritten that working project, so observations of this file and
the historical run below must not be attributed to the untouched ZIP entry.
Read-only inspection emits the full manifest and returns nonzero for
`complete=false` with exactly these three active refusal classes:

1. `BoardPartRepoPaths` points into the mutable per-user Xilinx XHub board
   store while the project selects the Arty A7-35 board;
2. `impl_1` has the non-empty run override `LaunchOptions=-jobs 4`; and
3. `tdc_light_version.srcs/utils_1/imports/synth_1/system_wrapper.dcp` is an
   active DCP input in `utils_1`.

Board-flow data changes Vivado semantics, a project-selected launch override is
outside the frozen argv contract, and an active checkpoint can carry compiled
design state. None can be normalized away. Historical absolute `ImportPath`
attributes are retained as provenance only: Daedalus does not follow them, and
they are not an additional active refusal when the current project-relative
`File Path` is present. That original/later-working negative result remains
open by design. Acceptance item 11's sanitized static portion is green; its
canonical live portion remains operator-blocked, and Vivado was not started by
the canonical path.

The same manifest records
`system_microblaze_0_0.xci:bootloop_file=data/mb_bootloop_le.elf` as a
vendor-catalog resource value. Its transitive file bytes come from trusted
Vivado catalog state and are not claimed as hermetic source identity.

### Non-destructive sanitized derivation and static preflight

The ZIP and its exact fresh extraction remain preserved at their recorded byte
identities. A separate authoritative derivation was created at
`C:\daedalus_eda\tdc_daedalus_source_21708932`, with an independently writable,
disjoint execution copy at
`C:\daedalus_eda\tdc_daedalus_workspace_21708932`. Only the project XPR and the
`tdc_light_version.srcs` and `tdc_light_version.gen` trees were copied from the
fresh extraction. Historical `cache`, `runs`, `ip_user_files` and XSA products
were not carried into either derived root.

The derived XPR deliberately removes `BoardPart` and the mutable
`BoardPartRepoPaths` while retaining exact part `xc7a35ticsg324-1L` and the
unchanged declared XDC bytes. It removes the active `utils_1` reference to
`imports/synth_1/system_wrapper.dcp` and that one physical checkpoint only from
the derived copies, disables `synth_1` incremental checkpoint reuse, and
removes the `impl_1 LaunchOptions` override. Other generated content under
`.gen` remains visible to the manifest and its vendor-TCB limitations. The
sanitized XPR SHA-256 is
`69ED07B6AA5E1DA051DA314F6289BC1A6FFFD3BEC39B010060DE09F085C02155`.

Read-only inspection of both derived roots returned `complete=true`, no active
refusal, identical manifest SHA-256
`46df6acdded3791436a2c094b407ee111402d55f1c5dbc9cac640e26acd31a1d`, and
identical Source Identity `/3`
`842a21fc7be9aac430e9c22c9a594e28af992bf47107c8878aec8e7c670c2601`.
Static `plan --phase full` succeeded and produced the expected ordered
`synth, impl` steps. Package-known numeric release selection chose Vivado
2025.1.1 and Vitis 2025.1.1 on this host; Vitis remains discovery-only in this
Gate-1 slice.

The effectful run preflight was then exercised without changing operator
authority. It refused at the active `STOP` state while
`.agentenv/chip-eda-policy.json` was absent, before any admitted Vivado project
process, output-root creation or source/workspace mutation. No canonical
synthesis or implementation was executed from this derivation, so this is
static Daedalus readiness evidence, not timing, implementation, bitstream,
software, hardware or FPGA signoff.

The operator state was independently checked: the control file contained
`STOP`, and `.agentenv/chip-eda-policy.json` was absent. The packet neither
created that policy nor armed the switch. No canonical live TDC process was
started.

A separate isolated Vivado 2025.1.1 run is retained as historical feasibility
evidence under classification `EXPERIMENT`. For `xc7a35ticsg324-1L`, board
Arty A7-35 and top `system_wrapper`,
implementation completed in 181.424 s, reported WNS 0.162 ns and WHS 0.021 ns,
zero DRC errors, and routed 12,337 of 12,337 connections. The bitstream SHA-256
was `432D717654C3C0F8B1C88368875A232959AC23D78286ACA504529145559D179E`.
That run restored two OOC results from cache and predated this canonical
effect/source-closure path. It is explicitly non-clean-room and does not prove
the new runner. Retained negative evidence includes an AXI-Lite behavior bug,
a testbench mismatch, DRC/methodology warnings and critical timing-methodology
findings, unknown CDC status, missing IO-delay coverage, and absent simulation,
formal, Vitis and hardware-in-the-loop evidence.

The retained read-only functional audit makes those limits concrete. The
AXI-Lite slave remembers independent address/data handshakes without latching
`WDATA` or `WSTRB`, can acknowledge a W-before-AW transaction without applying
the write, and ignores byte strobes. The frontend testbench binds nonexistent
port `start_pulse` instead of `start_pulse_axi`, sequences test mode before its
stimulus completes, and has no assertions, scoreboard or timeout; the archived
relaxed XSim log recorded no AXIS or status events. The active XDC carries
hierarchy-specific false paths, zero input-delay assumptions, a questionable
asynchronous grouping between related MMCM clocks and broad `ASYNC_REG` false
paths; Vivado retained 100 warning occurrences before suppressing further
instances, so their true total is unknown. The `FRAME_HITS=10` ring holds only
nine pending values and silently drops overflow, while pulse-width, reset and
CDC timestamp semantics remain unproved. Both retained XSAs contain the same
HDL and only vendor bootloop software, not an authored Vitis application or
BSP workspace. These findings are negative evidence, not G1-EDA-01 passes.
Repair requires a new immutable TDC candidate and separate Work Packet; this
packet does not mutate the sanitized source identity to hide them.

## Explicit non-goals and refusal boundaries

- no FPGA programming or hardware-in-the-loop action;
- no automatic merge, promotion, or owner-approval substitution;
- no execution of active project/archive automation ending in `.tcl`, `.bat`,
  `.cmd`, `.exe` or `.ps1`; declared `.xdc` constraints are the explicit,
  operator-trusted executable-Tcl exception and are not a security boundary;
- no live admission of custom IP/board/include repositories, path-bearing run
  inputs, source/dependency-root escapes, transitive Verilog/VHDL file input or
  opaque core containers until their complete inputs can be content-bound;
- no claim of clean-room IP regeneration when cached OOC IP was used;
- no Vitis/XSCT/v++ application run from XSA alone;
- no implicit pass for simulation, formal, CDC/RDC, equivalence, power,
  testbench quality, AXI protocol behavior, or signoff;
- no kernel-level network or secret capability is requested by this lease.
  That authorization fact is not proof of OS-enforced offline, no-egress or
  no-secret operation: Vivado, trusted XDC and vendor-generated components run
  with ambient host access left available by the operating system. A license
  or other egress requirement is therefore neither contained nor disproved by
  this packet;
- no claim that a Python guard or sanitized child environment is an
  operating-system or network sandbox. The receipt must keep
  `security_boundary_claimed=false`;
- no claim that byte-binding `vivado.bat` and system `cmd.exe` content-addresses
  the transitive Vivado installation, device database or vendor catalogs;
- no claim that source/workspace disjointness or Python/Tcl rechecks provide an
  OS filesystem lock. The operator must keep the workspace single-writer; an
  unrelated concurrent writer can race Vivado and invalidates the evidence.

## Required verification

- reproduce the current chip-test and conformance failures before edits;
- focused unit/adversarial tests for manifest, Tcl, reports, execution lifecycle,
  exact-plan tamper, terminal/pending replay, continuous authority revocation,
  operator policy absence/malformed/unconfined/denial, registry/issuer, CLI
  refusal, guarded-boundary workspace mutation, stable artifact reads, status
  probing, and Windows path normalization;
- canonical effect-inventory/conformance and repository write-inventory tests;
- compile-all and affected integration tests;
- one read-only inspect against the untouched/later-working supplied project
  that emits the manifest and retains the expected incomplete/refusal result,
  plus matching complete inspections and a successful static full plan against
  the separate sanitized authoritative source and disjoint workspace;
- an opt-in live synthesis/implementation bench only when the operator control
  plane permits it;
- build a fresh wheel, install it into a clean environment and verify that the
  packaged static Tcl bytes/digest and CLI surface match the checkout;
- independent exact-diff review after the focused suite is green;
- retain every negative result and distinguish builder evidence from independent
  review.

## Contract and recovery verification at 2026-08-30

The final frozen package snapshot passed the complete focused EDA, kernel,
effect-boundary, CLI and recovery selection with `330 passed, 5 skipped` in
100.48 seconds under CPython 3.10.11. The exact selection was:

```powershell
py -3.10 -m pytest -p no:cacheprovider `
  tests/test_chip_execution_plan.py tests/test_chip_eda_executor.py `
  tests/test_chip_vivado_contracts.py tests/test_chip_cli_canonical.py `
  tests/test_chip_contracts.py tests/test_chip_toolchains.py `
  tests/kernel/test_effect_leases.py `
  tests/kernel/test_chip_eda_effect_boundary.py `
  tests/kernel/test_effect_lease_issuer_rule.py `
  tests/kernel/test_lease_authority_subject_split.py `
  tests/test_chip_design.py `
  tests/gates/test_chip_repository_write_inventory.py `
  tests/gates/test_repository_head_revision.py -q --tb=short
```

The publication-adapter fingerprint was identical before and after that run:
`d6ab5fbe72a8c53320e3a5fab964e697d0fff6f4a82cc1d77d2851a5f152dfda`.
It is the canonical identity of the on-disk Daedalus package Python inventory
plus its declared Python/platform fields. It does not prove that those bytes
equal Python modules already loaded in memory, that the checkout is clean, or
that the inventory belongs to the authority Git commit. Syntax compilation
and the EDA-scoped diff check were also clean.

Create and restart now consume the same strict publication-graph verifier. It
reconstructs the raw execution receipt from the durable ledger and canonical
Artifact Store, binds the exact plan, lifecycle, runtime, mission, attempt and
policy contracts, requires the complete manifest/Tcl/console/native-output
role inventory, and keeps the Evidence Packet `inconclusive` with an
`unverified` item. Adversarial tests retain the negative evidence: claim
inflation, a missing trusted-Tcl role, an incomplete raw receipt, non-canonical
Runtime/Mission/Attempt contracts, altered Evidence provenance, renamed native
outputs and a console summary with critical warnings are all refused before a
discoverable publication index is written. The real CLI
integration test proves create, inert restart and authority/CAS-only index
rebuild without constructing a second process.

The pre-handoff shared-working-tree distributable is
`daedalus-0.1.3-py3-none-any.whl`, 2,356,260
bytes, SHA-256
`E2FD6DF89BFDB88281482D7DB8146BFA5AD349F9B8463A5A40A44B8D5F2F3396`.
The matching source distribution is 3,388,477 bytes, SHA-256
`0FDC57AFE536B9D2F5A65ADB15FBFC2BE5B338F7706DEDC9FD31AE80FCA20B32`.
Independent archive inspection found all 337 checkout Python files with no
missing, extra or mismatched Python bytes, exact packaged Tcl SHA-256
`A195A313B106E2E6B43B0EC9C1627C1240455F0CB0DC483CBB1E9A1ECED9495F`,
and a valid `daedalus-chip` entry point. No-index/no-dependency installs into
fresh external CPython 3.10.11 and 3.11.15 environments passed isolated
imports, execution-plan schema `daedalus.chip-eda-execution-plan/5`, Tcl checks
and `daedalus-chip --help` with exit 0. Their adapter fingerprints were
respectively
`d6ab5fbe72a8c53320e3a5fab964e697d0fff6f4a82cc1d77d2851a5f152dfda`
and
`545fff73ccfde2ab1198f77558231b2f4e2b7b1825330bc5226096509919742b`.
Older 0.1.1
artifacts remain retained in `dist` as history; they are not the current build.

This is contract, recovery and boundary evidence, not a Vivado or FPGA
signoff. No new live Vivado process, hardware programming action, promotion or
Gate transition was performed for this verification.

For a future admitted synthesis phase, the packaged Tcl resets and generates
XCI/BD targets, then re-enumerates and validates the expanded active graph with
`get_files -quiet` in that same Vivado process before launch. Vendor-generated
HDL and other output products are derived same-process inputs; this recheck
does not make their generator, device data or built-in catalog independently
verified or pre-run content-addressed. The query is not advertised as an
inventory of every generator-internal support file. Those unenumerated inputs
and the generator remain explicit vendor TCB.

## Isolated candidate handoff at 2026-08-30

The safe shared-tree audit was transferred without unrelated changes into
branch `codex/g1-eda-handoff-20260830`, based exactly on
`2a2f7d8748b0fb62fb72b53d1bac6bcd264499fb`. Companion commit
`99ac4afa743f46e376d2c9072c085e32e39429e1` contains only G1-EDA-02's
five paths. Commit `5479c193097de747ee4de84bb6bf7fb3f05ad6fd` contains only
G1-EDA-01's 20 paths, including the formerly untracked
`publication.py` and `test_chip_toolchains.py`. The combined diff contains
exactly 25 paths, passes `git diff --check`, has no staged/untracked rows, and
every committed blob equals Git's filtered identity for the audited source
snapshot. This is an exact candidate handoff, not a merge or promotion.

On commit `5479c193097de747ee4de84bb6bf7fb3f05ad6fd`, the frozen 13-file
selection passed under every installed supported interpreter:

- CPython 3.10.11: `330 passed, 5 skipped` in 99.34 seconds;
- CPython 3.11.15: `330 passed, 5 skipped` in 100.34 seconds;
- CPython 3.12.13: `330 passed, 5 skipped` in 105.97 seconds; and
- CPython 3.13.5: `330 passed, 5 skipped` in 103.14 seconds.

All 337 package Python files compiled under the same four interpreters.
Documentation-reference verification scanned and listed 643 files with no
current or authority errors. Read-only inspection of both sanitized roots
again returned manifest
`46df6acdded3791436a2c094b407ee111402d55f1c5dbc9cac640e26acd31a1d`
and Source Identity `/3`
`842a21fc7be9aac430e9c22c9a594e28af992bf47107c8878aec8e7c670c2601`.
Both static full plans returned ordered `synth, impl` steps with 19 argv values
each and created no output root.

An initial offline/no-isolation build with the system CPython 3.10 environment
retained its successful sdist but could not build a wheel because that
environment lacked the dynamic `wheel` backend command. The clean retry used
CPython 3.11.15 with setuptools 79.0.1 and wheel 0.45.1, stayed offline, and
produced:

- wheel: 2,354,517 bytes, SHA-256
  `A8CADED1919E797003FB55A97512BCD0DB78F2A40F88B49E68746447F86DB362`;
- sdist: 3,380,240 bytes, SHA-256
  `E6BC62FA64F68ECC192909F4A599522FC3A5530AE3CE912C96298685AAA747F0`.

Archive verification found all 337 checkout Python files byte-exact in both
artifacts, 345 valid wheel/RECORD rows, the toolchain test in the sdist, and no
missing, extra or mismatched package Python file. The clean Windows checkout's
packaged Tcl SHA-256 is
`84B3C406A6CACAAD8E849184DA1C4CDA81B6B537298A9748357F1CE33F922E8F`;
it is Tcl-complete and differs from the earlier shared-tree LF artifact because
this host materializes unpinned text resources through `core.autocrlf=true`.
The execution plan and both archives bind the actual clean-checkout bytes; the
two package artifacts are therefore not conflated.

Fresh external CPython 3.10.11 and 3.11.15 virtual environments installed the
new wheel with `--no-index --no-deps`. Isolated imports reported version 0.1.3,
execution-plan schema `daedalus.chip-eda-execution-plan/5`, the same packaged
Tcl digest and package-local module paths; `daedalus-chip --help` exited zero.
Their publication-adapter identities were respectively
`04380603bd8459ab305f02f707a0c5df6e49a1db2d22d19449d8b4bb37e1438c`
and
`f1a8de41e1e234ca4f8e9d6fee5e69a83856ecacd57c1db156d10251922358c0`.

The remaining G1 acceptance item is still the operator-authorized canonical
Vivado synthesis/implementation run. The candidate handoff does not arm the
kill switch, create policy, trust XDC on the operator's behalf, or reinterpret
Vitis, HIL, simulation, formal, CDC/RDC, equivalence, power or signoff as run.

Iron Plan: **ALIGNED**
Iron Gate: **1**
Evidence: **required by the acceptance matrix; no promotion requested**
