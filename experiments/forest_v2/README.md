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

**Kill criterion.** The criterion *"benefits disappear on held-out
repositories"* **fires**. (Section numbers move between plan revisions: it is
**§14 "Kill criteria" in revision 5**, the revision checked out on this branch,
and was §13 when the earlier sections of this file were written; the amendment
protocol is §16 there. Cite the criterion by name, not by number.)
The evidence is archived here; the code-plane
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
the repaired B1). That is the kill criterion *"benefits disappear on held-out
repositories"* (§14 "Kill criteria" in the plan revision on this branch). Per
the alignment/amendment procedure the evidence is archived (above), the
attribution-share track is stopped rather than tuned, and an amendment
replacing the "resolution raises attribution" prior is owed from the owner.
The 29.16 % figure must not be quoted as a target for Gate 2.

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

## Slice s04 (2026-08-18): Knowledge-plane crosslink resolution

Directory: `experiments/forest_v2/s04_knowledge/`.

Sub-spec, frozen before the run: same frame as the pre-study (stdlib only, no
imports of repository code, no writes, no network, no subprocess, one JSON
object on stdout, no spend), budget ≤ 2 h, **expiry 2026-09-15**.

- **Hypothesis (falsifiable):** the Knowledge plane's existing crosslinks are
  decayed enough that a Gate-2 crosslinker must treat resolution as a
  first-class, measured property rather than assume prose points at reality.
  The plane is only a retrieval substrate to the extent its edges resolve.
- **Why measure first:** Gate 2 promises "knowledge crosslinks" and "evidence
  locators". The dead fraction must exist as a number BEFORE a crosslinker is
  built, so the later work cannot grade its own homework.
- **Output contract:** `probe_knowledge_crosslinks.py [root]` prints one JSON
  object, schema `forest-v2-knowledge-crosslink-probe/2`, with `waterfall`
  (the staged denominator — this is the headline), `totals` (raw counts per
  bucket), `rates` (per-class percentages, each carrying its own denominator),
  and `dead_examples` / `ambiguous_examples` / `inferred_examples` (≤ 12
  located specimens per bucket, so every claim is spot-checkable). Schema 1's
  single `all_edges_resolved_pct` is withdrawn — see the retraction below.
  Read-only: a check asserts corpus mtimes are unchanged after a run.
- **Counting rules, chosen so no weak claim is laundered into a strong one:**
  external URLs are unverifiable offline and therefore *leave the denominator*
  instead of counting as resolved; a code reference resolves only if the path
  exists **and** the cited line is within the file's real length; bare
  basenames resolve only on a unique match; package-relative paths get a
  separate suffix bucket; ambiguous matches are never silently resolved.

### RETRACTED — the 96.6% headline is withdrawn [2026-08-18]

This section used to publish one number:

    | **all edges** | **413** | **399** | **96.6%** |

It is withdrawn. Not as a rounding correction: three defects stacked into one
flattering figure. The old row is quoted above rather than deleted, so the
correction stays auditable.

1. **Denominator cosmetics.** 551 candidates were extracted. 138 of them left
   the denominator — 136 external URLs and 2 ambiguous references — without
   appearing anywhere in the published table. 413 was the survivor count, not
   the population.
2. **Inference sold as resolution.** 16 of the 399 "resolved" edges were
   unique-suffix inference: a proposal about which file was probably meant, not
   a verified edge. Strictly verified was 383, not 399.
3. **Nothing pinned it.** Every check built its corpus in a temp dir, which
   pins the resolution *rules* and pins no *number*. The same command printed
   96.6% at `3c7f9352`, 95.9% once these findings were written down, and 95.2%
   at `84d54f05` — three published values for one "measurement", and no check
   ever failed.

Over all extracted candidates the strict figure was **383/551 = 69.5%**.

### The replacement: a denominator waterfall

One rate cannot be honest about a population that was filtered twice, so there
is no longer a single rate. Every stage is reported with its own count:

`extracted` → `excluded` (itemised per reason) → `verifiable` →
`strictly_verified` / `inferred_proposal` / `unresolved` (itemised per reason).

