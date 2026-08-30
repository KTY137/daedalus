# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
from pathlib import Path


TARGET = (
    Path(__file__).resolve().parents[2]
    / "daedalus/gates/repository_write_source_anchor_semantics.py"
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


def test_module_has_read_only_authority_and_no_callback_smuggling() -> None:
    tree = _tree()
    source = TARGET.read_text(encoding="utf-8")
    forbidden_imports = {
        "subprocess",
        "sqlite3",
        "docker",
        "git",
        "shutil",
        "tempfile",
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
        "write_text",
        "write_bytes",
        "mkdir",
        "touch",
        "unlink",
        "replace",
        "rename",
        "remove",
        "rmdir",
        "subprocess.run",
        "subprocess.Popen",
        "os.system",
    }
    calls = {_call_name(node) for node in ast.walk(tree) if isinstance(node, ast.Call)}
    assert not calls.intersection(forbidden_calls)
    assert "os.open" in calls
    assert "os.read" in calls
    assert "os.write" not in calls


def test_public_verifier_reauthenticates_before_tree_projection() -> None:
    tree = _tree()
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "verify_repository_write_source_anchor_semantics"
    )
    calls = [
        (_call_name(node), node.lineno)
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
    ]
    materialize = [
        line
        for name, line in calls
        if name == "materialize_repository_write_evidence"
    ]
    authenticate = [
        line
        for name, line in calls
        if name == "verify_repository_write_evidence_origin"
    ]
    resolve_root = [line for name, line in calls if name == "_resolve_repository_root"]
    read_source = [line for name, line in calls if name == "_read_exact_source"]
    assert len(materialize) == len(authenticate) == len(resolve_root) == 1
    assert materialize[0] < authenticate[0] < resolve_root[0] < read_source[0]


def test_exact_one_anchor_position_digest_and_chain_fences_are_present() -> None:
    source = TARGET.read_text(encoding="utf-8")
    required = {
        "if len(source_bindings) != 1:",
        "path != row.surface.path",
        "line != row.surface.line",
        "column != row.surface.column",
        "hashlib.sha256(source).hexdigest() != source_sha256",
        "if selected[column : column + 1].isspace():",
        "if mismatches:",
        "surface_binding_sha256(revision, row.surface)",
    }
    for fragment in required:
        assert source.count(fragment) == 1


def test_source_open_is_no_follow_bounded_and_identity_checked() -> None:
    source = TARGET.read_text(encoding="utf-8")
    assert "os.O_RDONLY" in source
    assert "os.O_NOFOLLOW" in source
    assert "os.O_WRONLY" not in source
    assert "os.O_RDWR" not in source
    assert "_MAX_SOURCE_BYTES" in source
    assert "before.st_dev, before.st_ino" in source
    assert "after.st_dev, after.st_ino" in source
    assert "final_path.st_dev, final_path.st_ino" in source
    assert "source anchor path contains a symlink" in source


def test_report_cannot_launder_remaining_semantics_or_gate_authority() -> None:
    source = TARGET.read_text(encoding="utf-8")
    for false_claim in (
        '"semantic_receipts_verified": False',
        '"evidence_authenticated": False',
        '"gate_report_bound": False',
        '"closed": False',
    ):
        assert source.count(false_claim) == 1
    for blocker in (
        "effect-lease-semantic-verification-missing",
        "guard-contract-semantic-verification-missing",
        "primary-checkout-disjointness-semantic-verification-missing",
        "retirement-semantic-verification-missing",
        "runtime-conformance-semantic-verification-missing",
        "gate-report-binding-missing",
    ):
        assert source.count(blocker) == 1
    assert '"source_anchor_semantics_verified": True' in source
    assert '"origin_authenticated": True' in source
