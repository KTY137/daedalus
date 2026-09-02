from __future__ import annotations

import ast
import json
from pathlib import Path

from daedalus import file_bridge
from daedalus.interfaces.bridge import watcher
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "file_bridge.py"
IMPLEMENTATION = ROOT / "daedalus" / "interfaces" / "bridge" / "watcher.py"


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


def test_legacy_watcher_types_are_exact_owner_aliases() -> None:
    assert file_bridge.WatcherOwnershipBusy is watcher.WatcherOwnershipBusy
    assert file_bridge._BridgeWatcherLock is watcher._BridgeWatcherLock


def test_legacy_watcher_functions_delegate_to_the_hierarchy_owner() -> None:
    owners = {
        "current_process_identity": "current_process_identity",
        "_watcher_lock_path": "watcher_lock_path",
        "write_heartbeat": "write_heartbeat",
        "restart_hint": "restart_hint",
        "heartbeat_status": "heartbeat_status",
        "_looks_unfinished": "looks_unfinished",
        "handle_poison_request": "handle_poison_request",
        "watch": "watch_loop",
    }
    for facade_name, owner_name in owners.items():
        wrapper = _function(FACADE, facade_name)
        assert len(_attribute_calls(wrapper, owner_name)) == 1


def test_registered_watch_effect_precedes_the_owner_loop() -> None:
    wrapper = _function(FACADE, "watch")
    calls = [node for node in ast.walk(wrapper) if isinstance(node, ast.Call)]
    begin = [
        node
        for node in calls
        if isinstance(node.func, ast.Name) and node.func.id == "begin_effect"
    ]
    loops = _attribute_calls(wrapper, "watch_loop")
    assert len(begin) == 1
    assert len(loops) == 1
    assert begin[0].lineno < loops[0].lineno


def test_watcher_owner_has_no_reverse_facade_or_effect_import() -> None:
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


def test_process_identity_refreshes_only_when_pid_changes() -> None:
    identity, pid, nonce = watcher.current_process_identity(
        pid=41,
        recorded_pid=41,
        nonce="same-process",
        new_nonce=lambda: "must-not-be-used",
    )
    assert (identity, pid, nonce) == ("41:same-process", 41, "same-process")

    identity, pid, nonce = watcher.current_process_identity(
        pid=42,
        recorded_pid=41,
        nonce="inherited",
        new_nonce=lambda: "child-process",
    )
    assert (identity, pid, nonce) == ("42:child-process", 42, "child-process")


def test_settling_classification_uses_the_injected_clock(tmp_path) -> None:
    request = tmp_path / "partial.json"
    request.write_text("{", encoding="utf-8")
    modified = request.stat().st_mtime
    failure = json.JSONDecodeError("partial", "{", 1)

    assert watcher.looks_unfinished(
        request,
        failure,
        settle_grace_s=5.0,
        now_epoch=lambda: modified + 4.9,
    ) is True
    assert watcher.looks_unfinished(
        request,
        failure,
        settle_grace_s=5.0,
        now_epoch=lambda: modified + 5.0,
    ) is False


def test_poison_facade_contains_no_recovery_state_machine_calls() -> None:
    wrapper = _function(FACADE, "handle_poison_request")
    direct_calls = {
        child.func.id
        for child in ast.walk(wrapper)
        if isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
    }

    assert not {
        "_looks_unfinished",
        "quarantine_request",
        "_quarantine_dir",
        "_request_key",
        "print",
    } & direct_calls


def test_structure_packet_does_not_change_effect_registry() -> None:
    assert registry_sha256() == (
        "1afe32ac18cb6cb755a1bf9a3f5aa47834c3716298e8914c0cc6c983633aef3d"
    )
