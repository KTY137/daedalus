# G2-INGEST-01 — result: `INFEASIBLE_CONTRACT`, and the missing contract is already in the tree

`[MEASURED 2026-09-09]` Pre-registration: `G2_INGEST_01_PREREGISTRATION_20260909.md`,
committed at `67113153` **before** any census data existed.
Classification: `EXPERIMENT` (read-only). **Decides nothing. Closes no gate.**
Production code changed: **none.**

## Verdict against the frozen table

**`INFEASIBLE_CONTRACT`.** Both subjects land on the same branch, so there is
no split to report.

| | `black` @ `c3cc5a95` | `fastapi` @ `53d2453d` |
| --- | ---: | ---: |
| declared files (mechanical manifest) | 351 | 2 223 |
| over `max_files` (10 000) | no | no |
| total bytes | 5.5 MB | 11.3 MB |
| symlinks / non-UTF-8 / oversize | 0 / 0 / 0 | 0 / 0 / 0 |
| **empty plane** | — | **`data` (0 files)** |
| `.py` unparseable | 8 / 312 = **2.6 %** | 0 / 1 242 = 0 % |
| `.json` unparseable | 0 / 1 | — |
| **`.md` with ≥1 unresolvable link** | **6 / 38 = 15.8 %** | **75 / 981 = 7.6 %** |

Link counts use the compiler's own extractor (`_MD_LINK_RE`,
`normalized_link`), not an approximation of it — the verdict turns on this
number, so the instrument is the production one.

Applying the pre-registered rule:

- **fastapi** has **zero** files in the compiler's data-plane vocabulary. No
  exclusion rule can create a file, so the `data` plane cannot be populated at
  all. This alone is `INFEASIBLE_CONTRACT` under the "no plane becomes empty"
  clause.
- **black** would require excluding **15.8 %** of its knowledge plane, and
  fastapi **7.6 %**, both over the frozen 5 % threshold — because the compiler
  treats *any* unresolvable local Markdown link as fatal to the **whole**
  compilation (`_reference_inventory.py:212`).

The 5 % threshold was fixed before measurement and has not been moved.

## Why fastapi has no data plane

`data_files` admits only `.csv` and `.json` (`reference_compiler.py:105`).
Mainstream Python projects keep configuration and data in `.toml`, `.yaml`,
`.cfg`, `.ini`. fastapi has `pyproject.toml` and `mkdocs.yml`; the compiler
cannot see either. The barrier is vocabulary, not absence of data.

## The finding that outranks the verdict

The compiler's admission contract is **fixture-shaped**: for a six-file
hand-authored reference project, a broken link *is* a bug and refusing is
correct. For a real repository it refuses everything. The obvious response —
loosen the compiler — would be a silent degradation of the `assurance=verified`
bindings the Twin's value rests on, and §1 of the global constitution forbids
exactly that.

It is not necessary, because **the degradation vocabulary already exists in
production and is simply not wired**:

| already in the tree | reference compiler |
| --- | --- |
| `twin/contracts.py:102` — plane status is `complete` \| `partial` \| `absent`, and `partial` **requires a `reason`** (`:138`) | hardcodes `status="complete"` (`reference_compiler.py:207`); no other value is reachable |
| `extractors/registry.py` — 21 `LanguageSpec` rows, 26 language ids, each carrying `semantic_planes` | hardcodes 5 suffixes: `.py .js` / `.csv .json` / `.md` |
| `extractors/root_file_adapter.py:334` — `status="partial" if diagnostics else "complete"` | any per-file defect aborts the entire compilation |

`detect_language` and `LANGUAGE_SPECS` have **no production consumer**. Their
only importers are the registry itself, `extractors/__init__.py`, and
`tests/twin/test_extractor_contracts.py`. The reference compiler never imports
them (verified: no match for `registry`, `LANGUAGE_SPECS`, or `detect_language`
in `reference_compiler.py`, `_reference_common.py`, `_reference_inventory.py`).

So Gate 2's corpus obligation does **not** need an amendment and does **not**
need a looser trust boundary. It needs the reference compiler to emit the
`partial` status its own contract already defines, with the mandatory `reason`
carrying the excluded files. That is wiring, which `AGENTS.md` §3 asks for
before a new subsystem.

## Correction: this morning's document was wrong about Type

`G2_TWIN_PLANE_ORACLE_NOT_FEASIBLE_20260909.md` concluded:

> Both instruments independently agree that **Type is not a file-level
> property**.

There is a **third** production instrument, and it disagrees:

```
LanguageSpec("python", (".py", ".pyi"), "text", ("code", "type"))
LanguageSpec("json",   (".json",),      "text", ("data", "knowledge"))
LanguageSpec("sql",    (".sql",),       "text", ("code", "data"))
```

The field is named `semantic_planes` — plural, deliberately. A `.py` file *is*
a file-level member of the Type plane there. What forest_v2 and the manifest
actually lack is not Type; it is **multi-plane membership**, and the reference
compiler refuses it explicitly:

```
reference_compiler.py:101  "a declared file may belong to only one semantic plane"
```

The corrected statement: the three instruments do not disagree about whether
Type is file-level. They disagree about **exclusivity**. Two of them force one
plane per file and therefore cannot express Type; the one that does not,
expresses it. My earlier phrasing generalised from two instruments to a claim
about the domain, and the third instrument refutes it.

**Standing unchanged.** `G2-TYPEPLANE-01`'s `.schema.json → type` refinement
stays withdrawn, now on a third independent basis:
`LanguageSpec("json-schema", (".schema.json",), "text", ("data",))` — the
registry assigns it to `data`, as the fixture manifest and `PLANE_BY_SUFFIX`
both did. Three instruments, same answer, against my refinement.

**Standing unchanged.** The twelve retrieval measurements. Nothing here touches
them.

## What this does not claim

- Auto-ingestion is **not** implemented. Naming the wiring is not doing it.
- A repository that compiled under a `partial` status would have `claims: []`
  by construction — planes and **no cross-plane hypotheses**. That is strictly
  weaker than the fixture's ten verified bindings. Admission is not coverage.
- The 5 % threshold is a pre-registered convention, not a principled constant.
  A different threshold would change black's branch but not fastapi's, whose
  empty data plane is threshold-independent.
- Nothing here says the compiler *should* be loosened. It says the choice is
  between a fixture-quality contract and a corpus, that the choice is currently
  being made by default rather than deliberately, and that the tree already
  contains the vocabulary for making it explicitly.

## Reproduction

Both subjects at the pinned anchors; mechanical manifest (`.py`/`.js` → code,
`.csv`/`.json` → data, `.md` → knowledge, `claims: []`); each precondition in
the pre-registration's table audited independently against
`git ls-tree -r` output, using `_MD_LINK_RE` and `normalized_link` from
`daedalus/twin/_reference_inventory.py` for link resolution.
