#!/usr/bin/env python3
"""Execute the canonical Effect-Lease SQLite writer-contention fault.

This is a Linux host test fixture, not a production runtime entrypoint and not a
trust anchor. It drives the real ``EffectLeaseLedger.begin`` path while another
connection owns the writer lock. The shortened busy timeout is injected only by
this fixture so the semantic fault can run quickly in CI; the production
transaction ordering and persistence code are otherwise unchanged.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import daedalus.kernel.effects as effects_module
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseLedger,
    issue_effect_lease,
)
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import (
    HostFaultFact,
    HostFaultResult,
    LinuxHostExecutorBinding,
    LinuxHostFaultRun,
    run_linux_host_fault,
)
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)
from daedalus.spine.envelope import canonical_json, canonical_sha

_REPORT_SCHEMA = "daedalus-linux-effect-ledger-lock-fault/1"
_SCENARIO_ID = "runtime.effect-ledger.lock-contention"
_BUSY_TIMEOUT_MS = 150
_SECRET = b"linux-effect-lock-fault-secret-material-32-bytes"
_POLICY_SHA256 = "b" * 64
_NOW = datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc)


class LinuxEffectLedgerLockFaultError(RuntimeError):
    pass


class _ShortBusyEffectLeaseLedger(EffectLeaseLedger):
    """Production ledger semantics with a bounded test-only lock timeout."""

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            isolation_level=None,
            timeout=_BUSY_TIMEOUT_MS / 1000,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
        return connection


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def implementation_sha256() -> str:
    production_path = Path(effects_module.__file__).resolve()
    return canonical_sha(
        {
            "schema": _REPORT_SCHEMA,
            "executor_sha256": _file_sha256(Path(__file__)),
            "production_effects_sha256": _file_sha256(production_path),
            "busy_timeout_ms": _BUSY_TIMEOUT_MS,
        }
    )


def _registry() -> dict[str, EntrypointSpec]:
    spec = EntrypointSpec(
        id="python.lock-fault-provider",
        surface=Surface.PYTHON,
        target="tests.fixtures.lock_fault:provider",
        effects=(Effect.PROCESS_SPAWN,),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
    )
    return {spec.id: spec}


def _lease_material(source_revision: str):
    scope = EffectScope(
        read_only=True,
        tools=("python",),
        max_cost_microusd=0,
        max_concurrency=1,
        timeout_s=60,
        kill_switch_ref="mission-kill",
    )
    request = EffectLeaseRequest(
        request_id="effect-lock-request",
        mission_id="effect-lock-mission",
        attempt_id="effect-lock-attempt",
        entrypoint_id="python.lock-fault-provider",
        requested_effects=(Effect.PROCESS_SPAWN.value,),
        effect_scope=scope,
        idempotency_namespace="effect-lock-attempt",
        kill_switch_generation=1,
        provenance=ContractProvenance(
            origin="tests.linux-effect-ledger-lock-fault",
            source_revision=source_revision,
            created_at=_NOW.isoformat(),
            input_digests=(),
            trace_id="effect-lock-mission",
        ),
    )
    policy = PolicyDecision(
        decision_id="effect-lock-policy",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-03",
        policy_sha256=_POLICY_SHA256,
        verdict="allow",
        reasons=("bounded lock-contention fixture",),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="tests.linux-effect-ledger-lock-policy",
            source_revision=source_revision,
            created_at=_NOW.isoformat(),
            input_digests=(request.digest, _POLICY_SHA256),
            trace_id="effect-lock-mission",
        ),
    )
    registry = _registry()
    lease = issue_effect_lease(
        request,
        policy,
        lease_id="effect-lock-lease",
        issuer_key_id="effect-lock-key",
        issued_at=_NOW,
        expires_at=_NOW + timedelta(minutes=10),
        secret=_SECRET,
        registry=registry,
    )
    execution = EffectExecutionRequest(
        execution_id="effect-lock-execution",
        idempotency_key="effect-lock-idempotency",
        requested_effects=(Effect.PROCESS_SPAWN.value,),
        tools=("python",),
        max_cost_microusd=0,
        kill_switch_ref="mission-kill",
        kill_switch_generation=1,
    )
    guards = (
        GuardDecision(
            "budget.process_guard",
            True,
            "artifact-locator:sha256:" + "e" * 64,
        ),
    )
    return request, policy, lease, execution, guards, registry


def _execute_effect_lock_fault(scenario) -> HostFaultResult:
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

    source_revision = "a" * 40
    request, policy, lease, execution, guards, registry = _lease_material(source_revision)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="daedalus-effect-lock-") as temporary:
        root = Path(temporary)
        database = root / "effects.sqlite3"
        marker = root / "provider-ran"
        ledger = _ShortBusyEffectLeaseLedger(database)
        ledger.grant(
            lease,
            request=request,
            policy_decision=policy,
            keyring={"effect-lock-key": _SECRET},
            current_kill_switch_generation=1,
            granted_at=_NOW + timedelta(seconds=1),
            registry=registry,
        )

        blocker = sqlite3.connect(str(database), isolation_level=None, timeout=1)
        blocker.row_factory = sqlite3.Row
        blocker.execute("PRAGMA foreign_keys=ON")
        blocker.execute("PRAGMA journal_mode=WAL")
        blocker.execute("PRAGMA synchronous=FULL")
        blocker.execute("BEGIN IMMEDIATE")

        error_type: str | None = None
        sqlite_error_name: str | None = None
        sqlite_error_code: int | None = None
        lock_refused = False
        execution_rows_while_locked = -1
        try:
            try:
                start = ledger.begin(
                    lease,
                    execution,
                    request=request,
                    policy_decision=policy,
                    keyring={"effect-lock-key": _SECRET},
                    guard_decisions=guards,
                    current_kill_switch_generation=1,
                    started_at=_NOW + timedelta(seconds=2),
                    registry=registry,
                )
                if start.execute:
                    marker.write_text("provider callback executed\n", encoding="utf-8")
            except sqlite3.OperationalError as exc:
                error_type = type(exc).__name__
                sqlite_error_name = getattr(exc, "sqlite_errorname", None)
                sqlite_error_code = getattr(exc, "sqlite_errorcode", None)
                lock_refused = (
                    sqlite_error_name in {"SQLITE_BUSY", "SQLITE_LOCKED"}
                    or "locked" in str(exc).lower()
                )
            execution_rows_while_locked = int(
                blocker.execute("SELECT COUNT(*) FROM effect_executions").fetchone()[0]
            )
        finally:
            blocker.execute("ROLLBACK")
            blocker.close()

        persisted_state = ledger.execution_state(execution.execution_id)
        marker_exists = marker.exists()
        elapsed_ms = int((time.monotonic() - started) * 1000)
        passed = (
            lock_refused
            and execution_rows_while_locked == 0
            and persisted_state is None
            and not marker_exists
        )
        payload: dict[str, Any] = {
            "schema": _REPORT_SCHEMA,
            "scenario_id": scenario.scenario_id,
            "scenario_sha256": scenario.digest,
            "executor_implementation_sha256": implementation_sha256(),
            "production_effects_sha256": _file_sha256(
                Path(effects_module.__file__).resolve()
            ),
            "busy_timeout_ms": _BUSY_TIMEOUT_MS,
            "elapsed_ms": elapsed_ms,
            "lock_refused": lock_refused,
            "execution_rows_while_locked": execution_rows_while_locked,
            "persisted_execution_state": persisted_state,
            "provider_marker_exists": marker_exists,
            "error_type": error_type,
            "sqlite_error_name": sqlite_error_name,
            "sqlite_error_code": sqlite_error_code,
        }
        if passed:
            return HostFaultResult(
                status="passed",
                observed_outcome="refused-before-start",
                detail_code=None,
                raw_evidence=canonical_json(payload).encode("utf-8"),
                facts=(
                    HostFaultFact("busy-timeout-ms", str(_BUSY_TIMEOUT_MS)),
                    HostFaultFact("execution-rows", "0"),
                    HostFaultFact("provider-effect", "not-started"),
                    HostFaultFact("sqlite-result", sqlite_error_name or error_type or "locked"),
                ),
            )
        return HostFaultResult(
            status="failed",
            observed_outcome="failed",
            detail_code="effect-lock-invariant",
            raw_evidence=canonical_json(payload).encode("utf-8"),
            facts=(
                HostFaultFact("error-type", error_type or "missing-lock-error"),
                HostFaultFact("execution-rows", str(execution_rows_while_locked)),
                HostFaultFact("provider-effect", "started" if marker_exists else "not-started"),
            ),
        )


def effect_lock_binding() -> LinuxHostExecutorBinding:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[_SCENARIO_ID]
    return LinuxHostExecutorBinding(
        locator=scenario.executor,
        implementation_sha256=implementation_sha256(),
        execute=_execute_effect_lock_fault,
    )


def run_effect_lock_fault(*, source_revision: str) -> LinuxHostFaultRun:
    scenario = RUNTIME_FAULT_CATALOG.scenario_map[_SCENARIO_ID]
    return run_linux_host_fault(
        scenario,
        source_revision=source_revision,
        executor=effect_lock_binding(),
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise LinuxEffectLedgerLockFaultError("refusing to replace an output symlink")
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


def publish_effect_lock_fault(*, source_revision: str, output_dir: Path) -> dict[str, Any]:
    if output_dir.is_symlink():
        raise LinuxEffectLedgerLockFaultError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    run = run_effect_lock_fault(source_revision=source_revision)
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
    summary = {
        "schema": _REPORT_SCHEMA,
        "source_revision": source_revision,
        "executor_implementation_sha256": implementation_sha256(),
        "run": {
            "scenario_id": run.observation.scenario_id,
            "status": run.observation.status,
            "observed_outcome": run.observation.observed_outcome,
            "evidence_sha256": run.evidence.digest,
            "observation_sha256": run.observation.digest,
            "run_sha256": run.digest,
        },
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
    summary = publish_effect_lock_fault(
        source_revision=args.source_revision,
        output_dir=args.output_dir,
    )
    print(canonical_json(summary))
    return 0 if summary["run"]["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
