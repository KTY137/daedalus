# Write-surface closure: what actually clears a blocker

Revision scanned: working tree at `a4a25718` (g0 `main`), 2026-08-22.
Instrument: `daedalus.gates.repository_write_inventory_v2.scan_repository_write_surfaces_v2`,
the exact call `daedalus/gates/report_v3.py` makes. All counts below are
`[MEASURED]` on that scan, not estimated.

## 1. The coverage rule (read this before proposing any closure work)

1. `report_v3._repository_write_inventory` sets `repository_write_failures` to
   `scan_repository_write_surfaces_v2(root).blockers` and to nothing else.
2. `blockers` is `[s for s in surfaces if s.blocking]`, and `blocking` is
   `kind in _ALLOWED_KINDS - {"sqlite_read_only"}` — decided by the **syntactic
   kind of the callsite**, per file, per AST node.
3. The scanner is a per-file AST walk with same-module alias resolution. It has
   no call graph, no anchor reachability, no entrypoint lookup, and no
   declaration table on the v3 path.
4. Therefore **nothing can mark a write surface "covered" today** — not a
   registry door, not a guard contract, not a source annotation. A surface
   leaves the report only when the scanner stops emitting it, i.e. only when the
   call provably cannot write.
5. The classification machinery that *is* designed to clear surfaces
   (`repository_write_classification` → `_effect_lease` → `_evidence_materialization`
   → `_evidence_origin` → `_source_anchor_semantics` → `_guard_structure` →
   `_runtime_conformance`) exists, is tested, and is **not imported by
   `report_v3`**. Every one of those modules says so in its own docstring.

Two consequences that overturn the working assumption of the recon note:

- "37 files have a covering registry door, so 171 of the 418 blockers are
  covered" describes an overlay computed outside the gate. Measured here: 165
  surfaces live in modules that *are* registered entrypoint targets, and all 165
  are still blockers. Door coverage subtracts zero.
- Even under the classification contract, what clears a surface is
  `TargetDisposition` + `GuardDisposition` + evidence bindings. Door
  reachability only decides the `production_reachable` flag. A door row is
  never, by itself, closure.

Pinned by `tests/test_write_surface_coverage.py::test_a_registered_door_does_not_clear_the_write_surfaces_behind_it`
and `::test_blocking_is_decided_by_kind_alone`.

## 2. The three worked kernel files

None of the three is a door. None is a registered entrypoint target, none has
`__main__`, none parses arguments; each is reached through a caller
(`daedalus.storage` → `atomic`; the attempt/promotion spine and the provider
ledgers → `source_trees`; `kernel.promotion` and `spine.attempt` →
`promotion_trust_root`). Registering rows for them would have been a
declaration the code does not justify, and — per section 1 — would not have
removed a single blocker. No registry row was added and no annotation was
painted into these files.

What the surfaces actually are:

| file | before | after | true state |
| --- | ---: | ---: | --- |
| `daedalus/kernel/source_trees.py` | 18 | 17 | 15 genuine CAS writes into the store root (`mkstemp`, `os.link`, `os.replace`, `rmtree`, `mkdir`, `chmod`, `output.open("xb")`) — all real, all caller-supplied paths. 1 false positive removed: `os.open(path, os.O_RDONLY)` at line 261, which the base scanner already proved read-only and the stdlib delta re-flagged. 2 residual: `os.open(target, self._open_flags())` at 333/378, genuinely read-only but the flags come from a helper. |
| `daedalus/kernel/promotion_trust_root.py` | 14 | 13 | 12 genuine: the claim-ledger append (`open(..., "a")` ×2 plus the handle writes), the `O_CREAT\|O_EXCL\|O_WRONLY` marker claim, `mkstemp`/`os.unlink` for the signers file, and `subprocess.run(["git", *pre, *args])` with a dynamic verb. 1 false positive removed: `open(path, "r", encoding="utf-8")` at line 706, again a base-cleared read the delta restated. |
| `daedalus/atomic.py` | 11 | 11 | all 11 genuine. This module *is* the atomic-write primitive: temp sibling, `write_text`/`write_bytes`/`open("xb")`, `os.link`, `os.replace`, `os.unlink`. Nothing here is dead and nothing here is a scanner artefact; the target is whatever the caller passed. |

