# daedalus/arch_memory.py

## 1. Size and shape

326 lines (`wc -l`). 1 class: `ArchMemory` (dataclass, `arch_memory.py:70-82`).
10 top-level functions: `_git` (61), `_package_roles` (85), `build` (109),
`save` (172), `load` (195), `render` (205), `_last_shown` (238),
`_remember_shown` (245), `render_delta` (249), `main` (305).

Module-level state: `ARCH_MEMORY_VERSION = "1"` (51), `MEMORY_REL_PATH =
"runs/arch_memory.json"` (52), `STATE_REL_PATH = "docs/architecture-state.json"`
(53), `MAX_LINES = 24` (57), `MAX_LINE_CHARS = 110` (58),
`LAST_SHOWN_REL_PATH = "runs/arch_memory.shown"` (232), `NEWLINE = chr(10)`
(235, named deliberately per the comment at 233-234 because an inlined
escape did not survive shell-quoting layers). No mutable singleton, no cache
decorator.

Module-level side effects at import time: **none**. No file reads/writes, no
`git` subprocess calls, no env reads happen at module scope — `_git()`,
`build()`, `save()`, `load()`, `render()`, `render_delta()` all defer their
I/O to call time, and `main()` (the only function that performs an effect
requiring the boundary registry) only runs under the `if __name__ ==
"__main__":` guard (`arch_memory.py:324-326`).

## 2. What it does

It compiles a small, hard-budgeted (`MAX_LINES = 24`, `MAX_LINE_CHARS = 110`)
architecture summary — freshness-vs-HEAD, per-package one-liners derived
from each package's own `__init__.py` docstring, islands, shims, doc-drift,
and an honest "not seen" line for what the underlying snapshot could not
resolve — built from `docs/architecture-state.json` plus the structcore
index (`build()`, `arch_memory.py:109-169`), and always via atomic publish
(`save()`, using `daedalus.atomic.write_text_atomic`) because a post-commit
hook writes it while a prompt hook may concurrently read it. `render_delta()`
is the actual hook-facing surface: it shows the full block on the first call
of a session and only the diff against a "last shown" cursor afterward, so a
repeated turn costs one line instead of the whole summary, and it hard-fails
if a caller tries to relocate that cursor outside the repository
(`arch_memory.py:265-271`). `main()` wires the CLI/build path through the
canonical effect-boundary registry (`cli.arch_memory`) rather than writing
files unguarded.

## 3. Who imports it (MEASURED)

Search covered `from daedalus.arch_memory import`, `from daedalus import
arch_memory`, `import daedalus.arch_memory`, `from .arch_memory import`,
`from . import arch_memory`, `importlib.import_module("daedalus.arch_memory")`,
and the bare string `"daedalus.arch_memory"`, across daedalus/, tests/,
tools/, apps/, docs/, .claude/. Several hits were not imports and are
excluded: docstring/comment mentions in `daedalus/atomic.py:19`,
`daedalus/spine/killswitch.py:1082`, `daedalus/hooks/_common.py:159`,
`tests/test_envelope_coverage.py:100`, `tests/test_deepseek_substitution_guard.py:7`;
path-string data in `daedalus/hooks/_tree.py:124,141` (excludes the
`runs/arch_memory.shown` file from tree-hash scope, not an import); and a
facade legend string entry in `daedalus/kernel/events/envelope.py:682-684`
describing the artifact `daedalus/arch_memory.py` for documentation purposes.
One further reference is a **registry string coupling, not a Python import**:
`daedalus/spine/effect_boundary.py:709-720` registers an effect-boundary
entry with `id="cli.arch_memory"` and `target="daedalus.arch_memory:main"`
plus a `GuardAnchor("daedalus.arch_memory:main", "begin_effect")` — this
names the module as a string for the effect-boundary/guard-anchor mechanism
that `arch_memory.main()` itself calls into (`arch_memory.py:313-317`), but
it is not an AST-visible import edge and the boundary checker (section 6)
would not see it either way.

**TOTAL real Python-import importer edges: 5** — 2 under `daedalus/`
(1 package, 1 outside daedalus/), 3 under `tests/`.

| Importer | Layer | Form |
| --- | --- | --- |
| `daedalus/hooks/events.py:203` (`from daedalus import arch_memory`) | hooks (existing package) | DEFERRED — inside `render_arch()` closure in `user_prompt()` |
| `tools/watchdog.py:440` (`from daedalus import arch_memory`) | tools/ (repo-level, outside daedalus/) | DEFERRED — inside `docs_drift()` |
| `tests/test_cli_effect_boundary.py:171` (`from daedalus.arch_memory import main`) | tests | DEFERRED — inside a test function |
| `tests/test_hooks_v2.py:554` (`from daedalus import arch_memory`) | tests | DEFERRED — inside a test function |
| `tests/test_hooks_review_20260825.py:17` (`from daedalus import arch_memory`) | tests | MODULE-LEVEL |

