# Chip Design Toolchains

Daedalus should choose EDA tools by workflow role, not by brand. The initial
registry therefore records capabilities such as lint, simulation, synthesis,
formal, physical design and Tcl rather than pretending one tool covers every
stage equally well.

## Recommended role map

| Role | Useful tools | Daedalus use |
| --- | --- | --- |
| RTL/project inventory | built-in `chip_design.sources` and `chip_design.manifest` | classify RTL/constraints, distinguish XPR/BD/XCI, and bind an existing Vivado project without starting a tool |
| SystemVerilog style/parser tooling | Verible | cheap style/syntax feedback, formatting ecosystem |
| Strong SystemVerilog front end | Surelog/UHDM | future richer parsing/elaboration metadata for complex SV designs |
| Verilog/SystemVerilog lint/compile | Verilator | fast deterministic `--lint-only -Wall`; simulation/compiled models when needed |
| Verilog simulation | Icarus Verilog | lightweight open simulator |
| VHDL compile/simulation | GHDL | open VHDL analysis/elaboration/simulation |
| Cross-simulator Python verification | cocotb | self-checking Python tests over supported HDL simulators |
| Open synthesis | Yosys | RTL synthesis and formal front-end roles; Tcl script mode available |
| Open formal orchestration | SymbiYosys | property checking around Yosys + solver backends |
| Open ASIC physical design | OpenROAD | Tcl-controlled physical implementation and timing-oriented flow stages |
| Open RTL-to-GDS composition | OpenLane 2 | composes Yosys/OpenROAD/KLayout and related steps into broader flows |
| AMD/Xilinx FPGA | Vivado | admitted existing-XPR inspection, synthesis, implementation, native reports and bitstream through static packaged Tcl |
| Intel/Altera FPGA | Quartus Prime | analysis/synthesis, fitter, TimeQuest, programming files; Tcl automation |

This table is a workflow map, not an instruction to install every tool on every
machine. `daedalus-chip status` performs effect-free executable discovery.
Version probing is a distinct admitted observation; discovery alone does not
claim that a launcher ran successfully.

## RTL source intelligence

The dedicated hardware scanner recognizes:

```text
.v          Verilog RTL
.sv         SystemVerilog RTL
.vh/.svh    Verilog/SystemVerilog headers
.vhd/.vhdl  VHDL RTL
.xdc        Xilinx design/timing constraints; executable Tcl when admitted by Vivado
.sdc        Synopsys Design Constraints / timing constraints
.qsf        Quartus settings/assignments
.xpr        Vivado project XML
.bd         Vivado block-design source
.xci        Vivado IP configuration source
.tcl        EDA automation; inventoried but refused as active project automation in G1
.do         simulator automation (classified, not executed by the Tcl command)
.sby        formal flow configuration
.f          source filelist
```

The XPR manifest additionally detects `.xcix`/`.xco` core-container
references and refuses them as opaque inputs in Gate 1; that refusal is not a
claim that the generic source scanner classifies those formats.

This is deliberately separate from the existing generic StructCore language
registry for the first slice. The next integration step should teach StructCore
about RTL/Tcl semantics so Daedalus context selection, clone analysis and
structural maps can understand hardware repositories directly.

The current `tree-sitter-language-pack` project contains grammars for Verilog,
SystemVerilog, VHDL and Tcl, making it a practical candidate for that
integration. For SystemVerilog projects requiring richer preprocessing,
parsing/elaboration and standardized design representation, Surelog/UHDM is a
stronger future front-end candidate than relying on syntax trees alone.

## Verible versus Verilator

These tools overlap but are not interchangeable.

### Verible

Good early use:

- SystemVerilog syntax/parser tooling;
- style lint;
- formatting;
- editor/LSP-oriented workflows.

It is useful for cheap developer feedback and consistent source quality.

### Verilator

Good early use:

- compile-oriented lint;
- width/signal/construct diagnostics;
- `--lint-only -Wall` preflight;
- fast simulation/compiled model workflows for compatible designs.

