from __future__ import annotations

import ast
from pathlib import Path

from daedalus import file_bridge
from daedalus.interfaces.bridge import journal
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "file_bridge.py"
IMPLEMENTATION = ROOT / "daedalus" / "interfaces" / "bridge" / "journal.py"


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


def test_legacy_journal_names_each_delegate_to_one_hierarchy_owner() -> None:
    owners = {
        "_request_key": "request_key",
        "_request_sha256": "request_sha256",
        "_raw_request_sha256": "raw_request_sha256",
        "_report_request_binding": "report_request_binding",
        "_effect_identity_for": "effect_identity_for",
        "_journal_dir": "journal_dir",
        "_mission_projection_dir": "mission_projection_dir",
        "_read_journal": "read_journal",
        "_write_json_atomic": "write_json_atomic",
        "_completed_report": "completed_report",
        "_journal_path": "journal_path",
        "_request_lock_path": "request_lock_path",
        "_crash_journal_decision": "crash_journal_state",
        "_write_journal": "write_journal",
    }
    for facade_name, owner_name in owners.items():
        wrapper = _function(FACADE, facade_name)
        assert len(_attribute_calls(wrapper, owner_name)) == 1


def test_journal_owner_has_no_facade_or_dispatch_authority() -> None:
    tree = _tree(IMPLEMENTATION)
    imports: set[str] = set()
    definitions: set[str] = set()
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add(node.module or "")
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            definitions.add(node.name)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            called_names.add(node.func.id)

    assert not any(name.startswith("daedalus.file_bridge") for name in imports)
    assert not {"enqueue", "process_request", "watch", "main"} & definitions
    assert not {
        "begin_effect",
        "run_mission",
        "Popen",
        "ThreadingHTTPServer",
    } & called_names
    assert not {"sqlite3", "socket", "subprocess"} & imports


def test_write_wrapper_resolves_legacy_ports_per_call(monkeypatch, tmp_path) -> None:
    writes: list[tuple[Path, dict[str, object]]] = []
    target = tmp_path / "patched.state"

    monkeypatch.setattr(file_bridge, "_journal_path", lambda key: target)
    monkeypatch.setattr(file_bridge, "_now_iso", lambda: "2026-08-31T00:00:00Z")
    monkeypatch.setattr(
        file_bridge,
        "_write_json_atomic",
        lambda path, payload: writes.append((path, dict(payload))),
    )
    entry: dict[str, object] = {"state": "started"}

    file_bridge._write_journal("request-key", entry)

    assert writes == [
        (
            target,
            {"state": "started", "updated": "2026-08-31T00:00:00Z"},
        )
    ]
    assert entry["updated"] == "2026-08-31T00:00:00Z"


def test_malformed_journal_remains_fail_safe_empty(tmp_path) -> None:
    target = tmp_path / "request.json"
    target.write_text("{not-json", encoding="utf-8")

    assert journal.read_journal("request", path_for=lambda key: target) == {}


def test_structure_packet_does_not_change_effect_registry() -> None:
    assert registry_sha256() == (
        "44222aa9f9269eb1c9d9f5cf118786cbb1a1d602f6f3ca77aeb00d4f599214c9"
    )
