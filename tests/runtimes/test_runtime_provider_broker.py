from __future__ import annotations

from types import SimpleNamespace

import pytest

from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectStartResult,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.runtimes.broker import (
    RuntimeProviderBindingMismatch,
    RuntimeProviderReconciliationRequired,
    RuntimeProviderStateError,
    run_runtime_provider,
)
from daedalus.spine.effect_boundary import Effect, EntrypointSpec, Surface, Wiring
from daedalus.spine.envelope import canonical_sha


ENTRYPOINT = "provider.fake"
RUNTIME = "fake_runtime"
OUTPUT_SHA = "a" * 64


def _spec(*, wiring: Wiring = Wiring.CENTRAL, runtime_id: str = RUNTIME) -> EntrypointSpec:
    return EntrypointSpec(
        id=ENTRYPOINT,
        surface=Surface.PYTHON,
        target="tests.fake_provider:run",
        effects=(Effect.PROCESS_SPAWN, Effect.NETWORK_EGRESS),
        guard_contracts=("runtime.adapter_profile",),
        wiring=wiring,
        runtime_id=runtime_id,
    )


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="runtime-execution-1",
        idempotency_key="runtime-idempotency-1",
        requested_effects=(
            Effect.NETWORK_EGRESS.value,
            Effect.PROCESS_SPAWN.value,
        ),
        egress_endpoints=("https://runtime.invalid",),
        tools=("fake_runtime",),
        kill_switch_ref="mission-kill",
        kill_switch_generation=3,
    )


def _start_receipt() -> LeasedEffectStartReceipt:
    body = {
        "lease_sha256": "1" * 64,
        "execution_id": "runtime-execution-1",
        "idempotency_key": "runtime-idempotency-1",
        "execution_request_sha256": "2" * 64,
        "boundary_receipt_sha256": "3" * 64,
        "started_at": "2026-08-03T01:00:00+00:00",
    }
    return LeasedEffectStartReceipt(receipt_sha256=canonical_sha(body), **body)


class FakeAuthorization:
    def __init__(
        self,
        *,
        entrypoint_id: str = ENTRYPOINT,
        lease_entrypoint_id: str | None = None,
        runtime_id: str = RUNTIME,
        spec: EntrypointSpec | None = None,
        replay: bool = False,
    ) -> None:
        self.request = SimpleNamespace(entrypoint_id=entrypoint_id)
        self.capability = SimpleNamespace(
            lease=SimpleNamespace(
                entrypoint_id=lease_entrypoint_id or entrypoint_id,
            ),
            runtime_id=runtime_id,
        )
        row = spec or _spec(runtime_id=runtime_id)
        self.registry = {row.id: row}
        self.replay = replay
        self.grant_calls = 0
        self.begin_calls = 0
        self.verify_calls = 0
        self.finish_calls: list[dict[str, object]] = []
        self.verify_error: BaseException | None = None
        self.verify_error_at: int | None = None
        self.finish_error: BaseException | None = None

    def grant(self) -> None:
        self.grant_calls += 1

    def begin_effect(self, execution: EffectExecutionRequest) -> EffectStartResult:
        self.begin_calls += 1
        assert execution.execution_id == "runtime-execution-1"
        return EffectStartResult(
            receipt=_start_receipt(),
            execute=not self.replay,
        )

    def verify(self) -> object:
        self.verify_calls += 1
        if (
            self.verify_error is not None
            and (
                self.verify_error_at is None
                or self.verify_calls == self.verify_error_at
            )
        ):
            raise self.verify_error
        return object()

    def finish_effect(
        self,
        start_receipt: LeasedEffectStartReceipt,
        *,
        outcome: str,
        output_digests=(),
        detail_sha256: str | None = None,
    ) -> EffectTerminalReceipt:
        if self.finish_error is not None:
            raise self.finish_error
        outputs = tuple(output_digests)
        row = {
            "outcome": outcome,
            "output_digests": outputs,
            "detail_sha256": detail_sha256,
        }
        self.finish_calls.append(row)
        finished_at = "2026-08-03T01:00:01+00:00"
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


def _evidence(value) -> tuple[str, ...]:
    return (OUTPUT_SHA,)


def test_completed_provider_call_is_granted_started_rechecked_and_finished() -> None:
    auth = FakeAuthorization()
    calls: list[str] = []

    result = run_runtime_provider(
        ENTRYPOINT,
        authorization=auth,  # type: ignore[arg-type]
        execution=_execution(),
        invoke=lambda: calls.append("invoked") or {"answer": 42},
        output_digests=lambda value: ("b" * 64, OUTPUT_SHA),
    )

    assert calls == ["invoked"]
    assert auth.grant_calls == 1
    assert auth.begin_calls == 1
    assert auth.verify_calls == 2
    assert auth.finish_calls == [
        {
            "outcome": "completed",
            "output_digests": (OUTPUT_SHA, "b" * 64),
            "detail_sha256": None,
        }
    ]
    assert result.executed is True
    assert result.runtime_id == RUNTIME
    assert result.value == {"answer": 42}
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "COMPLETED"


def test_exact_replay_is_inert_and_has_no_second_terminal() -> None:
    auth = FakeAuthorization(replay=True)
    calls: list[str] = []
    evidence_calls: list[str] = []

    result = run_runtime_provider(
        ENTRYPOINT,
        authorization=auth,  # type: ignore[arg-type]
        execution=_execution(),
        invoke=lambda: calls.append("invoked"),
        output_digests=lambda value: evidence_calls.append("evidence") or (OUTPUT_SHA,),
    )

    assert result.executed is False
    assert result.value is None
    assert result.terminal_receipt is None
    assert calls == []
    assert evidence_calls == []
    assert auth.grant_calls == 1
    assert auth.begin_calls == 1
    assert auth.verify_calls == 0
    assert auth.finish_calls == []


