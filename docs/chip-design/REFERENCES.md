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
- [Vivado Tcl Scripting (UG894): initializing Tcl scripts](https://docs.amd.com/r/2024.1-English/ug894-vivado-tcl-scripting/Initializing-Tcl-Scripts)
  documents installation- and user-level startup Tcl. This is the upstream
  basis for refusing ambient init files rather than assuming batch mode is
  automatically free of startup state.
- [Using Constraints (UG903): constraint-file order](https://docs.amd.com/r/en-US/ug903-vivado-using-constraints/Constraint-Files-Order)
  establishes that ordered XDC inputs affect the design result.
- [Using Constraints (UG903): entering XDC constraints](https://docs.amd.com/r/en-US/ug903-vivado-using-constraints/Entering-XDC-Constraints?contentId=eIp1udAqjJ9J8NVbdpKeWg)
  documents XDC command execution and file properties. XDC is Tcl behavior,
  not inert data or a security boundary.
- [`config_ip_cache` Tcl command (UG835)](https://docs.amd.com/r/2024.1-English/ug835-vivado-tcl-commands/config_ip_cache)
  is the command authority for explicitly disabling and verifying IP-cache use.
- [Using Tcl commands to reset and generate target IP (UG896)](https://docs.amd.com/r/2025.1-English/ug896-vivado-ip/Using-Tcl-Commands-to-Reset-and-Generate-Target-IP)
  and [`generate_target` (UG835)](https://docs.amd.com/r/2024.1-English/ug835-vivado-tcl-commands/generate_target)
  anchor the reset/force-regeneration sequence.
- [`IP_REPO_PATHS` property (UG912)](https://docs.amd.com/r/en-US/ug912-vivado-properties/IP_REPO_PATHS)
  and [IP Packager XGUI Tcl outputs (UG1118)](https://docs.amd.com/r/2023.2-English/ug1118-vivado-creating-packaging-custom-ip/Outputs-from-IP-Packager)
  show why a custom IP repository is executable/transitive input and is
  refused until its complete catalog is content-bound.
- [Synthesis include files (UG901)](https://docs.amd.com/r/en-US/ug901-vivado-synthesis/Include-Files)
  and [memory initialization through file-I/O tasks (UG901)](https://docs.amd.com/r/en-US/ug901-vivado-synthesis/Loading-Memory-Contents-With-File-I/O-Tasks)
  anchor the Gate-1 refusal of unclosed Verilog include and `$readmem*` inputs.
- [Adding user boards to a repository (UG895)](https://docs.amd.com/r/2024.2-English/ug895-vivado-system-level-design-entry/Adding-User-Boards-to-a-Repository)
  establishes the board catalog as a semantically active project input; a
  mutable per-user board repository cannot be normalized away as relocation
  metadata.
- [`write_project_tcl` (UG835)](https://docs.amd.com/r/2024.2-English/ug835-vivado-tcl-commands/write_project_tcl)
  and [Vivado project general settings (UG895)](https://docs.amd.com/r/en-US/ug895-vivado-system-level-design-entry/General-Settings)
  are supporting references for FileSet/project configuration and reproducible
  project state. They do not make XPR a stable public schema.

The documentation version above establishes the launch contract; it is not a
claim that report formats are identical across releases. The retained
G1-EDA-01 bench evidence was produced by Vivado 2025.1.1. Native timing,
utilization, DRC, methodology, route and message parsers are frozen against
those retained shapes and must return `unparseable`, not guessed metrics, when
a future format does not satisfy the contract.

Vivado XPR is parsed as bounded, untrusted XML for the fields exercised by the
retained project fixtures. Daedalus does not advertise a complete public XPR
schema. New project-format variants require a fixture and a focused manifest
test before the parser contract is widened.

The repository-local implementation authority for this slice is
[`G1-EDA-01_CANONICAL_VIVADO_PROJECT_RUN.md`](../work-packets/G1-EDA-01_CANONICAL_VIVADO_PROJECT_RUN.md).
It requires package-owned Tcl, source/workspace separation, canonical effect
admission and retained negative evidence; upstream vendor documentation does
not replace those Daedalus policy boundaries.

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
