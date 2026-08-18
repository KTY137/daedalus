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

## Slice s01 (2026-08-18): from probe to resolver — `s01_resolution/`

> **RETRACTED HEADLINE.** The "+7.92 pp" result below was measured against a
> control with a hole in it and does not survive. It is left standing, word for
> word, and answered in
> [Retraction (2026-08-18)](#retraction-2026-08-18-the-headline-was-measured-against-a-dominated-control).
> The measured value of this slice is **precision, not attribution share**, and
> on a held-out corpus the share is **negative**. Read the retraction before
> quoting any number in this section.

Sub-spec, frozen before the run. Same frame as the pre-study (stdlib AST only,
read-only, no imports of production code, no writes, no network, no subprocess,
no model calls, no spend). Budget ≤ 1 working day, one slice directory.
**Expiry 2026-09-15** — after that re-measure before reuse, the tree moves.

### Hypothesis (falsifiable)

Replacing the pre-study's spelling rule (match the last dotted segment against
a flat set of every function *and method* name in the file) with a scope-aware
resolver — import binding with re-export chains, `self`/`super`/`cls` dispatch
over the class hierarchy, and receiver typing from constructors, annotations
and instance attributes — raises the share of call sites bound to a **named
definition inside the tree**, and does so for structural reasons rather than
name coincidence.

Falsified if: attribution does not rise on the same denominator; or a
randomised control that repoints bindings at the wrong module leaves
attribution intact (then the resolver matches names, not bindings).

**Verdict (2026-08-18): the first clause is FALSIFIED.** Against the repaired
control the rise is +0.44 pp at home and **−6.12 pp** on a held-out corpus; the
second clause holds (the randomised control does break import-derived
verification). What survives is a claim about *precision*, not about share —
see the retraction below.

### Contract of the outputs

