# EXPERIMENT: Forest v2 pre-study — call-resolution gap baseline

Classification: `EXPERIMENT` (master plan §1, §11 Gate 2 prework).
Status: read-only pre-study. **No production promotion. No production import
may reference this directory.** The pre-study may read production code; it
may never be wired into it.

## Frozen specification

- **Hypothesis (falsifiable):** Gate-2 function/method resolution will
  materially increase the fraction of statically attributable call sites in
  the production packages, and that increase will make at least the three
  measured invisibility classes of the Gate-0 effect scanner (cross-module
  sinks, dispatch tables, subclass evasion) mechanically detectable.
- **Baseline (this pre-study):** measure, with the same stdlib-AST method the
  effect boundary uses, how many call sites a same-module fixed point can
  resolve today. The number must exist BEFORE any resolver is built, so the
  later experiment cannot grade its own homework.
- **Scope:** read-only AST analysis of `daedalus`, the tool directory and the
  run directory. No imports of repository code, no writes, no network, no
  subprocess. The probe prints one JSON object.
- **Budget:** ≤ 2 hours of implementation, one probe module, re-runnable in
  seconds. No model calls, no spend.
- **Expiry:** 2026-10-31. If Gate 2 has not consumed this baseline by then,
  re-measure before use (the tree will have moved) and retire this document.
- **Kill criterion linkage:** if a later resolver does not beat this baseline
  on attribution while keeping the quality/cost frontier (plan §14), the
  four-plane track's code-plane investment must be re-argued, not assumed.

## Measured baseline (2026-08-17, this worktree @ 05d5ba3)

`python experiments/forest_v2/probe_call_resolution.py` →

| quantity | value |
| --- | ---: |
| files parsed | 307 (0 unparseable) |
| module functions / methods | 2850 / 1551 |
| call sites | 42,725 |
| same-module resolvable | 6,616 (**15.5%**) |
| cross-module or dynamic | 36,101 |
| unresolvable call shape | 8 |
| resolution gap (upper bound) | **84.5%** |

Honest caveat: the 84.5% is an UPPER bound on what function/method resolution
could address — it counts stdlib calls, method calls on instances, and
attribute chains that no repo-internal resolver should claim. The later
experiment must therefore report its gain against this same counting rule,
not against a friendlier denominator.

Context that motivated the probe: the Gate-0 inventory measured three
concrete invisibility classes caused by the same-module limit —
`tools/guarded_call.py` (cross-module-only sink), `tools/system_check.py`
(dispatch table), `runs/council/room_server.py` (subclass evasion). All three
are now hand-registered rows; a resolver that finds them mechanically has a
ready-made acceptance test.

## Continuation 1 (2026-08-18): import-binding resolution probe

Sub-spec, frozen before the run: same frame (stdlib AST, read-only, no repo
imports, no writes/network/subprocess, one JSON, no spend), budget ≤ 2 h,
same counting rule and same expiry as the pre-study.  Question: how much of
the 84.5% gap does the CHEAPEST resolver (per-file import bindings, whole
tree incl. function-level imports) already attribute, and does it make the
three measured invisibility classes mechanically detectable?

`python experiments/forest_v2/probe_cross_module_resolution.py` @ this
worktree (base 4fb2251; baseline re-measured here: 44,115 sites, 15.5%):

| quantity | value |
| --- | ---: |
| attributed total (same-module + cross-module) | **30.3%** (from 15.5%) |
| cross-module, repo-verified | 2,413 (5.5%) |
| cross-module, external-attributed (unverified) | 4,098 |
| still unattributed | 69.7% |
| classes with externally-attributed base | 39 of 812 |
| registry decorators / registered functions | 4 / 38 |

Acceptance sites (the three invisibility classes):

1. **Subclass evasion — DETECTED.** `runs/council/room_server.py` resolves
   `RoomServer -> http.server.ThreadingHTTPServer` and
   `Handler -> http.server.BaseHTTPRequestHandler` purely mechanically.