The `ambiguous_binding` label on `target.parent.mkdir` and `tmp.write_text` is
not a false positive either — the receiver is a local, so the scanner cannot
name it, but the call really does mutate the filesystem. Fail-closed is correct
here; only the *label* is imprecise.

## 3. What changed, and what it measured

Two scanner corrections, both in files this lane owns. Neither weakens a
blocker that a human could not decide from the callsite alone.

**F1 — an unnameable receiver no longer hides a decided mode**
(`daedalus/gates/repository_write_inventory.py`, `_ambiguous_receiver_open`).
`X.open(...)` where `X` is rebound somewhere in the module was emitted as
`ambiguous_binding` regardless of mode. The ambiguity is about the *receiver*,
not the *mode literal*, and the unambiguous branch below already trusts mode
semantics for an arbitrary receiver. A proven read is now dropped; a proven
write now carries its exact mode. A dynamic mode, a duplicated `mode=`, a
non-mode string literal (`shelve.open(path)` creates its database), and the
undotted `open` — where rebinding changes which callable runs — all keep the
blocker.

**F2 — the delta no longer restates a base-owned `open`**
(`daedalus/gates/repository_write_stdlib_delta.py`, `_BASE_OWNED_TERMINALS`).
`open` enters the delta's tracked terminals only through the five
`_MODE_OPENERS`, which are matched by resolved name before any fallback. Every
remaining call whose terminal is `open` — `os.open`, builtin `open`, `io.open`,
`X.open(mode)` — is classified by the base scanner with exact flag/mode
semantics, and the base deliberately leaves the position empty when it proves
the call read-only. The delta was re-adding exactly those cleared positions as
"unresolved". `daedalus/council/vendors.py:419` is the clean witness: three
`open` calls on one line, base kept both `"wb"` writes (cols 45, 75) and the
delta re-flagged only the `"rb"` read (col 17).

Measured on isolated before/after snapshots of `daedalus/`, so concurrent lane
edits cannot contaminate the comparison:

| | surfaces | blockers |
| --- | ---: | ---: |
| before (HEAD scanner) | 433 | 433 |
| after (F1 + F2) | 410 | 410 |

23 removed, **0 added**, 13 relabelled `ambiguous_binding` → `write_mode_open`
with the exact mode. Every one of the 23 was read back from source and is
unambiguously read-only (`open(p,"r")`, `path.open("rb")`, `os.open(p, O_RDONLY)`,
`csv_file.open(newline="", encoding="utf-8")`). Kind deltas:
`ambiguous_binding` 189→167, `ambiguous_stdlib_binding` 51→37,
`write_mode_open` 11→24; all other kinds unchanged.

The 418 in the v3 report at `b52f5f9a` and the 433 here are the same instrument
on different trees; the tree moved between them.

## 4. Projection for the rest

108 files carry the remaining 410 blockers: 36 files (165 surfaces) are
registered entrypoint target modules, 72 files (245 surfaces) are not. Because
door coverage subtracts nothing, the split that matters is *what evidence would
clear the surface*, not *whether a door exists*. Categories over the 245
no-door surfaces:

