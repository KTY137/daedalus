# Tcl Automation for EDA Tools

Tcl is a first-class control language across a large part of digital design.
Daedalus therefore models a Tcl invocation as a typed EDA capability rather
than as a free-form shell string.

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

```text
vivado -mode batch -source script.tcl
vivado -mode batch -source script.tcl -tclargs arg1 arg2
```

Vivado's documented batch mode executes the Tcl source and exits. Daedalus uses
batch mode explicitly so an agent does not accidentally depend on an
interactive GUI session or its transient state.

Inside a parameterized script, consume documented Tcl arguments rather than
building a shell command around the script.

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

The execution contract is therefore:

```text
validated repo path
  -> backend-specific argv builder
  -> executable resolved from PATH
  -> subprocess(..., shell=False)
  -> bounded receipt
```

The Tcl file itself remains powerful by design. A repository that permits an
agent to edit or execute Tcl is permitting EDA automation and must review that
capability accordingly.

## Dry-run first

`daedalus-chip tcl` does not start a tool unless `--live` is present. The normal
sequence is:

```text
daedalus-chip tcl vivado flow/build.tcl --arg PART=xc7a35ticsg324-1L
# inspect argv
daedalus-chip tcl vivado flow/build.tcl --arg PART=xc7a35ticsg324-1L --live
```

The script must resolve inside `--repo-root`; escaping the checkout is refused.
This prevents a task nominally scoped to one project from selecting an
unrelated Tcl file elsewhere on the host.

## Recommended Tcl structure

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

## Rules for agent-authored Tcl

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

### Pin or record tool versions

Vendor releases and open-source EDA versions can change warnings, synthesis
heuristics, timing models and output formats. Every meaningful comparison needs
tool-version provenance.

## Suggested Tcl flow API for future Daedalus work

Instead of teaching agents hundreds of vendor commands directly, Daedalus can
progress toward a semantic phase interface:

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
