# daedalus/bootstrap_prompt.py — hierarchy dossier

## 1. Size and shape

- 59 lines (`daedalus/bootstrap_prompt.py`, measured `wc -l`).
- 0 classes, 1 function: `claude_bootstrap_prompt(project: str) -> dict[str, Any]`
  (`bootstrap_prompt.py:13-59`).
- Module-level state: one module-level constant computed at import —
  `HARNESS_ROOT = Path(__file__).resolve().parents[1]` (`bootstrap_prompt.py:10`).
  Pure path arithmetic (no filesystem access), no singleton, no registry, no
  cache.
- Import-time side effects: none. No file I/O, no env read, no network, no
  path creation at module scope. The one function does call
  `load_project(project)` (`:14`) and `core.team_config(project)` (`:16`),
  both of which may perform I/O, but only when `claude_bootstrap_prompt` is
  actually called, never at import.

## 2. What it does

It builds a single Markdown-formatted "session bootstrap prompt" string
(`claude_bootstrap_prompt`, `bootstrap_prompt.py:13-59`) that orients an
external Claude Code runtime to a connected Daedalus project: it resolves the
project's repo root and active-agents list via `load_project` and
`core.team_config`, then interpolates the harness root, repo root, useful
`daedalus.cli`/`daedalus.file_bridge` commands, outbox/inbox/memory paths, the
Agent OS app URL, and the currently configured active agents into fixed
prose. It returns `{"project": project, "prompt": text}` — a plain data dict,
no side effects, no network call, no file write. It is pure text templating
over already-loaded project/team configuration; it contains no policy
decision, no effect boundary, and no guard call of its own.

## 3. Who imports it (MEASURED)

Command run: `Grep` for `from daedalus.bootstrap_prompt import|from daedalus import bootstrap_prompt|import daedalus\.bootstrap_prompt|from \. import bootstrap_prompt|from \.\.\.bootstrap_prompt import|daedalus\.bootstrap_prompt` across `daedalus/`, `tests/`, `tools/`, `apps/`, `scripts/`, `docs/`, `.claude/` (only `daedalus/` and `tests/` had hits).

TOTAL real Python import edges: **3**.

| importer | layer | scope |
|---|---|---|
| `daedalus/web_api.py:34` — `from .bootstrap_prompt import claude_bootstrap_prompt` | flat (`web_api.py` is a flat top-level module, not yet under `daedalus/interfaces/http/`) | MODULE-LEVEL |
| `daedalus/interfaces/http/read.py:18` — `from ...bootstrap_prompt import claude_bootstrap_prompt` (used at `read.py:131`, `bootstrap = claude_bootstrap_prompt(project)`) | interfaces/http (existing package) | MODULE-LEVEL |
| `tests/test_web_api.py:20` — `from daedalus.bootstrap_prompt import claude_bootstrap_prompt` | tests | MODULE-LEVEL |

Per-layer breakdown: interfaces/http = 1, flat = 1 (`web_api.py`), tests = 1.
No importers found in `tools/`, `apps/`, `scripts/`, `docs/`, `.claude/`.
No dynamic (`importlib.import_module`) or bare-string references found for
this module (unlike `benchmark`/`bookkeeper`, it has no CLI/effect-boundary
registry entry — it is a pure library function, never a registered
entrypoint).

## 4. What it imports (MEASURED)

Command run: `Grep '^from \.|^import' daedalus/bootstrap_prompt.py` (whole file is 59 lines, all imports are at module scope — no functions besides the one defined function contain further imports).

| import | file:line | scope | target layer |
|---|---|---|---|
| `from . import core` | `bootstrap_prompt.py:7` | MODULE-LEVEL | **SCC-owned** (`core` is one of the 11 modules in the 18-module SCC owned by another lead — not classified here, edge recorded per instructions) |
| `from .projects import load_project` | `bootstrap_prompt.py:8` | MODULE-LEVEL | flat (`daedalus/projects.py` exists; not declared foundation, not SCC, not a package) |

Third-party imports: none beyond stdlib (`pathlib.Path`, `typing.Any`).

## 5. Proposed destination

**interfaces/http** — confidence **medium**.

