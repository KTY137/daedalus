from __future__ import annotations

import ast
import json
from pathlib import Path

from daedalus import file_bridge
from daedalus.interfaces.bridge import queue
from daedalus.spine import effect_boundary
from daedalus.spine.effect_boundary import GuardDecision, registry_sha256


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus" / "file_bridge.py"
IMPLEMENTATION = ROOT / "daedalus" / "interfaces" / "bridge" / "queue.py"


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


def test_queue_facade_delegates_document_ownership_once() -> None:
    assert len(
        _attribute_calls(_function(FACADE, "enqueue"), "admit_enqueue")
    ) == 1
    assert len(
        _attribute_calls(_function(FACADE, "enqueue"), "publish_request")
    ) == 1
    assert len(
        _attribute_calls(
            _function(FACADE, "codex_inline_brief_warning"),
            "codex_inline_brief_warning",
        )
    ) == 1
    assert len(
        _attribute_calls(_function(FACADE, "_read_request"), "read_request")
    ) == 1


def test_legacy_watcher_refusal_is_the_queue_owner_object() -> None:
    assert file_bridge.WatcherNotRunning is queue.WatcherNotRunning


def test_enqueue_admission_precedes_effect_and_publication() -> None:
    wrapper = _function(FACADE, "enqueue")
    admission = _attribute_calls(wrapper, "admit_enqueue")
    publication = _attribute_calls(wrapper, "publish_request")
    effect = [
        node
        for node in ast.walk(wrapper)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "begin_effect"
    ]

    assert len(admission) == len(effect) == len(publication) == 1
    assert admission[0].lineno < effect[0].lineno < publication[0].lineno


def test_queue_owner_has_no_effect_dispatch_or_watcher_authority() -> None:
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

    assert not any(name.startswith("daedalus") for name in imports)
    assert not {"enqueue", "process_request", "watch", "main"} & definitions
    assert not {
        "begin_effect",
        "heartbeat_status",
        "run_mission",
        "Popen",
    } & called_names
    assert not {"os", "socket", "sqlite3", "subprocess", "uuid"} & imports


def test_publish_request_preserves_the_wire_document_and_name(tmp_path) -> None:
    writes: list[tuple[Path, str]] = []

    path = queue.publish_request(
        outbox=tmp_path,
        objective="Fix GUI panel layout",
        repo_root="C:/repo",
        paths=["apps/web/src/App.tsx"],
        model="sonnet",
        lane="auto",
        project="daedalus",
        source="user",
        strategy="single",
        category="frontend",
        trace_id="tr-fixed",
        clock=lambda: "20260831T120000Z",
        unique_hex=lambda: "0123456789abcdef",
        stamp_trace=lambda payload, *, trace_id: {
            **payload,
            "trace_id": trace_id,
        },
        write_text=lambda target, body: writes.append((target, body)),
    )

    assert path == tmp_path / (
        "20260831T120000Z-fix-gui-panel-layout-01234567.json"
    )
    assert writes[0][0] == path
    assert json.loads(writes[0][1]) == {
        "objective": "Fix GUI panel layout",
        "repo_root": "C:/repo",
        "paths": ["apps/web/src/App.tsx"],
        "model": "sonnet",
        "source": "user",
        "strategy": "single",
        "lane": "auto",
        "project": "daedalus",
        "category": "frontend",
        "trace_id": "tr-fixed",
    }


def test_enqueue_resolves_facade_ports_at_call_time(monkeypatch, tmp_path) -> None:
    captured: dict[str, object] = {}
    expected = tmp_path / "request.json"
    outbox = tmp_path / "outbox"

    monkeypatch.setattr(
        file_bridge,
        "heartbeat_status",
        lambda: {"state": "alive", "restart": "unused"},
    )
    monkeypatch.setattr(
        file_bridge,
        "_crash_journal_decision",
        lambda detail: GuardDecision("file_bridge.crash_journal", True, detail),
    )
    monkeypatch.setattr(effect_boundary, "begin_effect", lambda *args: None)
    monkeypatch.setattr(file_bridge, "OUTBOX", outbox)
    clock = lambda: "20260831T130000Z"
    monkeypatch.setattr(file_bridge, "_stamp", clock)

    def capture(**kwargs):
        captured.update(kwargs)
        return expected

    monkeypatch.setattr(queue, "publish_request", capture)

    assert file_bridge.enqueue("probe", "C:/repo", []) == expected
    assert captured["outbox"] == outbox
    assert captured["clock"] is clock
    assert captured["stamp_trace"] is file_bridge.envelope.stamp
    assert captured["write_text"] is file_bridge.write_text_atomic


def test_structure_packet_does_not_change_effect_registry() -> None:
    assert registry_sha256() == (
        "ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec"
    )