@pytest.mark.parametrize(
    "auth",
    [
        FakeAuthorization(entrypoint_id="provider.other"),
        FakeAuthorization(lease_entrypoint_id="provider.other"),
        FakeAuthorization(spec=_spec(wiring=Wiring.INVENTORY_ONLY)),
        FakeAuthorization(runtime_id="other_runtime", spec=_spec()),
    ],
)
def test_foreign_noncentral_or_runtime_mismatched_authority_refuses_before_effect(
    auth: FakeAuthorization,
) -> None:
    called = False

    def invoke() -> None:
        nonlocal called
        called = True

    with pytest.raises(RuntimeProviderBindingMismatch):
        run_runtime_provider(
            ENTRYPOINT,
            authorization=auth,  # type: ignore[arg-type]
            execution=_execution(),
            invoke=invoke,
            output_digests=_evidence,
        )

    assert called is False
    assert auth.grant_calls == 0
    assert auth.begin_calls == 0


def test_provider_exception_is_failed_before_it_escapes() -> None:
    auth = FakeAuthorization()

    def invoke() -> None:
        raise RuntimeError("secret provider message must not enter evidence")

    with pytest.raises(RuntimeError, match="secret provider"):
        run_runtime_provider(
            ENTRYPOINT,
            authorization=auth,  # type: ignore[arg-type]
            execution=_execution(),
            invoke=invoke,
            output_digests=_evidence,
        )

    assert auth.finish_calls[0]["outcome"] == "failed"
    detail = auth.finish_calls[0]["detail_sha256"]
    assert isinstance(detail, str) and len(detail) == 64


def test_keyboard_interrupt_is_cancelled_before_it_escapes() -> None:
    auth = FakeAuthorization()

    def invoke() -> None:
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        run_runtime_provider(
            ENTRYPOINT,
            authorization=auth,  # type: ignore[arg-type]
            execution=_execution(),
            invoke=invoke,
            output_digests=_evidence,
        )

    assert auth.finish_calls[0]["outcome"] == "cancelled"


def test_runtime_trust_loss_after_provider_call_withholds_output_and_cancels() -> None:
    auth = FakeAuthorization()
    auth.verify_error = RuntimeError("runtime quarantined")
    auth.verify_error_at = 1
    evidence_calls: list[str] = []

    with pytest.raises(RuntimeError, match="quarantined"):
        run_runtime_provider(
            ENTRYPOINT,
            authorization=auth,  # type: ignore[arg-type]
            execution=_execution(),
            invoke=lambda: {"untrusted": "output"},
            output_digests=lambda value: evidence_calls.append("evidence") or (OUTPUT_SHA,),
        )

    assert auth.verify_calls == 1
    assert evidence_calls == []
    assert auth.finish_calls[0]["outcome"] == "cancelled"


def test_runtime_trust_loss_after_evidence_extraction_blocks_completion() -> None:
    auth = FakeAuthorization()
    auth.verify_error = RuntimeError("runtime rotated")
    auth.verify_error_at = 2
    evidence_calls: list[str] = []

    with pytest.raises(RuntimeError, match="rotated"):
        run_runtime_provider(
            ENTRYPOINT,
            authorization=auth,  # type: ignore[arg-type]
            execution=_execution(),
            invoke=lambda: "output",
            output_digests=lambda value: evidence_calls.append(value) or (OUTPUT_SHA,),
        )

    assert auth.verify_calls == 2
    assert evidence_calls == ["output"]
    assert auth.finish_calls[0]["outcome"] == "cancelled"


@pytest.mark.parametrize(
    "output_digests,cause_type",
    [
        (lambda value: (), ValueError),
        (lambda value: ("not-a-digest",), ValueError),
        (lambda value: (_ for _ in ()).throw(RuntimeError("local digest crash")), RuntimeError),
    ],
)
def test_post_provider_output_evidence_failure_requires_reconciliation(
    output_digests,
    cause_type: type[BaseException],
) -> None:
    auth = FakeAuthorization()
    with pytest.raises(RuntimeProviderReconciliationRequired) as captured:
        run_runtime_provider(
            ENTRYPOINT,
            authorization=auth,  # type: ignore[arg-type]
            execution=_execution(),
            invoke=lambda: "external-output",
            output_digests=output_digests,
        )

    error = captured.value
    assert error.entrypoint_id == ENTRYPOINT
    assert error.runtime_id == RUNTIME
    assert error.start_receipt == _start_receipt()
    assert error.phase == "output-evidence"
    assert len(error.cause_sha256) == 64
    assert isinstance(error.__cause__, cause_type)
    assert auth.verify_calls == 1
    assert auth.finish_calls == []
    assert not hasattr(error, "value")


def test_terminal_persistence_failure_is_a_broker_state_error() -> None:
    auth = FakeAuthorization()
    auth.finish_error = OSError("disk full")

    with pytest.raises(RuntimeProviderStateError, match="terminal receipt"):
        run_runtime_provider(
            ENTRYPOINT,
            authorization=auth,  # type: ignore[arg-type]
            execution=_execution(),
            invoke=lambda: "output",
            output_digests=_evidence,
        )
