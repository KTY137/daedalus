# Agent Communications Protocol (Phase 3)

The definitive contract for how Claude Code, Codex, and the local bench talk
to each other inside this harness. **All cross-tool traffic goes through the
file bridge** (`daedalus/file_bridge.py`) -- a JSON file queue processed by a
watcher. No tool ever talks to another tool directly.

`daedalus.core` is the shared Ikarus Core facade above this transport. CLI
commands, Mission Control, and future chat/app clients should call Core for
dashboard state, provider health, queue actions, squads, quality gates, and
enforcement. The bridge still owns only transport: enqueue, read request,
process request, write report, archive request.

## Transport: the file queue

| Directory | Role |
|---|---|
| `outbox/` | Requests waiting to be processed (`*.json`) |
| `inbox/` | Finished reports (`<request-stem>.report.json`) |
| `runs/processed/` | Archived request files after processing |

Flow for one request:

```text
enqueue -> outbox/<stamp>-<slug>.json
        -> watcher picks it up (processing happens in place; the request
           stays in outbox/ until it is done)
        -> inbox/<stamp>-<slug>.report.json  (the report)
        -> runs/processed/<stamp>-<slug>.json (request archived)
        -> memory/events.local.jsonl          (a bridge_report memory event)
```

Request filenames are `<UTC stamp>-<slug>.json` where the slug is the first 48
characters of the objective, lowercased, non-alphanumerics replaced with `-`.

### The watcher

```powershell
python -m daedalus.file_bridge watch [--repo-root <repo>] [--project <name>] [--interval-s 2.0]
```

On startup it prints `AGENT_BRIDGE_START`, the outbox path, then
`AGENT_BRIDGE_READY` (the VS Code task "Daedalus Bridge: watch" keys its
readiness on that line). It then polls `outbox/*.json` in sorted order every
`--interval-s` seconds (default 2.0). `--repo-root` / `--project` supply a
default `repo_root` for requests that omit one.

One-shot alternative: `python -m daedalus.file_bridge once` drains the
current outbox and exits.

## Request JSON (`outbox/*.json`)

Fields handled by `_read_request` / `process_request`:

| Field | Required | Default | Meaning |
|---|---|---|---|
| `objective` | yes | -- | What the specialist should do. A request without it is rejected. |
| `repo_root` | yes* | watcher's `--repo-root`/`--project` | Target repository. *May be omitted only if the watcher was started with a default; otherwise the request is rejected. |
| `paths` | no | `[]` | Relevant file paths (pruned by the token policy before prompting). |
| `model` | no | `"sonnet"` | Claude model used on the claude lane. |
| `lane` | no | `"auto"` | `"auto"` \| `"local"` \| `"local_only"` \| `"claude"` -- see lane semantics below. |
| `source` | no | `"unknown"` | Who queued the request: `"codex"` \| `"claude"` \| `"user"` \| `"ikarus"` \| `"unknown"`. |
| `strategy` | no | `"single"` | `"single"` routes one scoped task through Ikarus; `"spawn"` lets Ikarus decompose the objective and dispatch the local bench. |
| `project` | no | absent | Project name; honored on the local lane, where it is forwarded to `offload()` for policy resolution. |
| `timeout_s` | no | `300` | Subprocess timeout for the Claude CLI call (claude lane only). |

Example:

```json
{
  "objective": "Review current root-cleanup diff",
  "repo_root": "C:\\Users\\nukei\\Desktop\\project_tct",
  "paths": ["C:\\Users\\nukei\\Desktop\\project_tct\\README.md"],
  "model": "sonnet",
  "lane": "auto"
}
```

Enqueue helpers (both write this exact shape):

```powershell
python -m daedalus.file_bridge enqueue "<objective>" --repo-root <repo> --paths <p1> <p2> --model sonnet --lane auto
python -m daedalus.orchestrate "<task>" --repo-root <repo> --lane auto --source codex   # records memory + routes + enqueues
```

## Lane semantics

The `lane` field controls which executor the watcher may dispatch to:

