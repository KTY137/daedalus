from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import daedalus.core as core
import daedalus.kernel.runtime_authorization_issuer as legacy_runtime_admission
import daedalus.providers as providers
import daedalus.runtime_registry as registry
import daedalus.runtimes.admission as runtime_admission
import daedalus.runtimes.admission.authorization as runtime_authorization


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


def test_claude_provider_probe_requires_runtime_and_canonical_dispatch_readiness() -> None:
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

    assert available is False
    assert "canonical dispatch is not activated" in error
    assert "provider.claude wiring=inventory_only" in error
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


def test_core_provider_health_surfaces_canonical_claude_dispatch_refusal(monkeypatch) -> None:
    refusal = (
        "Claude CLI is installed, but canonical dispatch is not activated "
        "(provider.claude wiring=inventory_only)"
    )
    rows = [
        {"name": "ollama", "available": True, "last_error": ""},
        {"name": "claude_cli", "available": False, "last_error": refusal},
    ]
    monkeypatch.setattr(core, "_provider_health", lambda: rows)

    payload = core.provider_health("daedalus")

    assert payload["providers"] == rows
    assert payload["warnings"] == [f"Claude lane unavailable: {refusal}"]
    assert all("not on PATH" not in warning for warning in payload["warnings"])


_RUNTIME_ADMISSION_API = (
    "RUNTIME_AUTHORITY_KEY_ID",
    "RUNTIME_LEASE_KEY_ID",
    "acquire_runtime_bound_authorization",
    "runtime_trust_ledger",
    "runtime_trust_ledger_path",
)


@pytest.mark.parametrize("name", _RUNTIME_ADMISSION_API)
def test_runtime_admission_has_one_canonical_owner(name: str) -> None:
    assert getattr(legacy_runtime_admission, name) is getattr(runtime_admission, name)


def test_kernel_runtime_admission_path_is_compatibility_only() -> None:
    legacy_source = Path(legacy_runtime_admission.__file__).read_text(encoding="utf-8")
    owner_source = Path(runtime_authorization.__file__).read_text(encoding="utf-8")

    assert "def acquire_runtime_bound_authorization(" not in legacy_source
    assert "RuntimeBoundEffectAuthorization(" not in legacy_source
    assert owner_source.count("def acquire_runtime_bound_authorization(") == 1
    assert owner_source.count("RuntimeBoundEffectAuthorization(") == 1


def test_ikarus_scheduler_claude_availability_requires_canonical_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(
        "daedalus.doctor.check",
        lambda: {
            "claude_cli": True,
            "can_offload_local": True,
            "deepseek_key": False,
            "codex_cli": False,
        },
    )
    with mock.patch(
        "daedalus.providers._availability_probe",
        return_value=(False, "inventory_only"),
    ) as probe:
        availability = core._availability_from_doctor()

    assert availability["claude_cli"] is False
    assert availability["ollama"] is True
    probe.assert_called_once_with("claude_cli")


def test_ikarus_scheduler_binary_presence_cannot_override_dispatch_refusal(monkeypatch) -> None:
    monkeypatch.setattr(
        "daedalus.doctor.check",
        lambda: {
            "claude_cli": True,
            "can_offload_local": False,
            "deepseek_key": False,
            "codex_cli": False,
        },
    )
    with mock.patch(
        "daedalus.providers._availability_probe",
        return_value=(False, "provider.claude wiring=inventory_only"),
    ):
        availability = core._availability_from_doctor()

    assert availability == {
        "claude_cli": False,
        "ollama": False,
        "deepseek": False,
        "codex_cli": False,
    }


def test_core_claude_fallback_never_invokes_unsealed_public_bridge(monkeypatch) -> None:
    monkeypatch.setattr(
        core,
        "ask_claude",
        mock.Mock(side_effect=AssertionError("ambient Claude invocation is forbidden")),
    )
    payload = {
        "objective": "inspect runtime seam",
        "repo_root": "/repo",
        "paths": [],
        "model": "sonnet",
        "lane": "claude",
    }

    report = core._ask_claude_report(payload)

    core.ask_claude.assert_not_called()
    assert report["bridge_status"] == "failed"
    assert report["lane"] == "claude"
    assert "ClaudeSealedInvocationBundle" in report["error"]
    assert "blocked before provider invocation" in report["error"]
