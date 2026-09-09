# s02 external corpora: the declared set completed, and a pin that was blocking every production commit

`[MEASURED 2026-09-09 on origin/main 094f3567]`
Classification: `EXPERIMENT` (slice s02 continuation) + one test repair.
**Decides nothing. Closes no gate.**

## 1. The declared corpus set, measured in full for the first time

`probe_external_corpora.py` declares six corpora and reports every one, present
or absent. Two had never been present on any measuring host, so the slice's
headline had only ever been read against four. Installing the declared packages
into a **purpose-built throwaway venv** — deliberately not the shared one other
sessions use — completes the set:

| corpus | type-name sites | `annotation_only` | **`marginal_pp`** | resolution |
| --- | ---: | ---: | ---: | ---: |
| `kernel` (daedalus) | 46 882 | 94.44 % | **0.1134** | 99.93 % |
| `fixture_alias` | 30 | 73.68 % | **15.7895** | 86.67 % |
| `stdlib` | 2 425 | 1.28 % | **0.0000** | 98.89 % |
| `third_party_typed` (fastapi, anyio) | 12 865 | 95.46 % | **0.0688** | 99.67 % |
| `third_party_reexport` (attr, attrs) | 154 | 10.15 % | **0.0000** | 100.00 % |
| `third_party_untyped` (bs4, click) | 6 145 | 96.91 % | **2.3711** | 99.14 % |

`marginal_pp` is what the entire binding-and-symbol-table machinery buys over an
**annotation-only control**. It is subtractive by construction, so this is also
its ceiling.

### What the completed set shows

**On 68 471 type-name sites across five real corpora, the resolver machinery
buys at most 2.37 pp, and 0.00 pp on two of them.** The only corpus where it
earns a large margin is `fixture_alias` — 30 sites, 0.04 % of everything
measured, hand-built to exercise exactly that machinery.

The two newly measured corpora do not overturn the slice's retracted headline;
they extend it to a further 19 010 sites and make it harder to attribute to
daedalus's own typing posture.

### The instrument has aged, and the labels are now wrong

`third_party_untyped` was declared as "no `py.typed`, largely unannotated". It
measures **96.91 % annotated — the highest of any corpus in the set.** `bs4` and
`click` acquired annotations after the spec was written.

That matters because the spec's stated purpose is "spread of *typing posture*".
The spread still exists — `stdlib` at 1.28 % and `attrs` at 10.15 % are genuinely
sparse — but it is no longer where the names say it is. The corpus label is now
false and should be re-declared before the set is reused. Recorded here rather
than renamed silently, because renaming a corpus after seeing its numbers is
exactly what the frozen sub-spec forbids.

## 2. The pin was a tripwire on the tree, not a check on the claim

`test_kernel_row_is_the_retracted_headline_restated` asserted the corpus
`sha256` exactly. That digest is content-addressed over the whole `daedalus`
package, so **every commit touching production code turned it red.**

The superseded comment records the cost in its own words — three re-pins in a
single day, the last saying:

> "files, functions and every percentage identical yet again, sha only."

Measured today, on two independent branches neither of which touches the
resolver:

| tree | result |
| --- | --- |
| pristine `origin/main` | **8 passed** |
| main + one-file `twin/reference_compiler.py` fix | **1 failed** |
| main + another lane's `twin/relation_compiler.py` edit | **1 failed** |

`AGENTS.md` lists "a guard that blocks reading or measuring" as a
release-blocking defect. This is that shape: a guard that blocks *committing*,
while measuring nothing.

### The repair

Gate on the **rates**, which are the retracted headline and which held
byte-identical across all three re-pins; keep the census as recorded provenance.

- still asserted: `annotation_only_pct`, `full_resolver_pct`,
  `marginal_functions`, `marginal_pp`, `verified_share_of_internal_pct`
- now provenance, not assertions: `sha256` (shape-checked as 64 hex),
  `files`, `functions`, `type_name_sites`, `internal_named_only` — the last
  measured values are recorded in the docstring

### Proof the repair did not just weaken the test

A mutation test, per plan §10 step 6 — `type_plane.py:266`
`return "repo_unverified"` → `return "repo"`:

| perturbation | before repair | after repair |
| --- | --- | --- |
| unrelated edit under `daedalus/` | **red** | **green** |
| real resolver bucket mutation | red | **red** (plus 2 sibling tests) |

The test still fails on a resolver regression and no longer fails on an
unrelated commit. That is the whole intent.

## What this does not claim

- No claim that the resolver machinery is worthless. It resolves 98.9–100 % of
  written type names on every corpus. The measured statement is narrower: it
  adds almost nothing **over an annotation-only control**, which is what the
  slice set out to test.
- The two new corpora were installed into a throwaway venv, so this run is not
  reproducible from the repository alone. The probe reports absent corpora
  honestly, and on a host without those packages it will report four again.
- Nothing here is a Gate-2 or Gate-4 kill-criterion verdict. §14's criteria are
  about the four-plane representation and cross-plane fusion; this measures one
  plane's construction machinery against one control.