- **`auto`** -- route the task via `provider_router.route_and_select` against a
  live availability snapshot (`doctor.check`). Local-capable work is handed to
  **Ikarus**, who routes/decomposes, dispatches the Ollama bench, and accepts
  only verified `offloaded` results. Anything else -- routing failure,
  ineligible task, bench down -- falls through to the Claude lane. Claude is
  always the backstop.
- **`local`** -- same Ikarus dispatch path as `auto`: prefer the bench, fall
  back to Claude if the bench is not eligible or not available.
- **`local_only`** -- try the local bench and never call Claude. If the bench
  cannot complete a verified offload, the request is reported as failed with
  `Claude fallback skipped`. Use this when Claude tokens are exhausted.
- **`claude`** -- skip offload entirely; always run on the trusted senior lane
  (`ask_claude`, the original behaviour). Use this for high-risk or
  judgment-heavy work.

## Report JSON (`inbox/*.report.json`)

Every report is an envelope:

| Field | Always | Meaning |
|---|---|---|
| `request` | yes | Echo of the (normalized) request payload. |
| `bridge_status` | yes | `"done"` or `"failed"`. |
| `lane` | yes | The lane that actually executed: `"local"` or `"claude"` (may differ from the requested lane after fallback). |
| `agent` | on success | Local lane: the bench `owner` that ran the task. Claude lane: the routed specialist role name. |
| `orchestrator` | local success | `"ikarus"` when the local bench handled the request. |
| `result` | local success | The raw dict returned by `offload()` (owner, verification, etc.). |
| `report` | claude success | The specialist's `agent_report_v1` (below). |
| `error` | on failure | Stringified exception; no `agent`/`report`/`result`. |

### `agent_report_v1` (the inner report on the Claude lane)

Validated by `daedalus.schemas.validate_report` -- exactly these keys, no
extras:

```json
{
  "status": "done | blocked | needs_review | failed",
  "summary": "string, max 600 characters",
  "files_changed": ["list of paths"],
  "tests_run": ["list of commands"],
  "risks": ["list of strings"],
  "todos": ["list of strings"],
  "handoff": {}
}
```

If the Claude CLI itself errors (rate limit, session limit), the bridge
converts it into a valid `status: "blocked"` report carrying
`handoff.api_error_status`, `handoff.session_id`, and the fallback decision --
consumers never need to parse raw CLI errors.

## Rules (non-negotiable)

1. **No agent-to-agent chat.** Claude Code never messages Codex (or the bench)
   directly, and vice versa. Everything goes `outbox/ -> inbox/`.
2. **Stateless specialists.** Every dispatched task carries its full brief
   (objective, repo_root, paths). Specialists get no chat history and must not
   ask another agent for context.
3. **Structured reports only.** Specialists return `agent_report_v1` JSON and
   nothing else; the orchestrator prunes state to summary/files/tests/risks/
   todos. Chatty or oversized reports are rejected by validation.
4. **Memory is the recovery channel.** Every processed report is appended to
   `memory/events.local.jsonl`; open TODOs surface in `memory/todos.local.md`.
   After an interruption, check the TODO snapshot before continuing.

## Who does what in VS Code

- **Claude Code** delegates via `python -m daedalus.orchestrate "<task>"
  --repo-root <repo> --source claude` (or `--strategy spawn` for decomposable objectives) and,
  when acting as a specialist, answers only with `agent_report_v1`.
- **Codex** queues work with `python -m daedalus.file_bridge enqueue ...
  --lane auto --source codex` and reads the answer from `inbox/`. Use
  `--lane local_only` when Claude must not be called.
- **Ikarus** is the master agent for the Ollama developer team: local-capable
  requests go through him, not directly to a provider. He may fan out subtasks
  with `strategy: "spawn"` and returns a consolidated assignment report.
- **The watcher** must be running for either to get answers: VS Code task
  "Daedalus Bridge: watch" (see `.vscode/tasks.json`).

## Supported IDE integration boundary

Daedalus coordinates Claude/Codex through supported surfaces: `AGENTS.md`,
`CLAUDE.md`, the file bus, CLI/API/provider paths, MCP-compatible tools, and
documented URI handoff where a tool exposes one. It does not rely on controlling
private VS Code chat webviews or scraping their DOM.
