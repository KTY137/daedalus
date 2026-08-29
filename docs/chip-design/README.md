# Chip Design Workflows

This directory is the dedicated hardware-design knowledge base for Daedalus.
It intentionally keeps RTL, verification, FPGA, ASIC and EDA automation
material separate from the general agent/runtime documentation.

## What Daedalus supports in this first hardware slice

- RTL discovery and classification for Verilog (`.v`), SystemVerilog (`.sv`),
  headers (`.vh`, `.svh`) and VHDL (`.vhd`, `.vhdl`).
- Constraint/config discovery for XDC, SDC, QSF, SBY and source filelists.
- Tcl automation through explicit backends for Tclsh, AMD Vivado, Quartus
  Prime, Yosys and OpenROAD.
- Verilog/SystemVerilog lint command construction for Verilator and Verible.
- Tool availability/version probing for the registered EDA stack.
- Dry-run-first external execution with timeout, exit code, bounded stdout and
  stderr receipts. External processes are executed as argv with `shell=False`.
- Repository confinement for RTL files, Tcl scripts and include directories.

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

Run it only after inspecting the planned argv:

```text
daedalus-chip lint --tool verilator --top top rtl/top.sv --live
```

Plan a vendor Tcl flow:

```text
daedalus-chip tcl vivado flow/build.tcl --arg PART=xc7a35ticsg324-1L
daedalus-chip tcl quartus flow/build.tcl --arg Agilex
daedalus-chip tcl yosys flow/synth.tcl
daedalus-chip tcl openroad flow/pnr.tcl
```

Add `--live` to actually start the corresponding EDA executable. The same CLI
is available without installation as:

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

This slice supplies orchestration primitives and workflow knowledge. It does
not claim foundry signoff, analog/mixed-signal support, power-integrity signoff,
DFT/ATPG closure or equivalence closure. Those should be added as explicit
capabilities and evidence gates rather than hidden behind a generic `success`
status.
