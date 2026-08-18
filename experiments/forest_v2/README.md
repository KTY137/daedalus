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
  kind, name, locator, fields[], complete, notes, meta)` where `kind ∈
  {sqlite.table, json.schema, json.schema.def, csv.table}`, and
  `Field(name, declared_type, type_source ∈ {declared, inferred, none}, flags,
  locator)`. A locator is `<repo-relative path>#L<line>` (DDL, CSV) or
  `<repo-relative path>#/<JSON Pointer>` (schemas). `meta` carries the
  verifier's evidence for CSV nodes (rows read, whether that was exhaustive,
  ragged/blank rows, per-column observations). `--nodes` prints the node list,
  no flag prints the measurement. `probe()` also returns `DataEdge` counts
  (`sqlite.foreign_key`, `json.ref`), a staged `accounting` funnel and a tree
  `census`. Binding records are `intra_data_proposal`s with status ∈
  {`verified`, `rejected`, `indeterminate`} and an explicit list of the §6
  verifier inputs they lack. `Scope` makes the frozen roots a parameter, so
  the committed corpus can pin the whole table. Nothing under `daedalus/`
  imports this; it only reads.
- **Frozen scope:** DDL from `daedalus/**/*.py`; JSON from `configs/`,
  `tests/fixtures/`, `examples/`, `daedalus/`; CSV from `tests/fixtures/`,
  `examples/`. Loud exclusions, counted in the output rather than hidden:
  `runs/` (3,540 files — receipt *instances* of these schemas, not shape
  declarations) and `.claude/skills/` (48 files of vendored third-party data).

### Corrected 2026-08-18 after an external attack on this slice

Two defects were reported against the first published version of this section
and both were reproduced. They are recorded here rather than quietly
overwritten, because the retained-failure rule applies to our own numbers
first.

**Defect 1 — a subset heuristic was published as a verified cross-plane
binding.** The check called "cross-plane CSV↔schema binding verified per §6"
was neither cross-plane nor a verification. Both endpoints are *data-plane*
nodes, so it is an intra-data-plane check. And `verified` was set without any
of the §6 verifier inputs beyond source evidence: no revision compatibility,
no task relevance, no score, no expiry/retest. Worse, it was not even a type
check: a property whose declared type the probe did not understand — a union,
a `$ref`, a bare `enum`, an untyped property — fell through a `dict.get()`
that returned `None`, and "no mismatch found" was read as "verified". Required
properties were never consulted, and column types were inferred from the first
50 rows, so row 51 onward could contradict the claim unseen.

**Defect 2 — the file counts had a shrinking denominator.** "285 scanned / 0
unparseable" paired two different populations. A content prefilter dropped
every file not containing the literal text `CREATE TABLE`, and it ran *before*
the parser, so only 10 files ever reached it. Measured: **275 of 285 files
were never parsed**. A syntactically invalid file without that text could not
have appeared in the unparseable count at all.

The table below is the corrected measurement. What changed in substance: the
published "8 proposals → 2 verified" is really **8 → 1 verified, 1
indeterminate, 6 rejected**. The lost one is
`examples/fourfold_wiki_app/data/articles.csv` → `article.schema.json`, whose
`status` property is a bare `enum` with no `type` — it was called verified
without its type ever being checked. The earlier claim "both are the correct
pairs" was right about intent and wrong about evidence: only one of the two
was actually verified by anything. **n = 1.**

### Measured (2026-08-18, this worktree @ c2e438ad, plan revision 5) [MEASURED]

`python experiments/forest_v2/s03_data/probe_data_plane.py` →

Every stage is a funnel whose exits are all named and all add up. There is no
prefilter: a file that enters the frozen scope reaches the parser.

| stage | scanned | = parsed | + unparseable | + unreadable |
| --- | ---: | ---: | ---: | ---: |
| Python | 285 | 285 | 0 | 0 |
| JSON | 48 | 48 | 0 | 0 |
| CSV | 2 | 2 (+0 empty) | — | 0 |

