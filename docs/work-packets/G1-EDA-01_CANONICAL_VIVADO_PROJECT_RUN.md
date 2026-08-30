# G1-EDA-01 - Canonical Vivado project run

Status: implementation packet; supplied-project canonical planning currently refuses safely
Classification: `ALIGNED`
Active gate: Gate 1 - renovation ignition slice
Base branch: `main`
Base revision: `98833bf71e53eec184a7db2a065aec1469a9b8c7`
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
   reports are not passes. The strict phase summary must match the exact
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
11. The supplied project can be inspected read-only: the CLI emits its manifest
    and returns nonzero to signal `complete=false`. Its current mutable
    `BoardPartRepoPaths` is semantically active and not content-addressed, so
    `plan` is expected to refuse; inspect-plus-plan end to end is not claimed
    accepted. A future canonical live rerun additionally requires a pinned
    board catalog, complete matching manifests, an operator-created policy and
    an already armed kill switch. This packet never changes `STOP` to `RUN`.

## Supplied-project evidence at 2026-08-30

The supplied `tdc_light_version.zip` has SHA-256
`2170893265CAE54678E217BA9777ADA278D826C02923A5D237082F7E251DD517`.
Read-only inspection of its XPR emits the full manifest, retains the refusal
reason, and returns nonzero for `complete=false`. The project declares a
per-user `BoardPartRepoPaths` into the mutable
Xilinx XHub board store while selecting the Arty A7-35 board. Board-flow data
changes Vivado semantics, so this value cannot be treated as relocation-only
metadata. Until the relevant catalog tree is pinned, closed and included in
Source Identity, a complete manifest cannot be proven and `plan` is expected
to refuse. The measured effect-free invocation exited with
`planned Vivado project manifest is incomplete: custom board repositories=1`;
Vivado was not started. Acceptance item 11 is therefore open by design, not
green.

The same manifest records
`system_microblaze_0_0.xci:bootloop_file=data/mb_bootloop_le.elf` as a
vendor-catalog resource value. Its transitive file bytes come from trusted
Vivado catalog state and are not claimed as hermetic source identity.

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
- no network or secret capability. A Vivado installation requiring license
  egress not already available locally is refused/deferred to another packet;
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
- one read-only inspect against the supplied project that emits the manifest
  and returns the expected incomplete status, plus the expected refusal at
  `plan` until a board catalog is pinned;
- an opt-in live synthesis/implementation bench only when the operator control
  plane permits it;
- build a fresh wheel, install it into a clean environment and verify that the
  packaged static Tcl bytes/digest and CLI surface match the checkout;
- independent exact-diff review after the focused suite is green;
- retain every negative result and distinguish builder evidence from independent
  review.

Iron Plan: **ALIGNED**
Iron Gate: **1**
Evidence: **required by the acceptance matrix; no promotion requested**
