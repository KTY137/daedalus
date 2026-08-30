# Tcl Automation for EDA Tools

Tcl is a first-class control language across a large part of digital design.
Daedalus therefore models a Tcl invocation as a typed EDA capability rather
than as a free-form shell string.

G1-EDA-01 separates two surfaces that must not be conflated:

- generic backend argv construction for expert Tcl workflows, which remains a
  dry-run/planning surface; and
- the live existing-XPR Vivado flow, which accepts no caller-selected script
  and uses one static package-owned template behind canonical admission.

## Backend contracts

The initial implementation in `daedalus/chip_design/toolchains.py` maps a
script to an explicit argv for each supported backend.

### Generic Tcl

```text
tclsh script.tcl arg1 arg2
```

Use this only for portable Tcl that does not require commands registered by a
specific EDA tool.

### AMD Vivado

The generic, non-live backend shape remains:

```text
vivado -mode batch -source script.tcl
vivado -mode batch -source script.tcl -tclargs arg1 arg2
```

Vivado's documented batch mode executes the Tcl source and exits. Daedalus uses
batch mode explicitly so an agent does not accidentally depend on an
interactive GUI session or its transient state.

Inside a parameterized script, consume documented Tcl arguments rather than
building a shell command around the script.

This generic form is not the admitted G1-EDA-01 project runner. For a live
existing-XPR phase, Daedalus constructs only this shape:

```text
VIVADO -mode batch -nojournal -nolog -notrace \
  -source PACKAGE/daedalus/chip_design/tcl/vivado_project_flow.tcl \
  -tclargs PHASE WORKSPACE_ROOT WORKSPACE_XPR OUTPUT_DIR PART TOP SYNTH_RUN IMPL_RUN JOBS
```

`PHASE` is `inspect`, `synth` or `impl`; the CLI's `full` phase orchestrates
the required phase invocations. Every runtime value is a separate argv item
after `-tclargs`. Python does not interpolate values into Tcl and does not
write a temporary Tcl file before the durable effect start.

The installed template is itself evidence. `trusted_vivado_tcl()` returns its
resolved package path, byte length and SHA-256; `build_vivado_flow_argv()` binds
that exact path into argv. Packaging must include `tcl/vivado_project_flow.tcl`
as `daedalus.chip_design` package data.

The template:

- opens only the workspace XPR and validates the exact expected part/top;
- requires exact synthesis and implementation run names;
- clears Tcl hook properties from every project run before launching work;
- rejects selected project files outside the declared workspace root;
- revalidates the expanded graph before and after IP/BD generation and before
  launch, including exact part/top, write roots, file modes, run-input
  overrides and cleared hook state;
- reads `FILE_TYPE` for every active file and refuses `Tcl` regardless of
  suffix, plus active automation ending in `.tcl`, `.bat`, `.cmd`, `.exe` or
  `.ps1`;
- admits `.xdc` only with `FILE_TYPE=XDC` as executable, operator-trusted
  constraint Tcl; an XDC can transitively `source`/`exec`, so this is trust,
  not containment or a security boundary;
- refuses non-empty custom `IP_REPO_PATHS`, custom/ambient board repository
  paths, `INCLUDE_DIRS`, path-bearing run overrides, opaque `.xcix`/`.xco`
  containers and non-`xilinx.com` IP definitions;
- refuses resolved project, run or IP-output directories outside the declared
  isolated workspace before reset or launch, including default-launch and
  selected synthesis/implementation run directories;
- keeps its output directory as a proper descendant of the dedicated
  workspace `.daedalus-chip/` namespace;
- disables and verifies Vivado IP-cache use, resets/force-regenerates active
  XCI/BD output products, resets all synthesis runs and disables incremental
  checkpoint reuse for synthesis and implementation;
- reruns fresh synthesis inside `impl` and retains `synth_design.dcp` before
  implementation;
- writes native reports/checkpoints/bitstream with stable declared names;
- emits a strict phase summary whose exact phase/project/part/top/run/version,
  cache/generation and completion facts must match the plan, while timing prose
  must agree with numeric slack, total-negative-slack and failing-endpoint
  fields; and
- never `source`s a project/archive Tcl file or invokes a host command through
  Tcl `exec`.

Python preflight closes the direct source graph before this template can run.
It rejects FileSet, block-design and XCI dependency-root escapes; links or
junctions; unsafe `DefaultLaunch`, run and `GeneratedRun` paths; opaque core
containers; path-bearing run arguments including `LaunchOptions`; Verilog
include directives and `$readmemh`/`$readmemb`; and VHDL TextIO file input.
The Tcl rechecks are defense against XPR parser drift or project expansion,
not a way to make an incomplete manifest executable.

### Quartus Prime

```text
quartus_sh -t script.tcl arg1 arg2
```

