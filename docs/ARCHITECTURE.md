> **TOMBSTONE (2026-08-22).** Era-3 snapshot, kept as history at this path; the live architecture is [docs/architecture-narrative.md](architecture-narrative.md) + [docs/architecture-state.json](architecture-state.json), under [the master plan](IKARUS_ARIADNE_MASTER_PLAN.md). Era-3 context: [docs/ERA3_PLAN.md](ERA3_PLAN.md).

# Daedalus — Architecture

*A deep summary: what it is, how it's built, what it can do today, and what it's
meant to become. Current as of Era 3 (branch `feat/api-webapp-agent-os`, 230
tests green).*

---

## 1. What Daedalus is

**A dynamic agent space** you drive from **VS Code, a browser, chat, or the CLI**
— all over one shared file-bus state. You hand it a goal; it routes the work
across a **frontier lane** (Claude / Codex — the capable, trusted builders) and a
**free local bench** (Ollama), applies **fail-closed safety** at every step, and
**verifies every result on disk** before trusting it.

Two ideas sit under everything:

- **Frugal cascade.** Cheap/free models do what they reliably can (scoped edits,
  docstrings, reviews, bookkeeping); the expensive frontier lane does what only
  it can (architecture, multi-file features, anything risky). The free agents are
  most valuable running *constantly and cheaply* on the maintenance grind.
- **Trust nothing you didn't verify.** A model's self-report is never believed.
  Acceptance is gated on a real, on-disk content-hash change plus syntax/lint/
  test checks — or the write is rolled back and escalated.

The **name is the mandate**: *Ikarus* (the foreman) must not fly too high — he
runs only pre-cleared, low-risk work on the bench and bounces anything senior
back to *Adam*/Claude.

---

## 2. The layers (Python core is the single source of truth)

```
  Surfaces      VS Code webview  │  React webapp (apps/web)  │  CLI  │  chat/Codex
                        └──────────────┴───────── all speak to ────────┘
  Local API      daedalus/web_api.py  (stdlib HTTP; serves the built webapp too)
                        │  dashboard · hierarchy · control-plane · drafts · queue
  Orchestration  Ikarus (ikarus.py)  ── decompose → accept → dispatch (waves)
                        │
  Routing        router.route_task      (WHO: which specialist role)
                 provider_router         (WHERE: which lane, by sensitivity×risk)
                        │
  Execution      offload.py  ── the ONE seam that runs work + verifies + escalates
                        │
  Providers      ollama (local, write)  ·  claude_cli (trusted, write)  ·  deepseek (ext, advisory)
                        │
  Safety+Proof   sensitivity (policy/guards) · verifier (gates) · metrics · drafts
```

Everything above the core is a **client**. The webview and the webapp both render
`core.get_dashboard` (pinned identical by `tests/test_ui_contract.py`), so the
two UIs can't drift into two products.

---

## 3. How a task actually flows

1. **Decompose** (optional): `Ikarus.spawn` → `decompose` turns a goal into
   scoped subtasks (local model, deterministic per-path fallback).
2. **Route WHO** — `router.route_task(objective, paths, repo_root)` scores agent
   roles by `owns` (path match) + `triggers` (keyword). Roles live in the global
   `agents/*.json` and per-repo `<repo>/.agentenv/agents/*.json` (the repo's own
   crew — threaded through routing since Era 1).
3. **Route WHERE** — `provider_router.select_provider` decides the lane on two
   axes:
   - **data sensitivity** — may bytes leave the machine? (sensitive → local
     Ollama only, *never* an external API)
   - **change risk** — `low` → the free bench may *write*; `mid` → it may only
     *advise*; `high` write → stays on Claude.
   - a role that isn't `external_ok` never leaves the trusted lane (but may still
     do local *advisory* review).
4. **Execute + verify** — `offload()` is the single cascade:
   - fail-closed: **no live write without a loaded policy** (guards would be off).
   - snapshot repo → run the worker → snapshot again → diff = **disk ground
     truth** (`disk_changed`, surfaced to callers as `result["wrote"]`).
   - **verifier gate**: `did_work` (real change), `syntax`/`lint` for `.py`,
     parse for `.json`/`.yaml`, `jscheck`/`htmlcheck` for `.js`/`.html`, plus the
     project's own test suite when configured.
   - **pass** → accept (zero Claude tokens). **fail** → roll the write back and
     escalate; anything the rollback can't revert is surfaced as
     `dirty_unreverted` (never silently lost).
5. **Report** — a distilled result (who · what · verified `wrote` · action);
   advisory proposals are persisted as **drafts** for review.

---

## 4. The safety model (fail-closed everywhere)

- **Write-guard** (`sensitivity.path_write_blocked`): the local bench may never
  write device/vendor/secret/high-risk paths; it's confined to `repo_root`
  (traversal/symlink-checked) and only writes when the router granted write mode.
- **Egress guard** (`deny_content` / `classify_data`): sensitive content never
  goes to an untrusted external API; sensitive work is pinned to local Ollama.
