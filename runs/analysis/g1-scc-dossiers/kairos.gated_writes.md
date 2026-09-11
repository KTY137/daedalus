# kairos.gated_writes — SCC dossier

Module: `daedalus/kairos/gated_writes.py` (326 lines; [MEASURED] via Read, full file), plus a second
file it `exec()`s into its own namespace at import time: `daedalus/kairos/_gated_writes_legacy.py.src`
(1345 lines; [MEASURED] via Read, full file — see "Correction" below, this changes the edge count).
Base: main @ 851ff43c (task brief); tree actually read at `wip/g1-freeze-2026-08-31` /
`main @ 54f0975398` working copy (`git rev-parse HEAD` and the SubagentStart hook both report
`54f09753`, not `851ff43c`) — noted, not resolved; no edits made either way. [MEASURED discrepancy]

## Measured edges (raw AST probe)

Command: `.venv/Scripts/python.exe C:/Users/Administrator/scc-scratch/probe.py kairos.gated_writes` [MEASURED]

```
### OUTGOING edges FROM kairos.gated_writes to other SCC members
  -> kernel.promotion           MODULE-LEVEL               in <module>
       daedalus/kairos/gated_writes.py:56   from daedalus.kernel.promotion import (
  -> kernel.promotion           FUNCTION-LOCAL (deferred)  in promote_candidates
       daedalus/kairos/gated_writes.py:231   from daedalus.kernel.promotion import (
  -> spine.picker               FUNCTION-LOCAL (deferred)  in promote_candidates
       daedalus/kairos/gated_writes.py:259   from daedalus.spine.picker import resolve_spine_db_path
  -> kernel.promotion           FUNCTION-LOCAL (deferred)  in promote_candidates
       daedalus/kairos/gated_writes.py:276   from daedalus.kernel.promotion import (

### INCOMING edges INTO kairos.gated_writes from other SCC members
  <- build_exec                 FUNCTION-LOCAL (deferred)  in WaveExecutor.run_wave
       daedalus/build_exec.py:1099   from .kairos.gated_writes import run_write_wave
  <- kairos.scheduler            FUNCTION-LOCAL (deferred)  in KairosScheduler.gate_concurrent_writes
       daedalus/kairos/scheduler.py:436   from .gated_writes import gate_candidates
```

### Verification of the probe, and the note about `kernel.promotion`'s "two import statements"

The task brief describes the `kernel.promotion` edge as reported "BOTH module-level AND function-local
(two separate import statements)". Reading the raw output above precisely: it is **one module-level
statement (line 56) plus two separate function-local statements (lines 231 and 276)** — three import
statements total, not two. Both function-local sites are inside the same function, `promote_candidates`
(gated_writes.py:144–322), at two different points separated by a cross-process lock acquisition:

- **Line 231–234** (before the lock, inside a `try:` at the top of `promote_candidates`): `from
  daedalus.kernel.promotion import (PREAUTHORIZATION_STAGE, authorize_persisted_promotion)`. Used two lines
  later, `authorize_persisted_promotion(... promotion_stage=PREAUTHORIZATION_STAGE)` (line 236–252). This is
  the pre-lock, effect-free authorization pass, explicitly documented as happening "before any process,
  lock or worktree effect."
- **Line 276–280** (inside `with _PromotionLock(lock_path, ...)`, after the lock is held): `from
  daedalus.kernel.promotion import (SEALED_STAGE, authorize_persisted_promotion,
  resolve_live_target_revision)` — a **redundant re-import of `authorize_persisted_promotion`**, plus two
  names not imported at the first site. Used at lines 286–297: `authorize_promotion =
  authorize_persisted_promotion` (local rebind), `live_target_revision =
  resolve_live_target_revision(root, target_ref)`, then `authorize_promotion(...
  promotion_stage=SEALED_STAGE, live_target_revision=live_target_revision)`. This is the **second,
  re-authenticated pass with a freshly read live target**, per the function's own docstring: "The same
  capability is re-authenticated while the cross-process promotion lock is held against the freshly read
  live target HEAD immediately before the retained integration-worktree implementation is entered."