Unique-suffix inference is never counted as resolution — it is a proposal
awaiting verification and holds its own stage. Ambiguity is not discarded
either: it leaves the denominator, but it leaves *visibly*, with its own count
and its own listed specimens. Two balance identities are checked while the
waterfall is built (`excluded + verifiable == extracted`, and
`strict + inferred + unresolved == verifiable`), so a bucket that stops being
counted raises instead of quietly improving the rate.

#### Pinned to the committed corpus [MEASURED, pinned]

<!-- waterfall:corpus:start -->

| stage | count | % of extracted | meaning |
| --- | ---: | ---: | --- |
| extracted | 19 | 100.0% | every candidate the extractor produced |
| - excluded: external_url | 3 | 15.8% | http/mailto — unverifiable offline |
| - excluded: ambiguous_target | 2 | 10.5% | several files matched; reported, never guessed |
| = verifiable | 14 | 73.7% | candidates this frame can actually decide |
| strictly_verified | 7 | 36.8% | exact hit, cited line inside the real file |
| inferred_proposal | 1 | 5.3% | unique-suffix inference, awaiting verification |
| unresolved | 6 | 31.6% | target, anchor, or cited line absent |

<!-- waterfall:corpus:end -->

Reproduce:

```sh
python experiments/forest_v2/s04_knowledge/probe_knowledge_crosslinks.py \
  experiments/forest_v2/s04_knowledge/corpus
```

A check pins every cell above to the committed corpus, and a second check
parses this very table out of this README and compares it against a live run —
so the prose cannot drift away from the computation that produced it. The
corpus is small and deliberately unrepresentative: its job is to keep every
stage and every exclusion reason non-empty so the published table has something
to break against, not to resemble a real repository. Verified in both
directions: adding one dead link to the corpus fails the pin, deleting one
corpus file fails the inventory check, and editing a number in the table above
fails the README check. The retracted style would have read (7 + 1) / 14 =
**57.1%** here; a check asserts that value appears nowhere in the output.

#### Tree-wide, this worktree @ `cd550d21` [MEASURED, revision-bound, NOT pinned]

424 markdown files, 0 unreadable, 2950 headings. Re-measured at `8e18b690`, the
commit that contains this retraction: **identical in every stage**. The earlier
observer effect (writing findings down moved the number) was avoided here on
purpose — the reproduce command sits in a fenced block, and the cited names
stay inside inline code, so none of this section mints a new edge. Reflexivity
is manageable when it is designed for; it is only fatal when it is unnoticed.

| stage | count | % of extracted |
| --- | ---: | ---: |
| extracted | 576 | 100.0% |
| - excluded: external_url | 139 | 24.1% |
| - excluded: ambiguous_target | 4 | 0.7% |
| = verifiable | 433 | 75.2% |
| strictly_verified | 389 | 67.5% |
| inferred_proposal | 17 | 3.0% |
| unresolved | 27 | 4.7% |

Unresolved by reason: `code_ref_dead_path` 9, `code_ref_line_out_of_range` 7,
`wiki_dead` 6, `wiki_code_target_dead` 2, `link_path_dead` 2,
`link_anchor_dead` 1.

This table is **not** pinned and must not be quoted as a stable result — it
moves whenever the repository's prose moves, which is precisely how the
retracted headline drifted three times. Two figures matter and both are
published: strictly verified is **389/576 = 67.5%** of everything extracted and
**389/433 = 89.8%** of what this frame can decide. Neither one of them is "the"
resolution rate.

**Declared fixture contribution.** The corpus lives inside the tree it
documents and is *not* excluded from the tree-wide walk — a silent
self-exclusion would be exactly the sin being corrected here. It contributes 19
of the 576 candidates: 3 external, 2 ambiguous, 6 strictly verified, 1
inferred, 7 unresolved. Under its own root it reads 7 verified / 6 unresolved,
because one typed `[[code:...]]` edge is root-relative and resolves only
against the corpus root. The same fixture measuring differently under two roots
is why a published figure has to name its root as well as its revision. The
corpus filenames all carry an `s04` prefix for the same reason: with plain
names (`report.py`, `attempt.py`) the fixture made 12 unrelated references
elsewhere in the tree ambiguous, driving tree-wide ambiguity from 2 to 14.

Fence filter (@ `3c7f9352`) masked 1918 lines and removed **0** link-shaped
refs — this corpus genuinely does not put links in fenced blocks (verified
independently).

