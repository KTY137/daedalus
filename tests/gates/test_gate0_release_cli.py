from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.gates import load_gate_evidence_index
from daedalus.gates.release import load_gate0_release_receipt
from daedalus.gates.trust_bundle import load_evidence_trust_bundle

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests" / "gates" / "test_gate0_release_assessment.py"


def _load_fixture():
    name = "daedalus_test_gate0_release_cli_fixture"
    spec = importlib.util.spec_from_file_location(name, FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_fixture()

# The bundle under test is signed by the trust-bundle fixture's collector
# key; derive the CLI argument from that chain instead of repeating the
# secret material as a literal that can go stale.  A stale literal does not
# fail loudly here: the CLI still refuses, but for a signature mismatch
# rather than the condition under test, so the assertion on the refusal
# reason is what keeps these tests honest.
COLLECTOR_ID, COLLECTOR_KEY_ID = fixture.fixture.COLLECTOR_KEY
COLLECTOR_KEY_ARG = ":".join(
    (COLLECTOR_ID, COLLECTOR_KEY_ID, fixture.fixture.SECRET.decode("ascii"))
)

# The release verifier keyring is owned by the assessment fixture; derive it
# from the same chain for the same reason.
VERIFIER_ID, VERIFIER_KEY_ID = fixture.VERIFIER_KEY
VERIFIER_SECRET = fixture.RELEASE_SECRET.decode("ascii")
VERIFIER_KEY_ARG = ":".join((VERIFIER_ID, VERIFIER_KEY_ID, VERIFIER_SECRET))


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _run(*args: str, env: dict[str, str] | None = None):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, "-m", "scripts.gate0_release", *args],
        cwd=ROOT,
        env=merged,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _dump_inputs(tmp_path: Path):
    root, report, index, bundle = fixture._inputs(tmp_path)
    report_path = tmp_path / "gate-report.json"
    index_path = tmp_path / "evidence-index.json"
    bundle_path = tmp_path / "trust-bundle.json"
    _write_json(report_path, report.to_dict())
    _write_json(index_path, index.to_dict())
    _write_json(bundle_path, bundle.to_dict())
    workflow_path = root / fixture.fixture.WORKFLOW_PATH
    return root, report_path, index_path, bundle_path, workflow_path


def _common_issue_args(
    root: Path,
    report_path: Path,
    index_path: Path,
    bundle_path: Path,
    workflow_path: Path,
    output: Path,
) -> tuple[str, ...]:
    return (
        "issue",
        "--report",
        str(report_path),
        "--index",
        str(index_path),
        "--trust-bundle",
        str(bundle_path),
        "--repo-root",
        str(root),
        "--collector-key",
        COLLECTOR_KEY_ARG,
        "--expected-collector-id",
        COLLECTOR_ID,
        "--expected-workflow",
        f"gate0-contracts:{workflow_path}",
        "--current-revision",
        fixture.fixture.REVISION,
        "--current-tree-revision",
        fixture.fixture.TREE,
        "--receipt-id",
        "gate0-release-receipt-1",
        "--verifier-id",
        VERIFIER_ID,
        "--verifier-key-id",
        VERIFIER_KEY_ID,
        "--verified-at",
        (fixture.fixture.NOW + fixture.timedelta(minutes=2)).isoformat(),
        "--output",
        str(output),
    )


def test_issue_and_live_verify_cli_refuse_retired_release_contract(
    tmp_path: Path,
) -> None:
    root, report_path, index_path, bundle_path, workflow_path = _dump_inputs(
        tmp_path
    )
    output = tmp_path / "release-receipt.json"
    issue_env = {"DAEDALUS_GATE0_RELEASE_VERIFIER_SECRET": VERIFIER_SECRET}
    issued = _run(
        *_common_issue_args(
            root,
            report_path,
            index_path,
            bundle_path,
            workflow_path,
            output,
        ),
        env=issue_env,
    )
    assert issued.returncode == 1
    assert issued.stdout == ""
    assert "secret" not in issued.stderr.lower()
    assert "inspection-only" in issued.stderr
    assert not output.exists()

    report = fixture.load_strict_gate_report(report_path)
    index = load_gate_evidence_index(index_path)
    bundle = load_evidence_trust_bundle(bundle_path)
    receipt = fixture._historical_receipt(report, index, bundle)
    _write_json(output, receipt.to_dict())
    assert load_gate0_release_receipt(output) == receipt

    verified = _run(
        "verify",
        "--receipt",
        str(output),
        "--report",
        str(report_path),
        "--index",
        str(index_path),
        "--trust-bundle",
        str(bundle_path),
        "--repo-root",
        str(root),
        "--collector-key",
        COLLECTOR_KEY_ARG,
        "--expected-collector-id",
        COLLECTOR_ID,
        "--expected-workflow",
        f"gate0-contracts:{workflow_path}",
        "--verifier-key",
        VERIFIER_KEY_ARG,
        "--expected-verifier-id",
        VERIFIER_ID,
        "--current-revision",
        fixture.fixture.REVISION,
        "--current-tree-revision",
        fixture.fixture.TREE,
        "--now",
        (fixture.fixture.NOW + fixture.timedelta(minutes=3)).isoformat(),
    )
    assert verified.returncode == 1
    assert verified.stdout == ""
    assert "inspection-only" in verified.stderr


