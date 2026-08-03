#!/usr/bin/env python3
"""Execute the canonical runtime-trust writer-contention host fault.

The fixture seeds one authenticated active RuntimeTrustRecord with the production
ledger format, issues a real runtime-bound Effect Lease, and runs the production
runtime provider broker. The provider acquires a competing trust-ledger writer
transaction immediately before returning. The broker must withhold the returned
value and persist the effect execution as CANCELLED when its post-invoke trust
verification reaches the bounded SQLite busy timeout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import daedalus.kernel.effects as effects_module
import daedalus.kernel.runtime_effects as runtime_effects_module
import daedalus.runtimes.broker as broker_module
import daedalus.runtimes.trust_store as trust_store_module
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import EffectExecutionRequest, EffectLeaseLedger
from daedalus.kernel.runtime_effects import (
    RuntimeBoundEffectAuthorization,
    issue_runtime_bound_effect_lease,
)
from daedalus.runtimes.broker import run_runtime_provider
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.host_fault_runner import (
    HostFaultFact,
    HostFaultResult,
    LinuxHostExecutorBinding,
    LinuxHostFaultRun,
    run_linux_host_fault,
)
from daedalus.runtimes.trust_store import RuntimeTrustLedger
from daedalus.schemas import ContractProvenance, EffectScope, PolicyDecision
from daedalus.spine.effect_boundary import (
    Effect,
    EntrypointSpec,
    GuardDecision,
    Surface,
    Wiring,
)
from daedalus.spine.envelope import canonical_json, canonical_sha

_REPORT_SCHEMA = "daedalus-runtime-trust-contention-fault/1"
_SCENARIO_ID = "runtime.trust-ledger.lock-contention"
_BUSY_TIMEOUT_MS = 125
_TIMEOUT_TOLERANCE_MS = 25
_RUNTIME_ID = "trust_contention_runtime"
_ENTRYPOINT_ID = "provider.trust-contention"
_TRUST_KEY = b"runtime-trust-contention-integrity-key-material-32-bytes"
_LEASE_KEY = b"runtime-trust-contention-effect-lease-key-material-32-bytes"
_AUTHORITY_KEY = b"runtime-trust-contention-authority-key-material-32-bytes"
_POLICY_SHA256 = "b" * 64
_MANIFEST_SHA256 = "3" * 64
_PROBE_SHA256 = "4" * 64
_CONFORMANCE_SHA256 = "5" * 64
_ENVELOPE_SHA256 = "6" * 64
_MAX_RAW_EVIDENCE_BYTES = 64 * 1024


class RuntimeTrustContentionFaultError(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module_source_path(module, label: str) -> Path:
    source = getattr(module, "__file__", None)
    if not source:
        raise RuntimeTrustContentionFaultError(f"{label} has no source-file identity")
    path = Path(source).resolve()
    if not path.is_file():
        raise RuntimeTrustContentionFaultError(f"{label} source file is unavailable")
    return path


def implementation_sha256() -> str:
    return canonical_sha(
        {
            "schema": _REPORT_SCHEMA,
            "executor_sha256": _file_sha256(Path(__file__).resolve()),
            "broker_sha256": _file_sha256(
                _module_source_path(broker_module, "production runtime broker")
            ),
            "trust_store_sha256": _file_sha256(
                _module_source_path(trust_store_module, "production runtime trust ledger")
            ),
            "runtime_effects_sha256": _file_sha256(
                _module_source_path(runtime_effects_module, "runtime effect authority")
            ),
            "effect_ledger_sha256": _file_sha256(
                _module_source_path(effects_module, "production effect ledger")
            ),
            "busy_timeout_ms": _BUSY_TIMEOUT_MS,
            "timeout_tolerance_ms": _TIMEOUT_TOLERANCE_MS,
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
    """Production trust operations with a fixture-controlled busy timeout."""

    def __init__(
        self,
        path: str | Path,
        *,
        integrity_key: bytes | str,
        busy_timeout_ms: int,
    ) -> None:
        if (
            isinstance(busy_timeout_ms, bool)
            or not isinstance(busy_timeout_ms, int)
            or not 1 <= busy_timeout_ms <= 10_000
        ):
            raise ValueError("busy_timeout_ms must be an integer in [1, 10000]")
        self.busy_timeout_ms = busy_timeout_ms
        super().__init__(path, integrity_key=integrity_key)

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


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _seed_active_record(
    ledger: BoundedRuntimeTrustLedger,
    *,
    source_revision: str,
    now: datetime,
):
    observed = now - timedelta(minutes=2)
    admitted = now - timedelta(minutes=1)
    expires = now + timedelta(minutes=30)
    record = trust_store_module._make_record(  # noqa: SLF001 - fault setup
        integrity_key=ledger._integrity_key,  # noqa: SLF001 - authenticated setup
        runtime_id=_RUNTIME_ID,
        envelope_sha256=_ENVELOPE_SHA256,
        probe_identity_sha256=_PROBE_SHA256,
        conformance_receipt_sha256=_CONFORMANCE_SHA256,
        runtime_manifest_sha256=_MANIFEST_SHA256,
        source_revision=source_revision,
        observed_at=_timestamp(observed),
        admitted_at=_timestamp(admitted),
        expires_at=_timestamp(expires),
        state="ACTIVE",
        state_changed_at=_timestamp(admitted),
        reason="",
    )
    with ledger._connect() as connection:  # noqa: SLF001 - fault setup
        connection.execute("BEGIN IMMEDIATE")
        ledger._insert(connection, record)  # noqa: SLF001 - authenticated setup
        connection.execute("COMMIT")
    return record


def _central_spec() -> EntrypointSpec:
    return EntrypointSpec(
        id=_ENTRYPOINT_ID,
        surface=Surface.CODEX,
        target="tests.fake_trust_contention:run",
        effects=(
            Effect.FILESYSTEM_WRITE,
            Effect.PROCESS_SPAWN,
            Effect.SPEND,
        ),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        runtime_id=_RUNTIME_ID,
    )


def _authority(
    *,
    root: Path,
    source_revision: str,
    now: datetime,
):
    trust_ledger = BoundedRuntimeTrustLedger(
        root / "runtime-trust.sqlite3",
        integrity_key=_TRUST_KEY,
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
    )
    trust_record = _seed_active_record(
        trust_ledger,
        source_revision=source_revision,
        now=now,
    )
    spec = _central_spec()
    registry = {spec.id: spec}
    scope = EffectScope(
        read_only=False,
        writable_paths=("workspace",),
        tools=("codex",),
        max_cost_microusd=100,
        max_concurrency=1,
        timeout_s=60,
        kill_switch_ref="mission-kill",
    )
    request = EffectLeaseRequest(
        request_id="trust-contention-request",
        mission_id="trust-contention-mission",
        attempt_id="trust-contention-attempt",
        entrypoint_id=spec.id,
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_SPAWN.value,
            Effect.SPEND.value,
        ),
        effect_scope=scope,
        idempotency_namespace="trust-contention-attempt",
        kill_switch_generation=7,
        runtime_manifest_sha256=_MANIFEST_SHA256,
        runtime_conformance_sha256=_CONFORMANCE_SHA256,
        provenance=ContractProvenance(
            origin="tests.runtime-trust-contention",
            source_revision=source_revision,
            created_at=_timestamp(now - timedelta(seconds=30)),
            input_digests=tuple(
                sorted((_MANIFEST_SHA256, _CONFORMANCE_SHA256))
            ),
            trace_id="trust-contention-mission",
        ),
    )
    policy = PolicyDecision(
        decision_id="trust-contention-policy",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-03",
        policy_sha256=_POLICY_SHA256,
        verdict="allow",
        reasons=("bounded trusted runtime",),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="tests.runtime-trust-contention-policy",
            source_revision=source_revision,
            created_at=_timestamp(now - timedelta(seconds=30)),
            input_digests=(request.digest, _POLICY_SHA256),
            trace_id="trust-contention-mission",
        ),
    )
    capability = issue_runtime_bound_effect_lease(
        request,
        policy,
        lease_id="trust-contention-lease",
        lease_issuer_key_id="trust-contention-lease-key",
        lease_issuer_secret=_LEASE_KEY,
        runtime_envelope_sha256=_ENVELOPE_SHA256,
        runtime_trust_ledger=trust_ledger,
        runtime_authority_key_id="trust-contention-authority-key",
        runtime_authority_secret=_AUTHORITY_KEY,
        issued_at=now - timedelta(seconds=20),
        expires_at=now + timedelta(minutes=10),
        registry=registry,
    )
    effect_ledger = EffectLeaseLedger(root / "effect-leases.sqlite3")
    authorization = RuntimeBoundEffectAuthorization(
        capability=capability,
        request=request,
        policy_decision=policy,
        effect_ledger=effect_ledger,
        runtime_trust_ledger=trust_ledger,
        lease_keyring={"trust-contention-lease-key": _LEASE_KEY},
        runtime_authority_keyring={
            "trust-contention-authority-key": _AUTHORITY_KEY
        },
        guard_decisions=(
            GuardDecision(
                "budget.process_guard",
                True,
                "artifact-locator:sha256:" + "e" * 64,
            ),
        ),
        current_kill_switch_generation=7,
        registry=registry,
    )
    execution = EffectExecutionRequest(
        execution_id="trust-contention-execution",
        idempotency_key="trust-contention-idempotency",
        requested_effects=request.requested_effects,
        writable_paths=("workspace/out.txt",),
        tools=("codex",),
        max_cost_microusd=100,
        kill_switch_ref="mission-kill",
        kill_switch_generation=7,
    )
    return trust_ledger, trust_record, effect_ledger, authorization, execution


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
    text = str(exc).lower()
    return "locked" in text or "busy" in text


def _terminal_row(path: Path, execution_id: str) -> dict[str, Any] | None:
    with sqlite3.connect(str(path)) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT state, terminal_receipt_json FROM effect_executions "
            "WHERE execution_id=?",
            (execution_id,),
        ).fetchone()
    if row is None:
        return None
    receipt = (
        None
        if row["terminal_receipt_json"] is None
        else json.loads(str(row["terminal_receipt_json"]))
    )
    return {"state": str(row["state"]), "receipt": receipt}


def _execute_runtime_trust_contention(scenario) -> HostFaultResult:
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

    with tempfile.TemporaryDirectory(prefix="daedalus-trust-contention-") as root_text:
        root = Path(root_text)
        now = datetime.now(timezone.utc)
        (
            trust_ledger,
            trust_record,
            effect_ledger,
            authorization,
            execution,
        ) = _authority(root=root, source_revision=scenario.digest, now=now)

        blocker = sqlite3.connect(
            str(trust_ledger.path),
            isolation_level=None,
            timeout=1,
        )
        blocker.execute("PRAGMA journal_mode=WAL")
        blocker.execute("PRAGMA busy_timeout=1000")
        provider_called = False
        output_digest_called = False
        writer_lock_held = False
        result_released = False
        observed_error: sqlite3.OperationalError | None = None
        provider_output = secrets.token_hex(32)

        def invoke() -> str:
            nonlocal provider_called, writer_lock_held
            provider_called = True
            blocker.execute("BEGIN IMMEDIATE")
            writer_lock_held = blocker.in_transaction
            return provider_output

        def output_digests(value: str) -> tuple[str, ...]:
            nonlocal output_digest_called
            output_digest_called = True
            if value != provider_output:
                raise RuntimeTrustContentionFaultError(
                    "provider output changed before evidence extraction"
                )
            return (hashlib.sha256(value.encode("utf-8")).hexdigest(),)

        started = time.monotonic()
        try:
            try:
                run_runtime_provider(
                    _ENTRYPOINT_ID,
                    authorization=authorization,
                    execution=execution,
                    invoke=invoke,
                    output_digests=output_digests,
                )
                result_released = True
            except sqlite3.OperationalError as exc:
                observed_error = exc
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if blocker.in_transaction:
                blocker.execute("ROLLBACK")
            blocker.close()

        terminal = _terminal_row(effect_ledger.path, execution.execution_id)
        trust_rows = trust_ledger.records(_RUNTIME_ID)
        trust_record_still_active = (
            len(trust_rows) == 1
            and trust_rows[0].state == "ACTIVE"
            and trust_rows[0].record_sha256 == trust_record.record_sha256
        )
        contention = observed_error is not None and _is_lock_contention(observed_error)
        sqlite_code = (
            _sqlite_error_code(observed_error)
            if observed_error is not None
            else None
        )
        terminal_receipt = None if terminal is None else terminal["receipt"]
        terminal_state = None if terminal is None else terminal["state"]
        terminal_outcome = (
            None if terminal_receipt is None else terminal_receipt.get("outcome")
        )
        terminal_outputs = (
            None if terminal_receipt is None else terminal_receipt.get("output_digests")
        )
        terminal_detail = (
            None if terminal_receipt is None else terminal_receipt.get("detail_sha256")
        )
        payload: dict[str, Any] = {
            "schema": _REPORT_SCHEMA,
            "scenario_id": scenario.scenario_id,
            "scenario_sha256": scenario.digest,
            "executor_implementation_sha256": implementation_sha256(),
            "broker_sha256": _file_sha256(
                _module_source_path(broker_module, "production runtime broker")
            ),
            "trust_store_sha256": _file_sha256(
                _module_source_path(
                    trust_store_module,
                    "production runtime trust ledger",
                )
            ),
            "effect_ledger_sha256": _file_sha256(
                _module_source_path(effects_module, "production effect ledger")
            ),
            "trust_database_path_sha256": hashlib.sha256(
                str(trust_ledger.path).encode("utf-8")
            ).hexdigest(),
            "effect_database_path_sha256": hashlib.sha256(
                str(effect_ledger.path).encode("utf-8")
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
            "output_digest_called": output_digest_called,
            "result_released": result_released,
            "terminal_state": terminal_state,
            "terminal_outcome": terminal_outcome,
            "terminal_output_count": (
                None if terminal_outputs is None else len(terminal_outputs)
            ),
            "terminal_detail_present": terminal_detail is not None,
            "trust_record_still_active": trust_record_still_active,
        }
        raw = canonical_json(payload).encode("utf-8")
        passed = (
            writer_lock_held
            and contention
            and provider_called
            and not output_digest_called
            and not result_released
            and terminal_state == "CANCELLED"
            and terminal_outcome == "CANCELLED"
            and terminal_outputs == []
            and terminal_detail is not None
            and trust_record_still_active
            and provider_output.encode("utf-8") not in raw
            and elapsed_ms >= max(
                1,
                _BUSY_TIMEOUT_MS - _TIMEOUT_TOLERANCE_MS,
            )
            and elapsed_ms < 5_000
            and len(raw) <= _MAX_RAW_EVIDENCE_BYTES
        )
        if passed:
            return HostFaultResult(
                status="passed",
                observed_outcome="cancelled",
                detail_code=None,
                raw_evidence=raw,
                facts=(
                    HostFaultFact("busy-timeout-ms", str(_BUSY_TIMEOUT_MS)),
                    HostFaultFact("output-digest-called", "false"),
                    HostFaultFact("provider-called", "true"),
                    HostFaultFact("result-released", "false"),
                    HostFaultFact(
                        "sqlite-errorcode",
                        "unavailable" if sqlite_code is None else str(sqlite_code),
                    ),
                    HostFaultFact("terminal-state", "CANCELLED"),
                    HostFaultFact("trust-record-active", "true"),
                    HostFaultFact("writer-lock-held", "true"),
                ),
            )
        return HostFaultResult(
            status="failed",
            observed_outcome="failed",
            detail_code="runtime-trust-contention-invariant",
            raw_evidence=raw,
            facts=(
                HostFaultFact("contention-observed", str(contention).lower()),
                HostFaultFact("output-digest-called", str(output_digest_called).lower()),
                HostFaultFact("provider-called", str(provider_called).lower()),
                HostFaultFact("result-released", str(result_released).lower()),
                HostFaultFact(
                    "terminal-state",
                    "none" if terminal_state is None else terminal_state,
                ),
                HostFaultFact("writer-lock-held", str(writer_lock_held).lower()),
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
        raise RuntimeTrustContentionFaultError(
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
        if os.name != "nt":
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory = os.open(path.parent, directory_flags)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


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
