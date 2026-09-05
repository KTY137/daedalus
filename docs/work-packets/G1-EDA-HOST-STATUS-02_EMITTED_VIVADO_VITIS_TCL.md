# G1-EDA-HOST-STATUS-02 - Emitted Vivado/Vitis-HLS Tcl a reviewer can read

Packet ID: `G1-EDA-HOST-STATUS-02`

Artifact role: primary

Classification: `EXPERIMENT`

Active gate: Gate 1

Owner: repository owner

Base revision: `cfe8d34b8ef1438156e6fa3e6982f5a30d91696f`

Dependencies: `G1-EDA-01` (the read-only Vivado inspection, planning and admitted project runner) and `G1-EDA-HOST-STATUS-01` (the measured host state this packet builds on)

Working-tree context: isolated worktree `.claude/worktrees/lane7-vivado-tcl`,
branch `loop/lane7-vivado-tcl`, stacked on `loop/stage3-failed-receipt`

Promotion: not requested

**Iron Plan: `EXPERIMENT`.** The owner wants Vivado/Vitis chip-design support;
no amendment has yet made it product scope, so this stays an isolated, bounded
experiment: read-only planning that emits its review artifacts into its own
payload, no new effect path, no promotion, no merge.

## Primary acceptance claim

`python -m daedalus.chip_design plan` can turn an inspected minimal Vivado
project into a canonical, byte-deterministic AMD Vivado batch-mode Tcl script
with explicit part, top module, run names, source list and output directory,
carrying the inspected XPR SHA-256, manifest digest, source identity and plan
digest as comments, and can turn a trivial C++ kernel into the equivalent
Vitis HLS `csynth` script, without starting any process. Each emitted script
carries a Tcl completeness verdict whose checker agrees with the installed
`tclsh` on a 35-case corpus, and an optional self-contained harness that a
plain `tclsh` parses with every vendor command and every effectful Tcl surface
stubbed. Emission writes no file: the scripts travel inside the plan payload,
and `--emit-tcl -` streams one to stdout for the operator to redirect. None of
this is claimed to be vendor acceptance: no AMD toolchain exists on this host,
and the emitted scripts have never been executed.

## Scope

**Frozen scope (in):** `daedalus/chip_design/tcl_emit.py` (new, pure),
the `plan` subcommand and its emission helpers in
`daedalus/chip_design/cli.py`, two discovery rows in
`daedalus/chip_design/toolchains.py`, the package re-exports in
`daedalus/chip_design/__init__.py`, `tests/test_chip_design_tcl_emit.py`,
`tests/test_chip_design_isolation.py`,
`docs/evidence/G1-EDA-HOST-STATUS-02/` and its packet-local
`.gitattributes`.

`docs/work-packets/index.json` is deliberately **not** touched. It was
already stale at the base revision `cfe8d34b` - `tools/index_work_packets.py
--check` reports `stale` there, and a regeneration adds eight *other* lanes'
packet rows (264 committed packet IDs versus 272 tracked) alongside this one.
Writing that file here would silently claim another lane's rows and guarantee
a merge conflict with every parallel lane. `--render` succeeds and emits this
packet correctly (all six required sections, `EXPERIMENT`, gate 1, base
revision, owner), so one regeneration at integration time covers every lane at
once.

**Forbidden (out):** the master plan, its amendment chain, `AGENTS.md`,
`CLAUDE.md`, anything under `.agentenv/`; the root `.gitattributes` byte-pin
list (shared with every other lane; this packet pins only its own evidence
directory, from inside it); the effect registry
(`daedalus/spine/effect_boundary.py`); the admitted live path
(`daedalus-chip run`, `executor.py`, `manifest.py`, `vivado_tcl.py`, the
package-owned `tcl/vivado_project_flow.tcl`); every other lane's paths;
installing a toolchain; KiCad.

**Budget:** one agent session, no monetary spend, no network egress, no
provider call. The only process this work started is `tclsh` for measurement,
run by the operator and by two skippable tests - never by the CLI.

**Evaluator:** `tests/test_chip_design_tcl_emit.py` for the contract,
`tests/test_chip_design_isolation.py` for the effect-free claim, plus the
pre-existing `tests/test_chip_*.py` suites, all run with the worktree-local
`.venv/Scripts/python.exe`. Two of the evaluators are deliberately not this
packet's own code: the Tcl completeness checker is measured against the real
`tclsh` on a retained corpus, and the isolation guard was mutation-tested by
reintroducing the rejected write.

**Expiry:** this experiment expires when the owner either amends the plan to
make chip design product scope, or declines it. Until then nothing here may be
promoted, and the emitted scripts remain review artifacts only.

## Contracts and behavior

