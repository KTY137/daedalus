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

### Measured, this worktree @ `ff5f22dd` [MEASURED]

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
| 200 | 1,562.8 | **43.9%** (was 50%) | 1,829.4 | **37.5%** |
| 800 (default) | 1,943.6 | **35.3%** (was 41%) | 2,210.1 | **31.0%** |
| 4,000 | 2,582.5 | **26.6%** (was 31%) | 2,849.1 | **24.1%** |

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

Real s01 upstream, same 8,466 cards, more edges:

| content budget | total bytes | p50 | p90 | max | truncated | probe seconds |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 200 | 15,487,658 | 1,713 | 2,522 | 4,467 | 6,888 (81.4%) | 25.5 |
| 800 (default) | 18,711,048 | 2,135 | 3,138 | 5,075 | 3,841 (45.4%) | 24.4 |
| 4,000 | 24,120,651 | 2,279 | 5,814 | 8,389 | 768 (9.1%) | 25.5 |

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
| neighborhood edges found / kept | 18,640 / 13,762 | **34,104 / 27,983** |
| neighborhoods truncated by the bound | 345 (4.1%) | 952 (11.2%) |
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

Checks: `python -m pytest experiments/forest_v2/s06_cards/` → **85 passed**
[MEASURED] — 41 from the first version, plus the provenance-ref contract and
its break-even limit, the budget guards, the six negative-path fixtures, one
mutation probe per new guard, and the real-s01 wiring.

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
