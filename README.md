# Agent Environment

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
| `agent_env/` | Python router, schemas, and runbook CLI |
| `runs/` | Local ignored run state |
| `outbox/` | Local Claude task requests |
| `inbox/` | Local Claude reports |
| `memory/` | Local ignored append-only memory and TODO recovery snapshot |
| `tests/` | Harness tests |

## Quickstart

```powershell
cd C:\Users\nukei\Desktop\agent_env
python -m agent_env.runbook "Describe the change you want" --paths <your-repo>\path\to\file.py
python -m unittest discover tests
```

## Use in any project

`agent_env` is template-driven -- point it at any repo without editing the
harness. The generic, project-neutral defaults live in `templates/`:

| Template | Purpose |
|---|---|
| `templates/agents/*.json` | Neutral agent roles: `generalist-dev`, `docs-dev`, `tests-dev`, `reviewer`, `qa-critic` |
| `templates/agentenv.json` | Starter per-repo policy (identical to what `agentenv init` writes) |
| `templates/project.example.json` | Documented example entry for `projects/<name>.json` |

Onboard a new repo in three steps:

```powershell
# 1. scaffold <your-repo>\.agentenv\agentenv.json and copy the generic agent
#    roles into <your-repo>\.agentenv\agents\ (existing files are never overwritten)
agentenv init <your-repo>

# 2. check the local bench is ready (Ollama / model / claude CLI on PATH)
agentenv doctor

# 3. route + run a task against your repo
python -m agent_env.runbook "Describe the change you want" --paths <your-repo>\path\to\file.py
```

Each repo can then tune its own `.agentenv/agents/*.json` roles and
`.agentenv/agentenv.json` write policy. When a `repo_root` is supplied, the
router prefers that repo's `.agentenv/agents/`, then the generic
`templates/agents/`, then the built-in `agents/`. To register a repo as a named
project, copy `templates/project.example.json` to `projects/<name>.json`, edit
it, and pass `--project <name>`.

## Example: project_tct

The commands below are the concrete `project_tct` setup. Swap the paths and the
`--project` name for your own repo.

Ask Claude for a structured second opinion:

```powershell
python -m agent_env.claude_bridge "Review the motor panel icon fix" --repo-root C:\Users\nukei\Desktop\project_tct --paths C:\Users\nukei\Desktop\project_tct\TCT_app\gui\motor_panel.py
```

Start the VS Code/Codex/Claude file bridge:

```powershell
python -m agent_env.file_bridge watch --repo-root C:\Users\nukei\Desktop\project_tct
```

Queue a request for the watcher:

```powershell
python -m agent_env.file_bridge enqueue "Review current root-cleanup diff" --project project_tct --paths C:\Users\nukei\Desktop\project_tct\.claude\AGENT_PROTOCOL.md
```

The watcher reads `outbox/*.json`, calls Claude, writes `inbox/*.report.json`,
and archives processed requests under `runs/processed/`.

Record a TODO manually:

```powershell
python -m agent_env.memory add "Claude hit token/session limit during UI rewrite" --todo "Recover motor_panel TODOs before continuing" --repo-root C:\Users\nukei\Desktop\project_tct
```

Check the whole local bridge:

```powershell
python -m agent_env.status --project project_tct
```

Check Claude token pressure without making a Claude request:

```powershell
python -m agent_env.token_monitor --project project_tct
```

The VS Code task can run this as a watcher. It reads local Claude JSONL logs,
writes `memory/token_status.local.json`, and records a TODO checkpoint when it
sees rate-limit events or high context pressure.

Prepare a normal chat request for the Codex/Claude workflow:

```powershell
python -m agent_env.orchestrate "Fix the motor panel icon helper" --project project_tct
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
