from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

import daedalus.orchestration.runtime_registry as registry
import daedalus.providers as providers
import daedalus.providers.claude_cli as claude_provider


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


def test_claude_provider_probe_requires_runtime_AND_dispatch_readiness() -> None:
    """A resolved executable is necessary but NOT sufficient.

    Ported from `g1/ikarus-runtime-invocation-binding-07d3`. Before this, a
    discovered `claude` binary was reported available, so routing and the chat
    UI advertised a provider the canonical effect boundary must refuse:
    `provider.claude` is INVENTORY_ONLY and `probe_provider` never consulted
    the registry.

    The probe now projects that boundary. It does NOT activate dispatch --
    flipping `provider.claude` to CENTRAL is a separate owner-signed decision
    under plan §4.1/§10 -- so with the registry as it stands the honest answer
    is "installed, not activated".

    This assertion is INVERTED from the one it replaces, not deleted: the
    executable admission is still required to run first and is still asserted.
    """
    with mock.patch.object(
        claude_provider,
        "claude_command_for_spawn",
        return_value=r"C:\tools\claude.exe",
    ) as admission:
        available, error = providers._availability_probe("claude_cli")

    assert available is False
    assert "canonical dispatch is not activated" in error
    assert "inventory_only" in error
    admission.assert_called_once_with()


def test_claude_dispatch_readiness_tracks_the_registry_and_is_not_a_hard_no() -> None:
    """The refusal belongs to the registry, not to a constant.

    Without this, the test above would still pass if the projection were
    replaced by `return False, "..."`, and the probe would have quietly
    stopped tracking the boundary it claims to project.
    """
    from daedalus.runtimes.providers import catalogue
    from daedalus.spine import effect_boundary

    # REGISTRY_BY_ID is a read-only mappingproxy on purpose, so the whole
    # binding is replaced rather than an entry assigned into it.
    row = SimpleNamespace(wiring=effect_boundary.Wiring.CENTRAL)
    with mock.patch.object(
        effect_boundary, "REGISTRY_BY_ID", {"provider.claude": row}
    ):
        available, error = catalogue.claude_dispatch_readiness()

    assert available is True
    assert error == ""


def test_claude_provider_probe_preserves_runtime_admission_refusal() -> None:
    refusal = "Claude execution refused: Windows .cmd/.bat launchers reparse argv"
    with mock.patch.object(
        claude_provider,
        "claude_command_for_spawn",
        side_effect=RuntimeError(refusal),
    ) as admission:
        available, error = providers._availability_probe("claude_cli")

    assert available is False
    assert error == refusal
    admission.assert_called_once_with()
