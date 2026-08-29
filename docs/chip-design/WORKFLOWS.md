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

## 2. FPGA flow

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

Vivado is naturally automatable from Tcl. A batch flow commonly creates/opens
the project or uses non-project mode, reads RTL/constraints, synthesizes,
implements, emits reports, and writes a bitstream/checkpoint. Daedalus should
consume report data rather than merely checking whether `write_bitstream`
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

## 3. ASIC digital flow

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

## 4. Constraints are first-class code

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

## 5. Clock-domain crossings and resets

CDC/RDC problems require structural reasoning beyond ordinary simulation.
Future Daedalus hardware gates should include dedicated CDC/RDC analysis when a
backend is available. Until then agents should at minimum identify clock and
reset domains in their plans and avoid claiming that simulation alone proves
safe crossings.

## 6. Suggested Daedalus state machine

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

## 7. Receipts and reproducibility

For every external EDA action Daedalus should retain or make derivable:

- source revision;
- source/constraint manifest or digest;
- tool ID, resolved executable and version;
- argv and working directory;
- environment variables that affect the flow, redacted for secrets;
- start/end or duration;
- exit code;
- bounded console output;
- report paths and important metrics parsed from them;
- output artifact digests where practical.

This lets an agent compare two runs on actual implementation evidence rather
than on prose such as "the tool succeeded".

## 8. Agent workflow for RTL changes

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
