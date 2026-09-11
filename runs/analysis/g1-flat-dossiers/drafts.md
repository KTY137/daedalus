# daedalus/drafts.py

## 1. Size and shape

23 lines total (`daedalus/drafts.py:1-23`). 0 classes, 0 module-level
functions — pure re-export. Module-level state: none beyond the imported
names themselves (`DRAFT_DIR`, `ROOT` are re-exported constants owned by
`daedalus.kairos.drafts`, not defined here). Module-level side effects at
import: none — a single `from .kairos.drafts import (...)` at `drafts.py:3-12`
and an `__all__` list at `drafts.py:14-23`. No file reads, env reads, registry
mutation, or network at import time; whatever side effects `daedalus.kairos.drafts`
itself performs at import happen there, not in this shim.

## 2. What it does

`daedalus/drafts.py` re-exports eight names (`DRAFT_DIR`, `ROOT`,
`apply_payload`, `delete_draft`, `get_draft`, `list_drafts`, `save_draft`,
`set_status`) from `daedalus.kairos.drafts` under the flat import path
`daedalus.drafts`. It contains no logic of its own — every symbol is imported,
not defined. Its sole purpose (per its own docstring, `drafts.py:1`) is
declared as a "Compatibility wrapper for `daedalus.kairos.drafts`."

## 3. Who imports it (MEASURED)

**TOTAL: 0** real importers of `daedalus.drafts` (the flat shim) anywhere in
the git-tracked tree, across every import form searched:
`from .drafts import`, `from daedalus.drafts import`, `from daedalus import
drafts`, `import daedalus.drafts`, `from . import drafts`,
`importlib.import_module("daedalus.drafts")`, or the bare string
`"daedalus.drafts"` as a runtime target.

Commands run:
```
git grep -n --untracked=false -E "from \.drafts import|from daedalus\.drafts import|from daedalus import drafts|import daedalus\.drafts|from \. import drafts" -- '*.py'
git grep -n '"daedalus.drafts"' -- '*.py' '*.json' '*.md'
```
Both returned zero hits in source/test/config files. The only string hits for
`"daedalus.drafts"` are non-caller artifacts: `docs/architecture/shim-registry.json:29`
(the registry entry itself) and two occurrences inside a frozen historical
snapshot, `docs/inventory/2026-08-21/preruling/reachability.json:308,16703`.
`daedalus/cli.py:515` contains the substring `"daedalus drafts"` but it is a
CLI `prog=` label for argparse help text, not an import path or module
reference — confirmed by reading the surrounding line.

Per-layer breakdown: kernel 0, spine 0, twin 0, runtimes 0, orchestration 0,
interfaces 0, flat 0, tests 0. Every real consumer of draft functionality
imports `daedalus.kairos.drafts` **directly**, bypassing this shim entirely:
`daedalus/cli.py:512`, `daedalus/interfaces/http/effects.py:10`,
`daedalus/interfaces/http/read.py:8` (all confirmed via `from ...kairos import
drafts` / `from .kairos import drafts` reads), plus `tests/test_drafts.py`.
None of those is an edge onto `daedalus.drafts`.

## 4. What it imports (MEASURED)

- `daedalus.kairos.drafts` — `daedalus/drafts.py:3`, MODULE-LEVEL, relative
  import (`from .kairos.drafts import ...`), target layer `daedalus.kairos`
  (orchestration family). No third-party imports; no stdlib imports either —
  the file is exclusively a re-export statement plus `__all__`.

## 5. Proposed destination

**NONE-retire-per-registry-criteria.** Per the owner directive already
established for this module: `daedalus.drafts` is a REGISTERED SHIM
(`docs/architecture/shim-registry.json:28-36`, `import_path
"daedalus.drafts"`, `owner "orchestration"`, `kind "module_reexport"`, `target
daedalus.kairos.drafts`). A shim's import path *is* its contract; it does not
get a destination layer, and confidence in that framing is HIGH — it is
stipulated by the owner directive, not something this dossier re-derives. What
this dossier contributes is the registry's own removal-criteria audit below.

## 6. Boundary-rule check after the move

