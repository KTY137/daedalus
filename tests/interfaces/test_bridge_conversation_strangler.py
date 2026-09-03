from __future__ import annotations

import ast
from pathlib import Path

import pytest

from daedalus import file_bridge
from daedalus.interfaces.bridge import conversation
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "file_bridge.py"
IMPLEMENTATION = (
    ROOT / "daedalus" / "interfaces" / "bridge" / "conversation.py"
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _function(path: Path, name: str) -> ast.FunctionDef:
    matches = [
        node
        for node in _tree(path).body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def _attribute_calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        child
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and isinstance(child.func, ast.Attribute)
        and child.func.attr == name
    ]


def test_legacy_conversation_exceptions_are_the_owner_objects() -> None:
    assert (
        file_bridge.ConversationProjectionPending
        is conversation.ConversationProjectionPending
    )
    assert (
        file_bridge.ConversationProjectionFailed
        is conversation.ConversationProjectionFailed
    )


def test_legacy_conversation_helpers_delegate_to_the_owner() -> None:
    owners = {
        "_is_transient_projection_failure": "is_transient_projection_failure",
        "_project_report_to_conversation": "project_report",
        "_requeue_for_projection": "requeue_for_projection",
    }
    for facade_name, owner_name in owners.items():
        wrapper = _function(FACADE, facade_name)
        assert len(_attribute_calls(wrapper, owner_name)) == 1

    reconcile = _function(FACADE, "reconcile_conversation_report")
    assert len(_attribute_calls(reconcile, "prepare_reconciliation")) == 1
    assert len(_attribute_calls(reconcile, "finish_reconciliation")) == 1


def test_reconcile_effect_admission_precedes_projection_owner() -> None:
    wrapper = _function(FACADE, "reconcile_conversation_report")
    begin = [
        node
        for node in ast.walk(wrapper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "begin_effect"
    ]
    finish = _attribute_calls(wrapper, "finish_reconciliation")

    assert len(begin) == 1
    assert len(finish) == 1
    assert begin[0].lineno < finish[0].lineno


def test_conversation_owner_has_no_reverse_facade_or_effect_authority() -> None:
    tree = _tree(IMPLEMENTATION)
    imports: set[str] = set()
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.add(node.func.id)

    assert not any(name.startswith("daedalus") for name in imports)
    assert not {"begin_effect", "run_mission", "Popen"} & called_names
    assert not {"socket", "sqlite3", "subprocess"} & imports


def test_prepare_reconciliation_is_fixed_to_the_inbox(tmp_path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    report = {"request_file": "task", "bridge_status": "done"}

    prepared = conversation.prepare_reconciliation(
        "task",
        inbox=inbox,
        completed_report=lambda path: report,
    )

    assert prepared == ("task", report)
    with pytest.raises(ValueError, match="plain file-bridge request key"):
        conversation.prepare_reconciliation(
            "../outside",
            inbox=inbox,
            completed_report=lambda path: report,
        )


def test_projection_retry_requires_the_existing_report_step(tmp_path) -> None:
    archive = tmp_path / "archive"
    outbox = tmp_path / "outbox"
    archive.mkdir()
    (archive / "task.json").write_text("{}", encoding="utf-8")

    assert conversation.requeue_for_projection(
        "task",
        archive=archive,
        outbox=outbox,
        read_journal=lambda key: {"steps": {}},
        replace=lambda source, target: pytest.fail("must not move"),
        move=lambda source, target: pytest.fail("must not move"),
        move_error=RuntimeError,
    ) is False


def test_structure_packet_does_not_change_effect_registry() -> None:
    assert registry_sha256() == (
        "44222aa9f9269eb1c9d9f5cf118786cbb1a1d602f6f3ca77aeb00d4f599214c9"
    )
