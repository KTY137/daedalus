from __future__ import annotations

from unittest import mock

import pytest

import daedalus.claude_bridge as bridge
import daedalus.providers.claude_sealed_operation as sealed
from daedalus.spine.envelope import canonical_sha


def test_windows_native_claude_executable_is_admitted() -> None:
    resolved = r"C:\tools\claude.exe"
    assert bridge._command_for_spawn(resolved, platform_name="nt") == resolved


@pytest.mark.parametrize(
    "resolved",
    [r"C:\tools\claude.cmd", r"C:\tools\CLAUDE.BAT"],
)
def test_windows_shell_shim_is_refused(resolved: str) -> None:
    with pytest.raises(RuntimeError, match=r"\.cmd/\.bat launchers reparse argv"):
        bridge._command_for_spawn(resolved, platform_name="nt")


def test_windows_unresolved_claude_is_refused_before_spawn() -> None:
    with pytest.raises(RuntimeError, match="could not be resolved before spawn"):
        bridge._command_for_spawn(None, platform_name="nt")


def test_provider_prompt_never_reaches_windows_cmd_shim() -> None:
    agent = {"call_name": "Ikarus", "name": "Ikarus", "must_read": []}
    with (
        mock.patch.object(bridge.os, "name", "nt"),
        mock.patch.object(
            bridge.shutil,
            "which",
            return_value=r"C:\Users\runner\node\claude.CMD",
        ),
        mock.patch.object(bridge.subprocess, "run") as run,
    ):
        with pytest.raises(RuntimeError, match=r"\.cmd/\.bat launchers reparse argv"):
            bridge._invoke_claude_cli(
                objective='review " & echo injected',
                repo_root="C:/repo",
                paths=["daedalus/ikarus_os.py"],
                agent=agent,
                model='sonnet" & echo injected',
                timeout_s=30,
            )
    run.assert_not_called()


def _sealed_payload() -> dict[str, object]:
    return {
        "objective": "review Ikarus runtime",
        "worktree": "/tmp/ikarus-worktree",
        "paths": ["daedalus/ikarus_os.py"],
        "agent": {"call_name": "Ikarus", "name": "Ikarus", "must_read": []},
        "model": "sonnet",
        "timeout_s": 30,
        "invocation_sha256": "a" * 64,
    }


def test_sealed_claude_operation_consumes_only_authenticated_payload() -> None:
    payload = _sealed_payload()
    expected = {
        "agent": "Ikarus",
        "prompt_sha256": "b" * 64,
        "report_sha256": "c" * 64,
        "report": {"status": "done"},
    }
    with mock.patch.object(sealed, "_invoke_claude_cli", return_value=expected) as invoke:
        assert sealed.invoke(payload) == expected
    invoke.assert_called_once_with(
        objective="review Ikarus runtime",
        repo_root="/tmp/ikarus-worktree",
        paths=["daedalus/ikarus_os.py"],
        agent={"call_name": "Ikarus", "name": "Ikarus", "must_read": []},
        model="sonnet",
        timeout_s=30,
    )


def test_sealed_claude_operation_refuses_payload_shape_before_subprocess() -> None:
    payload = _sealed_payload()
    payload["unexpected_callback"] = "ambient"
    with mock.patch.object(sealed, "_invoke_claude_cli") as invoke:
        with pytest.raises(ValueError, match="payload fields are not exact"):
            sealed.invoke(payload)
    invoke.assert_not_called()


def test_sealed_claude_output_evidence_binds_invocation_identity() -> None:
    payload = _sealed_payload()
    report = {"status": "done", "summary": "sealed"}
    value = {
        "agent": "Ikarus",
        "prompt_sha256": "b" * 64,
        "report_sha256": canonical_sha(report),
        "report": report,
    }
    expected = canonical_sha(
        {
            "provider": "claude_cli",
            "agent": "Ikarus",
            "invocation_sha256": "a" * 64,
            "prompt_sha256": "b" * 64,
            "report_sha256": canonical_sha(report),
            "report": report,
        }
    )
    assert sealed.output_digests(value, payload) == (expected,)
