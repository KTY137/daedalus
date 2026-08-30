# Chip Design Workflows

This directory is the dedicated hardware-design knowledge base for Daedalus.
It intentionally keeps RTL, verification, FPGA, ASIC and EDA automation
material separate from the general agent/runtime documentation.

## What Daedalus supports in this first hardware slice

- RTL discovery and classification for Verilog (`.v`), SystemVerilog (`.sv`),
  headers (`.vh`, `.svh`) and VHDL (`.vhd`, `.vhdl`).
- Constraint/config discovery for XDC, SDC, QSF, SBY and source filelists, plus
  distinct Vivado project (`.xpr`), block-design (`.bd`) and IP configuration
  (`.xci`) identities. Generated Vivado run/cache directories are not treated
  as authored source inventory.
- Read-only XPR inspection that records the exact project bytes, target
  part/board/top, filesets, runs, referenced inputs, missing/outside references
  and SHA-256 identities without opening Vivado. Source Identity `/3` binds
  authored active-input bytes and conservative project-, fileset-, per-file-
  and run-level semantics, including file order/type/scope, strategies, steps,
  options and reports. The exact workspace manifest separately binds generated,
  cache and run-product bytes; those compiler products are excluded from
  authored candidate identity so deterministic regeneration does not mint a
  new source candidate.
- Gate-1 manifest refusal for source-closure mechanisms that are not yet
  content-addressed: custom IP or board repositories, include-directory
  search roots, path-bearing run arguments, FileSet/BD/XCI dependency-root
  escapes, unsafe `DefaultLaunch`/run/`GeneratedRun` paths, Verilog include
  directives and `$readmemh`/`$readmemb`, VHDL TextIO file input and opaque
  `.xcix`/`.xco` core containers. These remain visible in inspection evidence,
  but an incomplete manifest cannot be planned or run.
- Effect-free planning and one admitted Vivado project runner for `inspect`,
  `synth`, `impl` and `full` phases. The live project flow uses the static,
  package-owned `vivado_project_flow.tcl`. Any active file whose Vivado
  `FILE_TYPE` is `Tcl`, plus active project/archive automation ending in
  `.tcl`, `.bat`, `.cmd`, `.exe` or `.ps1`, is refused. A declared `.xdc` is
  accepted only with `FILE_TYPE=XDC`: it is deliberately executable constraint
  Tcl and must already be trusted by the operator as part of the authoritative
  design.
  Resolved project, default-launch, run and IP-output write roots must remain
  inside the isolated workspace, and selected synthesis/implementation runs
  require concrete workspace-local `DIRECTORY` values.
- Strict parsing of Vivado timing, utilization, DRC, methodology, routing and
  cumulative-message reports. Missing and unparseable reports remain distinct
  from a valid report containing zero findings. DRC/methodology passes require
  `checks_found=0` and zero counts at every retained severity; warning-only
  reports are not labelled passed.
- Tcl automation through explicit backends for Tclsh, AMD Vivado, Quartus
  Prime, Yosys and OpenROAD.
- Verilog/SystemVerilog lint command construction for Verilator and Verible.
- Effect-free tool availability discovery and separate interpretation of
  admitted version-probe output for the registered EDA stack.
- Dry-run-first external execution. A live Vivado project process requires the
  canonical kill switch, an injected Effect Lease and exact execution request;
  it runs as argv with `shell=False` and is controlled as a managed process.
  An exact `EdaExecutionPlan` binds argv, working directory, declared artifact
  paths, authority-dominated CAS root, timeout, sanitized environment, both
  manifests, trusted Tcl, vendor-launcher and Windows command-interpreter byte
  identities before the durable start. That operation digest is also signed
  into the specialized chip lease.
  The executor independently reconstructs and rechecks the canonical Vivado
  argv immediately before spawn and refuses a digest-bound but caller-selected
  `vivado -source` command.
- Content-addressed retention of console output, declared native artifacts and
  pre/post workspace manifests plus the execution receipt. A successful spawned
  phase requires a complete post-run manifest with unchanged authored Source
  Identity `/3`; its exact manifest SHA-256 may change as generated products
  change.
- Repository-relative path validation for RTL files, Tcl scripts and include
  directories; this is admission logic, not OS filesystem enforcement.

The implementation lives in `daedalus/chip_design/` and deliberately remains
Python-stdlib-only. EDA programs are external capabilities, not Python runtime
dependencies.

## Quick start