| Artifact | Guarantee |
| --- | --- |
| `s01_resolution/s01_index.py` | module symbols, re-export chains, class hierarchy, instance-attribute types. Every result is a `Target` with `status` = `repo` (file+line inside the tree) / `external` (a named module, a claim) / `unknown` (declines to guess). |
| `s01_resolution/s01_resolver.py` | one `Resolution` per `ast.Call`: `verified` (definition file+line), `external`, or `unresolved` **with a named reason**. `Options` carries the ablation switches and the control's module map. |
| `s01_resolution/s01_measure.py` | one JSON object on stdout, schema `forest-v2-s01-resolution/1`. Imports the pre-study probe; **raises `ParityError` and prints nothing** unless a per-site replica of the probe's rules reproduces its totals exactly, and **raises `DeadSwitchError`** if any ablation/control switch changed nothing. Four control arms (`baseline_arms`), comparison arm `DEFAULT_ARM = "B1"`. |
| `s01_resolution/s01_heldout.py` | the same four arms against a corpus nobody here tuned on (the running interpreter's stdlib), schema `forest-v2-s01-heldout/1`. Added 2026-08-18 because the kill criterion for a held-out corpus had never been executed. |
| `s01_resolution/test_s01_resolver.py` | `python -m pytest experiments/forest_v2/s01_resolution/test_s01_resolver.py`; fixtures are throwaway trees under `tmp_path`. |

Nothing under `s01_resolution/` imports `daedalus`, and nothing in `daedalus`
references it (checked both directions). It parses text; it never executes what
it parses.

### Measured, this worktree @ base `d849c2a9` [MEASURED]

Denominator identical to the pre-study: **45,005** call sites, 318 modules, 0
unparseable, `parity_ok: true` (the replica reproduces all five of the probe's
buckets exactly — without that assertion a "gain" could just be a moved
denominator).

| quantity | pre-study probe | s01 resolver |
| --- | ---: | ---: |
| bound to a definition **inside the tree** | 9,557 (**21.24 %**) | 13,124 (**29.16 %**) |
| named but unverified (external/stdlib) | 4,177 (9.28 %) | 17,881 (39.73 %) |
| attributed, either way | 13,734 (30.52 %) | 31,005 (68.89 %) |
| unresolved | 31,271 (69.48 %) | 14,000 (31.11 %) |

**[RETRACTED 2026-08-18 — the 21.24 % arm is a dominated control; see the
retraction below. The sentence is kept verbatim as the claim that was made.]
The honest headline is the first row: 21.24 % → 29.16 %, +7.92 pp, +3,567
sites.** The 30.5 % → 68.9 % row is *not* apples-to-apples: 13,701 of the
17,881 external attributions are builtins, a bucket the pre-study rule never
asked about and could have claimed just as cheaply. Reporting the second row as
the result would be accounting, not resolution.

Where the newly verified sites come from (3,949 sites the baseline left
unattributed):

| kind | new sites |
| --- | ---: |
| `local_class` (constructor calls) | 3,506 |
| `local_function` (nested/conditional defs) | 311 |
| `local_var_method` | 101 |
| `cls_method` | 19 |
| `self_attr_method` / `self_method` | 8 / 4 |

**Deflating our own result:** 3,506 of 3,949 is not clever resolution. The
pre-study built its name set from functions and methods only, so a call to a
class defined three lines above was invisible to it. Most of the gain is a
counting hole in the baseline, not machinery in the resolver. The parts that
*are* machinery — imports, hierarchy, receiver typing — are measured separately
below and are much smaller.

### Retraction (2026-08-18): the headline was measured against a dominated control

Reported by a second, independent adversarial pass; **every number in this
section was re-executed in this lane before it was written down** [MEASURED,
this worktree, base `16fab41e`, CPython 3.10.11].

**The error.** `s01_measure._local_functions` (at `16fab41e`,
`s01_measure.py:172-181`) built the baseline's name set by walking each
`ast.ClassDef` for its *methods* and never adding `node.name`. A call to a class
defined in the same module was therefore unattributable to the control **by
construction** — not because the control is a weak rule, but because that one
line was missing. 3,368 of the 3,567 "gained" sites (94.4 %) are that hole.

**The repaired-control curve.** One pass, one denominator (45,005 call sites,
318 modules, `parity_ok: true`), four arms of the same last-segment rule:

| control arm | name set | repo-claimed | share | s01 lift | contradicted by s01 | contradiction rate | sites the arm misses that s01 verifies |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| B0 — the chosen control | module functions + methods | 9,557 | 21.24 % | **+7.92 pp** | 109 (83 other-module, 26 external) | 1.56 % | 3,984 |
| **B1 — the repaired control (default)** | B0 + same-module class names | 12,925 | **28.72 %** | **+0.44 pp** | 109 (83, 26) | 1.05 % | 616 |
| B2 | every `def`/`class` in the module | 13,311 | 29.58 % | **−0.42 pp** | 121 (84, 37) | 1.13 % | 289 |
| B3 | B2 + module-level assign targets | 13,324 | 29.61 % | **−0.45 pp** | 122 (85, 37) | 1.14 % | 289 |
| s01 resolver | — | 13,124 | 29.16 % | — | — | — | — |

B3 is rule-dependent and the reader is owed that: counting *every* assignment
target anywhere in the module instead of only module-level ones gives 13,727
(30.50 %, lift **−1.34 pp**). The second attack reported 30.20 % / −1.04 pp,
which sits between the two spellings. The sign does not move.

**The "coverage bought with false positives" defence was tested and it failed.**
Of the 3,368 sites B1 gains over B0, **3,368 are sites s01 itself verifies**
(0 external, 0 unresolved), and B1's contradiction population is **identical**
to B0's — 109 sites, 26 of them external. B1 has more coverage and no more
false attribution: it strictly dominates B0. The headline was measured against a
control that a one-line repair beats without cost.

**Held-out corpus: the sign flips even against B0.**
`python experiments/forest_v2/s01_resolution/s01_heldout.py` — CPython 3.10.11
stdlib, 21 packages (`asyncio … zoneinfo`, test subtrees excluded), 201 modules,
18,683 call sites [MEASURED here]:

| arm | repo-claimed | share | s01 lift | packages where s01 wins |
| --- | ---: | ---: | ---: | ---: |
| B0 | 6,086 | 32.58 % | **−2.85 pp** | 8 of 21 |
| B1 | 6,697 | 35.85 % | **−6.12 pp** | 3 of 21 |
| B2 | 6,890 | 36.88 % | −7.15 pp | — |
| B3 | 6,978 | 37.35 % | −7.62 pp | — |
| s01 | 5,554 | 29.73 % | — | — |

The second attack's independently-built corpus (197 modules, 18,450 sites,
−2.93 / −6.19 pp, 7 of 20 and 4 of 20) [INHERITED] agrees within the difference
between two corpus definitions. The worst per-package results are `collections`
(−26.97 pp) and `dbm` (−16.04 pp); the best are `json` (+10.75) and `ctypes`
(+6.44).

