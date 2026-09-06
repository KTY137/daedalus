# Amendment proposal 013: Hardware targets and self-Renovation

Status: accepted 2026-09-06 08:48 (owner answer, verbatim option label: "Ja, exakt wie entworfen"; recorded in `docs/decisions-pending/OWNER_DECISIONS_20260906.md`); adopted as plan revision 13, amendment record sequence 12
Owner: repository owner. Date: 2026-09-05.
Classification: AMENDMENT. Active gate: 1.
Request: Daedalus should work like a persistent assistant ("Jarvis"), improve
itself, build apps through Genesis, and support PCB design with KiCad and chip
design with Vivado/Vitis.
Base plan: revision 12, version 2.3.0, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
Base HEAD: current working tree; this proposal does not change HEAD.

## Decision and reason

Map the owner's request onto existing architecture without new mythology or
control planes:

1. **"Jarvis" persistence** is the existing Ikarus assistant of section 7.2
   (Revision 12), with goals, product memory, skills, and full computer
   assistance through canonical Missions and policy-scoped tools. No new
   concept, no new control plane.

2. **"Self-improvement"** is Ariadne campaigns whose Renovation subject is the
   Daedalus repository itself. Propose as an explicit Gate-1 strand with hard
   limits: no automatic merge or promotion (Invariant 5), candidates never
   modify evaluator/policy/ledger (Invariant 3), owner OwnerApproval per
   promotion, isolated worktrees only, and a leakage rule: a candidate produced
   from the Daedalus repo may not touch `daedalus/spine`, kernel policy, the
   master plan, amendment chain, `AGENTS.md` or tests of its own evaluator.
   Daedalus will therefore never "improve itself" without the owner's per-change
   approval. This is a feature of the constitution, not a gap.

3. **Hardware targets** extend Genesis (sections 7 / 9 / 11 Gate 1) and the
   four-plane Twin with explicit support for PCB design (KiCad 8/9), FPGA/SoC
   (Vivado/Vitis: building on existing read-only XPR inspection and Vivado
   deterministic evaluators), and firmware. Evaluators must be deterministic
   tools (kicad-cli erc/drc, Vivado reports, Verilator/iverilog/GHDL
   simulators), never LLM judgment. Missing toolchains report `blocked_external`,
   not fallback. License and temporal provenance of imported symbols/footprints/IP
   is mandatory (section 9.1 rule).

## Exact proposed plan edits

### Insert new section 7.3 (Hardware design targets)

```
### 7.3 Hardware design targets

Genesis supports target materializations for PCB, FPGA/SoC, and firmware design.

**PCB projects** (KiCad 8/9 and later): `.kicad_pro`, `.kicad_sch`, `.kicad_pcb`
source files become ProductSpec inputs. Deterministic evaluators include
`kicad-cli erc`, `kicad-cli drc` for symbol/footprint/constraint validation,
and netlist/BOM extraction as Data plane artifacts. Symbols and footprints
remain Type plane; schematic/layout hierarchy are Code plane. Source Identity
follows symbol/footprint/library provenance with explicit version, license and
temporal binding; any imported library without declared provenance blocks the
manifest and is reported as `incomplete_sources`.

**FPGA/SoC projects** (Vivado/Vitis, AMD/Xilinx): build on the existing
read-only XPR inspection (docs/chip-design/README.md) and static Vivado Tcl
runner. RTL (Verilog/SystemVerilog/VHDL), block designs, HLS, and constraints
become source candidates; synthesis/implementation reports are deterministic
evaluators. Timing, utilization, DRC, methodology, and simulation receipt
contracts are expanded from G1-EDA-01 to support bounded Genesis synthesis and
implementation rounds. IP/block-design library provenance and vendor catalog
state are declared as explicit trust inputs.

**Firmware**: source targets for the selected board (ARM Cortex-M, RISC-V,
x86) with deterministic toolchain (GCC/Clang, LLVM) and evaluators (static
lint, unit test, simulation via GTest/pytest/cocotb). Bootloader and runtime
isolation is an explicit design statement, not inferred from target family.
Binary evaluators (checksum, size, symbol table) become Data plane artifacts
when relevant.

Daedalus does not claim to verify mixed-signal, power-integrity, thermal,
electrical safety, or manufacturing-readiness. Those remain explicit out-of-scope
dimensions.
```

### Insert new section 8.1 (Self-Renovation strand)

```
### 8.1 Self-Renovation strand

Ariadne may run controlled Renovation campaigns whose subject is the Daedalus
repository itself (code, tests, documentation, provider adapters). Each campaign
is an isolated, capability-bounded trial under the same Invariant rules:
candidates are content-addressed source trees, candidates cannot modify their
evaluator, policy, evidence ledger or promotion mechanism (Invariant 3/5).

Self-Renovation campaigns carry an additional leakage boundary: a candidate
produced from `daedalus/` sources may not edit `daedalus/spine`, `daedalus/kernel`
policy enforcement, the master plan (`docs/IKARUS_ARIADNE_MASTER_PLAN.md`),
amendment chain, `AGENTS.md`, or tests of its own evaluator. This prevents a
candidate from weakening its own constraints.

Every nominated candidate requires an explicit owner OwnerApproval per section
7.1 before promotion to the primary checkout. No self-nominated or auto-merged
candidate is admitted.
```