| classification of what parsed | value |
| --- | ---: |
| Python: carries a declaration / does not | 10 / 275 |
| JSON: schema document / not a schema | 40 / 8 |

The `0 unparseable` is now earned over 285 files instead of over 10. Files are
also classified **by parse, not by grep**: a file mentioning `CREATE TABLE`
only in a comment no longer counts as carrying a declaration.

| quantity | value |
| --- | ---: |
| **data nodes total** | **193** |
| — sqlite tables (declarations / complete) | 24 (23 complete) |
| — JSON schema roots / `$defs` sub-schemas | 40 / 127 |
| — CSV tables | 2 |
| **fields total** | **1,122** |
| — sqlite / JSON schema / CSV | 158 / 956 / 8 |
| field types: declared / inferred / none | 1,094 / 8 / 20 |
| field locators: line-anchored / pointer-anchored / **unanchored** | 166 / 956 / **0** |
| edges: sqlite foreign key / JSON `$ref` (internal) | 11 / 390 (389) |

Intra-data-plane bindings, with the full denominator:

| quantity | value |
| --- | ---: |
| candidate pairs (CSV × schema-with-properties) | 144 |
| excluded, no field overlap | 136 |
| **proposals** | **8** |
| — verified | **1** |
| — rejected | 6 |
| — indeterminate | 1 |
| **trusted cross-plane edges** | **0** |

The outer denominator — the frozen scope is a choice, so the population it
excludes is published too, by reason:

| suffix | in tree | in scope | excluded: documented | excluded: outside frozen roots | excluded: dir filter |
| --- | ---: | ---: | ---: | ---: | ---: |
| `.py` | 919 | 285 | 18 | 615 | 1 |
| `.json` | 3,515 | 48 | 3,329 | 137 | 1 |
| `.csv` | 45 | 2 | 35 | 8 | 0 |

Every row is fully accounted: in-scope plus each exclusion reason equals the
tree total, asserted by test. The documented exclusions are `runs/` (3,540
files — receipt *instances* of these schemas, not shape declarations) and
`.claude/skills/` (48 files of vendored third-party data).

### These are proposals inside one plane, not cross-plane edges

Plan §6 requires a verifier to check "source evidence, revision compatibility,
type/rule constraints, and task relevance before an edge becomes trusted", and
proposals to carry a score and to "expire or [be] retested". This probe has
**two of those six inputs**, and every record it emits says so about itself
(`record_type: intra_data_proposal`, `planes: ["data","data"]`,
`trusted_cross_plane_edge: false`, `sec6_verifier_record: null`, plus the
explicit missing list):

| §6 verifier input | present | why not |
| --- | --- | --- |
| source evidence | yes | every endpoint carries a file/line/pointer locator |
| type/rule constraints | yes | evaluated over every row |
| revision compatibility | **no** | the probe reads the *working tree* while the revision stamp reports HEAD; a dirty tree makes them disagree |
| task relevance | **no** | there is no mission or task in scope to be relevant to |
| score | **no** | the outcome is a boolean check, not a calibrated score |
| expiry / retest | **no** | records carry neither |

A CSV table and a JSON schema are both data-plane nodes. Calling their
agreement a cross-plane binding is a category error, and it is now impossible
to do so from this probe's output.

### Verification is fail-closed: three outcomes, never two

`rejected` — a check that *can* run says no: a column the schema does not
declare, a required property the header omits, a value contradicting the
declared type. `indeterminate` — the probe cannot decide: a union type, a
`$ref`, a bare `enum`/`const`, an untyped or non-scalar property, a duplicated
or blank header name, ragged rows, a column with no observed values, or types
read from a sample rather than the whole file. `verified` — every check passed
**and** every check was runnable. A rejection outranks an indeterminacy.

