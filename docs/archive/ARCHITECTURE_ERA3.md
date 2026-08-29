# Archived: Daedalus Architecture — Era 3

> **Archived 2026-08-30.** This is a condensed archival record of the Era-3
> architecture formerly described at `docs/ARCHITECTURE.md`. It preserves the
> design intent, contracts and historical capability claims while removing
> obsolete operational detail. It describes `feat/api-webapp-agent-os` at the
> point where the old page reported 230 green tests; that claim is historical,
> not current evidence. The live architecture is
> [`../architecture-narrative.md`](../architecture-narrative.md) plus
> [`../architecture-state.json`](../architecture-state.json), under the
> [`Ikarus/Ariadne master plan`](../IKARUS_ARIADNE_MASTER_PLAN.md).

## 1. What Daedalus was in this snapshot

A dynamic agent space driven from VS Code, browser, chat, or CLI over shared
file-bus state. Work was routed across a frontier lane (Claude/Codex) and a free
local bench (Ollama), with fail-closed safety and on-disk verification before
acceptance.

Two ideas sat under the design:

- **Frugal cascade.** Cheap/free models perform scoped maintenance work while
  frontier models handle architecture, multi-file features, and risky changes.
- **Trust only verified work.** Model self-report is not sufficient; acceptance
  requires a real content-hash change plus syntax/lint/test checks, otherwise the
  change is rolled back and escalated.

## 2. Layers

```text
Surfaces       VS Code webview | React webapp | CLI | chat/Codex
Local API      daedalus/web_api.py
Orchestration  Ikarus (ikarus.py)
Routing        router.route_task + provider_router
Execution      offload.py
Providers      ollama | claude_cli | deepseek
Safety+Proof   sensitivity | verifier | metrics | drafts
```

The Python core was the single source of truth. Both UI surfaces consumed the
same dashboard contract.

## 3. Task flow

1. **Decompose:** `Ikarus.spawn` optionally turns a goal into scoped subtasks.
2. **Route WHO:** `router.route_task(...)` selects roles from built-in and
   per-repository agent registries.
3. **Route WHERE:** `provider_router.select_provider` selects a lane from data
   sensitivity and change risk. Sensitive bytes stay local; high-risk writes stay
   on the trusted frontier lane.
4. **Execute + verify:** `offload()` snapshots the repository, executes work,
   derives the actual disk diff, runs language/project gates, accepts a passing
   change or rolls back and escalates a failing one.
5. **Report:** persist a distilled result; advisory proposals become drafts.

## 4. Safety model

- Local writes are path-confined and policy-gated.
- Sensitive content is denied to untrusted external APIs.
- Missing policy fails closed for live writes.
- Acceptance is based on disk state, not model claims.
- Draft identifiers are path-hardened before filesystem access.

## 5. Free vs frontier lanes

| | Free bench (Ollama) | Frontier (Claude / Codex) |
|---|---|---|
| Cost | local | metered |
| Writes | scoped, low-risk, guarded | trusted/high-risk |
| Best fit | maintenance, review, bounded edits | architecture, broad/risky work |
| Snapshot limitation | one 7B model reliably did full-file rewrites, not tool-calls | primary builder |

The point of the free bench was to absorb cheap grind, not to replace the
frontier lane.

## 6. Orchestration and concurrency

Ikarus followed an orchestrator-worker pattern with a review pass after
integration. Dispatch was sequential by default because verification used
whole-repository snapshots. `parallel=True` permitted disjoint path-scoped work
and rejected conflicting write tasks. Multi-file throughput was expected to move
toward per-runtime worktrees.

## 7. API-first webapp snapshot

`daedalus/web_api.py` exposed dashboard, projects, hierarchy, control-plane,
provider/runtime status, environment status, capabilities, drafts, queue and
Ikarus-chat operations. Secrets stayed server-side; the API exposed only whether
credentials were configured.

Two UI surfaces existed in the snapshot: a themed cockpit in
`apps/web/src/cockpit/` and an older classic surface loaded lazily. Both consumed
the same API.

## 8. Testing strategy in Era 3

- **Unit suite:** mocked, deterministic mechanics for routing, gates, rollback,
  attribution, path-hardening, UI contracts and parallel behavior.
- **Live self-test:** real local-model round trip on a throwaway repository,
  requiring an actual byte change that still compiled and passed verification.

## 9. Capabilities claimed by the snapshot

- Scoped local/frontier routing with fail-closed safety.
- End-to-end local write mode with disk verification, rollback and escalation.
- Dynamic per-project agent rosters, categories and squads.
- Advisory drafts with reviewed application.
- Safe opt-in parallelism, benchmarks, live self-test, API-first webapp and VS
  Code integration.

## 10. Direction recorded by the snapshot

- Per-runtime worktrees for multi-file local builds.
- Wave dependency graphs.
- Larger local review models.
- One-click reviewed draft application.
- Multiple runtimes/remote lanes and VSIX packaging.

> Historical north star: from any surface, configure agents, hand the crew a
> feature, let frontier models build while the free bench assists on cheap work,
> and keep every step visible, controllable and verified.

## Historical references

- Era-3 plan: [`ERA3_PLAN.md`](ERA3_PLAN.md)
- Parallel dispatch: [`PARALLEL_DISPATCH.md`](PARALLEL_DISPATCH.md)
- Validation run: [`VALIDATION_RUN.md`](VALIDATION_RUN.md)