### Modify Gate 1 heading and append paragraph

Change:
```
### Gate 1 — Renovation, owner-directed Genesis and general computer assistance (active)
```

Append after the general-assistant paragraph:

```
Gate 1 also admits self-Renovation campaigns of section 8.1. Subject is the
Daedalus repository itself; evaluators are existing tests, deterministic lint,
and review-gating. Candidates are isolated, cannot edit their own evaluator or
Daedalus policy boundaries, and require owner OwnerApproval per candidate for
promotion. Self-Renovation neither advances the research gates nor claims
autonomous self-improvement without explicit approval.
```

### Add one row to section 13 (Forbidden default directions)

```
- an LLM-judgment gate for ERC, DRC, timing closure, or electrical validation
  in hardware designs; deterministic tools and independent human review only;
```

## Concrete implementation sequence

Each row becomes a separate Work Packet.

| ID | Slice | Existing or new seam | Acceptance claim | Kill criterion |
| --- | --- | --- | --- | --- |
| G1-HW-01 | KiCad read-only inspection + Twin extraction | New chip_design module for `.kicad_pro` parsing, symbol/footprint identity binding, schematic/layout graph | `daedalus-chip classify` parses a live KiCad 9 project without `kicad` binary; Twin extracts hierarchy, net names, design intent; provenance test on import library binds version/license | Parser fails on project version or KiCad library index format changes |
| G1-HW-02 | kicad-cli deterministic evaluators | New ERC/DRC runner and report parser under canonical EffectLease (mirrors G1-EDA-01 structure) | `kicad-cli erc/drc` runs in policy-scoped workspace; ERC/DRC passed state requires zero findings; report digest and version retained; missing kicad-cli reports `blocked_external` | ERC pass reported on design with known violation; parser misses severity count |
| G1-HW-03 | Genesis KiCad blueprint | ProductSpec, TargetFourfoldSpec, and MaterializationPlan for PCB via deterministic symbol/footprint selection; isolated candidate source tree; round-trip rebuild | KiCad project materializes from explicit symbol/footprint roster; candidate Twin rebuilds from the generated `.kicad_pro`; exact schematic netlist match between target and rebuilt | Materialized project has unresolved symbols or layout connectivity mismatch |
| G1-HW-04 | Vitis/HLS runner (on existing Vivado slice) | Extend G1-EDA-01 Vivado runner with HLS synthesis and Vitis software build phases | HLS C/Tcl input synthesizes to RTL; Vitis build produces `.elf` or `.bit` with zero ERC; simulation receipt binds cocotb test harness and pass/fail | HLS synthesis refuses on unsupported pragma or Vitis build fails with unhandled exit code |
| G1-SELF-01 | Self-Renovation campaign rehearsal on frozen Daedalus revision | Ariadne campaign on Daedalus repo itself; leakage boundary enforcement; isolated worktree; owner approval per nomination | Freeze a Daedalus source revision and seed policy; run one deterministic repair (e.g. lint compliance, test coverage gap); nominate if evidence shows improvement; owner OwnerApproval blocks or admits promotion; no auto-merge | Candidate edits `daedalus/spine`; nominated without independent evidence; promotion proceeds without owner approval |

## Baseline and sources

Existing hardware integration: `docs/chip-design/README.md`, `TOOLCHAINS.md`,
and `daedalus/chip_design/` provide read-only XPR inspection and one Vivado
batch Tcl runner. KiCad support is absent. Vitis/HLS are named future work in
TOOLCHAINS section 327. Self-Renovation campaigns have no live producer; the
canonical campaign rehearsal (G1-ARIADNE-01) exists as a controlled trial, not a
self-mutation loop.

No edit to any codebase is proposed by this document. The amendment records
architectural scope; individual Work Packets provide build/review/evidence
chains.

## Alternatives, migration, rollback

Alternatives: retain FPGA-only hardware support (does not meet PCB request);
run KiCad autonomously outside Daedalus (does not integrate into Twin); gate
hardware validation on LLM critique (violates Invariant 4 evidence boundary);
promote self-Renovation candidates without owner approval (violates Invariant 5
sealed promotion).

Migration: each Work Packet is additive and gated. Existing Genesis Web/CLI and
Vivado G1-EDA-01 remain valid. Hardware targets activate after their acceptance
matrix passes. Self-Renovation campaigns are opt-in and require explicit owner
campaign start. Existing uncommitted work is preserved.

Rollback: disable the affected adapter for new work, cancel active leases,
retain evidence. Constitutional rollback is a new amendment. Hardware-target
rollback does not retract Ikarus assistant or general-computer-assistance
strands (Revision 12). Self-Renovation rollback stops campaign creation and
promotes no further candidates; running Attempts remain under their leases and
may not be retroactively forbidden.

## Owner approval request

This proposal maps your explicit 2026-09-05 requests onto Daedalus architecture
with no new mythology, new control planes, or weakening of Invariants 3 and 5.

To adopt: reply with explicit approval and proceed with the numbered Work
Packets in dependency order. The amendment will record your approval, increment
the plan revision to 13, and append one adopted amendment record to
`docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl` before any implementation
begins.

No file other than this proposal was changed to produce it.
