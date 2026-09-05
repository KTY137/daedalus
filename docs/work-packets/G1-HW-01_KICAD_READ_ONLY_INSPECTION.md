# G1-HW-01 — Effect-free KiCad inspection (isolated experiment)

Packet ID: G1-HW-01
Artifact role: primary
Active gate: Gate 1
Classification: `EXPERIMENT`
Owner: repository owner
Base revision: 585b7ea4e141332928ad6c9578b9c9997e55f247
Dependencies: none. It reads `daedalus/chip_design/` for shape only and imports
nothing from it; a test asserts the package is a leaf. Parent of no packet.
Plan revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.

**Iron Plan: EXPERIMENT.** Adopted plan Revision 12 has no PCB product strand.
`docs/AMENDMENT_PROPOSAL_013_HARDWARE_TARGETS_AND_SELF_RENOVATION.md` is a
proposal awaiting the owner, so this work is admitted only under master plan
section 1 ("scientific freedom"): a frozen, bounded, isolated experiment with an
explicit spec, budget, evaluator and expiry, wired into no production path and
eligible for no promotion. It supersedes the untracked draft
`docs/backlog/G1-HW-01_KICAD_READ_ONLY_INSPECTION.md`, which planned a wider
`ALIGNED` slice inside `daedalus/chip_design/` conditional on that adoption.

## Experiment record

- **Spec (frozen):** a new leaf package `daedalus/pcb_design/` with four
  read-only subcommands — `status`, `scan`, `inspect`, `plan` — and no other
  surface. Frozen at this packet's base revision; a change of scope is a new
  packet, not an edit to this one.
- **Scope:** exclusively `daedalus/pcb_design/**`, `tests/test_pcb_design*.py`,
  `tests/fixtures/pcb_design/**`, this packet and `docs/evidence/G1-HW-01/**`.
- **Budget:** one session, no monetary spend, no model calls, no network. The
  package's own runtime budget is its input bounds: 32 MiB default per file
  (256 MiB absolute ceiling), 200 nesting levels, 1 000 000 nodes, 20 000 files
  per scan.
- **Evaluator:** `pytest` over the five suites named below. It is deterministic
  and independent of the package: the fixture is hand-counted and the two
  report digests are pinned constants. No model judges anything here.
- **Expiry:** this experiment expires when amendment 013 is decided. If adopted,
  a successor `ALIGNED` packet re-homes the useful parts through the canonical
  kernel; if rejected, the package is deleted and this packet plus its evidence
  are retained as the negative record.
- **Kill criterion:** if the same unchanged fixture yields a different
  `report_sha256` across two supported KiCad point releases, or if supporting
  8.x and 9.x requires per-release parser forks, stop rather than widen the
  parser, and say so in an amendment.

## Primary acceptance claim

`python -m daedalus.pcb_design inspect <file.kicad_pcb|.kicad_sch>` parses one
KiCad 8/9 artifact with a pure-stdlib S-expression reader, binds the exact bytes
and SHA-256, and emits canonical JSON whose `report_sha256` is a pure function
of those bytes — identical from any directory, on any host, under either tab or
space indentation. Malformed, oversized, mistyped or unsupported-version input
produces a typed refusal with a frozen reason code and exit `3`, never a
partial parse and never a stack trace. The command performs no effect: with
process starts, sockets and every write API armed to raise, all four
subcommands complete, and the byte digest of the scanned tree is unchanged.

Explicit non-claim: a clean report is **not** evidence about the design. No ERC
or DRC verdict is produced, connectivity is not computed, and the board's net
table is the generator's claim rather than independent evidence. Every one of
those boundaries is emitted in the report's `limitations` array, not only in
prose.

## Scope

**In scope.** `daedalus/pcb_design/`: `sexpr.py` (bounded reader, typed
refusals), `sources.py` (artifact classification, project discovery),
`toolchains.py` (registry, effect-free discovery, pure probe interpretation),
`inspection.py` (board and schematic reports), `plan.py` (effect-free
description of the later effectful packet), `cli.py`, `__main__.py`,
`__init__.py`. Tests `tests/test_pcb_design_{sexpr,inspection,toolchains,cli,
isolation}.py` and the generator `tests/fixtures/pcb_design/__init__.py`.
Evidence under `docs/evidence/G1-HW-01/`.

**Forbidden and untouched.** Any `kicad-cli`, `pcbnew`, `kipy`, `ngspice` or
`gerbv` execution; any write, network call or process start; `pyproject.toml`
(no console script — auto-discovery already packages the module, so the file
needed no edit); the effect registry; any HTTP route; any desktop projection;
any `daedalus-chip` subcommand; `daedalus/chip_design/**`; `daedalus/spine/**`;
`daedalus/kernel/**`; `apps/**`; the master plan, its amendment chain,
`AGENTS.md`, `CLAUDE.md`, `.agentenv/**`, `.gitattributes` and every existing
test. `git status` on this branch shows only in-scope additions.

