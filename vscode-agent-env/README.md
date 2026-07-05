# Daedalus VS Code Extension

Thin VS Code cockpit for the `daedalus` harness. The extension keeps Ikarus,
Ollama, Claude, Codex, queues, and memory in the harness; it only gives VS Code
native controls.

## Features

- Project tree from `projects/*.json`
- Queue tree for `outbox/`, `inbox/`, `memory/`, and `runs/processed/`
- Start/stop the file bridge watcher
- Enqueue `local_only`, `auto`, or `claude` requests
- Run live Ikarus spawn for a selected project
- Status bar summary for pending queue and open TODOs

## Use

Open this folder in VS Code and run **Developer: Install Extension from
Location...**, selecting `vscode-agent-env`.

If the harness root is not auto-detected, set:

```json
{
  "daedalus.root": "C:\\Users\\nukei\\Desktop\\agent_env"
}
```
