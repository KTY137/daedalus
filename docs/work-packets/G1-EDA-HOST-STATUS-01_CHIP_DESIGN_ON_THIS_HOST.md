# G1-EDA-HOST-STATUS-01 — What the chip-design slice can do on this host today

Packet ID: G1-EDA-HOST-STATUS-01

Artifact role: primary

Classification: `EXPERIMENT`

Active gate: Gate 1

Owner: repository owner

Base revision: b59b2628ad6ed85a8b5e729a12c58512543e2e73

Working-tree context: isolated worktree `.claude/worktrees/stage3-failed-receipt`, branch `loop/stage3-failed-receipt` (commit 9e0a34b8)

Dependencies: `G1-EDA-01` (the existing Vivado read-only inspection, planning and runner slice documented under `docs/chip-design/`)

Stage: 10 of the owner-directed 2026-09-05 loop; a measurement toward the owner's Vivado/Vitis goal, not a code change.

## Primary acceptance claim

The chip-design slice that already exists in Daedalus reports its tool availability and file classification honestly on this host: the only EDA-adjacent tool present is a Tcl shell from Git for Windows; Vivado, Vitis, XSCT, Quartus, Yosys, OpenROAD, Verilator, Verible, Icarus, GHDL and SymbiYosys are reported `available: false` with empty paths and no probe run, never as a host fallback or a guess. The classifier maps RTL, constraints and Vivado project artifacts to their planes without a tool.

## Reproduced baseline (measured 2026-09-05, 15:17)

`python -m daedalus.chip_design status --json` (effect-free, read-only discovery):

| Tool | available | roles |
| --- | --- | --- |
| tclsh (Git for Windows) | true | tcl |
| verilator | false | lint, simulation |
| verible | false | style_lint, syntax |
| iverilog | false | simulation, compile |
| ghdl | false | simulation, compile |
| yosys | false | synthesis, formal_frontend, tcl |
| sby | false | formal |
| openroad | false | physical_design, sta, tcl |
| vivado | false | fpga, synthesis, implementation |
| vitis | false | embedded_software, hardware_platform |
| xsct | false | embedded_software, tcl |
| quartus | false | fpga, synthesis, implementation |

`python -m daedalus.chip_design classify top.v top.sv pkg.vhd constraints.xdc design.xpr bd.bd ip.xci top.kicad_pcb --json`: Verilog, SystemVerilog and VHDL sources classify as synthesizable RTL (`design/source`), `.xdc` as `fpga/constraints`; the Vivado project, block-design and IP identities are recognised; `top.kicad_pcb` is not a known kind, which is expected: KiCad support does not exist yet and is the subject of amendment proposal 013 and the `G1-HW-01` backlog draft.

Retained under `docs/evidence/G1-EDA-HOST-STATUS-01/` (`status.json`, `classify-sample.json`), user-profile paths replaced.

## Effect-free inspection and planning on a generated minimal project (stage 11, measured 2026-09-05, 15:38)

Fixture from `tests/test_chip_cli_canonical.py::_write_project` (`demo.xpr`, `top.sv` with `module top; endmodule`, `pins.xdc`) materialized under the session scratch directory, then `python -m daedalus.chip_design`:

| Command | Result |
| --- | --- |
| `scan <project> --json` | 3 sources; kinds `constraint`, `project`, `rtl` |
| `inspect demo.xpr --json` | `complete: true`, part `xc7a35ticsg324-1L`, top `top`, source identity `78b9ff9f9f450259adaf78417152813f67df9fc0b1be255ff72cc861722b488f`, no missing or outside references |
| `plan demo.xpr --phase inspect|synth|impl --json` | rc 0 for all three; `argv[0] == "vivado"`, manifest `9ba1f74eb0af4916c492783baf84ccb9983dd357ca1dfa5b0559331ab3421ddf` and the same source identity bound in every phase; trusted Tcl digest, effects, promotion and `security_boundary_claimed` fields present; nothing executed |
| fixture after the runs | byte-identical file set |

Retained under `docs/evidence/G1-EDA-HOST-STATUS-01/fixture/results.json` (user-profile paths replaced). Because Vivado is absent on this host, the plan is the most this machine can produce; it is deterministic (identical digests across phases) and a live phase would be `blocked_external`.

## Reading

For the owner's Vivado/Vitis goal, the honest state is: read-only XPR inspection, effect-free planning, report parsing and a Vivado project runner exist in the tree (see `docs/chip-design/README.md`), but on this developer machine no vendor toolchain is installed, so every live phase is `blocked_external` by construction. A live Vivado receipt needs a host with Vivado; nothing here claims one. Vitis/HLS is planned in amendment 013 as `G1-HW-04` on top of the existing slice.

## Scope

Measurement only. Out of scope: installing toolchains, any change to the chip-design modules, KiCad.

## Contracts and behavior

No contract changes; the CLI commands used are the registered read-only `status` and `classify` surfaces.

## Acceptance matrix

| Check | Result |
| --- | --- |
| tool discovery reports absence honestly (no fallback, no guess) | yes: 11 of 12 tools `available: false`, empty paths, `probe_status` not run |
| classifier maps RTL/constraints/Vivado identities | yes; unknown kind for `.kicad_pcb` as expected |
| retained evidence carries no user-profile path | yes |
| effect-free `scan`/`inspect`/`plan` on a generated minimal XPR | all rc 0, deterministic identities, fixture unchanged |

## Migration and rollback

Evidence only.

## Evidence, expected failures, and review

Codex review requested as a free room turn. The effect-free `inspect`/`plan` measurement is recorded above (stage 11).

Iron Plan: **EXPERIMENT** (measurement; no code change)

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