Not applicable in the ordinary sense — this module is not being moved to a
layer, it is being retired in place or left as-is pending the registry's
removal criteria. For completeness against the four authoritative rules: the
module's only edge (`daedalus.drafts` → `daedalus.kairos.drafts`) does not
touch `daedalus.kernel`, `daedalus.spine`, `daedalus.twin`, or
`daedalus.runtimes` as source or target, so none of the four rules currently
fire on it in either direction. No rule names `daedalus.drafts` by prefix.
Retiring it changes nothing about the boundary contract, since it has zero
measured importers to begin with — no edge disappears from any rule's
accounting.

## 7. Dead-code signals

**Registry removal-criteria audit** (`docs/architecture/shim-registry.json:35`:
*"Source, runtime-string, wheel, documentation, effect-registry, and pickle
audits show no caller for one supported release."*):

| Criterion | Verdict | Evidence |
| --- | --- | --- |
| (1) Source audit | **PASS** | Zero importers of `daedalus.drafts` (any Python import form) across 1459 git-tracked `.py` files. Commands above. |
| (2) Runtime-string audit | **PASS** | `git grep -n '"daedalus.drafts"' -- '*.py' '*.json' '*.md'` finds only the shim-registry entry and two hits inside a frozen point-in-time inventory snapshot (`docs/inventory/2026-08-21/...`), not a live registration. Checked `daedalus/spine/effect_boundary.py` specifically for a `"daedalus.drafts:..."` CLI target string (the pattern the task warned about for `daedalus.arch_memory`) — no hit; `daedalus.drafts` is not registered as an effect-boundary entrypoint target at all (only `daedalus.kairos.scheduler`-family and other flat modules are). |
| (3) Documentation audit | **PASS (as live doc), informational hits are archival** | No current `docs/*.md` (outside `docs/archive/`) references `daedalus/drafts.py` as a promised entry point. All doc hits are inside `docs/archive/swarm-2026-07-30/census/` (shard18.md, shard19.md, SYNTH-structure.md) — a dated historical census, not an active doc, and that census *itself* already recorded in `SYNTH-structure.md:321` that "no — live callers use `daedalus.kairos.drafts`". |
| (4) Wheel/packaging audit | **PASS (shipped, not a blocker)** | `pyproject.toml:81-83`: `[tool.setuptools.packages.find]` uses `include = ["daedalus*"]` with no per-module exclude, so `daedalus/drafts.py` is packaged into the wheel as part of the `daedalus` package tree. `[project.scripts]` (`pyproject.toml:77-79`) defines only `daedalus = daedalus.cli:main` and `daedalus-chip = daedalus.chip_design.cli:main` — no console-script points at `daedalus.drafts`. Being shipped is not itself a removal blocker (the criterion is about callers, not packaging inclusion), but it does mean removal requires no separate packaging-config edit beyond deleting the file — the wildcard include will stop matching it automatically. |
| (5) Effect-registry audit | **PASS** | `daedalus/spine/effect_boundary.py` (`EntrypointSpec` registry) has no entry with `target="daedalus.drafts:..."` or any anchor naming `daedalus.drafts`. The live `/api/drafts` HTTP surface and `daedalus drafts` CLI subcommand both route through `daedalus.kairos.drafts` directly (confirmed at `daedalus/cli.py:512`, `daedalus/interfaces/http/effects.py:10`, `daedalus/interfaces/http/read.py:8`), never through this shim. |
| (6) Pickle audit | **PASS** | `git grep -n "pickle" -- '*.py'` results contain no hit mentioning `draft`/`drafts` anywhere in the tracked tree — no serialized reference to this module path. |

Searched: all git-tracked `*.py`, `*.json`, `*.md` files (`git grep`, no
`--untracked`), `pyproject.toml`, `daedalus/spine/effect_boundary.py` in
full, `daedalus/cli.py` around line 512-515, git log for the file's history
(`ce5cb916` initial add as part of Era-3 drafts feature work, later
namespaced into `daedalus.kairos.drafts` by `ccb17634` "refactor(kairos):
namespace and harden scheduler execution", which is when this flat file
became a pure compat re-export).

**Label: REGISTERED-SHIM.** Not CANDIDATE-DELETE — the registry's own
`removal_criteria` gate its deletion on a one-supported-release grace period
after all audits pass, and that release/grace-period decision is the owner's
to make, not something this static audit can itself close out. All six named
audits above resolve PASS at this revision (b3cc415b), which is the evidence
the registry asks for; it does not by itself constitute the "one supported
release" the criteria also require.