**The metric is monotone in guessing.** "Share of call sites bound to a named
in-tree definition" rises whenever a rule guesses more, so a lift in it is
evidence only between arms of equal or better precision. The mitigating fact,
which does not rescue the lift: on the stdlib, B0's contradiction rate is
**6.79 %** (338 of 4,980 same-module claims) against **1.56 %** at home (109 of
6,965) — the second attack measured 9.25 % against 1.66 % on its corpus
[INHERITED] — so part of B0's held-out coverage is over-claiming that s01 is
right to refuse. That identifies the defect in the *measure*, not a win for the
slice: the two arms are not precision-comparable on the stdlib, which is exactly
why the share number should never have been the headline.

**What the evidence does support.** The measured value of s01 is **precision,
not attribution share**: it produces an *audited target identity* — module,
symbol, file and line, 13,124 of 13,124 landing on a real `def`/`class`,
`confirmed_assign: 0` — where the baseline produces a name match with no target
at all. It also declines where the baseline guesses (109 contradictions at home,
338 on the stdlib), and it still reaches **616 sites the repaired control
misses**. The retracted headline reported attribution share, which is the one
thing this slice does not deliver.

**Kill criterion.** Plan §13, *"benefits disappear on held-out repositories"*,
**fires** (§14 procedure). The evidence is archived here; the code-plane
attribution-share track is **stopped, not tuned** — the next slice may not
re-report a share lift, and an amendment replacing the "resolution raises
attribution" prior is **owed**. This lane does not propose that amendment and
does not touch the plan; it records the hit.

**Consequence for sibling slices.** Any slice quoting a lift over the 21.24 %
arm inherits the dominated-control defect and must be restated against the
28.72 % arm. The comparison arm is now `s01_measure.DEFAULT_ARM = "B1"`; the B0
figure survives only inside
`delta.retracted_vs_B0_dominated_control` and is labelled there.

### Guards repaired in the same beat, and their mutation receipts

Two of the slice's "guards" were decoration. Both are now assertions, and each
was mutation-tested: the guard was disabled, a **named** test was watched going
red, then the guard was restored and the baseline count returned. Suite:
**29 → 41 passed**, restored to `41 passed` after every mutation below
[MEASURED].

