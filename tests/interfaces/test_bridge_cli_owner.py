"""Contracts for the File Bridge CLI owner behind the registered facade."""

from __future__ import annotations

import ast
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from daedalus import file_bridge
from daedalus.interfaces.bridge import cli
from daedalus.spine import effect_boundary
from daedalus.spine.effect_boundary import GuardDecision, registry_sha256


ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "daedalus/file_bridge.py"
OWNER = ROOT / "daedalus/interfaces/bridge/cli.py"


class _Busy(RuntimeError):
    pass


class _WatcherMissing(RuntimeError):
    pass


class _Pending(RuntimeError):
    pass


def _ports(tmp_path: Path, **overrides):
    values = {
        "outbox": tmp_path / "outbox",
        "resolve_repo_root": lambda repo_root, project: repo_root or project or "",
        "watch": lambda *args, **kwargs: None,
        "enqueue": lambda *args, **kwargs: tmp_path / "request.json",
        "process_request": lambda *args, **kwargs: tmp_path / "report.json",
        "handle_poison_request": lambda path, exc: None,
        "bridge_status": lambda project: {"project": project},
        "print_status": lambda status: None,
        "mark_read": lambda names, all_reports=False: [],
        "watcher_ownership_busy": _Busy,
        "watcher_not_running": _WatcherMissing,
        "pending_exceptions": ((_Pending, "PENDING"),),
    }
    values.update(overrides)
    return cli.BridgeCliPorts(**values)


def _function(path: Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    assert len(matches) == 1
    return matches[0]


def test_parser_preserves_public_subcommands_defaults_and_choices() -> None:
    parser = cli.build_parser()
    enqueue = parser.parse_args(
        [
            "enqueue",
            "review",
            "--repo-root",
            "C:/repo",
            "--paths",
            "a.py",
            "b.py",
            "--lane",
            "local_only",
            "--source",
            "ikarus",
            "--strategy",
            "spawn",
            "--force",
        ]
    )
    assert vars(enqueue) == {
        "command": "enqueue",
        "objective": "review",
        "repo_root": "C:/repo",
        "project": None,
        "paths": ["a.py", "b.py"],
        "model": "sonnet",
        "lane": "local_only",
        "source": "ikarus",
        "strategy": "spawn",
        "force": True,
    }
    watch = parser.parse_args(["watch"])
    assert vars(watch) == {
        "command": "watch",
        "repo_root": None,
        "project": None,
        "interval_s": 2.0,
    }


def test_status_dispatch_is_read_only_and_uses_injected_projection(
    tmp_path: Path,
) -> None:
    observed: list[object] = []
    ports = _ports(
        tmp_path,
        bridge_status=lambda project: {"project": project, "ok": True},
        print_status=lambda status: observed.append(status),
    )
    args = cli.build_parser().parse_args(["status", "--project", "demo"])
    cli.dispatch(args, parser=cli.build_parser(), ports=ports)
    assert observed == [{"project": "demo", "ok": True}]
    assert not ports.outbox.exists()


def test_once_keeps_pending_classification_and_continues(tmp_path: Path) -> None:
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    request = outbox / "task.json"
    request.write_text("{}", encoding="utf-8")
    poisoned: list[tuple[Path, BaseException]] = []

    def pending(path: Path, repo_root: str | None) -> Path:
        del path, repo_root
        raise _Pending("retry later")

    ports = _ports(
        tmp_path,
        outbox=outbox,
        process_request=pending,
        handle_poison_request=lambda path, exc: poisoned.append((path, exc)),
    )
    args = cli.build_parser().parse_args(["once"])
    error = io.StringIO()
    with redirect_stderr(error):
        cli.dispatch(args, parser=cli.build_parser(), ports=ports)
    assert "PENDING task.json: retry later" in error.getvalue()
    assert poisoned == []


def test_facade_resolves_current_ports_per_main_call(monkeypatch) -> None:
    captured: dict[str, object] = {}
    status = lambda project: {"project": project}
    monkeypatch.setattr(file_bridge, "bridge_status", status)
    monkeypatch.setattr(sys, "argv", ["file_bridge", "status", "--json"])

    def capture(args, *, parser, ports):
        captured.update(args=args, parser=parser, ports=ports)

    monkeypatch.setattr(cli, "dispatch", capture)
    file_bridge.main()
    ports = captured["ports"]
    assert isinstance(ports, cli.BridgeCliPorts)
    assert ports.bridge_status is status
    assert ports.outbox is file_bridge.OUTBOX


def test_facade_guard_precedes_mutating_dispatch(monkeypatch) -> None:
    order: list[str] = []
    monkeypatch.setattr(sys, "argv", ["file_bridge", "mark-read"])
    monkeypatch.setattr(
        "daedalus.budget.process_guard_boundary_decision",
        lambda: GuardDecision("budget.process_guard", True, "test"),
    )
    monkeypatch.setattr(
        effect_boundary,
        "begin_effect",
        lambda *args, **kwargs: order.append("begin"),
    )
    monkeypatch.setattr(
        cli,
        "dispatch",
        lambda *args, **kwargs: order.append("dispatch"),
    )
    file_bridge.main()
    assert order == ["begin", "dispatch"]


def test_print_status_facade_injects_current_stale_threshold(monkeypatch) -> None:
    observed: dict[str, object] = {}
    monkeypatch.setattr(file_bridge, "STALE_AFTER_S", 17.0)
    monkeypatch.setattr(
        cli,
        "print_status",
        lambda status, *, stale_after_s: observed.update(
            status=status, stale_after_s=stale_after_s
        ),
    )
    payload = {"watcher": {"state": "none"}}
    file_bridge._print_status(payload)
    assert observed == {"status": payload, "stale_after_s": 17.0}


def test_owner_imports_no_product_or_effect_layer() -> None:
    tree = ast.parse(OWNER.read_text(encoding="utf-8"), filename=str(OWNER))
    imports = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not any(module.startswith("daedalus") for module in imports)
    assert "begin_effect" not in OWNER.read_text(encoding="utf-8")


def test_registered_facade_keeps_guard_anchor_and_delegates_once() -> None:
    main = _function(FACADE, "main")
    calls = [
        node.func.attr
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    names = [
        node.func.id
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    assert calls.count("build_parser") == 1
    assert calls.count("dispatch") == 1
    assert names.count("begin_effect") == 1


def test_structure_packet_keeps_effect_registry_exact() -> None:
    assert registry_sha256() == (
        "44222aa9f9269eb1c9d9f5cf118786cbb1a1d602f6f3ca77aeb00d4f599214c9"
    )
