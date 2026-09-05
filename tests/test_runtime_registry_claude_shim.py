from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

import daedalus.runtime_registry as registry


def test_shared_claude_spawn_admission_accepts_native_and_posix() -> None:
    native = r"C:\tools\claude.exe"
    posix = "/usr/local/bin/claude"

    assert registry.claude_command_for_spawn(native, platform_name="nt") == native
    assert registry.claude_command_for_spawn(posix, platform_name="posix") == posix


@pytest.mark.parametrize(
    "resolved",
    [r"C:\tools\claude.cmd", r"C:\tools\CLAUDE.BAT"],
)
def test_shared_claude_spawn_admission_refuses_windows_batch_shim(
    resolved: str,
) -> None:
    with pytest.raises(RuntimeError, match=r"\.cmd/\.bat launchers reparse argv"):
        registry.claude_command_for_spawn(resolved, platform_name="nt")


def test_shared_claude_spawn_admission_refuses_unresolved_command(
    monkeypatch,
) -> None:
    monkeypatch.setattr(registry.shutil, "which", lambda command: None)
    with pytest.raises(RuntimeError, match="could not be resolved before spawn"):
        registry.claude_command_for_spawn(None, platform_name="posix")


def test_claude_windows_batch_shim_is_not_reported_ready(monkeypatch) -> None:
    monkeypatch.setattr(registry, "_runtime_platform", lambda: "nt")
    resolved = r"C:\Users\runner\node\claude.CMD"
    monkeypatch.setattr(
        registry.shutil,
        "which",
        lambda command: resolved if command == "claude" else None,
    )
    with (
        mock.patch.object(
            registry,
            "claude_command_for_spawn",
            wraps=registry.claude_command_for_spawn,
        ) as admission,
        mock.patch.object(registry.subprocess, "run") as run,
    ):
        row = registry.runtime_status("claude_code_cli")

    assert row["available"] is False
    assert row["auth_status"] == "unavailable"
    assert row["command_path"].casefold().endswith("claude.cmd")
    assert ".cmd/.bat launchers reparse argv" in row["last_error"]
    admission.assert_called_once_with(resolved, platform_name="nt")
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