**Why import the same symbol (`authorize_persisted_promotion`) twice instead of once at the top of the
function?** Not a style accident: the two `try`/`with` blocks read as two structurally distinct
authorization *stages* (`PREAUTHORIZATION_STAGE` vs `SEALED_STAGE`, both literal constants from
`kernel.promotion`), and keeping each stage's import next to its own call keeps the "authenticate again
under the lock, against fresh state" invariant visually local and diff-reviewable — a caller cannot
accidentally reuse the pre-lock `live_target_revision=None` binding for the sealed call, because the sealed
call's imports and its own `resolve_live_target_revision(...)` call are co-located. It could be hoisted to
one function-top import of all 4 names with no behavioural change (all 4 are already deferred/function
scope either way), so this is a stylistic-cohesion choice, not a technical requirement. [MEASURED by
reading both sites in full]

**Module-level import (line 56)** — `PromotionAuthorizationError`, `snapshot_promotion_candidates as
_snapshot_promotion_candidates`. `PromotionAuthorizationError` is used at 7+ sites, several **outside**
`promote_candidates` (`_retired_legacy_promotion` at line 71, `_legacy_unpersisted_refusal` at line 137) —
so it genuinely needs module scope, this is not annotation-only, and `from __future__ import annotations`
(line 9) is irrelevant since these are runtime `raise`/`except`/call usages, not annotations. `
_snapshot_promotion_candidates` is used once, inside `promote_candidates` (line 216). [MEASURED]

### Correction: the probe undercounts this module's real outgoing edges by 7

`gated_writes.py` does **not** itself define `gate_candidates`, `GatedCandidate`, `GitWorktreeManager`,
`_PromotionLock`, `_promote_locked`, `run_write_wave`, etc. — every one of those names, used or re-exported
by `gated_writes.py`, comes from `daedalus/kairos/_gated_writes_legacy.py.src`, a **package resource file**
(non-`.py` extension) that `gated_writes.py` reads with `importlib.resources.files(...)`, verifies against
a pinned Git blob SHA-1, and `exec()`s directly into its own `globals()` (lines 42–47). The AST probe walks
the 18 declared `.py` files; it does **not** parse a `.src` resource that is never imported as a module in
its own right, so **every import statement inside that exec'd file is invisible to the probe**, even though
those statements execute as part of importing `daedalus.kairos.gated_writes` and their functions run in
`gated_writes`'s own namespace (confirmed: they are attributes of the module after import, e.g.
`daedalus.kairos.gated_writes.gate_candidates`, `.run_write_wave`, matching the docstring's claim that "all
non-promotion symbols retain the canonical `daedalus.kairos.gated_writes` module identity"). [MEASURED, by
reading both files and grepping the legacy source for `^import \|^from `]

Grepping `_gated_writes_legacy.py.src` for `^import \|^from ` (60 hits, including nested/indented ones)
and mapping each to its enclosing function (via `grep -n "^def \|^class "` and reading the surrounding
code) finds these **additional, reachable, real** edges to SCC members that the reported probe output
misses entirely:

