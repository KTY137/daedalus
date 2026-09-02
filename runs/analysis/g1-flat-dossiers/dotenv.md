# daedalus/dotenv.py

## 1. Size and shape

153 lines (`wc -l` = 153). One class, three functions, one private helper:

- `class DotEnvRefused(RuntimeError)` — `daedalus/dotenv.py:49`
- `def _is_git_tracked(path: Path) -> bool` (private) — `:54`
- `def parse(text: str) -> dict[str, str]` — `:72`
- `def load(path: Path | None = None, *, override: bool = False) -> list[str]` — `:101`
- `def describe(path: Path | None = None) -> dict[str, object]` — `:138`

Module-level state: two constants computed at import time —
`ROOT = Path(__file__).resolve().parents[1]` (`:43`) and
`DEFAULT_ENV_PATH = ROOT / ".env"` (`:44`). Both are pure path
arithmetic (`Path.resolve()` touches the filesystem to normalize the
path but does not read `.env` itself); no file I/O, env reads, registry
mutation, or network access happens at import. `__all__` is declared at
`:46`. No singletons, no mutable module-level containers.

All actual I/O (`os.environ` mutation, `.env` file reads, `git
ls-files` subprocess calls) happens inside function bodies (`load`,
`describe`, `_is_git_tracked`), not at import time — consistent with
the module's own stated design.

## 2. What it does

`daedalus/dotenv.py` loads `KEY=value` pairs from a `.env` file into
`os.environ`, filling only gaps (a real exported environment variable
always wins, and presence — not truthiness — is the check, so a
deliberately-empty export is not silently overwritten). It refuses,
by raising `DotEnvRefused`, to load a `.env` file that is tracked by
git, on the reasoning that a committed secrets file is a leak already
in progress and loading it would make the leak convenient rather than
visible. `load()` and `describe()` never return or log the values
themselves — `load()` returns only the list of variable NAMES it set,
and `describe()` reports presence/tracked/keys metadata for `doctor`-style
status output, deliberately carrying no values.

## 3. Who imports it (MEASURED)

**TOTAL: 6 measured references** across all import forms plus one
string-patch reference, all restricted to git-tracked files.

Commands run:
```
git grep -n -E "from daedalus\.dotenv|from daedalus import[^;]*\bdotenv\b|import daedalus\.dotenv|from \.dotenv import|from \. import[^;]*\bdotenv\b|importlib\.import_module\([\"']daedalus\.dotenv" -- "*.py"
git grep -n "daedalus.dotenv" -- "*.py" "*.json" "*.md" "*.toml"
```

| Importer | Line | Form | MODULE-LEVEL / DEFERRED |
| --- | --- | --- | --- |
| `daedalus/cli.py` | `:1123` | `from .dotenv import DotEnvRefused, load as _load_dotenv` | **DEFERRED** — inside `main()`, executed as the very first effectful step, explicitly BEFORE `install_process_guard()` (comment at `:1118-1122` explains why: the guard's own config belongs in `.env`, so it must load first). This is the production CLI entrypoint. |
| `daedalus/loop.py` | `:1661` | `from .dotenv import DotEnvRefused, load as _load_dotenv` | **DEFERRED** — inside the loop CLI's `main()`-equivalent, deliberately placed after `begin_effect(...)` registers the process-guard-boundary effect but before argument parsing (comment `:1652-1660` explains the ordering: git tracking-check is itself a process spawn, so it must happen after the canonical process boundary is registered). |
| `tests/test_dotenv.py` | `:18` | `from daedalus.dotenv import DotEnvRefused, describe, load, parse` | MODULE-LEVEL, TEST-ONLY. 16 test functions (`grep -c "^def test_"` = 16). |
| `tools/audit_swarm.py` | `:53` | `from daedalus import dotenv` | MODULE-LEVEL. Actually invoked at `tools/audit_swarm.py:293` as `dotenv.load()`. |
| `tests/test_loop_bound_safety.py` | `:58` | `mock.patch("daedalus.dotenv.load")` | DEFERRED, TEST-ONLY, string-patch target (not a static import form, but a live runtime-string reference to the module path). |

Per-layer breakdown: 2 production callers (`daedalus/cli.py`,
`daedalus/loop.py` — both top-level CLI entrypoints, DEFERRED/function-scope),
1 tooling caller (`tools/audit_swarm.py`, MODULE-LEVEL), 2 test-only
references (`tests/test_dotenv.py` module-level import,
`tests/test_loop_bound_safety.py` deferred string-patch).

This differs from the task's stated cross-check count of 4 (`cli.py`,
`loop.py`, `tests/test_dotenv.py`, `tools/audit_swarm.py`) by one: I
additionally counted `tests/test_loop_bound_safety.py:58`
(`mock.patch("daedalus.dotenv.load")`), a bare-string reference to the
module path that an AST-only census would not see as an import edge
(it is a `mock.patch` target string, not an `import` statement) but is
a genuine, git-tracked, runtime reference to `daedalus.dotenv.load`.
I flag rather than silently reconcile: the AST census's 4 is correct
for import-statement forms; 6 is the total once the bare-string
`mock.patch` form specified in the task's own methodology (§3, "bare
string" form) is included.

