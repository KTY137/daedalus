# Chip Design Workflows

This document defines the workflow vocabulary Daedalus should reason about
when it works on RTL. The important distinction from software development is
that correctness is progressively constrained by logic, timing and physical
implementation. Later stages can invalidate an apparently correct earlier
result.

## 1. Common RTL front end

A sensible flow starts with the same evidence regardless of whether the target
is an FPGA or an ASIC.

### 1.1 Source inventory

Record at minimum:

- synthesizable Verilog/SystemVerilog/VHDL sources;
- non-synthesizable testbench sources;
- include directories and macro definitions;
- top-level design unit;
- clock/reset definition;
- XDC/SDC/QSF constraints where applicable;
- memory/IP/generated-source dependencies;
- Tcl/build scripts and source filelists.

Generated RTL should be identifiable as generated rather than silently mixed
with human-authored RTL. The manifest used for a run should be retained or
hashed so a later report can be tied to exactly the sources it evaluated.

### 1.2 Style and syntax lint

Cheap deterministic checks should run before expensive simulation or place and
route. Useful roles include:

- Verible for SystemVerilog parsing/style lint/formatting;
- Verilator `--lint-only -Wall` for stronger compile-oriented Verilog/SystemVerilog lint;
- GHDL analysis for VHDL-oriented projects.

Warnings should be classified rather than globally suppressed. Clock/reset,
width, latch, combinational-loop, incomplete-case and unused-signal findings
can encode real design defects.

### 1.3 Elaboration and compile

A parser accepting individual files is weaker evidence than the complete design
elaborating with its top, parameters, packages, includes and generated blocks.
Daedalus should therefore distinguish:

`parsed -> linted -> elaborated`

rather than flattening all three into `syntax_ok`.

### 1.4 Dynamic verification

Run self-checking tests at the cheapest useful level first. A typical stack is:

- unit/module testbench;
- subsystem testbench;
- top-level integration testbench;
- protocol/property checks;
- randomized or constrained-random regressions where appropriate.

cocotb can provide Python testbenches over several simulators, while native
SystemVerilog or VHDL testbenches remain valid. The simulator, seed, test name
and result should be part of the receipt so failures are reproducible.

### 1.5 Formal verification

Formal is complementary to simulation. Good early targets are finite control
logic, FIFOs, handshakes, arbiters, counters, CDC-facing contracts and safety
properties. Open-source flows commonly combine Yosys with SymbiYosys and a
formal solver; vendor formal tools can occupy the same workflow role.

A formal result must state what was proved and under which assumptions. A
bounded proof is not silently upgraded to an unbounded proof.

### 1.6 Synthesis

Synthesis translates elaborated RTL into a technology-oriented netlist. Retain:

- tool/version;
- top and source manifest;
- target device/library;
- clocks/constraints;
- warnings;
- inferred memories/DSPs or technology cells;
- utilization/area estimates;
- critical timing information when available;
- emitted netlist/checkpoint identity.

Synthesis success does not imply timing closure or physical feasibility.

## 2. Canonical Vivado project slice (G1-EDA-01)

The project-aware Vivado path is deliberately narrower than arbitrary Tcl
execution. It opens an existing XPR in an isolated workspace, runs only the
Daedalus-owned phase template and retains native evidence through the canonical
kernel.

### 2.1 Source, workspace and derived identities

| Role | Mutability | Identity and rule |
| --- | --- | --- |
| Source XPR/root | read-only authoritative input | Exact XPR SHA-256 plus relocation-stable authored Source Identity `/3` |
| Workspace XPR/root | isolated execution copy; Vivado may write here | Must be disjoint from source/authority and have the same Source Identity `/3` before admission; exact manifest may change as products regenerate |
| Authority checkout | operator-owned policy/evidence root | Pairwise disjoint; CLI `--source-revision` must equal its current Git HEAD as lowercase 40-hex |
| Trusted Tcl | static package resource | Path, byte length and SHA-256 of `daedalus/chip_design/tcl/vivado_project_flow.tcl` |
| Post-run workspace manifest | final exact workspace observation | Retained after a spawned phase; successful result requires complete manifest and unchanged authored Source Identity `/3` |
| Reports/checkpoints/bitstream | derived run artifacts | Retained by byte SHA-256 with provenance; never replace source identity |

The workspace must have one operator-controlled writer. Source/workspace
manifests are rebound at guarded phase boundaries and Tcl rechecks the expanded
project before launch. A spawned phase also recomputes and retains its exact
post-run workspace manifest and requires unchanged authored Source Identity
`/3` for success. These are end-state observations, not an OS filesystem lock;
they do not prevent an unrelated host process from racing or restoring bytes
between checks. Any known concurrent writer invalidates the evidence and the
run must not be used for acceptance.

