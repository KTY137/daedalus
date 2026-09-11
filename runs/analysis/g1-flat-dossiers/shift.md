# daedalus/shift.py

Scope note: all searches below are scoped to `daedalus/`, `tests/`, `tools/`
only (Grep `path=`). `.claude/worktrees/agent-*/` holds full duplicate copies
of `daedalus/` and `tests/` and was explicitly excluded to avoid double
counting.

## Identity

Absolute path: `C:/Users/Administrator/daedalus/daedalus/shift.py`. 322 lines
(header says 322; file body read confirms `if __name__` tail at line 320-323).
Declares an explicit, OS-clock-anchored "working window" (goal, started,
until, done-means) in `runs/shift.json` so that an agent cannot lose track of
wall-clock time the way one measurably did on 2026-07-30 (module docstring).

## Importers (MEASURED)

Total found: 6 sites (2 daedalus/ + 3 tests/ + 1 tools/), 5 deferred —
matches the lead's precomputed count exactly.

daedalus/ (2 sites):
- `daedalus/hooks/events.py:58` — `from daedalus import shift as shift_mod` (deferred, inside a hook handler function).
- `daedalus/shift_ticker.py:34` — `from daedalus import shift as shift_mod  # noqa: E402` (module-level; the `noqa: E402` marks it as intentionally *not* at the top of the file, but it is still module-scope, not function-scope).

tests/ (3 sites, all deferred, across 2 files):
- `tests/test_cli_effect_boundary.py:114` — `from daedalus.shift import main` (deferred, inside a test function).
- `tests/test_cli_effect_boundary.py:121` — `from daedalus.shift import main` (deferred, second test function in the same file).
- `tests/test_hooks_review_20260825.py:328` — `from daedalus import shift as shift_mod` (deferred, inside a test function).

Not counted as importers: `tests/test_deepseek_substitution_guard.py:182,189,197`
and `tests/test_lanes_checks.py:201`, which all pass the *string* `"from
daedalus.shift import ...\n"` / `"from daedalus import shift\n"` as literal
test input to an import-resolution checker (`_unresolved_first_party_imports`)
— they test parsing of that string, they do not themselves import `shift`.

tools/ (1 site, deferred):
- `tools/watchdog.py:848` — `from daedalus import shift as shift_mod` (deferred, inside the fact-gathering function that also produces `facts["shift"]` for the anomaly report at lines 850-880).

Dynamic/string references searched: `python -m daedalus.shift` appears in
`daedalus/shift.py:316` itself (usage string) and `daedalus/shift_ticker.py:49`
(a suggested command printed to the user), not as an executed dynamic import.
No `importlib`/`__import__` reference to `shift` found. No `pyproject.toml`
console_scripts entry.

## Imports (MEASURED)

Module-level:
- `daedalus/shift.py:44` — `from .atomic import write_text_atomic` → `daedalus.atomic`.
- stdlib: `json`, `os`, `dataclasses`, `datetime`, `pathlib`, `time` (inside `_ShiftLock.__enter__`), `sys` (inside `__main__` guard).

Deferred/function-scope (inside `main()`, the CLI dispatcher, only for the
mutating verbs `start`/`note`/`end`; the read-only `status` verb never
reaches this):
- `daedalus/shift.py:295` — `from daedalus.budget import process_guard_boundary_decision` → `daedalus.budget`.
- `daedalus/shift.py:296` — `from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect` → `daedalus.spine`.

Outbound profile confirmed: `{atomic, budget, spine}`, 0 third-party, 2
deferred — matches the lead's precomputed profile exactly.

## What it does

`Shift` is a small dataclass (goal/started/until/done_means/notes) persisted
to `runs/shift.json`, read against a freshly-taken OS clock on every call so
neither a stale timestamp nor an unenforced deadline can be mistaken for the
truth. Concurrent writers (a ticker polling on a timer, a prompt hook reading
every turn, an agent appending checkpoints) are handled via atomic
temp-file-plus-`os.replace` publication for the whole-file writes and a
separate best-effort lock file for the read-modify-write `note()` append,
with an explicit Windows-specific caveat that `os.replace` can hit
`ERROR_ACCESS_DENIED` against a concurrently-open reader. 322 lines, module
level only touches `daedalus.atomic`; the two `daedalus.budget`/
`daedalus.spine` imports are deferred into the mutating CLI verbs only.

## Proposed destination

**foundation.**

Argument: it is a small, stdlib-only (module-level) state library — its only
`daedalus.*` dependency at import time is `daedalus.atomic`, itself a
foundation-level primitive — consumed *across* layers rather than owned by
one: a hook (`daedalus/hooks/events.py`, orchestration-adjacent), a CLI
ticker (`daedalus/shift_ticker.py`, interfaces.cli), and a standalone
diagnostic tool (`tools/watchdog.py`). That "shared substrate reused by
hooks, CLI, and tools, with no layer-specific logic of its own" is the same
shape the packet's steer already accepts for `skills`+`text_integrity` as
foundation.