def test_issue_cli_does_not_require_secret_for_retirement_refusal(
    tmp_path: Path,
) -> None:
    root, report_path, index_path, bundle_path, workflow_path = _dump_inputs(
        tmp_path
    )
    output = tmp_path / "release-receipt.json"
    result = _run(
        *_common_issue_args(
            root,
            report_path,
            index_path,
            bundle_path,
            workflow_path,
            output,
        ),
        env={"DAEDALUS_GATE0_RELEASE_VERIFIER_SECRET": ""},
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert not output.exists()
    assert "inspection-only" in result.stderr


def test_issue_cli_refuses_open_report_and_preserves_output(
    tmp_path: Path,
) -> None:
    root, _, index, bundle = fixture._inputs(
        tmp_path,
        report_changes={"security_boundary_claimed": False},
    )
    report = fixture._report(root, security_boundary_claimed=False)
    report_path = tmp_path / "gate-report.json"
    index_path = tmp_path / "evidence-index.json"
    bundle_path = tmp_path / "trust-bundle.json"
    output = tmp_path / "release-receipt.json"
    _write_json(report_path, report.to_dict())
    _write_json(index_path, index.to_dict())
    _write_json(bundle_path, bundle.to_dict())
    output.write_text("sentinel\n", encoding="utf-8")

    result = _run(
        *_common_issue_args(
            root,
            report_path,
            index_path,
            bundle_path,
            root / fixture.fixture.WORKFLOW_PATH,
            output,
        ),
        env={"DAEDALUS_GATE0_RELEASE_VERIFIER_SECRET": VERIFIER_SECRET},
    )
    assert result.returncode == 1
    assert output.read_text(encoding="utf-8") == "sentinel\n"
    assert "inspection-only" in result.stderr


def test_issue_cli_does_not_consume_collector_key_on_retired_path(
    tmp_path: Path,
) -> None:
    # Argument-shape refusals must fail closed on the same terms as evidence
    # refusals: exit 1, nothing on stdout, no receipt written, and no secret
    # material echoed back into the error stream.
    root, report_path, index_path, bundle_path, workflow_path = _dump_inputs(
        tmp_path
    )
    output = tmp_path / "release-receipt.json"
    args = list(
        _common_issue_args(
            root,
            report_path,
            index_path,
            bundle_path,
            workflow_path,
            output,
        )
    )
    args[args.index(COLLECTOR_KEY_ARG)] = f"{COLLECTOR_ID}:{COLLECTOR_KEY_ID}"

    result = _run(
        *args,
        env={"DAEDALUS_GATE0_RELEASE_VERIFIER_SECRET": VERIFIER_SECRET},
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert not output.exists()
    assert "inspection-only" in result.stderr
    assert VERIFIER_SECRET not in result.stderr


def test_cli_loaders_preserve_exact_index_and_bundle_contracts(
    tmp_path: Path,
) -> None:
    _, _, index, bundle = fixture._inputs(tmp_path)
    index_path = tmp_path / "index.json"
    bundle_path = tmp_path / "bundle.json"
    _write_json(index_path, index.to_dict())
    _write_json(bundle_path, bundle.to_dict())
    assert load_gate_evidence_index(index_path) == index
    assert load_evidence_trust_bundle(bundle_path) == bundle


def test_receipt_loader_refuses_recursive_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"contract_type":"daedalus-gate0-release-receipt/1",'
        '"receipt_id":"a","provenance":{"origin":"a","origin":"b"}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_gate0_release_receipt(path)
