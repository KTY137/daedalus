# mission_control

Measured at `HEAD = main = 851ff43c` (verified `git diff 74008fab..main -- daedalus/mission_control.py` is empty, so the 74008fab census carries).
Greps scoped to `daedalus/`, `tests/`, `tools/` (plus `docs/` for the promised-reader check). `.claude/worktrees/agent-*/` holds full copies of `daedalus/` and `tests/` and was excluded — counting it would have doubled every importer.

## Identity

`C:/Users/Administrator/daedalus/daedalus/mission_control.py` — 31 lines. A registered compatibility wrapper that re-exports twelve names from `daedalus.kairos.control` and nothing else.

## Importers (MEASURED)

**Zero import sites.** AST census over 1143 tracked `.py` files in `daedalus/ tests/ tools/`: 0 in `daedalus/`, 0 in `tests/`, 0 in `tools/`, 0 deferred.

Additional non-import reader search:

| Reference kind | Result |
| --- | --- |
| `importlib` / `__import__` / literal `"daedalus.mission_control"` | none in source |
| `pyproject.toml` console_scripts | none |
| `python -m daedalus.mission_control` | **none** — and it could not work anyway (no `__main__` block) |
| shim registry | **registered** — `docs/architecture/shim-registry.json:95` |

The only tracked mentions of the dotted name outside the file itself are records *about* it, not uses of it:
- `docs/architecture/shim-registry.json:95` — its own registry entry
- `docs/inventory/2026-08-21/council_verdicts.json:376` — a council verdict recording that nothing imports it
- `docs/inventory/2026-08-21/preruling/reachability.json:16716` — a reachability inventory listing it

## Imports (MEASURED)

**Module-level (1 statement, 12 names):**
- `daedalus/mission_control.py:3` — `from .kairos.control import (dashboard, main_dashboard, main_models, main_review_diff, main_squads, main_watcher, ollama_models, quality_gates, queue_timeline, review_diff, squads, watcher_status)` → `daedalus.kairos.control`

**Deferred/function-scope:** none.

`daedalus.*`: 1 target. stdlib/third-party: 0. All twelve re-exported names are public; unlike its sibling `orchestrate`, this facade does not reach into private members.

## What it does

It re-exports twelve public callables from `daedalus.kairos.control` — six `main_*` CLI entrypoints plus six data/dashboard helpers — so the historical dotted path `daedalus.mission_control` keeps resolving. It declares all twelve in `__all__` and contains no logic, no `__main__` guard, and no runtime behaviour of its own. 31 lines, one import statement, one `__all__` list.

## Proposed destination

**`interfaces.cli`** — and of the three zero-importer modules in this half, this is the **strongest `delete` candidate**, though not yet a safe one.

Argument: `docs/architecture/shim-registry.json:95` already assigns it — `import_path: "daedalus.mission_control"`, `owner: "interfaces-cli"`, `targets: ["daedalus.kairos.control"]`, `kind: "module_reexport"`. Six of the twelve re-exported names are `main_*` CLI entrypoints, which is what places the wrapper in the CLI interface layer rather than anywhere else. The repository has already decided the ownership; classification only has to agree.

Counter-argument, and it is genuinely strong here: unlike `orchestrate`, this module has **no `__main__` block**, so `python -m daedalus.mission_control` does not run anything. It therefore has no CLI reader, no import reader, and no documented invocation — the facade's whole purpose is to satisfy an importer, and no importer exists anywhere in the tree. That argues for `delete`.

Why it still loses, narrowly: the registry's removal criterion is *"CLI entrypoint, source, documentation, wheel, and runtime-string audits show no caller for one supported release."* I measured the source and runtime-string halves (clean) but **not** the wheel audit, and "one supported release" is a time condition I cannot evaluate from the tree. Deletion is a shim-retirement decision under a stated criterion, not a hierarchy-refactor side effect. Classify it to `interfaces.cli`, and hand the retirement to a packet that runs the wheel audit — which is a cheap, well-defined next step, not an open question.

## Boundary-rule verdict after the move

- **kernel-no-outer-layers** — (a) N/A, `interfaces.cli` is not a rule source. (b) no `daedalus/kernel` importer. CLEAN.
- **runtimes-no-gates** — (a) N/A. (b) no `daedalus/runtimes` importer. CLEAN.
- **spine-no-outer-layers** — (a) N/A. (b) no `daedalus/spine` importer. CLEAN.
- **twin-no-outer-layers** — (a) N/A. (b) no `daedalus/twin` importer. CLEAN.

Direction (b) is vacuously clean by enumeration, not by absence of search: the lead enumerated the **complete** set of flat `daedalus` modules the 142 files under `kernel/spine/twin/runtimes` import — `{budget, sensitivity, structcore, limit_policy, primary_tree, config, storage, atomic, mapping, offload, providers, resources}` — and `mission_control` is absent. The instrument was positive-controlled against the known `daedalus/kernel/attempt_execution.py:1209 -> daedalus.offload` edge.

Verdict: **CLEAN**, both directions. With zero importers there is by construction nothing a rule could refuse.

## Dead-code signals

Zero importers — a finding, not a verdict. Here the finding is unusually well-supported, because the zero state is *recorded and owned*.

Docstring, quoted in full: `"""Compatibility wrapper for :mod:`daedalus.kairos.control`."""` It promises a reader of exactly one kind — an importer of the legacy path — and no such importer exists.

Three independent records agree the zero is old and deliberate, not fresh rot:
1. the shim-registry entry, which pre-declares the retirement condition;
2. `docs/inventory/2026-08-21/council_verdicts.json:376`, which on 2026-08-21 already recorded *"no file imports daedalus.ikarus, daedalus.decompose, daedalus.drafts, daedalus.mission_control, daedalus.orchestrate"*;
3. the reachability inventory at `preruling/reachability.json:16716`.

That 2026-08-21 record is directly useful: it is evidence toward the registry's "no caller for one supported release" clause, since the state has now held for a documented span rather than being observed once today.

For deletion to be safe: the wheel/packaging audit must confirm no distributed artifact exposes `daedalus.mission_control`, and the "one supported release" clause must be satisfied. The source and runtime-string halves are already clean. Unlike `orchestrate`, **no documentation invokes it**, so there is no doc-repointing cost.

## Confidence

**High** on the classification and on the measurement; **medium** on the delete recommendation. What would raise the latter to high: the wheel/packaging audit named in the removal criterion, plus a decision on what "one supported release" means for this repository — both cheap and both outside this read-only packet.