2. **Dispatch table — DETECTED (structurally).** `tools/system_check.py`
   `@check -> CHECKS` found as a registry decorator with 18 registered
   top-level functions; the call site stays a subscript, but the registered
   population is known without executing anything.
3. **Cross-module sink — DETECTED, correcting the pre-study's expectation.**
   The inventory pinned `tools/guarded_call.py` as statically invisible; that
   holds only for the same-module fixed point.  Its sink imports are
   function-level (`from daedalus.env import load_env`,
   `from daedalus.providers.deepseek import DeepSeekProvider`, lines 62/68)
   and a whole-tree import walk attributes both.  Retained as a measured
   correction: the invisibility class is narrower than documented — it is
   "invisible to same-module fixed point", not "statically invisible".
   Revisiting the `not_rediscovered` pin is Gate-2 production work, not this
   experiment's.

Honest caveats: external attributions are unverified name claims (good
enough for sink matching, not existence proofs); the registry count only
sees top-level `FunctionDef`s; the baseline's generous last-segment
same-module rule is kept unchanged for comparability, so the cross-module
buckets only ever split the baseline's cross_module_or_dynamic mass.

## Slice s03 (2026-08-18): data plane — declared-schema extraction baseline

Sub-spec, frozen before the run. Same frame as the pre-study (stdlib AST/JSON
only, read-only, no repository imports, no writes, no network, no subprocess,
one JSON object on stdout, no spend), budget ≤ 2 h, **expiry 2026-09-15**.

- **Hypothesis (falsifiable):** the repository's data plane is already
  *declared* in machine-readable form (embedded sqlite DDL, JSON Schema, CSV
  headers), so a Gate-2 data plane can be extracted mechanically with a
  per-field provenance locator — without executing anything, without a
  database connection, and without an LLM. If the extraction had needed
  runtime introspection or heuristics with unverifiable output, the data
  plane's cost side of the plan §13 frontier would look much worse.
- **Output contract** (`s03_data/probe_data_plane.py`): `DataNode(node_id,
  kind, name, locator, fields[], complete, notes)` where `kind ∈ {sqlite.table,
  json.schema, json.schema.def, csv.table}`, and `Field(name, declared_type,
  type_source ∈ {declared, inferred, none}, flags, locator)`. A locator is
  `<repo-relative path>#L<line>` (DDL, CSV) or `<repo-relative path>#/<JSON
  Pointer>` (schemas). `--nodes` prints the node list, no flag prints the
  measurement. `probe()` also returns `DataEdge` counts (`sqlite.foreign_key`,
  `json.ref`). Nothing under `daedalus/` imports this; it only reads.
- **Frozen scope:** DDL from `daedalus/**/*.py`; JSON from `configs/`,
  `tests/fixtures/`, `examples/`, `daedalus/`; CSV from `tests/fixtures/`,
  `examples/`. Loud exclusions, counted in the output rather than hidden:
  `runs/` (3,540 files — receipt *instances* of these schemas, not shape
  declarations) and `.claude/skills/` (48 files of vendored third-party data).

### Measured (2026-08-18, this worktree @ 807ec12, plan revision 5) [MEASURED]

`python experiments/forest_v2/s03_data/probe_data_plane.py` →

| quantity | value |
| --- | ---: |
| Python files scanned / carrying DDL / unparseable | 285 / 10 / 0 |
| JSON files scanned / schema documents / plain documents | 48 / 40 / 8 |
| CSV files scanned | 2 |
| **data nodes total** | **193** |
| — sqlite tables (declarations / distinct names) | 24 (23 complete / 22) |
| — JSON schema roots / `$defs` sub-schemas | 40 / 127 |
| — CSV tables | 2 |
| **fields total** | **1,122** |
| — sqlite / JSON schema / CSV | 158 / 956 / 8 |
| field types: declared / inferred / none | 1,094 / 8 / 20 |
| field locators: line-anchored / pointer-anchored / **unanchored** | 166 / 956 / **0** |
| edges: sqlite foreign key / JSON `$ref` (internal) | 11 / 390 (389) |
| cross-plane proposals → verified | 8 → **2** |

