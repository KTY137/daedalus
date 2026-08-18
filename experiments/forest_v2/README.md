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

### Contract of the outputs

| Artifact | Guarantee |
| --- | --- |
| `s01_resolution/s01_index.py` | module symbols, re-export chains, class hierarchy, instance-attribute types. Every result is a `Target` with `status` = `repo` (file+line inside the tree) / `external` (a named module, a claim) / `unknown` (declines to guess). |
| `s01_resolution/s01_resolver.py` | one `Resolution` per `ast.Call`: `verified` (definition file+line), `external`, or `unresolved` **with a named reason**. `Options` carries the ablation switches and the control's module map. |
| `s01_resolution/s01_measure.py` | one JSON object on stdout, schema `forest-v2-s01-resolution/1`. Imports the pre-study probe and asserts a per-site replica of its rules reproduces its totals exactly (`parity_ok`). |
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

**The honest headline is the first row: 21.24 % → 29.16 %, +7.92 pp, +3,567
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

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