Argument from measured edges: two of the three real importers are HTTP-layer
consumers — `daedalus/interfaces/http/read.py` (already inside the
`interfaces/http` package, using the function to build an HTTP response
payload at `read.py:131`) and `daedalus/web_api.py` (the flat local-HTTP-API
module, which the module's own docstring class — "Local HTTP API and static
webapp host for Daedalus Agent OS" — matches). The only other consumer is its
own test. The module produces a plain string/dict payload with no policy
decision and no effect of its own, consistent with sitting under
`interfaces/http` as a small response-building helper alongside `read.py`,
rather than under `kernel`/`spine`/`twin`/`runtimes`/`foundation` (it touches
none of their contracts) or `orchestration` (it does no multi-step
coordination — it is single-shot text templating).

What would change my mind: `web_api.py` itself is still flat and not yet
moved under `daedalus/interfaces/http/`; if `web_api.py` is ultimately
classified somewhere other than `interfaces/http` (e.g. if it is judged too
broad — it also imports `kairos`, `file_bridge`, `ikarus_os`, `memory`, and
several other flat/SCC modules — to be a pure interfaces/http module), that
would weaken the case for co-locating `bootstrap_prompt.py` there. Since
`web_api.py` is out of scope for this dossier, medium rather than high
confidence.

## 6. Boundary-rule check after the move

None of the four documented rules (`kernel-no-outer-layers`,
`runtimes-no-gates`, `spine-no-outer-layers`, `twin-no-outer-layers`) have
`source_prefixes` matching `daedalus.interfaces`, so moving this module to
`interfaces/http` triggers **no rule check today**.

(a) Own-import refusal check if moved to `interfaces/http`: N/A — no
`interfaces-*` rule exists in the contract to refuse anything. (For the
record: both of its own imports, `daedalus.core` and `daedalus.projects`, are
module-level and would be visible to any future AST-walking rule.)

(b) Does a current rule name this module by prefix? No.
`daedalus.bootstrap_prompt` is not named in any `forbidden_target_prefixes`
list in the four existing rules. Nothing currently refuses importing it from
kernel/spine/twin (and nothing currently does import it from there — see
section 3, zero kernel/spine/twin importers measured).

(c) Allowlist exposure: N/A here since `interfaces/http` is not
`kernel`/`spine`/`twin` and has no allowlist rule. For contrast, if
`bootstrap_prompt.py` were hypothetically placed under `daedalus/spine/`
instead (not proposed — no evidence supports it), both of its imports would
be **refused** under `spine-no-outer-layers`'s allowlist
(`docs/architecture/import-boundaries.json` rule `spine-no-outer-layers`,
`allowed_target_prefixes`): `daedalus.core` is not on that allowlist (and
`daedalus.core` — as `daedalus.build`/`daedalus.file_bridge` are for the
same rule — is also explicitly named in the rule's `forbidden_target_prefixes`
list, so it would be a hard refusal, not just an allowlist omission), and
`daedalus.projects` is likewise absent from the allowlist and would be
refused by the allowlist-closure semantics documented in the rule file's own
rationale ("any flat module it imports that stays flat is REFUSED unless
named"). This is strong independent evidence against ever placing this
module under `spine`.

## 7. Dead-code signals

Importer count (real Python edges) = 3, all live: two production HTTP-layer
callers (`web_api.py:34` module-level, `interfaces/http/read.py:18`
module-level, actually invoked at `read.py:131`) and one direct test
(`test_web_api.py:20`, module-level). This is **LIVE**, not a dead-code
candidate — no further dead-code investigation (docstring-promised-reader
search, `pyproject.toml` entrypoint search, bare-string grep, git-log
consumer-removal check) is warranted given two confirmed, actively-invoked
production callers, but for completeness:

- Docstring: "Session bootstrap prompts for external runtimes."
  (`bootstrap_prompt.py:1`) — matches its confirmed HTTP-layer consumers,
  which expose it to external Claude Code runtimes via the local HTTP API.
- `pyproject.toml`: no `console_scripts` entry (checked; no match) — expected,
  since it is a library function, not a CLI entrypoint.
- Bare-string/registry references: none found — it has no
  `daedalus/spine/effect_boundary.py` `EntrypointSpec` entry (searched;
  no hits for `bootstrap_prompt` in that file), consistent with it being a
  pure, non-effectful helper rather than a registered door.
- `git log`: added 2026-07-06 (`1da0c0df`, "feat: API-first Agent OS — local
  web_api backend + React/Vite webapp (secure worktree)") in the same commit
  family as `web_api.py`; both call sites (`web_api.py`, `interfaces/http/read.py`)
  are present and current in the tracked tree.

Label: **LIVE**.