| Line | Import | Enclosing function | Reachable from a real caller? |
|---|---|---|---|
| 215 | `from daedalus.spine.attempt import GateResult` | `_relay_gate` (closure factory, 185–224) | Yes — `_relay_gate`/`_recording_runner` are the gate/runner pair `gate_candidates` wires per-attempt |
| 236 | `from daedalus.spine.attempt import offload_runner` | `_recording_runner` (227–246) | Yes, same as above |
| 308 | `from daedalus.spine.attempt import TaskSpec` | `_spec_for` (285–336) | Yes — called to build the `TaskSpec` handed into `run_attempt` inside `_attempt_assignment` |
| 462 | `from daedalus.spine.picker import resolve_spine_db_path` | `gate_candidates` (428–514) | **Yes** — `gate_candidates` is directly called from `kairos.scheduler.py:436`, a probe-confirmed live edge; this is a **second, probe-invisible** `gated_writes -> spine.picker` call site distinct from the one at `gated_writes.py:259` |
| 836 | `from daedalus.spine.attempt import RunnerContext, TaskSpec` | `_promote_one_inner` (774–883) | Yes — called via `_promote_one` (884–900, a thin try/except wrapper) ← `_promote_locked` (1012–1079, called from the **sealed** `promote_candidates` at `gated_writes.py:305`) |
| 941 | `from daedalus.kernel.promotion import (authorize_promotion, resolve_live_target_revision)` | legacy `promote_candidates` (901–1010) | **No — genuinely dead.** See below. |
| 989 | `from daedalus.spine.picker import resolve_spine_db_path` | legacy `promote_candidates` (901–1010) | **No — genuinely dead**, same reason |
| 1137 | `from daedalus.core import get_governance` | `_governance_verdict` (1109–1159) | Yes — called from `run_write_wave` (line 1269–1270), the function `build_exec.py:1099` imports and calls |
| 1215 | `from .scheduler import DEFAULT_AVAILABILITY` | `run_write_wave` (1160–end) | Yes — `run_write_wave` is the confirmed live production entrypoint |

**Why lines 941/989 are dead, not just unreachable-looking:** `gated_writes.py` line 44–47 `exec()`s the
whole legacy source into its own `globals()`, which defines a `promote_candidates` function at legacy
lines 901–1010 (a plain top-level `def`, no decorator, no assignment to any other name — grepped
`promote_candidates` across the whole legacy file: the only non-comment/docstring hits are the `def` line
itself and two message-string references inside `run_write_wave`, neither of which *calls* it). Immediately
after the `exec()`, `gated_writes.py:54` does `del promote_candidates`, removing that binding from the
shared `globals()` dict before anything else in `gated_writes.py` runs. No other retained function in the
legacy source calls `promote_candidates(...)` by name (grepped exhaustively). So the legacy
`promote_candidates` function object has zero remaining references the instant `del` executes and is
garbage — its body, and the two imports inside it (941, 989), can never execute. `gated_writes.py`'s own
docstring gestures at this precisely: "Existing retained functions resolve the global name
`promote_candidates` dynamically and therefore see the sealed replacement defined below" — true in
principle (shared `globals()` means a bare-name call would resolve to the new sealed function), but
**measured to not actually happen**: nothing calls it that way today. [MEASURED]

Lines 178 (`daedalus.spine.killswitch`), 365/385/696/835 (`daedalus.orchestration.execution`), 475/1015
(`daedalus.config`), and 83 (`.worktree`, module-level in the legacy source) are real and reachable too,
but none of their targets are among the 18 declared SCC members, so they do not change the SCC edge count
— they are noted only as evidence that `_promote_one_inner`/`_attempt_assignment` invoke actual attempts
through `daedalus.orchestration.execution.run_attempt`/`command_gate` (non-SCC), while the `spine.attempt`
imports above supply only *data/gate-construction* types (`GateResult`, `TaskSpec`, `RunnerContext`,
`offload_runner`) — real coupling to `spine.attempt`'s shape, but not to its own execution entrypoint.

### Dynamic references (AST-invisible)

Grepped both `gated_writes.py` and `_gated_writes_legacy.py.src` for `importlib.import_module`,
`__import__`: **0 matches** in either file. `gated_writes.py` does use
`importlib.resources.files(__package__).joinpath(...)` (line 13, 42) — not a module import, a **package
data resource read**, verified by pinned Git blob SHA-1 before `exec()`. This is the one dynamic-reference
mechanism in the module and it is the reason the probe misses the 7 edges above; it does not itself name
another SCC module by string. [MEASURED]

## What it actually does

