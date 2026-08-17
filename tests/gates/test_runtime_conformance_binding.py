"""Runtime-conformance evidence binds, or the report says exactly what is missing."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.gates.runtime_conformance_binding import (
    CANONICAL_PRODUCER,
    UNBOUND_ROW,
    RuntimeConformanceBinding,
    bind_runtime_conformance_receipts,
)
from daedalus.kernel.runtime_conformance import (
    RecordedObservation,
    assemble_recorded_conformance,
)
from daedalus.schemas import (
    RUNTIME_CONFORMANCE_CHECKS,
    ContractProvenance,
    RuntimeCapabilities,
    RuntimeManifest,
    RuntimeConformanceReceipt,
)


REVISION = "a" * 40
OTHER_REVISION = "b" * 40
NOW = datetime(2026, 8, 2, 0, 0, tzinfo=timezone.utc)


def _manifest(revision: str = REVISION) -> RuntimeManifest:
    return RuntimeManifest(
        runtime_id="fixture-runtime",
        runtime_version="1.0",
        adapter_id="fixture-adapter",
        adapter_version="1.0",
        source_revision=revision,
        assurance="declared",
        capabilities=RuntimeCapabilities(
            streaming=True,
            tool_events=True,
            structured_output=True,
            timeout=True,
            cancellation=True,
            workspace_isolation=True,
            cost_reporting=True,
            workspace_write=True,
        ),
        declared_tools=("read-file",),
        egress_transports=("internal-proxy",),
        workspace_modes=("isolated-worktree", "read-only"),
        cost_model="fixture-units",
        provenance=ContractProvenance(
            origin="tests.runtime-manifest",
            source_revision=revision,
            created_at=NOW.isoformat(),
            input_digests=(),
        ),
    )


def _receipt(
    tmp_path: Path,
    *,
    receipt_id: str = "runtime-fixture-001",
    revision: str = REVISION,
    passed: bool = True,
) -> RuntimeConformanceReceipt:
    return assemble_recorded_conformance(
        _manifest(revision),
        observations={
            name: RecordedObservation(
                passed=passed,
                detail="recorded offline fixture",
                transcript={"check": name},
            )
            for name in RUNTIME_CONFORMANCE_CHECKS
        },
        artifact_root=tmp_path / f"cas-{receipt_id}",
        receipt_id=receipt_id,
        started_at=NOW.isoformat(),
        finished_at=(NOW + timedelta(seconds=1)).isoformat(),
    )


def test_no_receipts_names_the_producer_instead_of_a_placeholder() -> None:
    binding = bind_runtime_conformance_receipts(source_revision=REVISION)
    assert binding.bound is False
    assert binding.failures == (UNBOUND_ROW,)
    assert f"info:runtime_conformance.canonical_producer:{CANONICAL_PRODUCER}" in (
        binding.diagnostics
    )
    assert "blocker:runtime_conformance_receipts:unbound" in binding.diagnostics
    assert any("persists-no-receipt-artifact" in row for row in binding.diagnostics)


def test_a_passed_receipt_at_this_revision_binds_clean(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    binding = bind_runtime_conformance_receipts((receipt,), source_revision=REVISION)
    assert binding.bound is True
    assert binding.failures == ()
    assert binding.receipt_sha256s == (receipt.digest,)


def test_a_failed_receipt_blocks(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path, receipt_id="failing", passed=False)
    binding = bind_runtime_conformance_receipts((receipt,), source_revision=REVISION)
    assert binding.failures == ("failing:failed",)


def test_a_receipt_from_another_revision_blocks(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path, receipt_id="stale", revision=OTHER_REVISION)
    binding = bind_runtime_conformance_receipts((receipt,), source_revision=REVISION)
    assert binding.failures == (f"stale:stale-revision:{OTHER_REVISION}",)


def test_a_persisted_bundle_is_loaded_and_verified(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    bundle = tmp_path / "receipts"
    bundle.mkdir()
    (bundle / "one.json").write_text(receipt.to_json(), encoding="utf-8")
    binding = bind_runtime_conformance_receipts(
        source_revision=REVISION, receipt_dir=bundle
    )
    assert binding.bound is True
    assert binding.failures == ()
    assert binding.receipt_sha256s == (receipt.digest,)


def test_a_bundle_of_rubbish_blocks_and_does_not_bind(tmp_path: Path) -> None:
    bundle = tmp_path / "receipts"
    bundle.mkdir()
    (bundle / "broken.json").write_text("{not json", encoding="utf-8")
    (bundle / "wrong.json").write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    binding = bind_runtime_conformance_receipts(
        source_revision=REVISION, receipt_dir=bundle
    )
    assert binding.bound is False
    assert "receipt-bundle:malformed:broken.json" in binding.failures
    assert "receipt-bundle:not-a-conformance-receipt:wrong.json" in binding.failures
    assert UNBOUND_ROW in binding.failures


def test_an_absent_bundle_directory_is_reported(tmp_path: Path) -> None:
    binding = bind_runtime_conformance_receipts(
        source_revision=REVISION, receipt_dir=tmp_path / "nowhere"
    )
    assert "receipt-bundle:absent" in binding.failures
    assert binding.bound is False


def test_duplicate_receipt_ids_block(tmp_path: Path) -> None:
    receipt = _receipt(tmp_path)
    binding = bind_runtime_conformance_receipts(
        (receipt, receipt), source_revision=REVISION
    )
    assert "runtime-fixture-001:duplicate-receipt-id" in binding.failures


def test_a_bound_binding_must_cite_a_receipt() -> None:
    with pytest.raises(ValueError, match="must cite at least one receipt"):
        RuntimeConformanceBinding(bound=True, failures=(), diagnostics=())


def test_non_receipt_input_is_refused() -> None:
    with pytest.raises(ValueError, match="exact receipts"):
        bind_runtime_conformance_receipts(("not-a-receipt",), source_revision=REVISION)
