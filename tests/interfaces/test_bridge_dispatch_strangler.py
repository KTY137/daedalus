from __future__ import annotations

import ast
from contextlib import contextmanager
from pathlib import Path

import pytest

from daedalus import file_bridge
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


def test_claimed_facade_delegates_the_state_machine_once(monkeypatch, tmp_path) -> None:
    request = tmp_path / "request.json"
    observed: dict[str, object] = {}

    def process_claimed(path, default_repo_root, *, key, ports):
        observed.update(
            path=path,
            default_repo_root=default_repo_root,
            key=key,
            ports=ports,
        )
        return tmp_path / "request.report.json"

    monkeypatch.setattr(dispatch, "process_claimed_request", process_claimed)

    result = file_bridge._process_request_claimed(
        request,
        "C:/registered/project",
        key="request",
    )

    assert result == tmp_path / "request.report.json"
    assert observed["path"] == request
    assert observed["default_repo_root"] == "C:/registered/project"
    assert observed["key"] == "request"
    assert isinstance(observed["ports"], dispatch.ClaimedDispatchPorts)


def test_claimed_facade_contains_no_state_machine_calls() -> None:
    wrapper = _function(FACADE, "_process_request_claimed")
    owner_calls = _attribute_calls(wrapper, "process_claimed_request")
    direct_calls = {
        child.func.id
        for child in ast.walk(wrapper)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
    }

    assert len(owner_calls) == 1
    assert not {
        "_read_journal",
        "_write_journal",
        "_read_request",
        "_completed_report",
        "_quarantine_move",
        "_finish_terminal_report",
        "_project_report_to_conversation",
        "_write_json_atomic",
        "quarantine_request",
    } & direct_calls


def test_legacy_quarantine_exceptions_are_dispatch_owner_objects() -> None:
    assert file_bridge.RequestIdentityConflict is dispatch.RequestIdentityConflict
    assert file_bridge.TerminalReportPreserved is dispatch.TerminalReportPreserved
    assert file_bridge.QuarantineMovePending is dispatch.QuarantineMovePending


def test_quarantine_facades_each_delegate_to_one_dispatch_owner() -> None:
    owners = {
        "_quarantine_request_identity_conflict": (
            "quarantine_request_identity_conflict"
        ),
        "quarantine_request": "quarantine_request",
        "_quarantine_move": "move_quarantined_request",
    }
    for facade_name, owner_name in owners.items():
        wrapper = _function(FACADE, facade_name)
        assert len(_attribute_calls(wrapper, owner_name)) == 1


def test_quarantine_facade_contains_no_persistence_state_machine_calls() -> None:
    wrappers = [
        _function(FACADE, "_quarantine_request_identity_conflict"),
        _function(FACADE, "quarantine_request"),
        _function(FACADE, "_quarantine_move"),
    ]
    direct_calls = {
        child.func.id
        for wrapper in wrappers
        for child in ast.walk(wrapper)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
    }

    assert not {
        "_read_journal",
        "_write_journal",
        "_completed_report",
        "_write_json_atomic",
        "_project_report_to_conversation",
        "_note_report_arrival",
    } & direct_calls


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
