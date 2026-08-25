# Daedalus

A multi-agent harness that routes work to the cheapest model that can be
*proven* to have done it correctly, and refuses to promote anything it cannot
prove.

Daedalus lives outside the repos it works on. That is deliberate: an
orchestrator that writes its run logs and agent experiments into an application's
history stops being reusable, and starts being a second codebase nobody owns.
Point it at any repo; it carries its own state.

**Start at [docs/STATUS.md](docs/STATUS.md)** — one page, no numbers of its own,
saying where the truth is today and what is still unsettled. From there it is
four more hops to everything: the plan, the narrative, the snapshot, the ADRs.

The long-horizon architecture and the dependency-gated delivery program live in
[Ikarus & Ariadne: Der Daedalus-Masterplan](docs/IKARUS_ARIADNE_MASTER_PLAN.md).
In that vocabulary **Ikarus** is the user-facing assistant and **Ariadne** is the
evolution engine; `forest-evolve` is a descriptive CLI surface, not a second
product identity.

## The rules that do not bend

- A central router picks one agent. There is no free agent-to-agent chat.
- Every subagent invocation is stateless.
- Downstream agents receive pruned state, never the full transcript.
- Reports are short and structured, or they are rejected.
- A number without provenance is not a result. Every figure this harness
  reports is stamped MEASURED, INHERITED, or ASSUMED.
- `present` and `unknown` are not passes. `daedalus health` exits non-zero on
  both, because "the code exists" has never been the same claim as "the code
  works".

## State of the tree

MEASURED 2026-08-25 by `daedalus map --check` against the working tree at
`2de997ef`. These are the *live* counts, not the committed snapshot — see the
provenance note below, which is the whole reason this section exists.

| | | |
|---|---:|---|
| Harness modules | 294 | tracked `.py` under `daedalus/`, across 21 subpackages |
| Tracked `.py`, whole tree | 1162 | harness plus tests, tools, scripts, experiments, recovery kits |
| Modules in the call graph | 1637 | everything `map` walks, tracked or not |
| Islands | 78 | present, but unreached from any entry point |
| Unreached | 115 | no inbound edge in the call graph |
| Shims | 8 | pure forwarding, no logic of their own |
| Test-only | 42 | reached exclusively from `tests/` |
| Unknown | 29 | parsed, unclassified |
| Doc-drift | 35 | documented names no code reads any more |
| Dark switches | 3 | env switch reachable but undocumented |
| Unparsable | 1 | |

7798 tests collected (MEASURED 2026-08-25, `pytest tests/ --collect-only`,
383s). `map --check` exits non-zero on **22 blocking items** at that revision.

Read the first row for how big the harness is; read the rest for what the graph
cannot currently justify. The gap between them is not a harness that grew
tenfold — the walk covers `experiments/`, `scripts/`, `docs/recovery/*.py` and
the vault's copies of those kits, and most of the new islands are one-shot
recovery scripts that were never meant to have an inbound edge.

**Provenance, and why it is not a formality.** `docs/architecture-state.json` is
a *snapshot*, stamped with the commit it was generated against. When that stamp
lags HEAD, `map --check` says so out loud and tells any consumer ranking work
out of it to treat it as untrusted. Numbers copied from a stale snapshot into
prose are how a document starts describing a system that no longer exists —
so read the live counts from `map --check`, not from the JSON, unless the
freshness line confirms they agree.

Right now the snapshot fails its own integrity check, and by more than a stale
stamp: it was generated against `94eb3515` while HEAD is `2de997ef`, its
`counts.modules` says 520 where its own module list holds 521, and the digest
written beside the mechanical lists no longer matches them — which is what a
hand-edited snapshot looks like [MEASURED 2026-08-25, `map --check`]. The
snapshot also records a different `.daedalusignore`, so a run today and the
baseline are not looking at the same tree and their green results are not the
same claim. Re-baselining it is a reviewed decision, not a docs edit.

The islands are not dead code by assumption — they are code the graph cannot
currently justify. `daedalus map --check` is the gate: it exits non-zero on a
new island, a vanished module, or drift between the mechanical half of the map
and the narrative half in `docs/architecture-narrative.md`. Each blocker has
exactly four honest resolutions: wire it, document it, delete it, or accept it
explicitly with a date and an owner.

## Layout

