# Chip Design Primary References

The first Daedalus hardware contracts were based primarily on tool-vendor or
project-maintainer documentation. These links are intended as anchors for
future adapter changes: when an argv shape or workflow assumption changes,
check the upstream contract rather than preserving accidental behavior.

## AMD Vivado

- Vivado Design Suite User Guide: Design Flows Overview (UG892), Vivado 2026.1 —
  batch Tcl launch with `vivado -mode batch -source <script>`:
  https://docs.amd.com/r/en-US/ug892-vivado-design-flows-overview/Launching-the-Vivado-Tools-Using-a-Batch-Tcl-Script
- Vivado Tcl command-line options / `-tclargs` are documented in AMD Vivado Tcl
  command references and launch-option documentation. Keep the Daedalus
  `-tclargs` mapping pinned to the currently supported Vivado CLI contract.

## Quartus Prime

- Quartus Prime Pro Edition 25.1 third-party simulation documentation — example
  batch Tcl form `quartus_sh -t <script file> [script args]`:
  https://www.intel.com/content/www/us/en/docs/programmable/683870/25-1/run-rtl-simulation-using-run-simulation.html
- Intel/Altera Quartus Tcl scripting documentation should be the authority for
  project/assignment/compile/report command behavior in future adapters.

## Yosys

- Yosys command-line reference — `-c, --tcl-scriptfile <tcl_scriptfile>`:
  https://yosyshq.readthedocs.io/projects/yosys/en/latest/cmd_ref.html
- Yosys Tcl command documentation:
  https://yosyshq.readthedocs.io/projects/yosys/en/latest/cmd/tcl.html

## Verilator

- Verilator executable and argument reference — including `--lint-only` and
  warning controls:
  https://verilator.org/guide/latest/exe_verilator.html
- Verilator overview:
  https://verilator.org/guide/latest/overview.html

## OpenROAD

- OpenROAD application/run documentation — command-file execution and options
  including `-no_init` and `-exit`:
  https://openroad.readthedocs.io/en/latest/main/README2.html
- OpenROAD documentation home / flow and tool documentation:
  https://openroad.readthedocs.io/

## OpenLane 2

- OpenLane 2 flow reference, including the Classic RTL-to-GDS flow:
  https://openlane2.readthedocs.io/en/stable/reference/flows.html
- OpenLane 2 documentation:
  https://openlane2.readthedocs.io/

## cocotb

- cocotb simulator support:
  https://docs.cocotb.org/en/stable/simulator_support.html
- cocotb documentation:
  https://docs.cocotb.org/en/stable/

## Verible

- Chips Alliance Verible project — SystemVerilog parser, linter, formatter and
  developer tools:
  https://github.com/chipsalliance/verible

## Surelog / UHDM

- Chips Alliance Surelog — SystemVerilog 2017 preprocessor, parser/elaborator and
  UHDM front end:
  https://github.com/chipsalliance/Surelog
- UHDM:
  https://github.com/chipsalliance/UHDM

## tree-sitter language coverage

- tree-sitter-language-pack:
  https://github.com/xberg-io/tree-sitter-language-pack

The project includes grammars for Verilog, SystemVerilog, VHDL and Tcl in its
language set, which makes it a candidate for the planned StructCore RTL/Tcl
integration. Grammar presence alone is not equivalent to full HDL elaboration;
preprocessing, parameters/packages, generate constructs and design hierarchy
can require stronger front ends such as Surelog/UHDM or the actual EDA tool.

## Reference policy

- Prefer official/vendor/project-maintainer documentation over blog examples.
- Record the tested tool version when implementing a backend contract.
- Do not silently assume command-line compatibility across major releases.
- Keep semantic workflow states stable even if a vendor command changes.
- Where documentation is ambiguous, Daedalus should refuse to guess an argv
  mapping and require an explicit adapter/test instead.
