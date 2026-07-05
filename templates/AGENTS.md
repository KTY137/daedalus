# AGENTS.md -- daedalus harness rules for Codex in this repo

This repo is wired into the `daedalus` multi-agent harness. Follow these
rules whenever the user delegates work here.

## Route work through the harness

- Delegate low-risk, well-scoped tasks (docs, tests, small refactors) by
  queueing them on the file bridge instead of doing everything yourself:

  ```powershell
  python -m daedalus.file_bridge enqueue "<task>" --repo-root <this repo> --lane auto
  ```

  `--lane auto` lets the router prefer the free local bench; use
  `--lane local_only` when Claude tokens must not be spent; use `--lane claude`
  to force the senior lane for high-risk work (auth, migrations, deletions,
  production config).

- The watcher MUST be running for queued requests to be answered: start the
  VS Code task **"Daedalus Bridge: watch"** (or
  `python -m daedalus.file_bridge watch`). Reports land in
  `inbox/<request>.report.json`.

## Communication rules

- Never talk to another agent (Claude Code, bench models) directly. All
  cross-agent traffic goes through the file bridge queue (`outbox/` ->
  `inbox/`).
- Work as a stateless specialist: the task brief is your only context; do not
  assume shared chat history and do not ask another agent for context.
- When acting as a specialist, return ONLY the structured `agent_report_v1`
  JSON: `status`, `summary` (max 600 chars), `files_changed`, `tests_run`,
  `risks`, `todos`, `handoff`. No prose around it.

## After interruptions

- Check `memory/todos.local.md` in the harness repo for open TODOs and
  recover those before starting anything new.

Full contract: `docs/COMMS_PROTOCOL.md` in the harness repo.
