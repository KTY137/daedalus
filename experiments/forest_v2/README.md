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
  orders, (b) moves when any digested field moves, and (c) cannot be produced
  at all from an incomplete or revision-inconsistent plane set. If any of the
  three fails, master plan invariant 6 ("partial graph states do not
  masquerade as a revision") has no cheap mechanical enforcement and Gate 2
  needs a heavier design than a digest.
- **Scope:** read-only stdlib AST/text/CSV/JSON analysis of the repository
  tree, no repository imports, no writes outside pytest's `tmp_path`, no
  network, no subprocess. Nothing under `daedalus/` may import this slice
  (checked: `grep -rn forest_v2 --include=*.py` over the package is empty).
- **Budget:** one work session, four modules, whole probe re-runnable in
  ~6 s wall time. No model calls, no spend.
- **Expiry:** 2026-09-15. After that, re-measure before reuse — the numbers
  below are properties of *this* tree, not constants.
- **Kill criterion linkage:** if maintaining a revision-atomic snapshot costs
  more than the value it carries, master plan §13 ("revision-atomic snapshots
  cannot be maintained at usable cost") fires. The cost side of that trade is
  the wall time and byte size reported below; the ceiling is not tested here.

### The common contract: `forest-v2-plane-extraction/1`

One plane extraction is one JSON object. s01–s04 produce it; s05 consumes it.
Exactly these keys, all required, **unknown keys are refused**:

```json
{
  "schema":   "forest-v2-plane-extraction/1",
  "plane":    "code" | "type" | "data" | "knowledge",
  "revision": "<source revision id, identical across all four planes>",
  "producer": "<who extracted this — provenance, NOT digested>",
  "nodes":    [ {"id": "...", "kind": "...",
                 "locator": {"path": "rel/posix/path", "start_line": 0, "end_line": 0},
                 "attrs":   { }} ],
  "edges":    [ {"src": "<node id>", "dst": "<node id>", "kind": "...", "attrs": {}} ]
}
```

Rules a producer must satisfy: node ids unique within the plane; locators
relative, posix, never absolute, never escaping the root; `end_line >=
start_line`; `attrs` JSON-serializable with string keys; **edges intra-plane
only** — an extractor asserting a cross-plane relation is refused with its own
code, because §6 gives cross-plane edges to a verifier, not to an extractor.

`producer` is deliberately outside the digest. That is what lets s01–s04
replace the placeholder extractors in `reference_planes.py` without moving a
digest, as long as the extraction itself is identical.

### Outputs

`snapshot.build_snapshot(docs)` → `forest-v2-snapshot/1` manifest:
`revision`, `snapshot_digest`, per-plane `{digest, producer, nodes, edges}`,
`node_total`, `edge_total`. No timestamp, no absolute path, no host state —
those are exactly what would break replay.

Digest algebra (domain-separated, sorted, so order cannot leak in):

```
node_digest     = sha256(canonical(node))            # canonical = JSON, sorted keys,
edge_digest     = sha256(canonical(edge))            # no spaces, UTF-8, no \u escapes
plane_digest    = sha256("forest-v2-plane/1" | plane | revision
                         | sorted(node_digests) | sorted(edge_digests))
snapshot_digest = sha256("forest-v2-snapshot/1" | contract | revision
                         | "<plane>=<plane_digest>" for code, type, data, knowledge)
```

### Measured, this worktree, `python probe_replay_identity.py` [MEASURED]

Placeholder extractors over `daedalus/` (code, type), `configs/ catalogue/
examples/` (data), `docs/` (knowledge):

| quantity | code | type | data | knowledge | total |
| --- | ---: | ---: | ---: | ---: | ---: |
| nodes | 3637 | 3399 | 382 | 2705 | **10,123** |
| edges | 3352 | 8005 | 337 | 2347 | **14,041** |
| canonical bytes | 1,273,600 | 2,014,422 | 159,125 | 1,279,229 | **4,726,376** |

| replay property | raw result |
| --- | --- |
| build twice in one process @ `d849c2a9` | `sha256:fa01e21b…d91ab0` = `sha256:fa01e21b…d91ab0` — **identical**, manifests byte-equal |
| build wall time | 5.822 s / 5.069 s (second build, warm) |
| three separate processes, `PYTHONHASHSEED` 1 / 2 / 424242 | `fa01e21b…` / `fa01e21b…` / `fa01e21b…` — **identical** |
| root spelled `<root>/daedalus/..` instead of `<root>` | identical |
| node and edge order shuffled (seed 20260818) | identical |
| documents round-tripped through the canonical form | identical |
| single-field sensitivity matrix | **10 of 10 as expected** (9 content fields move the digest, `producer` does not) |
| refusal matrix | **10 of 10 refused with the exact expected code** |

Revision binding, measured across three real commits of this branch with the
scanned roots untouched in between [MEASURED]:

| HEAD | git-bound `snapshot_digest` | with revision label held fixed |
| --- | --- | --- |
| `d849c2a9` | `sha256:fa01e21b…d91ab0` | — |
| `2c78bdb7` | `sha256:0ee74bbd…09f241` | `sha256:0b274bfc…30f99eb` |
| `f416ce52` | `sha256:44856f83…c5b58` | `sha256:0b274bfc…30f99eb` |

Three commits, three digests — the snapshot really is bound to the revision and
not merely to the bytes. Hold the revision label fixed and the digest stops
moving, which shows the movement comes from the revision binding, not from
nondeterminism.

Checks: `python -m pytest experiments/forest_v2/s05_snapshot/test_snapshot.py`
→ **40 passed in 1.93 s** [MEASURED].

### Honest caveats and open ends

1. **The extractors are placeholders, not evidence.** Top-level definitions
   only, syntactic annotation text with no inference, file-level data
   locators with no field spans, headings with no concept resolution. Every
   count above is a property of the cheapest possible producer. When s01–s04
   land, the counts change and only the *properties* carry over.
2. **The revision is HEAD, not the working tree.** `read_git_revision` reads
   git's files; it does not check whether the tree is dirty. A modified
   working tree is therefore silently labelled with a clean commit id. That is
   a real hole for Gate 2 — a production builder must either digest the tree
   state or refuse on a dirty tree. Measured builds above are honest only
   because the uncommitted files lived outside the scanned roots.
3. **`attrs` is free-form, so determinism there is producer-enforced.** The
   builder rejects unknown *contract* keys, which stops a wall clock at the
   node level, but a producer that writes `attrs: {"built_at": …}` is only
   caught by the double-build check, never by the schema.
4. **Digest ≠ storage.** Nothing here stores content-addressed blobs; it
   addresses the extraction, not the sources. §5's content-addressed source
   trees remain unbuilt.
5. **Cost ceiling untested.** 6 s and 4.7 MB canonical form for ~10k nodes is
   the frontier point measured, not a scaling claim. The §13 kill criterion
   about snapshot cost needs a curve, not one point.
6. **Cross-plane edges are refused, not verified.** That is deliberate (§6),
   but it means a real Twin still needs the verifier this slice does not build.

## Boundary note

This directory currently contains no effectful entrypoint (the probe's
`main` only prints, which the effect scanner correctly treats as read-only).
Anyone adding an effectful entrypoint under `experiments/` must either
register it in the canonical effect registry or extend `HARNESS_PACKAGES` —
an unscanned effectful directory is the exact blind spot the boundary work
just closed.
