# Chip Design Toolchains

Daedalus should choose EDA tools by workflow role, not by brand. The initial
registry therefore records capabilities such as lint, simulation, synthesis,
formal, physical design and Tcl rather than pretending one tool covers every
stage equally well.

## Recommended role map

| Role | Useful tools | Daedalus use |
| --- | --- | --- |
| RTL inventory | built-in `chip_design.sources` | classify RTL, headers, constraints and flow scripts without starting a tool |
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
| AMD/Xilinx FPGA | Vivado | RTL synthesis, implementation, timing, reports, bitstream; Tcl automation |
| Intel/Altera FPGA | Quartus Prime | analysis/synthesis, fitter, TimeQuest, programming files; Tcl automation |

This table is a workflow map, not an instruction to install every tool on every
machine. `daedalus-chip status` exposes which registered capabilities are
actually present.

## RTL source intelligence

The dedicated hardware scanner recognizes:

```text
.v          Verilog RTL
.sv         SystemVerilog RTL
.vh/.svh    Verilog/SystemVerilog headers
.vhd/.vhdl  VHDL RTL
.xdc        Xilinx design/timing constraints
.sdc        Synopsys Design Constraints / timing constraints
.qsf        Quartus settings/assignments
.tcl        EDA automation
.do         simulator automation (classified, not executed by the Tcl command)
.sby        formal flow configuration
.f          source filelist
```

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

The currently researched contract uses Vivado 2026.1 documentation for batch
Tcl execution. The tool is appropriate for AMD/Xilinx device synthesis,
implementation, timing, DRC and bitstream flows.

High-value parsed metrics for a future adapter:

- WNS/TNS and hold metrics;
- unconstrained path counts;
- LUT/FF/BRAM/DSP utilization;
- route/implementation status;
- DRC severity counts;
- clock utilization/skew where relevant;
- critical warnings.

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

## What to implement next

Priority order after the first slice:

1. integrate Verilog/SystemVerilog/VHDL/Tcl into StructCore indexing;
2. parse Verilator/Verible diagnostics into structured findings;
3. add simulator + cocotb run receipts;
4. add Yosys synthesis report/netlist metrics;
5. add Vivado report parsers (timing, utilization, DRC);
6. add OpenROAD/OpenLane timing/area/DRC metric ingestion;
7. add a generic `ChipRun` evidence model shared by FPGA and ASIC backends;
8. add formal/CDC/equivalence gates as explicit optional dimensions.

That order gives Daedalus useful RTL reasoning and deterministic verification
before it starts optimizing expensive implementation flows.