Also out of scope by design: following a sheet reference to another file,
resolving symbol or footprint library tables, reading the user's global KiCad
configuration, decoding embedded binary blobs, autorouting, fabrication output,
publishing, and any repair or edit of a KiCad file.

## Contracts and behavior

### Bounded reader

The KiCad dialect only: one root list, bare or double-quoted atoms, no
comments. The scanner is iterative on an explicit stack, so hostile nesting
answers `depth_exceeded` instead of crashing the interpreter. Quoting is
retained on every atom because the dialect distinguishes the keyword `signal`
from the string `"signal"`. Unknown string escapes are refused rather than
guessed, and `nan`/`inf` are rejected as coordinates although Python parses
them. Frozen refusal reasons: `not_a_file`, `unreadable`, `input_too_large`,
`max_bytes_out_of_range`, `invalid_encoding`, `malformed_sexpr`,
`depth_exceeded`, `node_budget_exceeded`, `unsupported_suffix`,
`unexpected_root`, `unsupported_format_version`. A `PcbRefusal` constructed
with an undeclared reason raises.

### Format gate

Board `20240108` (8.0) and `20241229` (9.0); schematic `20231120` (8.0) and
`20250114` (9.0). Anything else refuses as `unsupported_format_version`;
`--allow-unknown-version` parses it anyway, sets `complete: false`, records the
version in `limitations` and exits `1`. The version is never guessed silently.

### Reports

Board: format block, thickness, paper, full layer table with ordinals and user
names, copper-layer count, Edge.Cuts extents, net table, footprints
(reference, value, library link, layer, position, rotation, pad count,
attributes, pad nets), track/via/arc counts, zones. Schematic: format block,
sheet UUID, paper, title block, `lib_symbols` names, placed symbols (lib_id,
reference, value, footprint, datasheet, unit, in_bom/on_board/dnp, position),
sub-sheet references with `followed: false`, labels split into local, global,
hierarchical and netclass-flag, and wire/bus/junction/no-connect counts.

Outline extents are exact for lines, rectangles and circles (centre plus
radius). Arcs and curves contribute control points only, so the report sets
`extents_are_lower_bound: true`, declines to claim closure, and says so in
`limitations`. Edge.Cuts graphics living inside footprints are counted and
excluded, because applying the placement transform is not in this slice.

`report_sha256` covers the report minus that field. It contains no absolute
path, which is what makes it relocation-stable.

### Tool discovery

`status` starts no process, ever: a status call that shelled out would be an
unregistered effect entrypoint, which this repository's review rules class as a
release-blocking defect. `version` is therefore always empty and
`version_source` states provenance — `""`, `install_path` (a KiCad series read
out of an install directory name, explicitly *not* a running version), or
`probe`, which only `interpret_version_probe()` produces from output a caller
obtained elsewhere. A non-zero launcher that still printed a parseable banner
stays a `warning`, never a rewritten success. `pcbnew` and `kipy` are located
with `find_spec` and never imported; their rows state that absence in this
interpreter is not evidence that KiCad is absent, because KiCad ships `pcbnew`
inside its own bundled interpreter.

### Plan

`plan` emits argv **shapes** with unsubstituted `<placeholders>` for ERC, DRC
with schematic parity, netlist export, BOM export, Gerber export, drill export,
an independent gerbv render and an ngspice run, each with its evidence kind and
its exit-code semantics (`--exit-code-violations` returns 5 for violations;
1/2/3/4/6/7 stay distinct). `admissible` is `false` on every host by
construction and the report says so: the four unmet prerequisites are
governance (`amendment_013_adopted`, `effect_lease`, `bounded_write_root`,
`owner_approval`), and a missing binary is reported separately as the weaker,
host-local reason so it is never mistaken for the real blocker. Installing
every tool would not make `admissible` true.

### Exit codes

`0` answered; `1` incomplete (force-parsed unknown version, truncated scan,
inadmissible plan); `2` argparse usage; `3` typed refusal, printed as JSON.

## Acceptance matrix

