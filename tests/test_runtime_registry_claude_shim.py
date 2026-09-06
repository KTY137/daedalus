from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

import daedalus.orchestration.runtime_registry as registry
import daedalus.providers as providers


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(registry, "resolve_runtime_command", lambda runtime_id: None)
    with pytest.raises(RuntimeError, match="could not be resolved before spawn"):
        registry.claude_command_for_spawn(None, platform_name="posix")


def test_claude_windows_batch_shim_is_not_reported_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = r"C:\Users\runner\node\claude.CMD"
    monkeypatch.setattr(registry, "_runtime_platform", lambda: "nt")
    monkeypatch.setattr(
        registry,
        "resolve_runtime_command",
        lambda runtime_id: resolved if runtime_id == "claude_code_cli" else None,
    )
    with mock.patch.object(registry.subprocess, "run") as run:
        row = registry.runtime_status("claude_code_cli")

    assert row["available"] is False
    assert row["auth_status"] == "unavailable"
    assert row["command_path"] == resolved
    assert ".cmd/.bat launchers reparse argv" in row["last_error"]
    run.assert_not_called()


def test_claude_windows_native_executable_is_probed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = r"C:\tools\claude.exe"
    monkeypatch.setattr(registry, "_runtime_platform", lambda: "nt")
    monkeypatch.setattr(registry, "resolve_runtime_command", lambda runtime_id: resolved)
    completed = SimpleNamespace(returncode=0, stdout="2.1.0\n", stderr="")
    with mock.patch.object(registry.subprocess, "run", return_value=completed) as run:
        row = registry.runtime_status("claude_code_cli")

    assert row["available"] is True
    assert row["auth_status"] == "cli_detected"
    assert row["command_path"] == resolved
    assert row["version"] == "2.1.0"
    run.assert_called_once()


def test_codex_batch_probe_policy_is_not_changed_by_claude_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = r"C:\Users\runner\node\codex.CMD"
    monkeypatch.setattr(registry, "_runtime_platform", lambda: "nt")
    monkeypatch.setattr(registry, "resolve_runtime_command", lambda runtime_id: resolved)
    completed = SimpleNamespace(returncode=0, stdout="codex 0.152.0\n", stderr="")
    with mock.patch.object(registry.subprocess, "run", return_value=completed) as run:
        row = registry.runtime_status("codex_cli")

    assert row["available"] is True
    assert row["command_path"] == resolved
    run.assert_called_once()


def test_claude_provider_probe_reuses_canonical_runtime_readiness() -> None:
    row = {
        "id": "claude_code_cli",
        "available": True,
        "last_error": "",
        "measured_at": "2026-09-06T00:00:00Z",
        "measured_age_s": 0.0,
    }
    with (
        mock.patch.object(registry, "cached_runtime_status", return_value=row) as readiness,
        mock.patch.object(providers, "get_provider") as provider_factory,
    ):
        available, error = providers._availability_probe("claude_cli")

    assert available is True
    assert error == ""
    readiness.assert_called_once_with("claude_code_cli")
    provider_factory.assert_not_called()


def test_claude_provider_probe_preserves_runtime_admission_refusal() -> None:
    refusal = "Claude execution refused: Windows .cmd/.bat launchers reparse argv"
    row = {
        "id": "claude_code_cli",
        "available": False,
        "last_error": refusal,
        "measured_at": "2026-09-06T00:00:00Z",
        "measured_age_s": 0.0,
    }
    with (
        mock.patch.object(registry, "cached_runtime_status", return_value=row) as readiness,
        mock.patch.object(providers, "get_provider") as provider_factory,
    ):
        available, error = providers._availability_probe("claude_cli")

    assert available is False
    assert error == refusal
    readiness.assert_called_once_with("claude_code_cli")
    provider_factory.assert_not_called()
