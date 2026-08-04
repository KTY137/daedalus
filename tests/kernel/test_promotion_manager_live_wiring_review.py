from __future__ import annotations

import ast
import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PUBLIC = ROOT / "daedalus" / "kairos" / "gated_writes.py"
PARENT_GIT_BLOB_SHA1 = "56fb2bac50b7675e1c41c259b5bd5da9573b1ac5"
MARKER = "\n\n# Install the manager audit only after the sealed public callable exists."


def _git_blob_sha1(payload: bytes) -> str:
    header = f"blob {len(payload)}\0".encode("ascii")
    return hashlib.sha1(
        header + payload,
        usedforsecurity=False,
    ).hexdigest()


def test_counter_review_proves_parent_public_module_is_byte_identical_prefix() -> None:
    payload = PUBLIC.read_bytes()
    marker = MARKER.encode("utf-8")
    assert payload.count(marker) == 1
    prefix, suffix = payload.split(marker, 1)
    assert _git_blob_sha1(prefix) == PARENT_GIT_BLOB_SHA1
    assert suffix.startswith("\n# installers preserve the public PromotionExecutionLedger")


def test_counter_review_limits_append_to_two_imports_calls_and_deletions() -> None:
    source = PUBLIC.read_text(encoding="utf-8")
    suffix = source.split(MARKER, 1)[1]
    tree = ast.parse(suffix)
    executable = [node for node in tree.body if not isinstance(node, ast.Expr)]
    assert len(executable) == 6
    assert isinstance(executable[0], ast.ImportFrom)
    assert executable[0].module == "promotion_manager_boundary"
    assert isinstance(executable[1], ast.ImportFrom)
    assert executable[1].module == "promotion_manager_replay"
    for node, function_name in zip(
        executable[2:4],
        (
            "_install_promotion_manager_boundary",
            "_install_promotion_manager_replay_boundary",
        ),
        strict=True,
    ):
        assert isinstance(node, ast.Expr)
        assert isinstance(node.value, ast.Call)
        assert isinstance(node.value.func, ast.Name)
        assert node.value.func.id == function_name
        assert len(node.value.args) == 1
        argument = node.value.args[0]
        assert isinstance(argument, ast.Call)
        assert isinstance(argument.func, ast.Name)
        assert argument.func.id == "globals"
    for node, name in zip(
        executable[4:],
        (
            "_install_promotion_manager_boundary",
            "_install_promotion_manager_replay_boundary",
        ),
        strict=True,
    ):
        assert isinstance(node, ast.Delete)
        assert len(node.targets) == 1
        assert isinstance(node.targets[0], ast.Name)
        assert node.targets[0].id == name


def test_counter_review_does_not_change_export_or_authority_surface() -> None:
    source = PUBLIC.read_text(encoding="utf-8")
    prefix, suffix = source.split(MARKER, 1)
    assert prefix.count("__all__ = tuple(") == 1
    assert "__all__" not in suffix
    lowered = suffix.lower()
    for forbidden in (
        "issue_owner_approval",
        "effectlease",
        "subprocess",
        "git worktree",
        "git merge",
        "closed=true",
        "automatic promotion",
    ):
        assert forbidden not in lowered