- **Fail-closed defaults**: no policy → no live write; unknown lane →
  `local_only`; the guard is only "on" when a project policy is loaded.
- **Verification over trust**: acceptance needs a real disk change + passing
  gates; self-reported `files_changed` is ignored in favor of the snapshot diff.
- **Path-hardening**: draft ids (from CLI/URL) are stem-validated before touching
  the filesystem (`drafts._safe_path`).

---

## 5. Free vs frontier — who does what

| | **Free bench (Ollama)** | **Frontier (Claude / Codex)** |
|---|---|---|
| Cost | $0 (local) | metered |
| Trusted with IP | yes (local, no egress) | yes |
| Writes | scoped, low-risk, guarded, verified | anything, trusted |
| Best at | docstrings, notes, changelogs, reviews, scoped edits, **constant bookkeeping** | architecture, multi-file features, risk calls |
| Reality check | one 7B model (qwen2.5-coder) reliably does **full-file rewrites**, *not* tool-calls; single-file scoped (≤3 files, ≤24k chars) | the actual builder |

The point isn't "free replaces frontier" — it's **let the free agents eat the
cheap grind so frontier tokens go to what matters.** Benchmarks bear this out:
routine slice ~77% projected savings; a greenfield app build correctly stays
frontier (see `benchmark`, `docs/VALIDATION_RUN.md`).

---

## 6. Orchestration & concurrency

- **Ikarus** = orchestrator-worker (supervisor) pattern: a capable foreman
  decomposes and synthesizes; tiered workers do scoped pieces; a separate review
  pass follows integration.
- **Dispatch is sequential by default** — each live write is verified by a
  whole-repo snapshot diff, and concurrent same-repo runs would cross-attribute
  changes. **`parallel=True`** enables real concurrency *safely*: per-task
  path-scoped attribution + refusal to parallelize path-conflicting write-tasks
  (see `docs/PARALLEL_DISPATCH.md`). True multi-file throughput awaits
  per-runtime worktrees.

---

## 7. The API-first webapp (Agent OS)

`daedalus/web_api.py` (stdlib HTTP) exposes the core to any client and serves the
built React app (`apps/web/`):

- `GET /api/dashboard · /projects · /projects/{p}/hierarchy · /control-plane ·
  /providers/status · /runtimes/status · /env/status · /capabilities · /drafts`
- `POST /api/queue · /ikarus/chat · /drafts/{id}/apply|dismiss`
- `PUT /api/projects/{p}/team|autonomy|agents/{a}|categories/{c}`

**Secrets stay server-side**: `.env` loads into the process; the API only ever
returns `configured: true/false`, never key values. The webapp is an operational
cockpit (agent-network graph, inspector, Role Wheel, **Draft Inbox**, mission
feed, provider/env status), not a landing page.

---

## 8. Testing strategy — two tiers (answers "why mocks?")

- **Unit suite (mocked, 230 tests, ~10s, always green)** — tests the
  **mechanics**: routing, gates, rollback, attribution, path-hardening, UI
  contract, parallel concurrency (proven *deterministically* via an observed-
  concurrency counter, not wall-time). Deterministic and env-independent by
  design — real Ollama here would be slow, non-deterministic and weather-
  dependent.
- **Live self-test (`daedalus selftest`)** — tests the **capability**: a real
  qwen round-trip on a throwaway repo, asserting only model-agnostic facts (real
  byte change, still compiles, verifier accepted, zero Claude tokens). Repeatable,
  opt-in, skips cleanly when the bench is down. (Plus `benchmark --live` and the
  `sunny_garden` validation run for broader end-to-end proof.)

---

## 9. What it can do today

- Route + run scoped work across free/frontier lanes with fail-closed safety.
- Local **write mode** proven end-to-end (edit **and** create files), verified on
  disk, with rollback + escalation.
- Dynamic, per-project **agent rosters, categories, squads**; runtime CRUD via
  CLI/API/UI.
- **Advisory-apply loop**: free agents propose → drafts persist → review/apply
  hands a packet to the trusted lane (never auto-merges).
- **Safe opt-in parallelism**; honest token/cost **benchmarks**; a live
  **self-test**; an **API-first Agent OS** webapp + VS Code integration.

## 10. What it's meant to become

- **Multi-file feature builds** on the bench via per-runtime **git worktrees**
  (removes the single-file / disjoint-path limits).
- **Wave dependency graphs** (not just order) so independent work fans out while
  dependent work sequences.
- **A second, larger local model** on the review lane (Oracle's napkin) —
  benchmark whether critiques sharpen.
- **Draft Inbox → one-click apply** wired to the Claude lane; a running
  **watcher** so queued API tasks drain automatically.
- **Multiple runtimes / remote lanes** for real throughput; VSIX repackage so the
  webapp ships inside VS Code.

> North star: from any surface, spin up and configure agents, hand the crew a
> feature, watch frontier build (with the free bench assisting on everything
> cheap) — all visible, controllable, and *verified*.
