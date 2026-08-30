# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
from pathlib import Path


TARGET = (
    Path(__file__).resolve().parents[2]
    / "daedalus/gates/repository_write_guard_structure.py"
)


def _tree() -> ast.Module:
    return ast.parse(TARGET.read_text(encoding="utf-8"))


def _call_name(node: ast.Call) -> str:
    current = node.func
    parts: list[str] = []
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def test_module_is_read_only_and_accepts_no_callback_authority() -> None:
    tree = _tree()
    source = TARGET.read_text(encoding="utf-8")
    forbidden_imports = {
        "os",
        "subprocess",
        "sqlite3",
        "socket",
        "docker",
        "git",
        "shutil",
        "tempfile",
        "importlib",
        "runpy",
    }
    imported = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert not imported.intersection(forbidden_imports)
    assert "Callable" not in source
    assert "Protocol" not in source
    assert "**kwargs" not in source

    calls = {
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    for forbidden in (
        "open",
        "write_text",
        "write_bytes",
        "mkdir",
        "unlink",
        "replace",
        "rename",
        "subprocess.run",
        "subprocess.Popen",
        "exec",
        "eval",
    ):
        assert forbidden not in calls


def test_public_verifier_reauthenticates_before_payload_projection() -> None:
    tree = _tree()
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "verify_repository_write_guard_structure"
    )
    calls = [
        (_call_name(node), node.lineno)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    source_anchor = [
        line
        for name, line in calls
        if name == "verify_repository_write_source_anchor_semantics"
    ]
    materialize = [
        line
        for name, line in calls
        if name == "materialize_repository_write_evidence"
    ]
    manifest = [
        line
        for name, line in calls
        if name == "verify_guard_implementation_manifest"
    ]
    chain = [line for name, line in calls if name == "_verify_chain"]
    payload = [line for name, line in calls if name == "_guard_payload"]
    structure = [
        line
        for name, line in calls
        if name == "resolve_python_target_structure"
    ]
    assert len(source_anchor) == len(materialize) == len(manifest) == len(chain) == 1
    assert len(payload) == len(structure) == 1
    assert source_anchor[0] < materialize[0] < manifest[0] < chain[0]
    assert chain[0] < payload[0] < structure[0]


def _function_source(name: str) -> str:
    source = TARGET.read_text(encoding="utf-8")
    matches = [
        node
        for node in _tree().body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == name
    ]
    assert len(matches) == 1
    return ast.get_source_segment(source, matches[0]) or ""


def test_complete_cross_layer_digest_chain_is_rechecked() -> None:
    # Scope the count to the chain verifier: several of these keys are also
    # legitimate receipt fields and to_dict() keys elsewhere in the module.
    source = _function_source("_verify_chain")
    required = {
        '"materialization_revision"',
        '"materialization_classification"',
        '"source_anchor_revision"',
        '"source_anchor_classification"',
        '"source_anchor_materialization"',
        '"source_anchor_attestation"',
        '"guard_manifest_revision"',
        '"guard_manifest_classification"',
        '"guard_manifest_digest"',
        '"guard_manifest_entry_set"',
        "if mismatches:",
    }
    for fragment in required:
        assert source.count(fragment) == 1


def test_guard_coverage_is_non_vacuous_exact_and_structural() -> None:
    source = TARGET.read_text(encoding="utf-8")
    required = {
        "if not production_rows:",
        "row.guard not in allowed_guards",
        "or not row.guard_contracts",
        "if not required_contracts:",
        "if set(manifest_by_contract) != required_contracts:",
        "len(bindings) != 1",
        "surface_binding_sha256(revision, row.surface)",
        "_verify_manifest_entry(",
        "resolve_python_target_structure(",
    }
    for fragment in required:
        assert fragment in source


def test_blob_mapping_is_snapshotted_before_reuse() -> None:
    source = TARGET.read_text(encoding="utf-8")
    assert source.count("snapshot = _snapshot_blobs(blobs)") == 1
    assert source.count("dict(blobs.items())") == 1
    assert "classification,\n        snapshot," in source
    assert "materialize_repository_write_evidence(\n        classification,\n        snapshot," in source
    assert "raw = snapshot.get(binding.locator)" in source


def test_report_cannot_launder_structure_into_guard_semantics_or_gate() -> None:
    source = TARGET.read_text(encoding="utf-8")
    true_claims = (
        '"origin_authenticated": True',
        '"source_anchor_semantics_verified": True',
        '"guard_manifest_authenticated": True',
        '"guard_contract_structure_verified": True',
    )
    false_claims = (
        '"guard_contract_semantics_verified": False',
        '"semantic_receipts_verified": False',
        '"evidence_authenticated": False',
        '"gate_report_bound": False',
        '"closed": False',
    )
    for claim in (*true_claims, *false_claims):
        assert source.count(claim) == 1
    for blocker in (
        "effect-lease-semantic-verification-missing",
        "gate-report-binding-missing",
        "guard-contract-behavioral-verification-missing",
        "primary-checkout-disjointness-semantic-verification-missing",
        "retirement-semantic-verification-missing",
        "runtime-conformance-semantic-verification-missing",
    ):
        assert source.count(blocker) == 1
    for forbidden in (
        "OwnerApproval",
        "PromotionReceipt",
        "begin_effect",
        "issue_owner_approval",
        "promote",
    ):
        assert forbidden not in source


def test_record_binds_evidence_surface_and_exact_target_structure() -> None:
    source = TARGET.read_text(encoding="utf-8")
    for fragment in (
        '"surface_sha256": self.surface_sha256',
        '"locator": self.locator',
        '"contract": self.contract',
        '"implementation_target": self.implementation_target',
        '"implementation_sha256": self.implementation_sha256',
        '"source_path": self.source_path',
        '"source_size": self.source_size',
        '"definition_kind": self.definition_kind',
        '"line": self.line',
        '"column": self.column',
        '"end_line": self.end_line',
        '"end_column": self.end_column',
        "self.structure_sha256 != expected_structure",
    ):
        assert fragment in source
