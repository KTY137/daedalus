# Going live with real Ollama agents

Everything is built and tested (28 tests green), but the bench can only execute
once Ollama is actually running on this machine. Right now `doctor` says NOT
READY (server unreachable). Run this sequence:

## 1. Start Ollama + pull the models  (your machine — I can't do this)

```powershell
ollama serve                     # if it isn't already running as a service
ollama pull qwen2.5-coder:7b     # the coder (or an upgrade: qwen3-coder / devstral)
ollama pull nomic-embed-text     # embeddings for semantic stage-1 routing
```

## 2. Confirm readiness

```powershell
cd C:\Users\nukei\Desktop\agent_env
python -m agent_env.doctor          # must say READY
```

## 3. Dry-run first (no writes) — sanity-check routing

```powershell
python -m agent_env.ikarus          # spawn plan: who'd run where
python -m agent_env.benchmark       # projected token/cost picture
```

## 4. First LIVE task — on a safe, low-risk target

Start with something trivial and reversible (docstrings / a doc line), verified
+ auto-rolled-back if it fails the gate:

```powershell
python -m agent_env.offload "Add a module docstring to the scan panel" `
  --repo-root C:\Users\nukei\Desktop\project_tct `
  --paths TCT_app/gui/scan_panel.py --live
```

Outcome is one of: `offloaded` (bench wrote it, verified, $0 Claude),
`escalated_after_verify_fail` (write rolled back, hand to Claude), or
`escalate_to_claude` (wasn't eligible / bench down).

## 5. Watch for silent escalation

```powershell
python -m agent_env.metrics          # fallback-rate; alarms if the bench isn't pulling its weight
```

## 6. Fan-out a batch (optional)

```python
from agent_env.ikarus import Ikarus
Ikarus(max_workers=3).dispatch(r"C:\Users\nukei\Desktop\project_tct", tasks, dry_run=False)
```

## Before trusting `write` mode broadly

Mary (qa-critic) is reviewing the egress + write guards + rollback for holes.
Fold in any critical fixes she flags **before** running live writes against real
project source. Until then, keep live runs to throwaway/scratch targets.