Quartus exposes project, compile, assignment, report and timing automation
through Tcl. Treat the script as the reproducible description of the run, not
as a sidecar to manual GUI state.

### Yosys

```text
yosys -c script.tcl
```

Yosys documents `-c` as its Tcl-script mode. Daedalus currently refuses direct
script arguments for this backend rather than inventing an argv convention.
If parameters are required, make them explicit in the flow/config or add a
backend mapping after its contract is documented and tested.

### OpenROAD

```text
openroad -no_init -exit script.tcl
```

OpenROAD accepts a Tcl command file. Daedalus adds:

- `-no_init` so a user's `~/.openroad` file cannot silently alter an automated
  flow;
- `-exit` so the process ends after the command file instead of entering an
  interactive prompt.

Direct script arguments are intentionally refused by the first implementation
instead of guessing how a particular flow expects configuration.

## Why Daedalus does not use `shell=True`

A Tcl script is already an executable control surface. Adding another shell
parser between an agent and the EDA program makes quoting platform-dependent
and turns a structured invocation into a command-injection surface.

The generic planning contract is therefore:

```text
validated repo path
  -> backend-specific argv builder
  -> effect-free planned argv
```

The admitted Vivado project contract adds the required authority boundary:

```text
matching source/workspace manifests + trusted Tcl/launcher/system-cmd SHA-256
  -> exact EdaExecutionPlan(argv, cwd, artifacts, CAS, timeout,
                            sanitized env, manifests, Tcl, launcher, system cmd)
  -> operation SHA-256 signed into the specialized chip lease request
  -> operator write policy inside AUTHORITY_ROOT
  -> central cli.daedalus_chip policy/containment/budget decisions
  -> armed fail-closed kill switch
  -> exact NonRuntimeEffectAuthorization + EffectExecutionRequest
  -> durable begin
  -> managed process(argv, shell=False) + continuous authority verification
  -> content-addressed outputs + one terminal receipt
```

The write-policy and containment rows are canonical admission decisions and
evidence. They do not install an OS filesystem/network sandbox around Vivado.

A Tcl file remains powerful by design. Direct active `FILE_TYPE=Tcl` content
and `.tcl`, `.bat`, `.cmd`, `.exe` and `.ps1` project/archive automation is
therefore inventory, not executable authority in this slice. XDC is the
deliberate exception: Vivado interprets admitted `FILE_TYPE=XDC` constraints as
Tcl, so the operator must trust their behavior and transitive dependencies as
authoritative design input before admission. Their bytes, order, scopes and
file metadata are bound by Source Identity `/3`; Python does not sandbox what
trusted XDC does inside Vivado. Neither the XDC suffix/type checks nor the
packaged Tcl claim a security boundary against a malicious constraint.

## Dry-run first

`daedalus-chip tcl` and `daedalus-chip lint` remain effect-free planning
commands. Their raw `--live` form is refused in G1-EDA-01. For an existing
Vivado project, use:

```text
daedalus-chip inspect SOURCE_ROOT/design.xpr --project-root SOURCE_ROOT
daedalus-chip plan WORKSPACE_ROOT/design.xpr --project-root WORKSPACE_ROOT --phase synth
# after reviewing the isolated workspace, authority and already-armed switch:
daedalus-chip run SOURCE_ROOT/design.xpr --workspace-project WORKSPACE_ROOT/design.xpr --authority-root AUTHORITY_ROOT --write-policy .agentenv/chip-eda-policy.json --source-revision 0123456789abcdef0123456789abcdef01234567 --attempt-id operator-attempt-001 --writable-path . --confirm-project-writes --phase synth --output-dir .daedalus-chip/runs
```

Planning creates no output directory and acquires no authority. Live `run`
requires disjoint source/workspace roots, identical relocation-stable source
identity, a stable operator-supplied `--attempt-id`, exactly one
`--writable-path .`, and workspace-confined output. The write-policy JSON must resolve
inside the authority root and contain a usable, non-empty `write_allow`; for
this exact whole-workspace admission the minimal explicit form is
`{"policy":{"write_allow":["."]}}`. Missing, malformed, unconfined or denied
policy material fails closed. The exact `EdaExecutionPlan` binds argv, cwd,
phase-exact artifact paths, authority-dominated CAS root, timeout, sanitized
environment, both manifests and the trusted Tcl/launcher digests into the
execution operation. The specialized issuer signs that operation digest into
the lease request. It never arms the kill switch itself.

The authority root is also disjoint from both design roots.
`--source-revision` must equal its current Git HEAD as lowercase 40-hex; it is
not either 64-hex design-manifest/Source-Identity digest.