`describe()` specifically (one of the three public functions) has
**zero** callers anywhere in the tracked tree —
`git grep -n "dotenv.describe"` returns nothing — despite the module's
own docstring stating it exists as "Report for `doctor`" (`:138-139`).
`daedalus/doctor.py` does not mention `dotenv` at all
(`git grep -n "dotenv" -- daedalus/doctor.py` → no output). See §7.

## 4. What it imports (MEASURED)

No `daedalus.*` imports at all. Full import list (`daedalus/dotenv.py:39-41`):
- `os` (stdlib)
- `subprocess` (stdlib)
- `pathlib.Path` (stdlib)

Zero third-party imports, zero intra-repo imports. This is a leaf
module with no upward or lateral dependency inside `daedalus/`.

## 5. Proposed destination

**foundation.** Confidence: **high**.

Argument from measured edges: `daedalus/dotenv.py` has zero `daedalus.*`
imports (§4) — it cannot violate any boundary rule regardless of where
it lands, since it imports nothing that could be forbidden. Its
callers are both of the CLI-layer process entrypoints
(`daedalus/cli.py`, `daedalus/loop.py`), invoked before any other
subsystem — including the budget/spend-guard installation
(`daedalus/budget.py`, itself a declared FOUNDATION module) — which
places it at the same "bottom of the stack, loaded first" position as
the already-declared foundation set (`atomic, budget, config,
limit_policy, primary_tree, sensitivity, storage`). It is a pure,
side-effect-contained, stdlib-only utility exactly like the other
foundation modules.

What would change my mind: if a future hierarchy packet defines a
narrower "process-bootstrap" or "environment" layer distinct from
foundation, `dotenv.py` (and its sibling `daedalus/env.py`, see below)
would belong there instead — but no such layer exists in the target
layout given in this task.

**No split boundary** — this is one coherent module (parse/load/describe
over one file format), not two things fused.

### Highest-value finding: a second, competing, less-safe .env loader already exists and is more widely used