| Path | Purpose |
|---|---|
| `daedalus/` | The harness: router, providers, safety core, CLI, and the 21 subpackages below |
| `agents/` | Built-in agent role registry (JSON) |
| `templates/` | Project-neutral defaults copied into any repo (`agents/`, `agentenv.json`, `project.example.json`, `CLAUDE.md`, `AGENTS.md`) |
| `projects/` | Registered repos — one `<name>.json` per project, carrying its policy |
| `tests/` | Harness test suite |
| `docs/` | Architecture, protocol, decision records (`docs/adrs/`, one namespace), audit reports |
| `tools/` | Standalone scripts that are *not* part of the shipped package (`exclude`d in `pyproject.toml`) — distinct from `daedalus/tools/`, which is |
| `scripts/`, `experiments/` | One-shot operational scripts, and frozen research spikes (`experiments/forest_v2/`). Most of the graph's islands live here |
| `apps/`, `catalogue/`, `configs/` | Web/app surfaces, GUI catalogue, runtime configuration |
| `structcore-rs/` | Rust structural core |
| `vscode-agent-env/` | The VS Code extension (Mission Control) |
| `outbox/`, `inbox/`, `runs/`, `memory/` | The file bus and local run state. **Not** wholesale Git-ignored: `.gitignore` excludes the volatile parts (`runs/*.json`, `memory/*.local.*`, `runs/processed/`) while retained evidence is committed — 836 tracked files under `runs/`, 32 under `inbox/` [MEASURED 2026-08-25, `git ls-files`] |
| `.room/` | Cross-vendor shared transcript ("der Raum") |

The `daedalus` package ships 21 subpackages: `adapters`, `council`, `eval`,
`gates`, `gui`, `hooks`, `ignition`, `kairos`, `kernel`, `lanes`, `mapping`,
`memory`, `observe`, `providers`, `runs`, `runtimes`, `spine`, `structcore`,
`tools`, `twin`, `wiki`.

> Packaging is load-bearing here. `pyproject.toml` now *discovers* them
> (`[tool.setuptools.packages.find]`, `include = ["daedalus*"]`) instead of
> naming them one by one. The earlier explicit list is why that changed:
> `structcore`, `eval`, and `mapping` were each absent from a built wheel at
> some point, and the omission was invisible locally because every install on a
> dev box is editable. Discovery removes that particular trap, not the rule —
> `exclude` still drops `tests*` and `tools*`, and package data is still listed
> by hand. Verify with a real wheel, not with an import.

## Architecture layers

`daedalus/core.py` is the single project-aware facade. The CLI, Mission Control,
the file bridge, and future chat clients all enter through it:

```text
VS Code / CLI / web / future chat
  -> daedalus.core        dashboard, queue, providers, squads, quality, actions
  -> file_bridge          outbox/inbox transport and watcher loop
  -> ikarus / offload     routing, local bench dispatch, verifier gates
  -> providers            Ollama, Claude CLI, DeepSeek, Codex CLI
```

The file bus is the compatibility backbone. The `outbox/*.json` and
`inbox/*.report.json` contracts are preserved across every refactor.

## The three gates

These are independent, they read disjoint config fields, and **they have
different defaults**. Describing one with the other's rule is not a wording
problem — it has already produced a real hole (see
`daedalus/sensitivity.py::path_write_blocked`, where prose claiming an
allow-list left 8 of 12 supposedly-denied paths writable, including the file
that loads the policy).

| Gate | Question | Predicate | Default |
|---|---|---|---|
| **Data egress** | May these *bytes* leave for an untrusted API? | `classify_data` | **Fail-closed.** Not allow-listed ⇒ sensitive. |
| **Write confinement** | May a local writer put bytes on this path? | `path_write_blocked` | **Not fail-closed.** Empty `write_allow` ⇒ unconfined; only denylists apply. |
| **Change risk** | Is this high-blast-radius code? | risk classification | Gates whether a free model may do more than *review*. |

Policy is per-project config, not hardcoded. Generic defaults ship in
`daedalus/sensitivity.py`; project rules live under `projects/<name>.json` →
`"policy"` and are merged on top.

## Providers

| Provider | Runs | Writes | Trusted with IP | Notes |
|---|---|---|---|---|
| `claude_cli` | external (Claude CLI) | yes | yes | Senior lane; the backstop for `auto`/`local`. |
| `ollama` | local (no egress) | low-risk only | yes | The free bench; full-file rewrite + verifier gate. |
| `deepseek` | external API | no (advisory) | **no** | Non-sensitive content only; needs `DEEPSEEK_API_KEY`. |
| `codex_cli` | external (OpenAI Codex CLI) | legacy `auto` path only | **no** | Egress-gated. The forced `--lane codex` bridge is advisory-only until a verified worktree transaction exists. |

