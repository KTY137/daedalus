from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

import daedalus.claude_bridge as bridge
import daedalus.providers.claude_sealed_operation as sealed
from daedalus.providers.claude_cli import claude_invocation_sha256
from daedalus.spine.envelope import canonical_sha


def test_bridge_command_admission_delegates_to_runtime_policy() -> None:
    with mock.patch.object(
        bridge,
        "claude_command_for_spawn",
        return_value=r"C:\tools\claude.exe",
    ) as admission:
        assert bridge._command_for_spawn(
            r"C:\candidate\claude.exe", platform_name="nt"
        ) == r"C:\tools\claude.exe"

    admission.assert_called_once_with(
        r"C:\candidate\claude.exe", platform_name="nt"
    )


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


def _sealed_payload(worktree: Path) -> dict[str, object]:
    payload: dict[str, object] = {
        "objective": "review Ikarus runtime",
        "worktree": str(worktree),
        "paths": ["daedalus/ikarus_os.py"],
        "agent": {"call_name": "Ikarus", "name": "Ikarus", "must_read": []},
        "model": "sonnet",
        "timeout_s": 30,
        "attempt_id": "attempt-ikarus-1",
        "source_revision": "f" * 40,
        "request_sha256": "d" * 64,
    }
    payload["invocation_sha256"] = claude_invocation_sha256(
        objective=payload["objective"],  # type: ignore[arg-type]
        worktree=payload["worktree"],  # type: ignore[arg-type]
        paths=payload["paths"],  # type: ignore[arg-type]
        agent=payload["agent"],  # type: ignore[arg-type]
        model=payload["model"],  # type: ignore[arg-type]
        timeout_s=payload["timeout_s"],  # type: ignore[arg-type]
        attempt_id=payload["attempt_id"],  # type: ignore[arg-type]
        source_revision=payload["source_revision"],  # type: ignore[arg-type]
        request_sha256=payload["request_sha256"],  # type: ignore[arg-type]
    )
    return payload


def test_sealed_claude_operation_consumes_only_authenticated_payload(tmp_path: Path) -> None:
    payload = _sealed_payload(tmp_path)
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
        repo_root=str(tmp_path.resolve()),
        paths=["daedalus/ikarus_os.py"],
        agent={"call_name": "Ikarus", "name": "Ikarus", "must_read": []},
        model="sonnet",
        timeout_s=30,
    )


def test_sealed_claude_operation_refuses_payload_shape_before_subprocess(tmp_path: Path) -> None:
    payload = _sealed_payload(tmp_path)
    payload["unexpected_callback"] = "ambient"
    with mock.patch.object(sealed, "_invoke_claude_cli") as invoke:
        with pytest.raises(ValueError, match="payload fields are not exact"):
            sealed.invoke(payload)
    invoke.assert_not_called()


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("objective", "ship altered runtime"),
        ("paths", ["README.md"]),
        ("agent", {"call_name": "Other", "name": "Other", "must_read": []}),
        ("model", "opus"),
        ("timeout_s", 31),
        ("attempt_id", "attempt-ikarus-2"),
        ("source_revision", "e" * 40),
        ("request_sha256", "e" * 64),
    ],
)
def test_sealed_claude_operation_refuses_semantic_substitution_before_subprocess(
    tmp_path: Path,
    field: str,
    replacement: object,
) -> None:
    payload = _sealed_payload(tmp_path)
    payload[field] = replacement
    with mock.patch.object(sealed, "_invoke_claude_cli") as invoke:
        with pytest.raises(ValueError, match="invocation_sha256 does not match payload"):
            sealed.invoke(payload)
    invoke.assert_not_called()


def test_sealed_claude_operation_refuses_worktree_substitution_before_subprocess(
    tmp_path: Path,
) -> None:
    payload = _sealed_payload(tmp_path)
    alternate = tmp_path / "alternate"
    alternate.mkdir()
    payload["worktree"] = str(alternate)
    with mock.patch.object(sealed, "_invoke_claude_cli") as invoke:
        with pytest.raises(ValueError, match="invocation_sha256 does not match payload"):
            sealed.invoke(payload)
    invoke.assert_not_called()


def test_sealed_claude_operation_executes_canonical_path_identity(tmp_path: Path) -> None:
    payload = _sealed_payload(tmp_path)
    payload["paths"] = ["daedalus\\ikarus_os.py", "daedalus/ikarus_os.py"]
    payload["invocation_sha256"] = claude_invocation_sha256(
        objective=payload["objective"],  # type: ignore[arg-type]
        worktree=payload["worktree"],  # type: ignore[arg-type]
        paths=payload["paths"],  # type: ignore[arg-type]
        agent=payload["agent"],  # type: ignore[arg-type]
        model=payload["model"],  # type: ignore[arg-type]
        timeout_s=payload["timeout_s"],  # type: ignore[arg-type]
        attempt_id=payload["attempt_id"],  # type: ignore[arg-type]
        source_revision=payload["source_revision"],  # type: ignore[arg-type]
        request_sha256=payload["request_sha256"],  # type: ignore[arg-type]
    )
    with mock.patch.object(sealed, "_invoke_claude_cli", return_value={}) as invoke:
        sealed.invoke(payload)
    assert invoke.call_args.kwargs["paths"] == ["daedalus/ikarus_os.py"]


def test_sealed_claude_output_evidence_binds_invocation_identity(tmp_path: Path) -> None:
    payload = _sealed_payload(tmp_path)
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
            "invocation_sha256": payload["invocation_sha256"],
            "prompt_sha256": "b" * 64,
            "report_sha256": canonical_sha(report),
            "report": report,
        }
    )
    assert sealed.output_digests(value, payload) == (expected,)
