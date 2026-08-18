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