Use `local_only` while Claude tokens are exhausted — it never falls through to
Claude.

## Local write path

With `--live` and a loaded policy, Ollama writes real files via full-file
rewrite (`daedalus/providers/ollama.py::_run_rewrite`). The verifier gate
snapshots content hashes before and after and trusts **only** real on-disk
changes (`disk_changed`) — never the model's self-report. A write-mode task
that produced no file change fails the gate and escalates to Claude. Syntax
checks (`.py`, `.json`, `.yaml`) and optional project tests run before final
acceptance.

That asymmetry is the whole design: a weak model is cheap to run and expensive
to believe, so the harness spends its budget on verification rather than on a
bigger model.

## Quickstart — zero to first verified offload

```powershell
cd C:\Users\nukei\Desktop\agent_env

# 0. is the bench ready? (Ollama server + qwen2.5-coder + claude CLI)
python -m daedalus.cli doctor

# 1. scaffold your repo (.agentenv policy + agent roles; never overwrites)
python -m daedalus.cli init <your-repo>

# 2. one REAL round-trip proof: routes, writes, verifies on disk, cleans up
python -m daedalus.cli selftest

# 3. first offload (plan only; add --live to actually write)
python -m daedalus.cli offload "Add a docstring to <some function>" `
  --repo-root <your-repo> --paths path\to\file.py

# 4. the cockpit: local web API + Agent OS webapp
python -m daedalus.cli web        # -> http://127.0.0.1:8765
#   /                    the themed cockpit: the code map, Ikarus, decisions
#   /?surface=classic    the previous surface: dock, spaces, runtime panels
#   Themes (top right)   six built-in designs, all editable, forks on first edit

# sanity
python -m pytest tests/
```

## Command surface

Everything runs through one entry point. `daedalus <command> --help` for detail.

**Is it working?**
`doctor` · `status` · `health [--deep] [--json]` · `governance` · `drill` ·
`accelerators` · `models` · `metrics` · `selftest`

`health` and `governance` are the honest ones: they separate *working* from
*present-but-unexercised* from *degraded* from *unknown*, attach provenance to
every number, and exit non-zero rather than round up. `drill` trips every
operability control — promotion, spend ceiling, kill switch, gate escape,
damage bounding — and reports whether scheduling a shadow run would be
defensible. It never schedules anything.

**Do the work**
`offload` · `spawn` · `build` · `ikarus` · `context` · `dctx` · `review-diff` ·
`improve`

`improve` ranks the repo's own work by measurement; `--once` attempts the top
item in an isolated worktree and prints a patch for **human** review. It never
applies anything.

**Second opinions**
`council` · `canary` · `claude-crew` · `drafts`

`council` convenes the cross-vendor council over a patch or question and returns
every dissent verbatim. It is ADVISORY and promotes nothing. `--live` is
required to reach any vendor because it spends real money; `--dry-run` calls
nothing.

**Keep the map honest**
`map [--check]` · `bookkeeper update` · `project-memory` · `benchmark` ·
`tokens`

`tokens` reports what the session has burned — local Claude token usage, the
spend ledger, the intent spine — and is OBSERVATION ONLY. It reads the ledger
and decides nothing; the ceiling is enforced in `daedalus/budget.py`.

**Gate-0 evidence**
`fault-attestation issue|verify` · `fixture-fault-collect` ·
`fixture-fault-attestation issue|verify`

These are operator steps, deliberately separated from the drivers that produce
the evidence: the fault driver never calls the attestation command, so
*producing* evidence is not a way to produce *trust*. The live-host column and
the deterministic-fixture column have their own authority and their own key, and
neither issuer can sign the other's rows.

**Configuration**
`init` · `enforce` · `projects` · `agents` · `categories` · `squads` ·
`dashboard` · `watcher` · `web`

## Use in any project

Daedalus is template-driven — point it at a repo without editing the harness.

```powershell
# 1. scaffold <your-repo>\.agentenv\ (existing files are never overwritten)
daedalus init <your-repo>

# 2. check the bench
daedalus doctor

