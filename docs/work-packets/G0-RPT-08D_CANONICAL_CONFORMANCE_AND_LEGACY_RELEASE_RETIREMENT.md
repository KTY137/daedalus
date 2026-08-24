# G0-RPT-08D — Canonical Conformance and Legacy Release Retirement

## Packet identity

- Iron Plan: **ALIGNED**
- Active gate: **Gate 0**
- Owner: **repository owner**
- Exact base revision: `8542df51593ec040da72361bbc9895b9bccff78a`
- Primary claim: no canonically non-central kernel state and no historical
  GateReport-v2 can create or live-validate a current Gate-0 release receipt.
- Promotion: not requested; owner merge decision remains external.

## Dependencies and supersession

This packet depends on the read-only contracts from `G0-RPT-08A`,
`G0-RPT-08B`, `G0-RPT-08C`, and `G0-GR-20` through `G0-GR-24` at the exact
base revision. It changes no dependency.

`G0-RPT-08D` supersedes only the live issue/verify acceptance claim in
`G0-RPT-08C`. That acceptance was unsafe because it used GateReport-v2 and
could not bind GateReportV3 or repository-write admission. The v1/v2 report
parsers, the v1 receipt parser, and historical artifacts from `G0-RPT-08C`
remain available for audit. They have no current release authority.

## Reproduced baseline

The canonical effect-boundary report requires structural conformance and
`CENTRAL` wiring for every row. GateReport-v2 projected only selected finding
codes and wiring values. At the exact base revision, this read-only synthetic
probe produced a false close:

```powershell
@'
import dataclasses
from pathlib import Path
from types import SimpleNamespace
import daedalus.gates.report as report
from daedalus.spine.effect_boundary import ConformanceReport, REGISTRY_BY_ID, Wiring
rows = tuple(REGISTRY_BY_ID.values())
matrix = (dataclasses.replace(rows[0], wiring=Wiring.LOCAL_GUARDS),) + tuple(dataclasses.replace(row, wiring=Wiring.CENTRAL) for row in rows[1:])
conformance = ConformanceReport(registry_sha256='b' * 64, discoveries=(), findings=(), matrix=matrix)
report.check_conformance = lambda root: conformance
report.bind_runtime_conformance_receipts = lambda *args, **kwargs: SimpleNamespace(failures=(), diagnostics=())
report.bind_fault_matrix_evidence = lambda *args, **kwargs: SimpleNamespace(failures=(), diagnostics=())
report._writer_inventory_evidence = lambda *args, **kwargs: ('c' * 64, (), ())
built = report.build_gate0_report(Path('.'), source_revision='a' * 40, security_boundary_claimed=True)
print({'canonical_gate0_closed': conformance.gate0_closed, 'report_closed': built.closed, 'report_blockers': built.blockers})
'@ | python -
```

Result:

```text
{'canonical_gate0_closed': False, 'report_closed': True, 'report_blockers': ()}
```

The old public release success path was also executable:

```text
python -m pytest -q -p no:cacheprovider tests/gates/test_gate0_release_assessment.py::test_release_receipt_round_trip_signature_and_exact_bindings
1 passed in 1.37s
```

Live canonical conformance at the same revision measured
`gate0_closed=False`, `structurally_conformant=True`, registry digest
`0323d243e3954bad30022e04b6d573359c359611557d07dac3294bff00040303`,
and wiring `80 CENTRAL / 10 LOCAL_GUARDS / 8 INVENTORY_ONLY / 1 ABSENT`.

## Changed behavior

1. If `ConformanceReport.gate0_closed` is false, the canonical report builder
   adds one deterministic, registry-digest-bound sentinel to the existing
   blocker-bearing `runtime_conformance_failures` projection. The v2 wire shape
   remains unchanged and diagnostics do not become authority.
2. GateReportV3 inherits the same blocker through its v2 base report.
3. `issue_gate0_release_receipt()` and `verify_gate0_release_receipt()` retain
   their call signatures but return `NoReturn` and contain only the canonical
   retirement barrier. The old signing and live-verification implementations
   are deleted, not left behind the guard.
4. The owner-facing CLI strictly parses historical report/index/bundle inputs
   and then calls the same barrier. It consumes no collector or verifier secret,
   performs no trust verification or live scan, and never writes output. Its
   supported repository invocation is `python -m scripts.gate0_release`.
5. Directly constructed historical v2 objects can still represent
   `closed=true`; serialization and audit baselines require that compatibility.
   Such an object cannot cross the current public release boundary.

## Exact in-scope paths

- `docs/work-packets/G0-RPT-08D_CANONICAL_CONFORMANCE_AND_LEGACY_RELEASE_RETIREMENT.md`
- `daedalus/gates/report.py`
- `daedalus/gates/release.py`
- `scripts/gate0_release.py`
- `tests/gates/test_gate_report_canonical_conformance.py`
- `tests/gates/test_gate_report_matrix_binding.py`
- `tests/gates/test_gate_cli_conformance_receipts.py`
- `tests/gates/test_gate0_release_assessment.py`
- `tests/gates/test_gate0_release_assessment_review.py`
- `tests/gates/test_gate0_release_writer_inventory.py`
- `tests/gates/test_gate0_release_cli.py`

