# Daedalus VS Code Extension

Thin VS Code cockpit for the `daedalus` harness. The extension keeps Ikarus,
Ollama, Claude, Codex, queues, and memory in the harness; it only gives VS Code
native controls.

## Features

- **Chat with Ikarus** (`Daedalus: Chat with Ikarus` / the Activity Bar "Ikarus" panel) opens
  the Agent OS cockpit, which is chat-first. The extension iframes the local
  cockpit (`apps/web/`, served by `daedalus.interfaces.cli.entry web`); it is a window onto that
  app, not a second implementation. If the local backend is not reachable, the
  panel says so plainly (checking / unknown / degraded / absent, with Retry).
- **Ask Ikarus About This File** (editor right-click) captures an explicit
  editor selection through the fixed-loopback editor-context API and opens the
  chat panel with an opaque context reference; it never uses the clipboard.
- Project tree from `projects/*.json`
- Queue tree for `outbox/`, `inbox/`, `memory/`, and `runs/processed/`
- Start/stop the file bridge watcher
- Enqueue `local_only`, `auto`, or `claude` requests
- Run live Ikarus spawn for a selected project
- Status bar summary for pending queue and open TODOs

## Editor-context API contract

The extension is a thin UI adapter. It makes one fixed-loopback request after a
person invokes **Ask Ikarus About This File**:

```text
POST http://127.0.0.1:8765/api/editor/contexts
{
  project, source: "vscode" | "openvscode", path,
  range: { start_line, start_column, end_line, end_column }, selection
}
-> { ok: true, context: { context_ref: "opaque-id", ... } }
```

`path` is normalized with `/` and must remain below the selected, registered
project root. Ranges are 1-based and flat, matching the canonical API. The
selection limit is 12,000 characters: the adapter visibly refuses a larger
selection before it starts the backend or sends any bytes, rather than silently
truncating it. On success the cockpit receives only `project` and `context_ref`
as query parameters. The adapter never chooses a provider, queue lane, policy,
execution authority, or promotion action.

The backend contract is intentionally fail-closed: it must bind `context_ref`
to the registered project and its revision, enforce sensitivity/egress policy
before model use, and reject unknown, stale, foreign-project, or malformed
references. A backend without this route returns a visible refusal; the
extension does not fall back to clipboard text.

## Transient editor-session contract

At activation and after a project is selected, the adapter may make this
fixed-loopback, observation-only registration (it never starts the backend to
do so):

```text
POST http://127.0.0.1:8765/api/editor/sessions
{
  project, base_revision?, adapter: "vscode" | "openvscode",
  capabilities: ["reveal_location", "open_diff"]
}
-> { ok: true, session: { session_id, session_token, project, base_revision } }

GET http://127.0.0.1:8765/api/editor/sessions/{session_id}/events?after={sequence}&wait_s=25
X-Daedalus-Editor-Token: opaque-transient-session-token
```

`base_revision` is included only when `git rev-parse --verify HEAD` returns an
exact 40-hex revision without a shell. The token exists only in extension
memory and is never persisted, placed in a URL, copied, or shown in an error.
The session response is an API envelope: the adapter reads only
`body.session.{session_id,session_token,project,base_revision}` and refuses a
wrong project or a measured-revision mismatch. Each JSON long-poll envelope
contains `events`; every row has `{ sequence, command, payload, created_at }`.
Only these two command names can produce navigation:

```text
{ sequence, command: "reveal_location", payload: { path, range }, created_at }
{ sequence, command: "open_diff", payload: { path, range }, created_at }
```

The adapter resolves `payload.path` through the registered project root and
requires a real, in-root regular file plus an exact range. `open_diff` opens
only that path at the session's base revision versus the working-tree file.
Any absent or changed revision, wrong project, invalid path, malformed event,
rejected token, unsupported command, or non-increasing sequence is inert.
Reconnects reuse the in-memory token and `after` cursor only for GET
observation; they never renew a session or trigger queue, provider, policy,
filesystem-write, or shell behavior.

## Use

Open this folder in VS Code and run **Developer: Install Extension from
Location...**, selecting `vscode-agent-env`.

If the harness root is not auto-detected, set:

```json
{
  "daedalus.root": "C:\\Users\\nukei\\Desktop\\agent_env"
}
```
