from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectStartResult,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.runtimes.broker import (
    RuntimeProviderTrustFenceError,
    run_runtime_provider,
)
from daedalus.spine.effect_boundary import Effect, EntrypointSpec, Surface, Wiring
from daedalus.spine.envelope import canonical_sha

ENTRYPOINT = "provider.fenced"
RUNTIME = "fenced_runtime"
ENVELOPE_SHA = "1" * 64
RECORD_SHA = "2" * 64
MANIFEST_SHA = "3" * 64
RECEIPT_SHA = "4" * 64
REVISION = "5" * 40
OUTPUT_SHA = "6" * 64


def _spec() -> EntrypointSpec:
    return EntrypointSpec(
        id=ENTRYPOINT,
        surface=Surface.PYTHON,
        target="tests.fake_fenced_provider:run",
        effects=(Effect.PROCESS_SPAWN, Effect.NETWORK_EGRESS),
        guard_contracts=("runtime.adapter_profile",),
        wiring=Wiring.CENTRAL,
        runtime_id=RUNTIME,
    )


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="fenced-execution-1",
        idempotency_key="fenced-idempotency-1",
        requested_effects=(
            Effect.NETWORK_EGRESS.value,
            Effect.PROCESS_SPAWN.value,
        ),
        egress_endpoints=("https://runtime.invalid",),
        tools=("fenced_runtime",),
        kill_switch_ref="mission-kill",
        kill_switch_generation=1,
    )


def _start_receipt() -> LeasedEffectStartReceipt:
    body = {
        "lease_sha256": "7" * 64,
        "execution_id": "fenced-execution-1",
        "idempotency_key": "fenced-idempotency-1",
        "execution_request_sha256": "8" * 64,
        "boundary_receipt_sha256": "9" * 64,
        "started_at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
    }
    return LeasedEffectStartReceipt(receipt_sha256=canonical_sha(body), **body)


class FenceLedger:
    """Minimal real SQLite authority with the same writer-lock contract."""

    def __init__(self, path: Path) -> None:
        self.path = path
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE runtime_trust_records (
                    runtime_id TEXT NOT NULL,
                    envelope_sha256 TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    record_sha256 TEXT NOT NULL,
                    runtime_manifest_sha256 TEXT NOT NULL,
                    conformance_receipt_sha256 TEXT NOT NULL,
                    source_revision TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "INSERT INTO runtime_trust_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    RUNTIME,
                    ENVELOPE_SHA,
                    "ACTIVE",
                    (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(
                        timespec="microseconds"
                    ),
                    RECORD_SHA,
                    MANIFEST_SHA,
                    RECEIPT_SHA,
                    REVISION,
                ),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.path),
            isolation_level=None,
            timeout=5,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @staticmethod
    def _from_row(row: sqlite3.Row):
        return SimpleNamespace(**dict(row))

    def quarantine(self) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE runtime_trust_records SET state='QUARANTINED' "
                "WHERE runtime_id=? AND envelope_sha256=?",
                (RUNTIME, ENVELOPE_SHA),
            )
            connection.execute("COMMIT")

    def replace_record_identity(self) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE runtime_trust_records SET record_sha256=? "
                "WHERE runtime_id=? AND envelope_sha256=?",
                ("a" * 64, RUNTIME, ENVELOPE_SHA),
            )
            connection.execute("COMMIT")

    def state(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM runtime_trust_records WHERE envelope_sha256=?",
                (ENVELOPE_SHA,),
            ).fetchone()
        assert row is not None
        return str(row["state"])


