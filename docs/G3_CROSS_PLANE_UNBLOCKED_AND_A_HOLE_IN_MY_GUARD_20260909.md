# Gate 3's cross-plane refusal no longer fires — and my plane guard had a hole

`[MEASURED 2026-09-09 on origin/main 9351b661 + tensor wave]`
Classification: `EXPERIMENT` (read-only measurement) + one test repair.
**Decides nothing. Opens no gate.**

## 1. R3 no longer refuses, and it is not because of anything I decided

`G3-BASE-01_FROZEN_BASELINE_HARNESS.md` §F1 records the blocker:

> | census, all 27 | code=27, type=0, data=0, knowledge=0 |
> | planes present | `("code",)` |
> | `require_cross_plane()` | **REFUSES** |
>
> the cross-plane baselines cannot be honestly run until the corpus gains
> type-, data- and knowledge-plane tasks.

Re-measured today against `daedalus.eval.harness.all_tasks()`:

| | 2026-09-06 baseline | 2026-09-09 initial | 2026-09-09 later |
| --- | --- | --- | --- |
| tasks | 27 | **31** | **62** |
| census | code=27, type=0, data=0, knowledge=0 | code=27, type=0, data=2, knowledge=2 | **code=27, type=0, data=17, knowledge=18** |
| planes present | `("code",)` | `("code", "data", "knowledge")` | **`("code", "data", "knowledge")`** |
| primary tier | 10 | 14 | **14 (unchanged)** |
| primary census | code=10, type=0, data=0, knowledge=0 | code=10, type=0, data=2, knowledge=2 | **code=10, type=0, data=2, knowledge=2 (unchanged)** |
| `require_cross_plane()` | REFUSES | **PASSES** | **PASSES** |

Verified by building the frozen task set and calling the method, on both the
full corpus and the primary tier. The 14-task primary tier remained stable; 48 new quarantine-tier tasks landed in the later run (31 `independent_text_diff` + 17 `independent_diff`).

**The corpus gained two data-plane and two knowledge-plane tasks.** That is
corpus work someone did, exactly as §F1 said was needed. It has nothing to do
with the Type-plane decision I made earlier today.

### What this does and does not license

**Licensed:** R3's structural refusal is satisfied. A cross-plane comparison on
this corpus is no longer *structurally impossible*, which is the only thing R3
tests.

**Not licensed:** calling Gate 3 unblocked. R3 is a **minimum** guard, not a
sufficiency one — it asks "is this comparison structurally possible", not "is it
adequately powered". Four non-code tasks out of 31 (two data, two knowledge) is
thin, and **type is still 0**, so a code-versus-type comparison remains
impossible. The honest statement is that one specific blocker stopped firing,
not that the baselines are ready.

## 2. The false unblock I refused

Under the Type-plane rule I made canonical this morning, a `.py` file is **both**
code and type. Applied to this corpus that would report:

```
gate3 disjoint rule  : code=27, data=2, knowledge=2
canonical multi-plane: code=27, data=2, knowledge=2, type=27
```

`type=27` — **the same 27 tasks, counted twice.** Not one additional task. A
code-versus-type comparison would compare a set with itself, which is precisely
the structural artefact R3 exists to refuse, and which the s08 false verdict
already cost this programme once.

So the canonical rule is **deliberately not applied** in `eval/gate3/taskset.py`.
Its disjoint `_PLANE_EXTENSIONS` is load-bearing for its own question, and
"unblocking" Gate 3 by swapping the rule would have manufactured the number
rather than measured it.

## 3. My enforcement test had a hole, one iteration after I shipped it

`test_canonical_plane_rule.py` asserted "production has exactly one plane rule"
and passed. It passed because it searched only for modules containing
`semantic_planes`. `eval/gate3/taskset.py` uses `_PLANE_EXTENSIONS`, so the test
never looked at it.

**A guard that cannot see the thing it guards against is worse than no guard,
because it reads as evidence.** Widened to detect any production module that
names all four planes and maps file extensions to them. It immediately found
**five more** sites, and the honest accounting is:

| site | question it answers |
| --- | --- |
| `twin/extractors/registry.py` | **canonical**: artifact → plane membership, multi-plane |
| `eval/gate3/taskset.py` | which plane a *task's gold labels* sit in — disjoint by necessity |
| `eval/gate3/arms/separate_indices.py` | an *arm's* partition; must be one-file-one-plane or it double-counts |
| `eval/tasks.py` | which files a data-plane arm may *retrieve* |
| `eval/harness.py` | which planes to *walk*; not a classifier |
| `twin/reference_compiler.py` | manifest *validation*: a declared `code_files` entry must end `.py`/`.js` |

Each is now allowlisted **with the reason it must differ**, and a second test
fails if an allowlisted path disappears, so the list cannot outlive its entries.

### The correction this forces on my own decision

`G2_TYPE_PLANE_DECISION_20260909.md` says "there is now one answer to *what is
the Type plane*". **That was too strong.** The accurate claim is narrower and is
what the tree already documented before I arrived — `eval/tasks.py:194` says so
in its own comment:

> the twin's discovery registry […], the Gate-3 taskset's `_PLANE_EXTENSIONS`
> and `separate_indices`'s `_DATA_EXTENSIONS` remain the authorities for their
> own questions.

So: **the registry is canonical for artifact → plane membership.** The other
sites answer different questions and are not competitors. The decision stands;
its scope sentence was overstated and is corrected here rather than left to be
found by someone else.

## What this does not claim

- Gate 3 is **not** open. One blocker stopped firing; §F2 (every token count is
  a heuristic) and the power question are untouched.
- No baseline was run. This measured the guard, not the comparison.
- The four non-code tasks were not authored by me and I have not audited their
  quality — only that the classifier accepts them.
