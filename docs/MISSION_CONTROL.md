# Mission Control v1

Mission Control is a tabbed VS Code dashboard that provides real-time visibility into multi-agent orchestration, queue state, and resource health across all active projects.

## Opening Mission Control

### Via VS Code Activity Bar

Click the **Daedalus icon** in the VS Code Activity Bar (left sidebar) to open Mission Control.

### Via Command Palette

Press `Ctrl+Shift+P` and run:

```
Daedalus: Open Dashboard
```

Then select a registered project from the prompt.

## The Five Tabs

### Overview

Displays the health of your project's orchestration infrastructure:

- **Project status**: name, repo root, agents registered
- **Provider health**: Claude CLI readiness, Ollama connectivity, model readiness
- **Watcher state**: background bridge process status, last seen heartbeat
- **Routing policy**: write gates, enforcements, local-only fallback threshold
- **Enforcement gates**: schema validation, empty-report checks, local-only invariants

Use this tab to ensure all infrastructure is ready before queueing requests.

### Queue Timeline

Shows the complete lifecycle of agent requests across three lanes:

- **Outbox**: pending requests awaiting a watcher pickup (JSON request shape, enqueue time, assigned agent)
- **Inbox**: completed reports from Claude or local agents (status: success / error / timeout, summary, risk tags)
- **Processed**: archived requests with their outcomes (timestamped for recovery and audit trails)

Each request displays its:
- **Lane**: outbox, inbox, or processed
- **Status**: pending, success, error, timeout, or archived
- **Agent assigned**: which specialist handled the task
- **Timestamps**: created, started, completed
- **Summary**: brief result or error message

Use this tab to track request progress, debug failures, and understand queue backpressure.

### Agent Squads

Lists active agents and their current resource allocation:

- **Squad members**: all registered agents under their role category (generalist-dev, docs-dev, tests-dev, reviewer, qa-critic)
- **Per-agent model tier**: primary model for this agent (e.g., Ollama `mistral`, Claude `opus`)
- **Active state**: whether the agent has completed tasks in the last N hours

Use this tab to understand which specialists are available and which models they prefer.

### Model Resources

Displays installed Ollama models and safe capacity:

- **Installed models**: name, size (GB), disk space occupied
- **Safe parallel workers**: recommended maximum concurrent model loads based on available VRAM
- **Suggested pulls**: models not yet installed but referenced in agent configs
- **Storage pressure**: disk utilization to warn before reaching capacity

Use this tab to plan model pulls, understand capacity constraints, and diagnose out-of-memory issues.

### Quality Gates

Enforces data integrity and fallback safety:

- **Schema validation**: all reports match `daedalus/schemas.py` shapes; failed items listed
- **Empty-report checks**: no request returns a null report; counts of violations
- **Local-only invariants**: tasks run on local bench never route to Claude even if requested; enforcement count
- **Fallback rate**: percentage of requests that fell back to a secondary agent or model
- **Stale watchers**: background bridge processes that haven't reported in N minutes (warning threshold)

Use this tab to identify systemic issues (broken schemas, persistent local-only violations, high fallback rates) and tune enforcement policies.

## Backing Command

Mission Control reads its state from a single CLI command:

```powershell
python -m daedalus.cli dashboard --project <project-name> --json
```

Output format: JSON object with keys matching the five tabs above. This is called on tab switch or manual refresh; the backend is stateless and reads live from `outbox/`, `inbox/`, `runs/processed/`, and provider health checks.

If no project is specified, the CLI returns a summary across all registered projects.

## Safety Posture

Mission Control enforces a defensive-write policy to prevent unintended state changes:

- **Local-only enforcement**: tasks configured with `local_only: true` never request Claude tokens, even if a request escapes scope — the routing layer blocks at the provider level
- **Confirm-first model pulls**: suggesting a new Ollama model to download shows the resource cost (GB, estimated pull time) before any download begins; user must confirm
- **Inspect-before-write**: no automatic writes to `.agentenv/agentenv.json`, `projects/*.json`, or agent configs; all changes start as inspection + suggestions, requiring manual file edits or explicit confirm in the dashboard UI

This prevents token overages, unexpected disk consumption, and configuration drift.

## Integration with the File Bus

Mission Control is stateless and reads-through to the file bus:

- **Outbox scans** (`outbox/*.json`): detect pending requests and their metadata
- **Inbox reads** (`inbox/*.report.json`): ingest completed reports and quality scores
- **Processed archive** (`runs/processed/`): historical queries for auditing and recovery
- **Provider calls**: active health checks (Ollama `GET /api/tags`, Claude CLI `--version`, etc.)

There is no dashboard database. Refreshing Mission Control or switching projects always reflects the current state on disk.

## Keyboard & Search

Within each tab:

- **Search**: Ctrl+F to find requests by agent name, error message, or model
- **Sort**: click column headers to sort by date, status, or agent
- **Copy**: right-click a request to copy its JSON for manual inspection or replay

## Troubleshooting

### Mission Control won't open

1. Check `daedalus.root` in VS Code settings points to the harness folder
2. Verify `projects/<name>.json` exists for your project
3. Run `python -m daedalus.cli dashboard --project <name> --json` from PowerShell to test the backend

### Tab shows stale data

- Press the **Refresh** button in the dashboard header (or restart the tab)
- If the watcher is down, start it with **Daedalus Bridge: watch** from `.vscode/tasks.json`

### Model pull button is disabled

- Check `Model Resources` tab for disk space warnings
- Verify Ollama is running (`ollama serve` in a separate terminal or check system tray)

## See Also

- [`docs/COMMS_PROTOCOL.md`](COMMS_PROTOCOL.md) — JSON contract for outbox/inbox files
- [`docs/FALLBACK.md`](FALLBACK.md) — fallback policy and recovery workflows
- [`README.md`](../README.md) — quickstart and watcher setup