## Forbidden paths and authority

- `docs/IKARUS_ARIADNE_MASTER_PLAN.md`
- `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`
- `daedalus/gates/report_v3.py`
- `daedalus/gates/evidence.py`
- `daedalus/gates/evidence_verifier.py`
- `daedalus/gates/trust_bundle.py`
- `daedalus/gates/repository_write_artifact_admission.py`
- every policy, evaluator, ledger, promotion, merge, and OwnerApproval path

No evidence-index, trust-bundle, repository-write evidence, CAS, admission,
policy, evaluator, ledger, promotion, or plan authority is added or changed.

## Acceptance and refusal matrix

- every non-`CENTRAL` `Wiring` value creates the exact registry-bound sentinel;
- an unknown future blocker-severity conformance finding creates the sentinel;
- an all-`CENTRAL`, structurally conformant synthetic builder result omits the
  sentinel; this is a projection control, never release evidence;
- GateReportV3 composition cannot drop the base sentinel;
- legacy v2, naked V3, an actual GateReport subclass, a duck type, and an
  unrelated object all refuse at the same public release barrier;
- issue and verify refuse before trust checks, live scans, key access, signing,
  receipt construction, or output writing;
- historical v1/v2 reports and v1 receipts remain strictly parseable;
- CLI issue and verify exit 1, require no secret, and preserve absent or
  pre-existing output;
- removing the sentinel, issue barrier, or verify barrier kills a targeted test.

## Budgets and expected failures

- no network, provider, model, secret, external service, or repository write is
  required by verification;
- deterministic unit and source-review tests only; scan-heavy tests may consume
  several minutes but have no stochastic seed budget;
- Gate 0 is expected to remain open;
- CLI issue and verify are expected to exit 1;
- the stale architecture snapshot and broken system-CI paths are pre-existing,
  separate blockers and are not acceptance evidence for this packet.

## Migration and rollback

Migration is immediate and fail-closed: existing report and receipt bytes remain
readable, while all current issue/live-verify calls refuse. No data rewrite is
needed. Before owner merge, rollback is deletion of this isolated candidate
branch. After merge, reverting 08D would restore a reproduced false-release
path and is forbidden unless the same owner change atomically installs the
complete stronger V3/admission release chain.

The forward replacement must version and bind exact GateReportV3,
repository-write artifact evidence, CAS resolution and admission, the evidence
index, the trust bundle, live canonical conformance, exact commit/tree identity,
and a new release receipt. Variant-C authentication and its verification-only
key remain a separate owner-amendment dependency.

## Evidence and retained negative result

Commands:

```powershell
python -m pytest -q -p no:cacheprovider tests/gates/test_gate_report_canonical_conformance.py tests/gates/test_gate_report_matrix_binding.py tests/gates/test_gate0_release_assessment.py tests/gates/test_gate0_release_assessment_review.py tests/gates/test_gate0_release_cli.py tests/gates/test_gate0_release_writer_inventory.py
python -m pytest -q -p no:cacheprovider tests/gates/test_gate_cli_conformance_receipts.py
$targets = rg --files tests/gates | rg '(test_gate_report|test_gate0_release)'; python -m pytest -q -p no:cacheprovider $targets
python -m pytest -q -p no:cacheprovider -x tests/gates
```

The stable independent test window reported:

- final builder run: 49/49 focused report/release tests passed in 216.74
  seconds;
- 6/6 Gate CLI conformance-receipt tests passed in 203.69 seconds;
- 134/134 `test_gate_report*` and `test_gate0_release*` family tests passed in
  343.85 seconds;
- the complete Gate suite passed: 863 passed, 2 skipped in 651.68 seconds;
- all three in-memory mutants died at their targeted assertions;
- AST parsing of all ten Python scope paths passed;
- exact changed-path scope matched 11/11;
- `git diff --check` passed, with only repository LF/CRLF notices.

The plan-requested legacy guard command was attempted exactly:

```text
python tools/iron_plan_guard.py verify
can't open file '.../tools/iron_plan_guard.py': [Errno 2] No such file or directory
```

The repository instructions record that this retired tool no longer enforces
the plan. Its absence and the already-audited broken workflow paths mean build
chain step 7 (System CI) remains externally blocked; no green System-CI claim is
made. Plan alignment here is document review plus independent human-readable
scope review, not a replacement script.

An earlier 133/134 run is retained as invalid measurement: production files
changed during GateReportV3's deliberate double-scan drift fence. The frozen
rerun above supersedes it; it is not hidden or counted as a product failure.

## Independent review questions

1. Is any public issue or live-verification capability left behind the
   retirement barrier?
2. Can any current or future non-central canonical conformance state omit the
   sentinel from a builder-produced report?
3. Can a subtype, duck type, malformed report, old receipt, CLI secret, or
   pre-existing output bypass or weaken refusal?
4. Are historical parsing and baseline inspection preserved without granting
   release authority?
5. Does any change cross into V3 authentication, admission, evidence, trust,
   policy, evaluator, ledger, promotion, or plan authority?

No automatic merge, promotion, owner approval, gate transition, or security
guarantee is authorized.