| cat | count | what it is | what closes it |
| --- | ---: | --- | --- |
| A | 6 | residual scanner gap: `os.open(p, self._open_flags())` where a module-local helper returns only read-only flags | intra-module constant propagation in the scanner, or inlining the flags. **Not done** — see section 5 |
| B | 106 | `.mkdir` / `.write_text` / `.write_bytes` / `.unlink` on a local whose name the scanner cannot resolve; caller-supplied path | `TargetDisposition` per calling door + guard contract. Classification work, not scanner work |
| C | 58 | decided writes: `filesystem_mutation`, `write_mode_open`, `path_mutation`, `os_open_write` | same as B; these are the easiest to classify because the operation is already exact |
| D | 26 | `fh.write` / `json.dump` on a handle whose opener is already counted (28 of the 43 handle sinks repo-wide sit in a file that already carries a counted opener) | a "sink follows its opener" rule would collapse most of these, but it is a fail-open change and needs its own decision |
| E | 33 | `subprocess.run` / `asyncio.create_subprocess_*` with a dynamic command | process guard contract + command binding at the door |
| F | 16 | `sqlite3.connect(dynamic_path)`, one per ledger/store module | target binding of the database path (all 16 are `daedalus/**` ledger stores) |

B + C = 164 of 245 are ordinary classification work: one
`SurfaceClassification` each, with target disposition, guard disposition and
evidence bindings. There is no shortcut that clears them in bulk without
building the missing wire from `repository_write_classification` into
`report_v3`, which is a packet of its own (G0-RWI-20C..20F already scope it).

## 5. Genuine new doors — the mechanical sweep list

14 no-door files carry mechanical entrypoint evidence (`if __name__ ==
"__main__"`, an `argparse` `main`, or a listening socket). These are the real
registry candidates; the next lane can sweep them, one row each, after
confirming the guard contract and anchor per file. **Registering them will not
lower the blocker count** — it closes the *entrypoint registry* gap, which is a
different Gate-0 line item.

| file | surfaces | evidence |
| --- | ---: | --- |
| `daedalus/spine/killswitch.py` | 6 | `__main__` |
| `daedalus/memory/__init__.py` | 5 | `__main__`, argparse `main` |
| `daedalus/health.py` | 4 | `__main__`, argparse `main` |
| `daedalus/memory/projection_worker.py` | 3 | `__main__`, argparse `main` |
| `daedalus/metrics.py` | 3 | `__main__`, argparse `main` |
| `daedalus/progress.py` | 3 | `__main__`, argparse `main` |
| `daedalus/build_exec.py` | 2 | `__main__`, argparse `main` |
| `daedalus/eval/__main__.py` | 2 | `__main__`, argparse `main` |
| `daedalus/kernel/approvals.py` | 2 | `__main__`, argparse `main` |
| `daedalus/spine/picker.py` | 2 | `__main__`, argparse `main` |
| `daedalus/benchmark.py` | 1 | `__main__`, argparse `main` |
| `daedalus/claude_bridge.py` | 1 | `__main__`, argparse `main` |
| `daedalus/spine/bootstrap.py` | 1 | `__main__`, argparse `main` |
| `daedalus/structcore/index.py` | 1 | `HTTPServer` |

`daedalus/spine/killswitch.py` is live in another lane at the time of writing;
coordinate before adding its row.

The other 58 no-door files show no entrypoint evidence at all. They are library
modules in the same position as the three worked here: their writes are
reached through a caller, and they need classification, not a row.

## 6. Residuals deliberately not fixed (negative evidence)

- **6× `ambiguous_os_open_flags` from a helper.** `os.open(p, self._open_flags())`
  in `source_trees.py` (×2), `provider_observation_store.py`,
  `repository_tree.py`, `repository_write_artifact_cas.py`,
  `repository_write_source_anchor_semantics.py`. All are genuinely read-only.
  Fixing them needs interprocedural constant propagation inside a scanner that
  is deliberately syntax-only and fail-closed, for 6 surfaces. Inlining the
  flags at the callsites would duplicate the `hasattr(os, "O_BINARY")` platform
  logic and make the kernel code worse to please a scanner. Left blocking.
- **1× `ast.dump` counted as a stream sink** (`daedalus/eval/correctness.py:1429`).
  `dump` is tracked because of `json.dump`/`pickle.dump`/`marshal.dump`;
  `ast.dump` returns a string. A general "resolved-but-not-a-known-sink is out
  of scope" rule would fix it and would also let a genuine in-repo sink module
  through. Not worth one surface. Left blocking.