**New module `daedalus/chip_design/tcl_emit.py` (pure).** No filesystem
access, no subprocess, no vendor discovery. Renderers are total functions
returning canonical UTF-8/LF text:

- `render_vivado_project_flow(scope=...)` for `inspect | synth | impl | full`.
  The script opens the project when it exists and otherwise recreates it with
  the explicit part and only the manifest-declared present design and
  constraint inputs, asserts part/top/board-part, runs synthesis and
  implementation with explicit run names and `-jobs`, writes checkpoints and
  the utilization/timing/DRC/methodology/route-status reports plus the
  bitstream into an explicit output directory, and writes a summary file
  carrying the bound XPR and plan digests.
- `render_vitis_hls_flow(...)` renders the `vitis_hls -f` C-synthesis script
  for one C/C++ translation unit: `open_project -reset`, `add_files`,
  `set_top`, `open_solution -reset -flow_target vivado`, `set_part`,
  `create_clock`, `csynth_design`, then a checked report copy and a summary.
- `render_parse_harness(script)` renders the self-contained `tclsh` harness:
  the subject script travels inside it as base64, so the harness reads no file
  and cannot be aimed at bytes the emitter never saw. It installs a recording
  stub for every vendor command, a `get_property` that answers with the value
  the script itself expects, and renamed `file`/`open`/`exit` so `mkdir`,
  `copy`, `delete`, `rename` and channel creation cannot write anything. It
  reports `complete`, `embedded_bytes`, `stub_calls`, `intercepted_exit` and
  `tcl_error`, and always prints `vendor_acceptance_claimed=0`. It needs Tcl
  8.6 for `binary decode base64`.
- `tcl_completeness(text)` implements Tcl's `info complete` semantics in
  Python: braces and quotes open only at a word start, `[` always opens a
  substitution, `#` comments only at a command position, backslash always
  escapes, and inside a brace-quoted word only braces and backslashes matter.

Every emitted value passes `tcl_brace_literal`, which **refuses** rather than
escapes `{`, `}`, `\`, `$`, `[`, `]`, `"`, control characters and newlines, so
no inspected value can break out of the brace literal it is written into. Paths
are normalised to forward slashes; relative source paths are bounded (no `..`,
no absolute, no duplicate).

**`plan` CLI.** New flags: `--target {vivado-project,vitis-hls}`,
`--emit-tcl [-]`, `--emit-harness [-]`, and the HLS-only `--top`, `--part`,
`--solution`, `--clock-period`. Behaviour:

- Without `--emit-tcl`/`--emit-harness` the Vivado plan payload is **byte
  identical to before this packet**; no `emitted_*` key appears.
- With emission, the payload gains `emitted_tcl` (and `emitted_harness`)
  carrying the script itself as `text`, plus schema, target, scope, sha256,
  byte length, line count, declared commands, bound identities, expected
  outputs, and the syntax check with `executed: false` and
  `vendor_acceptance_claimed: false`.
- **Emission writes no file.** The bare flag puts the script in the payload;
  `--emit-tcl -` additionally streams the raw script to stdout so the operator
  can redirect it, and the plan then goes to stderr rather than being dropped.
  Passing a path is a refusal that names the redirect instead. At most one of
  the two flags may take `-`, because there is one stdout.
- The plan digest embedded in the script is taken over the payload **without**
  its `emitted_*` rows, so the two are not mutually recursive.
- `--emit-harness` without `--emit-tcl` is refused: the harness embeds it.
- `--target vitis-hls` refuses the Vivado-only `--phase`, `--vivado`,
  `--synth-run`, `--impl-run`, `--jobs`; the Vivado target refuses `--top`,
  `--part`, `--solution`, `--clock-period`. The HLS payload states
  `live_runner_available: false` and keeps `invocation_template` a template,
  because `daedalus-chip run` still knows only the package-owned Vivado
  project flow and no file exists for an `argv` to point at.

**No new effect path.** `plan` spawns nothing and opens nothing for writing.
The first revision of this packet did write the emitted script to an
operator-named path; review rejected that, correctly. `cli.daedalus_chip`
declares `FILESYSTEM_WRITE`, but its only effect anchor is `begin_effect`
inside `run_admitted_eda`, so a write from `plan` was a second write path
beside the door's own admission - a release-blocking defect under this
repository's review rules, experiment or not. That write is deleted;
`tests/test_chip_design_isolation.py` now asserts its absence statically, by
fault injection and by measurement, and the registry row and its digest are
untouched. This packet adds no anchor, no lease, no authority, no promotion.

**`status`.** Two discovery rows join the existing `vitis`/`xsct` rows:
`vitis_hls` (`vitis_hls`, batch `-f`) and `vpp` (`v++`), with the standard AMD
Windows install layouts (`C:/Xilinx/<release>/Vitis_HLS/bin/...` and
`.../Vitis/bin/v++.bat`, plus the legacy `<product>/<release>` form) and the
`DAEDALUS_VITIS_HLS_COMMAND` / `DAEDALUS_VPP_COMMAND` overrides. Discovery
still starts no process: an absent tool reports `available:false`,
`command_path:""`, `probe_status:"not_run"`, and no invented version.