`daedalus/env.py` (NOT one of my three assigned modules, but directly
relevant to this dossier's mandated shadowing question) is a **separate,
independently-implemented** `.env` loader with its own `_parse_env_line`,
its own `load_env()`, its own `ENV_PATH = ROOT / ".env"` constant — it
does **not** import or call anything in `daedalus/dotenv.py`
(`git grep -n "dotenv" -- daedalus/env.py` → no output). Critically,
`daedalus/env.py`'s `load_env()` has **no git-tracked-file refusal
check** — it will silently load and leak a git-tracked `.env` into
`os.environ`, exactly the failure mode `daedalus/dotenv.py`'s own
docstring exists to close (`daedalus/dotenv.py:20-24`, "rule 2").

Measured importers of `daedalus.env` (`git grep -n -E "from daedalus\.env|from \.env import" -- "*.py"`):
`daedalus/runtime_registry.py:25`, `daedalus/web_api.py:36`,
`scripts/daedalus_desktop_sidecar.py:103` (the packaged desktop
sidecar's `main()`, loaded before `daedalus.desktop_runtime` — see the
desktop_runtime dossier), `tests/test_web_api.py:21`,
`tools/funnel.py:70`, `tools/guarded_call.py:62`. That is **6 importers**
of the *unsafe* loader versus **2 production + 1 tooling** importer of
the *safe* one (§3) — the module with the security property has fewer
production callers than the module without it, and the desktop
sidecar's production entrypoint (`scripts/daedalus_desktop_sidecar.py`)
uses the unsafe one exclusively.

This is a duplicate-canonical-path finding under AGENTS.md §5 ("one
kernel... prefer wiring, consolidation, and deletion over a new
subsystem") and the plan's forbidden-directions list
(`docs/IKARUS_ARIADNE_MASTER_PLAN.md` §13, parallel paths). It is
**out of scope to fix** under this READ-ONLY task, but it is the
single highest-value fact in this dossier and I report it rather than
silently noting only the assigned file. Whether `daedalus.env` should be
retired in favor of `daedalus.dotenv` (or vice versa, or merged) is a
Work Packet decision, not something this static classification pass
should resolve.

## 6. Boundary-rule check after the move

**(a) Moved to `foundation`: would any of its own imports be refused?**
No. `daedalus/dotenv.py` imports only `os`, `subprocess`,
`pathlib.Path` (§4) — zero `daedalus.*` edges, so none of the four
rules in `docs/architecture/import-boundaries.json` can ever fire
against it regardless of source-prefix classification.

**(b) Does any current rule name this module by prefix?** No.
`git grep -n "dotenv" docs/architecture/import-boundaries.json` → no
output (also visually confirmed by reading the full file, §6 tables
above and the file content already retrieved). No rule mentions
`daedalus.dotenv` in any `source_prefixes`, `forbidden_target_prefixes`,
or `allowed_target_prefixes` list, so no move of this file changes any
rule's behavior.

**(c) If it lands in kernel/spine/twin: which flat imports would be
refused?** N/A for the actual proposed destination (foundation, not
kernel/spine/twin). For completeness: since it imports nothing under
`daedalus.*`, it would trivially satisfy even the strictest allowlist
(`twin-no-outer-layers`, `spine-no-outer-layers`,
`kernel-no-outer-layers`) if ever placed as a source under one of those
three — zero of its imports are `daedalus.*`, so zero could be refused.

**(d) Does any rule constrain `daedalus.interfaces` as a source?** No —
confirmed by reading all four rules; none uses `daedalus.interfaces` as
a `source_prefixes` entry. Not applicable to this module regardless,
since `foundation` (not `interfaces/*`) is the proposed destination and
this module has no CLI/HTTP/bridge/desktop surface of its own.

## 7. Dead-code signals

**Module-level label: LIVE.** `load()` is called at the top of both
production CLI entrypoints (`daedalus/cli.py:1123` inside `main()`,
`daedalus/loop.py:1661` inside its `main()`-equivalent), both
DEFERRED-but-executed on every CLI invocation, both explicitly ordered
relative to the spend-guard/effect-boundary machinery per inline
comments explaining why (`cli.py:1118-1122`, `loop.py:1652-1660`).
`parse()` is exercised indirectly through `load()`/`describe()` and
directly by `tests/test_dotenv.py`. This is not a dead-code candidate
for the module as a whole.

**Function-level exception: `describe()` is UNWIRED-WITH-PROMISED-READER.**
- Promised reader: the function's own docstring states
  `"""Report for \`doctor\`: whether a \`.env\` exists, ..."""`
  (`daedalus/dotenv.py:138-139`).
- Actual caller search: `git grep -n "dotenv.describe"` (tree-wide) →
  zero hits. `git grep -n "dotenv" -- daedalus/doctor.py` → zero hits —
  `daedalus/doctor.py` does not import or reference `dotenv` at all.
  `tests/test_dotenv.py` does import and test `describe` directly
  (module-level import at `:18`), so it is exercised by tests, but has
  no production caller anywhere, including the `doctor` command its own
  docstring names.
- Historical corroboration: `docs/archive/swarm-2026-07-30/census/shard17.md:261`
  and `shard18.md:238` independently recorded, over a month before this
  audit, `UNWIRED|daedalus/dotenv.py|describe function is defined but
  not called within this file` / same for its own presence check — a
  prior swarm census already flagged this as unwired, and it remains
  unwired at HEAD.
- Label: **UNWIRED-WITH-PROMISED-READER**, not CANDIDATE-DELETE — the
  promised reader (`doctor`) exists in the codebase
  (`daedalus/doctor.py`) and simply has not been wired to call it; this
  reads as an incomplete integration, not intentional removal-worthy
  code.

What I searched for a promised reader beyond the docstring: `pyproject.toml`
for `console_scripts`/`[project.scripts]` naming `dotenv` or `describe`
(`grep -n -i "dotenv" pyproject.toml` → no output — `dotenv` is not
declared as a dependency, script, or packaging entry anywhere in
`pyproject.toml`); `docs/architecture/shim-registry.json` for
membership (`daedalus.dotenv` does not appear — it is not a registered
shim, it is an original/canonical module); git log
(`git log --oneline --follow -- daedalus/dotenv.py`) shows two commits,
`68921f0f` ("feat(config,tooling): load .env, probe the bench's
compute, ship daedalus.mapping" — original introduction) and `3528f232`
("feat(budget): loopback is physics, declared trust still counts calls;
.env keys pinned suite-wide") — no commit removed a consumer of
`describe()`; it appears to have simply never been wired to `doctor`
since introduction.

### Dedicated shadowing verdict (mandated finding)

`python-dotenv` (the third-party PyPI package providing a top-level
`dotenv` module) is **not a declared dependency anywhere**:
`grep -n -i "dotenv" pyproject.toml` → no output (checked
`dependencies`, all `optional-dependencies` groups including `yaml`,
`math`, `polyglot`, `root`, `orchestration`, `test`); `git grep -n -i
"python-dotenv"` tree-wide → no output.

No file in the tracked tree performs a bare, top-level
`import dotenv` or `from dotenv import ...`:
`git grep -n -E "^\s*import dotenv\b|^\s*from dotenv import"` → no
output.

**Verdict: `daedalus/dotenv.py` does not currently shadow
`python-dotenv`, and cannot, under normal packaging.** `daedalus/dotenv.py`
is only ever reachable as the submodule `daedalus.dotenv` (via
`from daedalus.dotenv import ...` / `from .dotenv import ...` / `from
daedalus import dotenv`) — it occupies the `daedalus` package's
namespace, not the top-level `sys.path` namespace, so a hypothetical
bare `import dotenv` elsewhere in the tree would resolve to the
third-party package (if installed) regardless of `daedalus/dotenv.py`'s
existence; the two are only name-identical at the leaf, not at import
resolution. Shadowing could only occur in an unusual scenario the tree
does not exhibit today (e.g. code executed with `daedalus/` itself,
rather than its parent, on `sys.path`, so that `dotenv.py` becomes
top-level-importable) — no evidence of that setup was found (no
`sys.path.insert` targeting `daedalus/` itself, only `tools/audit_swarm.py:11`
inserting the repo ROOT, which puts `daedalus` — the package — on the
path, not `daedalus/` — the directory — which is the distinction that
matters here). This is a naming collision at the leaf-module-name level
only, not a live or latent shadowing bug; flagging it for awareness
(a person searching PyPI for "why doesn't `pip install python-dotenv`
give me this" could be confused) is reasonable, but no functional risk
was measured.
