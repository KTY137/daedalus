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

## Slice s02 (2026-08-18): the type plane — `s02_types/`

Sibling slice to the call-resolution probes above, same frozen frame, own
sub-directory. Where those measure the **code** plane's resolution gap, this
one builds the **type** plane of master plan section 5 and measures how much
of it is actually recoverable from declarations.

### Frozen specification

- **Hypothesis (falsifiable):** the type plane of this repository can be
  recovered from declarations alone — annotations, signatures, dataclass and
  TypedDict fields, class bases, type aliases — at a rate high enough that
  Gate 2 does not need type *inference* to make the plane useful, and the
  residue that cannot be recovered is small, enumerable, and mostly a real
  defect rather than a limit of the extractor.
- **Falsifier:** if the resolved-signature rate had come out low, or if the
  unresolved residue were dominated by extractor limitations rather than real
  source problems, the type plane would need inference (a far larger Gate-2
  cost) before it could carry any weight, and this slice would say so.
- **Kill-criterion linkage (section 14, "a plane has no marginal
  contribution"):** the ablations below are the beginning of that test for
  the type plane. They are *construction*-side only. They show what the
  extraction machinery buys in coverage; they do **not** show that the type
  plane improves any downstream task. That is Gate 3/4 work and this slice
  claims none of it.
- **Contract of outputs** — schema `forest-v2-type-plane/1`, one JSON object
  on stdout, deterministic, revision-stamped:
  - type nodes `type:<bucket>:<canonical name>`, plane `type`;
  - symbol nodes `sym:<module>.<qualname>` and `...#<param>`, plane `code`.
    These are *anchors* only: the slice does not re-derive the code plane,
    it names the endpoints its edges need.
  - cross-plane edges (code -> type): `param_type`, `return_type`,
    `field_type`, `var_type`, `subtype_of`;
  - intra-plane edges (type -> type): `type_arg`, `alias_of`;
  - edges are unique per `(src, dst, kind)` and carry `count` plus a
    `first_seen` source locator.
  - Every edge here is *declaration evidence*, not a latent proposal. The
    section 6 verifier problem does not arise; what does arise is whether the
    annotation's name can be attributed at all, which is what the buckets
    measure.
- **Scope:** read-only AST analysis of the kernel package. No imports of
  repository code, no writes, no network, no subprocess. `daedalus/` is read
  and never edited, and nothing in `daedalus/` imports this directory.
- **Budget:** one module plus its tests, no model calls, no spend; the whole
  extraction re-runs in single-digit seconds.
- **Expiry:** 2026-09-15. Re-measure before reuse after that date — the tree
  moves, and every number below is revision-bound.

### Measured baseline (2026-08-18) — `[MEASURED]`, raw

`python experiments/forest_v2/s02_types/type_plane.py` over `daedalus/` at
tree state `d849c2a9` (this slice adds only files under `experiments/`, so
the measured package is byte-identical to that base):

| quantity | raw | rate |
| --- | ---: | ---: |
| files parsed | 285 (0 unparseable) | |
| functions / methods / nested | 2588 / 1519 / 96 | |
| **functions with a resolved signature** | **3899 / 4203** | **92.77%** |
| signatures syntactically annotated | 3904 / 4203 | 92.89% |
| resolved, excluding zero-parameter functions | 2796 / 3089 | 90.51% |
| parameters annotated (implicit `self`/`cls` excluded) | 6784 / 7148 | 94.91% |
| returns annotated | 4112 / 4203 | 97.83% |
| dataclass fields resolved | 3294 / 3295 | 99.97% |
| classes / dataclasses / class bases | 765 / 435 / 319 | |
| type aliases (conservative rule) | 10 | |

Controls, same tree, same counting rule:

| resolver | resolved signatures | rate |
| --- | ---: | ---: |
| full (bindings + repo symbol tables) | 3899 | 92.77% |
| **builtins-only control** | **1562** | **37.16%** |
| resolved without needing any repo type | 2811 | 66.88% |
| resolved, requires a repo type | 1088 | 25.89% |

Graph size: 641 type nodes (`repo` 549, `stdlib` 46, `builtin` 19,
`typing` 18, `special` 1, `third_party` 1, `unresolved` 7), 16,485 symbol
anchors, 16,216 unique edges / 26,811 weighted
(`param_type` 6784, `return_type` 4112, `field_type` 3318, `var_type` 1041,
`type_arg` 632, `subtype_of` 319, `alias_of` 10).

Construction cost: 7.0 / 8.0 / 7.2 s wall for three full runs, single
process, cold-ish cache, Python 3.10.11 on Windows. Cheap enough that the
section 14 cost-frontier criterion is not threatened at this repository size;
nothing is claimed about larger trees.

### The unresolved residue, enumerated with locators

The whole residue is 7 distinct names across 4,203 functions and 3,295
fields. Small enough to list, so it is listed rather than summarised:

| name | sites | verdict |
| --- | --- | --- |
| `Mapping` | `daedalus/core.py:488`, `:768`, `daedalus/kairos/gated_writes.py:154` | **true positive** — used as `Mapping[str, Any]`, never imported in either module |
| `Any` | `daedalus/kairos/gated_writes.py:102`, `:125`, `:158` | **true positive** — not bound in the module |
| `GatedCandidate` | `daedalus/kairos/gated_writes.py:146` | **true positive**, and the sharpest one — the name has **no definition anywhere in the tree**, only this annotation and two docstring mentions |
| `ContainmentAttestation` | `daedalus/spine/attempt.py:627` | **true positive** — string forward ref; the class exists in `daedalus/spine/containment.py` but only the *module* is imported here, and the module-qualified form is used everywhere else in the file |
| `LeasedEffectAuthorization`, `EffectExecutionRequest` | `daedalus/offload.py:724`, `:725` | **true positive** — same pattern; both classes exist in `daedalus/kernel/effects.py`, neither name is bound here |
| `original` | `daedalus/budget.py:1135` | **false positive** — `class GuardedPopen(original)` where `original` is a closure variable; the extractor has no local-scope tracking |

Six of seven were confirmed by hand against the sources (grep for the import
and for the definition); one is a known limitation of this extractor and is
recorded as such rather than quietly dropped.

Under `from __future__ import annotations` none of these raise at import
time, which is why they survived. They break `typing.get_type_hints()` and
any runtime schema derivation over those objects. Repairing them is
production work and out of scope here — three of the five files are protected
artifacts. This slice reports; it does not touch them.

### Honest caveats

- **Only `repo` is verified.** `stdlib`, `third_party` and `repo_unverified`
  are name attributions through import bindings, not existence proofs — the
  same caveat continuation 1 carries. `repo_unverified` happened to be empty
  on this tree; that is a property of this tree, not a guarantee.
- **The headline is a coverage rate, not a correctness rate.** "Resolved"
  means every name in the signature was attributable. It says nothing about
  whether the annotation is *true* of the runtime value. The type plane is
  explicitly not a correctness oracle (section 5).
- **Zero-parameter functions inflate the headline.** 1114 of 4203 functions
  take no arguments, and 1103 of them resolve trivially on their return
  annotation alone. The `excl_zero_param` row (90.51%) is the number to quote
  when that matters.
- **The residue is a lower bound.** Names bound by a wildcard import, by a
  closure, or at class scope are invisible to a module-level symbol table, so
  the extractor can both miss real dangling names and invent false ones (it
  did, once).
- **Aliases are detected conservatively** — `TypeVar`/`NewType`/`ParamSpec`
  calls and typing subscripts only. Plain `X = SomeClass` rebinding is not
  counted, so 10 is a floor.
- **`type_arg` edges aggregate.** `dict -> str` accumulates across every
  `dict[str, ...]` in the tree; the edge is a repository-level fact with an
  occurrence count, not a per-occurrence instantiation. Gate 2 needs
  parameterized type identity if it wants the latter.
- **No downstream claim.** Nothing here shows the type plane helps retrieval,
  generation, or evaluation. Section 14's marginal-contribution criterion is
  answered only on the construction side.

### Reproduce

```
python experiments/forest_v2/s02_types/type_plane.py            # summary JSON
python experiments/forest_v2/s02_types/type_plane.py --graph    # + nodes/edges
python -m pytest experiments/forest_v2/s02_types/test_type_plane.py
```

25 tests, all green, each grading the extractor against a throwaway source
tree whose answer was computed by hand.

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