The exact source and workspace XPR hashes may differ because XPR XML contains
relocation-volatile project paths and generated-run metadata. The stable source
identity excludes those values but binds the selected part, board, top,
filesets, authored active-input bytes, declared output roots, vendor-catalog
resource declarations, conservative root/fileset/per-file configuration and
every run's semantic strategy, ordered steps, options and reports. Project
paths are normalized as project-relative or canonical
external identities; narrow GUI activity counters, mutable run status,
and volatile launch/`GeneratedRun` attributes are excluded from the semantic
run-configuration projection only after their paths are resolved and checked.
`DefaultLaunch`, run and `GeneratedRun` directories must remain inside the
project, and an existing generated-run file is byte-bound by the exact
workspace manifest. Generated/cache/run products and files below declared
output roots are intentionally excluded from authored Source Identity `/3`.
It is not a general similarity check: an authored RTL, XDC, BD/XCI or semantic
run-strategy change must change the identity or make the comparison refuse.

Historical `ImportPath` entries and references outside the declared root are
reported rather than silently followed. An active input that is missing,
unreadable, unresolved or outside the root makes the active manifest
incomplete. Paths outside the root are not opened merely to hash them.

Gate 1 also refuses project semantics whose transitive bytes are not closed by
Source Identity `/3`: custom IP/board repositories, include-directory roots,
path-bearing run arguments, FileSet roots or BD/XCI dependency roots that
escape the project, unsafe `DefaultLaunch`/run/`GeneratedRun` paths, opaque
`.xcix`/`.xco` cores, Verilog include directives and
`$readmemh`/`$readmemb`, and VHDL TextIO file input. Direct BD/XCI dependency
trees inside the project are byte-bound; a link, junction, missing member,
unbound user file or escape makes the manifest incomplete. Read-only
`inspect` reports these reasons; `plan` and `run` require a complete manifest.

### 2.2 `inspect`: read-only source understanding

```text
daedalus-chip inspect SOURCE_ROOT/design.xpr --project-root SOURCE_ROOT --json
```

This command parses the XPR as bounded, untrusted XML and does not start
Vivado. Its manifest records project bytes, part/board/top, filesets, runs and
direct references including BD/XCI identities and explicit reference status.
Use it on the authoritative source before creating or approving a workspace.
An incomplete project still emits its manifest and refusal evidence, then
returns nonzero; read-only inspectability does not imply `complete=true`.

Do not confuse this command with `run --phase inspect`. The latter opens the
workspace project in Vivado and therefore remains a live, write-capable,
admitted action even though it does not synthesize or implement.

### 2.3 `plan`: effect-free argv and output review

```text
daedalus-chip plan WORKSPACE_ROOT/design.xpr --project-root WORKSPACE_ROOT --phase full --output-dir .daedalus-chip/plans
```

Planning validates the project/output confinement, target identity, run names,
job bound and trusted Tcl identity and then shows the exact argv and expected
outputs. It does not acquire a lease, create the output directory, execute a
version probe or start Vivado. A planning-only `--vivado PATH` can show an
installed launcher, but live execution accepts only the package-known standard
AMD discovery identity and treats `--vivado` as exact confirmation. Every
runtime value remains a distinct argv item after `-tclargs`. The output must be
a proper descendant of the dedicated workspace `.daedalus-chip/` namespace;
the namespace root itself and arbitrary sibling directories are refused.

### 2.4 `run`: the only live Vivado project surface

```text
daedalus-chip run SOURCE_ROOT/design.xpr --workspace-project WORKSPACE_ROOT/design.xpr --authority-root AUTHORITY_ROOT --write-policy .agentenv/chip-eda-policy.json --source-revision 0123456789abcdef0123456789abcdef01234567 --attempt-id operator-attempt-001 --writable-path . --confirm-project-writes --phase full --output-dir .daedalus-chip/runs --json
```

The policy file is operator-owned and must resolve inside `AUTHORITY_ROOT`.
This canonical flow declares the entire isolated workspace, so the policy must
admit `.`; its minimal shape is:

```json
{"policy":{"write_allow":["."]}}
```

Missing, unreadable or malformed policy material, an empty `write_allow`
(unconfined), an outside-authority policy path, or a policy denial all fail
closed before process spawn. The CLI additionally requires a stable,
operator-supplied `--attempt-id` and exactly one `--writable-path .`; narrower,
additional or omitted writable declarations are refused because Vivado may
rewrite project and run state throughout the isolated workspace.

