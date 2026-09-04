from __future__ import annotations

from unittest import mock

import pytest

import daedalus.claude_bridge as bridge


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
