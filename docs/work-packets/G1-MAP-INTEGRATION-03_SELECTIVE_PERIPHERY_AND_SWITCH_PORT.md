# G1-MAP-INTEGRATION-03 - Selective periphery and switch integration

Packet ID: `G1-MAP-INTEGRATION-03`
Artifact role: `primary`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `97e5e66a07028060005e071270d201a31a28b98b`
Dependencies: `Master Plan Revision 13; reviewed MAP-02 remote audit; existing project-center and env-helper reintegration`
Promotion: not requested by this packet; owner requested source integration

Plan revision 13 SHA-256:
`04e8cbf9441134e22b97fe1cb5e7ebcbcfedac64cda2f3e4e5086d82bb628639`.

## Primary acceptance claim

The architecture census keeps resolving every module while its drift and
inventory rankings omit explicitly ignored periphery and report that omission.
Mixed project/periphery disagreement edges remain visible. OS-owned environment
variables are consistently excluded from switch-documentation drift, and the
optional coverage-guided gate can be installed through the existing test extra.

## Scope

Allowed: `.daedalusignore`; `daedalus/mapping/reach.py`, `drift.py`,
`inventory.py`, `switches.py`; `pyproject.toml`; `uv.lock`;
`tests/test_mapping_scope.py`, `tests/test_mapping_switches_platform.py`, and
the relevant assertion in `tests/test_mapping_drift.py`; this packet.

Forbidden: generated inventory/map/state snapshots and accepted drift baselines;
master plan, amendment chain, AGENTS.md, policy, scheduler, execution authority,
provider code, existing env-helper resolver, project-center parser and preflight
semantics. No source scan is narrowed, no gate is closed, and no old campaign
or approval operation is reintroduced.

## Contracts and behavior

Harvest only the missing behavior from remote `packet/g1-map-02` at `ce4bcfd4`.
Reach reports retain their complete module and edge population, add `shell`
per module and record the ignore-scope fingerprint. Only the repository's
`.daedalusignore` rules define census periphery; environment variables and the
hotspot-ranking center declaration do not narrow this census. Drift/inventory
withhold periphery rankings while disclosing their counts. Disagreement edges
are withheld only when both endpoints are known periphery.

Keep main's stronger indirect env-reader discovery unchanged. Add only USER,
USERDOMAIN and PROCESSOR_IDENTIFIER to the OS-owned set, and use that same
set when deriving documented switch mentions. Add coverage>=7 to test extras
without changing existing optional dependency groups or core dependencies.

## Acceptance matrix

Budget: ten minutes per focused test invocation; no provider/model calls or
spend. Dependency lock resolution may read package-registry metadata.

1. Before implementation, run the existing reach, drift, switch, indirect-reader,
   project-center, and optional-preflight suites with the repository venv.
2. Ignored modules remain present/classified and importable as graph endpoints;
   environment-only exclusions cannot hide project modules.
3. Project islands stay ranked; ignored islands are withheld with a count and
   scope fingerprint. Unconfigured repositories preserve their old behavior.
4. Core/core, core/shell and shell/core disagreement edges remain visible;
   only shell/shell disagreements are withheld. Unknown endpoints stay visible.
5. Inventory ranking excludes periphery while retaining project findings and
   reporting how many periphery modules it withheld.
6. OS variables produce neither undocumented-read nor documented-unread false
   positives. Daedalus-owned undocumented variables remain findings.
7. Existing env-helper, project-center and preflight regressions remain green.
   Dependency locking retains all existing optional groups and pins.
8. Scoped diff/whitespace checks pass; the new primary's registry metadata
   validates. A pre-existing GPU-66 registry rendering blocker is reported
   separately and may be handled by the parent integration packet.

## Migration and rollback

Consumers that ignore additive report fields keep working. Historical generated
reports remain unchanged and retain their original source/measurement meaning;
this packet does not adopt a new architecture baseline. Revert this packet's
commit to restore the prior measurement behavior and test-extra declaration.

## Evidence expected failures and review

Measured 2026-09-08 with the main repository venv, CPython 3.12.13:

- Pre-change baseline: 168 passed in 78.08s across `test_mapping_reach`,
  `test_mapping_drift`, `test_mapping_switches`,
  `test_mapping_switches_indirect`, `test_structcore_center_directive`, and
  `test_gate_host_preflight_coverage`.
- New regression baseline before implementation: 17 failed, 9 passed in
  16.59s. Missing scope fields and unfiltered periphery/OS findings failed.
- Focused acceptance including inventory: 78 passed in 18.32s.
- Combined legacy and acceptance suites: 300 passed in 107.39s. The command
  adds `test_mapping_scope`, `test_mapping_switches_platform`,
  `test_generated_inventory`, and `test_mapping_cli` to the baseline paths;
  all paths are under `tests/` and end in `.py`. Every invocation used
  `-m pytest -q -p no:cacheprovider --color=no`, without `-x`.
- Reintroducing upstream's mixed-edge filter and the strict-doc OS exclusion
  defect makes their two focused regressions fail. The original source bytes
  were restored in a `finally` block after this mutation check; both focused
  regressions then pass again (2 passed in 0.85s).
- `uv lock --offline` initially refused because platform packages were absent
  from cache; ordinary `uv lock` succeeded, adding only coverage 7.16.0.
  A parsed-record comparison verifies every pre-existing dependency record
  unchanged. `uv lock --check` passes.
- `uv build --wheel` succeeds; wheel metadata declares `coverage>=7` only in
  the test extra. Existing optional dependency groups and core remain intact.
- The registry's `_artifact` validator accepts this primary's ID, role,
  metadata and all required sections. Full `tools/index_work_packets.py --check`
  refuses the pre-existing `docs/work-packets/G1-EXP-TENSOR-GPU-66.json`:
  `new Work Packet artifact lacks artifact_role`. Registry rendering is
  explicitly blocked on that parent integration repair; this packet does not
  rewrite the GPU packet or bypass the checker. The generated index is untouched.

The upstream mixed-edge filter used `not any(shell endpoint)`, suppressing
project/periphery disagreements despite its stated contract. This packet
retains that negative review finding and proves the corrected behavior.
The parent reviewer checks exact selective scope, disclosed withholding,
environment resistance, boundary edges and unchanged stronger main fixes
before cherry-picking. No scientific representation claim is made.

Iron Plan: ALIGNED. Iron Gate: 1.