After installing Daedalus from this checkout:

```text
daedalus-chip status
daedalus-chip scan .
daedalus-chip classify rtl/top.sv constraints/top.xdc flow/build.tcl
```

Plan an RTL lint invocation without starting a tool:

```text
daedalus-chip lint --tool verilator --top top rtl/top.sv
```

Raw `lint` and `tcl` commands are planning surfaces in G1-EDA-01. Their
`--live` form is refused; the admitted live surface is the project-aware
`run` command below.

### Canonical Vivado project flow

Keep the authoritative project and the execution workspace separate:

```text
SOURCE_ROOT/       authoritative input; inspect only
WORKSPACE_ROOT/    isolated copy/worktree where Vivado may write
AUTHORITY_ROOT/    Daedalus checkout owning policy and the kill switch
```

Create an operator-owned write-policy file inside `AUTHORITY_ROOT`. This Gate-1
flow declares the whole already-isolated workspace, so the policy must admit
`.`; the minimal form is:

```json
{"policy":{"write_allow":["."]}}
```

For example, store it as
`AUTHORITY_ROOT/.agentenv/chip-eda-policy.json`. A narrower policy does not
satisfy this packet's exact `--writable-path .` contract.

Inspect the source XPR without invoking Vivado:

```text
daedalus-chip inspect SOURCE_ROOT/design.xpr --project-root SOURCE_ROOT --json
```

Plan the exact workspace invocation without acquiring authority, writing files
or starting Vivado:

```text
daedalus-chip plan WORKSPACE_ROOT/design.xpr --project-root WORKSPACE_ROOT --phase full --output-dir .daedalus-chip/plans
```

Both planning and live output directories must be proper descendants of the
workspace's dedicated `.daedalus-chip/` namespace; an arbitrary workspace
directory is not accepted as the evidence root.

Only after independently creating and checking the isolated workspace, run the
admitted flow:

```text
daedalus-chip run SOURCE_ROOT/design.xpr --workspace-project WORKSPACE_ROOT/design.xpr --authority-root AUTHORITY_ROOT --write-policy .agentenv/chip-eda-policy.json --source-revision 0123456789abcdef0123456789abcdef01234567 --attempt-id operator-attempt-001 --writable-path . --confirm-project-writes --phase full --output-dir .daedalus-chip/runs --json
```

`run` requires disjoint source/workspace roots and equal relocation-stable
source identities, a stable operator-supplied `--attempt-id`, and exactly one
`--writable-path .` declaration. The stable attempt identity makes restart
behavior deterministic; the writable declaration acknowledges the entire
isolated workspace as the effect scope and must agree with the operator-owned
write policy. Exact XPR hashes are retained too, but are not expected to
match after Vivado rewrites path- or run-local XML metadata. The explicit
`--confirm-project-writes` flag acknowledges that Vivado can update project
state inside the workspace; it does not grant authority or arm the kill
switch. The operator must already have armed the existing fail-closed control
plane. The policy path is resolved under the authority root; a path outside
that root, a missing or malformed policy, an empty `write_allow`, or a policy
that denies `.` refuses before process spawn. Authority and the kill switch
are rechecked throughout the managed process. A terminal replay is inert; a
durable `STARTED` execution without a terminal receipt requires reconciliation
and is not retried. A safely proven pre-spawn refusal may terminalize, but an
ambiguous managed-process constructor/spawn exception or interrupt after
`STARTED` remains pending because child existence cannot be disproved. This
command never changes `STOP` to `RUN` itself.

`--source-revision` names the operator authority checkout, not the HDL design:
it must be the exact current `AUTHORITY_ROOT` Git HEAD as 40 lowercase hex
characters. The design manifest SHA-256 and Source Identity `/3` are separate
64-hex values retained in the plan/receipt. All three roots - source,
workspace and authority - must be pairwise disjoint.

The isolated workspace is an operator-enforced single-writer prerequisite,
not an OS lock. Daedalus rebinds manifests at guarded phase boundaries and
requires/retains a complete post-run workspace manifest with unchanged authored
Source Identity `/3`. It also performs stable opened-handle reads of declared
outputs. Those observations detect covered end-state drift, but cannot exclude
an unrelated host process changing and restoring bytes while Vivado is
running. Known concurrent mutation invalidates the run evidence; do not share
the workspace with another writer.