| Claim | Deterministic evidence | Result |
| --- | --- | --- |
| Byte identity | report `artifact` equals an independently computed `hashlib.sha256` of the file; pinned `12f7b274…` / `f4e9affd…` | `test_pcb_design_inspection.py` (2 tests) |
| Report determinism | `report_sha256` pinned to `149fd4f3…` (board) and `d5cbea19…` (schematic); recomputed from the report body | 3 tests |
| Relocation stability | the same fixture written to a deeper directory yields an identical report | 1 test |
| Whitespace irrelevance | the fixture re-indented with tabs produces an identical report apart from artifact identity | 1 test |
| Hand-counted content | 2 footprints, 4 nets (3 named), 20 layers (2 copper), 40×30 mm closed outline, 2 segments + 1 via, 1 zone; 2 symbols, 1 sheet, 3 labels, 3 wires | 12 tests |
| Outline honesty | absent Edge.Cuts reports `present: false` with null extents; an open polyline reports `closed_polyline: false`; an arc sets `extents_are_lower_bound` and refuses to claim closure | 3 tests |
| Typed refusals | empty, unterminated, trailing-content, bad-escape, unbalanced, atom-outside-list, non-UTF-8, truncated, random-bytes, oversized, over-depth, over-node-budget, wrong root, wrong suffix, unsupported version, absent version | 26 tests |
| Refusal vocabulary is frozen | an undeclared reason raises at construction | 1 test |
| No invented version | every registry row reports `version: ""` and `probe_status` in `{not_run, not_imported}` | 12 tests |
| Discovery starts no process | `subprocess.Popen/run/check_output`, `os.system`, `os.popen` armed to raise; `all_tool_status()` completes | 1 test |
| Modules are never imported | `builtins.__import__` guarded against `pcbnew`/`kipy`; status still answers | 1 test |
| Install path is not a version | a planted `…/KiCad/9.0/bin/kicad-cli.exe` yields `install_series: "9.0"`, `version: ""` | 1 test |
| Override does not fall through | an override naming a missing file reports that, and does not silently use PATH | 1 test |
| Probe interpretation | clean banner → `ok`; exit 1 with banner → `warning`, not success; exit 127 → `failed`; `None` → "probe did not start"; ngspice and gerbv banners parse | 5 tests |
| Plan is inadmissible and says why | all four governance reasons present; placeholders unsubstituted; `executed: false` everywhere; missing binaries listed separately; shape digest ignores host measurements | 5 tests |
| No effect, by injection | process starts, sockets, `builtins.open` in write mode and `Path.write_*`/`mkdir`/`touch`/`unlink` armed; all four subcommands and the refusal path complete | 2 tests |
| The trap is not a no-op | a deliberate `os.mkdir` and a deliberate write-mode `open` inside the armed context both raise | 1 test (mutation guard) |
| Tree unchanged | SHA-256 over the whole tmp tree identical before and after scan + 2 inspects + plan + status; no `.daedalus*` directory; inspected file's size and mtime unchanged | 2 tests |
| No effect API in the source | AST over all 8 modules: no forbidden import, no write/spawn call, no write-mode `open` | 24 tests |
| Package is a leaf | AST: no module imports anything under `daedalus.*` | 8 tests |
| Not wired anywhere | no file under `daedalus/`, `tools/`, `configs/` or `pyproject.toml` mentions `pcb_design`, outside the package itself | 2 tests |
| Entrypoint works and propagates codes | `python -m daedalus.pcb_design` in a real subprocess returns 0 and 3 | 2 tests |

**Measured 2026-09-05:** `148 passed` across the five suites
(`docs/evidence/G1-HW-01/acceptance-run-20260905.log.txt`). Regression checks on
pre-existing suites: `tests/contracts/test_work_packet_index.py` `22 passed`
after the registry re-measurement described under *Migration*, and
`tests/test_byte_pin_eol_durability.py` `17 passed`, confirming the fixture
generator created no new unlisted byte-pin subject.

## Migration and rollback

Additive except for the packet registry. New: eight package modules, five test
modules, one fixture generator, this packet and two evidence files.
`pyproject.toml` is untouched — `[tool.setuptools.packages.find] include =
["daedalus*"]` already discovers the package and no console script is declared.

**Two shared files were modified, and both are derived census, not contract.**
Adding any primary packet document makes `tools/index_work_packets.py --check`
report a stale registry and turns `tests/contracts/test_work_packet_index.py`
red, so this packet also:

