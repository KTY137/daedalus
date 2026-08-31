from __future__ import annotations

import ast
from pathlib import Path

from daedalus import file_bridge
from daedalus.interfaces.bridge import projection
from daedalus.spine.effect_boundary import registry_sha256


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "file_bridge.py"
IMPLEMENTATION = ROOT / "daedalus" / "interfaces" / "bridge" / "projection.py"


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


def test_legacy_projection_names_each_delegate_to_one_hierarchy_owner() -> None:
    owners = {
        "_seen_dir": "seen_dir",
        "_latest_log": "latest_log",
        "_note_report_arrival": "note_report_arrival",
        "_reported_result": "reported_result",
        "report_application_truth": "report_application_truth",
        "_conversation_report_fields": "conversation_report_fields",
        "unread_reports": "unread_reports",
        "mark_read": "mark_read",
        "quarantined_requests": "quarantined_requests",
        "_report_brief": "report_brief",
        "_project_report_briefs": "project_report_briefs",
        "bridge_status": "bridge_status",
        "stream_state": "stream_state",
    }
    for facade_name, owner_name in owners.items():
        wrapper = _function(FACADE, facade_name)
        assert len(_attribute_calls(wrapper, owner_name)) == 1


def test_projection_owner_has_no_effect_or_process_authority() -> None:
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
        "ThreadingHTTPServer",
        "Popen",
        "run_mission",
    } & called_names
    assert not {"os", "sqlite3", "subprocess", "socket"} & imports


def test_stream_wrapper_resolves_legacy_monkeypatch_seams_per_call(monkeypatch) -> None:
    status = {
        "queue_depth": 4,
        "in_flight": {"file": "probe"},
        "unread_count": 2,
        "quarantined_count": 1,
        "watcher": {"state": "busy"},
    }
    reports = [{"name": "probe.report.json", "project": "p"}]
    monkeypatch.setattr(file_bridge, "bridge_status", lambda project=None: status)
    monkeypatch.setattr(
        file_bridge,
        "_project_report_briefs",
        lambda project=None: reports,
    )

    assert file_bridge.stream_state("p") == {
        "queue_depth": 4,
        "in_flight": 1,
        "unread_count": 2,
        "quarantined_count": 1,
        "watcher_state": "busy",
        "reports_total": 1,
        "latest_report": reports[0],
    }


def test_projection_module_is_hierarchically_importable() -> None:
    assert callable(projection.reported_result)
    assert callable(projection.report_application_truth)
    assert callable(projection.conversation_report_fields)
    assert callable(projection.bridge_status)
    assert callable(projection.stream_state)


def test_report_projection_owner_keeps_conservative_application_truth() -> None:
    report = {
        "bridge_status": "done",
        "result": {
            "assignments": [
                {
                    "owner": "builder",
                    "status": "offloaded",
                    "result": {
                        "mode": "write",
                        "wrote": ["src/app.py"],
                        "verify": {"ok": True},
                    },
                }
            ]
        },
    }

    applied, reason = projection.report_application_truth(report)

    assert applied is True
    assert "1 changed path(s)" in reason


def test_structure_packet_does_not_change_effect_registry() -> None:
    assert registry_sha256() == (
        "ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec"
    )
