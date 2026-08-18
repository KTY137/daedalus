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

## Slice s05 (2026-08-18): revision atomicity — `s05_snapshot/`

Gate 2 (revision 5) asks for "revision atomicity, evidence locators" and
"deterministic Twin rebuilding". This slice builds the smallest thing that can
be *refuted* on that point: a builder that binds four plane extractions to one
revision, content-addresses them, and replays to the same digest.

### Frozen specification

- **Hypothesis (falsifiable):** four independently produced plane extractions
  of one source revision can be reduced to a single content-addressed digest
  that (a) is identical on replay across processes, path spellings and element
  orders, (b) moves when any digested field moves, (c) cannot be produced at
  all from an incomplete or revision-inconsistent plane set, and (d) cannot be
  produced at all unless the four planes provably read **one** tree state. If
  any of the four fails, master plan invariant 6 ("partial graph states do not
  masquerade as a revision") has no cheap mechanical enforcement and Gate 2
  needs a heavier design than a digest.
  Clause (d) was added on 2026-08-18 after (d) was refuted in its absence: a
  revision *label* shared by four documents is a claim, not evidence, and the
  first version of this slice enforced nothing else.
- **Scope:** read-only stdlib AST/text/CSV/JSON analysis of the repository
  tree, no repository imports, no writes outside pytest's `tmp_path`, no
  network, no subprocess. Nothing under `daedalus/` may import this slice
  (checked: `grep -rn forest_v2 --include=*.py` over the package is empty).
- **Budget:** one work session, four modules, whole probe re-runnable in
  ~10 s wall time warm. No model calls, no spend.
- **Expiry:** 2026-09-15. After that, re-measure before reuse — the numbers
  below are properties of *this* tree, not constants.
- **Kill criterion linkage:** if maintaining a revision-atomic snapshot costs
  more than the value it carries, master plan §13 ("revision-atomic snapshots
  cannot be maintained at usable cost") fires. The cost side of that trade is
  the wall time and byte size reported below; the ceiling is not tested here.

### Refuted 2026-08-18: revision identity was a string, and contract `/1` fell

The first version of this slice bound the four planes to one revision by
**string equality of the `revision` field**. A worktree mutated *between* two
plane extractions therefore reduced to one "atomic" digest — for a tree state
that never existed at any instant. Master plan invariant 6 says exactly that
must not happen, so the atomicity claim was false as stated, not merely weak.

Two smaller claims fell with it: the "10 of 10 single-field sensitivity"
number was overstated (three of its ten mutators moved more than one field,
and `edge.src`, `edge.dst`, `edge.attrs` and `locator.end_line` were never
measured at all), and the reported "build wall time" folded extraction into
the build.

Everything below is the repaired slice. The superseded numbers are kept in
the ledger at the end of this section rather than deleted.

### The common contract: `forest-v2-plane-extraction/2`

One plane extraction is one JSON object. s01–s04 produce it; s05 consumes it.
Exactly these keys, all required, **unknown keys are refused**:

```json
{
  "schema":   "forest-v2-plane-extraction/2",
  "plane":    "code" | "type" | "data" | "knowledge",
  "revision": "<source revision id, identical across all four planes>",
  "producer": "<who extracted this — provenance, NOT digested>",
  "nodes":    [ {"id": "...", "kind": "...",
                 "locator": {"path": "rel/posix/path", "start_line": 0, "end_line": 0},
                 "attrs":   { }} ],
  "edges":    [ {"src": "<node id>", "dst": "<node id>", "kind": "...", "attrs": {}} ],
  "witness":  { "rel/posix/path": "sha256:<digest of the text this plane read>" }
}
```

Rules a producer must satisfy: node ids unique within the plane; locators
relative, posix, never absolute, never escaping the root; `end_line >=
start_line`; `attrs` JSON-serializable with string keys; **edges intra-plane
only** — an extractor asserting a cross-plane relation is refused with its own
code, because §6 gives cross-plane edges to a verifier, not to an extractor;
and **every node locator must point at a file the same plane witnessed**.

`producer` is deliberately outside the digest. That is what lets s01–s04
replace the placeholder extractors in `reference_planes.py` without moving a
digest, as long as the extraction itself is identical.

### How the revision is bound now: evidence in two layers

**Layer 1 — the per-plane witness.** Every extractor reads through one
function, `reference_planes.read_source_text`, which records the digest of the
text it just returned. The witness is a by-product of the read that fed
extraction, never a second read — a second read could observe a different tree
state, which is precisely the hole `/1` had. Two planes that read the same
file must witness the same digest, or the build is refused
(`witness_conflict`).

**Layer 2 — the scope bracket.** The caller scans the declared scope (the
union of the plane roots, suffixes `.py .json .csv .md`) before the first
extraction and again after the last, and hands both readings to the builder.
They must be equal (`scope_drift`), and every witness entry must equal the
bracketed state of that file (`witness_scope_mismatch`, `witness_outside_scope`).

Neither layer suffices alone: layer 1 cannot see a file only one plane reads,
layer 2 cannot see a mutation reverted before the closing scan. Together they
refuse both. The scope argument to `build_snapshot` is **mandatory and has no
default** — an atomicity gate the caller may omit is not a gate, and
`test_a_missing_scope_bracket_is_not_an_option` holds that shut.

The scope is *declared*, not derived from what the extractors happened to
read. A scope defined by its own readers would prove nothing, and an extractor
reading outside the declared scope is refused as unbracketed input.

### Outputs

`snapshot.build_snapshot(docs, scope)` → `forest-v2-snapshot/2` manifest:
`revision`, `revision_binding`, `snapshot_digest`, per-plane
`{digest, producer, nodes, edges, witness_files}`, `node_total`, `edge_total`,
and a `scope` block `{digest, roots, files, witnessed_files, unread_files}`.
No timestamp, no absolute path, no host state — those are exactly what would
break replay. `reference_planes.build_atomic_snapshot(root, revision)` is the
one entry point that gets the scan/extract/scan ordering right; that ordering
is the whole guarantee, so it lives in one function rather than at four call
sites that can each get it wrong.

Digest algebra (domain-separated, sorted, so order cannot leak in):

```
node_digest     = sha256(canonical(node))            # canonical = JSON, sorted keys,
edge_digest     = sha256(canonical(edge))            # no spaces, UTF-8, no \u escapes
witness_digest  = sha256("forest-v2-witness/1" | decoded source text)
plane_digest    = sha256("forest-v2-plane/2" | plane | revision
                         | sorted(node_digests) | sorted(edge_digests)
                         | sorted("<path>=<witness_digest>"))
snapshot_digest = sha256("forest-v2-snapshot/2" | contract | revision
                         | "<plane>=<plane_digest>" for code, type, data, knowledge)
```

The witness is **inside** the plane digest and the scope bracket is
**outside** the snapshot digest, and both choices are load-bearing:

- Without the witness, the digest describes only the extracted *view*. These
  placeholder extractors see names and spans, so a changed function body moves
  no node and no edge — a "revision-atomic" identity that does not move when
  the revision's content moves. `test_a_source_change_no_extractor_looks_at_
  still_moves_the_digest` pins that.
- With the bracket outside, a file inside the scope that no plane reads cannot
  change the identity of what was extracted. The bracket is evidence about the
  build, not content of the snapshot;
  `test_the_scope_bracket_is_not_part_of_snapshot_identity` pins that, and the
  bracket's own `scope.digest` still moves so the provenance is not lost.

The witness digests the **decoded** text (UTF-8, universal newlines,
replacement on undecodable bytes), so a CRLF and an LF checkout of one file
stay one revision. Stated as a cost, not hidden: two files differing only in
bytes that decode identically witness identically.

### Measured, this worktree, `python probe_replay_identity.py` [MEASURED]

Placeholder extractors over `daedalus/` (code, type), `configs/ catalogue/
examples/` (data), `docs/` (knowledge):

| quantity | code | type | data | knowledge | total |
| --- | ---: | ---: | ---: | ---: | ---: |
| nodes | 3637 | 3399 | 382 | 2705 | **10,123** |
| edges | 3352 | 8005 | 337 | 2347 | **14,041** |
| canonical bytes | 1,304,377 | 2,045,199 | 165,173 | 1,322,678 | **4,837,427** |
| witness files | 285 | 285 | 45 | 358 | 688 distinct |

Scope bracket: **769 files** under `catalogue/ configs/ daedalus/ docs/
examples/`, of which **688 are witnessed** by at least one plane and **81 are
inside the scope but read by nobody**. Witness files per plane: code 285,
type 285, data 45, knowledge 358.

| replay property | raw result |
| --- | --- |
| build twice in one process @ `140def99` | `sha256:42fd0e98…26b422` = `sha256:42fd0e98…26b422` — **identical**, manifests byte-equal |
| three separate processes, `PYTHONHASHSEED` 1 / 2 / 424242 | `42fd0e98…26b422` ×3 — **identical**, `scope.digest` `c1d48a6d…` ×3 |
| root spelled `<root>/<code root>/..` instead of `<root>` | identical |
| node and edge order shuffled (seed 20260818) | identical |
| documents round-tripped through the canonical form | identical |
| single-field sensitivity matrix | **18 of 18 as expected, 0 skipped** |
| structure sensitivity (deletions, reported apart) | **3 of 3 as expected** |
| refusal matrix | **17 of 17 refused with the exact expected code** |

Wall time, warm cache, per phase [MEASURED] — the phases are separated because
the earlier single number folded extraction into the build and made the build
look about four times more expensive than it is:

| phase | build 1 | build 2 |
| --- | ---: | ---: |
| opening scope scan | 0.686 s | 0.656 s |
| `extract_all` (four planes) | 6.707 s | 6.662 s |
| closing scope scan | 0.584 s | 0.515 s |
| `build_snapshot` | 1.962 s | 1.817 s |
| **total** | **9.939 s** | **9.649 s** |

A cold first scan costs far more than a warm one — 23.522 s was observed on the
first scan of a cold cache, against 0.686 s warm. The warm numbers are the ones
above; the cold one is filesystem cache, not algorithm.

#### What the atomicity binding costs [MEASURED]

Contract `/1` and `/2` run against the same worktree, three trials each, warm
cache, minimum reported, identical output (10,123 nodes / 14,041 edges both
ways) — so this is the price of the evidence, nothing else:

| phase | contract `/1` | contract `/2` | delta |
| --- | ---: | ---: | ---: |
| scope scans | — | 1.014 s | +1.014 s (new) |
| `extract_all` | 5.428 s | 5.699 s | +0.271 s (×1.05) |
| `build_snapshot` | 1.514 s | 1.461 s | −0.053 s (×0.97) |
| **total** | **6.941 s** | **8.174 s** | **+1.232 s (×1.18)** |

Witnessing during extraction is nearly free (+5 %) because the read had to
happen anyway; the bracket is the real cost, and it is two extra full scans.
Against §13's "revision-atomic snapshots cannot be maintained at usable cost",
+18 % at 10k nodes is one frontier point, not a curve — the criterion still has
no scaling evidence either way.

#### Sensitivity matrix, in full [MEASURED]

Each row mutates exactly one field of one object; the expected outcome is
declared before the run, and a refusal is as valid an outcome as a moved digest.

| field | expected | observed |
| --- | --- | --- |
| `node.id` (isolated node) | changed | changed |
| `node.id` (node with an edge) | refused `dangling_edge` | refused `dangling_edge` |
| `node.kind` | changed | changed |
| `node.locator.path` | refused `unwitnessed_locator` | refused `unwitnessed_locator` |
| `node.locator.start_line` | changed | changed |
| `node.locator.end_line` | changed | changed |
| `node.attrs.<value>` | changed | changed |
| `edge.src` | changed | changed |
| `edge.dst` | changed | changed |
| `edge.kind` | changed | changed |
| `edge.attrs.<value>` | changed | changed |
| `witness.<path>` digest only | refused `witness_scope_mismatch` | refused `witness_scope_mismatch` |
| `witness.<path>` digest + bracket | changed | changed |
| `witness.<path>` key | refused `unwitnessed_locator` | refused `unwitnessed_locator` |
| `scope.opened.<path>` | refused `scope_drift` | refused `scope_drift` |
| `revision`, one plane | refused `revision_mismatch` | refused `revision_mismatch` |
| `revision`, all four planes | changed | changed |
| `producer`, all four planes | unchanged | unchanged |

Two rows restate one field in every document that holds it (`revision`,
`witness` digest) because the contract refuses an incoherent set before it ever
digests — that is labelled in the table rather than counted as one document's
field. Deletions are not field mutations and sit in their own table: dropping
an edge and dropping an isolated node both move the digest, dropping a witness
entry is refused as `unwitnessed_locator`.

### The atomicity claim, now that the gate is green

Restated only because it is now enforced, and with the checks that enforce it
named, so the claim can be re-refuted by disabling them:

> Four plane extractions reduce to one content-addressed digest **only if they
> provably read one tree state**. A worktree that moves during extraction
> produces no digest at all.

| scenario | refusal | check |
| --- | --- | --- |
| tree mutated between plane 1 and plane 2 | `scope_drift` | `test_mutation_between_plane_extractions_is_refused` |
| mutation reverted before the build, two readers | `witness_conflict` | `test_mutation_reverted_before_the_build_is_still_refused` |
| file only one plane reads, mutation left standing | `scope_drift` | `test_mutation_of_a_single_reader_file_is_refused` |
| file only one plane reads, mutation reverted | `witness_scope_mismatch` | `test_single_reader_mutation_reverted_is_refused_by_the_witness` |
| untouched tree | none — it builds | `test_an_untouched_tree_still_builds` |

The last row matters as much as the first four: a gate that refuses everything
is not fail-closed, it is broken.

**The gate was seen red before it was seen green** [MEASURED]. At commit
`be34f92f`, with contract `/1` still in place, the three mutation scenarios
failed with the digest the builder should never have produced, e.g.
`Failed: a tree mutated between two plane extractions digested as ONE atomic
revision: revision='rev-1' snapshot_digest=sha256:a77efb9a…de24eb -- that
snapshot describes a tree state that never existed at any instant`.

**Every guard is bound to at least one check** [MEASURED]. Disabling one
refusal at a time and re-running the suite:

| guard disabled | checks that went red |
| --- | ---: |
| `scope_drift` | 2 |
| `witness_conflict` | 2 |
| `witness_scope_mismatch` | 1 |
| `witness_outside_scope` | 1 |
| `unwitnessed_locator` | 1 |
| `nodes_without_witness` | 1 |
| witness inside the plane digest | 2 |

No guard is decoration.

Checks: `python -m pytest experiments/forest_v2/s05_snapshot/test_snapshot.py`
→ **63 passed in 2.91 s** [MEASURED].

#### Superseded numbers (kept, not deleted)

| claim | status |
| --- | --- |
| "single-field sensitivity: 10 of 10 as expected" | **overstated, withdrawn.** Three mutators were not single-field and two were deletions; four fields were untested. Replaced by 18 of 18 above. |
| "build wall time 5.822 s / 5.069 s" | **conflated, withdrawn.** That was extraction plus build under one label. Replaced by the per-phase table. |
| "refusal matrix: 10 of 10" | superseded by 17 of 17 (seven new refusal codes). |
| three-commit revision-binding table (`fa01e21b…`, `0ee74bbd…`, `44856f83…`) | measured under contract `/1`; those digests are not comparable to `/2` and are not re-measured here. The property they were evidence for — the revision label is inside the digest — is now row `revision, all four planes` of the sensitivity matrix. |

### Honest caveats and open ends

1. **The extractors are placeholders, not evidence.** Top-level definitions
   only, syntactic annotation text with no inference, file-level data
   locators with no field spans, headings with no concept resolution. Every
   count above is a property of the cheapest possible producer. When s01–s04
   land, the counts change and only the *properties* carry over.
2. **The revision *label* is still HEAD, not the working tree.**
   `read_git_revision` reads git's files and does not check whether the tree is
   dirty, so a modified tree is still labelled with a clean commit id. What
   changed on 2026-08-18 is that the label no longer carries the atomicity
   claim on its own: the digest now commits to the witnessed source text, so a
   dirty tree produces a *different* digest under the same label. Turning a
   dirty tree into a refusal rather than a distinct digest is still open, and
   still Gate-2 production work.
3. **The evidence is self-reported.** Witnesses and scope readings are produced
   by the same process that produces the documents. They defeat a racing
   writer; they do not defeat a lying extractor, which can forge its own
   evidence exactly as easily as its nodes. Sealing that needs a trusted reader
   outside the producer — §4's evidence boundary — which this slice does not
   build.
4. **One transient escapes by design.** A file mutated and reverted inside the
   extraction window that *no plane read while it was mutated* is not refused:
   both brackets agree and every witness matches them, so the snapshot really
   is a function of the bracketed tree. Refusing that too would need a
   filesystem watch, not a scan. Recorded as a passing check
   (`test_a_transient_no_plane_read_is_deliberately_NOT_refused`) rather than
   as prose, so it cannot quietly become false.
5. **`attrs` is free-form, so determinism there is producer-enforced.** The
   builder rejects unknown *contract* keys, which stops a wall clock at the
   node level, but a producer that writes `attrs: {"built_at": …}` is only
   caught by the double-build check, never by the schema.
6. **Digest ≠ storage.** Nothing here stores content-addressed blobs; it
   addresses the extraction and the source text it read, not the sources
   themselves. §5's content-addressed source trees remain unbuilt.
7. **Cost ceiling untested.** 9.6 s and 4.8 MB canonical form for ~10k nodes,
   of which the atomicity binding is +1.2 s (×1.18), is one frontier point, not
   a scaling claim. The §13 kill criterion about snapshot cost needs a curve.
   The bracket scans the whole declared scope twice, so its cost grows with the
   *scope*, not with the extracted graph — that is the shape most likely to
   bite at repository scale and it is untested here.
8. **The scope is coarse.** It covers every `.py .json .csv .md` file under the
   plane roots, including the 81 that no plane reads. A change to one of those
   refuses the build even though it could not have affected the snapshot. That
   is deliberately fail-closed and deliberately noisy; a tighter scope would be
   a scope derived from its readers, which proves nothing.
9. **Cross-plane edges are refused, not verified.** That is deliberate (§6),
   but it means a real Twin still needs the verifier this slice does not build.

## Slice s06 (2026-08-18): Node Cards — the §6 contract, built and measured

Directory: `experiments/forest_v2/s06_cards/`. Same frozen frame as the
pre-study (pure stdlib, read-only, no repository import, no writes, no
network, no subprocess, one JSON object on stdout).

### Frozen sub-specification

- **Hypothesis (falsifiable):** the seven fields §6 demands — stable node
  identity, revision, plane, source locator, compact content, local
  neighborhood, provenance — can be produced *mechanically and deterministically*
  for a whole revision, at a per-card cost small enough that the latent atlas is
  a storage question rather than a storage problem. If the mandatory envelope
  turns out to dominate the payload, §6's "schema-light" claim is the part that
  needs re-argument, not the extractor.
- **Contract of my outputs** (both versioned, both validated in-repo):
  - `forest-v2-node-record/1` — the *input* shape any producer must satisfy:
    `plane, kind, path, qualname, start_line, end_line` required;
    `ordinal, signature, doc, text, source_sha256, neighbors` optional.
  - `forest-v2-node-card/2` — the *card*: `schema, card_id, node_id, revision,
    plane, locator{path,start_line,end_line,source_sha256},
    content{kind,name,qualname,signature,doc,text,text_sha256,text_chars,truncated,budget},
    neighborhood{edges[],edge_total,truncated,budget}, provenance`.
    `validate_card()` is the machine-checkable definition; a card that fails it
    is not a card.
    **`provenance` is a `sha256:` content address, not a block.** The build
    emits each distinct block once in a `ProvenanceBook`; `validate_card(card,
    book)` fails a ref that does not resolve, so the compression cannot buy
    itself with a dangling pointer. `/1` carried an inline dict — a breaking
    difference, hence the version bump.
  - `forest-v2-node-card-probe/2` — the measurement report. `/2` adds
    `upstream`, `provenance_book`, `counter_liveness` and
    `contract_violation_reasons`.
- **Two identities, deliberately:** `node_id` = `plane://path#kind:qualname`
  (+`~ordinal`) carries **no line numbers**, so it survives a shift or a
  reformat; `card_id` = sha256 over the entire card body, so it cannot survive
  one. §6 wants a handle stable enough to compare across revisions, §5 wants a
  revision-atomic content address. One field cannot be both.
- **Budget:** ≤ 3 h, five modules + three check files, whole-repo run in
  seconds, no model calls, no spend. The frozen frame gained one deliberate
  exception: the probe may import slice s01's read-only modules from a sibling
  worktree. That is an experiment-to-experiment import, never production code,
  and the coupling is reported in-band (see the named gap below).
- **Expiry: 2026-09-15.** After that, re-measure before reuse (the tree moves)
  or retire the section.
- **Kill-criterion linkage (§14):** if cards must grow past the point where
  card construction and storage worsen the quality/cost frontier, or if the
  neighborhood bound has to be lifted so far that "local" stops meaning local,
  the latent-atlas prior loses its cheapest justification.

### RETRACTED: the first published numbers of this slice

An adversarial review reproduced the whole slice — all 8 headline figures, all
18 size cells, all 24 sweep cells, `envelope_bytes` 867, 41 checks — and found
no cooked denominator. It then found two defects that the reproduction could
not have caught, and both were real.

**Retracted claim 1 — `envelope_bytes` = 867 was inflated by a literal.**
267 of those 867 bytes were a constant provenance block inlined into every
card, including a 55-byte prose footnote about an upstream that was not wired.
Over 8,466 cards that literal was 2,260,422 bytes. "The price §6 charges before
the first useful character" was therefore ~31% not a §6 price at all, but a
copy-paste artefact of this slice's own extractor. **The derived claims fall
with it: "50% of the mean card at a 200-char budget" and the whole
content-budget sweep table above are withdrawn.** Replacements below.

**Retracted claim 2 — `records_rejected = 0` and `contract_violations = 0`
were not measurements.** No malformed record was ever fed to the probe, and
`build_card` raises before a malformed record can become a card, so neither
counter could have moved. They were restatements of control flow presented as
results. Replacements below.

Nothing else in the earlier section is withdrawn: the card counts, the plane
split, the edge counts and the determinism results reproduce unchanged.

### Measured, this worktree @ `461492ca` [MEASURED]

`python experiments/forest_v2/s06_cards/probe_node_cards.py`, default budgets
(content 800 chars, neighborhood 8 edges), scanning the same three code
packages as the earlier probes plus the markdown tree. `experiments/` is
deliberately **not** scanned: the slice does not measure itself.

Two upstream modes are reported, because they answer different questions.
`--no-s01` uses the stand-in extractor and so is **directly comparable to the
retracted numbers**; it isolates the envelope change with nothing else moving.
The default resolves the real slice-s01 upstream and is a different, larger
corpus of edges.

#### The envelope, corrected [MEASURED]

| | retracted | now | delta |
| --- | ---: | ---: | ---: |
| `envelope_bytes` | 867 | **686** | −181 (−20.9%) |
| …of which the provenance ref | 281 (inline block) | **87** (fixed-size pointer) | −194 |
| …of which everything else | 586 | **599** | +13 (`content.budget`, new) |
| corpus total bytes (stand-in, 800) | 17,986,544 | **16,454,198** | −1,532,346 (−8.5%) |

The corpus delta is exactly 8,466 × 181. Edge counts, truncation counts and
card counts are byte-identical to the retracted run, which is the check that
*only* the envelope moved.

The saving is smaller than "delete the literal" would suggest, and the README
says so rather than quoting the flattering figure: a ref is not free. It costs
a fixed **73 canonical bytes**, so a provenance block *smaller* than 73 bytes
is cheaper inlined. The narrow defensible claim is that ref cost does not grow
with the origin description, and s06's real block (267 bytes) is far past
break-even. Both directions are asserted in the checks.

#### Corrected derived claims: the envelope share [MEASURED]

The withdrawn "50% / 41% / 31%" becomes:

| content budget | mean card (stand-in) | envelope share | mean card (s01) | envelope share |
| ---: | ---: | ---: | ---: | ---: |
| 200 | 1,562.8 | **43.9%** (was 50%) | 1,809.6 | **37.9%** |
| 800 (default) | 1,943.6 | **35.3%** (was 41%) | 2,190.4 | **31.3%** |
| 4,000 | 2,582.5 | **26.6%** (was 31%) | 2,829.4 | **24.2%** |

The s01 column moved after the join repair below (1,829.4 → 1,809.6 and so on)
and its envelope **share rose**, 37.5% → 37.9%. That direction is against this
slice's own headline and is printed rather than rounded away: the repair made
the edge payload smaller while the envelope stayed 686 bytes, so the envelope
now buys a larger fraction of a smaller card.

A reviewer projected the corrected 800-char figure at ~35% assuming the
provenance cost vanished entirely; the stand-in column lands at 35.3%, and the
agreement is a coincidence of two errors cancelling — the ref still costs 87
bytes, but the corpus also gained `content.budget`. Were provenance genuinely
free the floor would be 599 bytes, i.e. 38.3% at a 200-char budget. It is not
free, and §7 does not permit it to be.

#### Content-budget sweep, re-run [MEASURED]

Stand-in upstream, 8,466 cards — the row-for-row replacement of the withdrawn
table:

| content budget | total bytes | p50 | p90 | max | truncated | probe seconds |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 200 | 13,230,808 | 1,425 | 2,003 | 4,467 | 6,888 (81.4%) | 12.4 |
| 800 (default) | 16,454,198 | 1,924 | 2,579 | 5,075 | 3,841 (45.4%) | 12.4 |
| 4,000 | 21,863,801 | 2,048 | 5,244 | 8,298 | 768 (9.1%) | 14.2 |

Real s01 upstream, same 8,466 cards, more edges — **re-measured after the join
repair below**, which is why every cell moved:

| content budget | total bytes | was | p50 | p90 | max | truncated |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 200 | 15,320,303 | 15,487,658 | 1,700 | 2,463 | 4,467 | 6,888 (81.4%) |
| 800 (default) | 18,543,693 | 18,711,048 | 2,126 | 3,079 | 5,075 | 3,841 (45.4%) |
| 4,000 | 23,953,296 | 24,120,651 | 2,268 | 5,779 | 8,298 | 768 (9.1%) |

The saving is **−167,355 bytes at every one of the three budgets**, to the
byte. That constancy is the check that the repair touched the neighborhood and
nothing else: content scales with the budget, edges do not. The stand-in table
above is byte-identical to its previous run, which is the other half of the
same check — the repair is confined to the s01 path.

The `probe seconds` column is dropped rather than carried forward stale. Other
lanes were running on this box, and a duration measured under load is wrong
rather than merely noisy. The previous values (≈24–26 s) stand as [INHERITED]
and were not re-measured here.

The qualitative reading survives the correction: raising the budget 5×
(800→4,000) moves the median card 6.4% but the p90 103% (stand-in). Half the
nodes are smaller than 800 chars anyway; the cost lives in a tail of large
modules and long documents. A per-plane or per-kind budget would beat one
global constant — a Gate-2 decision this slice does not pre-empt.

#### The corpus, both upstreams [MEASURED]

| quantity | stand-in | real s01 |
| --- | ---: | ---: |
| cards built | 8,466 | 8,466 |
| code / knowledge plane | 5,739 / 2,727 | 5,739 / 2,727 |
| distinct `node_id` / duplicates | 8,466 / 0 | 8,466 / 0 |
| neighborhood edges found / kept | 18,640 / 13,762 | **33,985 / 27,940** (was 34,104 / 27,983) |
| neighborhoods truncated by the bound | 345 (4.1%) | 940 (11.1%) (was 952) |
| cards with no edge at all | 3 | 23 |
| contract violations | 0 | 0 |
| records rejected | 0 | 0 |
| dangling provenance refs | 0 | 0 |
| provenance blocks in the book | 2 | 2 |

Two blocks, 8,466 cards. That ratio is the change.

s01's own resolution result, passed through [MEASURED]: 318 modules,
0 unparseable, 45,005 call sites — 13,124 verified, 17,881 external,
**14,000 declined**; 341 base classes, 189 resolved to a repo class. The
declined 31% is reported, not absorbed: s06 attaches no edge it cannot name.

Of the 13,124 verified, **12,788 now reach a Node Card and 336 do not**
(`calls_verified_joined` / `calls_verified_no_card` in `describe()`). The 336
are targets s01 verified and s06 does not card at all — defs nested inside
functions, which `_walk_defs` deliberately does not walk. They are dropped and
counted rather than shipped as pointers into nothing. See the retraction below
for what those figures were before.

### RETRACTED: "34,104 edges" was 13,124 pointers into nothing

The corpus attached 13,124 verified call edges and **not one of them could be
followed**. `node_cards.node_id` mints `code://{rel}#{kind}:{qualname}` from the
record's **node kind** — `module` | `class` | `function` | `method`.
`s01_upstream` minted the target id from `Resolution.kind`, which is not a node
kind at all but s01's **resolution bucket**: `local_function`, `local_class`,
`import_repo`, `self_method`, `module_attr_repo`, `local_var_method`,
`repo_class_attr`, `self_attr_method`, `cls_method`, `super_method`. Every
`calls` edge in the s01 column therefore addressed a card that cannot exist.

85 checks were green throughout. Each looked at one side of the join; none
looked at the join. That is the defect behind the defect, and it is the reason
the replacement is a **join guard** rather than a format assertion: it follows
a known edge set to its cards and fails on the rate, so a future drift for some
entirely different reason — a separator, an ordinal, a qualname convention —
reddens the same check.

**What is withdrawn.** The s01 column's edge counts and every byte figure
derived from them: 34,104 / 27,983 edges, 952 truncated neighborhoods, the
three s01 sweep rows, and the three s01 envelope-share cells. They were
arithmetically correct and they counted unusable edges. Replacements are in the
tables above.

**What is not withdrawn.** Card counts, the plane split, `distinct_node_ids`,
the envelope figures, the whole stand-in column, and the counter-liveness
table. The stand-in column re-runs byte-identical, which is the evidence that
the fault was confined to the s01 path rather than a claim that it was.

**The correction, in full** [MEASURED]:

| quantity | before | after |
| --- | ---: | ---: |
| verified call edges emitted | 13,124 | 12,788 |
| …that reach a card | **0** | **12,788 (100%)** |
| …verified but uncarded, declined | 0 (shipped dangling) | 336 |
| raw call edges | 31,005 | 30,669 |
| deduped call edges | 18,461 | 18,342 |
| joined targets by node kind | — | function 7,478 / class 4,055 / method 1,255 |

The deduped count falls by 119 while the raw count falls by 336, and the gap is
accounted for rather than waved at: 217 of the dropped edges were repeat calls
from one enclosing definition to the same nested target, which the per-owner
dedup would have collapsed anyway. Measured separately: **zero** edges existed
only because the route was in the id — within a single owner record no target
was ever reached under two different buckets. So the bucket never inflated the
edge count. It only broke the join, silently, at 100%.

**Mutation-verified, not asserted.** Putting `res.kind` back reddens
`test_every_repo_call_edge_reaches_a_card_in_the_same_build` and
`test_call_edges_carry_the_node_kind_not_the_resolution_bucket` (3 failed, 89
passed); restoring returns 100 passed and 12,788 / 12,788. One result is kept
because it is against interest: the build's own `calls_verified_joined` counter
does **not** notice the mutation — it counts successful kind lookups, and the
lookup still succeeds when the id minted from it is wrong. A counter is not a
join check. The in-suite mutation probe asserts that non-detection rather than
hiding it.

**The interface decision, stated because it binds two slices.** The **node kind
is canonical** and the resolver conforms. `node_id` is a pure function of a
record, so a card must be able to mint the identity another slice points at;
the resolution bucket is not a property of the record. And the bucket names the
*route* from call site to target, not the target — an identity that varies with
the path taken to it is not an identity. The bucket is not discarded: it is
published once per build as `calls_by_resolution`, split verified/external, the
same discipline this slice already applied to provenance blocks.

#### The two counters are now measurements [MEASURED]

Each condition runs through `node_cards.tally` — the same function the corpus
run uses, asserted by a check — and the probe publishes this table in-band
under `counter_liveness`:

| fixture | counter | clean input | broken input | moves |
| --- | --- | ---: | ---: | :-: |
| `malformed_record` | `records_rejected` | 0 | 4 | yes |
| `duplicate_node_id` | `duplicate_node_ids` | 0 | 1 | yes |
| `budget_overrun` | `content_over_budget` | 0 | 1 | yes |
| `missing_plane` | `contract_violations` | 0 | 1 | yes |
| `missing_revision` | `contract_violations` | 0 | 1 | yes |
| `dangling_provenance` | `provenance_refs_dangling` | 0 | 1 | yes |

The zeros in the corpus table above now carry information: the same counters
have been shown non-zero on input that deserves it. Every new guard also has a
**mutation probe** — its condition is rewritten to a dead branch, the module is
recompiled, and the check asserts the violation goes unnoticed in the mutant.

One mutation result is kept rather than smoothed: removing the ref-resolution
guard does **not** let a dangling ref through, because the content-address
check behind it still fires (`provenance_ref(None) != ref`). That guard is
load-bearing for the diagnosis, not for the rejection. Claiming one
load-bearing guard there would have been the easier sentence and the wrong one.

### Honest caveats

- **s01 is now wired for real, and the old adapter was wrong in shape.**
  `s01_adapter.py` assumed a JSONL stream with an alias table. s01 emits no
  stream: its contract is `build_index(root) -> ProjectIndex` plus
  `resolve_module -> [(ast.Call, Resolution)]`. No alias table over JSON keys
  could have absorbed that, so the adapter was deleted rather than kept as a
  plausible-looking join that cannot work. `s01_upstream.py` consumes the real
  contract; line ranges come from s01's own parsed tree, so no locator is
  guessed.
- **The s01 column is NOT reproducible from this slice alone, and the external
  commit is named.** Every code-plane number here — 318 modules, 5,739 records,
  12,788 joined edges, the s01 byte totals — is produced by s01's resolver in a
  **sibling worktree**. Nothing s06 commits determines them. Re-running this
  README's s01 figures requires that exact upstream, which is now pinned by
  content inside the artifact rather than described in prose:

  | | |
  | --- | --- |
  | `s01_index.py` | `sha256:213d7f888e868453fe69121bf3daa22e1fc9bf2d4e7f0d565ca06a6c66068ded` |
  | `s01_resolver.py` | `sha256:6b0604f78432167d216c2c9faaaf5e4255a71d23a22c2fbbb2d3fa8a5314396d` |
  | combined `input_digest` | `sha256:0b98dcd87afbb5d5471933b9d3e318beecaef8c0ae0eb378e519e240eddaeac5` |
  | s01 worktree HEAD | `d4f363f669d4bb126ed56a6ce8db45f4dc56b4f9` |

  Those two files are the whole upstream: `s01_resolver` imports only
  `s01_index` and the stdlib. The pin rides in the code-plane provenance block,
  which is content-addressed and referenced by every card, so the upstream
  reaches `card_id` — change s01 and the corpus changes identity loudly instead
  of quietly reporting different numbers under the same description. Before
  this, a card recorded only `"source": "s01_resolution"` and an
  `extractor_version` of `"1"`, a constant that does not move when s01 moves.

  The HEAD is reported **beside** the digest and never instead of it. That is
  not hypothetical: s01's HEAD moved under this lane mid-session
  (`16fab41e` → `d4f363f6`) and was carrying uncommitted edits before that.
  Neither imported module changed across that range — which is what licenses
  the before/after correction above to be read as one measurement rather than
  two.
- **The cross-lane coupling is a named gap, not prose.** s01 lives in a
  sibling worktree and is located by `--s01-path`, then `F2_S01_PATH`, then a
  sibling search. When none resolves, the run falls back to the stand-in and
  emits one structured record (`s06-upstream-s01-unreachable`, with `wants`,
  `effect`, `resolution` and where it looked) — once per build, not inlined
  into 8,466 cards. `--no-s01` forces that path so the fallback is exercised
  rather than described.
- **The knowledge plane is still the stand-in's**, because s01 is a code-plane
  resolver and has none. The split is recorded per plane in the provenance
  book; it is not a claim that s01 produced knowledge nodes.
- The size numbers are canonical JSON bytes, not tokens. An embedder's cost is
  the `content` block, not the envelope; a store's cost is both. Do not quote
  the envelope share as an embedding overhead.
- The s01 and stand-in corpora are **not** budget-equal comparisons of
  retrieval quality and must not be cited as one. s01 attaches 83% more edges;
  that is a different corpus, not a better one, and this slice measures cost
  and determinism only.
- The knowledge plane here is heading-structure only. Wiki links are captured
  as unresolved link names; no crosslink is verified, and §6 is explicit that
  an unverified similarity stays a proposal.
- Two planes are covered, two (type, data) are not. This is not a four-plane
  demonstration and must not be cited as one.

### Boundary

The slice imports nothing from `daedalus/`, nothing in `daedalus/` imports it,
and it contains no effectful entrypoint — `main()` only prints. Cards are
proposal carriers: they never become evidence and they promote nothing.

Checks: `python -m pytest experiments/forest_v2/s06_cards/` → **100 passed**
[MEASURED] — 41 from the first version, plus the provenance-ref contract and
its break-even limit, the budget guards, the six negative-path fixtures, one
mutation probe per new guard, the real-s01 wiring, the seven edge-join guards
and the eight upstream-pin guards.

Both new guard families are reproducible from **this slice alone**: they drive
the real code paths against an injected stand-in for s01's two modules over a
tree in `tmp_path`, so neither needs the sibling worktree. A guard that depends
on another lane's HEAD is not a guard this slice can run.

## Slice s08 (2026-08-18): graph baselines — `s08_graph_baselines/`

Sub-spec, frozen before the run.  This slice does not test the Project Twin;
it builds the two **baselines** the Twin will have to beat, so that a later
gain has something to be a gain *against*.  Master plan §10 (Gate 3) names
them; §13 turns both into kill criteria.

- **Hypothesis (falsifiable, two parts):**
  (a) *code-only graph retrieval* — ranking a module by the import/call
  neighbourhood of a lexical seed set retrieves documents that lexical
  matching alone misses, and the effect survives a degree-preserving rewiring
  of the graph;
  (b) *four separate single-plane indices without fusion* — four independent
  BM25 indices with no cross-plane scoring reach materially less than one
  index over the same documents, and the loss is attributable to plane
  routing rather than to ranking.
  Both are stated so a null result is a result.  A null (a) means the code
  graph is not a retrieval signal at this granularity; a null (b) means
  "four independent indices perform equivalently" — plan §13, verbatim.
  **The frozen text above is left exactly as it was written.  How (b) was
  first measured against it was wrong on two counts — see "What was withdrawn"
  below.  The result now standing for (b) is a null against the comparator
  this text names.**
- **Contract of the outputs.**  `s08_api.py` fixes the shared call, the one
  slice s07 and slice s08 must both answer:
  `retriever.query(text: str, k: int) -> list[Hit]`, with
  `Hit(doc_id, score, plane, locator, why)` and
  `doc_id == f"{plane}:{locator}"`.  Documents are `Document(doc_id, plane,
  locator, text, symbols, tokens)`, plane ∈ {code, type, data, knowledge}.
  Scores are comparable **only within one retriever** — four independent BM25
  scales are not commensurable and this slice refuses to pretend otherwise.
  `s08_selftest.py` prints exactly one JSON object and writes nothing.
- **Scope:** read-only, pure stdlib, no repository imports, no writes, no
  network, no subprocess, no model calls.  The corpus indexes `daedalus`,
  `tools`, `runs` (code), `docs`/`runs`/root Markdown (knowledge), and
  schema-shaped files under `daedalus`/`docs`/root (data);
  `runs/**/*.json` (3329 receipt files) is excluded as evidence, not data.
  `experiments/` is not indexed, so the slice never measures itself.
- **Budget:** ≤ 4 h implementation, one process, no spend.  Measured run cost
  after the correction: corpus build 22.9 s, index build 8.5 s, whole self-test
  149.6 s wall [MEASURED] — the added arms and the second query set roughly
  triple the earlier ≈ 40 s.
- **Expiry: 2026-09-15.**  Re-measure before reuse; the tree moves weekly.

### RAW measurement (2026-08-18, this worktree @ `49e40793`) [MEASURED]

> **This section replaces the first reported run.**  An adversarial review found
> two defects in it, both biased *towards* the four-plane hypothesis.  The
> retraction is spelled out under "What was withdrawn" below; the numbers here
> are the corrected ones.

Corpus: 1037 documents — code 318, type 289, data 65, knowledge 365;
1,066,495 tokens; 0 unparseable code files, 0 oversize skips.
Graph: 318 modules, 992 undirected edges, mean degree 6.239, 14 isolated
modules.  Frozen queries: 600 = 3 families × 200, seed 20260818, deterministic,
**unchanged**.  Added non-code-gold families: 138 (seed 20260819).

Query-token overlap with the own gold document (the honesty column):
`symbol` 1.0, `docstring` 1.0, `knowledge_ref` 0.6252, `doc_ref` 0.5847,
`data_ref` 0.1618.  The first two families are lexically easy by construction.

All 600 frozen queries, RAW hits out of 600:

| retriever | R@1 | R@5 | R@10 | MRR | hits @1/@5/@10 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `bm25_code_only` (control) | 0.5483 | 0.7650 | 0.8183 | 0.6432 | 329/459/491 |
| `graph_code_only` (a) α=0.5, 2 hops | 0.3717 | 0.7400 | **0.8283** | 0.5256 | 223/444/497 |
| `graph_code_only` rewired (control) | 0.4767 | 0.7517 | 0.8183 | 0.5926 | 286/451/491 |
| `four_plane_no_fusion` (b, round-robin) | 0.5483 | 0.6733 | 0.7200 | 0.5816 | 329/404/432 |
| `union_no_fusion` (b, per-plane top-k) | 0.5483 | 0.7650 | 0.8183 | 0.6432 | 329/459/**491** |
| `union_no_fusion` truncated to 10 | 0.5483 | 0.7650 | 0.8183 | 0.6432 | 329/459/491 |
| `union_no_fusion` code-LAST order | 0.0000 | 0.0000 | 0.0067 | 0.0346 | 0/0/4 |
| `bm25_single_index_all_planes` | 0.3883 | 0.6617 | 0.7300 | 0.5035 | 233/397/438 |

The 138 added queries whose gold label is **not** a code document, and the
extended 738:

| retriever | non-code @1/@5/@10 (n=138) | extended @1/@5/@10 (n=738) |
| --- | ---: | ---: |
| `bm25_code_only` | 0/0/**0** | 329/459/491 |
| `graph_code_only` | 0/0/**0** | 223/444/497 |
| `four_plane_no_fusion` | 0/12/32 | 329/416/464 |
| `union_no_fusion` | 0/0/1 | 329/459/492 |
| `union_no_fusion` code-LAST | 3/7/10 | 3/7/14 |
| `bm25_single_index_all_planes` | 10/39/**49** | 243/436/487 |

Gross rescue/loss **at every cutoff** (net deltas hide which system you have;
one cutoff hides which direction you have).  net = only B − only A:

| pair | k | both | only A | only B | neither | net |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A=`bm25_code_only`, B=`graph` | 1 | 182 | 147 | 41 | 230 | **−106** |
| A=`bm25_code_only`, B=`graph` | 5 | 423 | 36 | 21 | 120 | **−15** |
| A=`bm25_code_only`, B=`graph` | 10 | 482 | 9 | 15 | 94 | +6 |
| A=`graph rewired`, B=`graph` | 1 | 184 | 102 | 39 | 275 | **−63** |
| A=`graph rewired`, B=`graph` | 5 | 420 | 31 | 24 | 125 | **−7** |
| A=`graph rewired`, B=`graph` | 10 | 484 | 7 | 13 | 96 | +6 |
| A=`no_fusion`, B=`single index` | 1 | 229 | 100 | 4 | 267 | **−96** |
| A=`no_fusion`, B=`single index` | 5 | 374 | 30 | 23 | 173 | **−7** |
| A=`no_fusion`, B=`single index` | 10 | 415 | 17 | 23 | 145 | +6 |
| A=`no_fusion`, B=`bm25_code_only` | 1 | 329 | 0 | 0 | 271 | 0 |
| A=`no_fusion`, B=`bm25_code_only` | 5 | 404 | 0 | 55 | 141 | +55 |
| A=`no_fusion`, B=`bm25_code_only` | 10 | 432 | 0 | 59 | 109 | +59 |
| A=`union_no_fusion`, B=`bm25_code_only` | 1 | 329 | **0** | **0** | 271 | **0** |
| A=`union_no_fusion`, B=`bm25_code_only` | 5 | 459 | **0** | **0** | 141 | **0** |
| A=`union_no_fusion`, B=`bm25_code_only` | 10 | 491 | **0** | **0** | 109 | **0** |
| A=`union_no_fusion`, B=`single index` | 1 | 229 | 100 | 4 | 267 | −96 |
| A=`union_no_fusion`, B=`single index` | 5 | 396 | 63 | 1 | 140 | −62 |
| A=`union_no_fusion`, B=`single index` | 10 | 438 | **53** | **0** | 109 | −53 |

The graph pairs are not the only ones that flip: `no_fusion` vs the named
single joint index is **−96 / −7 / +6** across k=1/5/10, so the +6 that the
frozen-600 verdict rests on is the one cutoff of three where the joint index is
ahead.  The `union_no_fusion` tie with `bm25_code_only` is the opposite case and
is now shown to be a tie at **every** cutoff, 0 discordant queries throughout,
not only at k=10.

### What the numbers say, including against the hypothesis

1. **(a) is refuted as stated, and the "surviving remainder" was a
   single-cutoff artefact.**  The graph buys +6 documents at k=10
   (491 → 497, +1.0 pp) and *costs* 106 at k=1 (329 → 223, −17.7 pp); MRR falls
   0.6432 → 0.5256.  Propagated mass flows into high-degree modules and pushes
   the correct answer down.  Against the degree-preserving rewired control —
   the comparison plan §14.2 actually names — the sign **flips with the
   cutoff**: net **−63 at k=1**, **−7 at k=5**, **+6 at k=10**.  The earlier
   reading ("structure contributes about one percentage point") quoted the last
   of those three and called it the remainder.  It is the only cutoff at which
   the real graph beats its own randomised control, and the k=1 effect against
   that control is **ten times larger in the opposite direction**.  Read across
   all cutoffs, randomised edges do *not* perform worse than real ones; below
   k=10 they perform better.
2. **α = 0 is the best-ranking setting, and it is the control.**  Post-hoc
   sweep over the same 600 queries: α=0.0 → MRR 0.6432 (identical to
   `bm25_code_only`, which is also the consistency check that the two paths
   agree), α=0.25 → 0.6254, α=0.5 → 0.5256, α=0.75 → 0.4333.  Recall@10 peaks
   at α=0.25 (499/600, 0.8317).  Monotone in the wrong direction for the
   hypothesis; reported, not buried.
3. **(b) is NOT confirmed.  The earlier confirmation is withdrawn — see below.**
   The un-starved no-fusion arm ties the code-only control exactly: 491 = 491,
   rank-identical on **600 of 600** queries, 0 rescued and 0 lost.  Against the
   comparator the frozen sub-spec actually names it goes the other way: the
   no-fusion arm rescues 53 and loses 0.  On the 138 non-code-gold queries the
   direction reverses again and the single joint index wins (49 against 32 and
   1).  Three query sets, three different signs — the honest summary is that
   (b) is *comparator- and query-set-dependent*, which is not a confirmation
   of anything.
4. **The routing cost is the whole story, and the fusion question is still NOT
   answered.**  Per-plane hits@10 of the four indices (out of 200 per family)
   are code 190 / 117 / 184 for docstring / knowledge_ref / symbol, and
   type = data = knowledge = **0** on all three frozen families, because every
   gold label there is a code document by construction.  The plane oracle
   therefore equals the code index exactly.  This slice measures the *cost of
   not routing*; it cannot measure the *value of fusing*, because no fusion
   retriever exists in it.
5. **A fixed plane order is a hidden prior worth almost everything here.**  The
   union arm's tie with the code-only control is not a property of no-fusion
   retrieval; it is a property of putting the code block first.  Reverse the
   order and the same arm scores 4/600 instead of 491/600.  Concatenation order
   is not a cross-plane score comparison, but it decides rank just as firmly,
   and on a query set with only code gold labels the code-first order is
   exactly the flattering one.  Stated because it would otherwise read as a
   result rather than as a choice.

### What was withdrawn (2026-08-18)

An adversarial review found two defects in the first reported run; correcting
them surfaced a third, of the same class, in the graph half of the slice.  All
three bias towards the four-plane hypothesis, so all three are retracted here
rather than reworded.

**Withdrawn claim 1 — "`no_fusion` is *strictly dominated* by
`bm25_code_only`: 0 queries found that code-only missed, 59 lost."**  That was
an artefact of slot allocation, not a property of no-fusion retrieval.  The
arm split ONE budget of k slots round-robin across four planes, so the only
plane that can hold a code gold label received slots 1, 5 and 9 — its top-3.
The measurement that refutes the claim:

| measurement | hits of 600 |
| --- | ---: |
| `four_plane_no_fusion` @10 (the arm as reported) | 432 |
| `bm25_code_only` @**3** (what the arm effectively had) | 430 |
| `union_no_fusion` @10 (per-plane top-k, no shared budget) | **491** |
| `bm25_code_only` @10 (the control it was said to lose to) | **491** |

`union_no_fusion` gives each plane its own top-k and concatenates; it compares
no score across planes anywhere.  It ties the control exactly, rank for rank,
on all 600 queries.  The clipped row in the table above shows the tie is not
bought with a bigger budget: truncated to the same 10 returned documents it is
still 491.  "Strictly dominated" was measuring the handicap, not the design.

**Withdrawn claim 2 — the comparator was substituted.**  The frozen sub-spec
names *"one index over the same documents"*, i.e.
`bm25_single_index_all_planes`.  The confirmation was reported against
`bm25_code_only`, a different and much stronger comparator over a subset of the
documents.  Re-reported against the named one (materiality declared in this
correction, not at freeze time: |Δ hits@10| ≥ 5% of the query set with the same
sign at k=1, 5 and 10):

| query set | arm | Δ hits @1/@5/@10 vs named comparator | verdict |
| --- | --- | ---: | --- |
| frozen 600 | `four_plane_no_fusion` | +96 / +7 / −6 | NULL |
| frozen 600 | `union_no_fusion` | +96 / +62 / +53 | REFUTED (opposite direction) |
| extended 738 | `four_plane_no_fusion` | +86 / −20 / −23 | NULL |
| extended 738 | `union_no_fusion` | +86 / +23 / +5 | NULL |
| non-code gold 138 | `four_plane_no_fusion` | −10 / −27 / −17 | CONFIRMED |
| non-code gold 138 | `union_no_fusion` | −10 / −39 / −48 | CONFIRMED |

Against the named comparator, hypothesis (b) is a **null** on the query set it
was frozen against, and the sub-claim that survives is confirmed only on the
138 queries whose answer the code plane cannot hold.

**Withdrawn claim 3 — "structure contributes about one percentage point at
k=10, and nothing at k=1."**  Found while correcting the first two, in the
graph half of the slice, and it is the same defect one level down: the first
two runs emitted crosstabs at **k=10 only**, which for the graph pairs is the
single cutoff where the graph wins.  Against the degree-preserving rewired
control that plan §14.2 names:

| cutoff | both | only rewired | only graph | neither | net for graph |
| ---: | ---: | ---: | ---: | ---: | ---: |
| k=1 | 184 | 102 | 39 | 275 | **−63** (−0.1050) |
| k=5 | 420 | 31 | 24 | 125 | **−7** (−0.0117) |
| k=10 | 484 | 7 | 13 | 96 | +6 (+0.0100) |

The k=1 effect is an order of magnitude larger than the k=10 effect and points
the other way.  "A one-point effect is not a foundation; it is a measurement"
was true as far as it went, but it quoted the one cutoff that favours the
hypothesis and omitted the two that refute it.  §14.2 ("degree-preserving
randomized cross-plane edges perform equivalently") is not answered by the
+6 row alone; read across cutoffs, the randomised control is *better* than the
real graph below k=10.  The self-test can no longer emit a single-cutoff
crosstab, and a check enforces it.

### Kill criterion §13 "four independent indices perform equivalently to cross-plane fusion"

**Verdict: NOT DECIDABLE AS STATED.**  Entered as the result, replacing the
earlier "instrumented here, not evaluated" framing, which implied the
instrumentation was sound.

Two independent reasons:

1. **No second arm exists.**  This slice contains no cross-plane fusion
   retriever, so the criterion's comparison cannot be run at all.  What is
   measurable is the weaker question "four independent indices vs *one joint
   index*", and a joint index is not fusion.
2. **The query set cannot decide it.**  All 600 frozen gold labels are code
   documents.  On such a set any cross-plane method can only spend slots on
   planes that are guaranteed not to hold the answer, and a code-only index
   cannot be beaten by anything.  The criterion is structurally unfalsifiable
   here, in the direction that favours the hypothesis.

What the added non-code gold labels *do* show, for the weaker joint-index
question (n=138, hits@10): `bm25_code_only` 0, `union_no_fusion` 1,
`four_plane_no_fusion` 32, `bm25_single_index_all_planes` **49**.  When the
answer can live outside the code plane, one joint index beats every no-fusion
arm — evidence *against* "four independent indices perform equivalently", for
the joint-index comparison only.  The plan's actual criterion stays open until
a fusion arm exists.

Closing it needs two things this slice does not have: a real cross-plane fusion
retriever, and gold labels in all four planes.

### The added non-code gold labels

The frozen 600 are untouched.  138 queries were added whose gold document is
not a code document, because without them the question above cannot be asked:

- `doc_ref` (**124**, gold in the knowledge plane) — a prose line in one
  Markdown file naming another Markdown file; the named path's tokens are
  stripped from the query, so the prose has to carry it.  Overlap with gold
  0.5847.
- `data_ref` (**14**, gold in the data plane) — the same derivation for
  schema-shaped files.  Overlap 0.1618.  **n = 14 is small**; treat its numbers
  as an existence proof, not as a rate.

Each gold document is capped at 4 mentions so a much-referenced file cannot
supply a family alone, and sampling uses its own generator (seed 20260819), so
the frozen families' stream is bit-for-bit unchanged.  Extended set: 738, gold
mix code 600 / knowledge 124 / data 14.

**Named gap — the type plane still has zero gold labels.**  No mechanical
derivation exists in this tree: the type plane is a proxy built from the same
source files as the code plane, and nothing references it as an artifact.  So
of the four planes, three can now be a retrieval target and one cannot.  Order
of magnitude: 289 type documents (27.9% of the corpus) carry 0 gold labels, and
their marginal contribution (plan §13, "a plane has no marginal contribution in
ablation") remains untested.  Closing it needs real type artifacts, not a
better query rule.

Also unchanged and still true: **one number is a query-set artefact, measured
rather than argued away.**  For the `knowledge_ref` family the query is lifted
from a Markdown file that the all-planes index also contains; that source file
lands in the top ten for **181 of 200** queries at mean rank 2.26.  The
single-index retriever's weak knowledge_ref R@1 (0.1200 vs code-only 0.3100) is
therefore partly a property of the query set, not of the retriever.

### Decidability audit: can this query set produce BOTH verdicts?

Asked after the s10 kill-criterion evaluator consumed the correction above and
observed that on the frozen 600 every gold label is a code document, so §13's
"four independent indices" criterion is structurally unfalsifiable there in the
direction that favours the hypothesis.  The commit that added 138 non-code gold
labels looked like the answer.  Measured, it is the answer to one of the two
criteria and not to the other.  Corpus pinned by digest
`b0d146a34356356782a6b4817b3398dd202ebdbc9682b8f54c3d8cd64b7175a2`; the
self-test now prints that digest beside every number it reports.

**Gold-label plane distribution** (all [MEASURED], `decidability_audit`):

| query set | n | code | knowledge | data | type |
| --- | ---: | ---: | ---: | ---: | ---: |
| frozen 600 | 600 | 600 | 0 | 0 | 0 |
| added non-code | 138 | 0 | 124 | 14 | 0 |
| extended | 738 | 600 | 124 | 14 | **0** |

Corpus for scale: code 318, type 289, data 65, knowledge 365 documents.  Three
of four planes can now hold an answer; the type plane holds 289 documents and
**zero** gold labels, and no mechanical rule in this tree yields one.

**Which planes each arm can return at all** — the number that decides what a
comparison is able to refute, measured over the extended 738 at k=10:

| arm | code | type | data | knowledge | can return non-code |
| --- | ---: | ---: | ---: | ---: | --- |
| `bm25_code_only` | 7345 | 0 | 0 | 0 | **no** |
| `graph_code_only` | 7370 | 0 | 0 | 0 | **no** |
| `graph_rewired` | 7370 | 0 | 0 | 0 | **no** |
| `four_plane_no_fusion` | 2447 | 1654 | 1468 | 1801 | yes |
| `union_no_fusion` | 7345 | 4648 | 5809 | 7359 | yes |
| `bm25_single_index_all_planes` | 3202 | 148 | 103 | 3917 | yes |

#### §13 "degree-preserving randomized cross-plane edges perform equivalently"

**Second arm exists** (`graph_rewired`).  **Verdict: still NOT resolvable in
either direction by this query set**, for two independent reasons, and the
non-code labels make it worse rather than better.

1. *The added labels carry zero information for it.*  Both arms index the code
   plane only, so on all 138 non-code-gold queries both score 0 and every one of
   them is concordant.  Discordant (informative) queries:

   | query set | n | k=1 | k=5 | k=10 |
   | --- | ---: | ---: | ---: | ---: |
   | frozen 600 | 600 | 141 | 55 | 20 |
   | added non-code | 138 | **0** | **0** | **0** |
   | extended | 738 | 141 | 55 | 20 |

   The discordant counts on 738 are *identical* to those on 600 while n grows
   23%.  An equivalence test run on the extended set therefore reports a
   smaller difference (6/738 = +0.0081 instead of 6/600 = +0.0100) and a
   tighter interval **from no new evidence at all**.  s10 projected that at the
   observed discordance rate n=1800 would flip 14.2 from INCONCLUSIVE to
   EQUIVALENT, i.e. fire KILL.  Padding with queries neither arm can answer is
   a way to walk to that n without measuring anything — the fastest route to a
   KILL verdict here is to add queries that contain no information.
2. *The object the criterion names does not exist in this slice.*  The graph
   has **992 edges and 0 of them cross a plane**: every edge joins two code
   modules (endpoint plane counts: code 1984, nothing else).  The rewiring
   control randomises an intra-code-plane import/call graph.  Whatever the
   graph-vs-rewired comparison measures, it is not "cross-plane edges perform
   equivalently".

**A KILL verdict for 14.2 from this query set would be an artefact** — evidence
about the arms' index scope and the graph's plane coverage, not about the
four-plane prior.  Stated plainly because the measurement says so, not because
it is the comfortable answer: the earlier −63/−7/+6 reading against the rewired
control still stands as a refutation of *this graph's* claimed structural gain,
but it cannot be promoted into a verdict on the plan's §13 clause.

#### §13 "four independent indices perform equivalently to cross-plane fusion"

**Second arm does not exist.**  No cross-plane fusion retriever is implemented
here, so the criterion has one arm on *any* query set.  That is a missing-arm
problem, and gold labels cannot fix it.  **Verdict: not resolvable in either
direction**, unchanged by the 138.

What the 138 *do* fix is the weaker joint-index proxy — and there the query set
now cuts both ways, which it did not before.  Hits@10 and discordant counts for
`union_no_fusion` vs `bm25_single_index_all_planes`:

| query set | union | joint index | net @10 | discordant k=1/5/10 |
| --- | ---: | ---: | ---: | ---: |
| frozen 600 | 491 | 438 | **union +53** | 104 / 64 / 53 |
| added non-code 138 | 1 | 49 | **joint +48** | 10 / 39 / 48 |
| extended 738 | 492 | 487 | union +5 | 114 / 103 / 101 |

Both directions are reachable, both are populated, and the two halves disagree.
That is a real finding about the cost of not routing.  It is **not** the plan's
criterion and must not be reported as one: a joint index is not fusion, and the
suite now refuses any arm named "fusion" while no fusion retriever exists.

#### What would make them resolvable

- **14.2**: cross-plane edges to rewire — the graph currently has none — and
  arms whose index can return the plane the gold label lives in.
- **14.3**: a real cross-plane fusion retriever as the second arm.
- **both**: gold labels in the type plane, which no mechanical rule in this tree
  yields.

Mutation evidence for the five checks added with this audit (each re-introduced
defect, each turning the suite red from 51 green): census blind to cross-plane
edges → 1 failed; `reachable_planes` always claiming non-code → 1 failed;
`informative_queries` counting agreement instead of discordance → 1 failed;
`corpus_digest` returning a constant → 1 failed; an arm renamed to
`cross_plane_fusion` → 1 failed.

### Honest caveats

- The type plane is a **proxy**: the tree carries no `.pyi`, so type documents
  are annotations/bases extracted from the same source files the code plane
  indexes.  A plane derived from another plane cannot demonstrate independent
  marginal contribution (plan §13) — that ablation needs real type artifacts.
- All gold labels of the **frozen 600** are code documents; two of its three
  families draw their text from the gold file itself (overlap 1.0).  Those
  families measure string matching more than retrieval and are kept only as a
  sanity floor.  The 138 added queries fix the plane mix, not the leakage.
- **The no-fusion baseline has two arms and neither is "the" one.**  The
  round-robin arm is budget-equal by construction but starves whichever plane
  holds the answer; the union arm is un-starved but returns up to 4k documents
  and imposes a fixed plane order.  They disagree by design — 432 vs 491 on the
  frozen set, 32 vs 1 on non-code gold — so any single-number "no-fusion
  result" is a choice of arm, and must be reported as one.
- The materiality rule (5% of the query set, consistent sign across cutoffs)
  was declared **in this correction, after seeing the first run**, not at
  freeze time.  It is a stated decision procedure, not a pre-registered one.
- Graph weights (import 1.0, call 0.5/site capped at 10), α=0.5, 2 hops and
  25 seeds were frozen before the run.  The sweep is labelled post-hoc and no
  headline number was selected from it.
- The rewiring control preserves each module's edge *count* exactly; summed
  edge weight per node can shift, because weights travel with the swapped
  edge.
- One query of 600 yields no tokens after stopword removal and returns empty
  for every retriever; it is counted as a miss for all of them equally.
- Single machine, single run, no repeated trials, no confidence intervals.
  Differences of a few documents out of 600 are not separated from noise here.

### How to run

```text
python experiments/forest_v2/s08_graph_baselines/s08_selftest.py
python -m pytest experiments/forest_v2/s08_graph_baselines/ -q
```

42 checks, all green at `49e40793` [MEASURED].  They assert mechanics on a
synthetic four-plane tree, never this repository's measured numbers; two
structural checks verify that the slice imports no repository package and calls
nothing that writes.

Six of them exist to keep the two withdrawn defects from coming back, and each
was verified by re-introducing the defect and watching it fail [MEASURED]:

| defect re-introduced | checks that went red |
| --- | ---: |
| union arm shares one budget again (the starvation) | 3 of 42 |
| union arm sorts the concatenation by score (cross-plane comparison) | 4 of 42 |
| per-gold-document mention cap removed | 1 of 42 |
| non-code families yield nothing again | 2 of 42 |

Restoring each returned the suite to 42 green.

## Slice s10 (2026-08-18): the kill-criteria evaluator

`experiments/forest_v2/s10_kill/` turns the master plan's kill criteria into
code, so that stopping a research track becomes a computed proposal with a
stated uncertainty instead of a judgement call made under sunk cost.

**Section numbering:** the kill criteria are **section 14** in plan revisions 5
and 6. They were section 13 in earlier revisions; section 13 is now "Forbidden
default directions". The code no longer *cites* the live numbering, it reads
it: `plan_register.py` matches the section by title and takes the number from
the heading, so the next renumbering is a red check rather than a wrong
citation. Section 14 is byte-identical in revisions 5 and 6 [MEASURED].

### Frozen specification

- **Hypothesis (falsifiable):** the mechanically checkable part of section 14
  can be decided from a retrieval result set alone, and an evaluator that
  applies it will withhold judgement exactly where the plan's own honesty
  rules demand it (too few cases, unequal budgets, equivalence that was never
  actually tested). Refuted if a constructed kill fails to fire, a constructed
  pass fires anything, or a guard has to be bypassed to get a usable verdict.
- **Contract of the outputs:** the evaluator reads `forest_v2.s10.kill-input/1`
  JSON (`schema.py`) and emits, per criterion, one of `KEEP` / `KILL` /
  `INCONCLUSIVE` / `UNDECIDABLE` / `NOT_EVALUABLE` with its comparison
  intervals, plus a per-prior rollup. Text and `--json` renderings carry the same content.
  **Advisory: it gates nothing, promotes nothing, blocks nothing, writes
  nothing.** A `KILL` is a proposal to open an amendment (plan section 15).
  Its exit code says whether the evaluation ran, never what it found.
- **Scope:** pure stdlib, read-only, no repository imports, no network, no
  subprocess, no writes. Consumes serialised results, so it never imports the
  harness it grades. It reads exactly one repository file, the master plan,
  and only to derive and verify the criteria register.
- **Budget:** one package, ~2.6k lines of implementation plus ~0.7k of
  self-check, re-runnable in seconds. No model calls, no spend.
- **Expiry: 2026-09-15.** After that, re-measure before reuse. The criteria
  themselves no longer expire quietly: they are re-derived from the live plan
  on every check run, and a drifted register is a red check rather than a
  stale list nobody noticed. This bullet used to say "re-derive the criteria
  from the live plan before trusting a verdict" and left the doing to a
  future reader -- who was, predictably, nobody.

### RETRACTED (2026-08-18): the published coverage was 60%, the truth is 56.3%

**Withdrawn claim:** "Nine of the plan's *fifteen* kill criteria are decidable"
— i.e. 9/15 = 60% coverage, as printed by `report.py` and by this README.

**What the error was.** Section 14 of the living plan lists **sixteen**
bullets. The criteria register was copied by hand and had lost one:
*"corpus licensing/provenance or extraction cost prevents reproducible reuse"*
(14.15) appeared nowhere — neither as a predicate nor as a declared
out-of-scope entry. Because the remaining entries were then numbered by hand,
the orchestration criterion slid into the freed index, so the code cited it as
`14.15` when the plan numbers it `14.16`: anyone checking a `14.15` citation
against the plan read a **different criterion** than the report meant. Nine
decided criteria divided by a denominator that had silently shrunk gave 60%
instead of 56.3%, and the check that existed to prevent exactly this pinned
the wrong constant with a confident reason (`"the plan lists 15 kill
criteria"`).

The number was not rounded, mis-typed or stale — it was computed from a
register that no longer matched the document it claimed to mirror. So the
repair is not a corrected constant. `plan_register.py` now parses section 14
out of the living plan at check time and compares the code register to it one
to one — count, order, `plan_ref`, and verbatim wording — and coverage is
`n_decided / n_registered`, computed. A plan that gains, loses, renumbers or
rewords a bullet turns
`test_the_register_matches_the_living_plan_one_to_one` red.

**Corrected figure: 9 of 16 = 56.3%.**

Two side effects of doing it this way, both worth having: the section number
is read from the plan too (it has already moved once, 13 → 14), and the
comparison spans revisions — section 14 is byte-identical in plan revisions 5
and 6, checked, so this register is valid against both [MEASURED].

### What it decides, and what it refuses to

Nine of the plan's sixteen kill criteria are decidable from a retrieval result
set (**9/16 = 56.3%**). Seven are not, and are reported as `NOT_EVALUABLE`
**with the reason and counted in the denominator**, because shipping nine
checks under the name "the kill criteria" would be the dishonest version —
and dividing them by fifteen is the same dishonesty with a decimal point.

| decided from retrieval results | needs evidence this format does not carry |
| --- | --- |
| 14.1 full beats code-only / BM25 | 14.5 graph movement predicts behaviour |
| 14.2 rewired cross-plane control | 14.10 revision-atomic snapshot cost |
| 14.3 four indices vs fusion | 14.11 embedding precision after verification |
| 14.4 per-plane ablation | 14.13 motif composition vs direct generation |
| 14.6 graph-conditioned prioritization | 14.14 Genesis round-trip conformance |
| 14.7 gain survives leakage scrubbing | **14.15 corpus licensing / provenance** |
| 14.8 extra tokens explain the gain | 14.16 orchestration transfer |
| 14.9 quality/cost frontier | |
| 14.12 held-out transfer | |

14.15 is out of scope for a reason stronger than "not yet": it is not a
retrieval question at all. Deciding it needs per-document corpus ingestion
metadata — source repository, revision, license, temporal cutoff, extraction
version and extraction cost (plan sections 5 and 9.1) — so *no* result set of
this schema can ever decide it. That is recorded in the register with the
reason attached, which is the difference between a stated limit and the
silent omission that produced the 60%.

Three design decisions carry the honesty of the whole slice:

1. **Absence of a difference is not evidence of equivalence.** Four criteria
   fire on *equivalence*. Implemented as "the difference was not significant",
   they would kill a prior faster the less you measured. So equivalence is a
   separate test against a declared practical margin (default +/-0.02): the
   whole interval must lie inside the band. A wide interval is `INCONCLUSIVE`,
   which is a real answer and never a soft pass.
2. **A win bought with a larger budget is not a win.** Unequal budgets
   downgrade the verdict they flatter and leave standing the verdict they
   argue against -- a loss on fewer tokens is starvation, not refutation.
3. **The metric is declared in the input, before the numbers are seen.** The
   evaluator reads that one metric and cannot shop for a friendlier cutoff.

### The dynamic-range precondition (2026-08-18) [MEASURED]

A census found that this evaluator could mint a hard `KILL` against the plan's
central research prior from data that cannot support it. Three measured
defects, all the same defect in different coordinates:

1. **A role label could manufacture a verdict.** `criteria.py` selected the
   14.3 treatment as `rs.find("fusion") or rs.find("full")`. Relabelling one
   string in a real s08 result set -- role `bm25` to role `fusion` on the
   frozen-600 routing run -- produced `14.3 verdict=KILL`, with no warning
   anywhere in the report. The fallback also graded 14.3 as `KEEP` on a
   synthetic run that had no fusion arm at all. **No cross-plane fusion
   retriever is implemented anywhere in this program** (s08 ships
   `LexicalRetriever`, `CodeGraphRetriever`, `FourPlaneNoFusionRetriever`,
   `UnionNoFusionRetriever`, `SinglePlaneOracleRetriever`; s09 ships
   `random_uniform`, `path_lexical`, `bm25`, `bm25_content_only`,
   `recency_prior`), so every 14.3 verdict this evaluator could emit was a
   category error.
2. **Arms were selected by role string, never by what they contain.** 14.2 is
   about *cross-plane* edges and was being computed on s08's graph: **992
   edges, 0 of them cross a plane**, endpoint plane counts `{code: 1984}`. The
   rewiring control randomises an intra-code import/call graph. Neither `KEEP`
   nor `KILL` from that comparison means anything about the plan's clause --
   and the `INCONCLUSIVE` it actually returned was the most dangerous of the
   three, because the remedy it invites is a bigger query set.
3. **The same blindness in the query set.** All 600 frozen gold labels are code
   documents; the 138 added non-code queries left the discordant counts
   identical while `n` grew 23%. The **type plane has zero gold labels
   anywhere in the program**, against 289 type documents (27.9% of the corpus).

The rule, in `plane_range.py`: **before any comparison metric is reported, emit
the cross-tab of gold-label plane x plane each arm can actually return, and
refuse the metric -- `UNDECIDABLE`, never a number -- when the gold labels
contain zero instances in any plane that distinguishes the two arms, or when an
arm sits at a structural 0%/100% ceiling.** The gate lives inside
`criteria._compare_arms`, the one function every comparison passes through, so
a criterion cannot report a number by forgetting to ask.

`UNDECIDABLE` is a fifth verdict, kept strictly apart from the other two
refusals because the remedies differ: `INCONCLUSIVE` -> run more;
`NOT_EVALUABLE` -> ship the arm; `UNDECIDABLE` -> neither helps, because the
distinguishing observation is not in the data. Conflating the first two is how
this class of error hides.

Applied to today's artifacts, every measured run refuses [MEASURED]:

| run | n | 14.2 | 14.3 |
| --- | ---: | --- | --- |
| `s08_graph_structure` | 600 | UNDECIDABLE | UNDECIDABLE |
| `s08_routing_frozen600_four_plane_no_fusion` | 600 | UNDECIDABLE | UNDECIDABLE |
| `s08_routing_frozen600_union_no_fusion` | 600 | UNDECIDABLE | UNDECIDABLE |
| `s08_routing_noncode138_four_plane_no_fusion` | 138 | UNDECIDABLE | UNDECIDABLE |
| `s08_routing_noncode138_union_no_fusion` | 138 | UNDECIDABLE | UNDECIDABLE |
| `s08_routing_extended738_four_plane_no_fusion` | 738 | UNDECIDABLE | UNDECIDABLE |
| `s08_routing_extended738_union_no_fusion` | 738 | UNDECIDABLE | UNDECIDABLE |

The rollup consequence, stated plainly: **on the measurements this project has
today, this evaluator decides none of the criteria that bear on the four-plane
prior.** `four_plane_project_twin` rolls up `0/9 decidable` on every measured
run -- two criteria UNDECIDABLE, the rest with no arm shipped.

`python -m experiments.forest_v2.s10_kill.cli --plane-census` reports which
planes can never be a retrieval target anywhere in the program. Today that is
the **type** plane: 289 documents, 0 gold labels in any query set.

Every new guard was mutation-tested: disabled at the source, one named test
watched go red, restored, baseline confirmed green. 11 of 11 are watched
[MEASURED].

| mutation | named test that goes red |
| --- | --- |
| restore the deleted `or rs.find("full")` fallback | `test_a_missing_fusion_arm_never_falls_back_to_the_full_arm` |
| accept the role label without checking the mechanism | `test_a_relabelled_arm_cannot_mint_a_fusion_verdict` |
| stop demanding a second returned plane from a fusion arm | `test_a_relabelled_arm_cannot_mint_a_fusion_verdict` |
| stop counting cross-plane edges for 14.2 | `test_142_is_undecidable_on_every_measured_run_in_the_program` |
| stop refusing when the distinguishing planes hold no gold label | `test_a_gold_set_blind_to_the_distinguishing_planes_is_undecidable` |
| stop refusing an arm pinned at a 0%/100% ceiling | `test_an_arm_pinned_at_a_structural_ceiling_is_refused` |
| stop refusing an arm that cannot reach any gold plane | `test_an_arm_that_cannot_reach_any_gold_plane_is_refused` |
| remove the gate from `_compare_arms` | `test_no_criterion_can_report_a_comparison_without_passing_the_gate` |
| conflate `UNDECIDABLE` with `INCONCLUSIVE` | `test_undecidable_is_distinct_from_inconclusive_and_not_evaluable` |
| count `UNDECIDABLE` as covered | `test_undecidable_does_not_count_as_covered` |
| stop refusing a run that declares no gold planes | `test_a_run_with_no_declared_gold_planes_reports_no_number` |

The first pass of that probe found one of these tests was **decoration**:
disabling the mechanism check changed nothing, because the relabelled arm was
already caught one line later for carrying no measured per-plane returns. The
test now includes the realistic attack -- a joint index that really does span
four planes and really does return documents from more than one, whose only
defect is that it compares no score across them -- which the mechanism check
alone catches.

### Self-test result (2026-08-18, synthetic ground truth) [MEASURED]

`python -m pytest experiments/forest_v2/s10_kill/ -q` -> **97 passed**
(2026-08-18, after the dynamic-range precondition; was 68 passed before it,
and 44 before the register repair). The table below predates the precondition
and its `decidable` column is one too high for every scenario without an
attested fusion arm -- which is all of them, because none exists.

Nine scenarios with constructed ground truth, all scores drawn at runtime from
a seeded PRNG (no fixture tables). Default config: CI95 percentile bootstrap,
10,000 resamples, margin +/-0.02, `min_cases` 10.

| scenario | cases | decidable | KEEP | KILL | INCONCLUSIVE | fired | sec |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| surviving_prior | 40 | 9 | 9 | 0 | 0 | - | 2.68 |
| no_gain | 40 | 2 | 1 | 1 | 0 | 14.1 | 0.50 |
| rewire_kill | 40 | 3 | 2 | 1 | 0 | 14.2 | 0.82 |
| leakage_kill | 40 | 3 | 2 | 1 | 0 | 14.7 | 1.06 |
| cost_kill | 40 | 2 | 0 | 2 | 0 | 14.1, 14.9 | 0.47 |
| held_out_kill | 60 | 3 | 2 | 1 | 0 | 14.12 | 0.89 |
| tiny_win | 80 | 2 | 1 | 1 | 0 | 14.1 | 0.91 |
| underpowered | 5 | 2 | 0 | 0 | 2 | - | 0.14 |
| budget_bought_win | 40 | 2 | 0 | 0 | 2 | - | 0.47 |

Every constructed kill fired its own criterion; the constructed pass fired
nothing. The headline comparison (14.1, full vs code-only) shows the guards
doing the work:

| scenario | verdict | mean diff | CI95 | n | state |
| --- | --- | ---: | --- | ---: | --- |
| surviving_prior | KEEP | +0.1503 | [+0.1430, +0.1581] | 40 | SUPERIOR |
| no_gain | KILL | +0.0012 | [-0.0028, +0.0052] | 40 | EQUIVALENT |
| tiny_win | KILL | +0.0035 | [+0.0020, +0.0051] | 80 | EQUIVALENT(but +) |
| underpowered | INCONCLUSIVE | +0.2065 | [-0.1500, +0.4489] | 5 | INCONCLUSIVE |
| budget_bought_win | INCONCLUSIVE | +0.1504 | [+0.1432, +0.1578] | 40 | SUPERIOR |

The last three rows are the point of the slice. `underpowered` holds a real
+0.21 effect and decides nothing, because five noisy cases cannot decide.
`budget_bought_win` shows a clean, significant win and is still withheld,
because the winner held 2.50x the tokens. `tiny_win` is a *statistically*
unambiguous win (CI entirely above zero) that is killed anyway for being
smaller than the practical margin -- with a warning saying exactly that.

Prior rollups are asymmetric on purpose: one fired criterion outranks any
number of passes, since the plan stops the track on any single one.
`rewire_kill` rolls up to `four_plane_project_twin = KILL (3/9 decidable)`
on 14.2 alone, while `surviving_prior` reaches `KEEP (7/9)` only because
every decidable criterion passed.

### Can this evaluator ever say KILL? [MEASURED]

The question the slice has to ask about itself. Synthetic scenarios prove the
machinery fires, which is not the same as a verdict being reachable from the
measurements this project actually has. Verdict: **it can, and one structural
bias toward KEEP was found and removed. On today's real numbers it withholds
— and the withholding is correct.**

**The bias that was there.** A criterion whose control arm a run never shipped
came back `NOT_EVALUABLE`, and `NOT_EVALUABLE` never blocked a KEEP. So a
prior could survive by being under-instrumented: ship `full`, `code_only` and
`bm25`, omit the rewiring control, the ablations, the scrubbed variant and the
token-matched arm, and every criterion that might have killed the prior is
simply absent — the fewer controls a run carried, the safer its prior looked.
The rollup now separates a *limit of the instrument* (a criterion this input
schema can never carry, e.g. 14.15) from a *hole in the run* (a criterion
implemented here that the run did not ask), and a prior with holes cannot
reach KEEP. `test_a_prior_cannot_reach_keep_while_its_controls_were_never_shipped`
pins it; `surviving_prior`, which ships every control, still reaches KEEP.

**On real data it withholds.** Slice s08's corrected 600-query run (@
`a0c8fabd`; s08's first run was retracted on 2026-08-18 and its withdrawn
tables are not reused here — both rows below survived the retraction
unchanged), rebuilt from
its published 2x2 counts (`measured_inputs.py`; both marginals and the pairing
come back out exactly, no score invented):

```text
python -m experiments.forest_v2.s10_kill.cli --measured s08_graph_structure
```

| criterion | verdict | mean diff | CI95 | n | rescued/lost |
| --- | --- | ---: | --- | ---: | --- |
| 14.2 graph vs its degree-preserving rewiring | INCONCLUSIVE | +0.0100 | [-0.0050, +0.0250] | 600 | 13 / 7 |

The interval reaches 0.0250 against a ±0.02 margin, so it is neither a win nor
demonstrable equivalence — and the evaluator says so instead of reading "not
significant" as "equivalent". This is a real limit worth stating: **with a
binary per-query metric, 600 paired queries cannot resolve inside a ±0.02
band.**

How far off is it? Holding s08's observed discordance rate (13 rescued, 7
lost, 580 tied) and scaling the query set, CI95 percentile bootstrap, 20,000
resamples [MEASURED — a power projection over the real effect shape, not more
data]:

| queries | mean diff | CI95 | state |
| ---: | ---: | --- | --- |
| 600 (s08 as run) | +0.0100 | [-0.0050, +0.0250] | INCONCLUSIVE |
| 1200 | +0.0100 | [+0.0000, +0.0208] | INCONCLUSIVE |
| **1800** | +0.0100 | [+0.0017, +0.0183] | **EQUIVALENT → 14.2 fires KILL** |
| 2400 | +0.0100 | [+0.0029, +0.0171] | EQUIVALENT |

So the criterion is reachable, and the gap is a factor of three in query
count, not a structural impossibility: at s08's own effect size a 1800-query
run would kill 14.2. (A graded metric — MRR, nDCG — would get there sooner
than more binary queries, since the variance is mostly the 0/1 quantisation.)
Every verdict from the real run also carries `run declares 1 seed(s)`; s08 was
a single run with no repeated trials.

**14.3 is refused, not answered — and that is the finding.** All six
`--measured s08_routing_*` runs report `0 of 16` criteria decidable. s08 built
**no cross-plane fusion retriever**, so the criterion's second arm does not
exist: `missing: fusion|full`. Its own verdict is "NOT DECIDABLE AS STATED".

The nearest measurable system is `bm25_single_index_all_planes` — *one joint
BM25 index* over all four planes' documents, a shared IDF space that never
compares or combines per-plane scores. **A joint index is not fusion.**
Labelling it `fusion` would have produced a 14.3 verdict out of a comparison
nobody ran — the substituted-comparator defect s08 itself had to retract,
committed one level up by the instrument built to catch it. Pinned by
`test_no_arm_of_a_measured_run_is_labelled_fusion` and by the refusal check
across every query set and both no-fusion instantiations.

Against that weaker joint-index question the answer is comparator- and
query-set-dependent, which is why it is reported here rather than rolled into
a verdict (hits@10, corrected s08 @ `a0c8fabd` [MEASURED]):

| query set | four independent indices | one joint index | direction |
| --- | ---: | ---: | --- |
| frozen 600 (all gold = code) | 432 round-robin / **491** union | 438 | union ties the code-only control exactly, 0 rescued 0 lost |
| non-code gold 138 | 32 / 1 | **49** | joint index wins; rescues 21, loses 4 |
| extended 738 | 464 / **492** | 487 | sign flips again |

Three query sets, three signs. Two further reasons no verdict belongs here:
the two no-fusion arms (`four_plane_no_fusion` round-robin vs `union_no_fusion`
per-plane top-k) disagree by design, so picking one *is* picking the answer —
both are shipped for that reason; and `union_no_fusion` scores **491/600
code-first against 4/600 code-last**, so a fixed plane order is a hidden prior
worth almost the entire result. Every no-fusion arm here names its plane order
in the report's new `ARMS AS LABELLED` block.

**The sharpest limit is not statistical.** On the frozen 600 every gold label
is a code document, so a cross-plane method can only lose slots to planes
guaranteed not to hold the answer and a code-only index *cannot be beaten*.
The criterion is structurally unfalsifiable there, in the direction that
favours the hypothesis. A kill instrument can be blind for reasons that have
nothing to do with its statistics — the query set decides what is refutable
before any interval is computed. The 138 non-code-gold queries fix the plane
mix but not the leakage, and the **type plane still carries zero gold labels**
(289 documents, 27.9% of the corpus), so 14.4's per-plane ablation is
untestable there too.

Because criteria select arms by *role*, a role label is all that stands
between "cross-plane fusion" and whatever a run actually measured, and the
evaluator cannot know the difference. So the report now prints every arm's id,
role and provenance note under `ARMS AS LABELLED`. That is a disclosure, not a
guard: it makes a substituted comparator visible to a reader. Nothing in this
package can detect one.

So: no criterion fires on the evidence available today, and the reason is
insufficient resolution and missing controls, not a KEEP-shaped evaluator.

### Mutation probe (2026-08-18) [MEASURED]

Checks that cannot fail are decoration. Each mutation was applied, the suite
run, and the tree restored.

| mutation | result |
| --- | --- |
| remove criterion 14.9 from `REGISTER` | **6 failed, 53 passed** — `test_the_register_matches_the_living_plan_one_to_one` red: `count: the plan lists 16 kill criteria, the code registers 15`, plus `position 16: ... the code registers nothing -- a criterion is missing, not out of scope` |
| reword plan bullet 14.3 (on a copy) | red: `14.3: wording differs / plan: 'four independent indices are basically fine' / code: 'four independent indices perform equivalently to cross-plane fusion'` |
| add a 17th bullet to the plan (on a copy) | red: `count: the plan lists 17 kill criteria, the code registers 16` + 15 misfiled-citation reports |
| drop 14.15, slide later refs up (**the landed defect**) | red: `misfiled citation: the register cites 14.15 for a criterion the plan numbers 14.16; anyone looking up 14.15 in the plan reads a different criterion` |

The real plan file is never modified: plan-side mutations are applied to a
copy in a temporary directory, and the helper asserts the tamper anchor still
matched, so a probe that mutates nothing fails instead of passing quietly.

### Honest caveats

- **Every number in the scenario tables is synthetic.** This slice measures the
  *evaluator*, not the Project Twin. The `--measured` runs are real s08
  numbers, but they are a *rebuild* from published aggregate counts, not a
  live re-run, and s08's own graph is a code graph — nothing here is evidence
  about the four-plane Twin. The first end-to-end real input will come from
  the s09 harness.
- **The s08 rebuild reproduces published pairings, not unpublished ones.**
  Where s08 printed a 2x2 the reconstruction is exact; where it did not, the
  joint is filled deterministically and no criterion consumes that pairing.
  The runs are deliberately kept apart for this reason rather than merged into
  one many-armed result set that would imply pairings nobody measured.
- **Upstream retractions propagate, they do not get patched over.** s08
  withdrew its starved round-robin comparison (432/0/59/109) on 2026-08-18;
  that table is deleted here rather than reworded, and
  `test_the_retracted_s08_comparison_is_not_reused` fails if it comes back. A
  retracted measurement republished downstream is how a corrected finding
  stays wrong.
- **The margin is a judgement, not a measurement.** +/-0.02 absolute on a 0..1
  metric decides the difference between `tiny_win` being a KILL and a KEEP. It
  should be pre-registered per campaign, not defaulted.
- **The input contract is s10's, not s09's.** s09 was still in flight when this
  was written, so the two were never wired end to end. The roles, budget and
  cost fields are shape-matched to s09's `contract.py` (arms, per-case scores,
  raw/scrubbed variants, cutoff metrics) but the adapter that emits this schema
  from an s09 run does not exist yet.
- **Bootstrap CIs on 40 paired cases are not a substitute for seeds.** The
  evaluator warns below 5 declared seeds; it cannot manufacture the repetitions
  the plan asks for.
- **The `NOT_EVALUABLE` seven are not "fine".** They are unmeasured. A prior
  whose only decidable criteria pass is a prior that survived a partial exam —
  which is now enforced rather than merely written here: a run missing the
  controls for criteria this evaluator implements cannot roll up to KEEP.
- **A verified register is not a verified evaluator.** The check proves the
  code's criteria list matches the plan's wording, order and numbering. It
  says nothing about whether each predicate is a *faithful operationalisation*
  of its bullet — that judgement stays with a reader, and 14.1's mapping of
  "the full representation" onto whatever arm a run labels `full` is the
  loosest joint in the whole slice.

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
