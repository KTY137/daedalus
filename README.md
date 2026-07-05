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
| `agent_env/` | Python router, schemas, and runbook CLI |
| `runs/` | Local ignored run state |
| `outbox/` | Local Claude task requests |
| `inbox/` | Local Claude reports |
| `memory/` | Local ignored append-only memory and TODO recovery snapshot |
| `tests/` | Harness tests |

## Quickstart

```powershell
cd C:\Users\nukei\Desktop\agent_env
python -m agent_env.runbook "Improve the motor panel icons" --paths C:\Users\nukei\Desktop\project_tct\TCT_app\gui\motor_panel.py
python -m unittest discover tests
```

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
python -m agent_env.file_bridge enqueue "Review current root-cleanup diff" --repo-root C:\Users\nukei\Desktop\project_tct --paths C:\Users\nukei\Desktop\project_tct\.claude\AGENT_PROTOCOL.md
```

The watcher reads `outbox/*.json`, calls Claude, writes `inbox/*.report.json`,
and archives processed requests under `runs/processed/`.

Record a TODO manually:

```powershell
python -m agent_env.memory add "Claude hit token/session limit during UI rewrite" --todo "Recover motor_panel TODOs before continuing" --repo-root C:\Users\nukei\Desktop\project_tct
```

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
