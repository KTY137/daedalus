# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
from pathlib import Path


TARGET = (
    Path(__file__).resolve().parents[2]
    / "daedalus/gates/guard_implementation_manifest.py"
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


def test_module_is_inert_and_accepts_no_callback_authority() -> None:
    tree = _tree()
    source = TARGET.read_text(encoding="utf-8")
    forbidden_imports = {
        "os",
        "pathlib",
        "sqlite3",
        "subprocess",
        "tempfile",
        "shutil",
        "docker",
        "git",
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

    forbidden_calls = {
        "open",
        "write_text",
        "write_bytes",
        "mkdir",
        "unlink",
        "replace",
        "rename",
        "subprocess.run",
        "subprocess.Popen",
    }
    calls = {
        _call_name(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert not calls.intersection(forbidden_calls)


def test_issue_path_signs_the_zero_signature_subject_only() -> None:
    tree = _tree()
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "issue_guard_implementation_manifest"
    )
    calls = [
        (_call_name(node), node.lineno)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    manifest_lines = [
        line
        for name, line in calls
        if name == "GuardImplementationManifest"
    ]
    signature_lines = [
        line
        for name, line in calls
        if name == "_signature"
    ]
    replace_lines = [
        line
        for name, line in calls
        if name == "dataclasses.replace"
    ]
    assert len(manifest_lines) == len(signature_lines) == len(replace_lines) == 1
    assert manifest_lines[0] < replace_lines[0]
    source = ast.get_source_segment(
        TARGET.read_text(encoding="utf-8"),
        function,
    )
    assert source is not None
    assert 'signature_sha256="0" * 64' in source
    assert "unsigned.signing_digest" in source


def test_verifier_authenticates_before_projecting_signed_bindings() -> None:
    tree = _tree()
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "verify_guard_implementation_manifest"
    )
    source = TARGET.read_text(encoding="utf-8")
    segment = ast.get_source_segment(source, function)
    assert segment is not None
    signature_index = segment.index("hmac.compare_digest")
    authority_index = segment.index("manifest.authority_id != authority_id")
    revision_index = segment.index("manifest.source_revision != revision")
    classification_index = segment.index(
        "manifest.classification_digest != classification_digest"
    )
    time_index = segment.index('instant = _as_utc(now, "now")')
    assert signature_index < authority_index
    assert signature_index < revision_index
    assert signature_index < classification_index
    assert classification_index < time_index


def test_wire_parser_is_bounded_strict_and_canonical() -> None:
    source = TARGET.read_text(encoding="utf-8")
    required = {
        "_MAX_MANIFEST_BYTES",
        'raw.startswith(b"\\xef\\xbb\\xbf")',
        'b"\\x00" in raw',
        "object_pairs_hook=_reject_duplicate_keys",
        "parse_constant=_reject_nonfinite",
        "raw != canonical",
        "_require_exact_keys(",
    }
    for fragment in required:
        assert fragment in source


def test_report_cannot_launder_semantics_or_gate_authority() -> None:
    source = TARGET.read_text(encoding="utf-8")
    for claim in (
        '"guard_contract_semantics_verified": False',
        '"semantic_receipts_verified": False',
        '"evidence_authenticated": False',
        '"gate_report_bound": False',
        '"closed": False',
    ):
        assert source.count(claim) == 1
    assert source.count('"guard_manifest_authenticated": True') == 1
    for blocker in (
        "effect-lease-semantic-verification-missing",
        "gate-report-binding-missing",
        "guard-contract-semantic-replay-missing",
        "primary-checkout-disjointness-semantic-verification-missing",
        "retirement-semantic-verification-missing",
        "runtime-conformance-semantic-verification-missing",
        "source-anchor-chain-binding-missing",
    ):
        assert source.count(blocker) == 1


def test_module_does_not_import_classification_or_effect_authority() -> None:
    source = TARGET.read_text(encoding="utf-8")
    assert "repository_write_classification" not in source
    assert "effect_boundary" not in source
    assert "EffectLease" not in source
    assert "OwnerApproval" not in source
    assert "PromotionReceipt" not in source
