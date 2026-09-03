from __future__ import annotations

import dataclasses
import hashlib
import json

import pytest

from daedalus.gates.report_v3 import GateReportV3
from daedalus.gates.repository.write_artifact_verifier import (
    RepositoryWriteArtifactVerificationError,
    RepositoryWriteArtifactVerificationReceipt,
    verify_repository_write_artifact,
)
from daedalus.gates.repository.write_evidence import (
    RepositoryWriteArtifactEvidence,
)
from daedalus.gates.repository.write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json, canonical_sha


REVISION = "1" * 40
TREE = "2" * 40
BUILT_AT = "2026-08-04T20:00:00+00:00"
VERIFIED_AT = "2026-08-04T20:01:00+00:00"


def _inventory(**changes) -> RepositoryWriteInventoryV2:
    inventory = RepositoryWriteInventoryV2(
        source_revision=REVISION,
        package_root="daedalus",
        scan_input_sha256="3" * 64,
        files_scanned=1,
        base_inventory_digest="4" * 64,
        stdlib_delta_digest="5" * 64,
        surfaces=(
            RepositoryWriteSurface(
                path="daedalus/example.py",
                line=7,
                column=4,
                origin="base_v1",
                kind="path-write",
                callee="Path.write_text",
                operation="write_text",
                blocking=True,
            ),
        ),
    )
    return dataclasses.replace(inventory, **changes)


def _failures(inventory: RepositoryWriteInventoryV2) -> tuple[str, ...]:
    return tuple(
        f"{surface.path}:{surface.line}:{surface.column}:"
        f"{surface.kind}:{surface.callee}:{surface.operation}"
        for surface in inventory.blockers
    )


def _report(
    inventory: RepositoryWriteInventoryV2 | None = None,
    **changes,
) -> GateReportV3:
    bound = inventory or _inventory()
    report = GateReportV3(
        gate=0,
        source_revision=bound.source_revision,
        registry_sha256="6" * 64,
        security_boundary_claimed=False,
        event_store_writer_inventory_sha256="7" * 64,
        repository_write_inventory_sha256=bound.digest,
        repository_write_scan_input_sha256=bound.scan_input_sha256,
        repository_write_files_scanned=bound.files_scanned,
        repository_write_inventory_generation=2,
        repository_write_failures=_failures(bound),
    )
    return dataclasses.replace(report, **changes)


def _bytes(inventory: RepositoryWriteInventoryV2 | None = None) -> bytes:
    bound = inventory or _inventory()
    return canonical_json(bound.to_dict()).encode("ascii")


def _artifact(
    report: GateReportV3,
    artifact_bytes: bytes,
    **changes,
) -> RepositoryWriteArtifactEvidence:
    values = {
        "artifact_id": "artifact.repository-write-inventory",
        "source_revision": report.source_revision,
        "source_tree_revision": TREE,
        "gate_report_v3_sha256": report.to_dict()["report_sha256"],
        "inventory_sha256": report.repository_write_inventory_sha256,
        "scan_input_sha256": report.repository_write_scan_input_sha256,
        "files_scanned": report.repository_write_files_scanned,
        "inventory_generation": report.repository_write_inventory_generation,
        "failure_set_sha256": canonical_sha(
            list(report.repository_write_failures)
        ),
        "failure_count": len(report.repository_write_failures),
        "artifact_content_sha256": hashlib.sha256(artifact_bytes).hexdigest(),
        "built_at": BUILT_AT,
    }
    values.update(changes)
    values.setdefault(
        "locator",
        f"artifact-locator:sha256:{values['artifact_content_sha256']}",
    )
    values["provenance"] = ContractProvenance(
        origin="gate0.repository-write-artifact",
        source_revision=values["source_revision"],
        created_at=values["built_at"],
        input_digests=(
            values["gate_report_v3_sha256"],
            values["inventory_sha256"],
            values["scan_input_sha256"],
            values["failure_set_sha256"],
            values["artifact_content_sha256"],
        ),
    )
    return RepositoryWriteArtifactEvidence(**values)


def _verify(
    artifact: RepositoryWriteArtifactEvidence,
    report: GateReportV3,
    artifact_bytes: bytes,
) -> RepositoryWriteArtifactVerificationReceipt:
    return verify_repository_write_artifact(
        artifact,
        report,
        artifact_bytes,
        verification_id="verification.repository-write-artifact",
        verified_at=VERIFIED_AT,
    )


def test_exact_bytes_inventory_report_and_evidence_produce_receipt() -> None:
    inventory = _inventory()
    raw = _bytes(inventory)
    report = _report(inventory)
    artifact = _artifact(report, raw)
    receipt = _verify(artifact, report, raw)
    assert receipt.source_revision == REVISION
    assert receipt.source_tree_revision == TREE
    assert receipt.gate_report_v3_sha256 == report.to_dict()["report_sha256"]
    assert receipt.artifact_evidence_sha256 == artifact.digest
    assert receipt.artifact_content_sha256 == hashlib.sha256(raw).hexdigest()
    assert receipt.inventory_sha256 == inventory.digest
    assert receipt.checks == tuple(sorted(receipt.checks))
    assert type(receipt.provenance) is ContractProvenance
    assert RepositoryWriteArtifactVerificationReceipt.from_dict(
        receipt.to_dict()
    ) == receipt


