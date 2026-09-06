from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

import daedalus.claude_bridge as bridge


def _payload(worktree: Path, command_path: str) -> dict[str, object]:
    return {
        "objective": 'review " & echo injected',
        "worktree": str(worktree),
        "paths": ["daedalus/orchestration/runtime_registry.py"],
        "agent": {"call_name": "Ikarus", "name": "Ikarus", "must_read": []},
        "model": 'sonnet" & echo injected',
        "timeout_s": 30,
        "command_path": command_path,
    }


@pytest.mark.parametrize(
    "resolved",
    [r"C:\tools\claude.cmd", r"C:\tools\CLAUDE.BAT"],
)
def test_authenticated_payload_never_reaches_windows_batch_shim(
    tmp_path: Path,
    resolved: str,
) -> None:
    with mock.patch.object(
        bridge.subprocess,
        "run",
        side_effect=AssertionError("provider payload reached subprocess"),
    ) as run:
        with pytest.raises(RuntimeError, match=r"\.cmd/\.bat launchers reparse argv"):
            bridge._invoke_claude_payload(_payload(tmp_path, resolved))

    run.assert_not_called()


def test_authenticated_payload_spawns_exact_native_executable(tmp_path: Path) -> None:
    native = r"C:\tools\claude.exe"
    completed = mock.Mock(returncode=0, stdout="", stderr="")
    completed.stdout = '{"status":"done","summary":"ok","files_changed":[],"tests_run":[],"risks":[],"todos":[],"handoff":{}}'
    with mock.patch.object(bridge.subprocess, "run", return_value=completed) as run:
        result = bridge._invoke_claude_payload(_payload(tmp_path, native))

    assert result["report"]["status"] == "done"
    assert run.call_args.args[0][0] == native
