# Going live with real Ollama agents

The write path below is built and covered by the harness suite; the bench can
only execute once Ollama is actually running on this machine. Whether `doctor`
says READY is a property of your machine right now, not of this page — run it
rather than trusting a sentence written on some earlier day.

> The "28 tests green" this page used to claim was measured in the harness's
> first weeks; the suite collects 7798 tests today [MEASURED 2026-08-25,
> `pytest tests/ --collect-only`]. A count is not a readiness claim, which is
> why it no longer appears here. `python -m daedalus.cli health --deep` and
> `python -m daedalus.cli governance` are the commands that answer readiness,
> and they exit non-zero rather than round up.

Run this sequence:

## 1. Start Ollama + pull the models  (your machine — I can't do this)

```powershell
ollama serve                     # if it isn't already running as a service
ollama pull qwen2.5-coder:7b     # the coder (or an upgrade: qwen3-coder / devstral)
ollama pull nomic-embed-text     # embeddings for semantic stage-1 routing
```

## 2. Confirm readiness

```powershell
cd C:\Users\nukei\Desktop\agent_env
python -m daedalus.doctor          # must say READY
```

## 3. Dry-run first (no writes) — sanity-check routing

```powershell
python -m daedalus.kairos.scheduler  # spawn plan: who'd run where
python -m daedalus.orchestration.benchmark       # projected token/cost picture
```

## 4. First LIVE task — on a safe, low-risk target

Start with something trivial and reversible (docstrings / a doc line), verified
+ auto-rolled-back if it fails the gate:

```powershell
python -m daedalus.offload "Add a module docstring to the scan panel" `
  --repo-root C:\Users\nukei\Desktop\project_tct `
  --paths TCT_app/gui/scan_panel.py --live
```

Outcome is one of: `offloaded` (bench wrote it, verified, $0 Claude),
`escalated_after_verify_fail` (write rolled back, hand to Claude), or
`escalate_to_claude` (wasn't eligible / bench down).

## 5. Watch for silent escalation

```powershell
python -m daedalus.metrics          # fallback-rate; alarms if the bench isn't pulling its weight
```

## 6. Fan-out a batch (optional)

```python
from daedalus.kairos.scheduler import KairosScheduler
KairosScheduler(max_workers=3).dispatch(r"C:\Users\nukei\Desktop\project_tct", tasks, dry_run=False)
```

## Write-mode verification gate

Local write-mode is now verified end-to-end. The pipeline:

1. **Policy guard**: Ollama never writes without a loaded policy (`--project` or
   `.agentenv/agentenv.json`). Device/vendor/secret/high-risk paths are blocked
   even when the policy is loaded.

2. **Disk-change verification**: Before accepting the result, `offload.py`
   snapshots content-hashes of target files before the run and compares them
   after. The write-mode gate trusts ONLY real on-disk changes (via `disk_changed`),
   not the model's self-report. A model that narrates an edit without writing fails
   the gate and escalates to Claude.

3. **Post-write checks**: Python syntax (`py_compile`), JSON/YAML config parsing,
   and optional project tests (if `test_command` is set) gate acceptance.

4. **Rollback on fail**: If any check fails, the worker rolls back the writes
   before escalating to Claude.

Safe to run against real project source with `--live` when the target repo has a
proper `.agentenv/agentenv.json` or is registered as a `--project`.
