# Documentation archive

This directory retains historical and foreign-project material that is useful
for provenance but is not current Daedalus guidance. Archived files must not be
used as gate, architecture, benchmark, or operations authority.

The canonical architecture and delivery authority remains
`docs/IKARUS_ARIADNE_MASTER_PLAN.md`. Current executable work packets live in
`docs/work-packets/`.

## Index

| Path | Last source commit | Archived SHA-256 | Archived because | Replacement |
| --- | --- | --- | --- | --- |
| `legacy-project-tct/bench_run.ps1` | `a98e2b1d238433f89c7c11eea49c663ee480b547` | `18f221eabdc68cd7eed7c3484c9bab9c98b9df8e491bbc3b57c40078faf56007` | Synchronizes and hard-resets the separate `project_tct` checkout on a named remote bench; it never tested Daedalus. | No canonical replacement yet. `tools/bench_test.sh` is legacy remote transport, not Gate evidence. |
| `legacy-project-tct/recreate_tct_venv.ps1` | `f2a4f6c341e688e8523d3f0eea22005bdec9167c` | `711c2194e623bd476ef168ee2c8d4290fc6d689fd30ed009b0c09aba85287ffd` | Recreates the camera-specific `TCT_app` Python 3.10 environment and PySpin wheel. | The Daedalus package/build verification documented by the active Gate-0 work packets. |

Negative experimental evidence under `runs/` is deliberately not archived or
deleted by this cleanup.
