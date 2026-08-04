from __future__ import annotations

import ast
import inspect

import daedalus.gates.repository_write_evidence as evidence


def test_contract_has_no_execution_release_or_promotion_authority() -> None:
    source = inspect.getsource(evidence)
    tree = ast.parse(source)
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
    assert imported.isdisjoint(
        {
            "subprocess",
            "socket",
            "requests",
            "httpx",
            "urllib",
            "sqlite3",
        }
    )
    assert {
        "write_text",
        "write_bytes",
        "mkdir",
        "unlink",
        "replace",
    }.isdisjoint(called)
    assert {"exec", "eval", "compile", "system", "popen"}.isdisjoint(called)
    assert "OwnerApproval" not in source
    assert "PromotionReceipt" not in source
    assert "Gate0ReleaseReceipt" not in source
    assert "begin_effect" not in source


def test_artifact_contract_binds_every_logical_and_content_identity() -> None:
    fields = {
        field.name
        for field in evidence.dataclasses.fields(
            evidence.RepositoryWriteArtifactEvidence
        )
    }
    assert fields == {
        "artifact_id",
        "source_revision",
        "source_tree_revision",
        "gate_report_v3_sha256",
        "inventory_sha256",
        "scan_input_sha256",
        "files_scanned",
        "inventory_generation",
        "failure_set_sha256",
        "failure_count",
        "artifact_content_sha256",
        "locator",
        "built_at",
        "provenance",
    }


def test_locator_and_provenance_are_mechanically_checked() -> None:
    source = inspect.getsource(
        evidence.RepositoryWriteArtifactEvidence.__post_init__
    )
    assert "_locator_sha256(self.locator) != self.artifact_content_sha256" in source
    assert "type(self.provenance) is not ContractProvenance" in source
    for field_name in (
        "gate_report_v3_sha256",
        "inventory_sha256",
        "scan_input_sha256",
        "failure_set_sha256",
        "artifact_content_sha256",
    ):
        assert f"self.{field_name}" in source
    assert "_require_provenance_inputs(" in source


def test_report_binding_uses_exact_v3_and_derived_failure_set() -> None:
    source = inspect.getsource(
        evidence.RepositoryWriteArtifactEvidence.report_binding_blockers
    )
    assert "type(report) is not GateReportV3" in source
    assert 'report_payload["report_sha256"]' in source
    assert "report.repository_write_inventory_sha256" in source
    assert "report.repository_write_scan_input_sha256" in source
    assert "report.repository_write_files_scanned" in source
    assert "report.repository_write_inventory_generation" in source
    assert "canonical_sha(" in source
    assert "list(report.repository_write_failures)" in source
    assert "len(report.repository_write_failures)" in source


def test_contract_does_not_claim_artifact_bytes_were_fetched_or_verified() -> None:
    source = inspect.getsource(evidence)
    assert "read_bytes" not in source
    assert "download" not in source
    assert "signature" not in source.lower()
    assert "trust_bundle" not in source
