# Daedalus

Standalone multi-agent harness for building apps across local repositories.

This lives outside `project_tct` on purpose: the orchestrator should be reusable
for any app repo and should not pollute application history with run logs or
agent-runtime experiments.

Design goals:

- central router, no free agent-to-agent chat
- stateless subagent execution
- pruned state instead of full conversation history
- strict structured reports
- local JSON run logs that are ignored by Git
- optional LangGraph adapter for durable production workflows

## Layout

| Path | Purpose |
|---|---|
| `agents/` | Agent role registry as JSON |
| `templates/` | Generic, project-neutral defaults copied into any repo (`agents/`, `agentenv.json`, `project.example.json`) |
| `daedalus/` | Python router, schemas, and runbook CLI |
| `runs/` | Local ignored run state |
| `outbox/` | Local Claude task requests |
| `inbox/` | Local Claude reports |
| `memory/` | Local ignored append-only memory and TODO recovery snapshot |
| `tests/` | Harness tests |

## Architecture layers

`daedalus` is now organized around **Ikarus Core** (`daedalus/core.py`), the
single project-aware facade used by the CLI, Mission Control, the file bridge,
and future chat/app clients. The layers are:

```text
VS Code / CLI / future chat
  -> daedalus.core       dashboard, queue, providers, squads, quality, actions
  -> file_bridge          outbox/inbox transport and watcher loop
  -> Ikarus/offload       routing, local bench dispatch, verifier gates
  -> providers            Ollama, Claude CLI, DeepSeek, future API providers
```

The file bus remains the compatibility backbone. Existing `outbox/*.json` and
`inbox/*.report.json` contracts are preserved.

## Quickstart

```powershell
cd C:\Users\nukei\Desktop\agent_env
python -m daedalus.runbook "Describe the change you want" --paths <your-repo>\path\to\file.py
python -m unittest discover tests
```

## Local write path

When `--live` is passed and a target repo's policy is loaded, Ollama writes real
files via full-file rewrite (`daedalus/providers/ollama.py::_run_rewrite`). Before
accepting the result, the verifier gate snapshots file content-hashes before and
after the run — it trusts ONLY real on-disk changes (`disk_changed`), not the
model's self-report. A write-mode task that produced no file changes fails the
gate and escalates to Claude. Post-write syntax checks (`.py`, `.json`, `.yaml`)
and optional project tests are then run before final acceptance.

## Use in any project

`daedalus` is template-driven -- point it at any repo without editing the
harness. The generic, project-neutral defaults live in `templates/`:

| Template | Purpose |
|---|---|
| `templates/agents/*.json` | Neutral agent roles: `generalist-dev`, `docs-dev`, `tests-dev`, `reviewer`, `qa-critic` |
| `templates/agentenv.json` | Starter per-repo policy (identical to what `daedalus init` writes) |
| `templates/project.example.json` | Documented example entry for `projects/<name>.json` |

Onboard a new repo in three steps:

```powershell
# 1. scaffold <your-repo>\.agentenv\agentenv.json and copy the generic agent
#    roles into <your-repo>\.agentenv\agents\ (existing files are never overwritten)
daedalus init <your-repo>

# 2. check the local bench is ready (Ollama / model / claude CLI on PATH)
daedalus doctor

# 3. route + run a task against your repo
python -m daedalus.runbook "Describe the change you want" --paths <your-repo>\path\to\file.py
```

Each repo can then tune its own `.agentenv/agents/*.json` roles and
`.agentenv/agentenv.json` write policy. When a `repo_root` is supplied, the
router prefers that repo's `.agentenv/agents/`, then the generic
`templates/agents/`, then the built-in `agents/`. To register a repo as a named
project, copy `templates/project.example.json` to `projects/<name>.json`, edit
it, and pass `--project <name>`.

## VS Code integration

Claude Code and Codex in VS Code always talk through the harness, never to
each other. The definitive request/report contract (JSON shapes, lane
semantics, directory flow) is [`docs/COMMS_PROTOCOL.md`](docs/COMMS_PROTOCOL.md).
Mission Control gets its backend state from `daedalus dashboard --json`, which
is backed by Ikarus Core rather than extension-side scraping.

### Native extension cockpit

The `vscode-agent-env/` folder contains a VS Code extension that makes the
team bus visible in the editor:

- **Daedalus Projects** tree: registered `projects/*.json`
- **Daedalus Queue** tree: `outbox/`, `inbox/`, `memory/`, `runs/processed/`
- commands for watcher start/stop, status, local-only/auto/Claude enqueue, and
  live Ikarus spawn
- status bar summary for pending queue items and open TODOs

Install from VS Code with **Developer: Install Extension from Location...** and
select `vscode-agent-env/`. If the harness root is not auto-detected, set:

```json
{
  "daedalus.root": "C:\\Users\\nukei\\Desktop\\agent_env"
}
```