Before process spawn, the run must:

1. build both manifests and require identical relocation-stable source
   identities;
2. prove pairwise source/workspace/authority disjointness, require the supplied
   40-hex `--source-revision` to equal the authority checkout's current Git
   HEAD, and keep every selected project/output path inside the workspace;
3. bind the static Tcl resource and an exact `EdaExecutionPlan` covering argv,
   cwd, phase-exact native-artifact paths, authority-dominated Artifact
   Store/CAS root, timeout, sanitized environment digest, source/workspace
   manifest identities, Tcl digest, vendor-launcher digest and, on Windows,
   the resolved system `cmd.exe` path/digest; sign that plan digest into the
   specialized lease request, then independently reconstruct and recheck the
   canonical argv/Tcl/launcher/interpreter immediately before spawn so a
   caller cannot make arbitrary Vivado Tcl safe merely by hashing it;
4. consume a caller-issued `NonRuntimeEffectAuthorization` and exact
   `EffectExecutionRequest` for the centrally registered
   `cli.daedalus_chip` entrypoint;
5. pass process-budget, the operator-owned confined write policy and
   containment decisions while the fail-closed operator kill switch is already
   armed; and
6. persist the durable effect start before any effectful version observation or
   Vivado process spawn.

`--confirm-project-writes` is an explicit operator acknowledgement that Vivado
can rewrite XPR/run state inside the isolated workspace. It is not a lease,
does not weaken write policy and does not arm the kill switch. A missing,
stopped or unreadable permit; a denied path; missing authority; or failed
containment refuses before Vivado starts.

Do not substitute one revision namespace for another. CLI
`--source-revision` is the authority Git HEAD (40 hex); source/workspace
manifest SHA-256 and Source Identity `/3` are design identities (64 hex). The
receipt and execution plan retain their distinct roles.

The admitted executor uses argv with `shell=False` and a managed process tree.
Timeout/cancellation reaps that tree. It continuously revalidates the injected
authority and kill switch while the child is live; revocation or an unreadable
authority cancels the tree. A failure that is safely proven to occur before
any child can exist may receive a terminal record. Once the durable effect is
`STARTED`, an ambiguous `ManagedProcess` constructor/spawn exception,
`KeyboardInterrupt`, `SystemExit`, or any other outcome for which child
existence cannot be proven false remains `STARTED` for explicit reconciliation.
Known completed outcomes receive one terminal record, and replay of a terminal
execution is inert; an ambiguous start is never silently retried or relabelled
failed.

The sanitized environment copies only a small platform allow-list, replaces
host `PATH` with the minimal system path, pins `TEMP`/`TMP` to the workspace,
and redirects `HOME`/`USERPROFILE`/`APPDATA` to a fresh phase/output-specific
workspace leaf. Installation startup Tcl and pre-existing profile leaves are
refused. That reduces accidental secret and host-state inheritance; it is not
an OS network sandbox. The lease grants no network capability, and
`security_boundary_claimed` remains false.

The launcher file and Windows command interpreter are byte-bound inputs, not a
claim that the whole vendor installation is hermetic. Vivado binaries loaded
behind the launcher, device data and vendor IP/board catalogs remain trusted
transitive installation state. A canonical receipt must state this residual
trust rather than presenting launcher hashing as complete toolchain identity.

Likewise, source/workspace disjointness is not a complete concurrent-tamper
boundary. The effect policy authorizes or refuses the declared write scope but
does not install an OS write boundary around the child. It cannot stop Vivado
or an independent host process from writing outside that logical declaration;
the operator-provided exclusive workspace remains required.

The phases produce the following declared files inside their selected output
directory:

| Phase | Required native outputs |
| --- | --- |
| `inspect` | `inspect_summary.txt` |
| `synth` | `synth_summary.txt`, `utilization.rpt`, `timing_summary.rpt`, `drc.rpt`, `methodology.rpt`, `design.dcp` |
| `impl` | `impl_summary.txt`, `utilization.rpt`, `timing_summary.rpt`, `drc.rpt`, `methodology.rpt`, `route_status.rpt`, `synth_design.dcp`, `design.dcp`, `design.bit` |
| `full` | the synthesis and implementation phase sets, retained with their phase provenance |

