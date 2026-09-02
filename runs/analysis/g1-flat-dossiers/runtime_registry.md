# `daedalus/runtime_registry.py`

Scoping note: every search below is restricted to `daedalus`, `tests`,
`tools` (via `git grep -- daedalus tests tools`, or `Grep path=`).
`.claude/worktrees/agent-*/` holds full copies of `daedalus/` and `tests/`
and was deliberately excluded to avoid double-counting importer sites.

## Identity

Absolute path: `C:/Users/Administrator/daedalus/daedalus/runtime_registry.py`
Line count: 501 (`wc -l`, confirmed 2026-09-02).
One sentence: a "CLI-first, API-ready" registry of runtime capability specs
(Claude Code CLI, Codex CLI, Ollama HTTP/CLI, Anthropic/OpenAI API) that
resolves executable paths portably, probes live availability, and exposes a
TTL-cached status surface for CLIs and interfaces.

## Importers (MEASURED)

Total unique importer sites found by this scope: **13** = 10 daedalus/ + 3
tests/ + 0 tools/, matching the lead's precomputed count exactly; **6 of the
10 daedalus/ sites are deferred (function-scope)**, also matching exactly.

daedalus/ (10 total; 4 module-level, 6 deferred):

- `daedalus/desktop_runtime.py:24` — `from . import runtime_registry` (module-level)
- `daedalus/ikarus_os.py:1158` — `from .runtime_registry import resolve_runtime_command` (deferred, inside the function enclosing line 1158)
- `daedalus/ikarus_os.py:1500` — `from .runtime_registry import resolve_runtime_command, runtime_subprocess_env` (deferred)
- `daedalus/ikarus_os.py:1580` — `from .runtime_registry import resolve_runtime_command, runtime_subprocess_env` (deferred)
- `daedalus/ikarus_os.py:1613` — `from .runtime_registry import resolve_runtime_command, runtime_subprocess_env` (deferred)
- `daedalus/ikarus_os.py:2003` — `from .runtime_registry import resolve_runtime_command, runtime_subprocess_env` (deferred)
- `daedalus/interfaces/http/effects.py:22` — `runtime_registry,` (part of a module-level import block)
- `daedalus/interfaces/http/read.py:16` — `runtime_registry,` (module-level import block)
- `daedalus/llm_client.py:181` — `from .runtime_registry import cached_runtime_status` (deferred, inside `_probe`, def at line 172)
- `daedalus/web_api.py:32` — `runtime_registry,` (module-level import block)

5 deferred sites are in `ikarus_os.py`, 1 in `llm_client.py` = 6 deferred,
matching the lead's figure exactly.

tests/ (3, all real module-level imports; other hits below are usages, not
imports, and are excluded):

- `tests/test_kernel_contracts.py:9` — `from daedalus.runtime_registry import RuntimeSpec`
- `tests/test_runtime_registry_portable.py:9` — `from daedalus import runtime_registry`
- `tests/test_web_api.py:17` — `runtime_registry,` (module-level import block)