Use `local_only` while Claude tokens are exhausted; it never falls through to
Claude.

### Mission Control v1

Mission Control is a tabbed VS Code dashboard for real-time visibility into
multi-agent orchestration, queue state, and resource health. Open it by clicking
the **Daedalus icon** in the Activity Bar or running **Daedalus: Open Dashboard**
from the command palette.

The five tabs are:

- **Overview**: project/provider/watcher/routing/enforcement health
- **Queue Timeline**: outbox/inbox/processed lanes with request status and outcomes
- **Agent Squads**: registered agents and their assigned model tiers
- **Model Resources**: installed Ollama models, disk usage, safe parallel capacity, and pulls to suggest
- **Quality Gates**: schema validation, local-only enforcement, fallback rate, and stale watcher warnings

Data is fetched live from the file bus (no persistent dashboard database):

```powershell
python -m daedalus.cli dashboard --project <name> --json
```

Safety first: writes and model pulls require explicit user confirm; `local_only`
tasks never fall through to Claude.

See [`docs/MISSION_CONTROL.md`](docs/MISSION_CONTROL.md) for full details.

Supported Claude/Codex integration is through durable repo instructions
(`CLAUDE.md` / `AGENTS.md`), CLI/API/provider paths, MCP-compatible tooling, the
file bus, and documented entry points such as Claude Code URI handoff where
available. The harness does not depend on brittle private chat-webview DOM
control.

`.vscode/tasks.json` ships ready-made tasks (Terminal -> Run Task):

- **Daedalus Bridge: watch** -- background watcher; must be running for queued requests to be answered
- **Daedalus Bridge: watch project** -- watcher with a prompted `projects/<name>.json` as the default repo
- **Daedalus: doctor / status / benchmark (dry)** -- bench health, bridge state, projected costs
- **Daedalus: list projects** -- prints names registered under `projects/*.json`
- **Daedalus Team: enqueue local-only / auto** -- queue a task for a prompted project
- **Daedalus: spawn (prompt for objective)** -- decompose an objective onto the local bench
- **Daedalus: run tests** -- `python -m unittest discover tests`

`daedalus init <repo>` also drops `CLAUDE.md` and `AGENTS.md` (from
`templates/`) into the target repo root -- the standing instructions that make
each tool route delegable work through the harness (existing files are never
overwritten).

## Example: project_tct

The commands below are the concrete `project_tct` setup. Swap the paths and the
`--project` name for your own repo.

Ask Claude for a structured second opinion:

```powershell
python -m daedalus.claude_bridge "Review the motor panel icon fix" --repo-root C:\Users\nukei\Desktop\project_tct --paths C:\Users\nukei\Desktop\project_tct\TCT_app\gui\motor_panel.py
```

Start the VS Code/Codex/Claude file bridge:

```powershell
python -m daedalus.file_bridge watch --repo-root C:\Users\nukei\Desktop\project_tct
```

Queue a request for the watcher:

```powershell
python -m daedalus.file_bridge enqueue "Review current root-cleanup diff" --project project_tct --paths C:\Users\nukei\Desktop\project_tct\.claude\AGENT_PROTOCOL.md
```

The watcher reads `outbox/*.json`, calls Claude, writes `inbox/*.report.json`,
and archives processed requests under `runs/processed/`.

Record a TODO manually:

```powershell
python -m daedalus.memory add "Claude hit token/session limit during UI rewrite" --todo "Recover motor_panel TODOs before continuing" --repo-root C:\Users\nukei\Desktop\project_tct
```

Check the whole local bridge:

```powershell
python -m daedalus.status --project project_tct
```

Check Claude token pressure without making a Claude request:

```powershell
python -m daedalus.token_monitor --project project_tct
```

The VS Code task can run this as a watcher. It reads local Claude JSONL logs,
writes `memory/token_status.local.json`, and records a TODO checkpoint when it
sees rate-limit events or high context pressure.

Prepare a normal chat request for the Codex/Claude workflow:

```powershell
python -m daedalus.orchestrate "Fix the motor panel icon helper" --project project_tct
```

This records durable memory, routes the task to the likely specialist, and queues
a Claude second-opinion request for the watcher.

Memory files:

```text
memory/events.local.jsonl   append-only local event log, ignored by Git
memory/todos.local.md       generated human-readable recovery snapshot, ignored by Git
```

## Operating Model

```text
user request
  -> router selects one agent
  -> orchestrator creates a minimal task brief
  -> agent returns a structured report
  -> orchestrator stores only summary, files, tests, risks, and todos
  -> next agent receives only the pruned state it needs
```

Rules:

- No agent receives the full chat transcript by default.
- No agent talks directly to another agent.
- Every agent is stateless across invocations.
- Every report must be short and structured.
- Reviewer and test gates run before commit or PR.
- Claude/Codex fallback policy is documented in `docs/FALLBACK.md`; either side
  can continue with memory and tests when the other is unavailable.