- **Base scanner reads argument 0 as the mode for resolved mode-openers.**
  `gzip.open("read.gz", "rb")` is scored by the base against the *path* string;
  a path containing `a`, `w`, `x` or `+` would be labelled `write_mode_open`
  with a nonsense operation. It does not fire anywhere in this tree (measured:
  1 site reaches that branch, with a valid mode literal) and the delta covers
  the five mode-openers correctly, so the composed result is right today. Left
  as-is: tightening it made the base and the delta claim the same position and
  the v2 composition refused the whole scan. That attempt is recorded here
  because the next person will try the same thing.

## 7. Verification

`tests/test_write_surface_coverage.py`, 15 cases, all green. Each fix was
disabled in an isolated tree and the tests went red as follows:

| mutant | red |
| --- | --- |
| both fixes reverted | 6 (both correction groups + all three kernel-file pins) |
| F1 reverted only | 4 (receiver-mode tests, `atomic.py`, `source_trees.py`; `promotion_trust_root.py` stays green — it has no ambiguous `.open`) |
| F2 reverted only | 4 (delta-restatement test, `promotion_trust_root.py`, `source_trees.py`; `atomic.py` stays green — it has no base-owned `open`) |
| `ambiguous_binding` removed from `_BLOCKING_KINDS` | 3 (the door test, the kind test, the undecidable-writer test) |

The four `tests/gates/test_gate_report_v3*.py` pins are untouched and did not
need updating: the wire shape does not move, and the only real-repo assertion
is `assert report.repository_write_failures` (non-empty), with no pinned count.
The two stdlib-delta fixtures that could have collided
(`COMPRESSED_AND_ARCHIVE_SOURCE`, `ALIAS_AND_REBINDING_SOURCE`) were replayed
against both scanners and are byte-identical before and after.

## 8. The chain is wired (2026-08-22, lane HERACLES-CLASSIFY)

Section 1.5 is no longer true: `report_v3` now imports
`repository_write_classification` and the counters come from classified
surfaces. What the wire is, in one line: the reporter asks the chain for a
verdict per surface and publishes only the surfaces the chain leaves as
blockers, but because the chain declares its own evidence unauthenticated,
anything it clears is replaced by an aggregate row that names how many.

**Counters, `[MEASURED]` on isolated snapshots of `daedalus/ + configs/ +
scripts/` (the same method as section 3), before and after the wire:**

| | schema | surfaces_total | failures | verdicts |
| --- | --- | ---: | ---: | --- |
| before | `daedalus-gate-report/4` | *(not declared)* | 410 | *(not declared)* |
| after | `daedalus-gate-report/5` | 410 | 410 | `unclassified:410` |

The failure count is unchanged **on purpose**. No classification declaration
exists at this head, so the chain classifies nothing, every blocking surface is
`unclassified`, and every one stays a blocker. The wire moved the shape, not
the verdict — painting verdicts the chain does not produce is exactly what the
finding warned against. What the report gained is the ability to say *why* a
surface is a blocker, and the three declared counters
(`repository_write_surfaces_total`, `repository_write_surface_verdicts`,
`repository_write_classification_schema`, the last read back out of the
projection rather than asserted), plus the raw syntactic blocker count as the
declared diagnostic `repository_write_syntactic_blockers:410`.

**Verdict vocabulary** — from `surface_classification_verdict` in the chain,
never minted by the reporter: `cleared:central` (leased under a door, the full
four-family evidence set), `cleared:retired` (proven not production-reachable),
`blocked:<candidate_blocker>[+...]` (`primary-checkout-write-target`,
`write-target-unknown`, `production-write-{local_guards,inventory_only,unguarded}`),
`unclassified` (no declaration binds this surface), `non_blocking_kind` (the
scanner emitted it but never marked it blocking; it was never a failure).