Daedalus' first `lint` command supports both, but elaboration-oriented switches
(`--top`, include directories, defines) are routed to Verilator rather than
being silently ignored by the Verible adapter.

## Simulation and cocotb

cocotb 2.x supports multiple simulators and provides a Python testbench API.
That is attractive for Daedalus because tests can be generated and evaluated in
a normal Python ecosystem while the DUT remains HDL.

Do not make cocotb itself the semantic boundary. The receipt should still name:

- simulator/backend;
- HDL language and top;
- compile/elaboration arguments;
- test module/test case;
- seed;
- pass/fail plus failing assertion;
- waveform/artifact location when enabled.

That allows the same conceptual regression to move between Icarus, GHDL,
Verilator or commercial simulators without losing provenance.

## Yosys and open synthesis

Yosys is the natural open-source synthesis backend for many Verilog-centric
flows and also participates in formal workflows. It should be treated as a
compiler with inspectable intermediate/output netlists and reports, not merely
as a binary that returns zero.

Future Daedalus extraction should capture at least:

- inferred cell/memory counts;
- unmapped/unsupported constructs;
- hierarchy/top information;
- technology mapping target;
- generated netlist digest;
- warnings that indicate unintended inference.

## OpenROAD and OpenLane

OpenROAD provides a unified physical-design application with Tcl control over
major implementation operations. OpenLane 2 builds higher-level flows around
OpenROAD and companion tools.

This pairing is useful for Daedalus because it exposes an open path from RTL
through synthesis and physical implementation where agents can inspect the
commands, reports and artifacts at each step.

It must not be described generically as "signoff complete." Signoff depends on
the chosen PDK, checks, corners and often additional foundry/commercial tools.
Daedalus should report exactly what ran.

## Vendor FPGA backends

### Vivado

The canonical G1-EDA-01 contract uses Vivado batch Tcl for an existing XPR, but
does not execute a project-selected script. `inspect` first binds the source
manifest without Vivado. `plan` selects the static packaged Tcl and constructs
argv without effects. `run` compares a disjoint workspace XPR to the source
Identity `/3`, which conservatively includes authored input order/bytes/scopes,
project/fileset/file configuration and semantic run strategies while excluding
relocation/activity state and compiler products below declared generated/cache/
run roots. The exact workspace manifest still binds those product bytes.
Active `.tcl`, `.bat`, `.cmd`, `.exe` and `.ps1`
project automation and every active `FILE_TYPE=Tcl` file are refused. Declared
`.xdc` is admitted only as `FILE_TYPE=XDC`, remains intentionally executable,
and must be operator-trusted including any transitive Tcl behavior. It is not
contained by the suffix/type guard, and no XDC guard is a security boundary.

Manifest preflight fails closed on custom IP or board repositories,
include-directory roots, path-bearing run arguments, FileSet/BD/XCI path
escapes, unsafe `DefaultLaunch`/run/`GeneratedRun` paths, links/junctions or
unbound dependency members, Verilog include directives and
`$readmemh`/`$readmemb`, VHDL TextIO file input and opaque core
containers. These conditions remain visible in read-only inspection but
prevent planning and live admission until their inputs can be content-bound.

Live admission requires an operator-owned `--write-policy` path inside the
authority root; `{"policy":{"write_allow":["."]}}` is the explicit
whole-isolated-workspace form. Missing, malformed, empty/unconfined or denying
policy material fails closed. `run` also requires a stable operator-supplied
`--attempt-id` and exactly one `--writable-path .`. The execution request is
bound to an exact `EdaExecutionPlan` covering argv, cwd, phase-exact native artifacts,
authority-derived CAS root, timeout, sanitized environment, manifests, trusted
Tcl, standard-install launcher bytes and, on Windows, the resolved system
`cmd.exe` bytes. Its digest is signed into the
specialized lease. Authority is rechecked immediately before spawn and while
the managed process runs; terminal replay is inert, same-attempt lease
reacquisition is refused, and a durable `STARTED` execution requires
reconciliation. A safely proven pre-spawn failure may terminalize, but an
ambiguous managed-process constructor/spawn exception or interrupt after
`STARTED` stays pending because child existence cannot be disproved. Ambient
startup Tcl and host tool/profile search paths are refused, but environment
sanitization is not an OS network or secret sandbox. The lease requests no
kernel network or secret capability, but that is not proof of offline,
no-egress or no-secret execution. Vivado, trusted XDC and vendor components
retain ambient host access allowed by the OS. Policy admission records the
declared write scope; it does not OS-enforce that scope on Vivado.

