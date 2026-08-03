#!/usr/bin/env python3
"""Execute the canonical runtime-trust-ledger contention host fault.

The fixture uses the production runtime provider broker and the production
HMAC-authenticated RuntimeTrustLedger. A test-only subclass changes only the
SQLite busy timeout so the real writer-lock failure is bounded. The locally
seeded authenticated row is test setup, not external runtime admission evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

import daedalus.runtimes.broker as broker_module
import daedalus.runtimes.trust_store as trust_store_module
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectStartResult,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.runtimes.broker import RuntimeProviderTrustFenceError, run_runtime_provider
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import (
    HostFaultFact,
    HostFaultResult,
    LinuxHostExecutorBinding,
    LinuxHostFaultRun,
    run_linux_host_fault,
)
from daedalus.runtimes.trust_store import RuntimeTrustLedger, RuntimeTrustRecord
from daedalus.spine.effect_boundary import Effect, EntrypointSpec, Surface, Wiring
from daedalus.spine.envelope import canonical_json, canonical_sha

_REPORT_SCHEMA = "daedalus-runtime-trust-contention-fault-report/1"
_SCENARIO_ID = "runtime.runtime-trust.lock-contention"
_BUSY_TIMEOUT_MS = 125
_MIN_ELAPSED_MS = 100
_MAX_ELAPSED_MS = 5000
_INTEGRITY_KEY = b"runtime-trust-contention-integrity-key-32-bytes"
_ENTRYPOINT_ID = "provider.runtime-trust-contention"
_RUNTIME_ID = "runtime_trust_contention"
_REVISION = "a" * 40
_ENVELOPE_SHA256 = "1" * 64
_PROBE_SHA256 = "2" * 64
_RECEIPT_SHA256 = "3" * 64
_MANIFEST_SHA256 = "4" * 64
_OUTPUT_SHA256 = "5" * 64


class RuntimeTrustContentionFaultError(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module_source_sha256(module, label: str) -> str:
    source = getattr(module, "__file__", None)
    if not source:
        raise RuntimeTrustContentionFaultError(f"{label} has no source-file identity")
    path = Path(source).resolve()
    if not path.is_file():
        raise RuntimeTrustContentionFaultError(f"{label} source file is unavailable")
    return _file_sha256(path)


def implementation_sha256() -> str:
    return canonical_sha(
        {
            "schema": _REPORT_SCHEMA,
            "executor_sha256": _file_sha256(Path(__file__).resolve()),
            "broker_sha256": _module_source_sha256(
                broker_module, "production runtime broker"
            ),
            "trust_store_sha256": _module_source_sha256(
                trust_store_module, "production runtime trust store"
            ),
            "busy_timeout_ms": _BUSY_TIMEOUT_MS,
            "min_elapsed_ms": _MIN_ELAPSED_MS,
            "max_elapsed_ms": _MAX_ELAPSED_MS,
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
        raise RuntimeTrustContentionFaultError(
            "runtime-trust contention scenario binding mismatch: "
            + ", ".join(mismatches)
        )


class BoundedRuntimeTrustLedger(RuntimeTrustLedger):
    """Production ledger logic with a test-only bounded SQLite wait."""

    def __init__(
        self,
        path: str | Path,
        *,
        integrity_key: bytes | str,
        busy_timeout_ms: int,
    ) -> None:
        self._fault_busy_timeout_ms = int(busy_timeout_ms)
        super().__init__(path, integrity_key=integrity_key)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            isolation_level=None,
            timeout=self._fault_busy_timeout_ms / 1000,
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute(
                f"PRAGMA busy_timeout={self._fault_busy_timeout_ms}"
            )
            return connection
        except BaseException:
            connection.close()
            raise


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _seed_record(
    ledger: BoundedRuntimeTrustLedger,
    *,
    now: datetime,
) -> RuntimeTrustRecord:
    observed = now - timedelta(minutes=2)
    admitted = now - timedelta(minutes=1)
    expires = now + timedelta(hours=1)
    record = trust_store_module._make_record(  # noqa: SLF001 - fixture seed only
        integrity_key=_INTEGRITY_KEY,
        runtime_id=_RUNTIME_ID,
        envelope_sha256=_ENVELOPE_SHA256,
        probe_identity_sha256=_PROBE_SHA256,
        conformance_receipt_sha256=_RECEIPT_SHA256,
        runtime_manifest_sha256=_MANIFEST_SHA256,
        source_revision=_REVISION,
        observed_at=_timestamp(observed),
        admitted_at=_timestamp(admitted),
        expires_at=_timestamp(expires),
        state="ACTIVE",
        state_changed_at=_timestamp(admitted),
        reason="",
    )
    with ledger._connect() as connection:  # noqa: SLF001 - fixture seed only
        connection.execute("BEGIN IMMEDIATE")
        ledger._insert(connection, record)  # noqa: SLF001 - fixture seed only
        connection.execute("COMMIT")
    return record


def _spec() -> EntrypointSpec:
    return EntrypointSpec(
        id=_ENTRYPOINT_ID,
        surface=Surface.PYTHON,
        target="tests.fake_runtime_trust_contention:run",
        effects=(Effect.PROCESS_SPAWN, Effect.NETWORK_EGRESS),
        guard_contracts=("runtime.adapter_profile",),
        wiring=Wiring.CENTRAL,
        runtime_id=_RUNTIME_ID,
    )


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="runtime-trust-contention-execution",
        idempotency_key="runtime-trust-contention-idempotency",
        requested_effects=(
            Effect.NETWORK_EGRESS.value,
            Effect.PROCESS_SPAWN.value,
        ),
        egress_endpoints=("https://runtime.invalid",),
        tools=(_RUNTIME_ID,),
        kill_switch_ref="mission-kill",
        kill_switch_generation=1,
    )


def _start_receipt() -> LeasedEffectStartReceipt:
    body = {
        "lease_sha256": "6" * 64,
        "execution_id": "runtime-trust-contention-execution",
        "idempotency_key": "runtime-trust-contention-idempotency",
        "execution_request_sha256": "7" * 64,
        "boundary_receipt_sha256": "8" * 64,
        "started_at": _timestamp(datetime.now(timezone.utc)),
    }
    return LeasedEffectStartReceipt(receipt_sha256=canonical_sha(body), **body)


@dataclass
class _TerminalObservation:
    outcome: str
    output_digests: tuple[str, ...]
    detail_sha256: str | None
    receipt_sha256: str


class RuntimeTrustContentionAuthorization:
    """Narrow effect seam around the real trust ledger and production broker."""

    def __init__(
        self,
        ledger: BoundedRuntimeTrustLedger,
        record: RuntimeTrustRecord,
    ) -> None:
        self.runtime_trust_ledger = ledger
        self.effect_ledger = SimpleNamespace(
            path=ledger.path.with_name("effect-leases.sqlite3")
        )
        self.request = SimpleNamespace(entrypoint_id=_ENTRYPOINT_ID)
        self.capability = SimpleNamespace(
            lease=SimpleNamespace(entrypoint_id=_ENTRYPOINT_ID),
            runtime_id=record.runtime_id,
            runtime_envelope_sha256=record.envelope_sha256,
            runtime_trust_record_sha256=record.record_sha256,
            runtime_manifest_sha256=record.runtime_manifest_sha256,
            runtime_conformance_sha256=record.conformance_receipt_sha256,
            source_revision=record.source_revision,
        )
        spec = _spec()
        self.registry = {spec.id: spec}
        self.verify_calls = 0
        self.provider_invoked = False
        self.output_evidence_built = False
        self.terminals: list[_TerminalObservation] = []
        self._writer: sqlite3.Connection | None = None

    def grant(self) -> None:
        return None

    def begin_effect(self, execution: EffectExecutionRequest) -> EffectStartResult:
        if execution.execution_id != "runtime-trust-contention-execution":
            raise RuntimeTrustContentionFaultError("unexpected execution identity")
        return EffectStartResult(receipt=_start_receipt(), execute=True)

    def verify(self, *, now: datetime) -> RuntimeTrustRecord:
        self.verify_calls += 1
        record = self.runtime_trust_ledger.require_active(
            runtime_id=self.capability.runtime_id,
            envelope_sha256=self.capability.runtime_envelope_sha256,
            record_sha256=self.capability.runtime_trust_record_sha256,
            runtime_manifest_sha256=self.capability.runtime_manifest_sha256,
            conformance_receipt_sha256=self.capability.runtime_conformance_sha256,
            source_revision=self.capability.source_revision,
            now=now,
        )
        if self.verify_calls == 2:
            writer = sqlite3.connect(
                str(self.runtime_trust_ledger.path),
                isolation_level=None,
                timeout=5,
            )
            writer.execute("PRAGMA busy_timeout=5000")
            writer.execute("BEGIN IMMEDIATE")
            if not writer.in_transaction:
                writer.close()
                raise RuntimeTrustContentionFaultError(
                    "external runtime-trust writer did not become active"
                )
            self._writer = writer
        return record

    def release_writer(self) -> None:
        writer = self._writer
        self._writer = None
        if writer is None:
            return
        try:
            if writer.in_transaction:
                writer.execute("ROLLBACK")
        finally:
            writer.close()

    @property
    def writer_active(self) -> bool:
        return self._writer is not None and self._writer.in_transaction

    def finish_effect(
        self,
        start_receipt: LeasedEffectStartReceipt,
        *,
        outcome: str,
        output_digests=(),
        detail_sha256: str | None = None,
    ) -> EffectTerminalReceipt:
        outputs = tuple(output_digests)
        finished_at = _timestamp(datetime.now(timezone.utc))
        body = {
            "lease_sha256": start_receipt.lease_sha256,
            "execution_id": start_receipt.execution_id,
            "start_receipt_sha256": start_receipt.receipt_sha256,
            "outcome": outcome.upper(),
            "output_digests": list(outputs),
            "detail_sha256": detail_sha256,
            "finished_at": finished_at,
        }
        receipt = EffectTerminalReceipt(
            lease_sha256=start_receipt.lease_sha256,
            execution_id=start_receipt.execution_id,
            start_receipt_sha256=start_receipt.receipt_sha256,
            outcome=outcome.upper(),
            output_digests=outputs,
            detail_sha256=detail_sha256,
            finished_at=finished_at,
            receipt_sha256=canonical_sha(body),
        )
        self.terminals.append(
            _TerminalObservation(
                outcome=outcome.lower(),
                output_digests=outputs,
                detail_sha256=detail_sha256,
                receipt_sha256=receipt.receipt_sha256,
            )
        )
        return receipt


def _sqlite_base_code(exc: BaseException | None) -> int | None:
    if not isinstance(exc, sqlite3.Error):
        return None
    code = getattr(exc, "sqlite_errorcode", None)
    if not isinstance(code, int):
        return None
    return code & 0xFF


def _execute_runtime_trust_contention(scenario) -> HostFaultResult:
    _assert_scenario(scenario)
    if sys.platform != "linux":
        return HostFaultResult(
            status="blocked",
            observed_outcome=None,
            detail_code="linux-required",
            raw_evidence=canonical_json(
                {
                    "schema": _REPORT_SCHEMA,
                    "scenario_id": scenario.scenario_id,
                    "scenario_sha256": scenario.digest,
                    "executor_implementation_sha256": implementation_sha256(),
                    "status": "blocked",
                    "detail_code": "linux-required",
                    "platform": sys.platform,
                }
            ).encode("utf-8"),
            facts=(HostFaultFact("prerequisite", "linux-required"),),
        )

    with tempfile.TemporaryDirectory(prefix="daedalus-runtime-trust-lock-") as temporary:
        database = Path(temporary) / "runtime-trust.sqlite3"
        ledger = BoundedRuntimeTrustLedger(
            database,
            integrity_key=_INTEGRITY_KEY,
            busy_timeout_ms=_BUSY_TIMEOUT_MS,
        )
        now = datetime.now(timezone.utc)
        record = _seed_record(ledger, now=now)
        authorization = RuntimeTrustContentionAuthorization(ledger, record)
        raised: BaseException | None = None
        elapsed_ms = 0
        returned_value = False

        def invoke() -> dict[str, str]:
            authorization.provider_invoked = True
            return {"provider": "output-must-be-withheld"}

        def output_digests(value: dict[str, str]) -> tuple[str, ...]:
            if value.get("provider") != "output-must-be-withheld":
                raise RuntimeTrustContentionFaultError("provider output changed")
            authorization.output_evidence_built = True
            return (_OUTPUT_SHA256,)

        started = time.monotonic()
        try:
            run_runtime_provider(
                _ENTRYPOINT_ID,
                authorization=authorization,  # type: ignore[arg-type]
                execution=_execution(),
                invoke=invoke,
                output_digests=output_digests,
            )
            returned_value = True
        except BaseException as exc:
            raised = exc
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            writer_active_before_release = authorization.writer_active
            authorization.release_writer()

        durable = ledger.require_active(
            runtime_id=record.runtime_id,
            envelope_sha256=record.envelope_sha256,
            record_sha256=record.record_sha256,
            runtime_manifest_sha256=record.runtime_manifest_sha256,
            conformance_receipt_sha256=record.conformance_receipt_sha256,
            source_revision=record.source_revision,
            now=datetime.now(timezone.utc),
        )
        cause = raised.__cause__ if raised is not None else None
        sqlite_code = getattr(cause, "sqlite_errorcode", None)
        sqlite_name = getattr(cause, "sqlite_errorname", None)
        sqlite_base_code = _sqlite_base_code(cause)
        terminal_rows = [
            {
                "outcome": row.outcome,
                "output_digest_count": len(row.output_digests),
                "detail_present": row.detail_sha256 is not None,
                "receipt_sha256": row.receipt_sha256,
            }
            for row in authorization.terminals
        ]
        payload = {
            "schema": _REPORT_SCHEMA,
            "scenario_id": scenario.scenario_id,
            "scenario_sha256": scenario.digest,
            "executor_implementation_sha256": implementation_sha256(),
            "broker_sha256": _module_source_sha256(
                broker_module, "production runtime broker"
            ),
            "trust_store_sha256": _module_source_sha256(
                trust_store_module, "production runtime trust store"
            ),
            "database_path_sha256": hashlib.sha256(
                str(database).encode("utf-8")
            ).hexdigest(),
            "busy_timeout_ms": _BUSY_TIMEOUT_MS,
            "elapsed_ms": elapsed_ms,
            "writer_active_before_release": writer_active_before_release,
            "provider_invoked": authorization.provider_invoked,
            "output_evidence_built": authorization.output_evidence_built,
            "provider_value_returned": returned_value,
            "exception_module": None if raised is None else type(raised).__module__,
            "exception_type": None if raised is None else type(raised).__qualname__,
            "cause_module": None if cause is None else type(cause).__module__,
            "cause_type": None if cause is None else type(cause).__qualname__,
            "sqlite_errorcode": sqlite_code,
            "sqlite_errorname": sqlite_name,
            "sqlite_base_code": sqlite_base_code,
            "verify_calls": authorization.verify_calls,
            "terminal_rows": terminal_rows,
            "durable_record_sha256": durable.record_sha256,
            "durable_state": durable.state,
            "status": "observed",
            "trusted": False,
            "attested": False,
            "gate_closure_claimed": False,
        }
        exact_contention = (
            writer_active_before_release
            and authorization.provider_invoked
            and authorization.output_evidence_built
            and returned_value is False
            and isinstance(raised, RuntimeProviderTrustFenceError)
            and isinstance(cause, sqlite3.OperationalError)
            and sqlite_base_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
            and _MIN_ELAPSED_MS <= elapsed_ms < _MAX_ELAPSED_MS
            and authorization.verify_calls == 2
            and len(authorization.terminals) == 1
            and authorization.terminals[0].outcome == "cancelled"
            and authorization.terminals[0].output_digests == ()
            and authorization.terminals[0].detail_sha256 is not None
            and durable.record_sha256 == record.record_sha256
            and durable.state == "ACTIVE"
        )
        if exact_contention:
            return HostFaultResult(
                status="passed",
                observed_outcome="cancelled",
                detail_code=None,
                raw_evidence=canonical_json(payload).encode("utf-8"),
                facts=(
                    HostFaultFact("provider-invoked", "true"),
                    HostFaultFact("provider-output-returned", "false"),
                    HostFaultFact("runtime-trust-state", "ACTIVE"),
                    HostFaultFact("sqlite-base-code", str(sqlite_base_code)),
                    HostFaultFact("terminal-outcome", "cancelled"),
                    HostFaultFact("writer-active", "true"),
                ),
            )
        return HostFaultResult(
            status="failed",
            observed_outcome="cancelled" if authorization.terminals else None,
            detail_code="runtime-trust-contention-invariant",
            raw_evidence=canonical_json(payload).encode("utf-8"),
            facts=(
                HostFaultFact("provider-invoked", str(authorization.provider_invoked).lower()),
                HostFaultFact("provider-output-returned", str(returned_value).lower()),
                HostFaultFact("terminal-count", str(len(authorization.terminals))),
                HostFaultFact("writer-active", str(writer_active_before_release).lower()),
            ),
        )


def runtime_trust_contention_binding() -> LinuxHostExecutorBinding:
    scenario = _canonical_scenario()
    return LinuxHostExecutorBinding(
        locator=scenario.executor,
        implementation_sha256=implementation_sha256(),
        execute=_execute_runtime_trust_contention,
    )


def run_runtime_trust_contention(*, source_revision: str) -> LinuxHostFaultRun:
    return run_linux_host_fault(
        _canonical_scenario(),
        source_revision=source_revision,
        executor=runtime_trust_contention_binding(),
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeTrustContentionFaultError("refusing to replace an output symlink")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        if os.name != "nt":
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory = os.open(path.parent, directory_flags)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def publish_runtime_trust_contention(
    *,
    source_revision: str,
    output_dir: Path,
) -> dict[str, Any]:
    if output_dir.is_symlink():
        raise RuntimeTrustContentionFaultError(
            "output directory must not be a symlink"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    run = run_runtime_trust_contention(source_revision=source_revision)
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
    summary = publish_runtime_trust_contention(
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
