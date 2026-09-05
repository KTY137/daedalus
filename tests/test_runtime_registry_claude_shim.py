from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import daedalus.runtime_registry as registry


def test_claude_windows_batch_shim_is_not_reported_ready(monkeypatch) -> None:
    monkeypatch.setattr(registry, "_runtime_platform", lambda: "nt")
    monkeypatch.setattr(
        registry.shutil,
        "which",
        lambda command: r"C:\Users\runner\node\claude.CMD" if command == "claude" else None,
    )
    with mock.patch.object(registry.subprocess, "run") as run:
        row = registry.runtime_status("claude_code_cli")

    assert row["available"] is False
    assert row["auth_status"] == "unavailable"
    assert row["command_path"].casefold().endswith("claude.cmd")
    assert ".cmd/.bat launcher reparses argv" in row["last_error"]
    run.assert_not_called()


def test_claude_windows_native_executable_is_probed(monkeypatch) -> None:
    monkeypatch.setattr(registry, "_runtime_platform", lambda: "nt")
    resolved = r"C:\tools\claude.exe"
    monkeypatch.setattr(registry.shutil, "which", lambda command: resolved)
    completed = SimpleNamespace(returncode=0, stdout="2.1.0\n", stderr="")
    with mock.patch.object(registry.subprocess, "run", return_value=completed) as run:
        row = registry.runtime_status("claude_code_cli")

    assert row["available"] is True
    assert row["auth_status"] == "cli_detected"
    assert row["command_path"] == resolved
    assert row["version"] == "2.1.0"
    run.assert_called_once()


def test_codex_batch_probe_policy_is_not_changed_by_claude_guard(monkeypatch) -> None:
    monkeypatch.setattr(registry, "_runtime_platform", lambda: "nt")
    resolved = r"C:\Users\runner\node\codex.CMD"
    monkeypatch.setattr(registry.shutil, "which", lambda command: resolved)
    completed = SimpleNamespace(returncode=0, stdout="codex 0.152.0\n", stderr="")
    with mock.patch.object(registry.subprocess, "run", return_value=completed) as run:
        row = registry.runtime_status("codex_cli")

    assert row["available"] is True
    assert row["command_path"] == resolved
    run.assert_called_once()
