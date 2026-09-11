# orchestrate

Measured at `HEAD = main = 851ff43c` (verified `git diff 74008fab..main -- daedalus/orchestrate.py` is empty, so the 74008fab census carries).
Greps scoped to `daedalus/`, `tests/`, `tools/` (plus `docs/` for the promised-reader check). `.claude/worktrees/agent-*/` holds full copies of `daedalus/` and `tests/` and was excluded — counting it would have doubled every importer.

## Identity

`C:/Users/Administrator/daedalus/daedalus/orchestrate.py` — 9 lines. A registered compatibility CLI facade that re-exports three names from `daedalus.kairos.orchestrate` and forwards `__main__` to its `main()`.

## Importers (MEASURED)

**Zero import sites.** AST census over 1143 tracked `.py` files in `daedalus/ tests/ tools/`: 0 in `daedalus/`, 0 in `tests/`, 0 in `tools/`, 0 deferred.

Searched additionally for non-import readers — this is the part that matters for a facade:

| Reference kind | Result |
| --- | --- |
| `importlib` / `__import__` / literal `"daedalus.orchestrate"` | none in source |
| `pyproject.toml` console_scripts | none (no `[project.scripts]` entry) |
| `python -m daedalus.orchestrate` | **4 documented invocations** |
| shim registry | **registered** |

Documented invocations (these are the promised readers):
- `daedalus/resources/templates/CLAUDE.md:12` — `python -m daedalus.orchestrate "<task>" --repo-root <this repo>`
- `daedalus/resources/templates/CLAUDE.md:18` — same, `--lane local_only`
- `docs/COMMS_PROTOCOL.md:83` — `python -m daedalus.orchestrate "<task>" --repo-root <repo> --lane auto --source codex`
- `docs/COMMS_PROTOCOL.md:168` — "Claude Code delegates via `python -m daedalus.orchestrate`"

`daedalus/resources/templates/` is shipped template content, i.e. this command is handed to *other* repositories.

## Imports (MEASURED)

**Module-level (1):**
- `daedalus/orchestrate.py:3` — `from .kairos.orchestrate import _infer_paths, main, prepare_task` → `daedalus.kairos.orchestrate`

**Deferred/function-scope:** none.

`daedalus.*`: 1. stdlib/third-party: 0. Note it re-exports `_infer_paths`, a **private** name, so the facade is bound to its target's internals, not only its public surface.

## What it does

It re-exports `prepare_task`, `main` and the private `_infer_paths` from `daedalus.kairos.orchestrate` so that the historical dotted path `daedalus.orchestrate` keeps resolving. Its `if __name__ == "__main__"` block forwards to the target's `main()`, which is what makes `python -m daedalus.orchestrate` still work. It contains no logic of its own — 9 lines, one import, one `__all__`, one main guard.

## Proposed destination

**`interfaces.cli`** (retain as a shim; do **not** delete in this packet).

Argument: `docs/architecture/shim-registry.json` already assigns it — `import_path: "daedalus.orchestrate"`, `owner: "interfaces-cli"`, `targets: ["daedalus.kairos.orchestrate"]`, `kind: "cli_facade"`. The repository has already decided both what this is and who owns it; classification only has to agree. Its sole behaviour is a console entrypoint, which is the definition of the CLI interface layer.

Counter-argument, and the strongest one: zero importers plus zero console_scripts looks exactly like dead code, and `delete` is the tidier answer. It loses on the registry's own removal criterion — *"The replacement CLI is packaged and effect-registry plus wheel audits show no remaining legacy target."* Four documented invocations of the legacy target remain live, two of them inside `daedalus/resources/templates/`, which is content shipped into other repositories. The criterion is **not met**, so deletion now would break a documented, externally-distributed command. Zero importers is a finding here, not a verdict — the reader is a human at a shell, and no import graph can see that.

## Boundary-rule verdict after the move

- **kernel-no-outer-layers** — (a) N/A, `interfaces.cli` is not a rule source. (b) no `daedalus/kernel` file imports it (measured, see below). CLEAN.
- **runtimes-no-gates** — (a) N/A, not a rule source. (b) no `daedalus/runtimes` importer. CLEAN.
- **spine-no-outer-layers** — (a) N/A. (b) no `daedalus/spine` importer. CLEAN.
- **twin-no-outer-layers** — (a) N/A. (b) no `daedalus/twin` importer. CLEAN.

Direction (b) is vacuously clean for a stronger reason than "I found nothing": the lead enumerated the **complete** set of flat `daedalus` modules that the 142 files under `kernel/spine/twin/runtimes` import — `{budget, sensitivity, structcore, limit_policy, primary_tree, config, storage, atomic, mapping, offload, providers, resources}` — and `orchestrate` is absent from it. The instrument was positive-controlled: it fired on the known `daedalus/kernel/attempt_execution.py:1209 -> daedalus.offload` edge named in the boundary contract's own rationale.

Verdict: **CLEAN**, both directions.

One caveat the moving packet must own: the module's *dotted name* is the artifact here. A move that changes `daedalus.orchestrate` to `daedalus.interfaces.cli.orchestrate` without updating the four documented invocations and the shim-registry `import_path` breaks the facade's only purpose.

## Dead-code signals

Zero importers — a finding, not a verdict, and here the verdict goes the other way.

Docstring, quoted in full: `"""Compatibility CLI for :mod:`daedalus.kairos.orchestrate`."""` It promises a reader explicitly, and the reader is a CLI user, not an importer.

Corroborating history: `docs/inventory/2026-08-21/council_verdicts.json:376` recorded the same zero state — *"no file imports daedalus.ikarus, daedalus.decompose, daedalus.drafts, daedalus.mission_control, daedalus.orchestrate"*. So the zero is an old, known, deliberate state, not fresh rot.

For deletion to be safe, all four documented `python -m daedalus.orchestrate` invocations would have to be repointed at the replacement CLI and the shipped template content regenerated. That is **not** true today. Keep the shim; retire it under its registered criterion, in a packet that owns the docs.

## Confidence

**High.** The shim registry states the kind, the owner and the retirement condition; the docstring states the intent; the invocation sites are enumerated. What would raise it to certainty: confirming whether the "replacement CLI" is packaged (a `[project.scripts]` audit of the built wheel), which decides how close this shim is to its removal criterion.
