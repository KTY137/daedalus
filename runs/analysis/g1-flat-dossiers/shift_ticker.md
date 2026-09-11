# shift_ticker

Measured at `HEAD = main = 851ff43c` (verified `git diff 74008fab..main -- daedalus/shift_ticker.py` is empty, so the 74008fab census carries).
Greps scoped to `daedalus/`, `tests/`, `tools/` (plus `docs/` for the promised-reader check). `.claude/worktrees/agent-*/` holds full copies of `daedalus/` and `tests/` and was excluded — counting it would have doubled every importer.

## Identity

`C:/Users/Administrator/daedalus/daedalus/shift_ticker.py` — 97 lines. A standalone human-facing terminal CLI that re-renders the currently declared working shift on a timer; stdlib only apart from one `daedalus` sibling.

## Importers (MEASURED)

**Zero import sites.** AST census over 1143 tracked `.py` files in `daedalus/ tests/ tools/`: 0 in `daedalus/`, 0 in `tests/`, 0 in `tools/`, 0 deferred.

For a leaf CLI, zero importers is the *expected* shape, so the non-import reader search is the real measurement:

| Reference kind | Result |
| --- | --- |
| `importlib` / `__import__` / literal `"daedalus.shift_ticker"` | none in source |
| `pyproject.toml` console_scripts | **none** |
| shim registry | **not registered** (unlike `orchestrate` / `mission_control`) |
| `python -m daedalus.shift_ticker` | **documented, plus its own docstring** |

Documented readers:
- `docs/FEATURE_INVENTORY.json:40575` — the literal command `"python -m daedalus.shift_ticker"`
- `docs/FEATURE_INVENTORY.json:2445` and `:2447` — records it as `main_guard:daedalus.shift_ticker`, i.e. the inventory classifies it as an entrypoint reached through its `__main__` guard, and `reached_from` names that guard
- its own docstring, lines 3-6, gives two invocations verbatim

So the inventory already models this module as a main-guard entrypoint rather than as library code. That is a recorded reader, and it is the only kind this module ever had.

## Imports (MEASURED)

**Module-level (6):**
- `daedalus/shift_ticker.py:27` — `argparse` (stdlib)
- `daedalus/shift_ticker.py:28` — `sys` (stdlib)
- `daedalus/shift_ticker.py:29` — `time` (stdlib)
- `daedalus/shift_ticker.py:30` — `from datetime import datetime` (stdlib)
- `daedalus/shift_ticker.py:31` — `from pathlib import Path` (stdlib)
- `daedalus/shift_ticker.py:34` — `from daedalus import shift as shift_mod` → **`daedalus.shift`** (the only `daedalus.*` edge)

**Deferred/function-scope:** none.

`daedalus.*`: 1. stdlib: 5. Third-party: 0 — consistent with the docstring's claim *"stdlib only; no daemon, no tmux dependency."*

Two couplings worth recording:
- Line 33 executes `sys.path.insert(0, str(Path(__file__).resolve().parents[1]))` **at import time**, before the `daedalus` import on line 34 (hence the `# noqa: E402`). A module that mutates `sys.path` on import is a portability smell and, as shown below, a concrete move hazard.
- It reaches into a **private** member of its sibling: `shift_mod._hm(...)` at lines 62, 64, 65. So it depends on `daedalus.shift`'s internals, not only its public surface.

## What it does

It loads the declared shift via `daedalus.shift.load()` and renders a one-screen status block — wall-clock time, the declared goal, a progress bar, time remaining against the declared window, and the last four checkpoints. `main()` loops on a configurable cadence (`--every`, default 60s, or `--once`) printing that block until interrupted, and deliberately enforces nothing: when the window passes it says so loudly once per tick and keeps running. 97 lines, stdlib plus one sibling.

## Proposed destination

**`interfaces.cli`.**

Argument: every measured property is that of a console entrypoint. It has an `argparse` parser with `prog="daedalus.shift_ticker"`, a `__main__` guard raising `SystemExit(main())`, zero importers, and its only documented readers are two `python -m` invocations. It holds no state, writes nothing, and its single `daedalus` dependency is a read-only `load()` of a sibling. `docs/FEATURE_INVENTORY.json` independently classifies it as `main_guard:daedalus.shift_ticker`.

Counter-argument: zero importers, no console_scripts entry and no shim-registry entry could read as unowned rot — the weakest ownership evidence of the three zero-importer modules in this half. It loses on the docstring, which is unusually explicit about who reads this and why: *"This is the HUMAN's view"*, run *"in tmux, screen, or any spare terminal"*. The reader is a person at a terminal; no import graph can ever see that reader, so absence from the graph is not evidence of absence of use. The docstring also positions it as *"the companion to the hooks package"* and warns that *"Building only this would look like a fix and change nothing about the agent's blindness"* — that is a designed, argued role, not an abandoned file.