Live launcher selection ignores `PATH` and `DAEDALUS_VIVADO_COMMAND`; it uses
only a regular, non-symlink launcher under a package-known standard AMD install
layout and binds its SHA-256. On Windows the resolved system `cmd.exe` used to
start the vendor `.bat` launcher is also byte-bound. `--vivado` can confirm
the discovered launcher but cannot replace it. The child gets a fixed minimal
system `PATH`, a fresh profile leaf derived from the phase/output identity,
and workspace-local `TEMP`/`TMP`.
Existing installation `Vivado_init.tcl`/legacy `init.tcl` or a pre-existing
profile leaf refuses before spawn. These checks reduce ambient startup state;
they are not an OS sandbox. The selected launcher and command interpreter are
exact inputs, but the transitive Vivado installation, device database and
vendor catalogs they load are still trusted installation state rather than a
fully content-addressed toolchain.

The same CLI is available without installation as:

```text
python -m daedalus.chip_design ...
```

## Documentation map

- [WORKFLOWS.md](WORKFLOWS.md) — canonical RTL-to-FPGA and RTL-to-GDS flows,
  verification gates and evidence Daedalus should retain.
- [TCL_AUTOMATION.md](TCL_AUTOMATION.md) — exact Tcl backend contracts and
  conventions for deterministic EDA scripts.
- [TOOLCHAINS.md](TOOLCHAINS.md) — recommended open-source and vendor tools by
  design phase, plus how they fit together.
- [REFERENCES.md](REFERENCES.md) — primary documentation used to establish the
  initial contracts.

## Operating principle

Chip design is not normal application code. A syntactically valid RTL patch is
not evidence of a valid hardware change. Daedalus should promote confidence in
stages:

1. classify the design sources and constraints;
2. lint and elaborate;
3. simulate and/or formally verify the intended behavior;
4. synthesize and inspect warnings/utilization;
5. prove timing against explicit constraints;
6. run implementation/physical-design checks;
7. retain the reports and tool versions that justify the result.

A generated bitstream or GDS file alone is therefore never a sufficient pass
signal.

## Current boundary

G1-EDA-01 bounds only a Vivado project flow and its retained evidence.
A completed implementation or generated bitstream is not a signoff claim. The
receipt keeps simulation, formal, CDC/RDC, equivalence, power, testbench/AXI
behavior, Vitis software, hardware-in-the-loop and signoff explicitly
`not_run` unless a later packet supplies independent evidence.

The slice does not program an FPGA, execute a Vitis/XSCT/`v++` application,
auto-promote a result, or claim that Python path checks or the sanitized child
environment form an operating-system or network sandbox. The lease grants no
network capability,
but this packet does not install an OS-level network boundary. Foundry
signoff, analog/mixed-signal support, power-integrity signoff and DFT/ATPG
closure remain outside this slice.

For synthesis-capable canonical phases, the package Tcl disables Vivado's IP
synthesis cache, verifies that state, resets and force-regenerates active XCI
and block-design output products, disables incremental checkpoint reuse for
both synthesis and implementation, and records the relevant completion/cache
facts in the strict phase summary. Summary identity and timing prose must agree
with the exact run inputs and parsed numeric timing fields.

The supplied `tdc_light_version` project can currently be inspected read-only,
but its XPR declares a mutable per-user `BoardPartRepoPaths` entry for the
Xilinx board store. Because the selected board part affects Vivado semantics
and that catalog is not yet content-addressed, the manifest is intentionally
incomplete and `plan` refuses. `inspect --json` still emits the full read-only
manifest, then returns nonzero to signal `complete=false`; this is not an
Exit-0 acceptance claim. The manifest also records a vendor-catalog MicroBlaze
boot-loop resource, whose transitive bytes remain declared installation trust.
This is the expected safe result until the board catalog is pinned and bound.
On 2026-08-30 the operator kill switch was also `STOP` and
`.agentenv/chip-eda-policy.json` was absent, so no canonical live rerun was
admitted.

An earlier isolated Vivado 2025.1.1 run did synthesize, implement and emit a
bitstream for this archive. It ran outside the canonical Gate-1 path and used
two cached out-of-context IP results, so it remains separate, non-clean-room
historical evidence; it is not silently upgraded by this implementation.

XDC trust is intentionally strong: XDC is Tcl and can transitively `source`
other scripts or invoke host commands. The direct active-file checks do not
contain a malicious constraint file and are not a security boundary. Only run
this flow after reviewing and trusting every declared XDC; otherwise stop
before admission.