Excluded as non-importer usages (mock.patch string targets, attribute access
through an already-imported module, or comments): `daedalus/desktop_runtime.py:963`
(`runtime_registry.resolve_runtime_command(...)`, uses the line-24 import);
`daedalus/interfaces/desktop/http.py:63,98,101` (`web_api.runtime_registry...`,
accesses it through `web_api`'s own import, not a separate import here);
`daedalus/kernel/contracts/canonical.py:2427` (a comment: "Conservative
adapter for `runtime_registry.RuntimeSpec` declarations"); and roughly a
dozen `mock.patch("daedalus.runtime_registry....")` / attribute-access hits
across `tests/test_desktop_runtime.py`, `tests/test_ikarus_context.py`,
`tests/test_ikarus_stream.py`, `tests/test_ikarus_runtime_role.py`,
`tests/test_wires.py`, `tests/runtimes/test_provider_invocation_resolution_review.py`,
`tests/runtimes/test_runtime_provider_recovery.py`, `tests/test_budget.py`
(a docstring-config table entry), and further lines in
`tests/test_runtime_registry_portable.py` and `tests/test_web_api.py` beyond
their one real import line each.

**Dynamic/string references searched and found:** searched
`importlib`/`__import__` combined with the module name, literal dotted
strings, and `pyproject.toml` console_scripts (only `daedalus` and
`daedalus-chip`, neither names this module). No `importlib.import_module` or
`__import__` reference to this module exists in scope. The module *itself*
is not a plugin/registry table target of any other module — it *is* the
registry (`RUNTIMES: tuple[RuntimeSpec, ...]`), consulted by callers via
normal attribute/function access, not dynamic dispatch.

## Imports (MEASURED)

**Module-level (file:line):**

stdlib (13):
- `json` — 9, `os` — 10, `platform` — 11, `shutil` — 12, `subprocess` — 13,
  `sys` — 14, `threading` — 15, `time` — 16, `urllib.error` — 17,
  `urllib.request` — 18, `collections.abc.Mapping` — 19,
  `dataclasses.asdict, dataclass` — 20, `datetime.datetime, timezone` — 21,
  `pathlib.Path` — 22, `typing.Any` — 23 (15 stdlib module-level import
  statements/targets across these lines)

daedalus.* (2):
- `daedalus/env.py` — line 25, `from .env import load_env`
- `daedalus/providers/ollama.py` — line 26, `from .providers.ollama import DEFAULT_HOST, DEFAULT_MODEL`

**Deferred / function-scope (file:line + enclosing function):**

daedalus.* (1):
- line 318, `from .providers.ollama import ollama_endpoint_admission,
  ollama_http_base_url`, inside `_ollama_http_status()` (def at line 315).

No third-party (non-stdlib, non-daedalus) imports anywhere in this file.
Total: 2 daedalus.* module-level + 1 daedalus.* deferred = 3 daedalus.*
imports; 15 stdlib module-level imports; 0 deferred stdlib; 0 third-party.

## What it does

`runtime_status()`/`cached_runtime_status()`/`all_status()` probe each
registered `RuntimeSpec` (Claude Code CLI, Codex CLI, Ollama HTTP/CLI,
Anthropic API, OpenAI API) for live availability — spawning `--version` for
CLIs, HTTP `GET /api/tags` for Ollama — and `resolve_runtime_command()`
portably locates each CLI binary via override env var, `PATH`,
platform-specific per-user install roots, and known editor-extension
payloads, all resolved against the *actual resolved path* rather than a bare
command name (a Windows `.CMD`-shim lesson documented inline at
`_run_version`). A TTL-based, per-runtime, lock-protected cache
(`cached_runtime_status`) exists purely to avoid re-launching every CLI on
every status poll while always stamping `measured_at`/`measured_age_s` so a
cached row is never presented as a fresher reading than it is. Size: 501
lines.

## Proposed destination

**Proposed: `orchestration`.**

The name suggests `daedalus.runtimes`, but **the name does not decide it**:
measured, zero files under `daedalus/runtimes/` import this module at any
scope (lead's AST sweep, independently reconfirmed: `git grep` over
`daedalus/runtimes daedalus/kernel daedalus/spine daedalus/twin` for all
five module names surfaces only one unrelated comment,
`daedalus/kernel/contracts/canonical.py:2427`). The measured importer graph
instead clusters entirely around orchestration/interfaces-tier consumers:
`ikarus_os.py` (5 of 13 sites, all deferred — the orchestration voice/chat
runtime), `llm_client.py` (1 deferred site — the explicitly orchestration
"vendor-neutral language-model client policy for Ikarus", master-plan §7),
`desktop_runtime.py` and `interfaces/http/{effects,read}.py` and
`web_api.py` (interfaces-tier consumers that *query* runtime status, they do
not define runtime capability). The tightest coupling is to `llm_client.py`,
which is itself destined for `orchestration` (see `llm_client.md`) and is
this module's sole in-package `daedalus.*`-adjacent conceptual peer for
"which model/runtime is currently usable" policy.

**Strongest counter-argument:** `interfaces/http/effects.py`,
`interfaces/http/read.py`, and `web_api.py` all import this module too, and
one could argue a shared leaf-utility with heavy interfaces-side consumption
belongs in `foundation` instead, so that both `orchestration` and every
`interfaces.*` package can depend on it without an interfaces->orchestration
edge. This loses on the measured evidence: the module is not a generic
primitive like `config`/`storage`/`atomic` (the layer-files' actual
`foundation`-shaped import set, per the lead's measurement) — it is
domain-specific provider/runtime discovery logic tightly coupled to
`daedalus.providers.ollama` (its only non-stdlib dependency, imported both
module-level and deferred) and to the exact provider IDs `llm_client.py`
selects among (`claude_code_cli`, `codex_cli`, `ollama_http`, `ollama_cli`).
An `interfaces.*` package importing `orchestration` for a status read is
architecturally unremarkable (orchestration/interfaces are not bound by the
four kernel/spine/twin/runtimes rules at all), so there is no boundary cost
to keeping it beside `llm_client`.

## Boundary-rule verdict after the move

Four rules by id (`kernel-no-outer-layers`, `runtimes-no-gates`,
`spine-no-outer-layers`, `twin-no-outer-layers`), both directions:

- **(b) inbound:** VACUOUSLY CLEAN, attributed to the lead's AST sweep: no
  file under `daedalus/kernel`, `daedalus/spine`, `daedalus/twin`,
  `daedalus/runtimes` imports any of the five dossier modules at any AST
  scope, and the complete flat-module import set of those 142 layer-files is
  `{budget, sensitivity, structcore, limit_policy, primary_tree, config,
  storage, atomic, mapping, offload, providers, resources}` —
  `runtime_registry` is not in it, despite `daedalus.providers` (a *sibling*
  package this module itself imports) being in that set. Independently
  reconfirmed: none of this module's 13 measured importer sites is under
  kernel/spine/twin/runtimes.
- **(a) outbound / `daedalus.gates` check:** this module's only daedalus.*
  imports are `.env` and `.providers.ollama` (module-level) and
  `.providers.ollama` again (deferred) — never `daedalus.gates`. Grep
  confirms directly: `git grep -n "daedalus.gates\|from \.gates\|from
  \.\.gates\|import gates" -- daedalus/runtime_registry.py` returns no
  matches. If hypothetically moved into `daedalus.runtimes`, rule
  `runtimes-no-gates` would still pass: **CLEAN**. (`daedalus.providers`
  itself is not forbidden by `runtimes-no-gates`, whose denylist names only
  `daedalus.gates`.)
- Because the proposed destination is `orchestration`, which is not a
  `source_prefixes` entry for any of the four rules
  (`docs/architecture/import-boundaries.json`), none of the four rules binds
  this module as a source after the move.

**One-line verdict: N-A-not-a-rule-source (destination `orchestration`); the
hypothetical `daedalus.runtimes` landing would also be CLEAN (no
`daedalus.gates` import at any scope).**

## Dead-code signals

Not dead: 13 measured importer sites, the highest of the five dossier
modules, spanning production orchestration (`ikarus_os.py`, `llm_client.py`),
interfaces (`desktop_runtime.py`, `interfaces/http/*`, `web_api.py`), and
tests. Docstring, quoted in full from lines 1–6:

> "CLI-first, API-ready runtime registry.
>
> Daedalus orchestration should depend on runtime capabilities, not on
> random subprocess calls scattered through the app. This registry exposes a
> stable status/test surface for CLIs today and API providers later."

The docstring's own claim — "Daedalus **orchestration** should depend on
runtime capabilities" — is independent textual support for the proposed
`orchestration` destination, not merely the module's own naming. All 6
deferred importer sites (5 in `ikarus_os.py`, 1 in `llm_client.py`) are
inside functions that perform real provider dispatch (resolving a CLI path
or checking cached status immediately before spawning/calling it), consistent
with lazy/plugin-style loading rather than cycle avoidance: `ikarus_os.py`
and `llm_client.py` both need this module only at the moment they are about
to act on a runtime decision, not at their own import time, and neither
module is imported *by* `runtime_registry.py` (no cycle exists to avoid —
confirmed by the 0-daedalus-imports-into-ikarus_os/llm_client fact above).
The chase-one-hop check on `ikarus_os.py`, `llm_client.py`,
`desktop_runtime.py`, and `web_api.py`/`interfaces/http/*` finds all of them
live: each has its own multi-site test coverage in `tests/` confirmed above
and elsewhere in this scoping sweep.

## Confidence

**High.** The 13/10/3/0/6 counts all match the lead's precomputed figures
exactly and were independently re-derived line-by-line from `git grep`
output, including correctly separating the 6 deferred `daedalus/` sites from
the 4 module-level ones. The destination argument is grounded in the
measured importer set (`ikarus_os`, `llm_client`, interfaces/`web_api`) and
the docstring's own "Daedalus orchestration" framing, not in the module's
`runtime_*` name.