Vivado run-hook properties are cleared before a selected run. Any active file
with `FILE_TYPE=Tcl`, plus project/archive automation with `.tcl`, `.bat`,
`.cmd`, `.exe` or `.ps1` extensions, is refused. Declared `.xdc` constraints
are admitted only as `FILE_TYPE=XDC` and are intentionally executed by Vivado:
they are authoritative, operator-trusted constraint Tcl, not inert data. An
XDC can itself `source` or `exec`; these direct checks do not claim transitive
containment or form a security boundary. Runtime rechecks also refuse custom
IP/board repositories, include-directory roots, opaque core containers and
non-Xilinx IP definitions. Resolved project/default-launch/run/IP-output
directories are checked against the workspace before any run reset or launch;
the selected synthesis and implementation runs require non-empty,
workspace-local `DIRECTORY` properties.

For `synth` and `impl`, the trusted template disables and verifies the IP
synthesis cache, resets/force-regenerates active XCI/BD targets, resets every
synthesis run, disables synthesis and implementation incremental
checkpoint reuse, and launches a fresh synthesis. `impl` retains the resulting
`synth_design.dcp` before resetting and launching implementation, so it never
trusts a stale Complete/100% synthesis status. A CLI `full` run therefore has
two independently leased/evidenced phases and intentionally repeats synthesis
inside `impl`.

Console output, the exact native files and the structured execution receipt
are hashed and stored in the authority-root-derived content-addressed Artifact
Store before the effect is terminalized. A declared output missing after exit
zero makes the execution failed rather than silently successful. Each declared
artifact is read through one opened regular-file handle with stable file
identity, size and modification time checked before and after the read; a
replacement or torn read requires reconciliation instead of accepting a hash.
For a spawned process, the retained evidence includes the exact post-run
workspace manifest. A successful result requires it to be complete and its
Source Identity `/3` to match the pre-run authored identity; generated-product
changes may still change its exact manifest SHA-256.
Restarting
the same mission/attempt cannot mint a new chip lease; its deterministic lease
identity reaches the canonical replay refusal before another process exists.

### 2.5 Evidence is not signoff

Report parsers return `parsed`, `missing` or `unparseable`; only a valid native
report can supply zero findings. DRC and methodology pass only when
`checks_found=0` and every retained severity count is zero; warning-only
reports are findings, not passes. The phase summary requires the exact schema,
phase, project, part, top, runs, parseable Vivado version and phase-specific
completion/cache fields. Timing includes setup/hold/pulse-width values and
selected `check_timing` counts; its prose verdict must agree with slack,
negative-slack totals and failing endpoints. Utilization covers
LUT/register/BRAM/DSP, and DRC, methodology, route status and cumulative
message counts retain their native byte identities.

Even a routed, timing-met design with a bitstream is only evidence for the
checks that actually ran. G1-EDA-01 leaves lint, elaboration, simulation,
formal, CDC/RDC, equivalence, power, Vitis software, hardware-in-the-loop and
signoff explicit as `not_run` when no independent evidence exists. Process
exit zero cannot upgrade those dimensions.

### 2.6 Current supplied-project status

The supplied `tdc_light_version` XPR can be inspected read-only: the CLI emits
the manifest and then returns nonzero to signal `complete=false`. Inspection
finds a per-user `BoardPartRepoPaths` value pointing at the mutable Xilinx
board store. The board part is a semantically active Vivado input, so the
catalog cannot be discarded as relocation-only metadata. The manifest also
records a vendor-catalog MicroBlaze boot-loop resource; its transitive bytes
remain declared installation trust rather than hermetic source identity.
Because the custom board-catalog bytes are not content-addressed, the
effect-free `plan` command refuses. That refusal is the expected Gate-1 result
pending a pinned board catalog; inspect-plus-plan end to end is not an accepted
claim today.

As measured on 2026-08-30, the operator kill switch was `STOP` and the expected
`.agentenv/chip-eda-policy.json` did not exist. No canonical live process was
therefore admitted. A separate earlier Vivado 2025.1.1 synthesis/
implementation run emitted a bitstream but restored two cached out-of-context
IP results and did not traverse the canonical effect boundary. It remains
useful, explicitly non-clean-room historical evidence, not proof that this
workflow has completed the supplied project.

## 3. FPGA flow

The FPGA branch typically continues:

```text
RTL + constraints
  -> synthesize
  -> technology mapping
  -> place
  -> route
  -> static timing analysis
  -> DRC / implementation checks
  -> bitstream
  -> optional hardware-in-the-loop validation
```

### Vivado-oriented flow

Vivado is naturally automatable from Tcl. For an existing XPR, the canonical
G1-EDA-01 flow is section 2: separate source/workspace projects, static packaged
Tcl, admitted execution and retained native reports. Non-project mode or
agent-authored Vivado Tcl is not a substitute for that contract. Daedalus
consumes report data rather than merely checking whether `write_bitstream`
produced a file.

Recommended gates before accepting an implementation:

