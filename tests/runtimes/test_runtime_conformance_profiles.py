from __future__ import annotations

import ctypes
import dataclasses
import hashlib
import importlib.util
import json
import os
import platform
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kernel.runtime_conformance import (
    RecordedObservation,
    RuntimeConformanceError,
    assemble_recorded_conformance,
)
from daedalus.runtimes import (
    REQUIRED_GATE0_RUNTIME_IDS,
    RuntimeConformanceEnvelope,
    RuntimeProbeIdentity,
    bind_conformance_envelope,
    build_probe_identity,
    load_runtime_profiles,
    materialize_runtime_manifest,
    verify_runtime_envelope,
)
from daedalus.schemas import RUNTIME_CONFORMANCE_CHECKS
from daedalus.spine.cancel import CancellationUnavailable, ManagedProcess
from daedalus.spine.envelope import canonical_sha

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "configs" / "runtimes" / "gate0-runtime-profiles-v1.json"
FIXTURE = ROOT / "tests" / "fixtures" / "runtime_probe_fixture.py"
REVISION = "7" * 40
NOW = datetime(2026, 8, 3, 0, 0, tzinfo=timezone.utc)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _interpreter_image() -> Path:
    """The interpreter image that can actually be read off disk.

    ``sys.executable`` is not always a readable file. On a Microsoft-Store
    Python it is an App Execution Alias: a zero-length reparse point that
    ``open()`` refuses with ``OSError: [Errno 22] Invalid argument``. The real
    image lives under ``sys.base_prefix``. Spawning the alias works, so only
    the *hashing* path needs this; the digest still identifies the exact
    interpreter binary in use, which is what the manifest binds.
    """
    candidates = [Path(sys.executable)]
    base_executable = getattr(sys, "_base_executable", None)
    if base_executable:
        candidates.append(Path(base_executable))
    name = Path(sys.executable).name
    candidates.append(Path(sys.base_prefix) / name)
    candidates.append(Path(sys.base_prefix) / "bin" / name)
    for candidate in candidates:
        try:
            with candidate.open("rb"):
                return candidate
        except OSError:
            continue
    raise RuntimeError(f"no readable interpreter image for {sys.executable!r}")


def _adapter_sha256(module_name: str) -> str:
    spec = importlib.util.find_spec(module_name)
    assert spec is not None and spec.origin is not None
    return _file_sha256(Path(spec.origin))


def _environment_sha256() -> str:
    return canonical_sha(
        {
            "schema": "daedalus-offline-runtime-environment/1",
            "os_name": os.name,
            "platform": sys.platform,
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
        }
    )


def _parse_json_lines(raw: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in raw.splitlines() if line.strip()]