### What the residue actually is

The hypothesis as stated is still refuted, now for a defensible reason rather
than a laundered one: of what this frame can actually decide, ~90% is strictly
verified, so "the prose is rotten" does not hold for this corpus. The honest
denominator changes the *shape* of the result though — roughly a third of
everything extracted (external URLs, ambiguous references, inference) is not
something this frame verified at all, and calling that fraction "resolved" was
the original error. The unresolved edges stay more interesting than any rate
[classes below are as of `3c7f9352`; the classes persist, the totals move with
the prose]:

1. **Decayed line anchors (2) — the real Gate-2 signal.**
   `GATE0_SEALED_OWNER_APPROVAL.md` cites `gated_writes.py:774` and
   `TODO_2026-07-30_SESSION.md` cites `kairos/gated_writes.py:987`, in a file
   that is now ~313 lines. These were **valid when written**: the file was
   1245 lines at `e0808054` and was split to 313 at `dae260ee`. A *sealed
   owner-approval document* now carries an evidence locator pointing past the
   end of its own evidence. Path-existence checking alone would have called
   both edges healthy — only the line-range check catches them.
2. **References to untracked runtime artifacts (5).** `.room/room.md` cites
   `runs/council/room.jsonl` and `runs/spine/gate_discrimination.json`, both
   matched by `.gitignore` (lines 51 and 59). Dead in a fresh worktree by
   construction, not stale prose. A Gate-2 crosslinker needs a distinct
   "ephemeral target" verdict; scoring these as broken would be wrong.
3. **Build-artifact path (1)** and **prose note links (5)**, the latter mostly
   generic placeholders (`[[Note]]`) in documentation about wiki syntax.

### Honest caveats

- Line counting uses iteration semantics (a final unterminated line counts),
  which matches what a `file:line` reference means and differs from `wc -l` by
  one on files without a trailing newline. The direction is generous to
  resolution, so it cannot inflate a deadness claim.
- Code references are read only from inline code spans, the form they occur in
  here; unbackticked `path.py:12` in bare prose is not counted.
- The suffix bucket is a *weaker* claim than an exact path (unique-suffix
  inference, not a resolved import). Schema 1 reported it separately and then
  added it to the headline anyway; schema 2 keeps it in its own
  `inferred_proposal` stage and never folds it into the verified count.
- 59 checkable links is a small denominator: 136 of 195 links are external, so
  the 98.3% link rate carries wide uncertainty and should not be quoted alone.
- Wiki-link resolution matches note stems and heading titles only; an Obsidian
  vault with aliases would resolve more. No vault was present in this worktree.

### Observer effect (measured, not hypothesised)

Writing the findings down changed the thing measured: quoting the decayed
specimens added them to the corpus as real refs. Re-running against the tree
that contains this README gave [MEASURED] 318 code refs (+3),
`code_ref_line_out_of_range` 4 (+2), and the old-style all-edge figure
**95.9%** (from 96.6%) — the first of the three drifts that forced the
retraction above. The three additions are `gated_writes.py:774` and
`kairos/gated_writes.py:987` (the cited specimens, now genuinely present and
genuinely decayed) and `path.py:12` from the caveat sentence above.

This is not a defect to filter away — it is a property Gate 2 inherits: the
Knowledge plane documents the system that measures it, so knowledge metrics
are reflexive. Either the corpus revision is pinned (done here) or citations
must be marked as specimens and excluded by an explicit, declared rule. A
crosslinker that silently self-excludes its own documentation would be
reporting a number nobody can reproduce.

### Consequence for Gate 2

Resolution rate is the wrong headline metric twice over: it is already high on
the fraction it is allowed to judge, and it was only *that* high because two
exclusions and one inference were folded into it. Any Gate-2 crosslinker that
reports a single resolution number will reproduce this defect; it should
publish the waterfall, and the exclusions in particular, because "how much of
the plane can this frame even decide?" is the question a retrieval substrate
has to answer. The measurable that earns its keep is **anchor precision under
edit**:
locators decay silently while paths keep resolving, and the one place it bit is
a sealed approval document. A Gate-2 crosslinker should store line anchors as
revision-bound locators (or content-anchored ranges), not raw integers.

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
