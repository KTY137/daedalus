# daedalus/semantic_route.py

Scope note: all searches below are scoped to `daedalus/`, `tests/`, `tools/`
only (Grep `path=`). `.claude/worktrees/agent-*/` holds full duplicate copies
of `daedalus/` and `tests/` and was explicitly excluded to avoid double
counting.

## Identity

Absolute path: `C:/Users/Administrator/daedalus/daedalus/semantic_route.py`.
509 lines. Stage-1 semantic (embedding-based) task router: embeds an
objective and each agent role's example text via a local Ollama model and
picks the nearest role, falling back to the keyword router on any failure,
with full provenance on which mechanism actually produced the answer.

## Importers (MEASURED)

Total found: 8 sites (2 daedalus/ + 6 tests/ + 0 tools/), 3 deferred — matches
the lead's precomputed count exactly.

daedalus/ (2, 1 deferred):
- `daedalus/provider_router.py:33` — `from .semantic_route import FALLBACK, LATENT, semantic_route_explained` (module-level).
- `daedalus/health.py:1648` — `from .semantic_route import FALLBACK, semantic_route_explained` (deferred, inside a health-probe function `_p_islands`/probe helper).

tests/ (6 sites, 2 deferred, across 5 files):
- `tests/test_cascade.py:6` — `from daedalus import metrics, semantic_route, verifier` (module-level).
- `tests/test_health_surface.py:514` — `import daedalus.semantic_route as sr` (deferred, inside a test method).
- `tests/test_health_surface.py:525` — `import daedalus.semantic_route as sr` (deferred, inside a different test method).
- `tests/test_semantic_route_cold_start.py:53` — `from daedalus import semantic_route as sr` (module-level).
- `tests/test_semantic_route_live.py:30` — `from daedalus import semantic_route as sr` (module-level).
- `tests/test_semantic_route_wired.py:42` — `from daedalus import semantic_route as sr` (module-level).

Not counted as importers: `tests/conftest.py` (docstring prose about
`OLLAMA_HOST` isolation, no import) and `tests/test_skills.py:1025` (the
string `"daedalus/semantic_route.py"` inside a watched-files list, not an
import).

tools/: 0 matches for `semantic_route` anywhere under `tools/`.

Dynamic/string references searched: `python -m daedalus.semantic_route`
(zero hits, repo-wide), `importlib`/`__import__` near `semantic_route` (zero
hits), `pyproject.toml` console_scripts (no entry for this module). The only
string-literal references are `daedalus.health.CAPABILITY_MODULES` /
`production_importers("daedalus.semantic_route", ...)` in `daedalus/health.py:1633,1733`,
which is the module's own self-health probe, not a caller.

## Imports (MEASURED)

Module-level:
- `daedalus/semantic_route.py:66` — `from .providers.ollama import DEFAULT_HOST` → `daedalus.providers`.
- `daedalus/semantic_route.py:67` — `from .router import load_agents, route_task` → `daedalus.router`.
- stdlib: `json`, `logging`, `math`, `os`, `urllib.error`, `urllib.request`, `dataclasses`.

Deferred/function-scope: none. Every `daedalus.*` import in this file is
module-level; the outbound profile the lead measured (`{providers, router}`,
0 third-party, 0 deferred) is confirmed by direct read of the file.

## What it does

Embeds the task objective and each agent role's trigger/ownership text with a
local Ollama model and routes to the nearest role by cosine similarity,
treating a path already owned by a role as a harder signal that skips
embedding entirely. Any embedding failure (host down, cold-start timeout,
degenerate/mismatched vectors, ambiguous tie) falls back to the existing
keyword router in `daedalus.router`, and every route — latent or fallback —
returns a `LatentRouteResult` that states which mechanism actually fired
rather than silently returning a plausible-looking agent dict. 509 lines,
roughly half of which is provenance/failure-mode documentation for five
previously-measured silent-degradation bugs (cache poisoning, degenerate
vectors, dimension drift, a cold-model-read-as-dead-host timeout).

## Proposed destination

**orchestration.**