Plus the one non-AST registry string coupling noted above
(`daedalus/spine/effect_boundary.py:711,715`), which functions as a
production dependency on this module's `main` entrypoint even though a
static-import boundary checker cannot see it.

## 4. What it imports (MEASURED)

`from .atomic import write_text_atomic` — `arch_memory.py:49`, MODULE-LEVEL,
target layer **foundation** (declared FOUNDATION module).

Inside `main()` only (both DEFERRED, `arch_memory.py:310-311`):
- `from daedalus.budget import process_guard_boundary_decision` — target
  layer **foundation** (declared FOUNDATION module).
- `from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect`
  — target layer **spine**.

Also one deferred stdlib import inside `build()`: `from datetime import
datetime` (`arch_memory.py:167`) — stdlib, not counted above. Third-party:
none. Stdlib elsewhere: `json`, `subprocess`, `dataclasses.dataclass`,
`pathlib.Path`.

## 5. Proposed destination

**foundation** — confidence medium.

Its own dependency footprint is minimal and strictly downward: one
FOUNDATION module at module scope, one more FOUNDATION module and one spine
leaf (`spine.effect_boundary`, itself the canonical effect-registration
surface every effectful entrypoint plugs into) deferred inside `main()`
only. It holds no orchestration state, no mission/attempt/twin concepts, and
its purpose — a compressed, budget-capped, always-atomically-published
context artifact consumed by hooks and a drift-watchdog tool — is
infrastructure for *other* layers' agents to orient themselves, not a
product or orchestration behavior itself. This matches the profile of the
existing FOUNDATION set: broadly-read, narrowly-dependent, self-contained.

Alternative: it could be filed as its own `observe`-flavored concern (the
existing `daedalus/observe` package name suggests introspection/telemetry
is already a recognized concern), but the given target-layer list has no
"observe" slot, and by measured dependency shape (section 4) it fits
foundation's constraints (see 6) without friction. What would change my
mind: if `daedalus/hooks` (its only in-package production importer) is
itself later classified as orchestration/interfaces-adjacent and the
hierarchy packet wants introspection utilities to travel with their sole
caller rather than sit in a shared foundation tier, this module would move
with hooks instead.

## 6. Boundary-rule check after the move

(a) If moved to **foundation**: no rule names `foundation` as a
`source_prefixes` entry, so no rule applies to it as a source there. Its
own edges (section 4) are foundation→foundation and foundation→spine, which
is the same direction every existing FOUNDATION module already takes toward
`spine` implicitly (e.g. budget/atomic are both allowlisted *targets* from
kernel and spine, meaning spine already reads foundation — arch_memory
reading spine is the one directionally-interesting edge, and no rule
restricts what a foundation module may import).

(b) No rule names `daedalus.arch_memory` by prefix in any list. Nothing
changes there.

(c) Hypothetical placement in kernel/spine/twin, checked against each
ALLOWLIST using arch_memory's measured imports (`.atomic`,
`daedalus.budget`, `daedalus.spine.effect_boundary`):
  - **kernel** allowlist (`atomic, budget, config, limit_policy, offload,
    primary_tree, sensitivity, spine, storage, twin`): all three edges
    ALLOWED (`atomic`, `budget`, `spine` are each explicitly listed).
  - **spine** allowlist (`atomic, budget, config, kernel, limit_policy,
    mapping, sensitivity, structcore`): `atomic` and `budget` ALLOWED;
    `daedalus.spine.effect_boundary` is an intra-package self-import if
    arch_memory itself were spine, trivially fine.
  - **twin** allowlist (`kernel, spine, structcore`): the module-level
    `from .atomic import write_text_atomic` (`arch_memory.py:49`) is
    **REFUSED** — `atomic` is not in twin's allowlist — and the deferred
    `daedalus.budget` import inside `main()` (line 310) is **also REFUSED**
    for the same reason. Only the deferred `daedalus.spine.effect_boundary`
    import (line 311) would be permitted. This is concrete evidence against
    placing `arch_memory` under `twin`: two of its three edges, including
    its one module-level edge, would need the checker's allowlist widened
    or the module rewritten to avoid `atomic`/`budget` outright.

## 7. Dead-code signals

Not applicable — importer count is 5 (Python-import edges), not 0, plus a
production registry-string coupling from `daedalus/spine/effect_boundary.py`
that a static-import checker cannot see but that is a real runtime
dependency on `arch_memory.main`. 2 of the 5 AST-visible importers are
non-test production code (`daedalus/hooks/events.py`, `tools/watchdog.py`).
Also reachable directly as `python -m daedalus.arch_memory` (guarded by
`if __name__ == "__main__":`, `arch_memory.py:324-326`, calling `main()`
at line 325) and referenced by name in `daedalus/hooks/_common.py:159`'s
performance-budget docstring and `daedalus/spine/killswitch.py:1082`'s
atomic-publish enumeration. **Label: LIVE.**
