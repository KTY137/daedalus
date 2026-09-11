# G1-HW-01 — KiCad read-only inspection and Project Twin extraction

**Classification: BACKLOG draft, awaiting amendment 013 approval; no production
code until approved.**

**Location note (2026-09-05):** this draft lives under `docs/backlog/` on purpose. The canonical packet index (`tools/index_work_packets.py`) admits only `ALIGNED`, `AMENDMENT` or `EXPERIMENT` primary packets, and a `BACKLOG` draft must not appear index-canonical before amendment 013 is adopted. Move it to `docs/work-packets/` with a canonical `Packet ID:` line and an allowed classification only then.

## Frozen packet metadata

- Packet ID: `G1-HW-01`; artifact role: primary
- Classification: `BACKLOG`; becomes `ALIGNED` only if
  `docs/AMENDMENT_PROPOSAL_013_HARDWARE_TARGETS_AND_SELF_RENOVATION.md` is
  adopted as plan Revision 13 with its section 7.3 and section 13 row
- Active gate: Gate 1
- Owner: repository owner
- Base revision: `61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0`
- Design authority: master plan Revision 12, SHA-256
  `126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`
  (measured 2026-09-05; equals the amendment's base)
- Dependencies: `daedalus/chip_design/` manifest and CLI seams from G1-EDA-01,
  source-tree CAS, EvidencePacket contracts. Parent of G1-HW-02 (kicad-cli
  evaluators) and G1-HW-03 (Genesis blueprint); neither starts before this
  packet is green and reviewed
- Promotion: forbidden
- Host baseline (measured 2026-09-05): no `C:\Program Files\KiCad`, no
  `kicad-cli` on PATH; KiCad is absent from the tree except amendment 013

## Primary acceptance claim

`daedalus-chip inspect PROJECT.kicad_pro --project-root ROOT --json` parses one
KiCad 8.x/9.x project directory without any KiCad binary, records the exact
bytes and SHA-256 of the project file, every reachable schematic sheet, the
board, the project-local library tables and design rules, binds a
relocation-stable KiCad Source Identity, emits a four-plane Twin extraction
plus library-provenance rows, and returns nonzero whenever `complete=false`.
As in the Vivado slice, an incomplete manifest is still emitted; read-only
inspectability never implies completeness. The command acquires no lease,
spawns no process and writes nothing.

## Scope

Included: bounded JSON parser for `.kicad_pro`; bounded s-expression reader
for `.kicad_sch`, `.kicad_pcb`, `.kicad_sym`, `.kicad_mod`, `sym-lib-table`,
`fp-lib-table`, `.kicad_dru`, `.kicad_wks`; hierarchy walk over `sheet`
file-name properties; manifest, identity, Twin extraction, provenance and
refusal evidence; two frozen fixtures (one 8.0, one 9.0) with declared licenses.

Excluded: any `kicad-cli` execution (G1-HW-02); a Genesis KiCad blueprint or
materialization (G1-HW-03); autorouting; Gerber, drill, STEP, ODB++ or
IPC-2581 export; fabrication, publishing or ordering; editing or upgrading any
KiCad file (`sym upgrade`/`fp upgrade` are effects); reading the user's global
library tables or KiCad configuration; corpus-scale library ingestion; IPC API
or SWIG scripting; LLM critique of any kind.

## Contracts and behavior

### Inspector and Source Identity

- `.kicad_pro` is JSON (`PROJECT_FILE` derives from `JSON_SETTINGS`); the other
  files are UTF-8 s-expressions with quoted strings and millimetre units.
  Parsers are bounded in size and depth and treat every file as untrusted.
- Format gate on the `version` token: schematic and symbol `20231120` (8.0);
  schematic `20250114` and symbol `20241209` (9.0); board `20240108` (8.0) and
  `20241229` (9.0). Any other value is `unsupported_format_version`, reported
  rather than guessed. `generator` and `generator_version` (8.0+) are retained.
- KiCad Source Identity `/1` binds the authored bytes of project, ordered
  sheets, board, project-local library tables, `.kicad_dru`, `.kicad_wks` and
  the resolved sheet order. It excludes `.kicad_prl`, `fp-info-cache`,
  backup/lock files, `pcbnew.last_paths.*` and GUI state (`board.viewports`,
  `board.3dviewports`, `board.layer_presets`) only after those values pass the
  path checks below. `text_variables`, `net_settings`, ERC/DRC severities and
  `drc_exclusions` stay inside the identity because they change evaluator
  output. The exact directory manifest separately binds every other byte.

### Four-plane Twin mapping (PRIOR, not fact)

| Plane | Extracted from | Not claimed |
| --- | --- | --- |
| Code / AST | sheet hierarchy; `symbol` instances with `lib_id`, unit, `Reference`, `Value`, `Footprint`, `Datasheet`; `label`, `global_label`, `hierarchical_label`; wires, buses, junctions, `no_connect`; board `footprint`, `net` ordinals, tracks, zones | connectivity correctness; that is ERC/DRC evidence |
| Type | `lib_symbols` cache, referenced `.kicad_sym`/`.kicad_mod` entries, pin electrical types, `net_settings` classes, `.kicad_dru` rules, board design settings | a universal electrical oracle |
| Data | netlist and BOM as inspector-derived tables; the kicad-cli exports become the independent comparison in G1-HW-02 | a parts database |
| Knowledge | README/notes, `Datasheet` fields, `text_variables`, title blocks, library-table `descr` fields | authority above sources or evidence |

The schematic embeds its own `lib_symbols`, so the Code plane needs no library
access; libraries are Type-plane provenance inputs. Whether this split beats a
flat file inventory is measured, not assumed, and Gate-2 ablations may revise it.

### Refusal rules (mirroring the Vivado slice)

Each rule yields a visible reason and `complete=false`; none is normalized away:

- `missing`, `unreadable`, `unresolved` or `outside` sheet, symbol-library or
  footprint-library reference; links and junctions; absolute paths;
- `unbound_library`: a table `uri` using `${KICAD8_*}`, `${KICAD9_*}` or
  `${KICAD9_3RD_PARTY}`, or a nickname present only in the user's global table.
  Those variables are internal to KiCad and invisible outside it, and the global
  table lives in the mutable user configuration directory, the analogue of
  Vivado's `BoardPartRepoPaths`. `${KIPRJMOD}` is accepted only when it resolves
  inside the root;
- `path_bearing_project_setting`: `schematic.legacy_lib_dir`,
  `schematic.legacy_lib_list`, `cvpcb.equivalence_files`,
  `pcbnew.page_layout_descr_file` and any `last_paths` value escaping the root;
- `opaque_binary`: KiCad 9 embedded-file blobs (fonts, datasheets, 3D models,
  SPICE models), referenced `model` files, PDFs and images are hashed and
  listed, never decoded, rendered or executed;
- `blocked_external`: any consumer needing a kicad-cli report while no admitted
  tool exists. There is no host fallback, GUI automation or model-authored
  substitute.

### Deterministic evaluators (contract inherited by G1-HW-02)

Evidence comes only from `kicad-cli sch erc --format json`,
`kicad-cli pcb drc --format json --schematic-parity`,
`kicad-cli sch export netlist --format kicadsexpr|kicadxml` and
`kicad-cli sch export bom`, run in an isolated workspace under the canonical
EffectLease. `--exit-code-violations` returns 0 or 5; the CLI header also
defines 1 (args), 2 (unknown), 3 (invalid input), 4 (output conflict),
6 (jobset failed) and 7 (unknown format), each retained distinctly. Report
parsers return `parsed|missing|unparseable`; a pass requires zero `violations`,
zero `unconnected_items` and zero `schematic_parity` entries at every retained
severity, with `kicad_version`, `coordinate_units` and the `kicad-cli version`
string bound. Warnings are findings, not passes. An LLM judgment is never an
ERC/DRC gate (plan section 13; amendment 013 row).

### License and temporal provenance (plan 9.1)

Every library nickname produces a row: `type`, `uri`, resolved in-tree bytes
and SHA-256, declared license, library version tag or commit, retrieval date
and redistribution flag. The official KiCad libraries are CC-BY-SA 4.0 with an
exception waiving article 3 for designs and their generated files;
redistributed library collections keep the license and attribution. A library
or embedded file without declared license, version and date blocks the manifest
as `incomplete_sources`.

## Acceptance matrix

| Claim | Deterministic evidence |
| --- | --- |
| Exact identity | byte counts and SHA-256 of every bound file equal an independent `sha256sum`; a relocated copy yields the same Source Identity `/1` and a different exact manifest digest |
| Format gate | 8.0 and 9.0 fixtures parse; a synthetic `20260101` version and a legacy `.sch` refuse with `unsupported_format_version` |
| Hierarchy | sheet order, page numbers and instance paths match the fixture; a sheet moved outside the root gives `complete=false` and exit nonzero |
| Twin extraction | symbol, net and footprint counts equal hand-counted fixture values; net names match the fixture's frozen kicad-cli netlist bytes, not a live run |
| Refusals | each rule above has a mutant fixture and turns red when its check is disabled |
| Provenance | a `${KICAD9_SYMBOL_DIR}` library without declared license, version and date yields `unbound_library` and `incomplete_sources`; a declared in-tree snapshot yields a complete row |
| No effects | before/after directory hashes are identical; no lease, process or `.daedalus-chip` write occurs |
| Kill criterion | if unchanged fixtures produce different Source Identity `/1` across two supported point releases, or 8.x/9.x support needs per-release parser forks, stop the track and propose an amendment instead of widening the parser |

## Forbidden paths

`daedalus/spine/**`, `daedalus/kernel/**`, `docs/IKARUS_ARIADNE_MASTER_PLAN.md`
and its amendment chain, `AGENTS.md`, `CLAUDE.md`, the Vivado runner
(`executor.py`, `execution_plan.py`, `vivado_tcl.py`, `tcl/`), `apps/**` and
every existing test. In scope after approval: new
`daedalus/chip_design/kicad_*.py`, one `cli.py` subcommand registration,
`tests/test_chip_kicad_*.py`, `docs/chip-design/KICAD.md`, this packet.

## Migration and rollback

Additive. Rollback removes the module, subcommand and docs page and retains
fixtures, negative results and this packet.

## Evidence, expected failures and review

Expected failures to retain: format drift inside a stable series; KiCad 9
embedded files; libraries reachable only through KiCad path variables;
`.kicad_dru` exclusion severities reported as errors by the CLI (GitLab issue
24264, open at 9.0.7/10.0.1), which proves GUI and CLI can disagree, so only the
CLI report is evidence. Review questions: does any code path resolve a global
table, open a file outside the root, or infer connectivity without a report?

Verified online 2026-09-05: 8.0/9.0 kicad-cli option surfaces and exit code 5
(https://docs.kicad.org/8.0/en/cli/cli.html,
https://docs.kicad.org/9.0/en/cli/cli.html); exit-code header, master branch
(https://docs.kicad.org/doxygen/exit__codes_8h_source.html); schematic, symbol
and board version constants on the 8.0 and 9.0 branches
(https://gitlab.com/kicad/code/kicad/-/raw/9.0/eeschema/sch_file_versions.h,
https://gitlab.com/kicad/code/kicad/-/raw/8.0/eeschema/sch_file_versions.h,
https://gitlab.com/kicad/code/kicad/-/raw/9.0/pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr.h,
https://gitlab.com/kicad/code/kicad/-/raw/8.0/pcbnew/pcb_io/kicad_sexpr/pcb_io_kicad_sexpr.h);
s-expression conventions and tokens (https://dev-docs.kicad.org/en/file-formats/);
`.kicad_pro` JSON keys
(https://gitlab.com/kicad/code/kicad/-/raw/9.0/common/project/project_file.cpp);
library-table keywords
(https://gitlab.com/kicad/code/kicad/-/raw/9.0/common/lib_table.keywords);
file types, path variables, global versus project tables
(https://docs.kicad.org/9.0/en/kicad/kicad.html); DRC JSON fields
(https://docs.kicad.org/doxygen/namespaceRC__JSON.html); library license
(https://www.kicad.org/libraries/license/); Docker intent
(https://www.kicad.org/download/docker/); issue
https://gitlab.com/kicad/code/kicad/-/issues/24264.

Unverified: headless behaviour of `kicad-cli.exe` on Windows and of 8.x/9.x on
Linux without a display (only a 2021 kicad2step issue,
https://gitlab.com/kicad/code/kicad/-/issues/10075, was found; G1-HW-02 must
measure it); the ERC JSON `sheets` field list; per-branch exit codes other
than 5; the exact embedded-file token spelling; fixture licenses, which must be
audited before import.

Iron Plan: **BACKLOG** (draft; `ALIGNED` only after amendment 013 adoption)
Iron Gate: **1**
Evidence: **research citations and one host measurement; no code written, no tests run**
