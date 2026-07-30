# Calibration: can a layered graph see what the test gate missed?

2026-07-30 · `daedalus/eval/graph_delta.py` · evidence: `runs/eval/graph_delta.json`

## The question and why this corpus

`tools/gate_discrimination.py` seeds real, incident-modelled defects into a disposable
sandbox and records CAUGHT/SURVIVED. Its docstring carries the finding that motivates this:
*"An audit measured the gate's rejection rate against the three known-bad changes of a single
day at 0/3."* Tests answer one bit, and that day they answered it wrong three times.

**The attempt ledger could not answer this.** 91 attempts, 82 completed, 69 with a diff —
and **all 69 are `state=clean`**. The label is very nearly constant, several diffs are
byte-identical repeats of one docref task, and the diff text was never stored (only
`diff_sha256` and `byte_length`). Calibrating a signal where every example wears the same
label measures nothing. The mutation corpus has ground truth by construction.

## Predictions, written before the first run

Recorded in the module docstring, in the corpus's own `predicted_survive` spirit:
call-deletions visible; vacuous conditions visible; **data-literal changes invisible**;
**inserted early `return` invisible** (needs control flow, which this repo does not build).
Estimated ~3 of 5 on the mutations I had read at the time.

## Result

```
corpus 12 · applied 12 · skipped 0
CLEAN arm (AST, comments excluded)   7/12 detected
LEAKY arm (raw source, comments count) 10/12   <- the gap IS the artefact
```

| Mutation | Defect class | Clean arm |
|---|---|---|
| worktree_moved_checkout_unguarded | deletes-outside-the-worktree | **blind** |
| worktree_drain_skips_reachability | deletes-outside-the-worktree | seen `ast(-2)` |
| offload_escalation_gate_disabled | spends-money-without-a-gate | seen `ast(-3)` |
| free_lanes_includes_claude | spends-money-without-a-gate | **blind** |
| room_ssh_rce_reintroduced | sends-bytes-off-the-machine | seen `ast(+2/-10)` |
| lane_for_host_accepts_localhost | sends-bytes-off-the-machine | **blind** |
| room_verify_always_passes | reports-failure-as-success | seen `ast(±113)`, **types(+4/-2)** |
| attempt_capture_patch_drops_no_textconv | reports-failure-as-success | **blind** |
| bridge_enqueue_collision | logic | seen `ast(-3)` |
| read_inlined_context_inverted_skip | logic | **blind** |
| picker_abbrev_sha_guard_disabled | boundary | seen `ast(-3)` |
| attempt_reap_unwired | resource | seen `ast(-2)` |

## The two mistakes this run caught in itself

**1. The measurement was detecting its own label.** The first run reported 10/12 — and every
single detection contained the tokens `SEEDED` and `DEFECT`, because the corpus writes those
words into its replacement comments and `graph.identifiers` scans raw source, where a comment
is a token. That is a textbook tautology, the same shape `eval/ceiling.py` separates with its
clean and leaky arms. Fixed by extracting identifiers from the **AST**, where comments do not
exist and docstrings are dropped explicitly. **Both arms stay reported: the gap of 3 is the
measured size of the marker artefact**, not a footnote.

**2. Set semantics erased real deletions.** Comparing identifier *sets* hides "this function
now calls `_verify_reachable` once instead of twice" — exactly the shape of a seeded defect.
Switching to a multiset moved two mutations from blind to seen
(`worktree_drain_skips_reachability`, `offload_escalation_gate_disabled`). This was wrong
independently of the answer, which is why fixing it is not tuning to the result.

## What the blindness is made of — and it is only two things

The five misses are not five problems. They are two, cleanly separable:

**Data-only changes (3).** `free_lanes_includes_claude` adds `"claude_cli"` to a tuple.
`lane_for_host_accepts_localhost` and `attempt_capture_patch_drops_no_textconv` change literal
values and argv flags. No name moves, so a name-based view sees nothing. **Fix: a literal
layer** — compare constant values, not just identifiers. `structcore/artifacts.py` already has
that shape for path literals; generalising it is cheap and it would cover all three.

**Control-flow-only changes (2).** `worktree_moved_checkout_unguarded` inserts an early
`return`; `read_inlined_context_inverted_skip` inverts a condition. The identifier multiset is
unchanged in both. **Fix: AST-structure comparison** — hash the statement shape, not the name
counts. Moderate work, and it is the honest boundary of what a name-based graph can do.

Both fixes are named because a signal whose blind spots are *characterised* is usable; one
whose blind spots are unknown is not.

## The caveat that matters more than the number

**7/12 means "the graph is not blind to it". It does NOT mean "the graph detects defects."**

The delta also moves for every legitimate change. A signal that fires on every patch
discriminates nothing, and this corpus contains **only bad patches** — so it can measure
sensitivity and cannot measure specificity at all. The fitness claim needs the other half:
a corpus of *good* patches, run through the identical pipeline, showing that the delta's
shape differs. Until that exists, the honest statement is:

