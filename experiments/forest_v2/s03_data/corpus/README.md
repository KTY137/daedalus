# s03 pinned corpus

A frozen, committed tree whose extraction numbers are asserted exactly by
`test_probe_data_plane.py`. Its only job is to stop the published table from
drifting away from what the code does.

The repository-level table in `experiments/forest_v2/README.md` is
revision-bound: it moves whenever the tree moves, so it cannot be pinned. This
corpus does not move, so every number it produces is a contract. Change a
fixture or the extractor and the pin test fails and names the number.

## What each fixture pins

### `src/` — the DDL root

| file | pins |
| --- | --- |
| `tables.py` | two complete tables from implicitly concatenated literals; a `REFERENCES` edge; the case a one-line regex cannot read |
| `duplicate_a.py` / `duplicate_b.py` | the same table `session` declared twice: names agree, types agree, **constraint flags do not** (`TEXT PRIMARY KEY` vs `TEXT NOT NULL PRIMARY KEY`) |
| `fragment.py` | a DDL prefix used as a guard predicate: `complete=false`, `no_balanced_body`, no invented columns |
| `fstring.py` | an f-string declaration: exactly **one** node marked `f_string_partial`, never two |
| `comment_only.py` | the statement text in a `#` comment only: parsed, classified as carrying no declaration |
| `prose_mention.py` | a known **false positive** — prose inside a docstring that mines as a shapeless incomplete node |
| `plain.py` | an ordinary module, no declaration |
| `unparseable_fixture.py` | **deliberately invalid Python**, so `unparseable = 1` is asserted against a real parser failure |

`unparseable_fixture.py` is never imported and never collected (its name does
not start with `test_`). It exists because the defect being regression-tested
was precisely that a content prefilter removed such a file from the denominator
before the parser ever saw it.

### `schemas/` — the JSON root

| file | pins |
| --- | --- |
| `article.schema.json` | all-scalar, fully `required` — the only schema anything can verify against |
| `enum_votes.schema.json` | a bare `enum` with **no** `type` — the exact hole the old check walked through |
| `union_votes.schema.json` | a union type `["integer", "null"]` |
| `ref_id.schema.json` | a `$ref` property, plus a scalar `$defs` entry and a record `$defs` entry |
| `plain.json` | valid JSON that declares no shape |
| `broken.json` | invalid JSON, so `unparseable = 1` is real |

### `data/` — the CSV root

One file per fail-closed condition. Against the four schemas that have
properties, these produce 24 proposals: **1 verified, 10 rejected, 13
indeterminate**.

| file | outcome |
| --- | --- |
| `good.csv` | `verified` against `article`, `indeterminate` against the other three |
| `extra_column.csv` | `rejected` — a column the schema does not declare |
| `missing_required.csv` | `rejected` — a required property the header omits |
| `bad_type.csv` | `rejected` where the type is decidable, `indeterminate` where it is not |
| `ragged.csv` | `indeterminate` — a row whose width differs from the header |
| `duplicate_header.csv` | `indeterminate` — an ambiguous header |
| `empty.csv` | no node at all; counted as `csv.empty = 1` |

### `excluded/`

Stands in for the documented exclusions (`runs/` in the real tree). It holds a
`.csv` and a `.json` that must land in the census bucket
`excluded_documented` — proof that an exclusion is *counted*, not hidden.

## Reading the pinned table

Nothing here is a trusted cross-plane edge. `good.csv -> article.schema.json`
is an **intra-data-plane proposal** that survived every check this probe can
run; both endpoints are data-plane nodes, and the plan section 6 verifier
record is incomplete by construction. See the slice README.
