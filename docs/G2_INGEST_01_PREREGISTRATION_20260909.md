# G2-INGEST-01 — pre-registration: can the Twin compiler admit a repository it was not configured for?

`[PRE-REGISTERED 2026-09-09, before the barrier census was run]`
Classification: `EXPERIMENT` (read-only feasibility audit of production code).
**Decides nothing. Closes no gate.**

## Why

`G2_DELIVERABLE_STATUS_20260909.md` named Gate 2's binding constraint:

> Gate 2's corpus obligation is not "clone more repositories" […] It is
> **"make the Twin able to ingest a repository it was not hand-configured
> for."**

This packet measures whether that capability is *absent but reachable* or
*blocked by the compiler's own admission contract*. It builds nothing.

## The instrument

For each subject repository at a pinned anchor, derive a manifest **purely
mechanically** — every `.py`/`.js` path to `code_files`, every `.csv`/`.json`
to `data_files`, every `.md` to `knowledge_files`, `claims: []` — and audit it
against every admission precondition `daedalus/twin/` enforces:

| # | precondition | source |
| --- | --- | --- |
| 1 | `schema == "daedalus-fourfold-reference/1"` | `reference_compiler.py:83` |
| 2 | declared file count ≤ `max_files` (10 000) | `reference_compiler.py:89` |
| 3 | planes disjoint | `reference_compiler.py:101` |
| 4 | suffix contracts per plane | `reference_compiler.py:103-107` |
| 5 | each plane list non-empty | `_reference_common.py:84` |
| 6 | no duplicate paths | `_reference_common.py:86` |
| 7 | no symlink in a declared path | `_reference_common.py:123` |
| 8 | declared path is a regular file | `_reference_common.py:129` |
| 9 | file ≤ `max_file_bytes` (32 MB), total ≤ 512 MB | `_reference_common.py:137` |
| 10 | every declared file is UTF-8 | `_reference_common.py:155` |
| 11 | every `.py` file parses | `_reference_inventory.py:48` |
| 12 | every `.json` parses, no duplicate keys | `_reference_common.py:99,108` |
| 13 | every local Markdown link resolves to a real file | `_reference_inventory.py:212` |
| 14 | compiled node identities unique | `_reference_inventory.py:214` |

Subjects, pinned: `black` @ `c3cc5a95d4f72e6ccc27ebae23344fce8cc70786`,
`fastapi` @ `53d2453d1a77f3384a1648d717f8ddafb5e9e460`.

## Reading table — frozen before the census

Four outcomes, not two. My recorded standing defect is writing a binary table
for a space that has a third branch, so the branches are named in full:

**`FEASIBLE_UNCHANGED`** — both subjects compile from the purely mechanical
manifest with no exclusions. Auto-ingestion exists today and was merely never
attempted.

**`FEASIBLE_WITH_DECLARED_EXCLUSIONS`** — both subjects compile once files
violating a *content* precondition (10–13) are excluded, **and** in each
subject the excluded share is `< 5 %` of that plane's declared files, **and**
no plane becomes empty. Auto-ingestion is reachable; the exclusion rule is the
work, and it must be declared rather than silent.

**`INFEASIBLE_CONTRACT`** — at least one subject cannot compile without either
emptying a plane or excluding `≥ 5 %` of one. The barrier is then the
compiler's admission contract, not the repository, and Gate 2's corpus
obligation needs a contract amendment before it needs a corpus.

**`UNANSWERABLE`** — the audit cannot be executed (crash, timeout, or an
environment fault), or the two subjects split across `FEASIBLE_*` and
`INFEASIBLE_CONTRACT` such that no single verdict covers both. A split is
reported as a split, not rounded to the worse or better half.

## Committed before measurement

This file is committed before the census runs, so the ordering is checkable in
git history. The 5 % threshold and the "no plane becomes empty" clause are
fixed here and will not be moved after seeing the counts.

## What this cannot decide

Nothing about retrieval quality, nothing about whether four planes beat three,
and nothing about Gate 2 closure. A repository that *compiles* has a Twin whose
`claims` list is empty by construction — it has planes and no cross-plane
hypotheses, which is a strictly weaker object than the fixture's. That gap is
named here so a later document cannot quietly present admission as coverage.
