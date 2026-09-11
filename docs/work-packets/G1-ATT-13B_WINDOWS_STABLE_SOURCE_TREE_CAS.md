# G1-ATT-13B — Windows-stable Source Tree CAS capture

Classification: `ALIGNED`  
Active gate: Gate 1 — Renovation ignition slice  
Base revision: `52b4baa5f7b065c54779cafd6a35b2411eeb5e84`  
Parent responsibility: `G0-ATT-13A_SOURCE_TREE_CAS_PORT`

## Primary claim

`SourceTreeStore` must accept unchanged regular files on every supported Python
version while retaining fail-closed detection of content, identity, size, and
modification-time changes. Windows creation-time metadata is not used as a
stability signal because repeated `fstat()` calls on the same open descriptor
produce different `st_ctime_ns` values under supported CPython 3.12 and 3.13.

This packet changes the metadata comparison only. It creates no second CAS,
runtime path, Campaign, approval, promotion, or primary-checkout write.

## Reproduced negative baseline

On Windows 11, the focused source-tree suite reported five false corruption or
capture failures. Instrumentation found that `st_dev`, `st_ino`, `st_size`, and
`st_mtime_ns` remained equal while only `st_ctime_ns` changed between stable
reads.

Fifty repeated `SourceTreeStore.put_bytes()` calls produced:

- CPython 3.13: 27 false failures;
- CPython 3.12: 26 false failures;
- CPython 3.11: 0 false failures;
- CPython 3.10: 0 false failures.

The package supports Python `>=3.10`, so this is a compatibility defect in the
canonical Candidate Source Tree substrate, not evidence of candidate mutation.

## Frozen scope

Changed:

- `daedalus/kernel/source_trees.py`
- `tests/kernel/test_source_tree_store.py`

Forbidden:

- artifact or locator identity changes;
- weakening digest, device/inode, size, or modification-time checks;
- changes to Attempts, Campaigns, evaluators, policy, promotion, or the master
  plan;
- edits to unrelated dirty worktree files.

## Acceptance matrix

1. Windows metadata policy excludes only `st_ctime_ns`; POSIX retains it.
2. Stable files and CAS objects no longer fail spuriously on supported Windows
   interpreters.
3. Same-size content corruption is still caught by SHA-256 verification.
4. Source changes during capture and object changes during reads remain
   fail-closed through identity, size, mtime, and digest checks.
5. The focused source-tree, Fourfold-evidence, and ignition suites remain green
   apart from explicitly named environment-only skips.

## Verification

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q tests/kernel/test_source_tree_store.py
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -q tests/kernel/test_fourfold_evidence.py tests/ignition/test_voltage_ignition.py tests/test_ignition_gate1.py
```

Measured 2026-08-31 on Windows / CPython 3.13.5:

- `tests/kernel/test_source_tree_store.py`: `10 passed, 1 skipped`;
- dependent Fourfold-evidence and Ignition selection: `73 passed`;
- the skip is the existing host inability to create the requested symlink and
  is not a product pass or failure.

Rollback: restore the two scoped implementation/test files from the base
revision. Retain this packet and its false-failure counts as negative evidence.

Iron Plan: **ALIGNED**  
Iron Gate: **1**  
Promotion: **not requested**
