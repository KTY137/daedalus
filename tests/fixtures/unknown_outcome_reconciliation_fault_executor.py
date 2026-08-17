#!/usr/bin/env python3
"""Crash after durable external acknowledgement, then reconcile without re-effect."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

import daedalus.kernel.effect_recovery as recovery_module
import daedalus.kernel.effects as effects_module
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effect_recovery import (
    issue_external_effect_observation,
    reconcile_unknown_effect,
)
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectLeaseLedger,
    LeasedEffectAuthorization,
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

_REPORT_SCHEMA = "daedalus-unknown-outcome-reconciliation-fault/1"
_SCENARIO_ID = "runtime.effect.unknown-outcome-replay"
_PROVIDER_ID = "provider.idempotent-external"
_ENTRYPOINT_ID = "provider.unknown-outcome"
_LEASE_KEY = b"unknown-outcome-effect-lease-key-material-32-bytes"
_OBSERVATION_KEY = b"unknown-outcome-observation-key-material-32-bytes"
_POLICY_SHA256 = "b" * 64
_CRASH_RETURN_CODE = 91
_MAX_RAW_EVIDENCE_BYTES = 64 * 1024


class UnknownOutcomeFaultError(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module_path(module, label: str) -> Path:
    source = getattr(module, "__file__", None)
    if not source:
        raise UnknownOutcomeFaultError(f"{label} has no source identity")
    path = Path(source).resolve()
    if not path.is_file():
        raise UnknownOutcomeFaultError(f"{label} source is unavailable")
    return path


def implementation_sha256() -> str:
    return canonical_sha(
        {
            "schema": _REPORT_SCHEMA,
            "executor_sha256": _file_sha256(Path(__file__).resolve()),
            "recovery_sha256": _file_sha256(
                _module_path(recovery_module, "effect recovery")
            ),
            "effects_sha256": _file_sha256(
                _module_path(effects_module, "effect ledger")
            ),
            "crash_return_code": _CRASH_RETURN_CODE,
        }
    )


def _scenario():
    return RUNTIME_FAULT_CATALOG.scenario_map[_SCENARIO_ID]


def _assert_scenario(value) -> None:
    expected = _scenario()
    fields = {
        "scenario_id": (value.scenario_id, expected.scenario_id),
        "scenario_sha256": (value.digest, expected.digest),
        "authority": (value.authority, expected.authority),
        "executor": (value.executor, expected.executor),
        "expected_outcome": (value.expected_outcome, expected.expected_outcome),
    }
    mismatches = sorted(name for name, pair in fields.items() if pair[0] != pair[1])
    if mismatches:
        raise UnknownOutcomeFaultError(
            "unknown-outcome scenario binding mismatch: " + ", ".join(mismatches)
        )


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _authority(*, root: Path, source_revision: str, now: datetime):
    spec = EntrypointSpec(
        id=_ENTRYPOINT_ID,
        surface=Surface.PYTHON,
        target="tests.fake_unknown_outcome:apply",
        effects=(Effect.PROCESS_SPAWN, Effect.SPEND),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
    )
    registry = {spec.id: spec}
    scope = EffectScope(
        # The entrypoint declares PROCESS_SPAWN + SPEND only: no FILESYSTEM_WRITE
        # and no REPOSITORY_MUTATION. A write-capable scope here would grant
        # authority the execution can never exercise, so the scope stays
        # read-only and names no writable roots.
        read_only=True,
        tools=("python",),
        max_cost_microusd=100,
        max_concurrency=1,
        timeout_s=30,
        kill_switch_ref="mission-kill",
    )
    request = EffectLeaseRequest(
        request_id="unknown-outcome-request",
        mission_id="unknown-outcome-mission",
        attempt_id="unknown-outcome-attempt",
        entrypoint_id=spec.id,
        requested_effects=tuple(effect.value for effect in spec.effects),
        effect_scope=scope,
        idempotency_namespace="unknown-outcome-attempt",
        kill_switch_generation=7,
        # The spec declares no runtime_id, so issue_effect_lease refuses any
        # attached runtime conformance; both digests must stay absent together.
        runtime_manifest_sha256=None,
        runtime_conformance_sha256=None,
        provenance=ContractProvenance(
            origin="tests.unknown-outcome",
            source_revision=source_revision,
            created_at=_timestamp(now - timedelta(seconds=30)),
            trace_id="unknown-outcome-mission",
        ),
    )
    policy = PolicyDecision(
        decision_id="unknown-outcome-policy",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-03",
        policy_sha256=_POLICY_SHA256,
        verdict="allow",
        reasons=("bounded idempotent external effect",),
        effect_scope=scope,
        provenance=ContractProvenance(
            origin="tests.unknown-outcome-policy",
            source_revision=source_revision,
            created_at=_timestamp(now - timedelta(seconds=30)),
            input_digests=(request.digest, _POLICY_SHA256),
            trace_id="unknown-outcome-mission",
        ),
    )
    lease = issue_effect_lease(
        request,
        policy,
        lease_id="unknown-outcome-lease",
        issuer_key_id="unknown-outcome-lease-key",
        issued_at=now - timedelta(seconds=20),
        expires_at=now + timedelta(minutes=10),
        secret=_LEASE_KEY,
        registry=registry,
    )
    ledger = EffectLeaseLedger(root / "effects.sqlite3")
    ledger.grant(
        lease,
        request=request,
        policy_decision=policy,
        keyring={"unknown-outcome-lease-key": _LEASE_KEY},
        current_kill_switch_generation=7,
        granted_at=now - timedelta(seconds=10),
        registry=registry,
    )
    authorization = LeasedEffectAuthorization(
        lease=lease,
        request=request,
        policy_decision=policy,
        ledger=ledger,
        keyring={"unknown-outcome-lease-key": _LEASE_KEY},
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
        execution_id="unknown-outcome-execution",
        idempotency_key="unknown-outcome-idempotency",
        requested_effects=request.requested_effects,
        tools=("python",),
        max_cost_microusd=100,
        kill_switch_ref="mission-kill",
        kill_switch_generation=7,
    )
    return ledger, authorization, execution


def _external_connect(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(str(path), isolation_level=None, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=5000")
    return connection


def _initialize_external(path: Path) -> None:
    with _external_connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS external_effects (
                idempotency_key TEXT PRIMARY KEY,
                acknowledgement_sha256 TEXT NOT NULL,
                output_sha256 TEXT NOT NULL
            )
            """
        )