Authority and the kill switch are rechecked while Vivado is running. A
terminal replay does not spawn a process. A safely proven pre-spawn refusal can
be terminal; after durable `STARTED`, an ambiguous managed-process
constructor/spawn exception or interrupt remains `STARTED` for reconciliation
because child existence cannot be disproved. It is never treated as a failed
or successful replay. Reacquiring the same mission/attempt is refused by
deterministic lease identity rather than launching again.

The live child uses a standard-install launcher, minimal `PATH`, a fresh
phase/output-specific profile, and refuses ambient installation init Tcl. On
Windows both that launcher and the resolved system `cmd.exe` used for the
vendor batch file are byte-bound. The binaries, device data and IP/board
catalogs loaded transitively from the Vivado installation are not completely
content-addressed and remain explicit vendor-installation trust. Environment
sanitization is not an operating-system network sandbox, and this packet makes
no such security claim.

The packaged Tcl and Python manifest checks also do not lock the workspace
against an unrelated host writer. Revalidation catches changes at covered
phase/launch boundaries and stable output reads reject replacement/torn files,
while a spawned phase retains a complete post-run workspace manifest and
requires unchanged authored Source Identity `/3` for success. These end-state
checks do not prove bytes could not change and be restored while Vivado
consumes them. The operator must provide an exclusive workspace; known
concurrent tamper invalidates the evidence.

For the supplied `tdc_light_version` XPR, read-only `inspect` emits the manifest
and returns nonzero for `complete=false`; it finds a mutable per-user
`BoardPartRepoPaths`. Because board flow affects project semantics, `plan`
safely refuses until that catalog is pinned and bound. The manifest also
retains a vendor-catalog MicroBlaze boot-loop resource as explicit transitive
installation trust. With the operator switch at `STOP` and the chip policy
absent on 2026-08-30, no canonical live command was admitted; the older
cache-assisted Vivado run stays separate non-clean-room history.

## Recommended Tcl structure for non-canonical future adapters

A flow script should make hidden state difficult. Prefer this shape:

```tcl
# 1. Resolve project-relative inputs explicitly.
set script_dir [file dirname [file normalize [info script]]]
set project_dir [file normalize [file join $script_dir ..]]

# 2. Validate required inputs/parameters before expensive work.
# 3. Create a deterministic report/output directory.
# 4. Read sources and constraints explicitly.
# 5. Execute one named design phase at a time.
# 6. Emit machine-readable or consistently parseable reports.
# 7. Fail the process when a required gate fails.
```

Exact commands differ by backend, but the invariants should not.

## Rules for agent-authored Tcl outside the G1 Vivado project runner

These rules remain useful for dry-run expert workflows and future bounded
adapters. They do not authorize substituting agent-authored Tcl for the static
G1 Vivado template.

### Prefer explicit inputs

Do not depend on whatever project happened to be open in a GUI. Name the
project/checkpoint/source list or create it deterministically in the script.

### Resolve paths relative to the script or declared repository root

A run launched from a different current working directory should not silently
read another file.

### Make constraints visible

Clock/timing constraints and target part/library must be inspectable from the
flow inputs. A script that succeeds because it failed to read constraints is a
failed automation design.

### Produce reports before artifacts

For example, an FPGA script should generate timing/utilization/DRC reports
before or alongside a bitstream. An ASIC flow should emit timing and physical
metrics tied to the same run that creates its layout artifacts.

### Fail loudly

A message containing `ERROR` is not enough if the process still exits zero.
Where the tool permits it, convert violated required conditions into a non-zero
exit or a machine-readable failed gate Daedalus can consume.

### Avoid implicit user initialization

OpenROAD's `-no_init` is one example. For every tool, watch for startup scripts,
GUI preferences, environment-defined IP paths, cached projects and user-global
configuration that can make two nominally identical runs differ.

### Keep host process execution exceptional

Tcl often exposes `exec`. That can be useful, but it crosses from EDA scripting
into arbitrary host execution. Use it only when the workflow genuinely needs
it and make that command explicit enough to vet. Prefer Daedalus orchestrating
separate tools as separate typed steps when possible.

The G1 Vivado template does not use Tcl `exec`.

### Pin or record tool versions

Vendor releases and open-source EDA versions can change warnings, synthesis
heuristics, timing models and output formats. Every meaningful comparison needs
tool-version provenance.

## Semantic Tcl flow direction

The existing-XPR slice now exposes `inspect`, `synth`, `impl` and CLI-composed
`full` as bounded project phases. Broader backend work can progress toward a
semantic interface instead of teaching agents hundreds of vendor commands
directly:

```text
read_design(manifest)
apply_constraints(constraints)
lint()
synthesize()
place()
clock_tree()
route()
report_timing()
report_utilization_or_area()
write_artifact()
```

Backend adapters would compile these intentions to Vivado, Quartus, Yosys or
OpenROAD Tcl. Raw Tcl remains available for expert workflows, but the semantic
layer makes policies, receipts and cross-tool comparisons much easier to
reason about.
