# daedalus/claude_detect.py

## 1. Size and shape

80 lines (`daedalus/claude_detect.py:1-81`).

- 0 classes, 2 functions: `parse_frontmatter` (23), `detect_claude_crew`
  (61).
- No module-level state, no singletons. Module-level constants only:
  compiled regex `_KEY_RE` (19) and tuple `_BLOCK_MARKERS` (20) — both pure,
  no I/O.
- No module-level side effects at import time: no file reads, no env reads,
  no registry mutation, no network, no path creation. All filesystem access
  (`Path(repo_root) / ".claude" / "agents"`, `d.glob("*.md")`,
  `path.read_text(...)`) happens only inside `detect_claude_crew`, at call
  time, guarded by `if d.is_dir():` (`claude_detect.py:66-67`) and a
  try/except around the read (`69-72`) that silently skips unreadable files.

## 2. What it does

`parse_frontmatter` is a dependency-free, best-effort parser for the
leading `---`/`---` YAML block of a `.claude/agents/<name>.md` file, reading
only top-level scalar keys and tolerating folded/literal block scalars
(`>`, `|`, etc.) without raising on unknown or complex YAML. `detect_claude_
crew` scans `<repo_root>/.claude/agents/*.md`, applies `parse_frontmatter`
to each file, and returns a list of `{name, description, model, tools,
source}` dicts plus a count. The module's docstring (1-12) frames this as
distinct from the harness's own `agents/*.json` roles: it detects Claude
Code's *own* subagent definitions (the "frontier crew that builds the app
itself") so Mission Control can surface both crews in one place.

## 3. Who imports it (MEASURED)

Searched `daedalus/`, `tests/`, `tools/`, `apps/`, `docs/`, `.claude/` for
all required import forms plus the bare string `"daedalus.claude_detect"`.
Command: `grep -rn "claude_detect" --include="*.py" daedalus tests tools
apps scripts docs .claude`.

TOTAL real importer files: **4** — 3 production, 1 test.

Production (all under `daedalus/`):

- `daedalus/control_plane.py:14` — `from .claude_detect import
  detect_claude_crew` — **MODULE-LEVEL**. `control_plane.py` is
  flat/unclassified, but its own real consumers are `daedalus/interfaces/
  http/effects.py:14` and `daedalus/interfaces/http/read.py:11,128`
  (`control_plane.unified_profiles(project)` — confirmed by reading
  `daedalus/interfaces/http/read.py:128`), and `daedalus/web_api.py:26` —
  i.e. `control_plane.py` is itself a data-projection layer that feeds the
  existing `interfaces/http` package.
- `daedalus/core.py:15` — `from .claude_detect import detect_claude_crew` —
  **MODULE-LEVEL**. `core.py` is SCC-owned (do not classify; edge
  recorded).
