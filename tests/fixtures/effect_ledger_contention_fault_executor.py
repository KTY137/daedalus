#!/usr/bin/env python3
"""Execute the canonical effect-ledger lock-contention host fault.

The fixture inherits the production ``EffectLeaseLedger`` transaction logic and
only narrows its SQLite busy timeout so the fault remains bounded in CI. It is a
test-side Linux host executor, not a production effect entrypoint or trust root.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

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

_REPORT_SCHEMA = "daedalus-effect-ledger-contention-fault/1"
_SCENARIO_ID = "runtime.effect-ledger.lock-contention"
_BUSY_TIMEOUT_MS = 125
_TIMEOUT_TOLERANCE_MS = 25
_NOW = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
_SECRET = b"effect-ledger-contention-secret-material-32-bytes"
_POLICY_SHA = "b" * 64


class EffectLedgerContentionFaultError(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _effects_source_path() -> Path:
    source = getattr(effects_module, "__file__", None)
    if not source:
        raise EffectLedgerContentionFaultError(
            "production effect ledger has no source-file identity"
        )
    path = Path(source).resolve()
    if not path.is_file():
        raise EffectLedgerContentionFaultError(
            "production effect ledger source file is unavailable"
        )
    return path


def implementation_sha256() -> str:
    return canonical_sha(
        {
            "schema": _REPORT_SCHEMA,
            "executor_sha256": _file_sha256(Path(__file__).resolve()),
            "effect_ledger_sha256": _file_sha256(_effects_source_path()),
        }
    )


def _canonical_scenario():
    return RUNTIME_FAULT_CATALOG.scenario_map[_SCENARIO_ID]


def _assert_scenario(scenario) -> None:
    canonical = _canonical_scenario()
    comparisons = {
        "scenario_id": (scenario.scenario_id, canonical.scenario_id),
        "scenario_sha256": (scenario.digest, canonical.digest),
        "authority": (scenario.authority, canonical.authority),
        "executor": (scenario.executor, canonical.executor),
        "expected_outcome": (
            scenario.expected_outcome,
            canonical.expected_outcome,
        ),
    }
    mismatches = sorted(
        name for name, (actual, expected) in comparisons.items() if actual != expected
    )
    if mismatches:
        raise EffectLedgerContentionFaultError(
            "effect-ledger contention scenario binding mismatch: "
            + ", ".join(mismatches)
        )


class BoundedEffectLeaseLedger(EffectLeaseLedger):
    """Production ledger operations with a fixture-controlled busy timeout."""

    def __init__(self, path: str | Path, *, busy_timeout_ms: int) -> None:
        if (
            isinstance(busy_timeout_ms, bool)
            or not isinstance(busy_timeout_ms, int)
            or not 1 <= busy_timeout_ms <= 10_000
        ):
            raise ValueError("busy_timeout_ms must be an integer in [1, 10000]")
        self.busy_timeout_ms = busy_timeout_ms
        super().__init__(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            isolation_level=None,
            timeout=self.busy_timeout_ms / 1000,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")
            return connection
        except sqlite3.Error:
            connection.close()
            raise


def _central_spec() -> EntrypointSpec:
    return EntrypointSpec(
        id="python.central-attempt",
        surface=Surface.PYTHON,
        target="tests.fake:run",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
    )


def _authority(source_revision: str):
    spec = _central_spec()
    registry = {spec.id: spec}
    scope = EffectScope(
        read_only=False,
        writable_paths=("workspace",),
        tools=("python",),
        max_cost_microusd=100,
        max_concurrency=1,
        timeout_s=60,
        kill_switch_ref="mission-kill",
    )
    request = EffectLeaseRequest(
        request_id="contention-request",
        mission_id="contention-mission",
        attempt_id="contention-attempt",
        entrypoint_id=spec.id,
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
            Effect.SPEND.value,
        ),
        effect_scope=scope,
        idempotency_namespace="contention-attempt",
        kill_switch_generation=7,
        provenance=ContractProvenance(
            origin="tests.effect-ledger-contention",
            source_revision=source_revision,
            created_at=_NOW.isoformat(),
            input_digests=(),
            trace_id="contention-mission",
        ),
    )
    policy = PolicyDecision(
        decision_id="contention-policy",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-03",
        policy_sha256=_POLICY_SHA,
        verdict="allow",
        reasons=("bounded central effect",),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="tests.effect-ledger-contention-policy",
            source_revision=source_revision,
            created_at=_NOW.isoformat(),
            input_digests=(request.digest, _POLICY_SHA),
            trace_id="contention-mission",
        ),
    )
    lease = issue_effect_lease(
        request,
        policy,
        lease_id="contention-lease",
        issuer_key_id="contention-key",
        issued_at=_NOW,
        expires_at=_NOW + timedelta(minutes=10),
        secret=_SECRET,
        registry=registry,
    )
    execution = EffectExecutionRequest(
        execution_id="contention-execution",
        idempotency_key="contention-idempotency",
        requested_effects=request.requested_effects,
        writable_paths=("workspace/out.txt",),
        tools=("python",),
        max_cost_microusd=100,
        kill_switch_ref="mission-kill",
        kill_switch_generation=7,
    )
    guards = (
        GuardDecision(
            "budget.process_guard",
            True,
            "artifact-locator:sha256:" + "e" * 64,
        ),
    )
    return registry, request, policy, lease, execution, guards


def _sqlite_error_code(exc: sqlite3.OperationalError) -> int | None:
    value = getattr(exc, "sqlite_errorcode", None)
    return value if isinstance(value, int) else None


def _is_lock_contention(exc: sqlite3.OperationalError) -> bool:
    code = _sqlite_error_code(exc)
    contention_codes = {
        getattr(sqlite3, "SQLITE_BUSY", 5),
        getattr(sqlite3, "SQLITE_LOCKED", 6),
    }
    if code is not None and (code & 0xFF) in contention_codes:
        return True
    # Python 3.10 may not expose sqlite_errorcode. The message is inspected only
    # for classification and is never retained in evidence.
    text = str(exc).lower()
    return "locked" in text or "busy" in text


def _execution_count(path: Path, execution_id: str) -> int:
    with sqlite3.connect(str(path)) as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM effect_executions WHERE execution_id=?",
                (execution_id,),
            ).fetchone()[0]
        )


def _execute_effect_contention(scenario) -> HostFaultResult:
    _assert_scenario(scenario)
    if sys.platform != "linux":
        payload = {
            "schema": _REPORT_SCHEMA,
            "scenario_id": scenario.scenario_id,
            "platform": sys.platform,
            "status": "blocked",
            "detail_code": "linux-required",
        }
        return HostFaultResult(
            status="blocked",
            observed_outcome=None,
            detail_code="linux-required",
            raw_evidence=canonical_json(payload).encode("utf-8"),
            facts=(HostFaultFact("platform", sys.platform),),
        )

    with tempfile.TemporaryDirectory(prefix="daedalus-effect-contention-") as root_text:
        root = Path(root_text)
        database = root / "effects.sqlite3"
        registry, request, policy, lease, execution, guards = _authority(
            scenario.digest
        )
        ledger = BoundedEffectLeaseLedger(
            database,
            busy_timeout_ms=_BUSY_TIMEOUT_MS,
        )
        ledger.grant(
            lease,
            request=request,
            policy_decision=policy,
            keyring={"contention-key": _SECRET},
            current_kill_switch_generation=7,
            granted_at=_NOW + timedelta(milliseconds=1),
            registry=registry,
        )

        blocker = sqlite3.connect(str(database), isolation_level=None, timeout=1)
        blocker.execute("PRAGMA journal_mode=WAL")
        blocker.execute("PRAGMA busy_timeout=1000")
        blocker.execute("BEGIN IMMEDIATE")
        writer_lock_held = blocker.in_transaction
        provider_called = False
        observed_error: sqlite3.OperationalError | None = None
        started = time.monotonic()
        try:
            try:
                start = ledger.begin(
                    lease,
                    execution,
                    request=request,
                    policy_decision=policy,
                    keyring={"contention-key": _SECRET},
                    guard_decisions=guards,
                    current_kill_switch_generation=7,
                    started_at=_NOW + timedelta(seconds=1),
                    registry=registry,
                )
                if start.execute:
                    provider_called = True
            except sqlite3.OperationalError as exc:
                observed_error = exc
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            blocker.execute("ROLLBACK")
            blocker.close()

        execution_count = _execution_count(database, execution.execution_id)
        contention = observed_error is not None and _is_lock_contention(observed_error)
        sqlite_code = (
            _sqlite_error_code(observed_error)
            if observed_error is not None
            else None
        )
        payload: dict[str, Any] = {
            "schema": _REPORT_SCHEMA,
            "scenario_id": scenario.scenario_id,
            "scenario_sha256": scenario.digest,
            "executor_implementation_sha256": implementation_sha256(),
            "effect_ledger_sha256": _file_sha256(_effects_source_path()),
            "database_path_sha256": hashlib.sha256(
                str(database).encode("utf-8")
            ).hexdigest(),
            "busy_timeout_ms": _BUSY_TIMEOUT_MS,
            "elapsed_ms": elapsed_ms,
            "writer_lock_held": writer_lock_held,
            "contention_observed": contention,
            "exception_module": (
                type(observed_error).__module__ if observed_error else None
            ),
            "exception_type": (
                type(observed_error).__qualname__ if observed_error else None
            ),
            "sqlite_errorcode": sqlite_code,
            "provider_called": provider_called,
            "execution_row_count": execution_count,
        }
        passed = (
            writer_lock_held
            and contention
            and not provider_called
            and execution_count == 0
            and elapsed_ms >= max(
                1,
                _BUSY_TIMEOUT_MS - _TIMEOUT_TOLERANCE_MS,
            )
            and elapsed_ms < 5_000
        )
        if passed:
            return HostFaultResult(
                status="passed",
                observed_outcome="refused-before-start",
                detail_code=None,
                raw_evidence=canonical_json(payload).encode("utf-8"),
                facts=(
                    HostFaultFact("busy-timeout-ms", str(_BUSY_TIMEOUT_MS)),
                    HostFaultFact("execution-row-count", "0"),
                    HostFaultFact("provider-called", "false"),
                    HostFaultFact(
                        "sqlite-errorcode",
                        "unavailable" if sqlite_code is None else str(sqlite_code),
                    ),
                    HostFaultFact("writer-lock-held", "true"),
                ),
            )
        return HostFaultResult(
            status="failed",
            observed_outcome="failed",
            detail_code="effect-ledger-contention-invariant",
            raw_evidence=canonical_json(payload).encode("utf-8"),
            facts=(
                HostFaultFact("contention-observed", str(contention).lower()),
                HostFaultFact("execution-row-count", str(execution_count)),
                HostFaultFact("provider-called", str(provider_called).lower()),
                HostFaultFact("writer-lock-held", str(writer_lock_held).lower()),
            ),
        )


def effect_contention_binding() -> LinuxHostExecutorBinding:
    scenario = _canonical_scenario()
    return LinuxHostExecutorBinding(
        locator=scenario.executor,
        implementation_sha256=implementation_sha256(),
        execute=_execute_effect_contention,
    )


def run_effect_contention(*, source_revision: str) -> LinuxHostFaultRun:
    return run_linux_host_fault(
        _canonical_scenario(),
        source_revision=source_revision,
        executor=effect_contention_binding(),
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise EffectLedgerContentionFaultError(
            "refusing to replace an output symlink"
        )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
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


def publish_effect_contention(
    *, source_revision: str, output_dir: Path
) -> dict[str, Any]:
    if output_dir.is_symlink():
        raise EffectLedgerContentionFaultError(
            "output directory must not be a symlink"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    run = run_effect_contention(source_revision=source_revision)
    _atomic_write(
        output_dir / "evidence.json",
        (canonical_json(run.evidence.to_dict()) + "\n").encode("utf-8"),
    )
    _atomic_write(
        output_dir / "observation.json",
        (canonical_json(run.observation.to_dict()) + "\n").encode("utf-8"),
    )
    _atomic_write(output_dir / "raw", run.raw_evidence)
    summary = {
        "schema": _REPORT_SCHEMA,
        "source_revision": source_revision,
        "scenario_id": run.observation.scenario_id,
        "status": run.observation.status,
        "observed_outcome": run.observation.observed_outcome,
        "detail_code": run.observation.detail_code,
        "evidence_sha256": run.evidence.digest,
        "observation_sha256": run.observation.digest,
        "run_sha256": run.digest,
        "executor_implementation_sha256": implementation_sha256(),
        "trusted": False,
        "attested": False,
        "gate_closure_claimed": False,
    }
    _atomic_write(
        output_dir / "summary.json",
        (canonical_json(summary) + "\n").encode("utf-8"),
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = publish_effect_contention(
        source_revision=args.source_revision,
        output_dir=args.output_dir,
    )
    print(canonical_json(summary))
    if summary["status"] == "passed":
        return 0
    if summary["status"] == "blocked":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