`gated_writes.py` is a thin "compatibility strangler": it `exec()`s a Git-blob-pinned legacy source file
into its own namespace (preserving every historical class/function/pickle name), deletes the legacy
`promote_candidates`, and defines a new sealed `promote_candidates` that requires a persisted
`ApprovalLedger` + `owner_keyring` + one-use `consumed_approval` before touching Git, re-authenticates that
capability twice (once effect-free, once again under a cross-process lock against a freshly read live
target HEAD), and refuses on any mismatch before worktree creation. The retained legacy code it wraps
(`gate_candidates`, `run_write_wave`) runs write-mode `Assignment`s concurrently through
`daedalus.spine.attempt`-shaped `TaskAttempt`/`run_attempt` calls in isolated worktrees and returns
`GatedCandidate`s — never touching the primary checkout — and separately gates cumulative promotion on
`daedalus.core.get_governance()`. The whole module's purpose is enforcing the master plan's Invariant 5
(sealed promotion, no auto-merge/self-promotion): promotion only happens through one exact,
owner-approved, evidence-bound call.

## Layer

**kernel**, and mis-sited today (lives in `daedalus/kairos/`, a legacy grab-bag package name, not in
`daedalus/kernel/`). This is not a scheduling/campaign-driving module by behaviour — it *is* the promotion
trust boundary. Its sealed `promote_candidates` performs exactly what the target layer definition names
for `kernel`: "effects, leases, policy, attempts, promotion, evidence." It authenticates persisted owner
approval (`authorize_persisted_promotion`, `PREAUTHORIZATION_STAGE`/`SEALED_STAGE`), refuses before any
process/lock/worktree effect, snapshots candidates immutably before capability authentication
(`snapshot_promotion_candidates`), and is the one production-capable, single-caller wrapper around
`daedalus.kernel.promotion`'s own primitives — its own docstring literally names it "the sealed Kairos
promotion seam." The task brief's own hint is correct: `gated_writes` imports `kernel.promotion` (three
statements, six distinct symbols total) precisely because it is doing kernel-shaped work, not because it
merely uses a kernel utility in passing. `kairos.scheduler` (the sibling module in this same package,
verdicted `orchestration` in its own dossier) calls **into** `gated_writes` for write gating — a
downward, orchestration → kernel dependency, which is the correct direction for the target layout, not
evidence the two belong in the same layer just because they share a directory today.

## Severance

**`-> kernel.promotion`, all three import statements (6 distinct symbols total:
`PromotionAuthorizationError`, `snapshot_promotion_candidates`, `PREAUTHORIZATION_STAGE`,
`authorize_persisted_promotion`, `SEALED_STAGE`, `resolve_live_target_revision`; combined 3 statements, 1
function).** Real coupling — not a pass-through — every one of these 6 symbols is a promotion-authority
primitive actually invoked (not merely re-exported). Cheapest severance: **(d) genuine merge with the
target.** Given the Layer verdict above, the split between "the sealed compatibility wrapper in
`kairos.gated_writes`" and "the promotion-authority primitives in `kernel.promotion`" is an artifact of
`gated_writes`'s legacy `kairos/` location, not a real architectural boundary — both already live in the
same conceptual trust boundary (D5 promotion), `gated_writes.promote_candidates` calls `kernel.promotion`
for literally every authorization decision it makes, and 6 symbols across 3 statements in one function is
too much surface for a Protocol to meaningfully narrow without just re-describing `kernel.promotion`'s own
API back to itself. Relocating `gated_writes.py` (or at minimum its sealed `promote_candidates` plus the
strangler machinery) into `daedalus/kernel/` removes the edge by removing the package boundary that
manufactures it, rather than porting/injecting around a boundary that should not exist.

