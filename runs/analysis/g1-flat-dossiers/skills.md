# daedalus/skills.py — classification dossier

Scope note: every search below is restricted to `daedalus`, `tests`, `tools`
(via `git grep -- daedalus tests tools` and an AST scan seeded from
`git ls-files -- daedalus tests tools '*.py'`, 1536 tracked files matched by
that pathspec — git treats bare directory pathspecs as "everything under
here" so it also swept a handful of non-`.py` files, which the AST scan
skipped and reported as parse failures, not hits). `.claude/worktrees/agent-*/`
(full repo copies) was never touched, so nothing here is double-counted.

## Identity

`C:/Users/Administrator/daedalus/daedalus/skills.py`, 1059 lines. Parses an
Agent Skills `SKILL.md` file into a `Skill` dataclass, as inert text — nothing
in the module starts a process, imports `importlib`/`__import__`, or executes
anything it reads.

## Importers (MEASURED)

AST scan (module-level `import`/`from` statements resolving to `daedalus.skills`
or `.skills`/`..skills` relative to the source file) plus a `git grep` cross-check
gave the same 4 hits, 0 deferred:

| file:line | kind |
| --- | --- |
| `daedalus/tools/inventory.py:26` | `from .. import skills as skills_mod` — the 1 daedalus/ site |
| `tests/test_skills.py:39` | `from daedalus import skills` |
| `tests/test_skills.py:40` | `from daedalus.skills import (...)` |
| `tests/test_tools_vet.py:16` | `from daedalus import skills as skills_mod` |

That is 1 daedalus/ site + 3 tests/ sites (two of the three are two import
statements in the same test file, `test_skills.py`), matching the lead's
precomputed count exactly.

Dynamic/string references searched and found NONE: `git grep` for
`importlib.*skills`, `__import__.*skills`, the literal dotted strings
`"daedalus.skills"` / `'daedalus.skills'`, `-m daedalus.skills`, and any
`*_REGISTRY = {` table — zero matches. `pyproject.toml` `[project.scripts]`
defines only `daedalus = "daedalus.cli:main"` and `daedalus-chip = ...`;
neither points at this module.

**Disambiguation from the `.claude/skills/*/SKILL.md` files:** those are DATA
— e.g. `.claude/skills/council/SKILL.md` — the exact artifacts this module's
`discover()`/`load_skill()` would parse. Every grep above matched only Python
import syntax (`from daedalus.skills`, `from . import skills`, etc.), never
the bare word "skills", so the `.claude/skills/` directory tree (5+ skill
folders present) was never miscounted as an importer.

## Imports (MEASURED)

AST script run with `.venv/Scripts/python.exe`:

```
=== daedalus/skills.py ===
daedalus/skills.py:123 enclosing='<module>' :: from __future__ import annotations
daedalus/skills.py:125 enclosing='<module>' :: import hashlib
daedalus/skills.py:126 enclosing='<module>' :: import os
daedalus/skills.py:127 enclosing='<module>' :: import re
daedalus/skills.py:128 enclosing='<module>' :: import unicodedata
daedalus/skills.py:129 enclosing='<module>' :: from dataclasses import dataclass, field, fields
daedalus/skills.py:130 enclosing='<module>' :: from pathlib import Path
daedalus/skills.py:131 enclosing='<module>' :: from typing import Mapping, Sequence
```

**Module-level:** 7 imports (`hashlib`, `os`, `re`, `unicodedata`,
`dataclasses.{dataclass,field,fields}`, `pathlib.Path`,
`typing.{Mapping,Sequence}`) — all stdlib, zero `daedalus.*`.
**Deferred/function-scope:** 0 (confirmed both by the AST scan, which found no
hits inside any `enclosing` function, and a plain grep for indented
`import`/`from` lines in the file, which returned nothing).

## What it does

Parses one `SKILL.md` file's YAML-like frontmatter (via a small strict
scanner, not a YAML library) plus body into a `Skill` dataclass, reporting
malformed directories as `SkillDefect` rather than skipping them silently.
It also exposes `render_untrusted`/`render_catalog` helpers that fence a
skill's text before it could ever reach a model. 1059 lines, zero
dependencies beyond the stdlib.

## Proposed destination