Strongest counter-argument: `shift.py` has its own `main()`/`__main__` guard
and is directly invokable as `python -m daedalus.shift start|note|end|status`,
which argues for `interfaces.cli`. This loses because the *live, documented*
CLI surface for shifts is `daedalus/shift_ticker.py` (which imports `shift`
and additionally reaches into its private `_hm()` helper — see Dead-code
signals) — `shift.py` itself is the reusable state/library layer underneath
that CLI, not the CLI itself; collapsing the two into one `interfaces.cli`
module would put policy-adjacent effect-boundary wiring for both `shift.py`
and `shift_ticker.py` in the CLI layer when only `shift.py`'s mutating verbs
touch `daedalus.budget`/`daedalus.spine` at all, and only when invoked
directly rather than via the ticker.

## Boundary-rule verdict after the move

Landing in `foundation` is not a rule source for any of the four rules (all
bind only `daedalus.kernel`, `daedalus.runtimes`, `daedalus.spine`,
`daedalus.twin` as sources), so all four rules are
**N-A-not-a-rule-source** for direction (a).

(b) reverse direction — **CLEAN**, per the lead's positive-controlled
measurement: no file under `daedalus/kernel`, `daedalus/spine`,
`daedalus/twin`, `daedalus/runtimes` imports any of the five packet modules
at any AST scope, and the complete flat-module import set of those 142
layer-files (`{budget, sensitivity, structcore, limit_policy, primary_tree,
config, storage, atomic, mapping, offload, providers, resources}`) does not
include `shift`. Attributed to the lead's measurement.

Hypothetical (a), if it had landed in a rule-source layer anyway (using its
actual measured imports: `atomic` module-level, `budget`+`spine` deferred
inside `main()`):
- `kernel-no-outer-layers`: `daedalus.atomic` is on the allowlist (clean);
  `daedalus.budget` is on the allowlist (clean); `daedalus.spine` is on the
  allowlist (clean). **No refusal.**
- `spine-no-outer-layers`: `daedalus.atomic` allowed; `daedalus.budget`
  allowed; `daedalus.spine` is the rule's own source prefix (n/a to self).
  **No refusal.**
- `twin-no-outer-layers`: allowlist is only `{kernel, spine, structcore}`.
  `daedalus.atomic` is **not** on it → refused (`daedalus/shift.py:44`).
  `daedalus.budget` is **not** on it → refused (`daedalus/shift.py:295`).
  `daedalus.spine` **is** allowed (`daedalus/shift.py:296`, clean).
- `runtimes-no-gates`: N/A — `shift.py` never imports `daedalus.gates` at any
  scope.

One-line verdict: **N-A-not-a-rule-source** (destination is foundation);
had it landed under `kernel` or `spine` instead it would be entirely
**CLEAN**; only under `twin` would it be **REFUSED**
(`daedalus.atomic` line 44, `daedalus.budget` line 295).

## Dead-code signals

Not dead; it is the busiest of this packet's five modules by distinct-caller
diversity (hook, ticker, tool, two test files). `docs/FEATURE_INVENTORY.json`
lines 2409-2413 record `"module": "daedalus/shift.py", "status": "wired",
"classification": "entry", "reason": "declared entry point", "entry_kinds":
["main_guard"]` — an independent static-reachability instrument agrees it is
live. No entry for `daedalus.shift` in `docs/architecture/shim-registry.json`
(checked; 21 entries enumerated by a peer worker, none match — it is not a
compatibility facade). One hop on its liveliest daedalus/ importer,
`shift_ticker.py`: that module is itself independently recorded in
`docs/FEATURE_INVENTORY.json` (line 300, listed alongside `shift.py` in the
same watched-module group) and reaches not just the public API (`load`,
`start`, `note`, `end`) but the **private** `_hm()` time-formatting helper
directly — `daedalus/shift_ticker.py:62,64,65,67` call `shift_mod._hm(...)`.
That is a live, intentional coupling (both files were authored together, per
the module docstring's "`hook.py` beside this module" framing), not a
leaked-abstraction accident, but it does mean `shift.py`'s "private" surface
is not actually private to a second production file — worth flagging for
whoever executes the move, since a mechanical "make `_hm` truly private"
cleanup would break `shift_ticker` silently.

## Confidence

High. Importer/import counts match the lead's precomputed numbers exactly
(6 total, 5 deferred; profile `{atomic, budget, spine}`, 0 third-party, 2
deferred), FEATURE_INVENTORY independently corroborates "wired/entry", and
the private-helper coupling to `shift_ticker` was confirmed by direct read
rather than inference.
