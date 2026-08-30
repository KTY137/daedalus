from __future__ import annotations

import dataclasses
import importlib.util
import json
import sqlite3
import sys
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.runtimes.broker import (
    RuntimeProviderBindingMismatch,
    RuntimeProviderReconciliationRequired,
    RuntimeProviderStateError,
    _run_runtime_provider_test_double as run_runtime_provider,
)
from daedalus.runtimes.fixture_fault_collector import report_runtime_fault_outcome
from daedalus.runtimes.provider_observation import (
    ProviderObservationBindingLedger,
    issue_provider_observation_authority,
)
from daedalus.spine.effect_boundary import Wiring


ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_FIXTURE = ROOT / "tests/kernel/test_runtime_effect_replay_projection.py"
AUTHORITY_KEY_ID = "broker-exact-authority-key"
AUTHORITY_KEY = b"broker-exact-authority-key-material-at-least-32-bytes"
OBSERVATION_KEY_ID = "broker-exact-observation-key"
OBSERVATION_KEY = b"broker-exact-observation-key-material-at-least-32-bytes"
RECORD_KEY = b"broker-exact-record-key-material-at-least-32-bytes"
OUTPUT_SHA = "a" * 64


def _load_authority_fixture():
    name = "daedalus_test_runtime_provider_broker_exact_fixture"
    spec = importlib.util.spec_from_file_location(name, AUTHORITY_FIXTURE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _load_authority_fixture()


def _set_clocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "daedalus.kernel.runtime_effects._utc_now",
        lambda: fixture.NOW,
    )
    monkeypatch.setattr(
        "daedalus.kernel.effects._utc_now",
        lambda: fixture.NOW + timedelta(seconds=3),
    )
    monkeypatch.setattr(
        "daedalus.runtimes.broker._utc_now",
        lambda: fixture.NOW + timedelta(seconds=2),
    )


def _authority_bundle(tmp_path: Path, authorization, execution):
    entrypoint_id = fixture._request().entrypoint_id
    ledger = ProviderObservationBindingLedger(
        tmp_path / "broker-provider-observation.sqlite3",
        authority_id="authority.runtime-provider-observation",
        authority_keyring={AUTHORITY_KEY_ID: AUTHORITY_KEY},
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        record_secret=RECORD_KEY,
    )
    authority = issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id=AUTHORITY_KEY_ID,
        authority_secret=AUTHORITY_KEY,
        binding_id="broker-exact-provider-binding",
        provider_id="provider.external-runtime-fixture",
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        entrypoint_id=entrypoint_id,
        runtime_id=authorization.capability.runtime_id,
        execution=execution,
        lease_sha256=authorization.capability.lease.digest,
        source_revision=authorization.capability.source_revision,
        issued_at=fixture.NOW - timedelta(minutes=1),
        expires_at=fixture.NOW + timedelta(hours=1),
    )
    return authority, ledger