| mutation | before this lane | after |
| --- | --- | --- |
| `_baseline_site` short-circuited (`parity_ok` becomes False) | `29 passed`; report published `parity_ok: false`, baseline 5.78 %, headline **+23.38 pp** | `ParityError`, **exit 1, 0 bytes on stdout**; red: `test_measure_reproduces_the_probe_on_the_same_denominator`, `test_report_declares_every_switch_live`, `test_the_repaired_arm_is_the_default_comparison`, `test_the_repaired_arm_is_not_bought_with_false_attributions` |
| parity check itself removed | — | red: `test_parity_failure_makes_the_report_unpublishable` |
| `use_imports` pinned on | `29 passed`, unnoticed | red: `test_import_ablation_strictly_reduces_and_removes_import_repo` + `test_report_declares_every_switch_live` (`DeadSwitchError`) |
| `use_hierarchy` pinned on | `29 passed`, unnoticed | red: `test_hierarchy_ablation_strictly_reduces_and_unbinds_the_inherited_method` + `test_report_declares_every_switch_live` |
| `use_receiver_types` pinned on | `29 passed`, unnoticed | red: `test_receiver_type_ablation_strictly_reduces_and_removes_local_var_method` + `test_report_declares_every_switch_live` |
| dead-switch check removed | — | red: `test_a_dead_ablation_switch_is_fatal` |
| `arm_b1` un-repaired (class names dropped again) | — | red: `test_b0_cannot_attribute_a_same_module_constructor_by_construction`, `test_the_repaired_arm_is_the_default_comparison` |
| `module_map` neutralised (randomised control) | red: 1 named test | red: 2 (`test_control_destroys_import_derived_verification` + liveness) |
| definition audit off-by-one (`lines[line]`) | red | red: `test_verified_targets_survive_the_definition_audit` |

Reproduce the whole series with
`python experiments/forest_v2/s01_resolution/s01_measure.py` for the report and
`python -m pytest experiments/forest_v2/s01_resolution/test_s01_resolver.py -q`
for the suite; each mutation above is a one-line edit named in the left column.

`test_ablations_never_increase_verification` is kept and is explicitly labelled
as worthless on its own: `ablated <= full` is satisfied by a switch that does
nothing. The three strict tests demand a strict drop **and** the disappearance of
the specific kind each switch controls; the harness additionally refuses to emit
JSON when any switch's marginal is zero (`ablation_switch_liveness`). Measured
marginals on this tree are unchanged — imports 2,669, receiver typing 276,
hierarchy 49, control 2,508 — so the published marginals were real; nothing
would have noticed if they had stopped being.

### Verified kinds and the definition audit

| kind | sites | | kind | sites |
| --- | ---: | --- | --- | ---: |
| `local_function` | 5,768 | | `module_attr_repo` | 290 |
| `local_class` | 3,506 | | `local_var_method` | 224 |
| `import_repo` | 2,305 | | `repo_class_attr` | 156 |
| `self_method` | 789 | | `self_attr_method` / `cls_method` / `super_method` | 52 / 29 / 5 |

Every verified resolution carries the target file and line; the harness reopens
that line and checks the claimed `def`/`class` is there. RAW: **13,124 of
13,124 confirmed, 0 mismatched, 0 unreadable.** Stated at its true strength:
this is a *consistency* check, not an independent oracle — the line came from
the same index that made the claim. It catches wrong file, wrong symbol and
off-by-one. It cannot catch a target that exists but is the wrong one.

### Ablations and the randomised control [MEASURED]

| run | verified | share | vs full |
| --- | ---: | ---: | ---: |
| full | 13,124 | 29.16 % | — |
| no import binding | 10,455 | 23.23 % | −2,669 |
| no receiver typing | 12,848 | 28.55 % | −276 |
| no class-hierarchy traversal | 13,075 | 29.05 % | **−49** |
| control: bindings repointed at the wrong module | 10,616 | 23.59 % | −2,508 |

The control keeps every mechanism switched on and only makes each repo-internal
binding name a different repo module. `import_repo` collapses **2,305 → 161**
and `module_attr_repo` **290 → 0**, while `local_function`, `local_class` and
`self_method` do not move. So import-derived attribution really does follow
bindings; the surviving 161 is name coincidence across modules and is the
honest false-positive floor for that bucket.

**Negative result worth keeping: class-hierarchy traversal earns 49 sites.**
Most base classes in this tree are external (`Exception`, `Enum`,
`BaseHTTPRequestHandler`), so cross-module inheritance is rare. Gate 2 should
not fund an MRO engine on this evidence.

