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
  object, schema `forest-v2-knowledge-crosslink-probe/1`, with `totals`
  (raw counts per bucket), `rates` (derived percentages, each carrying its own
  denominator), and `dead_examples` (≤ 12 located specimens per bucket, so
  every claim is spot-checkable). Read-only: a test asserts corpus mtimes are
  unchanged after a run.
- **Counting rules, chosen so no weak claim is laundered into a strong one:**
  external URLs are unverifiable offline and therefore *leave the denominator*
  instead of counting as resolved; a code reference resolves only if the path
  exists **and** the cited line is within the file's real length; bare
  basenames resolve only on a unique match; package-relative paths get a
  separate suffix bucket; ambiguous matches are never silently resolved.

### Measured, this worktree @ 3c7f9352 (2026-08-18) [MEASURED]

`python experiments/forest_v2/s04_knowledge/probe_knowledge_crosslinks.py`
over 421 markdown files (0 unreadable, 2936 headings):

| class | checkable | resolved | rate |
| --- | ---: | ---: | ---: |
| links (path + anchor) | 59 | 58 | **98.3%** |
| code refs `file:line` | 313 | 289 strict / 305 incl. suffix | **92.3% / 97.4%** |
| wiki links (prose notes) | 33 | 28 | **84.8%** |
| wiki links `[[code:PATH]]` | 8 | 8 | **100%** |
| **all edges** | **413** | **399** | **96.6%** |

Raw buckets: `link_external` 136 (excluded from the ratio), `link_path_dead` 1,
`link_anchor_dead` 0, `code_ref_suffix_resolved` 16, `code_ref_ambiguous` 2,
`code_ref_dead_path` 6, `code_ref_line_out_of_range` 2, `wiki_dead` 5.
Fence filter masked 1918 lines and removed **0** link-shaped refs — this corpus
genuinely does not put links in fenced blocks (verified independently).

### What the residue actually is

The headline is a negative result for the hypothesis as stated: at 96.6% the
crosslinks are **not** substantially decayed, so "the prose is rotten" is
refuted for this corpus. The 14 dead edges are more interesting than the rate:

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
  inference, not a resolved import) and is reported separately for that reason.
- 59 checkable links is a small denominator: 136 of 195 links are external, so
  the 98.3% link rate carries wide uncertainty and should not be quoted alone.
- Wiki-link resolution matches note stems and heading titles only; an Obsidian
  vault with aliases would resolve more. No vault was present in this worktree.

### Observer effect (measured, not hypothesised)

The table above is pinned to `3c7f9352`, the commit **before** this section
existed. Writing the findings down changed the thing measured: quoting the
decayed specimens added them to the corpus as real refs. Re-running against
the tree that contains this README gives [MEASURED] 318 code refs (+3),
`code_ref_line_out_of_range` 4 (+2), all-edge resolution **95.9%** (from
96.6%). The three additions are `gated_writes.py:774` and
`kairos/gated_writes.py:987` (the cited specimens, now genuinely present and
genuinely decayed) and `path.py:12` from the caveat sentence above.

This is not a defect to filter away — it is a property Gate 2 inherits: the
Knowledge plane documents the system that measures it, so knowledge metrics
are reflexive. Either the corpus revision is pinned (done here) or citations
must be marked as specimens and excluded by an explicit, declared rule. A
crosslinker that silently self-excludes its own documentation would be
reporting a number nobody can reproduce.

### Consequence for Gate 2

Resolution rate is the wrong headline metric — it is already high and will stay
high. The measurable that earns its keep is **anchor precision under edit**:
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