## Acceptance matrix

| # | Check | Result |
| --- | --- | --- |
| 1 | emitted Vivado script is byte-deterministic and digest-pinned for all four scopes | yes; `test_vivado_script_identity_is_pinned` pins sha256/bytes/lines per scope |
| 2 | emitted Vitis HLS script and parse harness are digest-pinned | yes; `test_vitis_hls_script_identity_is_pinned`, `test_parse_harness_identity_is_pinned` |
| 3 | repeated rendering is byte-stable, LF-only | yes; `test_rendering_is_byte_stable_across_calls` |
| 4 | XPR sha256, manifest digest, source identity, plan digest and trusted-Tcl digest are embedded as comments | yes; `test_vivado_script_binds_every_inspected_identity` |
| 5 | scope narrows the flow (no `launch_runs` in `inspect`, no `write_bitstream` in `synth`) | yes; `test_scope_narrows_the_emitted_flow` |
| 6 | no undeclared command word is emitted; every declared vendor command is used | yes; `test_emitted_scripts_use_only_declared_commands` |
| 7 | Tcl completeness checker agrees with the installed `tclsh` | yes; 35/35 agreement, `info-complete-agreement.txt`, and a live re-derivation test |
| 8 | the harness parses both emitted scripts under real `tclsh` and writes nothing | yes; rc 0, `complete=1`, `tcl_error=`, directory unchanged; `harness-run.txt` |
| 9 | emission never claims vendor acceptance or execution | yes; `executed:false`, `vendor_acceptance_claimed:false` in payload and script banner, `vendor_acceptance_claimed=0` in harness output |
| 10 | emission opens nothing for writing, anywhere | yes; `tests/test_chip_design_isolation.py` - AST scan of the emitter and of all 16 planning functions, fault injection with writes/spawns/sockets armed, and a tree-digest measurement - plus `fixture-project-after-plan.json` showing an empty review directory |
| 11 | emission is deterministic across runs and refuses a path argument | yes; `test_plan_emit_tcl_is_deterministic_across_runs`, `test_plan_emit_tcl_refuses_an_output_path` |
| 17 | the isolation guard catches the exact defect review found | yes; the write was reintroduced once and three independent checks fired, `isolation-mutation-check.txt` |
| 18 | the harness needs no companion file | yes; the base64 round-trip through real `tclsh` reports `embedded_bytes` equal to the pinned byte length |
| 12 | unsafe inspected values are refused, never escaped | yes; 18 Vivado and 7 HLS refusal cases |
| 13 | `plan` without emission is unchanged | yes; `test_plan_without_emission_is_unchanged` asserts no `emitted_*` key |
| 14 | the plan path starts no process | yes; every CLI test patches `acquire_chip_eda_lease`, `run_admitted_eda` and `execute_argv` to raise |
| 15 | `status` reports the Vitis family honestly on a host without it | yes; `vitis`, `vitis_hls`, `vpp`, `xsct` all `available:false`, `probe_status:"not_run"`, empty path/version |
| 16 | tests never require Vivado, Vitis or any vendor tool | yes; the only external binary any test touches is `tclsh`, and those tests skip when it is absent |

## Migration and rollback

Additive. The new module is new; the CLI change adds flags and one branch and
leaves the existing plan payload untouched when no emission flag is given; the
toolchain change appends two discovery rows. Nothing is migrated, no stored
artifact changes shape, and no existing digest pin moves.

Rollback is `git revert` of the single commit on `loop/lane7-vivado-tcl`, or
simply not integrating the branch. No state outside the working tree was
created: no lease, no ledger record, no evidence packet, no promotion.

## Evidence, expected failures, and review

**Measured host (2026-09-05, this machine).** The only EDA-adjacent tool that
resolves is `tclsh` 8.6.12 at `C:\Program Files\Git\mingw64\bin\tclsh.EXE`
(`windows`, `amd64`). All fourteen other registered tools report
`available:false` with an empty path and `probe_status:"not_run"`:
`verilator`, `verible`, `iverilog`, `ghdl`, `yosys`, `sby`, `openroad`,
`vivado`, `vitis`, `vitis_hls`, `vpp`, `xsct`, `quartus`. `command -v` agrees:
`vivado`, `vitis`, `vitis_hls`, `v++`, `xsct`, `quartus_sh`, `yosys`,
`openroad`, `verilator`, `iverilog` and `ghdl` are all absent. Full rows in
`docs/evidence/G1-EDA-HOST-STATUS-02/status.json`.