A second counter — "fold it into `shift.py`, it is 97 lines and uses `shift`'s privates" — is a real option, but it would put a blocking render loop inside a library module that other code imports. Keeping the loop in a separate CLI leaf is the better shape; the private-member coupling (`_hm`) is worth fixing separately by promoting `_hm` to public.

## Boundary-rule verdict after the move

- **kernel-no-outer-layers** — (a) N/A, `interfaces.cli` is not a rule source. (b) no `daedalus/kernel` importer. CLEAN.
- **runtimes-no-gates** — (a) N/A. (b) no `daedalus/runtimes` importer. CLEAN.
- **spine-no-outer-layers** — (a) N/A. (b) no `daedalus/spine` importer. CLEAN.
- **twin-no-outer-layers** — (a) N/A. (b) no `daedalus/twin` importer. CLEAN.

Direction (b) is vacuously clean by enumeration rather than by failed search: the lead enumerated the **complete** set of flat `daedalus` modules imported by the 142 files under `kernel/spine/twin/runtimes` — `{budget, sensitivity, structcore, limit_policy, primary_tree, config, storage, atomic, mapping, offload, providers, resources}` — and `shift_ticker` is absent. The instrument was positive-controlled against the known `daedalus/kernel/attempt_execution.py:1209 -> daedalus.offload` edge named in the boundary contract's own rationale.

Direction (a): its single `daedalus.*` import is `daedalus.shift`. Were it ever placed in `kernel`, `spine` or `twin`, that target is on **none** of those strict allowlists and would be REFUSED at line 34. Under `interfaces.cli` no rule binds it.

Verdict: **CLEAN** for the proposed destination.

### Move hazard the boundary rules cannot see (SILENT, not loud)

The four import rules would pass this move, and the move would still break the tool — quietly. Lines 33 and 82 both compute `Path(__file__).resolve().parents[1]`:

- today, from `daedalus/shift_ticker.py`, `parents[1]` is the **repository root**;
- after a move to `daedalus/interfaces/cli/shift_ticker.py`, `parents[1]` becomes `daedalus/interfaces`.

Line 82 feeds that value to `shift_mod.load(root)` as `repo_root`. `daedalus/shift.py:240-245` resolves it as `root / SHIFT_REL_PATH` and `load()` documents *"A missing file is not an error — it means nobody declared a shift, which is a legitimate state"*, returning an empty `Shift()` on `OSError`.

Consequence: after the move the ticker would **not crash**. It would print `no shift declared` on every tick, forever, while a shift was in fact active — a silent wrong answer, in the one tool whose entire job is to tell a human the truth about the clock. The `DAEDALUS_REPO_ROOT` environment fallback in `shift.py:241` can mask it on whichever machine has that variable set, making the failure environment-dependent and harder to reproduce.

The moving packet must therefore replace both `parents[1]` computations with a root that does not depend on file depth. This is worth stating loudly because no import-boundary rule, and no cold-import test, can observe it.

## Dead-code signals

Zero importers — a finding, and here the verdict clearly goes the other way: **not dead, and not a shim.**

Docstring, quoted: *"shift_ticker.py — the pane a person watches while an agent works. Run it in tmux, screen, or any spare terminal: `python -m daedalus.shift_ticker` ... This is the HUMAN's view."* It promises a reader, names the invocation, and argues its own scope limits.

Distinguishing it from its two zero-importer neighbours in this half is the useful result: `orchestrate` and `mission_control` are *registered shims* with retirement criteria, whereas `shift_ticker` is a *live leaf CLI* with real logic (rendering, progress bar, loop) and no re-export surface at all. Same importer count, opposite meaning — which is exactly why zero importers cannot be treated as a verdict.

For deletion to be safe, the `python -m` invocation recorded at `docs/FEATURE_INVENTORY.json:40575` would have to be withdrawn and the human workflow it serves replaced. That is not true, and nothing suggests it is intended. **Do not delete.**

The one real gap: it has neither a `console_scripts` entry nor any test, so nothing mechanical would notice if the move above broke it. Adding a `--once` smoke test would be cheap — `main(["--once"])` returns 0 and is non-blocking by construction — and would convert the silent failure mode above into a loud one.

## Confidence

**High** on destination and on the not-dead verdict: the docstring, the inventory's `main_guard` classification, and the module's own `argparse`/`__main__` structure agree.
What would raise it further: confirmation that a human actually runs it today (unobservable from the tree — the honest limit of this dossier), and a decision on whether `interfaces.cli` should carry a `console_scripts` entry so the entrypoint stops being invisible to packaging.
