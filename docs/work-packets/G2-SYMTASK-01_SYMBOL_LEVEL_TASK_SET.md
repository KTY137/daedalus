# G2-SYMTASK-01 — a retrieval task set whose unit is a symbol

Packet ID: `G2-SYMTASK-01`
Artifact role: `primary`
Status: `planned; baseline measured; not built`
Active gate: `1`
Classification: `EXPERIMENT`
Owner: `repository owner`
Base revision: `68b0b3bb52b58d08b8b96f37355aa46e9433b7d4`
Dependencies: `G2-SYMGOLD-01`
Master-plan authority: `Revision 13`
Promotion: not requested; automatic merge, promotion, and Gate transition are
forbidden. This packet builds an experiment instrument. It does not advance any
gate and cannot fire or clear a §14 criterion by itself.

## Primary acceptance claim

**A retrieval task set exists whose retrievable unit is a `(path, qualified
name)` symbol rather than a file, on which the Type plane has a
representative** — the thing `s09_eval/taskset_xplane.py:58` says was never
attempted.

## Scope

In scope: `experiments/forest_v2/s09_eval/` — `contract.py` (candidate
identity), a new symbol extractor, a new `taskset_symbol.py` builder, and their
tests.

Forbidden paths: `daedalus/**` in its entirety — this is an experiment and may
not import from or modify production. Also `docs/IKARUS_ARIADNE_MASTER_PLAN.md`,
the amendment chain, `AGENTS.md`, and `experiments/forest_v2/s10_kill/**`, whose
verdicts must not be touched by the instrument they judge.

## Contracts and behavior

**One candidate contract, extended, not a second class.** `Candidate` gains an
optional `qualname: str = ""` and a derived `key` property returning `path` when
`qualname` is empty and `f"{path}#{qualname}"` otherwise. `validate_ranking`
(`contract.py:135`) keys on `.key` instead of `.path`. Every existing file-level
candidate keeps `qualname == ""`, so its key is its path and its behaviour is
byte-identical. `metrics.py` needs no change at all: it already compares
opaque strings.

**Gold is pre-image-retrievable by construction.** A symbol enters the gold set
only if it exists in the **parent** tree, mirroring
`no_retrievable_gold_in_pre_image`. A symbol created by the commit is excluded
and counted, never silently dropped.

**Structural symbol identity.** Two symbols are the same when their `ast.dump`
matches, so a reformat is not a change. `G2-SYMGOLD-01` measured this against a
source-segment definition on `black` — a code formatter, the least favourable
subject for that worry — and found a 0.5 % difference.

## Acceptance matrix

| # | criterion | how it is checked |
| --- | --- | --- |
| A1 | the file-level pipeline is unchanged | full `s09_eval` suite green; `Candidate.key == path` whenever `qualname` is empty |
| A2 | a symbol ranking validates; an invented key is refused | new contract tests, both directions |
| A3 | gold is a subset of the universe in **every** emitted case | asserted over the whole built set, not sampled |
| A4 | no post-image leakage: the universe is built from the parent revision only | test that a symbol created by the commit never appears as a candidate |
| A5 | the set reproduces the measured baseline: **402 ± 5** usable cases on `black` | build and count |
| A6 | every exclusion is counted and reasoned, none silently dropped | exclusion tally sums to the input commit count |
| A7 | the build is deterministic: two runs byte-identical | run twice, compare digests |
| A8 | the Type plane has a representative | ≥ 1 gold symbol carrying an annotation in ≥ 90 % of cases |

## Migration and rollback

No migration: the task set is a new artifact and no existing file is
rewritten. The one shared change is an optional field with a default plus a
one-line identity swap in `validate_ranking`, so a revert restores prior
behaviour exactly and no stored task set, result set, or `s10` input changes
shape.

Rollback is `git revert` of this packet's commits. Nothing is persisted outside
`experiments/`, and no production path, contract, receipt family or gate is
touched.

## Evidence, expected failures and review

**Baseline, measured before building** (`G2-SYMGOLD-01`, corrected):

| stage | `black` |
| --- | ---: |
| cross-plane commits with a changed symbol | 438 |
| − no gold survives into the pre-image | −16 |
| − gold > 20 (Recall@20 bound) | −20 |
| **usable cases** | **402** |
| mean gold per case | 3.7 |

`fastapi` yields 51 cross-plane cases and stays out: below the pre-registered
200, and `G2-SYMGOLD-01` recorded why — only 174 of 1 500 commits change a
Python symbol at all.

**Expected failure modes.**

1. `validate_ranking` keying on `.path` while gold keys on `.key`, so every
   symbol ranking silently scores zero. A3 and A2 exist for this.
2. Symbols created by the commit leaking into the universe, making gold
   trivially retrievable. A4 exists for this.
3. Renames producing unstable gold, as `rename_dominated_diff` documents at file
   level. **Unresolved:** symbol renames are not tracked by either definition,
   and this packet does not fix it — it is recorded as a known limitation of the
   corpus rather than claimed away.

**Review questions.**

1. Does an optional `qualname` on `Candidate` genuinely keep one contract, or
   does it make every consumer branch on emptiness?
2. Is `ast.dump` equality the right identity, given it makes a docstring change
   a change but a comment change not one?
3. A symbol-level corpus is **not** the Project Twin. Does anything in the build
   invite a later reader to treat it as one?
