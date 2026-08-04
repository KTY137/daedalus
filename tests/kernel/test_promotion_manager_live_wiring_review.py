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


def test_counter_review_limits_append_to_typed_install_and_function_facade() -> None:
    source = PUBLIC.read_text(encoding="utf-8")
    suffix = source.split(MARKER, 1)[1]
    executable = ast.parse(suffix).body
    assert len(executable) == 11

    assert isinstance(executable[0], ast.ImportFrom)
    assert executable[0].module == "functools"
    assert executable[0].level == 0
    assert isinstance(executable[1], ast.ImportFrom)
    assert executable[1].module == "promotion_manager_boundary"
    assert executable[1].level == 1
    assert isinstance(executable[2], ast.ImportFrom)
    assert executable[2].module == "promotion_manager_replay"
    assert executable[2].level == 1

    for node, function_name in zip(
        executable[3:5],
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

    factory = executable[5]
    assert isinstance(factory, ast.FunctionDef)
    assert factory.name == "_make_public_promotion_wrapper"
    assert [argument.arg for argument in factory.args.args] == [
        "callable_",
        "parent",
    ]
    assert len(factory.body) == 2
    nested = factory.body[0]
    assert isinstance(nested, ast.FunctionDef)
    assert nested.name == "public"
    assert len(nested.decorator_list) == 1
    decorator = nested.decorator_list[0]
    assert isinstance(decorator, ast.Call)
    assert isinstance(decorator.func, ast.Name)
    assert decorator.func.id == "_wraps"
    assert isinstance(factory.body[1], ast.Return)

    assignment = executable[6]
    assert isinstance(assignment, ast.Assign)
    assert len(assignment.targets) == 1
    assert isinstance(assignment.targets[0], ast.Name)
    assert assignment.targets[0].id == "promote_candidates"
    assert isinstance(assignment.value, ast.Call)
    assert isinstance(assignment.value.func, ast.Name)
    assert assignment.value.func.id == "_make_public_promotion_wrapper"

    for node, name in zip(
        executable[7:],
        (
            "_make_public_promotion_wrapper",
            "_wraps",
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