- synthesis completed without unreviewed critical warnings;
- implementation completed;
- timing constraints are present and clocks are recognized;
- worst negative slack / total negative slack meet project policy;
- no unacceptable DRC violations;
- utilization remains below project-defined headroom limits;
- generated bitstream/checkpoint belongs to the same run receipt.

### Quartus-oriented flow

The equivalent roles are project/configuration setup, analysis/synthesis,
fitter/place-and-route, TimeQuest timing analysis and assembler/programming
file generation. Quartus Tcl should be treated as a backend implementation of
the same semantic stages rather than as a separate conceptual workflow.

## 4. ASIC digital flow

A modern open RTL-to-GDS flow can be represented as:

```text
RTL + SDC + technology/PDK
  -> synthesis
  -> floorplan / die-core sizing
  -> IO placement
  -> tap/endcap insertion
  -> power distribution network
  -> global placement
  -> placement optimization / timing repair
  -> clock-tree synthesis
  -> post-CTS optimization
  -> global routing
  -> detailed routing
  -> parasitic extraction
  -> signoff timing / power checks
  -> physical verification (DRC/LVS according to the target flow)
  -> GDS/OASIS handoff
```

OpenROAD provides the physical-design engine and Tcl control surface; OpenLane
2 composes broader RTL-to-GDS flows around tools including Yosys, OpenROAD,
KLayout and other utilities. The exact stages vary with the PDK and flow.

### ASIC evidence gates

Daedalus should not call an ASIC run `done` from process exit code alone. A
useful result model has explicit dimensions:

- `logic`: synthesis/elaboration clean enough for policy;
- `timing`: setup/hold constraints and violations reported;
- `physical`: route/design-rule state;
- `power`: if measured by the configured flow;
- `equivalence`: when a formal equivalence step exists;
- `signoff`: only when the project's actual signoff tools/rules ran.

Open-source P&R completion is not automatically synonymous with commercial
foundry signoff. Daedalus should state which checks ran instead of inferring
unobserved checks.

## 5. Constraints are first-class code

Timing constraints must not be treated as secondary metadata. A design that
"passes timing" with missing clocks or false-path mistakes can be less correct
than one that visibly fails a valid constraint set.

For every run, capture:

- recognized clocks and periods;
- generated clocks;
- input/output delays where applicable;
- false/multicycle paths;
- asynchronous clock groups;
- unconstrained paths/endpoints reported by the tool.

Constraint changes should trigger the same level of review as RTL changes when
they alter what the implementation is required to prove.

## 6. Clock-domain crossings and resets

CDC/RDC problems require structural reasoning beyond ordinary simulation.
Future Daedalus hardware gates should include dedicated CDC/RDC analysis when a
backend is available. Until then agents should at minimum identify clock and
reset domains in their plans and avoid claiming that simulation alone proves
safe crossings.

## 7. Suggested Daedalus state machine

A hardware-aware task can expose progressively stronger states:

```text
discovered
  -> linted
  -> elaborated
  -> simulated
  -> formally_checked (optional/parallel)
  -> synthesized
  -> implemented
  -> timing_checked
  -> physical_checks_run
  -> artifact_ready
```

Each transition should name the evidence that justified it. Optional stages
remain explicit `not_run`, never implicit passes.

## 8. Receipts and reproducibility

For every external EDA action Daedalus should retain or make derivable:

- source revision;
- source/constraint manifest or digest;
- tool ID, resolved executable and version;
- argv and working directory;
- environment variables that affect the flow, redacted for secrets;
- the exact `EdaExecutionPlan` digest binding argv, cwd, artifacts, CAS root,
  timeout, sanitized environment, manifests, trusted Tcl, vendor launcher and
  Windows command interpreter;
- start/end or duration;
- exit code;
- bounded console output;
- report paths and important metrics parsed from them;
- output artifact digests where practical.

This lets an agent compare two runs on actual implementation evidence rather
than on prose such as "the tool succeeded".

## 9. Agent workflow for RTL changes

A conservative automated loop is:

1. understand the module/interface and affected clock/reset domains;
2. identify existing assertions/testbenches and constraints;
3. produce a bounded RTL patch;
4. run deterministic lint/elaboration;
5. run the smallest relevant tests/formal properties;
6. inspect warnings and exact failures;
7. synthesize when the change can affect area/timing/inference;
8. run implementation when closure is part of the task;
9. compare reports against the baseline;
10. present the patch plus receipts for review/promotion.

The optimization target is not "generate more HDL". It is the smallest change
that improves the requested hardware behavior while preserving verified
contracts and implementation margins.