- `daedalus/cli.py:1022` — `from .claude_detect import detect_claude_crew` —
  **DEFERRED** (inside a CLI command function body, "List Claude Code
  subagents detected in a repo's .claude/agents/"). `cli.py` is
  flat/unclassified (destined for `interfaces/cli`).

Test (module-level):

- `tests/test_claude_detect.py:6` — `from daedalus import claude_detect as
  cd` — MODULE-LEVEL.

`tests/test_budget.py:931` has `"daedalus/claude_detect.py": "detects the
CLI, never invokes it"` — a data-literal annotation inside a spend/billable-
site inventory (confirming, in the test suite's own words, that this module
is read-only), not a Python import; not counted above.

Per-layer breakdown of the 3 production importers: SCC-owned = 1
(`core.py`), flat/unclassified feeding `interfaces/http` = 1
(`control_plane.py`), flat/unclassified feeding `interfaces/cli` = 1
(`cli.py`).

Vendored/duplicate copies excluded from the count (build artifacts / other
worktrees, not distinct call sites): `apps/web/src-tauri/backend/_internal/
daedalus/{cli.py,control_plane.py,core.py}` and its `target/{debug,
release}` mirrors, plus 5 `.claude/worktrees/agent-*/daedalus/{cli.py,
control_plane.py,core.py}` copies, all import identically to the 3
production sites above.

## 4. What it imports (MEASURED)

From `daedalus/claude_detect.py:15-17`: `re`, `pathlib.Path`,
`typing.Any` — **stdlib only**. Zero `daedalus.*` imports, module-level or
deferred. No third-party dependencies.

## 5. Proposed destination

**foundation**, at **medium confidence**; runner-up **interfaces/http**.

`daedalus/interfaces/bridge/` was checked per the packet's instruction and
is **not** an equivalent — it owns `cli`, `conversation`, `dispatch`,
`journal`, `projection`, `queue`, `watcher` for the headless file-bridge
(`daedalus/interfaces/bridge/__init__.py:1`: "File-bridge implementation
owners behind the stable legacy facade") — a different "bridge" concept
(Mission Control's own dispatch/journal transport) from detecting Claude
Code's `.claude/agents/*.md` subagent definitions. `daedalus/providers/`
was also checked and has no equivalent detector for Claude Code's own
subagent files. `claude_detect.py` is the sole, live implementation of this
specific detection — not a stale twin of anything under either existing
package.

Argument from measured edges: this module is a genuine leaf — zero
`daedalus.*` dependencies (§4) — and its 3 production consumers span two
different, already-existing `interfaces/*` surfaces plus one SCC module:
`control_plane.py` (feeds `interfaces/http/{effects,read}.py` and
`web_api.py`), `cli.py` (an `interfaces/cli`-destined command), and
`core.py` (SCC dashboard aggregation). A zero-dependency utility consumed
identically by two sibling `interfaces/*` sub-packages is the textbook
profile of the already-declared `foundation` tier (atomic, budget, config,
limit_policy, primary_tree, sensitivity, storage — all zero/near-zero-
dependency modules other layers freely depend on): placing it under either
`interfaces/http` or `interfaces/cli` specifically would create a needless
cross-sub-package dependency (the other interface would have to reach into
a sibling's package) for a module that has no interfaces-specific behavior
in it at all — it is pure frontmatter parsing plus a directory scan,
identical to what a `config`-tier reader does elsewhere in this
repository's `foundation` set.

Runner-up `interfaces/http`: two of the three production call sites
(`core.py`'s dashboard read and `control_plane.py`, which explicitly feeds
`interfaces/http`) ultimately serve the HTTP-backed Mission Control surface,
and the module's own docstring frames its purpose entirely in terms of
"Mission Control surfaces them" — a UI/product framing, not a generic infra
primitive, which argues against `foundation`'s existing "generic engine
machinery" character (atomic/budget/config/limit_policy/primary_tree/
sensitivity/storage are all domain-agnostic; this module is specifically
about Claude Code's own file convention).

Evidence that would change my mind: if `cli.py`'s deferred usage
(`claude_detect.py`'s only non-HTTP-adjacent consumer) is confirmed to be
retired or folded into the same dashboard payload `core.py`/`control_plane.
py` already build, that would remove the cross-`interfaces/*`-sub-package
argument against `interfaces/http` and make it the stronger pick. Conversely
if `router.py`/`agents_registry.py`-style flat modules (which `categories.py`
and `claude_bridge.py` both depend on) end up assigned to `foundation` too,
that would reinforce grouping `claude_detect.py` there for consistency.

## 6. Boundary-rule check after the move

(a) Would `claude_detect.py`'s own imports be refused under `foundation`?
No — it has zero `daedalus.*` imports (§4), so no rule can refuse anything
of its own regardless of destination layer.

(b) Does any current rule name `claude_detect`/`daedalus.claude_detect` by
prefix? No — confirmed by reading the full `import-boundaries.json`; none
of the 4 rules' prefix lists mention `claude_detect`. Nothing breaks or
unblocks specifically for this module.

(c) The allowlist enumeration applies to a `kernel`/`spine`/`twin`
destination. `foundation` is not one of those three, but is worth checking
for completeness since it is explicitly named as an ALLOWED target in all
three allowlists' style (e.g. `config`, a real foundation member, appears in
`kernel-no-outer-layers`, `spine-no-outer-layers`'s allowlists). If
`claude_detect.py` moves to `foundation`, and a future rule source-prefixed
on `daedalus.foundation` were ever added mirroring `kernel-no-outer-layers`,
it would trivially pass any such allowlist since it imports nothing
`daedalus.*` at all — this module is the easiest possible case for the
enumeration rule precisely because §4 found zero edges. If instead forced
directly into `kernel`/`spine`/`twin`: still zero refusals, for the same
reason (no imports to check against any allowlist).

## 7. Dead-code signals

Importers = 4 (3 production, 1 test), well above zero — **LIVE**. Verified
via §3's measured import list; also directly exercised by
`tests/test_claude_detect.py` (dedicated unit test for both
`parse_frontmatter` and `detect_claude_crew`), and indirectly reachable
through `tests/test_web_api.py`/`tests/test_project_row_rewrite.py`'s
`control_plane`-touching tests (not confirmed to exercise this exact
function per-test, but `control_plane.py` imports it at module level, so
any test importing `control_plane` transitively imports this module). No
candidate-delete signal found; no console_scripts/pyproject entrypoint
reference exists for it (checked `pyproject.toml`, no hits), and none is
needed since its readers are ordinary Python imports, not dynamic dispatch.
