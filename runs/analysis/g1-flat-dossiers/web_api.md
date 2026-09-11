# web_api

## Identity

`C:/Users/Administrator/daedalus/daedalus/web_api.py` — 1226 lines. It is the
process entrypoint and route-dispatch shell for Daedalus's local HTTP API: a
stdlib `http.server` server (`DaedalusHandler(BaseHTTPRequestHandler)` on
`ThreadingHTTPServer`), not a business-logic library merely named "api".

## Importers (MEASURED)

Scope note: searches were restricted to `daedalus/`, `tests/`, `tools/`
explicitly (`git grep -n "web_api" -- daedalus tests tools`, plus targeted
`grep -n` re-checks per file to separate real imports from string/comment
mentions), to avoid the `.claude/worktrees/agent-*/` full-repo-copy trap named
in the task.

**Real imports of `daedalus.web_api`, grouped by layer:**

- `daedalus/` (2): 1 flat, 1 in `interfaces/http/`
  - `daedalus/cli.py:1218` — deferred (function-scope, inside `main()`'s `elif cmd == "web":` branch): `from .web_api import main as m; m(rest)`. This is the `daedalus web` console-script route (`pyproject.toml` `[project.scripts] daedalus = "daedalus.cli:main"`).
  - `daedalus/interfaces/http/__init__.py:36` — dynamic: `import_module("daedalus.web_api")` inside `__getattr__`, used to lazily re-export `DaedalusHandler`, `run`, `main`, `_resolve_bind`, etc. as a **compatibility surface pointing *at* web_api**, not the other direction.
- `tests/` (15 files, 17 import statements — 11 module-level, 4 function-scope deferred, plus 2 more statements inside `test_web_api.py`):
  - `tests/interfaces/test_http_server_admission_owner.py:9` (module-level)
  - `tests/interfaces/test_http_sse_owner.py:11` (module-level)
  - `tests/interfaces/test_http_strangler_architecture.py:12` (module-level)
  - `tests/test_bridge_restart.py:45` (module-level)
  - `tests/test_cli_effect_boundary.py:610` (deferred, inside `test_web_api_main_refuses_fail_closed_before_binding`)
  - `tests/test_desktop_startup_nonce.py:10` (module-level)
  - `tests/test_project_registration.py:17` (module-level, `from daedalus import atomic, projects, web_api`)
  - `tests/test_project_row_rewrite.py:25` (module-level)
  - `tests/test_structcore_ignore.py:309` (deferred, function-scope)
  - `tests/test_ui_contract.py:16` (module-level)
  - `tests/test_ui_governance.py:35` (module-level)
  - `tests/test_web_api.py:18` (module-level, in the `from daedalus import (...)` block) + `:22` (`from daedalus.web_api import _json_safe`) + `:451` (deferred, function-scope, `DaedalusHandler`)
  - `tests/test_web_api_catalogue.py:30` (deferred, function-scope)
  - `tests/test_web_api_health.py:33` (module-level)
  - `tests/test_web_api_loop.py:40` (module-level)
- `tools/` (0 real static/deferred imports; 1 dynamic subprocess invocation): `tools/gui_check.py:201` — `("python -m daedalus.web_api (diagnostic fallback)", ["-m", "daedalus.web_api"])`, a `python -m` subprocess launch used as a fallback diagnostic path alongside the documented `-m daedalus.cli web`.

**Count: 2 real importers in `daedalus/`, 15 test files (17 statements) in `tests/`, 1 dynamic subprocess reference in `tools/`. Zero real Python `import`/`from import` statements found in `tools/`.**

**Dynamic/string references searched for and found** (`importlib`, `__import__`, bare `"daedalus.web_api"` strings, `pyproject.toml` scripts, subprocess `-m`):

- `daedalus/spine/effect_boundary.py` — **not an import**, but a load-bearing string identity: 4 `EntrypointSpec` rows carry `target="daedalus.web_api:..."` (`run`, `DaedalusHandler.do_POST`, `DaedalusHandler.do_PUT`, `main` under id `cli.web_api`), each paired with `GuardAnchor("daedalus.web_api:...", "<guard-fn>")` entries (lines ~222, 232, 242-243, 821-843). These are the registry's mechanically-checked pointers into this exact file/qualname.
- `daedalus/desktop_runtime.py:1246,1249` and `daedalus/interfaces/desktop/http.py` (~15 occurrences) — **not imports**: a parameter literally named `web_api: Any`, duck-typed, supplied by the caller. The actual import happens one hop away, in `scripts/daedalus_desktop_sidecar.py`.
- `daedalus/eval/tasks.py:169`, `daedalus/eval/tier2.py:40`, `daedalus/eval/baseline.json:50` — `"target": "daedalus/web_api.py"` as eval-task fixture data (a comprehension/read task about the file), not an import.
- `daedalus/ikarus_chat.py:44`, `conversation.py`, `loop.py`, `mapping/inventory.py`, `mapping/reach.py`, `sensitivity.py`, `wiki/vault.py` — docstring/comment mentions only.
- `tests/contracts/test_spine_outer_ports.py:91` — `"daedalus.web_api"` inside a tuple of "outer" module prefixes a spine-adjacent contract test asserts must not be imported — this mirrors (does not duplicate) the `spine-no-outer-layers` denylist entry in `import-boundaries.json`.
- `tests/kernel/test_kernel_lazy_facade.py:180` — `"import daedalus.web_api as web_api\n"` is a **string literal building synthetic test source**, not a real import of this test file.
- `tests/test_desktop_runtime.py`, `tests/test_desktop_strangler_architecture.py`, `tests/test_desktop_packaging.py` — `web_api = SimpleNamespace(...)` fakes, or `.read_text()` of the source as a string. **Not real imports** — flagged because they look like matches on a naive grep.

**Outside the stated scope but load-bearing (found because SPECIAL asked about the desktop shell):**

- `scripts/daedalus_desktop_sidecar.py:120` — `from daedalus import web_api`; line 123 `install_web_integration(web_api, manager)`; line 124 `web_api.main(argv)`. This script is PyInstaller-packaged (`tools/build_tauri_sidecar.py`, `--name daedalus-web-api`, `--onedir`) into the `daedalus-web-api(.exe)` sidecar that `apps/web/src-tauri/src/lib.rs:998-1020` (`spawn_backend`) launches with `--host 127.0.0.1 --port 8765` — matching `web_api.main`'s own `argparse` signature exactly. `apps/web/src-tauri/tauri.conf.json:8` and `capabilities/project-folder-dialog.json:8` both hardcode `http://127.0.0.1:8765`. `apps/web/src/api.ts` has no `8765`/`localhost` literal (it talks relative/same-origin to the Tauri-hosted server, not a separate constant).

## Imports (MEASURED)

**Module-level (lines 1-54), `daedalus.*` (18 statements):**
- `daedalus.interfaces.http.effects as http_effects` (16), `.read as http_read` (17), `.server as http_server` (18), `.sse as http_sse` (19)
- `.kairos.drafts` (21)
- `. import accelerators, agents_registry, categories, control_plane, conversation_requests, core, editor_context, hierarchy, ikarus_chat, runtime_registry` (22-33)
- `.bootstrap_prompt.claude_bootstrap_prompt` (34)
- `.context_plan.plan_context` (35)
- `.env.env_status, load_env` (36)
- `.projects.ProjectRegistrationError, ProjectRegistryUnavailable, ProjectRowNotFound, ProjectRowUpdateError, list_projects, register_project, resolve_repo_root` (37-45)
- `.file_bridge.stream_state` (46), `. import file_bridge` (47)
- `. import ikarus_os` (48)
- `.structcore.index.cached_index` (49), `.structcore.churn.co_change_pairs` (50), `.structcore.report.structure_summary` (51), `.structcore.slice.semantic_slice` (52), `.structcore.topology.spectral_partition` (53)
- `. import memory as memory_mod` (54)

**Module-level, stdlib/third-party (10 statements, all stdlib — no fastapi/flask/uvicorn/starlette found anywhere in the file):** `argparse` (4), `hmac` (5), `json` (6), `mimetypes` (7), `os` (8), `re` (9), `time` (10), `http.server.BaseHTTPRequestHandler, ThreadingHTTPServer` (11), `pathlib.Path` (12), `typing.Any` (13), `urllib.parse.parse_qs, unquote, urlparse` (14).

**Deferred/function-scope, `daedalus.*` (13 statements):**
- `.projects.load_project` — `_project_center` (72), `_project_ignore` (93), `_project_list` (119)
- `.spine.picker` — `_loop_queue` (314), `_loop_attempts` (396), `_loop_architecture` (465)
- `.spine.ledger.SpineLedger, default_db_path` — `_loop_attempts` (397)
- `. import progress as progress_mod` — `_task_snapshot` (669)
- `. import progress_sources` — `_task_snapshot` (670)
- `. import conversation as conv` — `_conversation_view` (863), `_dispatch_status_view` (908)
- `daedalus.spine.effect_boundary.GuardDecision` — `_bind_decision` (989)
- `daedalus.spine.effect_boundary.REGISTRY_BY_ID, begin_effect` — `DaedalusHandler.do_PUT` (1004), `DaedalusHandler.do_POST` (1026)
- `daedalus.spine.effect_boundary.REGISTRY_BY_ID, GuardDecision, begin_effect` — `main` (1198-1202)

**Deferred, stdlib (3 statements):** `pathlib.Path as _Path` — `_loop_attempts` (394), `_loop_architecture` (463); `dataclasses.asdict, is_dataclass` — `_dataclass_or_none` (848); `sys` — `main` (1183).

Totals: 18 module-level `daedalus.*` + 10 module-level stdlib = 28 module-level statements; 13 deferred `daedalus.*` + 3 deferred stdlib = 16 deferred statements. No third-party HTTP framework import anywhere — the server is entirely stdlib `http.server`.

## What it does

`web_api.py` is a stdlib `http.server`-based HTTP server (`DaedalusHandler` on `ThreadingHTTPServer`, no FastAPI/Flask/uvicorn) that serves the Daedalus Agent OS JSON API plus the built `apps/web/dist` static webapp, gating non-loopback binds behind a constant-time bearer-token check and CORS-locking to `http://127.0.0.1:5173`. Route parsing, read projections, mutation handling, and SSE delivery are already delegated to sibling modules under `daedalus/interfaces/http/{effects,read,server,sse}.py`; what remains here is the effect-boundary-registered guard anchors (`_resolve_bind`, `_authorized`, `begin_effect`), the self-improvement-loop read projections (`_loop_queue`/`_loop_attempts`/`_loop_architecture`), task/conversation snapshot views, and the `main()`/`run()` process entrypoint. It is the exact module the Tauri desktop shell's packaged `daedalus-web-api` sidecar executes on `127.0.0.1:8765`, and what `daedalus web` (CLI) and `python -m daedalus.web_api` (diagnostic fallback) both launch. Size: 1226 lines.

## Proposed destination

**`interfaces.http`.**

Argument: the measured evidence already points this direction on its own — `web_api.py` imports its own sibling package `daedalus.interfaces.http.{effects,read,server,sse}` for the bulk of route logic (lines 16-19), and that package's own `__init__.py` docstring explicitly frames itself as "HTTP compatibility surface for the Daedalus web API" whose "implementation modules ... own route parsing, read projections, mutations, SSE delivery, and host-bind admission" — i.e. the migration architecture for this exact module is already declared and half-executed; `web_api.py` is the one flat piece not yet inside the package. It is a genuine HTTP interface (stdlib `http.server`, real socket bind, real auth), not business logic misnamed "api" — confirmed by the total absence of a third-party web framework and the presence of `ThreadingHTTPServer`/bind/CORS/auth code.

Counter-argument: `interfaces/http/__init__.py`'s own docstring says, in so many words, "The registered effect targets intentionally remain in `daedalus.web_api`" — this is a **recorded, deliberate decision not to move it yet**, not an oversight. Four `EntrypointSpec` rows in `daedalus/spine/effect_boundary.py` hardcode `"daedalus.web_api:run"` / `"daedalus.web_api:DaedalusHandler.do_POST"` / `"...do_PUT"` / `"...main"` as string module:qualname targets, each paired with `GuardAnchor` strings pointing at the same dotted path, and at least two governance tests (`tests/interfaces/test_http_strangler_architecture.py:221-224`, `tests/interfaces/test_desktop_strangler_architecture.py`) assert other modules do **not** import `daedalus.web_api` directly and that these exact target strings resolve. This counter-argument does not survive as a reason to pick a *different* destination — it survives only as a reason the move is currently blocked (see next section and Dead-code signals).

## Boundary-rule verdict after the move

(a) **As SOURCE** — `daedalus.interfaces.http` is not a source prefix for any of the four rules (only `daedalus.kernel`, `daedalus.runtimes`, `daedalus.spine`, `daedalus.twin` are), so none of `kernel-no-outer-layers`, `runtimes-no-gates`, `spine-no-outer-layers`, `twin-no-outer-layers` constrain `web_api`'s own imports post-move. **N-A-not-a-rule-source** for all four, matching the task's stated semantics exactly.

(b) **As TARGET** — checked against every current real importer found above (`daedalus/cli.py`, `daedalus/interfaces/http/__init__.py`, plus the 15 test files and `scripts/daedalus_desktop_sidecar.py`): none live under `daedalus.kernel`, `daedalus.runtimes`, `daedalus.spine`, or `daedalus.twin`. So no rule fires on any *existing* edge. But `spine-no-outer-layers`'s `forbidden_target_prefixes` (import-boundaries.json line 88) explicitly names `"daedalus.web_api"` today — a prospective denylist entry (`runtimes-no-gates`/`twin`/`kernel` do not mention `web_api`). After the move, that string would refer to a module that no longer exists at that path; it would neither match nor protect against a future `daedalus.spine` → `daedalus.interfaces.http` edge unless updated in the same commit. No current violation exists (0 spine imports of web_api found), so this is a **maintenance hazard, not a live refusal**.

**Verdict: CLEAN (0 refusals in either direction today), but the move requires updating `spine-no-outer-layers.forbidden_target_prefixes` in `docs/architecture/import-boundaries.json` (replace/augment `"daedalus.web_api"` with the new `daedalus.interfaces.http` prefix) in the same commit, or that rule silently stops protecting against a spine→web edge.**

## Dead-code signals

Not applicable as a live concern — importer count is high (2 direct in `daedalus/`, 17 statements across 15 files in `tests/`, 1 dynamic in `tools/`, plus the CLI console-script and the Tauri desktop sidecar chain), so deletion is not a live question. Recorded for completeness: the module docstring — `"""Local HTTP API and static webapp host for Daedalus Agent OS."""` — promises exactly the readers found: a CLI (`daedalus web`), an external client (anything hitting `127.0.0.1:8765`), and a desktop shell (Tauri, confirmed via `lib.rs`/`tauri.conf.json`/the PyInstaller sidecar). All three promises are measured as true.

## Confidence

**High.** The destination call rests on measured, cross-checked evidence: the existing `daedalus/interfaces/http/` package's own docstring states the migration intent, the effect-boundary registry's string targets were read directly (not inferred), and the Tauri/PyInstaller chain was traced end-to-end from `lib.rs`'s `spawn_backend` through `tools/build_tauri_sidecar.py`'s PyInstaller invocation to `scripts/daedalus_desktop_sidecar.py`'s literal `web_api.main(argv)` call. The one thing that would raise confidence further is confirming whether any automated verifier actually re-parses `effect_boundary.py`'s `GuardAnchor`/`target` strings against live source (an AST anchor-checker analogous to `tools/architecture_boundaries.py`) — I found the registry and the governance tests that assert against it, but did not locate a dedicated anchor-resolution checker module to read its exact failure mode.