The plan also binds a publication-adapter fingerprint over the on-disk
`daedalus` package Python inventory and declared Python/platform fields. It is
a disk-drift guard for retained publication, not an identity of already-loaded
Python code, a clean-worktree attestation, or a binding to the authority Git
commit.

Byte-binding the launcher and command interpreter does not make the full
vendor toolchain hermetic. Transitive Vivado binaries, device data and built-in
IP/board catalogs remain trusted installation state and must be reported as
residual trust.

Source, workspace and authority roots are pairwise disjoint. CLI
`--source-revision` is the authority checkout's exact lowercase 40-hex Git
HEAD; the design manifest and Source Identity `/3` are distinct 64-hex
SHA-256 identities.

Plan and run outputs are restricted to proper descendants of the workspace
`.daedalus-chip/` namespace. Runtime also rechecks the project default-launch
and write roots and requires the selected synthesis/implementation run
`DIRECTORY` values to be non-empty and workspace-local.

Workspace separation is not an OS-level anti-tamper lock. An independent host
process can still race Vivado between manifest/Tcl checks. Spawned phases
retain an exact post-run workspace manifest and require unchanged authored
Source Identity `/3` for success, but that end-state evidence cannot rule out a
transient write-and-restore race. The operator must enforce single-writer use,
and any known concurrent mutation invalidates the result.

Synthesis-capable phases disable and verify IP-cache use, regenerate XCI/BD
targets, reset all synthesis runs, and disable synthesis and implementation
incremental checkpoint reuse. Implementation performs and retains its own
fresh synthesis checkpoint before place/route. The strict summary binds
the exact phase/project/part/top/runs, parseable Vivado version and completion
facts; timing prose must agree with numeric slack and endpoint metrics.
Target generation can register vendor-generated HDL and other active files;
the same Vivado process re-enumerates them with `get_files -quiet` and rechecks
the expanded graph before synthesis. These are derived same-process inputs,
not independently verified authored source, and the generator/catalog/device
data plus support files not exposed by that query remain vendor TCB.

The current strict native-report adapter exposes:

- WNS/TNS, hold and pulse-width metrics;
- selected missing-clock/unconstrained endpoint counts;
- LUT/FF/BRAM/DSP utilization;
- route/implementation status;
- DRC and methodology rule/severity counts;
- cumulative Vivado message counts; and
- byte identity for reports, checkpoints and bitstreams.

Each parser reports `parsed`, `missing` or `unparseable`. A process return code
or bitstream file is not substituted for a missing report. DRC/methodology
passes require `checks_found=0` and every retained severity count to be zero;
warnings do not pass. Console artifact binding also requires a parsed
cumulative Vivado message summary with zero critical warnings and zero errors.
Clock
utilization/skew, CDC/RDC and other unimplemented dimensions stay explicit
future evidence rather than inferred success.