1. regenerated `docs/work-packets/index.json` from
   `tools/index_work_packets.py --render` (there is no `--write` mode; the file
   is the tool's own canonical output, written back preserving the working
   copy's CRLF form);
2. re-measured the moving census in `tests/contracts/test_work_packet_index.py`
   — `330 -> 331` tracked files, `264 -> 265` packet IDs and the `counts` block
   — and added `G1-HW-01` to `expected_primary_ids`. That file's own comments
   instruct the adding packet to do exactly this ("A MOVING CENSUS, not an
   invariant: re-measure it in the packet that adds or retires an artifact");
   the frozen legacy baseline and the metadata-completeness assertions were not
   weakened.

**Integration note.** Ten lanes are running in parallel and every lane that
adds a packet will collide on these same two files. The conflict is trivially
resolvable and must be resolved by re-deriving, never by hand-merging: after
merging all lanes, run `python tools/index_work_packets.py --render >
docs/work-packets/index.json`, then re-run the counts assertion and paste the
measured values. Hand-editing either file to make a test pass would be exactly
the drift the registry exists to catch.

Rollback is `git rm -r daedalus/pcb_design tests/fixtures/pcb_design
tests/test_pcb_design_*.py`. Because the package is a leaf that nothing
imports, removal cannot break another subsystem, and the isolation suite is the
standing proof of that. This packet and its evidence are retained after
rollback as the negative record.

The fixture is a Python generator writing into `tmp_path` rather than committed
`.kicad_pcb`/`.kicad_sch` files. That is a deliberate migration constraint:
`core.autocrlf` is true on this host, and a committed text fixture whose bytes
are hashed into a pin is the recorded "CRLF daemon" failure family documented at
the top of `.gitattributes`. That pin list is paired with
`tests/test_byte_pin_eol_durability.py`, whose census detects only three shapes
and would not have seen a new fixture; rather than create an unlisted byte-pin
subject or edit a shared file outside this lane, the fixture avoids the problem.

## Evidence, expected failures, and review

### Host measurement (2026-09-05, this box)

`docs/evidence/G1-HW-01/host-measurement-20260905.log.txt`. Windows 11
26200, CPython 3.13.14. `kicad-cli`, `kicad`, `ngspice` and `gerbv` are all
absent from PATH; there is no `C:\Program Files\KiCad` and no `(x86)` install;
the Python modules `pcbnew` and `kipy` are not importable in this interpreter.
So `status` reports six ABSENT rows with reasons, and `plan` exits `1` with
`missing_tools: [gerbv, kicad-cli, ngspice]` on top of the four governance
blockers. Nothing was faked and no fallback was substituted — that is the point
of the measurement.

### Expected failures retained

- **Format drift inside a stable series.** The version gate is a whitelist of
  four integers. A KiCad point release that bumps the token refuses rather than
  guesses; that refusal is the designed behaviour, not a regression.
- **KiCad 9 embedded files** (fonts, datasheets, 3D and SPICE models) are not
  decoded. They are out of scope, and a file that carries them still inspects.
- **Footprint-local Edge.Cuts** graphics are excluded from the extents; the
  count is reported and a limitation is emitted rather than a wrong box.
- **Arcs and curves** make the extents a declared lower bound. Computing true
  arc extrema is deliberately deferred.
- **`pcbnew` is absent even where KiCad is installed**, because KiCad bundles
  it in its own interpreter. The row says so instead of concluding.
- **Multi-sheet designs** are inspected one file at a time; a hierarchical
  design's full symbol set is not obtainable from the root sheet alone.

### Review questions

1. Does any code path start a process, open a socket, or open a file for
   writing? The isolation suite answers no three ways (AST, fault injection,
   before/after tree digest) and includes a mutation guard proving the trap
   fires. Is a fourth way needed?
2. Does anything reach this package from a wired surface? The wiring test
   greps `daedalus/`, `tools/`, `configs/` and `pyproject.toml` and finds
   nothing. Should `apps/` and `.agentenv/` be added to that sweep?
3. Is `complete: true` misleading? It means only that the format gate passed.
   The `limitations` array is never empty and states every boundary, but a
   consumer reading `complete` alone could still over-read it.
4. Is `plan` returning `1` on every host the right signal, or should an
   inadmissible-by-construction plan exit `0` because producing the description
   succeeded? The current choice makes "you cannot run this" the exit status.
5. The four supported version constants were taken from the superseded draft's
   cited KiCad sources, not re-verified online in this session, and no KiCad is
   installed here to check them against. They are the weakest input in this
   packet.
6. Should the pinned report digests live in the packet as well as the test, so
   a silent test edit is visible in review? They are currently only in
   `tests/test_pcb_design_inspection.py`.

### Not done, and why

No `kicad-cli` execution, no ERC/DRC evidence, no round-trip comparison against
KiCad's own netlist export, no Project Twin extraction, no library provenance
rows, no `.kicad_pro`/`.kicad_sym`/`.kicad_mod`/`.kicad_dru` parsing, no
multi-sheet hierarchy walk, no Genesis blueprint. Each needs either an effect
path or an adopted amendment; the superseded draft specifies most of them and
remains the right starting point for the successor packet.

Iron Plan: **EXPERIMENT**
Iron Gate: **1**
Evidence: **148 passed across five suites; host measurement recorded under
`docs/evidence/G1-HW-01/`; no promotion, no wiring, no effect performed**
