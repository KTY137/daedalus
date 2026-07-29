# Daedalus VS Code Extension

Thin VS Code cockpit for the `daedalus` harness. The extension keeps Ikarus,
Ollama, Claude, Codex, queues, and memory in the harness; it only gives VS Code
native controls.

## Features

- **Chat with Ikarus** (`Daedalus: Chat with Ikarus` / the Activity Bar "Ikarus" panel) — opens
  the Agent OS cockpit, which now opens chat-first. The extension iframes the real cockpit
  (`apps/web/`, served locally by `daedalus.cli web`); it is a window onto that app, not a second
  implementation of it. If the local backend isn't reachable yet, the panel says so plainly
  (checking / unknown / degraded / absent, with a Retry) instead of staying blank.
- "Ask Ikarus About This File" (editor right-click) — copies a suggested objective for the
  current file/selection to the clipboard and opens the chat panel.
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