# 3. route + run
python -m daedalus.runbook "Describe the change" --paths <your-repo>\path\to\file.py
```

Role resolution order when `repo_root` is supplied: the repo's
`.agentenv/agents/`, then generic `templates/agents/`, then built-in `agents/`.
To register a repo as a named project, copy `templates/project.example.json` to
`projects/<name>.json`, edit it, and pass `--project <name>`.

`daedalus init` also drops `CLAUDE.md` and `AGENTS.md` into the target repo —
the standing instructions that make each tool route delegable work through the
harness.

## VS Code integration

Claude Code and Codex always talk *through* the harness, never to each other.
The request/report contract is [`docs/COMMS_PROTOCOL.md`](docs/COMMS_PROTOCOL.md).

`vscode-agent-env/` is a native extension providing **Mission Control**, a
tabbed dashboard: Overview, Queue Timeline, Agent Squads, Model Resources,
Quality Gates. It reads live from the file bus — there is no dashboard
database. Backend state comes from `daedalus dashboard --json`, backed by Ikarus
Core rather than extension-side scraping.

Install via **Developer: Install Extension from Location...** and select
`vscode-agent-env/`. If the harness root is not auto-detected:

```json
{ "daedalus.root": "C:\\Users\\nukei\\Desktop\\agent_env" }
```

Writes and model pulls require explicit confirmation.
[`docs/MISSION_CONTROL.md`](docs/MISSION_CONTROL.md) describes the tabbed
dashboard template, which is **not shipped**: `dashboardHtml` has no callers and
the doc carries a tombstone banner saying so. The live webview renders the web
app (`agentOsHtml`); read the doc as history, not as a feature list.

`.vscode/tasks.json` ships ready-made tasks (Terminal → Run Task) for the
watcher, doctor/status/benchmark, project listing, local-only and auto enqueue,
spawn, and the test suite.

The integration deliberately uses durable repo instructions, CLI/API paths,
MCP-compatible tooling, and the file bus. It does not depend on brittle private
chat-webview DOM control.

## The file bridge

```powershell
# watch (must be running for queued requests to be answered)
python -m daedalus.file_bridge watch --repo-root <your-repo>

# queue a request
python -m daedalus.file_bridge enqueue "<task>" --project <name> --paths <file>

# notice finished reports without polling
python -m daedalus.file_bridge status --project <name>
python -m daedalus.file_bridge mark-read --all
```

The watcher reads `outbox/*.json`, calls the lane, writes `inbox/*.report.json`,
and archives to `runs/processed/`. It appends one line per finished report to
`inbox/LATEST.log` — a single well-known path a file-watch can trigger on — and
writes a heartbeat to `runs/bridge_heartbeat.json` every loop. `daedalus doctor`
warns with the exact restart one-liner when the heartbeat goes stale (> 2 min)
or a task outlives the codex budget.

Codex-lane protocol: put full task briefs in a queue file inside the TARGET
repo — `docs/CODEX_QUEUE.md` is the conventional name, and it is a file the
target project creates, not one this repo ships (there has never been a
`docs/CODEX_QUEUE.md` here) — and enqueue a short pointer ("Execute task C9
from docs/CODEX_QUEUE.md"). Long inline objectives on `--lane codex` bounce, and
`enqueue` warns when an objective smells like an inline brief.

## Operating model

```text
user request
  -> router selects one agent
  -> orchestrator creates a minimal task brief
  -> agent returns a structured report
  -> orchestrator stores only summary, files, tests, risks, todos
  -> next agent receives only the pruned state it needs
```

Reviewer and test gates run before commit or PR. The Claude/Codex fallback
policy is in [`docs/FALLBACK.md`](docs/FALLBACK.md): either side can continue
with memory and tests when the other is unavailable.

Memory is append-only, and the `*.local.*` files specifically are Git-ignored:

```text
memory/events.local.jsonl   append-only local event log
memory/todos.local.md       generated human-readable recovery snapshot
```

That distinction is load-bearing and easy to get backwards. Local *state* is
ignored; retained *evidence* is committed. `runs/` is the clearest case — a
receipt that only ever existed on one machine is not evidence, so the receipts
are tracked and only the volatile artifacts are excluded. One consequence is
worth knowing before reading any architecture number: `runs/` currently carries
1109 Python modules, two thirds of everything `daedalus map` walks. See
`docs/ARCHITECTURE_BASELINE_20260825.md`.

## License

See [LICENSE](LICENSE).