**`foundation`.** Argument: the module has zero `daedalus.*` imports (measured
above), carries no lane/provider/host/path policy field by construction (a
pinned test enforces this), and its own docstring frames it as a pure format
layer deliberately kept out of routing/dispatch — the same "leaf, no domain
coupling" shape that defines the current foundation set
(`atomic/budget/config/limit_policy/primary_tree/sensitivity/storage`).
Strongest counter-argument: its only real consumer, `daedalus/tools/inventory.py`,
is dev-tooling/CLI-adjacent, which could argue for `interfaces.cli` instead.
It loses because classification should track the module's own nature (a
zero-dependency data-format parser reusable by orchestration, CLI, or a future
dispatch decision alike), not the sparseness of its current single consumer —
tying it to `interfaces.cli` today would falsely narrow a module the docstring
explicitly keeps generic.

## Boundary-rule verdict after the move

Four rules: `kernel-no-outer-layers`, `runtimes-no-gates`,
`spine-no-outer-layers`, `twin-no-outer-layers` — all bind only
`daedalus.kernel`/`daedalus.runtimes`/`daedalus.spine`/`daedalus.twin` as
SOURCE prefixes.

- **(b) target direction — CLEAN, vacuously**, per the lead's measurement: no
  file under `daedalus/kernel`, `daedalus/spine`, `daedalus/twin`, or
  `daedalus/runtimes` imports `daedalus.skills` at any AST scope (module-level
  or deferred), confirmed independently by this dossier's own AST scan (0
  hits in any of those four subtrees). **Foundation caveat:** the kernel and
  spine allowlists name flat module names (`daedalus.atomic`, `daedalus.budget`,
  ...); moving one of *those* allowlisted names to `daedalus.foundation.<name>`
  would drop it off the allowlist and refuse its kernel/spine importers. This
  does not bite `skills` because `skills` was never on either allowlist and no
  kernel/spine/twin/runtimes file imports it today — a future foundation
  migration packet for the *already-allowlisted* seven names needs the
  distinction, this module does not.
- **(a) source direction — N/A, not a rule source.** `daedalus.foundation` is
  not one of the four bound source prefixes, so moving `skills.py` there never
  makes it an evaluated SOURCE under any rule. Even hypothetically, it has no
  `daedalus.*` imports to refuse (see Imports above).

One-line verdict: **CLEAN (vacuous on (b); N/A-not-a-rule-source on (a)).**

## Dead-code signals

Zero importers this is not — it has 4 measured sites — but the count is low,
and the single production-path importer chases to nothing. `daedalus/tools/inventory.py`
(the 1 daedalus/ importer) is itself only reachable from
`tests/test_inventory_shadowing.py` (direct import) and from
`daedalus/tools/__init__.py`'s own `from .inventory import (...)`; nothing
outside `daedalus/tools/` and `tests/` imports the `daedalus.tools` package at
all (checked: `git grep "daedalus\.tools" -- daedalus tools` outside
`daedalus/tools/` itself returns nothing; `daedalus/cli.py` shells out to
`tools/operability_drill.py` as a subprocess rather than importing the
package). So **yes — the 1 daedalus/ importer is itself only test-reachable**;
the 3 test importers (2 files) are the module's only live readers, chased one
hop past `inventory.py`.

This matches the module's own docstring, which is explicit and does not
promise a reader: *"READ SURFACE ONLY... this module is deliberately NOT wired
into routing, the picker, or any dispatch path. Wiring it there is a separate
decision with its own preconditions; taking it silently is how this repo
acquired the subsystem ADR-002 later had to remove."* `pyproject.toml`
`[project.scripts]` names no entrypoint for it. This is a documented,
intentional "capability exists, not yet wired" state — not an accidental
orphan — so the finding is "currently test-only reachable by design," not
"dead."

## Confidence

**High.** The importer and import counts reproduce the lead's precomputed
numbers exactly via an independent AST scan, the dynamic-reference sweep
found nothing, and the one-hop dead-code chase (`inventory.py` →
`daedalus/tools/__init__.py` → no external importer) was verified directly
against `git grep`, not inferred. Would raise further only with a live
`grep --binary` sweep of non-`.py` config (already partially covered by the
pyproject/registry checks above) if a future packet adds a plugin-discovery
manifest.
