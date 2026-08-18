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

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
