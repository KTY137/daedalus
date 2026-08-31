# G1-IGNITION-02 — Outer ignition effect boundary

Classification: `ALIGNED`  
Active gate: Gate 1 — Renovation ignition slice  
Base revision: `52b4baa5f7b065c54779cafd6a35b2411eeb5e84`  
Parent responsibility: `G1-WP-01_RENOVATION_IGNITION_SLICE`

## Primary claim

The public `python -m daedalus.ignition` door must enter the canonical central
effect boundary before parsing arguments or starting the Gate-1 slice. The
inner `TaskAttempt` boundaries remain authoritative for each attempt; this
packet closes the previously unguarded outer command boundary and creates no
new policy, ledger, CAS, evaluator, or promotion path.

## Reproduced negative baseline

Static closure derivation from `daedalus.ignition.__main__:main` found three
reachable effect classes:

- `filesystem_write` (receipt and content-addressed evidence artifacts);
- `process_spawn` (Git and gate children);
- `process_control` (managed gate process lifetime).

The entrypoint had no registry row and called `run_gate1_ignition()` without a
prior `begin_effect()`. Therefore a central process-guard refusal could not stop
the outer run before its first write or child process.

## Frozen scope

Changed:

- `daedalus/ignition/__main__.py`
- `daedalus/spine/effect_boundary.py`
- `tests/test_registry_new_doors.py`
- `tests/test_cli_effect_boundary.py`

Forbidden:

- changes to the two inner `TaskAttempt` effect boundaries or their leases;
- new effect, event, artifact, graph, evaluator, or promotion authority;
- automatic nomination, merge, or promotion;
- edits to unrelated dirty worktree files.

## Acceptance matrix

1. `cli.ignition` is a `CENTRAL` registry row with a resolving anchor.
2. Its declared effect set exactly equals the independently derived reachable
   set; neither an under-declaration nor a painted label passes.
3. `begin_effect()` is the first call in `main()`, above argument parsing.
4. A missing guard contract refuses before `run_gate1_ignition()` and before a
   receipt directory can be created.
5. Existing Gate-1 ignition behavior, replay, evidence, and non-promotion remain
   unchanged after admission.

## Verification

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q `
  tests/test_registry_new_doors.py `
  tests/test_cli_effect_boundary.py::test_ignition_refuses_before_any_run `
  tests/test_ignition_gate1.py
```

Rollback: restore the four scoped implementation/test files from the base
revision. Retain this packet and the unguarded-entrypoint finding as negative
evidence.

Iron Plan: **ALIGNED**  
Iron Gate: **1**  
Promotion: **not requested**
