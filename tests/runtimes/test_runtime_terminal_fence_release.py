from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectStartResult,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.runtimes.broker import run_runtime_provider
from daedalus.spine.effect_boundary import Effect, EntrypointSpec, Surface, Wiring
from daedalus.spine.envelope import canonical_sha

ENTRYPOINT = "provider.release-fence"
RUNTIME = "release_fence_runtime"
OUTPUT_SHA = "a" * 64


class _NoCommitConnection:
    """Connection proxy that kills an unnecessary terminal-fence COMMIT."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def execute(self, statement: str, parameters=()):
        if statement.strip().upper() == "COMMIT":
            raise sqlite3.OperationalError("read-only fence COMMIT refused")
        return self._connection.execute(statement, parameters)

    @property
    def in_transaction(self) -> bool:
        return self._connection.in_transaction

    def close(self) -> None:
        self._connection.close()


class _NoCommitTrustLedger:
    def __init__(self, path: Path) -> None:
        self.path = path
        raw = sqlite3.connect(str(path), isolation_level=None)
        try:
            raw.execute("PRAGMA journal_mode=WAL")
            raw.execute(
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
            raw.execute(
                "INSERT INTO runtime_trust_records VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    RUNTIME,
                    "1" * 64,
                    "ACTIVE",
                    (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                    "2" * 64,
                    "3" * 64,
                    "4" * 64,
                    "5" * 40,
                ),
            )
        finally:
            raw.close()

    def _connect(self) -> _NoCommitConnection:
        raw = sqlite3.connect(str(self.path), isolation_level=None, timeout=5)
        raw.row_factory = sqlite3.Row
        raw.execute("PRAGMA journal_mode=WAL")
        raw.execute("PRAGMA busy_timeout=5000")
        return _NoCommitConnection(raw)

    @staticmethod
    def _from_row(row: sqlite3.Row):
        return SimpleNamespace(**dict(row))


def _start_receipt() -> LeasedEffectStartReceipt:
    body = {
        "lease_sha256": "6" * 64,
        "execution_id": "release-execution",
        "idempotency_key": "release-idempotency",
        "execution_request_sha256": "7" * 64,
        "boundary_receipt_sha256": "8" * 64,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    return LeasedEffectStartReceipt(receipt_sha256=canonical_sha(body), **body)


class _Authorization:
    def __init__(self, root: Path) -> None:
        self.runtime_trust_ledger = _NoCommitTrustLedger(root / "trust.sqlite3")
        self.effect_ledger = SimpleNamespace(path=root / "effects.sqlite3")
        self.request = SimpleNamespace(entrypoint_id=ENTRYPOINT)
        self.capability = SimpleNamespace(
            lease=SimpleNamespace(entrypoint_id=ENTRYPOINT),
            runtime_id=RUNTIME,
            runtime_envelope_sha256="1" * 64,
            runtime_trust_record_sha256="2" * 64,
            runtime_manifest_sha256="3" * 64,
            runtime_conformance_sha256="4" * 64,
            source_revision="5" * 40,
        )
        spec = EntrypointSpec(
            id=ENTRYPOINT,
            surface=Surface.PYTHON,
            target="tests.fake_release_provider:run",
            effects=(Effect.PROCESS_SPAWN,),
            guard_contracts=("runtime.adapter_profile",),
            wiring=Wiring.CENTRAL,
            runtime_id=RUNTIME,
        )
        self.registry = {spec.id: spec}
        self.finished: list[str] = []

    def grant(self) -> None:
        return None

    def begin_effect(self, execution: EffectExecutionRequest) -> EffectStartResult:
        return EffectStartResult(receipt=_start_receipt(), execute=True)

    def verify(self, *, now: datetime) -> object:
        assert now.tzinfo is not None
        return object()

    def finish_effect(
        self,
        start_receipt: LeasedEffectStartReceipt,
        *,
        outcome: str,
        output_digests=(),
        detail_sha256: str | None = None,
    ) -> EffectTerminalReceipt:
        self.finished.append(outcome)
        outputs = tuple(output_digests)
        finished_at = datetime.now(timezone.utc).isoformat()
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


def test_read_only_trust_fence_does_not_commit_after_effect_completion(
    tmp_path: Path,
) -> None:
    authorization = _Authorization(tmp_path)
    execution = EffectExecutionRequest(
        execution_id="release-execution",
        idempotency_key="release-idempotency",
        requested_effects=(Effect.PROCESS_SPAWN.value,),
        tools=("release_fence_runtime",),
        kill_switch_ref="mission-kill",
        kill_switch_generation=1,
    )

    result = run_runtime_provider(
        ENTRYPOINT,
        authorization=authorization,  # type: ignore[arg-type]
        execution=execution,
        invoke=lambda: {"answer": 42},
        output_digests=lambda value: (OUTPUT_SHA,),
    )

    assert result.executed is True
    assert result.value == {"answer": 42}
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "COMPLETED"
    assert authorization.finished == ["completed"]