The current `tdc_light_version` probe is intentionally incomplete. The
immutable ZIP has SHA-256
`2170893265CAE54678E217BA9777ADA278D826C02923A5D237082F7E251DD517`;
its original XPR is 69,273 bytes with SHA-256
`17E03D70D41990130258CF5DA111A9C0259508E8068170CABEAAC510187C5977`.
It records Vivado 2025.1, `impl_1 LaunchOptions=-jobs 14` and automatic
incremental synthesis reuse of `system_wrapper.dcp`.
The later inspected, Vivado-rewritten XPR is separately identified as 68,712
bytes and
`DEF8FC6B833B5C0A962BD497FF3116A01E598FCB90140E37DA9B2CB8D2A367A4`.
It records Vivado 2025.1.1, `impl_1 LaunchOptions=-jobs 4` and disabled
automatic incremental reuse, while the DCP remains an active project file.
Read-only `inspect` emits the working manifest and returns nonzero for
`complete=false`. Its exact active refusal classes are the mutable per-user
`BoardPartRepoPaths`, the non-empty `impl_1` override
`LaunchOptions=-jobs 4`, and active
`tdc_light_version.srcs/utils_1/imports/synth_1/system_wrapper.dcp`.
Historical `ImportPath` attributes are reported but not followed and are not a
fourth active refusal when their current project-local file resolves. A
recorded vendor-catalog MicroBlaze boot-loop resource remains explicit
transitive installation trust.
These three refusals apply to the original/later-working project, not the
separate sanitized source at
`C:\daedalus_eda\tdc_daedalus_source_21708932` and disjoint workspace at
`C:\daedalus_eda\tdc_daedalus_workspace_21708932`. Both derived trees inspect
complete with manifest SHA-256
`46df6acdded3791436a2c094b407ee111402d55f1c5dbc9cac640e26acd31a1d`
and Source Identity `/3`
`842a21fc7be9aac430e9c22c9a594e28af992bf47107c8878aec8e7c670c2601`;
their sanitized XPR SHA-256 is
`69ED07B6AA5E1DA051DA314F6289BC1A6FFFD3BEC39B010060DE09F085C02155`.
Static full planning accepts synthesis followed by implementation, and numeric
host discovery selects Vivado/Vitis 2025.1.1.

On 2026-08-30 the operator switch was `STOP` and the chip write policy was
absent, so no canonical live rerun was admitted. The earlier Vivado 2025.1.1
run used two cached OOC IP results and remains separate non-clean-room history.

### Quartus Prime

Quartus exposes comparable semantic stages through project Tcl, analysis and
synthesis, fitter/place-and-route, TimeQuest timing and output-file generation.
A Daedalus adapter should normalize the high-level metrics while preserving the
native reports for auditability.

## Formal verification

For formal-capable projects, Daedalus should model:

```text
property + assumptions + depth/engine + result
```

not just `formal_passed=true`.

Different engines and proof modes establish different strengths of evidence.
The agent should also retain counterexamples/traces when a property fails.

## Commercial EDA expansion

The architecture should be ready for additional Tcl-heavy commercial tools
without coupling core Daedalus to them. Likely future capability classes are:

- commercial logic synthesis;
- commercial simulation/debug;
- static timing analysis;
- equivalence checking;
- CDC/RDC;
- DFT/ATPG;
- physical implementation;
- physical verification/DRC/LVS;
- power and power-integrity analysis.

Adapters should expose semantic operations and receipts while keeping the
actual executable/license installation outside the Python package.

## What remains after G1-EDA-01

The existing-XPR manifest, static Tcl flow, canonical live admission, native
Vivado parsers and shared chip evidence contracts form the current
vertical-slice implementation. The packet remains an implementation packet
until its required system verification, independent review and evidence
handoff are complete. Later packets may address, in evidence-first order:

1. integrate Verilog/SystemVerilog/VHDL/Tcl into StructCore indexing;
2. parse Verilator/Verible diagnostics into structured findings;
3. add simulator + cocotb run receipts;
4. add Yosys synthesis report/netlist metrics;
5. add OpenROAD/OpenLane timing/area/DRC metric ingestion; and
6. add formal/CDC/equivalence gates as explicit optional dimensions.

That order gives Daedalus useful RTL reasoning and deterministic verification
before it starts optimizing expensive implementation flows.

Vitis/XSCT/`v++` application builds, FPGA programming and hardware-in-the-loop
are not implied by an XSA, bitstream or Vivado receipt. They require separate
work packets, authority, artifact contracts and independent evidence.
