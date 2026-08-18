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
  - `forest-v2-node-card/1` — the *card*: `schema, card_id, node_id, revision,
    plane, locator{path,start_line,end_line,source_sha256},
    content{kind,name,qualname,signature,doc,text,text_sha256,text_chars,truncated},
    neighborhood{edges[],edge_total,truncated,budget}, provenance{}`.
    `validate_card()` is the machine-checkable definition; a card that fails it
    is not a card.
  - `forest-v2-node-card-probe/1` — the measurement report.
- **Two identities, deliberately:** `node_id` = `plane://path#kind:qualname`
  (+`~ordinal`) carries **no line numbers**, so it survives a shift or a
  reformat; `card_id` = sha256 over the entire card body, so it cannot survive
  one. §6 wants a handle stable enough to compare across revisions, §5 wants a
  revision-atomic content address. One field cannot be both.
- **Budget:** ≤ 3 h, four modules + two check files, whole-repo run in seconds,
  no model calls, no spend.
- **Expiry: 2026-09-15.** After that, re-measure before reuse (the tree moves)
  or retire the section.
- **Kill-criterion linkage (§14):** if cards must grow past the point where
  card construction and storage worsen the quality/cost frontier, or if the
  neighborhood bound has to be lifted so far that "local" stops meaning local,
  the latent-atlas prior loses its cheapest justification.

### Measured, this worktree @ `d849c2a9` [MEASURED]

`python experiments/forest_v2/s06_cards/probe_node_cards.py`, default budgets
(content 800 chars, neighborhood 8 edges), scanning the same three code
packages as the earlier probes plus the markdown tree. `experiments/` is
deliberately **not** scanned: the slice does not measure itself.

| quantity | value |
| --- | ---: |
| cards built | **8,466** |
| contract violations | **0** |
| records rejected | 0 |
| distinct `node_id` / duplicates | 8,466 / **0** |
| code plane | 5,739 (module 318, class 801, function 2,992, method 1,628) |
| knowledge plane | 2,727 (document 358, section 2,369) |
| neighborhood edges found / kept | 18,640 / 13,762 (**26.2% dropped by the bound**) |
| cards whose neighborhood was truncated | 345 (4.1%) |
| cards with no edge at all | 3 |
| content truncated at 800 chars | 3,841 (45.4%) |

Size distribution, canonical JSON bytes [MEASURED]:

| bytes | all planes | code | knowledge |
| --- | ---: | ---: | ---: |
| min | 994 | 994 | 1,281 |
| p50 | 2,105 | 2,017 | 2,318 |
| p90 | 2,760 | 2,624 | 2,851 |
| p99 | 4,096 | 3,778 | 4,390 |
| max | 5,256 | 4,834 | 5,256 |
| mean | 2,124.6 | 2,017.1 | 2,350.7 |
| total | 17,986,544 | 11,576,281 | 6,410,263 |

Content-budget sweep, same 8,466 cards [MEASURED]:

| content budget (chars) | total bytes | p50 | p90 | max | truncated | probe seconds |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 200 | 14,763,154 | 1,606 | 2,184 | 4,648 | 6,888 (81.4%) | 7.8 |
| 800 (default) | 17,986,544 | 2,105 | 2,760 | 5,256 | 3,841 (45.4%) | 9.6 |
| 4,000 | 23,387,681 | 2,228 | 5,424 | 8,478 | 768 (9.1%) | 14.4 |

**The one number worth arguing about: `envelope_bytes` = 867 [MEASURED].**
That is a card carrying identity, revision, plane, locator, provenance and an
*empty* content and neighborhood — the price §6 charges before a single
character of payload. It is 50% of the mean card at a 200-char budget, 41% at
800, 31% at 4,000, and it explains why `bytes_min` stays at 994 no matter how
the content budget moves. Raising the budget 5× (800→4,000) moves the median
card by 5.8% but the p90 by 96%: half the nodes in this tree are smaller than
800 chars anyway, and the whole cost lives in a tail of large modules and long
documents. A per-plane or per-kind budget would beat one global constant, but
that is a Gate-2 decision and this slice does not pre-empt it.

### Honest caveats

- **s01 had produced nothing at this base.** Its worktree still sat on
  `d849c2a9`, so the numbers above come from `standin_source.py`, a stand-in
  extractor written for this slice, not from s01's output. `s01_adapter.py`
  is the declared join: it maps an upstream JSONL stream through an alias table
  and raises `AdapterError` with the offending line and the missing field
  rather than inventing a value. Nothing here is evidence about s01's card
  count — only about the contract's cost and determinism.
- The size numbers are canonical JSON bytes, not tokens. An embedder's cost is
  the `content` block, not the envelope; a store's cost is both. Do not quote
  the envelope share as an embedding overhead.
- `derives_from` and `imports` edges carry unresolved name targets
  (`code://symbol:Base`); resolving them is the s01/Gate-2 resolver's job, and
  the pre-study above already measured how much of that is reachable.
- The knowledge plane here is heading-structure only. Wiki links are captured
  as unresolved link names; no crosslink is verified, and §6 is explicit that
  an unverified similarity stays a proposal.
- Two planes are covered, two (type, data) are not. This is not a four-plane
  demonstration and must not be cited as one.

### Boundary

The slice imports nothing from `daedalus/`, nothing in `daedalus/` imports it,
and it contains no effectful entrypoint — `main()` only prints. Cards are
proposal carriers: they never become evidence and they promote nothing.

Checks: `python -m pytest experiments/forest_v2/s06_cards/test_node_cards.py
experiments/forest_v2/s06_cards/test_probe_node_cards.py` → 41 passed
[MEASURED].

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