**Negative result about control design, retained because it cost real time.**
Two earlier controls returned null and neither null meant anything. (a) Rotating
each module's import *table* onto another module barely moved the number,
because an `ImportFrom` target is stored as an absolute dotted path — the owning
module only matters for relative imports. (b) Rewriting the table on the index
leaked, because the resolver re-seeds function-level imports straight from the
AST and overwrote the permuted values. A control has to be applied where the
resolver reads, which is why the mapping is an `Options` field and not a
mutation of the index. A control that cannot fail is not evidence.

### What the baseline was claiming that is not true

Of the pre-study's 6,965 `same_module_resolvable` sites, s01 agrees with 6,465,
**contradicts 109** (83 resolve to a definition in a different module, 26 to an
external target) and declines on 391. Hand-verified example:
`daedalus/eval/graph_delta.py:642` is `subprocess.run(...)`; the file defines
`def run` at line 450, so the last-segment rule counts a stdlib subprocess call
as same-module. 109 is a *lower* bound — it only counts sites s01 can decide.

### Remaining failure classes — the Gate-2 work list [MEASURED]

| reason | sites | what would fix it |
| --- | ---: | --- |
| `untyped_local_receiver` | 9,060 | return-type inference (`x = f(); x.m()`) |
| `call_result_receiver` | 1,570 | same, for `f().m()` |
| `literal_receiver` | 624 | literal/stdlib type model (`''.join`) |
| `unknown_receiver` | 613 | cross-scope flow |
| `module_variable_receiver` | 581 | module-level constant typing |
| `chain_receiver` | 385 | attribute-chain types (`self.path.parent.mkdir`) |
| `other_receiver` | 370 | `BoolOp`/`BinOp` receivers (`a or {}`) |
| `untyped_self_attribute` | 359 | instance attributes not built by a constructor call |
| `subscript_receiver` | 284 | dispatch tables — needs the registry work, not types |
| all remaining reasons | 154 | — |

One class dominates: return-type inference is worth roughly 10,600 sites
(`untyped_local_receiver` + `call_result_receiver`), an order of magnitude more
than hierarchy or receiver-annotation work. That is the next slice, if any.

### Acceptance sites (the pre-study's three invisibility classes)

| file | call sites | verified | external | unresolved |
| --- | ---: | ---: | ---: | ---: |
| `tools/system_check.py` | 464 | 140 (30.2 %) | 142 | 182 |
| `runs/council/room_server.py` | 272 | 65 (23.9 %) | 108 | 99 |
| `tools/guarded_call.py` | 45 | 7 (15.6 %) | 21 | 17 |

These are per-file resolution rates, not a re-test of the pre-study's three
structural findings; the registry-decorator and external-base detectors live in
`probe_cross_module_resolution.py` and were not moved. `room_server.py`'s
`self.<x>()` calls now resolve through `self_method_external_base` to
`BaseHTTPRequestHandler` — visible as a claim, still not a proof.

### Kill-criterion linkage

Per plan §13, the code plane must earn its place. On this tree the marginal
contributions are: import binding **+2,669**, receiver typing **+276**,
hierarchy **+49**. If a Gate-2 resolver cannot beat 29.16 % repo-verified
attribution at comparable cost, the code plane's resolution investment must be
re-argued rather than assumed.

**Update 2026-08-18 — the criterion did not stay hypothetical: it FIRED.** On a
held-out corpus (CPython 3.10.11 stdlib, 201 modules, 18,683 sites) s01's share
is **below** the baseline's on every arm (−2.85 pp against B0, −6.12 pp against
the repaired B1). That is plan §13 *"benefits disappear on held-out
repositories"*. Per §14 the evidence is archived (above), the
attribution-share track is stopped rather than tuned, and an amendment
replacing the "resolution raises attribution" prior is owed from the owner.
The 29.16 % figure must not be quoted as a target for Gate 2.

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
