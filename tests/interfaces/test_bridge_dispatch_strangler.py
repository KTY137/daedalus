from __future__ import annotations

import ast
from contextlib import contextmanager
from pathlib import Path

import pytest

from daedalus.interfaces.bridge import dispatch
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "file_bridge.py"
IMPLEMENTATION = ROOT / "daedalus" / "interfaces" / "bridge" / "dispatch.py"


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


def test_registered_process_effect_precedes_claimed_dispatch_owner() -> None:
    wrapper = _function(FACADE, "process_request")
    begin = [
        node
        for node in ast.walk(wrapper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "begin_effect"
    ]
    dispatches = _attribute_calls(wrapper, "claim_and_dispatch_request")
    assert len(begin) == 1
    assert len(dispatches) == 1
    assert begin[0].lineno < dispatches[0].lineno


def test_dispatch_owner_has_no_reverse_facade_or_effect_authority() -> None:
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
    assert not {"os", "socket", "sqlite3", "subprocess"} & imports


def test_claim_owner_returns_the_winners_terminal_report_after_wait(tmp_path) -> None:
    request = tmp_path / "request-key.json"
    inbox = tmp_path / "inbox"
    report = inbox / "request-key.report.json"
    lock_path = tmp_path / "request-key.lock"
    claims: list[tuple[Path, str]] = []

    @contextmanager
    def lock(path: Path, label: str):
        claims.append((path, label))
        yield

    result = dispatch.claim_and_dispatch_request(
        request,
        None,
        inbox=inbox,
        key_for=lambda path: path.stem,
        lock_path_for=lambda key: lock_path,
        lock=lock,
        completed_report=lambda path: {"bridge_status": "done"},
        process_claimed=lambda *args, **kwargs: pytest.fail(
            "a missing loser request must not dispatch again"
        ),
    )

    assert result == report
    assert claims == [(lock_path, "file-bridge request 'request-key'")]


def test_claim_owner_refuses_missing_source_without_terminal_report(tmp_path) -> None:
    request = tmp_path / "missing.json"

    @contextmanager
    def lock(path: Path, label: str):
        yield

    with pytest.raises(FileNotFoundError, match="missing.json"):
        dispatch.claim_and_dispatch_request(
            request,
            None,
            inbox=tmp_path / "inbox",
            key_for=lambda path: path.stem,
            lock_path_for=lambda key: tmp_path / f"{key}.lock",
            lock=lock,
            completed_report=lambda path: None,
            process_claimed=lambda *args, **kwargs: pytest.fail(
                "a missing request must not dispatch"
            ),
        )


def test_structure_packet_does_not_change_effect_registry() -> None:
    assert registry_sha256() == (
        "ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec"
    )