> The layered graph carries a signal on 7 of 12 real defects, available before tests run at
> negligible cost, and its two blind spots are characterised and fixable. Whether that signal
> **separates good patches from bad ones** is not measured, and nothing here should be used
> to rank candidates until it is.

One encouraging data point for the multi-layer thesis specifically:
`room_verify_always_passes` moved the **type layer independently** (`types(+4/-2)`) as well as
the reference layer — a second, non-redundant layer firing on one defect. That is the fusion
claim getting its first observation. One observation.

## The specificity arm — built, and it changes the conclusion

The caveat above said the fitness claim needs a corpus of *good* patches. It now exists:
real commits from this repository's history, through the identical pipeline.

**First attempt, per commit — and it was the wrong granularity.** 76/77 commits moved the
delta (99%), and *zero* were pure deletions. That looked like a perfect discriminator and it
was an artefact of two things: this history is almost entirely growth (**median +354
references per commit, median −0**), and aggregating per commit lets a guard deleted beside a
new 300-line module vanish. A defect edits one function; the comparison has to be one function
wide.

**Per function, 413 changed functions from 120 commits:**

| Rule | False alarm on real code | Defects caught |
|---|---|---|
| **`added == 0 and removed > 0`** | **4/413 (1.0%)** | **6/12 (50%)** |
| `removed > added` | 36/413 (8.7%) | 7/12 |
| `removed >= 2*added + 1` | 27/413 (6.5%) | 7/12 |

Pure deletion is the usable rule: **likelihood ratio ≈ 50**. At a 10% defect rate among
candidates that is ~85% precision; even at 1% it is 34× the base rate.

## The four false alarms are the real finding

All four are **deliberate removals of behaviour**, and three of them are *fixes that work by
deleting*:

| Commit | Function | What was removed |
|---|---|---|
| `79553172` | `sensitivity._within_write_allow` | a `startswith` check — *"a file entry in write_allow must be equality, not a prefix"* |
| `efd0ed6f` | `spine/attempt._run_with_ledger` | git config lines — *"hardening git also removed core.autocrlf, and every patch became garbage"* |
| `1fdea7b2` | `core._codex_report` | the Ikarus spawn — *"make the forced codex lane advisory-only"* |
| `3528f232` | `dotenv.load` | an `override` condition |

Now compare with a seeded defect: `picker_abbrev_sha_guard_disabled` removes a `fullmatch`
check. **Structurally identical to the `sensitivity` fix.** A correct fix that deletes a check
and a defect that deletes a check produce the same graph delta. The difference is whether
deleting it was *right*, and that lives in the specification, not in the graph.

**That is this signal's ceiling, and it is a hard one.** No amount of extra layers closes it,
because the two cases are not distinguishable by structure — only by intent. So the honest
form of the claim is:

> The layered graph delta is **evidence with a measured likelihood ratio of about 50**, useful
> for ranking candidates and routing a reviewer's attention. It is structurally incapable of
> *deciding*, because a legitimate fix and a seeded defect can have identical shape.

Which lands exactly where `daedalus/mapping/spectral.py` already put itself: *"THIS IS
EVIDENCE, NEVER A GATE."* The measurement did not discover a new gate. It discovered a
ranking signal with a number attached, and the number is good enough to use.

## Does "deletion" penalise exactly the evolution step we want?

Owner's challenge, and it is the right one: if the next correct move is often a **refactor**,
a rule that treats deletion as suspicious teaches the loop to only ever add — and the system
already has an agent whose job is deletion (Aristaeus proposes distillations). Measured over
516 changed functions, grouped by commit type:

| Commit type | Functions | Pure deletion | Deletion-dominant |
|---|---|---|---|
| feat | 335 | 0.3% | 6.3% |
| fix | 136 | 2.2% | 8.8% |
| **perf** | **7** | 0% | **71.4%** |
| test | 34 | 0% | 2.9% |

**The soft rule is confirmed harmful and is dropped.** `removed > added` fires on 71% of
functions in `perf` commits — it would penalise optimisation work directly. Deletion-dominance
is confounded with intent and must not be used.

**The strict rule survives the check.** Pure deletion stays ≤2.2% in every commit class,
including 0% in `perf`. Whatever refactoring this history contains does not produce
reference-deleting-without-adding functions.

**The two-step worry, measured.** Of 39 deletion-dominant functions, only **5 (13%)** were
later rebuilt by a subsequent commit adding to the same function; 34 were terminal. So
"delete now, rebuild next step" is a real but minority pattern — `index.py::build_index` went
−31/+30 and later +199, `attempt.py::_run_with_ledger` went −2 then +62. A blocking gate would
have interrupted those.

**The gap that is NOT cleared.** The whole history contains about six cleanup-shaped commits
(3 `refactor`, 1 `cleanup`, 1 `distil`, 1 `retire`). The class most at risk from this rule is
**under-observed**, so "0.3% false alarms" is a statement about a repository that has barely
refactored yet, not about refactoring.

