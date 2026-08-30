# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import dataclasses
import inspect

import daedalus.gates.repository_write_artifact_verifier as verifier


def _source_without_docstrings(module) -> str:
    """Module source with docstring prose stripped.

    A docstring may legitimately *deny* an authority by name ("does not issue
    OwnerApproval"); only executable code proves the module actually holds it.
    """

    source = inspect.getsource(module)
    tree = ast.parse(source)
    drop: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node,
            (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            continue
        if ast.get_docstring(node, clean=False) is None:
            continue
        literal = node.body[0]
        drop.update(
            range(literal.lineno, (literal.end_lineno or literal.lineno) + 1)
        )
    return "".join(
        line
        for number, line in enumerate(source.splitlines(keepends=True), 1)
        if number not in drop
    )


def test_verifier_has_no_locator_resolution_release_or_effect_authority() -> None:
    source = inspect.getsource(verifier)
    code = _source_without_docstrings(verifier)
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
        "open",
        "read_bytes",
        "read_text",
        "write_bytes",
        "write_text",
        "mkdir",
        "unlink",
        "replace",
    }.isdisjoint(called)
    assert {"exec", "eval", "compile", "system", "popen"}.isdisjoint(called)
    assert "OwnerApproval" not in code
    assert "PromotionReceipt" not in code
    assert "Gate0ReleaseReceipt" not in code
    assert "begin_effect" not in code
    assert "resolve_locator" not in code
    assert "verify_signature" not in code


def test_verifier_rejects_non_exact_subjects_and_bytes_before_hashing() -> None:
    source = inspect.getsource(verifier.verify_repository_write_artifact)
    artifact_check = source.index(
        "type(artifact) is not RepositoryWriteArtifactEvidence"
    )
    report_check = source.index("type(report) is not GateReportV3")
    bytes_check = source.index("_validated_artifact_bytes(artifact_bytes)")
    hash_call = source.index("hashlib.sha256(exact_bytes)")
    assert artifact_check < hash_call
    assert report_check < hash_call
    assert bytes_check < hash_call
    bytes_source = inspect.getsource(verifier._validated_artifact_bytes)
    assert "type(raw) is not bytes" in bytes_source
    assert "not raw or len(raw) > _MAX_ARTIFACT_BYTES" in bytes_source


def test_strict_parser_reconstructs_and_compares_canonical_inventory() -> None:
    source = inspect.getsource(verifier._strict_inventory_from_bytes)
    assert "object_pairs_hook=_reject_duplicate_keys" in source
    assert "parse_constant=_reject_json_constant" in source
    assert "set(payload) != _ROOT_FIELDS" in source
    assert "set(components) != _COMPONENT_FIELDS" in source
    assert "set(row) != _SURFACE_FIELDS" in source
    assert "RepositoryWriteSurface(**row)" in source
    assert "RepositoryWriteInventoryV2(" in source
    # The canonical payload is bound to a local so the same value also fences
    # the raw bytes; both comparisons must survive.
    assert "canonical_payload = inventory.to_dict()" in source
    assert "payload != canonical_payload" in source
    assert (
        'exact != canonical_json(canonical_payload).encode("ascii")' in source
    )


def test_verifier_checks_every_artifact_inventory_binding() -> None:
    source = inspect.getsource(verifier.verify_repository_write_artifact)
    assert "artifact.report_binding_blockers(report)" in source
    assert "inventory.source_revision != artifact.source_revision" in source
    assert "inventory.digest != artifact.inventory_sha256" in source
    assert "inventory.scan_input_sha256 != artifact.scan_input_sha256" in source
    assert "inventory.files_scanned != artifact.files_scanned" in source
    assert "canonical_sha(list(failures)) != artifact.failure_set_sha256" in source
    assert "len(failures) != artifact.failure_count" in source


def test_receipt_contract_has_exact_identity_and_provenance_fields() -> None:
    fields = {
        field.name
        for field in dataclasses.fields(
            verifier.RepositoryWriteArtifactVerificationReceipt
        )
    }
    assert fields == {
        "verification_id",
        "source_revision",
        "source_tree_revision",
        "gate_report_v3_sha256",
        "artifact_evidence_sha256",
        "artifact_content_sha256",
        "inventory_sha256",
        "verified_at",
        "checks",
        "provenance",
    }
    source = inspect.getsource(
        verifier.RepositoryWriteArtifactVerificationReceipt.__post_init__
    )
    assert "self.checks != _VERIFICATION_CHECKS" in source
    assert "type(self.provenance) is not ContractProvenance" in source
    assert "_require_provenance_inputs(" in source


def test_verification_receipt_does_not_claim_git_or_signer_authentication() -> None:
    fields = {
        field.name
        for field in dataclasses.fields(
            verifier.RepositoryWriteArtifactVerificationReceipt
        )
    }
    assert "signer_id" not in fields
    assert "signature" not in fields
    assert "current_head" not in fields
    assert "current_tree" not in fields
    assert "owner_approval" not in fields