Argument: its only two `daedalus.*` dependencies are `daedalus.providers`
(a runtime/provider concern) and `daedalus.router` (the keyword task router),
and its only production caller is `daedalus/provider_router.py:33` at module
scope — task-routing-for-agent-orchestration is exactly the role the repo's
`ikarus_*` family (already classified orchestration by peers) plays. It
decides *which agent/role* handles a task, which is an orchestration
decision, not a kernel/spine/twin concern, and it has zero importers from any
of those three trust-boundary layers (see Boundary-rule verdict).

Strongest counter-argument: it could be filed under `runtimes` instead,
since it is fundamentally a provider-backend integration (talks HTTP to an
Ollama embeddings endpoint) and imports `daedalus.providers`. This loses
because the module's entire reason to exist is to make a *routing* decision
consumed by `provider_router.route_and_select` — the HTTP/embedding call is
an implementation detail of that decision, not the module's purpose; `router`
and `provider_router` are the closer siblings by both import graph and
semantic role, and both are orchestration-shaped (task-to-agent dispatch),
not provider-runtime-shaped (talk to a model API on behalf of a task).

## Boundary-rule verdict after the move

Landing in `orchestration` is not a rule source for any of the four rules
(`kernel-no-outer-layers`, `runtimes-no-gates`, `spine-no-outer-layers`,
`twin-no-outer-layers` all bind only `daedalus.kernel`, `daedalus.runtimes`,
`daedalus.spine`, `daedalus.twin` as sources), so all four rules are
**N-A-not-a-rule-source** for direction (a).

(b) reverse direction — does anything under `daedalus/kernel`, `daedalus/spine`,
`daedalus/twin`, `daedalus/runtimes` import `semantic_route`? **CLEAN**,
per the lead's positive-controlled measurement: no file under those four
prefixes imports any of the five packet modules, and the complete set of
flat-module imports those 142 layer-files make is `{budget, sensitivity,
structcore, limit_policy, primary_tree, config, storage, atomic, mapping,
offload, providers, resources}` — `semantic_route` is not in it. Attributed
to the lead's measurement, not independently re-derived here.

Hypothetical (a), if it *had* landed in a rule-source layer anyway: its two
imports are `daedalus.providers` (explicitly in `forbidden_target_prefixes`
for `kernel-no-outer-layers`, `spine-no-outer-layers`, and
`twin-no-outer-layers`) and `daedalus.router` (absent from all three rules'
`allowed_target_prefixes`, so refused by the non-empty-allowlist rule even
though it isn't separately denylisted). It does not import `daedalus.gates`
at any scope.

One-line verdict: **N-A-not-a-rule-source** (destination is orchestration);
would be **REFUSED** (`daedalus.providers` line 66, `daedalus.router` line 67)
under all three of kernel/spine/twin had it landed there instead.

## Dead-code signals

Not dead. `docs/FEATURE_INVENTORY.json:2284-2289` records
`"module": "daedalus/semantic_route.py", "status": "wired", "classification":
"reachable", "reason": "reached from cli:health"` — i.e. the inventory's own
static reachability analysis traces it from the `daedalus health` CLI path
(via `health.py`'s self-probe) in addition to the direct production caller
`provider_router.py:33`. The module's own docstring explicitly documents a
history of being *listed* as wired while being functionally dead in
production (0 of 5 live probes actually reached the latent path, per the
2026-07-29 postmortem in the module docstring, lines 40-53) — the exact
"docstring promises a reader but nothing proves it ran" trap this packet was
warned about — but that history is preserved as evidence *of a fixed bug*,
not a current defect: `test_semantic_route_wired.py` and
`test_semantic_route_live.py` now assert the real HTTP path end-to-end with
no mocks, specifically to prevent that regression from recurring silently.
No entry for `daedalus.semantic_route` in `docs/architecture/shim-registry.json`
(checked; 21 entries enumerated by a peer worker, none match). Chased one hop
on its daedalus/ importer: `provider_router.py:646` calls
`semantic_route_explained(...)` inside `route_and_select`, which is itself the
production task-routing entrypoint (confirmed live, not a second unwired
layer).

## Confidence

High. Importer/import counts match the lead's precomputed numbers exactly
(8 total, 3 deferred), the FEATURE_INVENTORY and the module's own test suite
(three dedicated live/wired/cold-start test files) independently corroborate
that it is wired and exercised, and the boundary-rule reasoning follows
directly from the quoted `import-boundaries.json` prefixes with no
inference required.