**Measured suites** (worktree-local `.venv/Scripts/python.exe`, CPython
3.13.14, `pytest` 9.1.1):

| Command | Result |
| --- | --- |
| `pytest tests/test_chip_design_tcl_emit.py` | 107 passed |
| `pytest tests/test_chip_design_isolation.py` | 28 passed |
| all nine chip suites together | 355 passed, 1 skipped in 278.66s |
| `pytest tests/test_byte_pin_eol_durability.py` | passed (this packet's evidence needs no root byte-pin line; its digests are computed in memory and its retained bytes are pinned by the packet-local `.gitattributes`) |
| `pytest tests/test_ignition_bundle_gitattributes.py` | **2 failed - pre-existing baseline red, not this packet.** `daedalus/orchestration/ikarus/computer_history.py` has no `.gitattributes` line; it entered at `b59b2628`, before this packet's base `cfe8d34b`, and lives outside this lane. `daedalus/chip_design/tcl_emit.py` is not in the evaluator-bundle closure and is not reported missing. |

One further honesty note on that table: an earlier contended run of the nine
suites (two pytest processes plus subprocess smoke tests on the same box)
reported `test_chip_eda_executor.py::test_live_authority_loss_cancels_known_
tree_then_terminalizes_cancelled[authority_fault1]` red. Re-run alone it passes
(2 passed in 9.43s), and the quiet full run above is green, so it is recorded
here as load-induced flakiness in a cancellation fault-injection test rather
than quietly dropped. This packet does not touch `executor.py`.

**Retained evidence** under `docs/evidence/G1-EDA-HOST-STATUS-02/`:

| File | Content |
| --- | --- |
| `status.json` | the fourteen discovery rows above |
| `tclsh-identity.txt` | `which tclsh`, `info patchlevel`, platform, machine |
| `info-complete-agreement.txt` | 35 cases, `tclsh` verdict vs the Python checker, `mismatches=0` |
| `emitted/*.tcl`, `emitted/*.harness.tcl` | the four emitted artifacts, rendered from synthetic pinned paths so they contain no host path and match the digests the tests pin |
| `isolation-mutation-check.txt` | the rejected write reintroduced once, the three guard failures it produced, and the revert |
| `emitted/manifest.json` | schema, target, scope, sha256, byte length, line count and syntax verdict per artifact |
| `harness-run.txt` | the contained `tclsh` dry parse of both scripts: rc 0, `complete=1`, no Tcl error, 42 and 11 stubbed vendor calls, `embedded_bytes` equal to the pinned lengths, directory unchanged |
| `plan-vivado-full.json`, `plan-vitis-hls.json` | real CLI payloads on a generated fixture, host paths replaced with `<FIXTURE>` / `<CHECKOUT>`; each carries its script inline as `emitted_tcl.text` |
| `fixture-project-after-plan.json` | the fixture after two emitting plan runs - project unchanged and the review directory still empty |

**Expected failures and honest limits.**

1. A live Vivado or Vitis HLS phase remains `blocked_external` on this host by
   construction. Nothing here moves that.
2. The Tcl completeness check is a *parseability* check. Real Vivado can reject
   a completely parseable script (unknown option, wrong part, missing IP). The
   harness stubs every vendor command, so it also cannot see a wrong argument
   spelling. Both surfaces say so in their own text and in every payload row.
3. The harness answers `get_property` with the value the script expects and
   makes `file exists` true, so it always walks the success path. It proves the
   command words resolve and the taken path raises no Tcl error; it proves
   nothing about the failure branches.
4. The 35-case corpus is the contract for the completeness checker, measured
   against one `tclsh` (8.6.12). A different Tcl release could in principle
   disagree; the live re-derivation test re-measures on whatever host runs it.
5. `emitted/*.tcl` are rendered from synthetic `C:/pinned/...` paths so the
   retained bytes carry no host path. A real emission embeds real absolute
   paths, which is why the fixture payloads are sanitised instead.
6. The `create_project` branch of the emitted Vivado script has never run. It
   is written from the manifest's declared inputs and reviewed on paper only.

**Review questions.** (a) *Asked, answered, acted on.* The first revision asked
whether one operator-named `.tcl` write was acceptable inside a command
documented as effect-free. The reviewer said no: `cli.daedalus_chip`'s only
effect anchor is `begin_effect` inside `run_admitted_eda`, so the write stood
beside the door's admission. The write is deleted, emission is inline, and
`tests/test_chip_design_isolation.py` makes the claim falsifiable. (b) Should
the emitted `create_project` fallback exist at all, or should the script refuse
a missing project outright? (c) Should `--target vitis-hls` live under `plan`
or under its own subcommand once an admitted HLS runner exists?

Iron Plan: **EXPERIMENT**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