**`-> spine.picker` (`resolve_spine_db_path`, 1 symbol, 2 reachable call sites: `gated_writes.py:259` in
the sealed `promote_candidates`, and legacy-src line 462 in `gate_candidates` — the second missed by the
probe entirely).** Real coupling (ledger-path resolution is required before either function can proceed),
but thin: one symbol, already deferred at both sites. Cheapest severance: **(b) callback/parameter
injection.** Add an optional `ledger_locator: Callable[[Path], tuple] | None = None` parameter to both
`gate_candidates` and the sealed `promote_candidates` (both already accept `ledger_path=None` and resolve
it lazily on demand), defaulting to the current deferred `spine.picker.resolve_spine_db_path` import when
not supplied. Cheaper than (a): one symbol used identically at both sites does not justify a new Protocol
module, and `spine.picker` is a small leaf-shaped module already, not a good merge target (per the
`kernel.promotion` dossier's own note, `spine.picker` is also imported by other SCC members independently).

**`-> spine.attempt` (4 distinct symbols — `GateResult`, `offload_runner`, `TaskSpec`, `RunnerContext` —
across 5 import statements at 4 call sites, all inside the exec'd legacy source and invisible to the
probe).** This is the deepest, least-thin edge on this module: `GateResult` is the gate-verdict type
`_relay_gate` constructs and returns, `offload_runner` is the factory `_recording_runner` wraps to make
`offload()` usable as a `TaskAttempt` runner, `TaskSpec` is built by `_spec_for` to describe every write
attempt, and `RunnerContext` types the promotion-retry path in `_promote_one_inner`. This is genuine,
substantial coupling to `spine.attempt`'s data shape — not a pass-through, and not cheap to sever cleanly:
the actual attempt *execution* already goes through `daedalus.orchestration.execution.run_attempt`/
`command_gate` (non-SCC, lines 385/696/835), so this module does not need `spine.attempt`'s composition
seams (`TaskAttempt`, `run_attempt`, `command_gate`, `pytest_gate` per the `kernel.promotion` dossier's
`_COMPOSITION_NAMES` finding) — only its four inert record/factory types. Cheapest severance: **(a)
port/protocol extraction**, mirroring the `kernel.promotion` dossier's own recommendation for the same
kind of symbols: if/when `AttemptResult`/`GateResult`/`PatchArtifact`/`STATE_CLEAN`/`TaskSpec` move to a
non-SCC-member contracts module (e.g. `daedalus/kernel/contracts/attempt.py`, already proposed by the
sibling `kernel.promotion` dossier), `gated_writes`'s four legacy-src imports move with them for free —
this is the same underlying edge as `kernel.promotion -> spine.attempt`, discovered independently here on
the `gated_writes` side, and both should be fixed by the same one contracts-extraction packet rather than
two separate ports.

**`-> core` (`get_governance`, 1 symbol, 1 call site inside `_governance_verdict`, called from
`run_write_wave` — invisible to the probe).** Real coupling: this is a genuine policy gate
("promotion_allowed, gov_state, gov_verdict = _governance_verdict(...)" directly decides whether gated
candidates get held or reported promotable). Already deferred. Cheapest severance: **(b)
callback/parameter injection** — thread a `governance_fn: Callable = None` parameter through
`run_write_wave`/`_governance_verdict`, defaulting to the current deferred `daedalus.core.get_governance`
import, letting `build_exec.WaveExecutor` (the confirmed caller of `run_write_wave`) inject it if it
already holds a `core` reference.

**`-> kairos.scheduler` (`DEFAULT_AVAILABILITY`, 1 symbol, 1 call site inside `run_write_wave` — invisible
to the probe; this is a second, independent 2-cycle with `kairos.scheduler`, distinct from the
scheduler↔offload cycle the sibling dossier addresses).** `DEFAULT_AVAILABILITY` is a plain dict constant
(`scheduler.py:37-38`) with no behaviour. Cheapest severance: **(b), effectively free constant
extraction** — exactly the same shape as the sibling analyst's `FREE_LANES → limit_policy.py` proposal
(see the `kairos.scheduler` dossier's assessment): move `DEFAULT_AVAILABILITY` (and `FREE_LANES`) into one
shared non-SCC leaf module both `kairos.scheduler` and `kairos.gated_writes`/`_gated_writes_legacy.py.src`
already need, so `run_write_wave` imports the constant from there instead of `.scheduler`. This closes the
`gated_writes -> scheduler` leg the same way the sibling's proposal closes `offload -> scheduler` — but
note it is a **different** cycle (`scheduler -> gated_writes` via `gate_candidates` at `scheduler.py:436`
is the other, real-coupling leg here, not `FREE_LANES`/offload), so fixing one does not fix the other; both
constant-extraction moves are independent, both cheap, and both should happen together since they are the
same pattern applied to sibling constants.

## Tests that pin this

Grep `daedalus\.kairos\.gated_writes|gate_candidates|GatedCandidate|run_write_wave` over `tests/*.py`
(excluding `__pycache__`): **18 files, 42 matching lines** [MEASURED, ripgrep count]. Files:
`tests/contracts/test_import_scc_hierarchy.py`, `tests/gates/test_repository_write_classification_review.py`,
`tests/gates/test_write_evidence_producer.py`, `tests/gates/test_write_surface_lease_dominance.py`,
`tests/kernel/test_effect_replay_projection.py`, `tests/kernel/test_live_promotion_legacy_retirement.py`,
`tests/kernel/test_live_promotion_seam.py`, `tests/kernel/test_live_promotion_seam_review.py`,
`tests/kernel/test_persisted_promotion_authorization.py`, `tests/kernel/test_promotion_material_review.py`,
`tests/kernel/test_sealed_promotion.py`, `tests/kernel/test_write_evidence_records.py`, `tests/test_loop.py`,
`tests/test_loop_lease.py`, `tests/test_loop_lease_policy.py`, `tests/test_loop_spend_refused.py`,
`tests/test_promotion_trust_root_single_caller.py`, `tests/test_registry_new_doors.py`,
`tests/test_spine_picker.py`.

`mock.patch`/`patch` string targets naming this module directly: **1 match** [MEASURED] —
`tests/test_loop_lease.py:482`, `mock.patch("daedalus.kairos.gated_writes.run_write_wave", ...)` inside
`test_gated_write_wave_gets_the_lease_the_day_it_accepts_one`. This breaks on any rename/move of
`run_write_wave` out of `daedalus.kairos.gated_writes`'s public surface, even though the function is
actually *defined* in the legacy `.src` resource — the patch target is the module attribute, which is
unaffected by where the definition physically lives as long as the exec-into-namespace mechanism keeps
exposing it there.

Governance/architecture test: `tests/contracts/test_import_scc_hierarchy.py` names
`"daedalus.kairos.gated_writes"` explicitly (line 27) inside `OLD_CROSS_DOMAIN_COMPONENT` /
`CURRENT_CROSS_DOMAIN_COMPONENT`, asserting a frozen `CURRENT_COMPONENTS_SHA256` computed from the actual
measured SCC via `daedalus.structcore.cycles.nontrivial_components`. Because that instrument walks real
`import` machinery (not a fixed file list), it is very likely **already sensitive to the 7 probe-missed
edges** documented above — `nontrivial_components` should see every edge that actually executes at import
time, including ones the hand-rolled AST probe in this task misses by not parsing the exec'd `.src`
resource. This is worth flagging upward: **the AST probe used for this whole 18-module SCC census may be
undercounting `gated_writes`'s true edge set, while the repo's own governance test may already be counting
it correctly** — the two instruments could disagree, and only the governance test's `nontrivial_components`
implementation, not this dossier, can settle whether the frozen `CURRENT_COMPONENTS_SHA256` reflects the 7
extra edges. Not verified further (would require reading `daedalus/structcore/cycles.py` and running the
test, out of scope for static analysis of these two modules).

Additionally relevant: the 8 `tests/kernel/test_*promotion*`/`test_live_promotion*`/`test_sealed_promotion`
files exercise `promote_candidates` end-to-end and would need updating if the sealed function's home
changes (per the `(d) genuine merge` recommendation above); `tests/gates/*` and `tests/test_spine_picker.py`
plausibly pin `gate_candidates`/`resolve_spine_db_path` call shape; not individually enumerated by test
function name here for space — file-level list above is exhaustive per the grep count.

Not run (STATIC ANALYSIS ONLY per task rules); pass/fail after any severance edit is UNVERIFIED until
`.venv/Scripts/python.exe -m pytest` is actually executed by an authorized step.
