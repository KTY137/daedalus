from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from daedalus.runtimes.provider_executable_structure import (
    ProviderExecutableStructureBindingError,
    ProviderExecutableStructureReceipt,
    ProviderExecutableStructureShapeError,
    verify_provider_executable_structure,
    verify_provider_executable_structure_receipt,
)
from daedalus.runtimes.provider_executable_targets import (
    ProviderExecutableTargetProjection,
)


SOURCE = b'''raise RuntimeError("this module must never be imported")\n\ndef invoke():\n    return "ok"\n\ndef output_digests(value):\n    return ("0" * 64,)\n'''


def _repository(tmp_path: Path, source: bytes = SOURCE) -> tuple[Path, str]:
    package = tmp_path / "daedalus"
    package.mkdir()
    (package / "demo_provider.py").write_bytes(source)
    return tmp_path, hashlib.sha256(source).hexdigest()


def _projection(source_sha256: str) -> ProviderExecutableTargetProjection:
    return ProviderExecutableTargetProjection(
        provider_id="provider_a",
        adapter_id="adapter_a",
        implementation_id="implementation_a",
        entrypoint_id="runtime_provider",
        runtime_id="runtime_a",
        source_revision="a" * 40,
        identity_sha256="1" * 64,
        identity_registry_sha256="2" * 64,
        identity_descriptor_sha256="3" * 64,
        target_manifest_sha256="4" * 64,
        target_descriptor_sha256="5" * 64,
        adapter_artifact_sha256="6" * 64,
        adapter_config_sha256="7" * 64,
        invoke_target="daedalus.demo_provider:invoke",
        invoke_source_sha256=source_sha256,
        output_digests_target="daedalus.demo_provider:output_digests",
        output_digests_source_sha256=source_sha256,
    )


def test_verifies_both_targets_without_importing_source(tmp_path: Path) -> None:
    root, digest = _repository(tmp_path)
    projection = _projection(digest)

    receipt = verify_provider_executable_structure(root, projection)

    assert receipt.provider_id == projection.provider_id
    assert receipt.target_projection_sha256 == projection.digest
    assert receipt.invoke.target == projection.invoke_target
    assert receipt.output_digests.target == projection.output_digests_target
    assert receipt.invoke.source_sha256 == digest
    assert receipt.output_digests.source_sha256 == digest
    assert receipt.to_dict()["targets_structurally_verified"] is True
    assert receipt.to_dict()["repository_bytes_executed"] is False
    assert receipt.to_dict()["provider_execution_allowed"] is False
    assert receipt.to_dict()["source_revision_verified_against_git_head"] is False


def test_receipt_round_trip_and_live_reverification(tmp_path: Path) -> None:
    root, digest = _repository(tmp_path)
    projection = _projection(digest)
    receipt = verify_provider_executable_structure(root, projection)

    parsed = ProviderExecutableStructureReceipt.from_dict(receipt.to_dict())

    assert parsed == receipt
    assert parsed.digest == receipt.digest
    verify_provider_executable_structure_receipt(root, projection, parsed)


def test_changed_source_refuses_before_any_execution(tmp_path: Path) -> None:
    root, digest = _repository(tmp_path)
    projection = _projection(digest)
    (root / "daedalus" / "demo_provider.py").write_bytes(
        SOURCE.replace(b'return "ok"', b'return "changed"')
    )

    with pytest.raises(ProviderExecutableStructureBindingError):
        verify_provider_executable_structure(root, projection)


def test_missing_output_target_refuses(tmp_path: Path) -> None:
    source = SOURCE.replace(b"def output_digests", b"def renamed_output_digests")
    root, digest = _repository(tmp_path, source)

    with pytest.raises(ProviderExecutableStructureBindingError):
        verify_provider_executable_structure(root, _projection(digest))


def test_projection_substitution_invalidates_retained_receipt(tmp_path: Path) -> None:
    root, digest = _repository(tmp_path)
    projection = _projection(digest)
    receipt = verify_provider_executable_structure(root, projection)
    substituted = replace(projection, target_manifest_sha256="8" * 64)

    with pytest.raises(ProviderExecutableStructureBindingError):
        verify_provider_executable_structure_receipt(root, substituted, receipt)


def test_detached_receipt_identity_refuses(tmp_path: Path) -> None:
    root, digest = _repository(tmp_path)
    projection = _projection(digest)
    receipt = verify_provider_executable_structure(root, projection)
    detached = replace(receipt, provider_id="provider_b")

    with pytest.raises(ProviderExecutableStructureBindingError):
        verify_provider_executable_structure_receipt(root, projection, detached)


def test_wire_authority_escalation_refuses(tmp_path: Path) -> None:
    root, digest = _repository(tmp_path)
    receipt = verify_provider_executable_structure(root, _projection(digest))
    payload = receipt.to_dict()
    payload["provider_execution_allowed"] = True

    with pytest.raises(ProviderExecutableStructureShapeError):
        ProviderExecutableStructureReceipt.from_dict(payload)


def test_git_head_claim_escalation_refuses(tmp_path: Path) -> None:
    root, digest = _repository(tmp_path)
    receipt = verify_provider_executable_structure(root, _projection(digest))
    payload = receipt.to_dict()
    payload["source_revision_verified_against_git_head"] = True

    with pytest.raises(ProviderExecutableStructureShapeError):
        ProviderExecutableStructureReceipt.from_dict(payload)


def test_exact_projection_and_receipt_types_are_required(tmp_path: Path) -> None:
    root, digest = _repository(tmp_path)
    projection = _projection(digest)
    receipt = verify_provider_executable_structure(root, projection)

    with pytest.raises(ProviderExecutableStructureShapeError):
        verify_provider_executable_structure(root, object())  # type: ignore[arg-type]
    with pytest.raises(ProviderExecutableStructureShapeError):
        verify_provider_executable_structure_receipt(
            root, projection, object()  # type: ignore[arg-type]
        )
    with pytest.raises(ProviderExecutableStructureShapeError):
        verify_provider_executable_structure(
            str(root), projection  # type: ignore[arg-type]
        )
    verify_provider_executable_structure_receipt(root, projection, receipt)