def _subject(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    authorization, _record = fixture._authorization(tmp_path, monkeypatch)
    execution = fixture._execution()
    authority, ledger = _authority_bundle(tmp_path, authorization, execution)
    _set_clocks(monkeypatch)
    return authorization, execution, authority, ledger


def _run(
    authorization,
    execution,
    authority,
    ledger,
    *,
    invoke,
    output_digests=lambda value: (OUTPUT_SHA,),
    entrypoint_id: str | None = None,
):
    return run_runtime_provider(
        entrypoint_id or fixture._request().entrypoint_id,
        authorization=authorization,
        execution=execution,
        invoke=invoke,
        output_digests=output_digests,
        observation_authority=authority,
        observation_binding_ledger=ledger,
    )


def _durable_execution_row(tmp_path: Path, execution_id: str) -> tuple[str, str | None]:
    """Read the effect ledger's own row instead of the in-process view of it.

    ``execution_state`` is a convenience reader on the same object under test. For
    a fault row the durable bytes are the evidence, so the state and the terminal
    receipt are read straight out of the SQLite file the ledger wrote.
    """

    connection = sqlite3.connect(str(tmp_path / "effect-leases.sqlite3"))
    try:
        row = connection.execute(
            "SELECT state, terminal_receipt_json FROM effect_executions "
            "WHERE execution_id=?",
            (execution_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None, "the effect must have reached a durable start"
    return str(row[0]), row[1]


def test_completed_provider_call_uses_exact_persisted_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    calls: list[str] = []
    result = _run(
        authorization,
        execution,
        authority,
        ledger,
        invoke=lambda: calls.append("invoked") or {"answer": 42},
        output_digests=lambda value: ("b" * 64, OUTPUT_SHA),
    )
    assert calls == ["invoked"]
    assert result.executed is True
    assert result.value == {"answer": 42}
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "COMPLETED"
    assert result.terminal_receipt.output_digests == (OUTPUT_SHA, "b" * 64)
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "COMPLETED"
    retained = ledger.load(execution.execution_id)
    assert retained is not None
    assert retained.authority == authority
    assert retained.start_receipt == result.start_receipt


def test_exact_replay_is_inert_and_reuses_retained_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_property,
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    provider_calls: list[str] = []
    first = _run(
        authorization,
        execution,
        authority,
        ledger,
        invoke=lambda: provider_calls.append("first") or "output",
    )
    evidence_calls: list[str] = []
    replay = _run(
        authorization,
        execution,
        authority,
        ledger,
        invoke=lambda: provider_calls.append("duplicate") or "duplicate",
        output_digests=lambda value: evidence_calls.append(value) or (OUTPUT_SHA,),
    )
    assert first.executed is True
    assert replay.executed is False
    assert replay.start_receipt == first.start_receipt
    assert replay.terminal_receipt is None
    assert replay.value is None
    assert provider_calls == ["first"]
    assert evidence_calls == []
    # The replay attempt is the injected fault: it reached no provider effect and
    # produced no terminal of its own. Deriving the token from the replay receipt
    # keeps the report red the moment a second terminal ever appears.
    report_runtime_fault_outcome(
        record_property,
        terminal_outcome=(
            None if replay.terminal_receipt is None else replay.terminal_receipt.outcome
        ),
    )


class _DuckAuthorization:
    def __init__(self) -> None:
        self.request = SimpleNamespace(entrypoint_id=fixture._request().entrypoint_id)
        self.capability = SimpleNamespace(
            lease=SimpleNamespace(entrypoint_id=fixture._request().entrypoint_id),
            runtime_id="codex_cli",
        )
        self.registry = fixture._registry()
        self.calls: list[str] = []

    def grant(self) -> None:
        self.calls.append("grant")

    def begin_effect(self, execution):
        self.calls.append("begin")
        raise AssertionError("duck authorization reached effect start")


class _AuthorizationSubclass(RuntimeBoundEffectAuthorization):
    pass


def test_duck_typed_and_subclassed_authority_cannot_bypass_exact_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exact, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    duck = _DuckAuthorization()
    with pytest.raises(RuntimeProviderBindingMismatch, match="exact RuntimeBound"):
        _run(duck, execution, authority, ledger, invoke=lambda: "forbidden")
    assert duck.calls == []

    subclass = _AuthorizationSubclass(
        capability=exact.capability,
        request=exact.request,
        policy_decision=exact.policy_decision,
        effect_ledger=exact.effect_ledger,
        runtime_trust_ledger=exact.runtime_trust_ledger,
        lease_keyring=exact.lease_keyring,
        runtime_authority_keyring=exact.runtime_authority_keyring,
        guard_decisions=exact.guard_decisions,
        current_kill_switch_generation=exact.current_kill_switch_generation,
        registry=exact.registry,
    )
    with pytest.raises(RuntimeProviderBindingMismatch, match="exact RuntimeBound"):
        _run(subclass, execution, authority, ledger, invoke=lambda: "forbidden")
    assert exact.effect_ledger.execution_state(execution.execution_id) is None


@pytest.mark.parametrize("mutation", ["entrypoint", "noncentral", "runtime", "malformed"])
def test_foreign_noncentral_or_malformed_binding_refuses_before_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    record_property,
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    entrypoint_id = fixture._request().entrypoint_id
    candidate = authorization
    requested_entrypoint = entrypoint_id
    if mutation == "entrypoint":
        requested_entrypoint = "provider.foreign-runtime"
    elif mutation == "noncentral":
        spec = authorization.registry[entrypoint_id]
        candidate = dataclasses.replace(
            authorization,
            registry={entrypoint_id: dataclasses.replace(spec, wiring=Wiring.INVENTORY_ONLY)},
        )
    elif mutation == "runtime":
        spec = authorization.registry[entrypoint_id]
        candidate = dataclasses.replace(
            authorization,
            registry={entrypoint_id: dataclasses.replace(spec, runtime_id="foreign-runtime")},
        )
    else:
        candidate = dataclasses.replace(
            authorization,
            registry={entrypoint_id: object()},
        )
    called: list[str] = []
    with pytest.raises(RuntimeProviderBindingMismatch):
        _run(
            candidate,
            execution,
            authority,
            ledger,
            entrypoint_id=requested_entrypoint,
            invoke=lambda: called.append("invoked"),
        )
    assert called == []
    state = authorization.effect_ledger.execution_state(execution.execution_id)
    assert state is None
    report_runtime_fault_outcome(
        record_property, terminal_outcome=None, execution_state=state
    )


@pytest.mark.parametrize(
    "error,outcome",
    [(RuntimeError("provider fault"), "FAILED"), (KeyboardInterrupt(), "CANCELLED")],
)
def test_provider_exception_is_terminalized_before_escape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    outcome: str,
    record_property,
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)

    def invoke():
        raise error

    with pytest.raises(type(error)):
        _run(authorization, execution, authority, ledger, invoke=invoke)
    state = authorization.effect_ledger.execution_state(execution.execution_id)
    assert state == outcome
    report_runtime_fault_outcome(
        record_property, terminal_outcome=state, execution_state=state
    )


def test_runtime_trust_loss_after_provider_withholds_evidence_and_cancels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_property,
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    evidence_calls: list[str] = []

    def fail_verify(self):
        raise RuntimeError("runtime quarantined")

    monkeypatch.setattr(RuntimeBoundEffectAuthorization, "verify", fail_verify)
    with pytest.raises(RuntimeError, match="quarantined"):
        _run(
            authorization,
            execution,
            authority,
            ledger,
            invoke=lambda: "untrusted-output",
            output_digests=lambda value: evidence_calls.append(value) or (OUTPUT_SHA,),
        )
    assert evidence_calls == []
    state = authorization.effect_ledger.execution_state(execution.execution_id)
    assert state == "CANCELLED"
    report_runtime_fault_outcome(
        record_property, terminal_outcome=state, execution_state=state
    )


def test_runtime_trust_loss_after_evidence_blocks_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_property,
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    original = RuntimeBoundEffectAuthorization.verify
    calls = {"count": 0}

    def fail_second(self):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("runtime rotated")
        return original(self)

    monkeypatch.setattr(RuntimeBoundEffectAuthorization, "verify", fail_second)
    evidence_calls: list[str] = []
    with pytest.raises(RuntimeError, match="rotated"):
        _run(
            authorization,
            execution,
            authority,
            ledger,
            invoke=lambda: "output",
            output_digests=lambda value: evidence_calls.append(value) or (OUTPUT_SHA,),
        )
    assert evidence_calls == ["output"]
    state = authorization.effect_ledger.execution_state(execution.execution_id)
    assert state == "CANCELLED"
    report_runtime_fault_outcome(
        record_property, terminal_outcome=state, execution_state=state
    )


@pytest.mark.parametrize(
    "output_digests,cause_type",
    [
        (lambda value: (), ValueError),
        (lambda value: ("not-a-digest",), ValueError),
        (
            lambda value: (_ for _ in ()).throw(RuntimeError("local digest crash")),
            RuntimeError,
        ),
    ],
)
def test_post_provider_evidence_failure_remains_started(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    output_digests,
    cause_type: type[BaseException],
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    with pytest.raises(RuntimeProviderReconciliationRequired) as captured:
        _run(
            authorization,
            execution,
            authority,
            ledger,
            invoke=lambda: "external-output",
            output_digests=output_digests,
        )
    assert isinstance(captured.value.__cause__, cause_type)
    assert authorization.effect_ledger.execution_state(execution.execution_id) == "STARTED"
    assert ledger.load(execution.execution_id) is not None


def test_terminal_persistence_failure_is_broker_state_error_and_stays_started(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_property,
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)

    def fail_finish(self, *args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(RuntimeBoundEffectAuthorization, "finish_effect", fail_finish)
    with pytest.raises(RuntimeProviderStateError, match="terminal receipt"):
        _run(
            authorization,
            execution,
            authority,
            ledger,
            invoke=lambda: "output",
        )
    # The I/O error hit terminal persistence itself, so the honest durable record
    # is the retained start: no terminal was invented for an external call that
    # already happened, and no success was reported to the caller.
    state, terminal_json = _durable_execution_row(tmp_path, execution.execution_id)
    assert state == "STARTED"
    assert terminal_json is None
    assert authorization.effect_ledger.execution_state(execution.execution_id) == state
    report_runtime_fault_outcome(
        record_property,
        terminal_outcome=None,
        execution_state=state,
        reconciliation_pending=True,
    )


def test_keyboard_interrupt_is_cancelled_and_withholds_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_property,
) -> None:
    """Cancellation during the provider call must be fail-closed, not partial.

    A KeyboardInterrupt is not an ordinary provider fault: it can arrive at any
    point of the call and it must never leave a half-finished effect that a later
    reader can mistake for a success.
    """

    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    evidence_calls: list[str] = []

    def invoke():
        raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        _run(
            authorization,
            execution,
            authority,
            ledger,
            invoke=invoke,
            output_digests=lambda value: evidence_calls.append(value) or (OUTPUT_SHA,),
        )

    # Three independent guarantees, checked separately so a regression in one of
    # them cannot hide behind another: output evidence is never even requested,
    # the durable terminal is CANCELLED rather than COMPLETED, and the receipt the
    # ledger actually persisted carries no output digests at all.
    assert evidence_calls == []
    state, terminal_json = _durable_execution_row(tmp_path, execution.execution_id)
    assert state == "CANCELLED"
    assert terminal_json is not None
    terminal = json.loads(terminal_json)
    assert terminal["outcome"] == "CANCELLED"
    assert terminal["output_digests"] == []
    report_runtime_fault_outcome(
        record_property, terminal_outcome=state, execution_state=state
    )


def test_missing_malformed_or_duplicate_output_digests_withhold_completion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_property,
) -> None:
    """Every unusable output-evidence shape must reach the same fail-closed state.

    This is one node rather than four parametrized ones on purpose: the catalog
    row names all of these injections together, and a matrix locator must resolve
    to exactly one test case.
    """

    shapes = {
        "duplicate": lambda value: (OUTPUT_SHA, OUTPUT_SHA),
        "malformed": lambda value: ("not-a-digest",),
        "missing": lambda value: (),
        "uppercase": lambda value: (OUTPUT_SHA.upper(),),
        "wrong-type": lambda value: (42,),
    }
    for name, digests in sorted(shapes.items()):
        case = tmp_path / name
        case.mkdir()
        authorization, execution, authority, ledger = _subject(case, monkeypatch)
        with pytest.raises(RuntimeProviderReconciliationRequired) as captured:
            _run(
                authorization,
                execution,
                authority,
                ledger,
                invoke=lambda: "external-output",
                output_digests=digests,
            )
        assert captured.value.phase == "output-evidence", name
        assert isinstance(captured.value.__cause__, ValueError), name
        # The provider call already reached the outside world, so claiming FAILED
        # would be as untrue as claiming COMPLETED. The boundary claims neither.
        state, terminal_json = _durable_execution_row(case, execution.execution_id)
        assert state == "STARTED", name
        assert terminal_json is None, name
        # The retained binding is what makes the start reconcilable later.
        assert ledger.load(execution.execution_id) is not None, name

    report_runtime_fault_outcome(
        record_property,
        terminal_outcome=None,
        execution_state="STARTED",
        reconciliation_pending=True,
    )