def test_artifact_byte_substitution_refuses_before_parsing() -> None:
    raw = _bytes()
    report = _report()
    artifact = _artifact(report, raw)
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="byte digest contradicts",
    ):
        _verify(artifact, report, raw + b" ")


@pytest.mark.parametrize(
    "raw,match",
    [
        (b"", "size is invalid"),
        (b"\xff", "must be UTF-8"),
        (b"{", "malformed JSON"),
        (b'{"value":NaN}', "non-finite"),
    ],
)
def test_malformed_artifact_bytes_refuse(raw: bytes, match: str) -> None:
    report = _report()
    artifact = _artifact(report, raw)
    with pytest.raises(RepositoryWriteArtifactVerificationError, match=match):
        _verify(artifact, report, raw)


def test_duplicate_json_keys_refuse() -> None:
    raw = _bytes()
    text = raw.decode("ascii")
    duplicated = (
        '{"schema":"daedalus-gate0-repository-write-inventory/2",'
        + text[1:]
    ).encode("ascii")
    report = _report()
    artifact = _artifact(report, duplicated)
    with pytest.raises(RepositoryWriteArtifactVerificationError, match="duplicate"):
        _verify(artifact, report, duplicated)


def test_oversized_artifact_refuses() -> None:
    raw = b" " * (16 * 1024 * 1024 + 1)
    report = _report()
    artifact = _artifact(report, raw)
    with pytest.raises(RepositoryWriteArtifactVerificationError, match="size is invalid"):
        _verify(artifact, report, raw)


@pytest.mark.parametrize(
    "mutator,match",
    [
        (
            lambda payload: payload.update(extra="forbidden"),
            "root fields are not exact",
        ),
        (
            lambda payload: payload.update(schema="foreign-schema"),
            "schema is unsupported",
        ),
        (
            lambda payload: payload["components"].update(extra="forbidden"),
            "component fields are not exact",
        ),
        (
            lambda payload: payload["surfaces"][0].update(extra="forbidden"),
            "surface fields are not exact",
        ),
        (
            lambda payload: payload.update(surface_count=99),
            "payload is non-canonical",
        ),
        (
            lambda payload: payload.update(closed=True),
            "payload is non-canonical",
        ),
    ],
)
def test_malformed_or_noncanonical_inventory_payload_refuses(mutator, match: str) -> None:
    inventory = _inventory()
    payload = inventory.to_dict()
    mutator(payload)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    report = _report(inventory)
    artifact = _artifact(report, raw)
    with pytest.raises(RepositoryWriteArtifactVerificationError, match=match):
        _verify(artifact, report, raw)


@pytest.mark.parametrize(
    "report_changes,match",
    [
        (
            {"repository_write_inventory_sha256": "8" * 64},
            "inventory digest contradicts evidence",
        ),
        (
            {"repository_write_scan_input_sha256": "9" * 64},
            "scan-input digest contradicts evidence",
        ),
        (
            {"repository_write_files_scanned": 2},
            "file count contradicts evidence",
        ),
        (
            {"repository_write_failures": ("wrong.py:1:0:write",)},
            "failure-set digest contradicts evidence",
        ),
        (
            {"source_revision": "a" * 40},
            "source revision contradicts evidence",
        ),
    ],
)
def test_inventory_bytes_must_match_report_and_artifact_claims(
    report_changes,
    match: str,
) -> None:
    inventory = _inventory()
    raw = _bytes(inventory)
    report = _report(inventory, **report_changes)
    artifact = _artifact(report, raw)
    with pytest.raises(RepositoryWriteArtifactVerificationError, match=match):
        _verify(artifact, report, raw)


def test_foreign_gate_report_refuses_before_inventory_acceptance() -> None:
    inventory = _inventory()
    raw = _bytes(inventory)
    report = _report(inventory)
    artifact = _artifact(report, raw)
    foreign = dataclasses.replace(report, registry_sha256="b" * 64)
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="contradicts GateReport-v3",
    ):
        _verify(artifact, foreign, raw)


def test_receipt_tampering_refuses_exact_checks_and_provenance() -> None:
    inventory = _inventory()
    raw = _bytes(inventory)
    report = _report(inventory)
    artifact = _artifact(report, raw)
    receipt = _verify(artifact, report, raw)

    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="checks are not exact",
    ):
        dataclasses.replace(receipt, checks=receipt.checks[:-1])

    missing_input = dataclasses.replace(
        receipt.provenance,
        input_digests=receipt.provenance.input_digests[:-1],
    )
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="does not bind referenced input",
    ):
        dataclasses.replace(receipt, provenance=missing_input)
