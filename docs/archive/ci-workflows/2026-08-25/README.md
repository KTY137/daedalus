# Retired packet-scoped CI workflows (2026-08-25)

Classification: **ALIGNED**, Gate 0.

This directory preserves 96 historical GitHub Actions definitions that were
active files at base revision
`4b9dae0c4bce519f794d87474c62e1a13005cded`. They are evidence of the
packet-by-packet build history; they are not current CI and must not be run as a
batch.

Measured at the base revision:

- 98 active workflow files, 10,905 lines, and 350 job definitions;
- 94 files with 170 calls to the intentionally retired
  `tools/iron_plan_guard.py`;
- zero workflows targeting current `main` for pull requests or pushes;
- 95 workflows with at least one missing local input;
- 84 full-suite jobs, 90 wheel jobs, and 70 invocations of 66 retained mutation
  runners.

Owner commit `79825b5752de4666b2163f3a31c8a8b0fd887180` retired the mechanical
Iron Plan guard. The archive deliberately retains dead guard calls, stale test
paths, branch filters, and other negative evidence. Their presence here is not
a request to restore the guard or a claim that these files are runnable.

Two specialized definitions remain active but manual-only:

- `.github/workflows/g0-canonical-fault-matrix-contract.yml`;
- `.github/workflows/fourfold-polyglot-probe.yml`.

`BASE_WORKFLOW_MANIFEST.tsv` binds every original workflow path to its exact
base Git blob and its current disposition. The resulting consolidation commit
binds the archived bytes again in its own tree. Any file can also be recovered
from Git with `git show 4b9dae0c:<original_path>`.

The last scheduled probe observed on GitHub, run `32687059768`, executed zero
steps. GitHub's check annotation reports a failed account payment or insufficient
spending limit. That external condition is retained as a System-CI blocker; it
is not converted into a product pass or failure.

No workflow in this archive grants merge, promotion, publication, or Gate-close
authority.