**The design conclusion is not a weaker rule — it is intent.** A candidate that declares
"this is a distillation" should have deletion *expected*, and the question then flips from
"did references disappear" to "did anything disappear that another layer still depends on" —
a doc that still links it, a type that still consumes it, an artefact still written by it.
That is the multi-layer check doing the work the single-layer count cannot, and it is the
honest use of the fusion: **intent plus delta, never delta alone.**

## The literal layer, and the first real evidence for fusion

The blind-spot analysis named a fix — compare constant VALUES, not just identifiers — and
predicted it would cover the three data-only misses. Built and measured:

**Sensitivity rose from 7/12 to 10/12.** The three predicted misses closed exactly as
predicted: `free_lanes_includes_claude` (`literals +1/−0`), `lane_for_host_accepts_localhost`
(`+1/−0`), `attempt_capture_patch_drops_no_textconv` (`−1`). The two that remain blind are
precisely the control-flow class named before the first run — an inserted `return` and an
inverted condition — and neither is reachable without control flow.

**Specificity, re-measured over 443 changed functions, is where it gets interesting:**

| Rule | False alarm on real code |
|---|---|
| literals moved at all | 363/443 (81.9%) — useless alone |
| literals, pure deletion | 45/443 (10.2%) |
| references, pure deletion | 4/443 (0.9%) |
| **both layers, pure deletion** | **0/443 (0.0%)** |

The 81.9% is the important number: **a new layer bought sensitivity and would have destroyed
the signal if used naively.** Adding layers is not free, and "the delta moved" gets worse with
every layer added, not better.

**The fusion claim gets its evidence here, and it is not the zero.** It is that the layers are
**not redundant**: `free_lanes_includes_claude` is visible ONLY to literals,
`attempt_reap_unwired` ONLY to references. Two layers, disjoint catches. That is what a
multi-layer graph has to demonstrate to be worth more than one good layer, and it now has one
measured instance of it.

**A discipline note against myself.** With n=12 defects, five candidate rules have now been
tested. That is already enough to fit noise, so no composite rule is adopted here — the
tiered reading is the honest one: references-pure-deletion is a strong flag (0.9%),
literals-pure-deletion is a weak one (10.2%), and any rule combining them needs a larger
defect corpus before it means anything.

## The structure layer closes it: 12/12, and each layer earns its place

The last two misses were the control-flow class named before the very first run: an inserted
early `return`, and an inverted condition. In both, the identifier multiset AND the constant
multiset are byte-identical — only the shape moved. A third layer records node **types** and
nesting depth while discarding every name and value, which makes it orthogonal to the other
two by construction rather than by hope.

**Sensitivity is now 12/12.** `worktree_moved_checkout_unguarded` shows `structure(+1/−0)` —
the inserted `Return` node. `read_inlined_context_inverted_skip` shows `structure(+0/−2)`.

**And the specificity table is where the fusion argument finally stands up:**

| Rule | False alarm (446 real functions) |
|---|---|
| structure moved at all | 421 (94.4%) — useless alone |
| literals, pure deletion | 45 (10.1%) |
| structure, pure deletion | 17 (3.8%) |
| **references, pure deletion** | **4 (0.9%)** |
| **structure-only change** | **3 (0.7%)** |

"Structure-only" means the shape changed while **no name and no value did**. That is a very
unusual thing for real work and a very natural thing for a logic flip — and it is the
signature of exactly the two defects nothing else could see. Critically, that rule was derived
from the MECHANISM (a control-flow-only edit) and predicted before the first run, not fitted
to the outcome afterwards.

**So the three layers are complementary in a way that is now measured, not asserted:**

| Defect | Only layer that sees it |
|---|---|
| `free_lanes_includes_claude` | literals |
| `attempt_reap_unwired` | references |
| `worktree_moved_checkout_unguarded` | structure |

Three defects, three layers, no overlap. That is what a multi-layer graph had to demonstrate
to be worth more than one good layer, and it is the first hard evidence for it in this repo.

**The discipline note stands and gets stronger.** Eight candidate rules have now been tested
against n=12 defects. Only two are adopted as reportable signals, and both because their
mechanism was stated in advance: *references pure-deletion* (0.9%) and *structure-only change*
(0.7%). Everything else is recorded as measured and explicitly not adopted. The corpus needs
to grow before any composite is believable.

## Next

1. **Specificity.** Build the good-patch arm: sample real commits from git history, run the
   identical pipeline, compare delta shapes. Without it there is no fitness function, only a
   change detector.
2. **The literal layer** — cheap, covers 3 of the 5 misses, and `artifacts.py` already has
   the machinery.
3. **AST-structure comparison** — covers the other 2, and closes the control-flow gap without
   building a CFG.
4. Only then: does the delta predict anything about candidates the gate passes?

Spectral analysis remains deferred and should stay deferred. It compresses a graph; if the raw
deltas turn out not to separate, their compression will not either.
