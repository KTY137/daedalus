# CLAUDE.md -- daedalus harness rules for this repo

This repo is wired into the `daedalus` multi-agent harness. Follow these
rules whenever the user delegates work here.

## Route work through the harness

- Delegate low-risk, well-scoped tasks (docs, tests, small refactors) instead
  of doing everything yourself:

  ```powershell
  python -m daedalus.orchestrate "<task>" --repo-root <this repo>
  ```

  If Claude tokens are exhausted, queue only local work:

  ```powershell
  python -m daedalus.orchestrate "<task>" --repo-root <this repo> --lane local_only
  ```

  For a bigger objective, decompose it onto the local bench:

  ```powershell
  daedalus spawn "<objective>" --repo-root <this repo>
  ```

- Keep high-risk work (auth, migrations, deletions, production config)
  yourself, or enqueue it with `--lane claude` to force the senior lane.

## Communication rules

- Never talk to another agent (Codex, bench models) directly. All cross-agent
  traffic goes through the file bridge queue (`outbox/` -> `inbox/`).
- Work as a stateless specialist: the task brief is your only context; do not
  assume shared chat history and do not ask another agent for context.
- When acting as a specialist, return ONLY the structured `agent_report_v1`
  JSON: `status`, `summary` (max 600 chars), `files_changed`, `tests_run`,
  `risks`, `todos`, `handoff`. No prose around it.

## After interruptions

- Check `memory/todos.local.md` in the harness repo for open TODOs and
  recover those before starting anything new.

Full contract: `docs/COMMS_PROTOCOL.md` in the harness repo.
