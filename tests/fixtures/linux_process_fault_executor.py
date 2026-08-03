#!/usr/bin/env python3
"""Execute the two canonical Linux process fault scenarios.

This is a host test fixture, not a production runtime entrypoint and not a trust
anchor. It emits collector records that still require an external
``RuntimeFaultAttestation`` before they may satisfy the canonical fault matrix.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import (
    HostFaultFact,
    HostFaultResult,
    LinuxHostExecutorBinding,
    LinuxHostFaultRun,
    run_linux_host_fault,
)
from daedalus.spine.envelope import canonical_json, canonical_sha

_FIXTURE_SCHEMA = "daedalus-linux-process-tree-fixture/1"
_REPORT_SCHEMA = "daedalus-linux-process-fault-report/1"
_FIXTURE = Path(__file__).with_name("linux_process_tree_fixture.py")
_READY_TIMEOUT_S = 5.0
_EXECUTION_TIMEOUT_S = 0.20
_TERM_GRACE_S = 0.35
_GROUP_QUIESCE_S = 3.0
_MAX_READY_BYTES = 4096


class LinuxProcessFaultError(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_sha256() -> str:
    return canonical_sha(
        {
            "schema": _REPORT_SCHEMA,
            "executor_sha256": _file_sha256(Path(__file__)),
            "fixture_sha256": _file_sha256(_FIXTURE),
        }
    )


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LinuxProcessFaultError(f"duplicate readiness key: {key}")
        result[key] = value
    return result


def _strict_readiness(line: str, *, process_pid: int, ignore_sigterm: bool) -> dict[str, Any]:
    if len(line.encode("utf-8")) > _MAX_READY_BYTES:
        raise LinuxProcessFaultError("readiness record exceeds four KiB")
    try:
        payload = json.loads(line, object_pairs_hook=_no_duplicate_keys)
    except json.JSONDecodeError as exc:
        raise LinuxProcessFaultError("readiness record is malformed JSON") from exc
    if not isinstance(payload, Mapping):
        raise LinuxProcessFaultError("readiness record must be an object")
    expected = {
        "schema",
        "parent_pid",
        "process_group_id",
        "child_pids",
        "ignore_sigterm",
    }
    if set(payload) != expected:
        raise LinuxProcessFaultError("readiness record fields do not match the fixture contract")
    if payload["schema"] != _FIXTURE_SCHEMA:
        raise LinuxProcessFaultError("readiness schema mismatch")
    if type(payload["parent_pid"]) is not int or payload["parent_pid"] != process_pid:
        raise LinuxProcessFaultError("readiness parent PID mismatch")
    if type(payload["process_group_id"]) is not int:
        raise LinuxProcessFaultError("readiness process group must be an integer")
    if payload["process_group_id"] != process_pid:
        raise LinuxProcessFaultError("fixture is not the expected process-group leader")
    if type(payload["ignore_sigterm"]) is not bool:
        raise LinuxProcessFaultError("readiness signal policy must be boolean")
    if payload["ignore_sigterm"] is not ignore_sigterm:
        raise LinuxProcessFaultError("readiness signal policy mismatch")
    children = payload["child_pids"]
    if not isinstance(children, list) or len(children) != 1:
        raise LinuxProcessFaultError("readiness must contain exactly one child PID")
    if type(children[0]) is not int or children[0] <= 1:
        raise LinuxProcessFaultError("readiness child PID is invalid")
    return dict(payload)


def _read_ready(process: subprocess.Popen[str], *, ignore_sigterm: bool) -> dict[str, Any]:
    if process.stdout is None:
        raise LinuxProcessFaultError("fixture stdout is unavailable")
    readable, _, _ = select.select([process.stdout], [], [], _READY_TIMEOUT_S)
    if not readable:
        raise LinuxProcessFaultError("fixture did not publish readiness before timeout")
    line = process.stdout.readline()
    if not line:
        raise LinuxProcessFaultError("fixture exited without a readiness record")
    return _strict_readiness(
        line,
        process_pid=process.pid,
        ignore_sigterm=ignore_sigterm,
    )


def _proc_state(pid: int) -> str | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return None
    closing = text.rfind(")")
    if closing < 0:
        return None
    remainder = text[closing + 2 :].split()
    return remainder[0] if remainder else None


def _group_members(process_group_id: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    live: list[int] = []
    zombies: list[int] = []
    try:
        names = os.listdir("/proc")
    except OSError as exc:
        raise LinuxProcessFaultError("/proc is unavailable") from exc
    for name in names:
        if not name.isdigit():
            continue
        pid = int(name)
        try:
            if os.getpgid(pid) != process_group_id:
                continue
        except (PermissionError, ProcessLookupError, OSError):
            continue
        state = _proc_state(pid)
        if state is None:
            continue
        if state == "Z":
            zombies.append(pid)
        else:
            live.append(pid)
    return tuple(sorted(live)), tuple(sorted(zombies))


def _wait_for_quiescence(process_group_id: int) -> tuple[tuple[int, ...], tuple[int, ...]]:
    deadline = time.monotonic() + _GROUP_QUIESCE_S
    while True:
        live, zombies = _group_members(process_group_id)
        if not live:
            return live, zombies
        if time.monotonic() >= deadline:
            return live, zombies
        time.sleep(0.02)


def _safe_group(process: subprocess.Popen[str]) -> int:
    if process.pid <= 1:
        raise LinuxProcessFaultError("fixture process PID is unsafe")
    try:
        process_group_id = os.getpgid(process.pid)
    except ProcessLookupError as exc:
        raise LinuxProcessFaultError("fixture exited before process-group validation") from exc
    if process_group_id != process.pid:
        raise LinuxProcessFaultError("fixture is not isolated in a new process group")
    if process_group_id == os.getpgrp():
        raise LinuxProcessFaultError("refusing to target the collector process group")
    return process_group_id


def _force_cleanup(process: subprocess.Popen[str], process_group_id: int | None) -> None:
    if process.poll() is not None:
        return
    try:
        if process_group_id is not None and process_group_id > 1:
            os.killpg(process_group_id, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2.0)


def _evidence_payload(
    *,
    scenario_id: str,
    scenario_sha256: str,
    metadata: Mapping[str, Any] | None,
    timed_out: bool,
    sent_sigterm: bool,
    escalated_sigkill: bool,
    returncode: int | None,
    live_members: tuple[int, ...],
    zombie_members: tuple[int, ...],
    elapsed_ms: int,
    error_code: str | None,
    error_type: str | None,
) -> dict[str, Any]:
    return {
        "schema": _REPORT_SCHEMA,
        "scenario_id": scenario_id,
        "scenario_sha256": scenario_sha256,
        "executor_implementation_sha256": implementation_sha256(),
        "fixture_sha256": _file_sha256(_FIXTURE),
        "metadata": dict(metadata) if metadata is not None else None,
        "timed_out": timed_out,
        "sent_sigterm": sent_sigterm,
        "escalated_sigkill": escalated_sigkill,
        "returncode": returncode,
        "live_group_members": list(live_members),
        "zombie_group_members": list(zombie_members),
        "elapsed_ms": elapsed_ms,
        "error_code": error_code,
        "error_type": error_type,
    }


def _execute_process_fault(scenario, *, ignore_sigterm: bool) -> HostFaultResult:
    if sys.platform != "linux":
        return HostFaultResult(
            status="blocked",
            observed_outcome=None,
            detail_code="linux-required",
            raw_evidence=canonical_json(
                {
                    "schema": _REPORT_SCHEMA,
                    "scenario_id": scenario.scenario_id,
                    "platform": sys.platform,
                }
            ).encode("utf-8"),
            facts=(HostFaultFact("platform", sys.platform),),
        )
    command = [sys.executable, str(_FIXTURE)]
    if ignore_sigterm:
        command.append("--ignore-sigterm")
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
        close_fds=True,
        bufsize=1,
    )
    process_group_id: int | None = None
    metadata: dict[str, Any] | None = None
    timed_out = False
    sent_sigterm = False
    escalated_sigkill = False
    live_members: tuple[int, ...] = ()
    zombie_members: tuple[int, ...] = ()
    try:
        process_group_id = _safe_group(process)
        metadata = _read_ready(process, ignore_sigterm=ignore_sigterm)
        try:
            process.wait(timeout=_EXECUTION_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            timed_out = True
        if not timed_out:
            raise LinuxProcessFaultError("fixture exited before the injected timeout")
        os.killpg(process_group_id, signal.SIGTERM)
        sent_sigterm = True
        try:
            process.wait(timeout=_TERM_GRACE_S)
        except subprocess.TimeoutExpired:
            escalated_sigkill = True
            os.killpg(process_group_id, signal.SIGKILL)
            process.wait(timeout=2.0)
        live_members, zombie_members = _wait_for_quiescence(process_group_id)
        if live_members:
            raise LinuxProcessFaultError("live process-group members remain after cancellation")
        if ignore_sigterm and not escalated_sigkill:
            raise LinuxProcessFaultError("SIGTERM-ignore fixture did not require escalation")
        if not ignore_sigterm and escalated_sigkill:
            raise LinuxProcessFaultError("ordinary timeout fixture unexpectedly required SIGKILL")
        expected_signal = signal.SIGKILL if ignore_sigterm else signal.SIGTERM
        if process.returncode != -expected_signal:
            raise LinuxProcessFaultError("fixture terminal signal does not match the scenario")
        elapsed_ms = int((time.monotonic() - started) * 1000)
        payload = _evidence_payload(
            scenario_id=scenario.scenario_id,
            scenario_sha256=scenario.digest,
            metadata=metadata,
            timed_out=timed_out,
            sent_sigterm=sent_sigterm,
            escalated_sigkill=escalated_sigkill,
            returncode=process.returncode,
            live_members=live_members,
            zombie_members=zombie_members,
            elapsed_ms=elapsed_ms,
            error_code=None,
            error_type=None,
        )
        return HostFaultResult(
            status="passed",
            observed_outcome="cancelled",
            detail_code=None,
            raw_evidence=canonical_json(payload).encode("utf-8"),
            facts=(
                HostFaultFact("child-count", str(len(metadata["child_pids"]))),
                HostFaultFact("elapsed-ms", str(elapsed_ms)),
                HostFaultFact("live-group-members", "none"),
                HostFaultFact(
                    "sigkill-escalated", "true" if escalated_sigkill else "false"
                ),
                HostFaultFact(
                    "zombie-group-members",
                    ",".join(str(pid) for pid in zombie_members) or "none",
                ),
            ),
        )
    except Exception as exc:
        _force_cleanup(process, process_group_id)
        if process_group_id is not None:
            live_members, zombie_members = _wait_for_quiescence(process_group_id)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        payload = _evidence_payload(
            scenario_id=scenario.scenario_id,
            scenario_sha256=scenario.digest,
            metadata=metadata,
            timed_out=timed_out,
            sent_sigterm=sent_sigterm,
            escalated_sigkill=escalated_sigkill,
            returncode=process.returncode,
            live_members=live_members,
            zombie_members=zombie_members,
            elapsed_ms=elapsed_ms,
            error_code="process-fault-invariant",
            error_type=type(exc).__name__,
        )
        return HostFaultResult(
            status="failed",
            observed_outcome="failed",
            detail_code="process-fault-invariant",
            raw_evidence=canonical_json(payload).encode("utf-8"),
            facts=(
                HostFaultFact("error-type", type(exc).__name__),
                HostFaultFact("live-group-members", ",".join(map(str, live_members)) or "none"),
            ),
        )
    finally:
        _force_cleanup(process, process_group_id)


def process_fault_bindings() -> dict[str, LinuxHostExecutorBinding]:
    implementation = implementation_sha256()
    timeout = RUNTIME_FAULT_CATALOG.scenario_map["runtime.process.timeout"]
    ignored = RUNTIME_FAULT_CATALOG.scenario_map["runtime.process.ignored-sigterm"]
    return {
        timeout.executor: LinuxHostExecutorBinding(
            locator=timeout.executor,
            implementation_sha256=implementation,
            execute=lambda row: _execute_process_fault(row, ignore_sigterm=False),
        ),
        ignored.executor: LinuxHostExecutorBinding(
            locator=ignored.executor,
            implementation_sha256=implementation,
            execute=lambda row: _execute_process_fault(row, ignore_sigterm=True),
        ),
    }


def run_process_faults(*, source_revision: str) -> tuple[LinuxHostFaultRun, ...]:
    bindings = process_fault_bindings()
    rows = []
    for scenario_id in ("runtime.process.timeout", "runtime.process.ignored-sigterm"):
        scenario = RUNTIME_FAULT_CATALOG.scenario_map[scenario_id]
        rows.append(
            run_linux_host_fault(
                scenario,
                source_revision=source_revision,
                executor=bindings[scenario.executor],
            )
        )
    return tuple(rows)


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise LinuxProcessFaultError("refusing to replace an output symlink")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def publish_process_faults(*, source_revision: str, output_dir: Path) -> dict[str, Any]:
    if output_dir.is_symlink():
        raise LinuxProcessFaultError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    runs = run_process_faults(source_revision=source_revision)
    summary_rows = []
    for run in runs:
        prefix = run.observation.scenario_id
        _atomic_write(
            output_dir / f"{prefix}.evidence.json",
            (canonical_json(run.evidence.to_dict()) + "\n").encode("utf-8"),
        )
        _atomic_write(
            output_dir / f"{prefix}.observation.json",
            (canonical_json(run.observation.to_dict()) + "\n").encode("utf-8"),
        )
        _atomic_write(output_dir / f"{prefix}.raw", run.raw_evidence)
        summary_rows.append(
            {
                "scenario_id": run.observation.scenario_id,
                "status": run.observation.status,
                "observed_outcome": run.observation.observed_outcome,
                "evidence_sha256": run.evidence.digest,
                "observation_sha256": run.observation.digest,
                "run_sha256": run.digest,
            }
        )
    summary = {
        "schema": _REPORT_SCHEMA,
        "source_revision": source_revision,
        "executor_implementation_sha256": implementation_sha256(),
        "runs": summary_rows,
        "trusted": False,
        "attested": False,
        "gate_closure_claimed": False,
    }
    _atomic_write(
        output_dir / "summary.json",
        (canonical_json(summary) + "\n").encode("utf-8"),
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = publish_process_faults(
        source_revision=args.source_revision,
        output_dir=args.output_dir,
    )
    print(canonical_json(summary))
    return 0 if all(row["status"] == "passed" for row in summary["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