Nodes with zero fields: 96, of which 93 are `$defs` entries declaring a scalar
type (`string` + `pattern`, `enum`, …). Those are type declarations, not record
shapes, and are counted separately rather than dressed up as data nodes.

### What the numbers actually say

1. **Naive DDL extraction recovers 0 of 24 tables.** A one-line regex over raw
   source sees all 24 `CREATE TABLE` heads and **0** complete column bodies —
   the DDL in this repository is written as implicitly concatenated string
   literals and triple-quoted blocks. AST constant folding recovers 24/24 and
   all 158 columns. The cheap method is not "slightly worse" here, it is
   empty; that is the measured argument for parsing rather than grepping.
2. **A real schema-drift hazard, found mechanically.** `provider_observation_
   bindings` is declared twice — `daedalus/runtimes/provider_observation.py#L545`
   and `daedalus/runtimes/provider_observation_store.py#L60`. Column names
   agree, column types agree, **constraint flags do not**: one declares
   `execution_id TEXT PRIMARY KEY`, the other `execution_id TEXT NOT NULL
   PRIMARY KEY`. In SQLite a `TEXT PRIMARY KEY` column does not imply
   `NOT NULL`, so the two declarations are not equivalent. Reported as an
   observation with locators, not as a proven defect; verifying which path
   creates the file is Gate-2 production work, not this experiment's.
3. **One in 24 "tables" is not a declaration.**
   `daedalus/gates/provider_observation_persistence_inventory.py#L303` holds a
   DDL *prefix* used as a guard predicate. The extractor marks it
   `complete=false / no_balanced_body` and gives it no fields instead of
   inventing them, and it is excluded from the duplicate analysis. A docstring
   that merely mentions `CREATE TABLE` produces no node at all.
4. **The schema corpus is total: 956 of 956 properties are `required`.**
   Counting rule: a property whose name appears in its sibling `required`
   array. Combined with `additionalProperties: false` this says the Gate-0
   contracts are closed records — useful for a later type/data cross-plane
   binding, and a warning that "optional field" carries no signal in this
   corpus.
5. **Cross-plane binding, tiny but clean.** Proposing CSV↔schema bindings by
   field-name overlap yields 8 proposals; verification (header ⊆ properties
   **and** every inferred column type admissible for the declared type) keeps
   2 — `examples/fourfold_wiki_app/data/articles.csv` → `article.schema.json`
   and `tests/fixtures/ignition/voltage/data/events.csv` → `event.schema.json`.
   Both are the correct pairs and both wrong-file proposals are rejected.
   **n = 2.** This is a §6-shaped demonstration (propose cheaply, verify before
   trusting), not a precision measurement; nobody may quote a percentage from
   two cases.

### Honest caveats

- 100 % locator coverage is coverage of *extracted* fields, not proof that the
  extractor found every data artifact in the tree. Anything declared at
  runtime, in an ORM, in YAML, or inside `runs/` instances is out of scope by
  construction and is not counted as a miss.
- CSV types are **inferred** from ≤ 50 sampled rows and labelled as such; a
  CSV header declares names, never types.
- `json_ref_internal` counts `$ref` strings starting with `#`; the one
  non-internal ref is not resolved, and no `$ref` target is checked for
  existence. `$ref` edges are structural claims, not verified bindings.
- The DDL parser is a column-list splitter, not a SQL parser: `CHECK`,
  `GENERATED`, and table-level constraints are skipped rather than modelled,
  and index statements are only counted (0 found in scope).
- Counts are bound to revision `807ec12`; re-measure before reuse.

### Kill-criterion linkage

This slice supplies the data plane's side of the plan §13 test "a plane has no
marginal contribution in ablation". Findings 1–3 are things the code plane
alone cannot state (a table's column set, its constraint divergence across
modules, a DDL string that is not a declaration). If a Gate-2 ablation shows
the data plane adds nothing beyond code-plane retrieval, these three are the
concrete claims to re-examine first.

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
