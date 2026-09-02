#!/usr/bin/env python3
"""Execute the canonical runtime-trust writer-contention host fault."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.util
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
import daedalus.runtimes.provider_observation as provider_observation_module
import daedalus.runtimes.trust_store as trust_store_module
from daedalus.kernel.contracts import EffectLeaseRequest
from daedalus.kernel.effects import EffectExecutionRequest, EffectLeaseLedger
from daedalus.kernel.runtime_effects import (
    RuntimeBoundEffectAuthorization,
    issue_runtime_bound_effect_lease,
)
from daedalus.runtimes.broker import (
    RuntimeProviderTrustFenceError,
)
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.provider_observation import (
    ProviderObservationBindingLedger,
    issue_provider_observation_authority,
)
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
_OBS_AUTHORITY_ID = "authority.trust-contention-observation"
_OBS_AUTHORITY_KEY_ID = "trust-contention-observation-authority-key"
_OBS_AUTHORITY_KEY = b"runtime-trust-contention-observation-authority-key-material"
_OBS_KEY_ID = "trust-contention-observation-issuer-key"
_OBS_KEY = b"runtime-trust-contention-observation-issuer-key-material"
_OBS_RECORD_KEY = b"runtime-trust-contention-observation-record-key-material"
_OBS_BINDING_ID = "trust-contention-observation-binding"
_OBS_PROVIDER_ID = "provider.trust-contention-runtime"
_POLICY_SHA256 = "b" * 64
_MANIFEST_SHA256 = "3" * 64
_PROBE_SHA256 = "4" * 64
_CONFORMANCE_SHA256 = "5" * 64
_ENVELOPE_SHA256 = "6" * 64
_MAX_RAW_EVIDENCE_BYTES = 64 * 1024


def _load_test_broker():
    """Load the callback fixture without making ``tests`` a Python package."""

    path = (
        Path(__file__).resolve().parents[1]
        / "runtimes"
        / "runtime_provider_test_double.py"
    )
    name = "daedalus_runtime_provider_test_double_fixture"
    module = sys.modules.get(name)
    if module is not None:
        return module.run_runtime_provider_test_double
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load runtime provider test double: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module.run_runtime_provider_test_double


run_runtime_provider = _load_test_broker()


class RuntimeTrustContentionFaultError(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _module_path(module, label: str) -> Path:
    source = getattr(module, "__file__", None)
    if not source:
        raise RuntimeTrustContentionFaultError(f"{label} has no source identity")
    path = Path(source).resolve()
    if not path.is_file():
        raise RuntimeTrustContentionFaultError(f"{label} source is unavailable")
    return path


def implementation_sha256() -> str:
    return canonical_sha(
        {
            "schema": _REPORT_SCHEMA,
            "executor_sha256": _file_sha256(Path(__file__).resolve()),
            "broker_sha256": _file_sha256(_module_path(broker_module, "broker")),
            "trust_store_sha256": _file_sha256(
                _module_path(trust_store_module, "trust store")
            ),
            "runtime_effects_sha256": _file_sha256(
                _module_path(runtime_effects_module, "runtime effects")
            ),
            "effect_ledger_sha256": _file_sha256(
                _module_path(effects_module, "effect ledger")
            ),
            "provider_observation_sha256": _file_sha256(
                _module_path(provider_observation_module, "provider observation")
            ),
            "busy_timeout_ms": _BUSY_TIMEOUT_MS,
            "timeout_tolerance_ms": _TIMEOUT_TOLERANCE_MS,
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
        raise RuntimeTrustContentionFaultError(
            "scenario binding mismatch: " + ", ".join(mismatches)
        )


class BoundedRuntimeTrustLedger(RuntimeTrustLedger):
    """Production trust operations with only the SQLite wait shortened."""

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


class _FenceArmingConnection:
    """Trust-store connection proxy that arms the competing writer in place.

    Every trust-store operation except the terminal fence opens its connection
    inside a ``with`` block; the fence alone keeps a bare connection and drives
    ``BEGIN IMMEDIATE`` on it directly.  Arming on that exact shape puts the
    competing writer into the fence's own window without a sleep or a race, and
    if the broker ever stopped opening the fence that way the tripwire would
    simply never fire and the scenario would report ``failed`` -- never a pass.
    """

    def __init__(self, connection: sqlite3.Connection, arm) -> None:
        self._connection = connection
        self._arm = arm
        self._entered = False

    def execute(self, statement: str, parameters=()):
        if not self._entered and statement.strip().upper().startswith("BEGIN"):
            self._arm()
        return self._connection.execute(statement, parameters)

    def __enter__(self) -> "_FenceArmingConnection":
        self._entered = True
        self._connection.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._connection.__exit__(exc_type, exc, tb)

    def __getattr__(self, name: str):
        return getattr(self._connection, name)


class TerminalFenceContentionTrustLedger(BoundedRuntimeTrustLedger):
    """Bounded trust ledger that injects one competing writer at the fence.

    Since G0-RTC-07A the broker accepts only an exact
    ``RuntimeBoundEffectAuthorization``, so the writer can no longer be armed
    from a wrapper around the authority.  It is armed on the persisted seam the
    fence itself uses instead, and only once the two post-invoke plain verifies
    have already completed -- the same instant the old wrapper chose, now
    measured on the production ledger rather than on a stand-in object.
    """

    def __init__(
        self,
        path: str | Path,
        *,
        integrity_key: bytes | str,
        busy_timeout_ms: int,
    ) -> None:
        self._invoked = False
        self._plain_verify_calls = 0
        self._writer: sqlite3.Connection | None = None
        self._armed = False
        super().__init__(
            path,
            integrity_key=integrity_key,
            busy_timeout_ms=busy_timeout_ms,
        )

    def _connect(self) -> sqlite3.Connection:
        return _FenceArmingConnection(super()._connect(), self._arm_writer)

    def require_active(self, **kwargs):
        record = super().require_active(**kwargs)
        if self._invoked:
            self._plain_verify_calls += 1
        return record

    def mark_invoked(self) -> None:
        self._invoked = True

    def _arm_writer(self) -> None:
        if self._armed or self._plain_verify_calls < 2:
            return
        self._armed = True
        writer = sqlite3.connect(str(self.path), isolation_level=None, timeout=1)
        try:
            writer.execute("PRAGMA journal_mode=WAL")
            writer.execute("PRAGMA busy_timeout=1000")
            writer.execute("BEGIN IMMEDIATE")
            if not writer.in_transaction:
                raise RuntimeTrustContentionFaultError(
                    "runtime-trust writer did not become active"
                )
        except BaseException:
            writer.close()
            raise
        self._writer = writer

    @property
    def plain_verify_calls(self) -> int:
        return self._plain_verify_calls

    @property
    def writer_active(self) -> bool:
        return self._writer is not None and self._writer.in_transaction

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


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _seed_record(
    ledger: BoundedRuntimeTrustLedger,
    *,
    source_revision: str,
    now: datetime,
):
    admitted = now - timedelta(minutes=1)
    record = trust_store_module._make_record(  # noqa: SLF001 - fixture setup
        integrity_key=ledger._integrity_key,  # noqa: SLF001 - fixture setup
        runtime_id=_RUNTIME_ID,
        envelope_sha256=_ENVELOPE_SHA256,
        probe_identity_sha256=_PROBE_SHA256,
        conformance_receipt_sha256=_CONFORMANCE_SHA256,
        runtime_manifest_sha256=_MANIFEST_SHA256,
        source_revision=source_revision,
        observed_at=_timestamp(now - timedelta(minutes=2)),
        admitted_at=_timestamp(admitted),
        expires_at=_timestamp(now + timedelta(minutes=30)),
        state="ACTIVE",
        state_changed_at=_timestamp(admitted),
        reason="",
    )
    # The ``with`` here is load-bearing and is deliberately NOT replaced by
    # ``contextlib.closing``. ``TerminalFenceContentionTrustLedger._connect``
    # returns a ``_FenceArmingConnection``, which arms the competing writer only
    # for a connection whose ``BEGIN`` arrives while ``_entered`` is False --
    # that flag is set by ``__enter__``, and it is exactly how the fault tells
    # the terminal fence's bare connection apart from every ordinary
    # trust-store operation. Dropping the ``with`` would route this seeding
    # ``BEGIN IMMEDIATE`` into the arming path and inject the writer at setup
    # time instead of inside the fence's window. Only the missing ``close()``
    # is added, wrapped around the unchanged transaction scope.
    connection = ledger._connect()  # noqa: SLF001 - fixture setup
    try:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            ledger._insert(connection, record)  # noqa: SLF001 - fixture setup
            connection.execute("COMMIT")
    finally:
        connection.close()
    return record


def _spec() -> EntrypointSpec:
    return EntrypointSpec(
        id=_ENTRYPOINT_ID,
        surface=Surface.CODEX,
        target="tests.fake_trust_contention:run",
        effects=(Effect.FILESYSTEM_WRITE, Effect.PROCESS_SPAWN, Effect.SPEND),
        guard_contracts=("budget.process_guard",),
        wiring=Wiring.CENTRAL,
        runtime_id=_RUNTIME_ID,
    )


def _authority(*, root: Path, source_revision: str, now: datetime):
    trust = TerminalFenceContentionTrustLedger(
        root / "runtime-trust.sqlite3",
        integrity_key=_TRUST_KEY,
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
    )
    trust_record = _seed_record(trust, source_revision=source_revision, now=now)
    spec = _spec()
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
        requested_effects=tuple(effect.value for effect in spec.effects),
        effect_scope=scope,
        idempotency_namespace="trust-contention-attempt",
        kill_switch_generation=7,
        runtime_manifest_sha256=_MANIFEST_SHA256,
        runtime_conformance_sha256=_CONFORMANCE_SHA256,
        provenance=ContractProvenance(
            origin="tests.runtime-trust-contention",
            source_revision=source_revision,
            created_at=_timestamp(now - timedelta(seconds=30)),
            input_digests=tuple(sorted((_MANIFEST_SHA256, _CONFORMANCE_SHA256))),
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
        runtime_trust_ledger=trust,
        runtime_authority_key_id="trust-contention-authority-key",
        runtime_authority_secret=_AUTHORITY_KEY,
        issued_at=now - timedelta(seconds=20),
        expires_at=now + timedelta(minutes=10),
        registry=registry,
    )
    effects = EffectLeaseLedger(root / "effect-leases.sqlite3")
    authorization = RuntimeBoundEffectAuthorization(
        capability=capability,
        request=request,
        policy_decision=policy,
        effect_ledger=effects,
        runtime_trust_ledger=trust,
        lease_keyring={"trust-contention-lease-key": _LEASE_KEY},
        runtime_authority_keyring={"trust-contention-authority-key": _AUTHORITY_KEY},
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
    # Since G0-RTC-07A the broker also refuses to run without the exact signed
    # provider-observation authority and its binding ledger.
    observation_ledger = ProviderObservationBindingLedger(
        root / "provider-observation.sqlite3",
        authority_id=_OBS_AUTHORITY_ID,
        authority_keyring={_OBS_AUTHORITY_KEY_ID: _OBS_AUTHORITY_KEY},
        observation_keyring={_OBS_KEY_ID: _OBS_KEY},
        record_secret=_OBS_RECORD_KEY,
    )
    observation_authority = issue_provider_observation_authority(
        authority_id=_OBS_AUTHORITY_ID,
        authority_key_id=_OBS_AUTHORITY_KEY_ID,
        authority_secret=_OBS_AUTHORITY_KEY,
        binding_id=_OBS_BINDING_ID,
        provider_id=_OBS_PROVIDER_ID,
        observation_keyring={_OBS_KEY_ID: _OBS_KEY},
        entrypoint_id=_ENTRYPOINT_ID,
        runtime_id=_RUNTIME_ID,
        execution=execution,
        lease_sha256=capability.lease.digest,
        source_revision=source_revision,
        issued_at=now - timedelta(seconds=20),
        expires_at=now + timedelta(minutes=10),
    )
    return (
        trust,
        trust_record,
        effects,
        authorization,
        execution,
        observation_authority,
        observation_ledger,
    )


def _sqlite_code(exc: sqlite3.OperationalError) -> int | None:
    value = getattr(exc, "sqlite_errorcode", None)
    return value if isinstance(value, int) else None


def _is_contention(exc: sqlite3.OperationalError) -> bool:
    code = _sqlite_code(exc)
    expected = {getattr(sqlite3, "SQLITE_BUSY", 5), getattr(sqlite3, "SQLITE_LOCKED", 6)}
    if code is not None and (code & 0xFF) in expected:
        return True
    text = str(exc).lower()
    return "busy" in text or "locked" in text


def _terminal(path: Path, execution_id: str) -> dict[str, Any] | None:
    with contextlib.closing(sqlite3.connect(str(path))) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute(
            "SELECT state, terminal_receipt_json FROM effect_executions "
            "WHERE execution_id=?",
            (execution_id,),
        ).fetchone()
    if row is None:
        return None
    receipt = None if row["terminal_receipt_json"] is None else json.loads(row["terminal_receipt_json"])
    return {"state": str(row["state"]), "receipt": receipt}


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

    with tempfile.TemporaryDirectory(prefix="daedalus-trust-contention-") as text:
        root = Path(text)
        now = datetime.now(timezone.utc)
        (
            trust,
            trust_record,
            effects,
            authorization,
            execution,
            observation_authority,
            observation_ledger,
        ) = _authority(
            root=root,
            source_revision=authority_revision or value.digest,
            now=now,
        )
        provider_output = secrets.token_hex(32)
        provider_called = False
        output_called = False
        released = False
        observed: RuntimeProviderTrustFenceError | None = None

        def invoke() -> str:
            nonlocal provider_called
            provider_called = True
            # From here on the trust ledger counts the broker's plain verifies
            # and arms the competing writer once the last one has passed.
            trust.mark_invoked()
            return provider_output

        def outputs(result: str) -> tuple[str, ...]:
            nonlocal output_called
            output_called = True
            if result != provider_output:
                raise RuntimeTrustContentionFaultError("provider output changed")
            return (hashlib.sha256(result.encode("utf-8")).hexdigest(),)

        started = time.monotonic()
        try:
            try:
                run_runtime_provider(
                    _ENTRYPOINT_ID,
                    authorization=authorization,
                    execution=execution,
                    invoke=invoke,
                    output_digests=outputs,
                    observation_authority=observation_authority,
                    observation_binding_ledger=observation_ledger,
                )
                released = True
            except RuntimeProviderTrustFenceError as exc:
                observed = exc
        finally:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            lock_held = trust.writer_active
            # Snapshot before the replay run, whose own grant/begin verifies
            # must not be counted as broker plain verifies.
            plain_verify_calls = trust.plain_verify_calls
            trust.release_writer()

        cause = observed.__cause__ if observed is not None else None
        contention = isinstance(cause, sqlite3.OperationalError) and _is_contention(cause)
        sqlite_errorcode = _sqlite_code(cause) if isinstance(cause, sqlite3.OperationalError) else None
        terminal = _terminal(effects.path, execution.execution_id)
        receipt = None if terminal is None else terminal["receipt"]
        state = None if terminal is None else terminal["state"]
        outcome = None if receipt is None else receipt.get("outcome")
        terminal_outputs = None if receipt is None else receipt.get("output_digests")
        detail = None if receipt is None else receipt.get("detail_sha256")

        rows = trust.records(_RUNTIME_ID)
        trust_unchanged = (
            len(rows) == 1
            and rows[0].state == "ACTIVE"
            and rows[0].record_sha256 == trust_record.record_sha256
        )

        replay_provider = False
        replay_outputs = False

        def replay_invoke() -> str:
            nonlocal replay_provider
            replay_provider = True
            return provider_output

        def replay_digest(result: str) -> tuple[str, ...]:
            nonlocal replay_outputs
            replay_outputs = True
            return (hashlib.sha256(result.encode("utf-8")).hexdigest(),)

        replay = run_runtime_provider(
            _ENTRYPOINT_ID,
            authorization=authorization,
            execution=execution,
            invoke=replay_invoke,
            output_digests=replay_digest,
            observation_authority=observation_authority,
            observation_binding_ledger=observation_ledger,
        )
        replay_inert = (
            replay.executed is False
            and replay.value is None
            and replay.terminal_receipt is None
            and not replay_provider
            and not replay_outputs
            and _terminal(effects.path, execution.execution_id) == terminal
        )
        payload = {
            "schema": _REPORT_SCHEMA,
            "scenario_id": value.scenario_id,
            "scenario_sha256": value.digest,
            "executor_implementation_sha256": implementation_sha256(),
            "broker_sha256": _file_sha256(_module_path(broker_module, "broker")),
            "trust_store_sha256": _file_sha256(_module_path(trust_store_module, "trust store")),
            "effect_ledger_sha256": _file_sha256(_module_path(effects_module, "effect ledger")),
            "provider_observation_sha256": _file_sha256(
                _module_path(provider_observation_module, "provider observation")
            ),
            "trust_database_path_sha256": hashlib.sha256(str(trust.path).encode()).hexdigest(),
            "effect_database_path_sha256": hashlib.sha256(str(effects.path).encode()).hexdigest(),
            "busy_timeout_ms": _BUSY_TIMEOUT_MS,
            "elapsed_ms": elapsed_ms,
            "plain_verify_calls": plain_verify_calls,
            "writer_lock_held": lock_held,
            "contention_observed": contention,
            "exception_type": type(observed).__qualname__ if observed else None,
            "cause_type": type(cause).__qualname__ if cause else None,
            "sqlite_errorcode": sqlite_errorcode,
            "provider_called": provider_called,
            "output_digest_called": output_called,
            "result_released": released,
            "terminal_state": state,
            "terminal_outcome": outcome,
            "terminal_output_count": None if terminal_outputs is None else len(terminal_outputs),
            "terminal_detail_present": detail is not None,
            "trust_record_still_active": trust_unchanged,
            "replay_inert": replay_inert,
        }
        raw = canonical_json(payload).encode("utf-8")
        passed = (
            plain_verify_calls == 2
            and lock_held
            and contention
            and isinstance(observed, RuntimeProviderTrustFenceError)
            and provider_called
            and output_called
            and not released
            and state == "CANCELLED"
            and outcome == "CANCELLED"
            and terminal_outputs == []
            and detail is not None
            and trust_unchanged
            and replay_inert
            and provider_output.encode("utf-8") not in raw
            and elapsed_ms >= max(1, _BUSY_TIMEOUT_MS - _TIMEOUT_TOLERANCE_MS)
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
                    HostFaultFact("output-digest-called", "true"),
                    HostFaultFact("provider-called", "true"),
                    HostFaultFact("replay-inert", "true"),
                    HostFaultFact("result-released", "false"),
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
                HostFaultFact("output-digest-called", str(output_called).lower()),
                HostFaultFact("provider-called", str(provider_called).lower()),
                HostFaultFact("replay-inert", str(replay_inert).lower()),
                HostFaultFact("result-released", str(released).lower()),
                HostFaultFact("terminal-state", "none" if state is None else state),
            ),
        )


def runtime_trust_contention_binding(
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


def run_runtime_trust_contention(*, source_revision: str) -> LinuxHostFaultRun:
    return run_linux_host_fault(
        _scenario(),
        source_revision=source_revision,
        executor=runtime_trust_contention_binding(authority_revision=source_revision),
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise RuntimeTrustContentionFaultError("refusing output symlink")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
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


def publish_runtime_trust_contention(
    *,
    source_revision: str,
    output_dir: Path,
) -> dict[str, Any]:
    if output_dir.is_symlink():
        raise RuntimeTrustContentionFaultError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    run = run_runtime_trust_contention(source_revision=source_revision)
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
