# Wiring a live session to actually offload

The harness is a standalone tool. Something has to *drive* it — call the offload
bridge for offloadable tasks. Three options, cheapest-to-wire first.

## The bridge

Everything routes through one call:

```python
from agent_env.offload import offload
offload(objective, repo_root, paths=[...], live=True, run_tests=False, project="project_tct")
```

- Not eligible / bench down  → `{"action": "escalate_to_claude", ...}` (you/Adam do it).
- Eligible + bench up + verify passes → `{"action": "offloaded", "report": {...}}` (done, $0 Claude).
- Verify fails → write rolled back, `{"action": "escalated_after_verify_fail", ...}`.

Every outcome is metered — watch it with `python -m agent_env.metrics`.

CLI form:

```powershell
python -m agent_env.offload "Draft docstrings for the motor panel" `
  --repo-root C:\Users\nukei\Desktop\project_tct `
  --paths TCT_app/gui/motor_panel.py --live
```

## Who drives it

1. **Manual / Codex (available now).** You or Codex call `offload(..., live=True)`
   for a batch of low-risk tasks before touching Claude. The existing
   `file_bridge` (outbox/inbox) is the async version of this. Zero new wiring.

2. **A Claude Code hook (the "every session uses it" idea).** A `UserPromptSubmit`
   or `PreToolUse` hook in `.claude/settings.json` that, for offloadable edits,
   runs `offload(..., live=True)` and returns the result so Claude never spends
   tokens on it. This is the durable "every VS Code chat offloads" path — it's a
   settings/hooks change, so we hold it until the design is final (use the
   `update-config` skill to add it).

3. **Ikarus batch driver.** For fan-out (many low-risk files at once),
   `Ikarus(max_workers=3).dispatch(repo_root, tasks, dry_run=False)` runs the
   whole batch on the bench in bounded waves. Good for "docstring the module",
   "regenerate the docs".

## Prerequisite (always)

`python -m agent_env.doctor` must say **READY** — Ollama serving + the coder
model pulled. Until then every offload honestly falls back to Claude, and the
metrics fallback-rate alarm will tell you if that's happening silently.