Rows are read whole, not sampled; a sampled node can never verify. Column
evidence is exhaustive and counts empty cells, so `""` is not an integer.
`boolean` admits the literals `true`/`false` only, not any string — the old
admissibility map let any string satisfy a boolean property.

### The published table is pinned to a committed corpus

The repository table above is revision-bound and moves when the tree moves,
which is how these numbers drifted from what the code did in the first place.
`s03_data/corpus/` is a frozen committed tree — 9 Python, 6 JSON, 7 CSV files,
one per branch and per fail-closed condition — whose numbers are asserted
exactly, so the table cannot drift again without a test naming the number.
Its unparseable counts are asserted against a genuinely invalid Python file
and a genuinely invalid JSON file, not against a claim.

| corpus quantity | value |
| --- | ---: |
| Python scanned = parsed + unparseable | 9 = 8 + 1 |
| Python carrying a declaration / not | 6 / 2 |
| JSON scanned = parsed + unparseable | 6 = 5 + 1 |
| JSON schema documents / not schemas | 4 / 1 |
| CSV scanned = parsed + empty | 7 = 6 + 1 |
| candidate pairs / proposals | 30 / 24 |
| **verified / rejected / indeterminate** | **1 / 10 / 13** |
| sqlite tables (complete / incomplete) | 7 (4 / 3) |

Writing the corpus immediately found a defect it now guards: an f-string's
literal segments are `ast.Constant` nodes in their own right, so `ast.walk`
yielded them once inside the `JoinedStr` and again individually — one
f-string declaration became **two** table nodes, the second a truncated
phantom. Fixed; the repository count is unaffected at 24, since no declaration
there is assembled in an f-string.

All five guards were mutation-tested by disabling them one at a time; each
disabled guard was caught by a named test [MEASURED].

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
5. **Intra-data binding, tiny and now honest. [CORRECTED]** Proposing
   CSV↔schema bindings by field-name overlap yields 8 proposals from 144
   candidate pairs. Fail-closed verification keeps **1**:
   `tests/fixtures/ignition/voltage/data/events.csv` → `event.schema.json`.
   Six are rejected (columns the schema does not declare, required properties
   the header omits). One is **indeterminate**:
   `examples/fourfold_wiki_app/data/articles.csv` → `article.schema.json`,
   because that schema's `status` property is a bare `enum` with no `type` —
   the earlier version called it verified without ever checking it. **n = 1.**
   This is a §6-*shaped* demonstration of "propose cheaply, verify before
   trusting" and nothing more: it is intra-plane, its verifier record is
   incomplete, and nobody may quote a percentage from a single case.

### Honest caveats

- 100 % locator coverage is coverage of *extracted* fields, not proof that the
  extractor found every data artifact in the tree. Anything declared at
  runtime, in an ORM, in YAML, or inside `runs/` instances is out of scope by
  construction and is not counted as a miss.
- CSV types are **inferred**, never declared — a CSV header declares names
  only. Inference now reads every row, and a node built from a sample is
  stamped `exhaustive=false` and can never verify anything. The reported
  column label still skips empty cells for readability; the verifier's
  evidence does not, so a column with an empty cell is admissible for a
  string property only.
- The declaration miner reads string constants, so prose in a docstring that
  mentions the statement produces a shapeless incomplete node. That false
  positive is pinned in the corpus rather than filtered away: it is textually
  indistinguishable from a genuine guard predicate, so a filter that
  suppressed one would suppress the other.
- `json_ref_internal` counts `$ref` strings starting with `#`; the one
  non-internal ref is not resolved, and no `$ref` target is checked for
  existence. `$ref` edges are structural claims, not verified bindings.
- The DDL parser is a column-list splitter, not a SQL parser: `CHECK`,
  `GENERATED`, and table-level constraints are skipped rather than modelled,
  and index statements are only counted (0 found in scope).
- Repository counts are bound to revision `c2e438ad`; re-measure before reuse.
  The corpus counts are not revision-bound — that is the point of pinning them.

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
