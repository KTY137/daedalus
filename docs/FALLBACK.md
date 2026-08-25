# Fallback Policy

Claude and Codex are collaborators, not single points of failure.

## Default

- Codex can continue work when Claude is rate-limited or out of tokens.
- Claude reports are preferred for risky reviews, but low-risk work can continue
  with tests, git diffs, and memory logging.
- Every blocked Claude call is written to local memory so it can be retried later.

## If Claude Is Unavailable

Codex continues with:

1. current git status
2. `memory/todos.local.md`
3. local tests
4. concise recovery TODOs

For safety-critical hardware, HV, motion, data-loss, or architecture changes,
Codex may implement small safe fixes but should leave a TODO to run Claude/Mary
review before final merge.

## If Codex Is Unavailable

Claude should read:

```text
C:\Users\nukei\Desktop\agent_env\memory\todos.local.md
C:\Users\nukei\Desktop\project_tct\docs\AGENT_WORKFLOW.md
C:\Users\nukei\Desktop\project_tct\CLAUDE.md
```

Then run:

```powershell
git -C C:\Users\nukei\Desktop\project_tct status --short --branch
```

Claude should write unresolved handoff notes back to:

```text
C:\Users\nukei\Desktop\agent_env\memory\events.local.jsonl
```

or ask the user to tell Codex: "recover from daedalus memory".