def _crash_worker(
    *,
    external_db: Path,
    idempotency_key: str,
    acknowledgement_sha256: str,
    output_sha256: str,
) -> int:
    connection = _external_connect(external_db)
    try:
        connection.execute("BEGIN IMMEDIATE")
        existing = connection.execute(
            "SELECT acknowledgement_sha256, output_sha256 "
            "FROM external_effects WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            raise UnknownOutcomeFaultError("external idempotency key already exists")
        connection.execute(
            "INSERT INTO external_effects "
            "(idempotency_key, acknowledgement_sha256, output_sha256) "
            "VALUES (?, ?, ?)",
            (idempotency_key, acknowledgement_sha256, output_sha256),
        )
        connection.execute("COMMIT")
    finally:
        connection.close()
    os._exit(_CRASH_RETURN_CODE)


def _external_row(path: Path, idempotency_key: str) -> sqlite3.Row | None:
    with _external_connect(path) as connection:
        return connection.execute(
            "SELECT idempotency_key, acknowledgement_sha256, output_sha256 "
            "FROM external_effects WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()


def _external_count(path: Path) -> int:
    with _external_connect(path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM external_effects").fetchone()[0])


def _execute(value, *, authority_revision: str | None = None) -> HostFaultResult:
    _assert_scenario(value)
    if sys.platform != "linux":
        raw = canonical_json(
            {
                "schema": _REPORT_SCHEMA,
                "scenario_id": value.scenario_id,
                "status": "blocked",
                "detail_code": "linux-required",
                "platform": sys.platform,
            }
        ).encode("utf-8")
        return HostFaultResult(
            status="blocked",
            observed_outcome=None,
            detail_code="linux-required",
            raw_evidence=raw,
            facts=(HostFaultFact("platform", sys.platform),),
        )

    with tempfile.TemporaryDirectory(prefix="daedalus-unknown-outcome-") as text:
        root = Path(text)
        now = datetime.now(timezone.utc)
        revision = authority_revision or value.digest
        ledger, authorization, execution = _authority(
            root=root,
            source_revision=revision,
            now=now,
        )
        start = authorization.begin_effect(execution)
        if not start.execute:
            raise UnknownOutcomeFaultError("first execution unexpectedly replayed")

        external_db = root / "external.sqlite3"
        _initialize_external(external_db)
        output_value = secrets.token_hex(32)
        output_sha256 = hashlib.sha256(output_value.encode("utf-8")).hexdigest()
        acknowledgement_sha256 = canonical_sha(
            {
                "provider_id": _PROVIDER_ID,
                "idempotency_key": execution.idempotency_key,
                "output_sha256": output_sha256,
            }
        )
        worker = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--crash-worker",
                "--external-db",
                str(external_db),
                "--idempotency-key",
                execution.idempotency_key,
                "--acknowledgement-sha256",
                acknowledgement_sha256,
                "--output-sha256",
                output_sha256,
            ],
            check=False,
            capture_output=True,
            timeout=10,
        )
        state_after_crash = ledger.execution_state(execution.execution_id)
        row = _external_row(external_db, execution.idempotency_key)
        external_count_after_crash = _external_count(external_db)
        if row is None:
            raw = canonical_json(
                {
                    "schema": _REPORT_SCHEMA,
                    "scenario_id": value.scenario_id,
                    "worker_returncode": worker.returncode,
                    "state_after_crash": state_after_crash,
                    "external_row_count": external_count_after_crash,
                }
            ).encode("utf-8")
            return HostFaultResult(
                status="failed",
                observed_outcome="failed",
                detail_code="external-acknowledgement-missing",
                raw_evidence=raw,
                facts=(HostFaultFact("external-row-count", str(external_count_after_crash)),),
            )

        observation = issue_external_effect_observation(
            observation_id="unknown-outcome-observation",
            provider_id=_PROVIDER_ID,
            execution=execution,
            start_receipt=start.receipt,
            acknowledgement_sha256=str(row["acknowledgement_sha256"]),
            output_digests=(str(row["output_sha256"]),),
            issuer_key_id="unknown-outcome-observation-key",
            issuer_secret=_OBSERVATION_KEY,
            source_revision=revision,
            observed_at=now + timedelta(seconds=1),
        )
        first = reconcile_unknown_effect(
            ledger,
            execution=execution,
            start_receipt=start.receipt,
            observation=observation,
            keyring={"unknown-outcome-observation-key": _OBSERVATION_KEY},
            expected_provider_id=_PROVIDER_ID,
            expected_source_revision=revision,
            reconciled_at=now + timedelta(seconds=2),
        )
        second = reconcile_unknown_effect(
            ledger,
            execution=execution,
            start_receipt=start.receipt,
            observation=observation,
            keyring={"unknown-outcome-observation-key": _OBSERVATION_KEY},
            expected_provider_id=_PROVIDER_ID,
            expected_source_revision=revision,
            reconciled_at=now + timedelta(seconds=3),
        )
        replay = authorization.begin_effect(execution)
        external_count_after_recovery = _external_count(external_db)
        final_state = ledger.execution_state(execution.execution_id)

        payload: dict[str, Any] = {
            "schema": _REPORT_SCHEMA,
            "scenario_id": value.scenario_id,
            "scenario_sha256": value.digest,
            "executor_implementation_sha256": implementation_sha256(),
            "recovery_source_sha256": _file_sha256(
                _module_path(recovery_module, "effect recovery")
            ),
            "effects_source_sha256": _file_sha256(
                _module_path(effects_module, "effect ledger")
            ),
            "effect_database_path_sha256": hashlib.sha256(
                str(ledger.path).encode("utf-8")
            ).hexdigest(),
            "external_database_path_sha256": hashlib.sha256(
                str(external_db).encode("utf-8")
            ).hexdigest(),
            "worker_returncode": worker.returncode,
            "worker_stdout_sha256": hashlib.sha256(worker.stdout).hexdigest(),
            "worker_stderr_sha256": hashlib.sha256(worker.stderr).hexdigest(),
            "state_after_crash": state_after_crash,
            "external_row_count_after_crash": external_count_after_crash,
            "external_row_count_after_recovery": external_count_after_recovery,
            "acknowledgement_sha256": acknowledgement_sha256,
            "observation_sha256": observation.digest,
            "first_reconciled": first.reconciled,
            "second_reconciled": second.reconciled,
            "terminal_receipt_sha256": first.terminal_receipt.receipt_sha256,
            "terminal_outcome": first.terminal_receipt.outcome,
            "terminal_output_count": len(first.terminal_receipt.output_digests),
            "final_state": final_state,
            "exact_replay_execute": replay.execute,
            "exact_replay_start_receipt_sha256": replay.receipt.receipt_sha256,
        }
        raw = canonical_json(payload).encode("utf-8")
        passed = (
            worker.returncode == _CRASH_RETURN_CODE
            and worker.stdout == b""
            and worker.stderr == b""
            and state_after_crash == "STARTED"
            and external_count_after_crash == 1
            and str(row["acknowledgement_sha256"]) == acknowledgement_sha256
            and str(row["output_sha256"]) == output_sha256
            and first.reconciled is True
            and second.reconciled is False
            and first.terminal_receipt == second.terminal_receipt
            and first.terminal_receipt.outcome == "COMPLETED"
            and first.terminal_receipt.output_digests == (output_sha256,)
            and first.terminal_receipt.detail_sha256 == observation.digest
            and final_state == "COMPLETED"
            and replay.execute is False
            and replay.receipt == start.receipt
            and external_count_after_recovery == 1
            and output_value.encode("utf-8") not in raw
            and len(raw) <= _MAX_RAW_EVIDENCE_BYTES
        )
        if passed:
            return HostFaultResult(
                status="passed",
                observed_outcome="unknown-reconciled",
                detail_code=None,
                raw_evidence=raw,
                facts=(
                    HostFaultFact("external-row-count", "1"),
                    HostFaultFact("first-reconciled", "true"),
                    HostFaultFact("replay-execute", "false"),
                    HostFaultFact("second-reconciled", "false"),
                    HostFaultFact("state-after-crash", "STARTED"),
                    HostFaultFact("terminal-state", "COMPLETED"),
                    HostFaultFact("worker-returncode", str(_CRASH_RETURN_CODE)),
                ),
            )
        return HostFaultResult(
            status="failed",
            observed_outcome="failed",
            detail_code="unknown-outcome-reconciliation-invariant",
            raw_evidence=raw,
            facts=(
                HostFaultFact("external-row-count", str(external_count_after_recovery)),
                HostFaultFact("final-state", "none" if final_state is None else final_state),
                HostFaultFact("replay-execute", str(replay.execute).lower()),
                HostFaultFact("state-after-crash", "none" if state_after_crash is None else state_after_crash),
                HostFaultFact("worker-returncode", str(worker.returncode)),
            ),
        )


def unknown_outcome_binding(
    *,
    authority_revision: str | None = None,
) -> LinuxHostExecutorBinding:
    scenario = _scenario()

    def execute(bound_scenario):
        return _execute(bound_scenario, authority_revision=authority_revision)

    return LinuxHostExecutorBinding(
        locator=scenario.executor,
        implementation_sha256=implementation_sha256(),
        execute=execute,
    )


def run_unknown_outcome(*, source_revision: str) -> LinuxHostFaultRun:
    return run_linux_host_fault(
        _scenario(),
        source_revision=source_revision,
        executor=unknown_outcome_binding(authority_revision=source_revision),
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise UnknownOutcomeFaultError("refusing output symlink")
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def publish_unknown_outcome(*, source_revision: str, output_dir: Path) -> dict[str, Any]:
    if output_dir.is_symlink():
        raise UnknownOutcomeFaultError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    run = run_unknown_outcome(source_revision=source_revision)
    _atomic_write(output_dir / "evidence.json", (canonical_json(run.evidence.to_dict()) + "\n").encode())
    _atomic_write(output_dir / "observation.json", (canonical_json(run.observation.to_dict()) + "\n").encode())
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
    _atomic_write(output_dir / "summary.json", (canonical_json(summary) + "\n").encode())
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--crash-worker", action="store_true")
    parser.add_argument("--external-db", type=Path)
    parser.add_argument("--idempotency-key")
    parser.add_argument("--acknowledgement-sha256")
    parser.add_argument("--output-sha256")
    parser.add_argument("--source-revision")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.crash_worker:
        required = (
            args.external_db,
            args.idempotency_key,
            args.acknowledgement_sha256,
            args.output_sha256,
        )
        if any(value is None for value in required):
            parser.error("crash worker arguments are incomplete")
        return _crash_worker(
            external_db=args.external_db,
            idempotency_key=args.idempotency_key,
            acknowledgement_sha256=args.acknowledgement_sha256,
            output_sha256=args.output_sha256,
        )
    if args.source_revision is None or args.output_dir is None:
        parser.error("--source-revision and --output-dir are required")
    summary = publish_unknown_outcome(
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