class FenceAuthorization:
    def __init__(self, ledger: FenceLedger) -> None:
        self.runtime_trust_ledger = ledger
        self.request = SimpleNamespace(entrypoint_id=ENTRYPOINT)
        self.capability = SimpleNamespace(
            lease=SimpleNamespace(entrypoint_id=ENTRYPOINT),
            runtime_id=RUNTIME,
            runtime_envelope_sha256=ENVELOPE_SHA,
            runtime_trust_record_sha256=RECORD_SHA,
            runtime_manifest_sha256=MANIFEST_SHA,
            runtime_conformance_sha256=RECEIPT_SHA,
            source_revision=REVISION,
        )
        spec = _spec()
        self.registry = {spec.id: spec}
        self.verify_calls = 0
        self.finish_calls: list[str] = []
        self.finish_entered: threading.Event | None = None
        self.finish_release: threading.Event | None = None
        self.mutate_after_verify: str | None = None

    def grant(self) -> None:
        return None

    def begin_effect(self, execution: EffectExecutionRequest) -> EffectStartResult:
        assert execution.execution_id == "fenced-execution-1"
        return EffectStartResult(receipt=_start_receipt(), execute=True)

    def verify(self, *, now: datetime) -> object:
        assert now.tzinfo is not None
        self.verify_calls += 1
        if self.verify_calls == 2:
            if self.mutate_after_verify == "quarantine":
                self.runtime_trust_ledger.quarantine()
            elif self.mutate_after_verify == "replace-record":
                self.runtime_trust_ledger.replace_record_identity()
        return object()

    def finish_effect(
        self,
        start_receipt: LeasedEffectStartReceipt,
        *,
        outcome: str,
        output_digests=(),
        detail_sha256: str | None = None,
    ) -> EffectTerminalReceipt:
        if outcome == "completed" and self.finish_entered is not None:
            self.finish_entered.set()
            assert self.finish_release is not None
            assert self.finish_release.wait(timeout=5)
        self.finish_calls.append(outcome)
        outputs = tuple(output_digests)
        finished_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
        body = {
            "lease_sha256": start_receipt.lease_sha256,
            "execution_id": start_receipt.execution_id,
            "start_receipt_sha256": start_receipt.receipt_sha256,
            "outcome": outcome.upper(),
            "output_digests": list(outputs),
            "detail_sha256": detail_sha256,
            "finished_at": finished_at,
        }
        return EffectTerminalReceipt(
            lease_sha256=start_receipt.lease_sha256,
            execution_id=start_receipt.execution_id,
            start_receipt_sha256=start_receipt.receipt_sha256,
            outcome=outcome.upper(),
            output_digests=outputs,
            detail_sha256=detail_sha256,
            finished_at=finished_at,
            receipt_sha256=canonical_sha(body),
        )


def test_quarantine_waits_until_completed_receipt_is_durable(tmp_path: Path) -> None:
    ledger = FenceLedger(tmp_path / "runtime-trust.sqlite3")
    authorization = FenceAuthorization(ledger)
    authorization.finish_entered = threading.Event()
    authorization.finish_release = threading.Event()
    result_box: dict[str, object] = {}
    error_box: list[BaseException] = []

    def invoke_broker() -> None:
        try:
            result_box["result"] = run_runtime_provider(
                ENTRYPOINT,
                authorization=authorization,  # type: ignore[arg-type]
                execution=_execution(),
                invoke=lambda: {"answer": 42},
                output_digests=lambda value: (OUTPUT_SHA,),
            )
        except BaseException as exc:
            error_box.append(exc)

    broker_thread = threading.Thread(target=invoke_broker)
    broker_thread.start()
    assert authorization.finish_entered.wait(timeout=5)

    quarantine_done = threading.Event()

    def quarantine() -> None:
        ledger.quarantine()
        quarantine_done.set()

    quarantine_thread = threading.Thread(target=quarantine)
    quarantine_thread.start()

    # The terminal fence owns BEGIN IMMEDIATE while the effect receipt is being
    # persisted, so a concurrent quarantine cannot commit in the middle.
    assert quarantine_done.wait(timeout=0.1) is False
    authorization.finish_release.set()
    broker_thread.join(timeout=5)
    quarantine_thread.join(timeout=5)

    assert not error_box
    result = result_box["result"]
    assert result.executed is True  # type: ignore[union-attr]
    assert result.terminal_receipt.outcome == "COMPLETED"  # type: ignore[union-attr]
    assert authorization.finish_calls == ["completed"]
    assert quarantine_done.is_set()
    assert ledger.state() == "QUARANTINED"


@pytest.mark.parametrize("mutation", ["quarantine", "replace-record"])
def test_trust_change_after_last_plain_verify_is_caught_by_terminal_fence(
    tmp_path: Path,
    mutation: str,
) -> None:
    ledger = FenceLedger(tmp_path / "runtime-trust.sqlite3")
    authorization = FenceAuthorization(ledger)
    authorization.mutate_after_verify = mutation

    with pytest.raises(RuntimeProviderTrustFenceError):
        run_runtime_provider(
            ENTRYPOINT,
            authorization=authorization,  # type: ignore[arg-type]
            execution=_execution(),
            invoke=lambda: {"must": "not be released"},
            output_digests=lambda value: (OUTPUT_SHA,),
        )

    # The provider already ran, but the broker withheld its value and converted
    # the durable execution to CANCELLED rather than publishing COMPLETED.
    assert authorization.verify_calls == 2
    assert authorization.finish_calls == ["cancelled"]