**What the chain still cannot classify**, and why the section-4 projection's
categories B (106) and D (26) stay blockers: the chain does not *derive*
anything. `project_repository_write_classifications` is a verifier of declared
`SurfaceClassification` rows bound to the exact revision and inventory digest —
it has no call graph, no target resolution, and no handle-to-opener rule. B
("unnameable receiver, caller-supplied path") needs a `TargetDisposition` per
calling door, which is a human declaration plus a disjointness receipt; D
("handle sink downstream of a counted opener") needs the fail-open "sink
follows its opener" rule that section 6 left undecided. Both remain
`unclassified` and therefore blockers, with their category nameable from the
surface kind in the failure row.

**Fail-closed, deliberately.** A declaration is a locator passed to the builder
(`repository_write_classification_input=`), never a verdict, and it is bound to
the digest of the scan performed in the same call — a stale or foreign document
yields `classification:input-refused` and clears nothing. Whatever it does
clear is replaced by `classification:evidence-unauthenticated:<n>` and
`classification:gate-report-binding-missing`, both taken from the chain's own
payload flags, so `closed` can never be reached by writing a JSON file. Those
rows disappear only when the deeper verifiers (lease → materialization →
origin → anchor semantics → guard structure → runtime conformance) actually run
and the chain stops declaring its evidence unauthenticated.

**Wire shape moved** to `daedalus-gate-report/5` under the one-id-one-shape
rule this module already applied at `/4`; `configs/schemas/gate-report-v5.schema.json`
is added and five pin files move with it (the four
`tests/gates/test_gate_report_v3*.py` plus `tests/test_gate_scanner_report_schema.py`,
which pins the same const and schema path). Every existing anchor in
`scripts/run_gate_report_v3_mutations.py` still resolves exactly once.

**Mutation evidence** — each new guard disabled in an isolated tree, baseline
green:

| mutant | red |
| --- | --- |
| classification ignored (raw syntactic failures again) | 4 |
| unauthenticated-evidence aggregate dropped | 2 |
| refused declaration no longer declared | 3 |
| classification-schema blocker removed | 1 |
| census-consistency blocker removed | 1 |
| door id dropped from the failure row | 1 |

## 9. The first honest declaration (2026-08-22, lane HERACLES-DECLARE)

Section 8 wired the chain and measured `unclassified:410` because no
declaration bound this head. This section is the first declaration, and the
measured answer to "what does a registered CENTRAL door actually let you
declare".

**Artifact.** `runs/gates/write-surface-classification/4fd2daa718c7304984c01fb6685a0d15aeac0d8f/`
— `classification-input.json` (29 rows), `cas/` (29 evidence objects, each file
named by the sha256 of its own bytes), `derivation.json` (the per-door
accounting). Regenerate with `python scripts/declare_write_surfaces.py`.