def _terminate_group(process: subprocess.Popen[str]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()


def _pid_alive(pid: int) -> bool:
    if os.name == "posix":
        stat_path = Path(f"/proc/{pid}/stat")
        if stat_path.exists():
            try:
                fields = stat_path.read_text(encoding="utf-8").split()
            except OSError:
                return False
            if len(fields) > 2 and fields[2] == "Z":
                return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    # A bare `return False` here would make every win32 liveness question
    # answer "already dead", which turns the cancellation check into a rubber
    # stamp. Ask the kernel instead.
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    ]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return False
        return code.value == 259  # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _protocol_observations(
    tmp_path: Path, *, probe_identity_sha256: str
) -> dict[str, RecordedObservation]:
    completed = subprocess.run(
        [sys.executable, str(FIXTURE), "emit"],
        check=False,
        text=True,
        capture_output=True,
        encoding="utf-8",
        timeout=10,
    )
    events = _parse_json_lines(completed.stdout)
    deltas = [event["text"] for event in events if event.get("event") == "delta"]
    tools = [event for event in events if event.get("event") == "tool"]
    finals = [event for event in events if event.get("event") == "final"]
    usages = [event for event in events if event.get("event") == "usage"]

    timeout_process = subprocess.Popen(
        [sys.executable, str(FIXTURE), "sleep", "--seconds", "60"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        start_new_session=(os.name == "posix"),
    )
    timed_out = False
    try:
        timeout_process.communicate(timeout=0.1)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_group(timeout_process)
        timeout_process.wait(timeout=5)

    # The canonical container primitive rather than a hand-rolled POSIX
    # process group: `daedalus.spine.cancel` reaps the whole tree through a
    # win32 job object or a POSIX session, so this check is a real measurement
    # on both platforms instead of an automatic Windows failure.
    cancellation_supported = False
    tree_terminated = False
    try:
        cancellation = ManagedProcess(
            [sys.executable, str(FIXTURE), "spawn-child"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except CancellationUnavailable:
        cancellation = None
    if cancellation is not None:
        cancellation_supported = True
        try:
            stdout = cancellation.process.stdout
            assert stdout is not None
            child_event = json.loads(stdout.readline().decode("utf-8"))
            child_pid = int(child_event["pid"])
            cancellation.cancel(grace_s=0.5)
        finally:
            # The container, not the graceful signal, is what guarantees no
            # survivor: `cancel` returns as soon as the *direct* child exits,
            # and `close` tears the container down (win32 KILL_ON_JOB_CLOSE,
            # POSIX session kill). Both halves are the cancellation contract,
            # so the measurement below runs after the container is gone.
            cancellation.close(grace_s=0.0)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and _pid_alive(child_pid):
            time.sleep(0.02)
        tree_terminated = (
            cancellation.returncode is not None and not _pid_alive(child_pid)
        )

    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir(parents=True)
    outside.mkdir(parents=True)
    sentinel = outside / "sentinel.txt"
    sentinel.write_text("unchanged\n", encoding="utf-8")
    allowed_target = workspace / "result.txt"
    allowed = subprocess.run(
        [
            sys.executable,
            str(FIXTURE),
            "write",
            "--workspace",
            str(workspace),
            "--target",
            str(allowed_target),
        ],
        check=False,
        text=True,
        capture_output=True,
        encoding="utf-8",
        timeout=10,
    )
    escaped_target = outside / "escape.txt"
    refused = subprocess.run(
        [
            sys.executable,
            str(FIXTURE),
            "write",
            "--workspace",
            str(workspace),
            "--target",
            str(escaped_target),
        ],
        check=False,
        text=True,
        capture_output=True,
        encoding="utf-8",
        timeout=10,
    )
    isolated = (
        allowed.returncode == 0
        and allowed_target.read_text(encoding="utf-8") == "fixture-output\n"
        and refused.returncode == 23
        and not escaped_target.exists()
        and sentinel.read_text(encoding="utf-8") == "unchanged\n"
    )

    def observation(
        check: str, passed: bool, detail: str, facts: dict[str, object]
    ) -> RecordedObservation:
        return RecordedObservation(
            passed=passed,
            detail=detail,
            transcript={
                "schema": "daedalus-offline-runtime-observation/1",
                "probe_identity_sha256": probe_identity_sha256,
                "check": check,
                "facts": facts,
            },
        )

    result = {
        "start": observation(
            "start",
            completed.returncode == 0
            and bool(events)
            and events[0]
            == {
                "event": "start",
                "protocol": "daedalus-runtime-fixture/1",
            },
            "fixture starts and emits the versioned protocol marker",
            {"exit_code": completed.returncode, "protocol_seen": bool(events)},
        ),
        "stream": observation(
            "stream",
            deltas == ["hel", "lo"],
            "fixture preserves ordered streaming deltas",
            {"delta_count": len(deltas), "joined_sha256": canonical_sha(deltas)},
        ),
        "tool-events": observation(
            "tool-events",
            len(tools) == 1
            and tools[0].get("name") == "read_file"
            and tools[0].get("arguments") == {"path": "fixture.txt"},
            "fixture emits one structured provider-neutral tool event",
            {
                "tool_count": len(tools),
                "tool_names": [row.get("name") for row in tools],
            },
        ),
        "structured-output": observation(
            "structured-output",
            len(finals) == 1
            and finals[0].get("value")
            == {
                "status": "done",
                "summary": "fixture complete",
                "files_changed": [],
            },
            "fixture final output matches the frozen structured shape",
            {"final_count": len(finals), "final_sha256": canonical_sha(finals)},
        ),
        "timeout": observation(
            "timeout",
            timed_out and timeout_process.returncode is not None,
            "fixture timeout terminates the process before returning",
            {
                "timeout_observed": timed_out,
                "process_reaped": timeout_process.returncode is not None,
            },
        ),
        "cancellation": observation(
            "cancellation",
            cancellation_supported and tree_terminated,
            "fixture cancellation terminates the complete child process tree",
            {
                "platform_supported": cancellation_supported,
                "process_tree_terminated": tree_terminated,
            },
        ),
        "workspace-isolation": observation(
            "workspace-isolation",
            isolated,
            "fixture accepts an in-workspace write and refuses an escape",
            {
                "allowed_exit": allowed.returncode,
                "escape_exit": refused.returncode,
                "outside_unchanged": sentinel.read_text(encoding="utf-8")
                == "unchanged\n",
            },
        ),
        "cost": observation(
            "cost",
            len(usages) == 1
            and usages[0]
            == {
                "event": "usage",
                "input_tokens": 11,
                "output_tokens": 7,
                "cost_microusd": 0,
            },
            "fixture emits exact non-negative provider-neutral usage",
            {"usage_count": len(usages), "usage_sha256": canonical_sha(usages)},
        ),
    }
    assert set(result) == set(RUNTIME_CONFORMANCE_CHECKS)
    return result


def _offline_bundle(tmp_path: Path, runtime_id: str):
    profiles = load_runtime_profiles(CATALOG)
    profile = profiles[runtime_id]
    adapter_sha = _adapter_sha256(profile.adapter_module)
    executable_sha = _file_sha256(_interpreter_image())
    environment_sha = _environment_sha256()
    fixture_sha = _file_sha256(FIXTURE)
    manifest = materialize_runtime_manifest(
        profile,
        runtime_version=f"offline-contract/{platform.python_version()}",
        adapter_version=f"source/{adapter_sha[:16]}",
        source_revision=REVISION,
        adapter_sha256=adapter_sha,
        executable_sha256=executable_sha,
        environment_sha256=environment_sha,
        fixture_suite_sha256=fixture_sha,
        created_at=NOW.isoformat(),
    )
    identity = build_probe_identity(
        profile,
        manifest,
        probe_id=f"{runtime_id}-offline-fixture",
        authority="offline-fixture",
        adapter_sha256=adapter_sha,
        executable_sha256=executable_sha,
        environment_sha256=environment_sha,
        fixture_suite_sha256=fixture_sha,
        collected_at=NOW.isoformat(),
    )
    observations = _protocol_observations(
        tmp_path, probe_identity_sha256=identity.digest
    )
    receipt = assemble_recorded_conformance(
        manifest,
        observations=observations,
        artifact_root=tmp_path / "cas",
        receipt_id=f"{runtime_id}-offline-receipt",
        started_at=NOW.isoformat(),
        finished_at=(NOW + timedelta(seconds=1)).isoformat(),
        trace_id=identity.probe_id,
    )
    receipt = dataclasses.replace(
        receipt,
        provenance=dataclasses.replace(
            receipt.provenance,
            input_digests=tuple(
                sorted({*receipt.provenance.input_digests, identity.digest})
            ),
        ),
    )
    envelope = bind_conformance_envelope(
        manifest,
        identity,
        receipt,
        envelope_id=f"{runtime_id}-offline-envelope",
        created_at=(NOW + timedelta(seconds=1)).isoformat(),
    )
    return profile, manifest, identity, receipt, envelope


def test_catalog_is_strict_complete_and_conservative() -> None:
    profiles = load_runtime_profiles(CATALOG)
    assert tuple(profiles) == tuple(sorted(REQUIRED_GATE0_RUNTIME_IDS))
    assert profiles["claude_code_cli"].capabilities.streaming is False
    assert profiles["codex_cli"].capabilities.cancellation is False
    assert profiles["ollama_http"].capabilities.tool_events is True
    assert all(
        profile.digest == canonical_sha(profile.to_dict())
        for profile in profiles.values()
    )


@pytest.mark.parametrize("runtime_id", REQUIRED_GATE0_RUNTIME_IDS)
def test_each_runtime_profile_runs_the_same_offline_contract_but_cannot_authorize(
    tmp_path: Path, runtime_id: str
) -> None:
    _, manifest, identity, receipt, envelope = _offline_bundle(
        tmp_path / runtime_id, runtime_id
    )
    assert receipt.status == "passed"
    assert identity.authority == "offline-fixture"
    assert envelope.production_eligible is False
    verify_runtime_envelope(
        envelope,
        identity,
        receipt,
        manifest,
        now=NOW + timedelta(days=1),
        require_live=False,
    )
    with pytest.raises(RuntimeConformanceError, match="cannot authorize"):
        verify_runtime_envelope(
            envelope,
            identity,
            receipt,
            manifest,
            now=NOW + timedelta(days=1),
        )


def test_offline_evidence_is_deterministic_and_round_trips(tmp_path: Path) -> None:
    first = _offline_bundle(tmp_path / "first", "codex_cli")
    second = _offline_bundle(tmp_path / "second", "codex_cli")
    assert first[0].digest == second[0].digest
    assert first[1].digest == second[1].digest
    assert first[2].digest == second[2].digest
    assert first[3].digest == second[3].digest
    assert first[4].digest == second[4].digest
    assert RuntimeProbeIdentity.from_dict(first[2].to_dict()) == first[2]
    assert RuntimeConformanceEnvelope.from_dict(first[4].to_dict()) == first[4]


def test_stale_repacked_and_cross_runtime_evidence_refuses(tmp_path: Path) -> None:
    _, manifest, identity, receipt, envelope = _offline_bundle(
        tmp_path / "claude", "claude_code_cli"
    )
    with pytest.raises(RuntimeConformanceError, match="stale"):
        verify_runtime_envelope(
            envelope,
            identity,
            receipt,
            manifest,
            now=NOW + timedelta(days=8),
            require_live=False,
        )

    _, other_manifest, other_identity, other_receipt, _ = _offline_bundle(
        tmp_path / "ollama", "ollama_http"
    )
    with pytest.raises(RuntimeConformanceError, match="binding mismatch"):
        verify_runtime_envelope(
            envelope,
            other_identity,
            other_receipt,
            other_manifest,
            now=NOW + timedelta(days=1),
            require_live=False,
        )

    repacked_receipt = dataclasses.replace(
        receipt,
        provenance=dataclasses.replace(
            receipt.provenance,
            input_digests=tuple(
                value
                for value in receipt.provenance.input_digests
                if value != identity.digest
            ),
        ),
    )
    with pytest.raises(RuntimeConformanceError, match="probe identity"):
        bind_conformance_envelope(
            manifest,
            identity,
            repacked_receipt,
            envelope_id="repacked",
            created_at=NOW.isoformat(),
        )


def test_malformed_duplicate_and_membership_drift_catalogs_refuse(
    tmp_path: Path,
) -> None:
    original = CATALOG.read_text(encoding="utf-8")
    duplicate = original.replace(
        '"schema": "daedalus-runtime-profile-catalog/1"',
        '"schema": "daedalus-runtime-profile-catalog/1",\n'
        '  "schema": "daedalus-runtime-profile-catalog/1"',
        1,
    )
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(duplicate, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_runtime_profiles(duplicate_path)

    payload = json.loads(original)
    payload["profiles"] = payload["profiles"][:-1]
    missing_path = tmp_path / "missing.json"
    missing_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="membership differs"):
        load_runtime_profiles(missing_path)

    payload = json.loads(original)
    payload["profiles"][0]["capabilities"]["invented"] = True
    malformed_path = tmp_path / "malformed.json"
    malformed_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="capability fields differ"):
        load_runtime_profiles(malformed_path)