**Method, and why it is not the working tree.** The declaration binds
`source_revision` **and** `inventory_digest`, so it must be derived from bytes
a later reader can reproduce. It was derived on an isolated `git archive HEAD`
snapshot at `4fd2daa7`, the same isolation method as sections 3 and 8. A scan
of the *working tree* at the same moment refused with `base inventory changed
while composing generation 2` and, when it did complete, produced a different
digest (`4f8199c8…` against HEAD's `35e54672…`) — a concurrent lane was editing
`daedalus/`. A declaration derived from a dirty tree is stale the second it is
written. `[MEASURED]`

**A declaration is a receipt for one commit, and only that commit.** It binds a
40-hex `source_revision`, so it can only be minted *after* the commit it
describes exists, and any later commit touching `daedalus/` refuses it with
`classification:input-refused` — by design (section 8). The artifact here is
the receipt for `4fd2daa7`. This lane's own additive edit to
`daedalus/gates/repository_write_classification.py` is inside the scanned
package, so the commit that lands this section needs its own receipt: run
`python scripts/declare_write_surfaces.py` once on a clean checkout of that
commit. Nothing regenerates it automatically today, and nothing in `report_v3`
looks for it by convention — the caller still has to pass the path. Both are
named here so the next lane does not mistake the receipt for a live input.

### 9.1 What the chain requires before it will say "authenticated"

Nothing, at any revision. This is a structural fact, not a missing receipt:

1. `report_v3._classify_repository_write_surfaces` reads
   `payload.get("evidence_authenticated")` off the classification projection.
2. In `RepositoryWriteClassificationReport._payload` that key is the bare
   literal `False`, and so is its twin in all seven sibling chain modules plus
   `guard_implementation_manifest`. There is **no code path in the tree that
   produces `True`**: the only occurrences of `"evidence_authenticated": True`
   are the *mutation strings* in six `scripts/run_*_mutations.py` runners,
   which flip the literal precisely to prove the suite goes red. `[MEASURED]`
3. Therefore `classification:evidence-unauthenticated:<n>` is unconditional for
   any non-zero cleared count. Producing a receipt cannot lift it.

So the answer to "which receipt kind is missing" is: **none of them is the
blocker.** The blocker is that `evidence_authenticated` is a declared constant
rather than a field derived by composing lease → materialization → origin →
anchor semantics → guard structure → runtime conformance. Making it derived is
a packet of its own, and it has to land *with* the mutation runners that
currently pin the constant, or the guard those runners protect is silently
removed. **This is the measured blocker; this lane stops here.**

Three receipt kinds have no producer either, which is why the declaration does
not claim them:

| evidence kind | producer at this head |
| --- | --- |
| `source_anchor` | **this generator** — payload is `path`, `line`, `column`, `source_sha256`, all measured |
| `guard_contract` | `guard_implementation_manifest` verifies one; nothing mints one |
| `effect_lease_receipt` | none. `daedalus-effect-lease-receipt/1` occurs only inside its own verifier `[MEASURED]` |
| `runtime_conformance_receipt` | `daedalus/kernel/runtime_conformance.py` mints `RuntimeConformanceReceipt` and 3 exist under `runs/gate0-*/conformance/receipts/`, but they attest **adapter runtimes** (start/stream/cost/cancellation/timeout/structured-output/workspace), not repository-write surfaces. `tools/effect_boundary_check.py` is a 46-line static drift check that writes nothing at all |
| `primary_checkout_disjointness_receipt` | none. `disjointness` occurs only in the verifiers that consume it |

### 9.2 Why every row is `unknown` / `inventory_only`, and not `central`

`GuardDisposition.CENTRAL` in the classification contract is not "the door is
centrally wired". `SurfaceClassification.__post_init__` refuses a CENTRAL row
whose target is `primary_checkout` or `unknown`, and demands all four of
`guard_contract`, `effect_lease_receipt`, `runtime_conformance_receipt` and
`primary_checkout_disjointness_receipt`. Two of those four have no producer,
and a disjoint target needs the third. **No surface in this tree can be
declared `central` without fabricating a receipt**, so none is.

`local_guards` was rejected for the same kind of reason: it requires a guard
contract evidenced *per surface*, and the only contract these doors name is
`budget.process_guard`, which interposes `subprocess.run`, `subprocess.Popen`
and `urllib.request.urlopen` against the spend ceiling. It is a spend net.
`daedalus/spine/effect_boundary.py` already says so in its own words — "there
is no filesystem-write contract in `GUARD_CONTRACT_IMPLEMENTED` to make a
stronger claim with" — so claiming it certifies a filesystem write would
contradict the registry. Every row is therefore `target=unknown,
guard=inventory_only, production_reachable=true`, carrying one real
`source_anchor` evidence object.

The vocabulary has no rung for *"centrally started, but no contract covers this
effect"*. That gap is worth an amendment proposal; it is not worth an
overclaim, and `inventory_only` is the registry's own word for a Gate-0 gap.

### 9.3 Dominance: what a door can actually vouch for

A surface is declared only when its exact `(line, column)` AST node descends
from a statement the anchor provably dominates. Two levels, both sound modulo
dynamic dispatch:

- **L1** — inside the anchor function, after the statement holding the
  `begin_effect` call (or inside the body of a `with begin_effect(...)`).
- **L2** — inside a module-private `_helper` that (a) is named nowhere else in
  the repository's Python sources, (b) is absent from `__all__`, and (c) is
  referenced inside its own module only from already-dominated code. Iterated
  to a fixpoint. 8 helpers were admitted across 6 doors.

**Counts `[MEASURED]` at `4fd2daa7`:** 97 registry rows, 78 CENTRAL, 51 CENTRAL
anchors resolving to a `begin_effect` start inside `daedalus/`; 27 skipped (25
anchored outside the scanned package — all `tools.*`, `runs.*` — and 2 on
`daedalus/spine/attempt.py`, held by another lane). Of the 51, **18 doors
declare 29 surfaces**; 33 declare nothing.

The ten Phase-4 doors registered at `4fd2daa7` yield **6 of the 29**:

| door | module | blocking surfaces in module | declared |
| --- | --- | ---: | ---: |
| cli.eval | `daedalus/eval/__main__.py` | 2 | 2 |
| cli.project_memory | `daedalus/memory/projection_worker.py` | 3 | 1 |
| cli.picker | `daedalus/spine/picker.py` | 2 | 1 |
| cli.benchmark | `daedalus/benchmark.py` | 1 | 1 |
| cli.build_exec | `daedalus/build_exec.py` | 2 | 1 |
| cli.killswitch | `daedalus/spine/killswitch.py` | 6 | 0 |
| cli.health | `daedalus/health.py` | 4 | 0 |
| cli.progress | `daedalus/progress.py` | 3 | 0 |
| cli.approvals | `daedalus/kernel/approvals.py` | 2 | 0 |
| cli.bootstrap | `daedalus/spine/bootstrap.py` | 1 | 0 |

**Why the five zeroes are the real finding.** The anchor dominates each door's
argument parsing and dispatch; the *effects* live somewhere no anchor reaches:

- `progress.py` — all 3 writes sit in an `append` **method**. Any holder of the
  object can call it.
- `approvals.py` — both in `__init__` and `_connect`, methods again.
- `health.py` — `_git`, `_ssh_powershell`, `_p_vectors`, `_p_room`: private,
  but each is called from many probe functions, not only from post-anchor code.
  The row's own note already predicted this ("main()'s own AST holds no sink,
  because every probe reaches its effect through a helper").
- `killswitch.py` — `_cross_process_visible` and `_verify_control_root_uncached`
  sit behind `control_check`/`verify_control_root`, which are library API; the
  two `os.unlink` calls are in `arm()` and `clear()`, importable functions.
- `bootstrap.py` — the one `subprocess.run` is in a shared `_run` helper.

This is section 1's rule measured from the other side: a door does not clear
what is behind it, because most of what is behind it **is not only behind it**.
Across the 51 door modules, 142 blocking surfaces are reachable by a path no
anchor dominates. Closing those needs the effect moved behind the door, or a
per-surface target/guard declaration a human signs — not another registry row.

### 9.4 Reporter before/after

`build_gate0_report_v3` on the isolated `4fd2daa7` snapshot, the only variable
being `repository_write_classification_input`:

| | schema | surfaces_total | failures | verdicts |
| --- | --- | ---: | ---: | --- |
| before (no declaration) | `daedalus-gate0-repository-write-classification/1` | 410 | 410 | `unclassified:410` |
| after (29-row declaration) | same | 410 | 410 | `unclassified:381`, `blocked:write-target-unknown+production-write-inventory_only:29` |

`unclassified` falls by **exactly 29**, the declared count. **Failures do not
move, and no `classification:` row appears** — because an honest declaration
clears nothing, the unauthenticated aggregate of section 8 never fires. The
declaration bought names, not absolution: 29 surfaces now say *why* they are
blockers instead of saying nobody looked. `[MEASURED]`

All 29 minted evidence objects were replayed through
`materialize_repository_write_evidence`: 29 records, 0 missing locators, every
`cas/<sha>.json` hashing to its own filename. The generator refuses to write
anything if that self-check fails.

### 9.5 Verification

`tests/test_declare_write_surfaces.py`, 15 cases (written this lane, not run
here — this lane was barred from invoking pytest). Three guards were disabled
in-process against the fixture module and the dominance set re-measured:

| mutant | effect `[MEASURED]` |
| --- | --- |
| cross-module name check defeated (another module names `_after_helper`) | the helper's write leaves the declared set — pins `test_a_private_helper_named_by_another_module_is_not_dominated` |
| `_anchor_regions` returns the whole anchor body | the write **before** `begin_effect` enters the declared set — pins `test_the_write_before_begin_effect_is_not_dominated` |
| `_references_are_dominated` forced `True` | `_shared_helper`, also called from `public_helper`, enters the declared set — pins `test_a_private_helper_reachable_from_undominated_code_is_not_dominated` |

Two independent generator runs over the same tree produced byte-identical
`classification-input.json`, `derivation.json` and CAS object sets, so the
artifact is reproducible rather than merely repeatable. `[MEASURED]`

All nine mutation anchors in `scripts/run_repository_write_classification_mutations.py`
still resolve exactly once against the edited module. The one change there is
additive: `CLASSIFICATION_INPUT_SCHEMA`, exported for producers and
deliberately *not* substituted into the verifier's own literal, so the two
spellings keep catching drift in each other.

All 51 anchors in this tree are the plain-statement shape, so the
`with begin_effect(...)` branch of the dominance rule fires nowhere at
`4fd2daa7`. It is therefore pinned by its own fixture
(`test_a_with_begin_effect_body_is_dominated`) rather than by a real door: an
unexercised branch in a soundness rule is the one place a fixture earns its
keep. `[MEASURED]`: the with-body write is dominated, the write above the
`with` is not.

## 10. The reporter can be handed a declaration, and the counters answer (2026-08-24)

Section 9 measured that no receipt kind was the blocker; today measured the
two structural reasons the census could not move even after a leased attempt
left real terminal evidence (eae9f72e door; full mechanics with line numbers
in `docs/inventory/2026-08-24/LEASED_RUN_CENSUS_DELTA.md`): the reporter
called the composition without `inputs=` behind an over-broad AST pin, and
`scripts/report_gate0_v3.py` had no flag reaching
`repository_write_classification_input` at all.

Cut D (Momus, endorsed over variants A/B/C; Codex holds variant C -- a
separate authenticator with its own content-addressed receipt -- as the later
shape, PRECONDITION: a verification-only key, since the HMAC's verifier must
currently hold the signing secret) landed as d651fbb7 (pin narrowed to the
actual 6be14dff rule), aa05c7ea (the CLI flag), 725e32a1 (an authentication
refusal is retained beside the declaration as `authentication-owed.json`).

**Measured at 725e32a1, numbers named before the build:**

| measurement | predicted | observed |
| --- | --- | --- |
| `repository_write_surfaces_total` | unchanged | 437 (this head's count) |
| verdicts with the fresh declaration (32 rows, 12-hex address `725e32a15752`) | `unclassified:total-N`, `blocked:...:N` | `unclassified:405`, `blocked:write-target-unknown+production-write-inventory_only:32` |
| `cleared` / `evidence-unauthenticated` / `binding-missing` rows | 0 / absent / absent | 0 / absent / absent |
| `report_sha256` | changes | changed (`6f589406...`) |
| control: stale `4fd2daa7` declaration at this head | `classification:input-refused` | `input-refused`, verdicts stay `unclassified:437` |

The remaining wall is unchanged and now isolated: `cleared` stays 0 because
every honest row carries `candidate_blockers` -- the classification
vocabulary has NO RUNG for "centrally started, but no contract covers this
effect" (section 9.2). That is an AMENDMENT question for the owner, drafted
in `docs/decisions-pending/AMENDMENT_DRAFT_classification_rung.md`, not a
wiring commit. Authentication work (variant C) waits behind the asymmetric
attestation precondition and behind that amendment.
