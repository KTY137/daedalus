from __future__ import annotations

import dataclasses
import importlib.util
import sys
import threading
from datetime import timedelta
from pathlib import Path

import pytest

from daedalus.kernel.effects import EffectLeaseLedger
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization
from daedalus.runtimes import trust_store
from daedalus.runtimes.broker import (
    RuntimeProviderBindingMismatch,
    RuntimeProviderTrustFenceError,
)
from tests.runtimes.runtime_provider_test_double import (
    run_runtime_provider_test_double as run_runtime_provider,
)
from daedalus.runtimes.fixture_fault_collector import report_runtime_fault_outcome
from daedalus.runtimes.provider_observation import (
    ProviderObservationBindingLedger,
    issue_provider_observation_authority,
)

ROOT = Path(__file__).resolve().parents[2]
AUTHORITY_FIXTURE = ROOT / "tests/kernel/test_runtime_effect_replay_projection.py"
AUTHORITY_KEY_ID = "fence-exact-authority-key"
AUTHORITY_KEY = b"fence-exact-authority-key-material-at-least-32-bytes"
OBSERVATION_KEY_ID = "fence-exact-observation-key"
OBSERVATION_KEY = b"fence-exact-observation-key-material-at-least-32-bytes"
RECORD_KEY = b"fence-exact-record-key-material-at-least-32-bytes"
OUTPUT_SHA = "6" * 64


def _load_authority_fixture():
    name = "daedalus_test_runtime_terminal_fence_exact_fixture"
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
    ledger = ProviderObservationBindingLedger(
        tmp_path / "fence-provider-observation.sqlite3",
        authority_id="authority.runtime-provider-observation",
        authority_keyring={AUTHORITY_KEY_ID: AUTHORITY_KEY},
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        record_secret=RECORD_KEY,
    )
    authority = issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id=AUTHORITY_KEY_ID,
        authority_secret=AUTHORITY_KEY,
        binding_id="fence-exact-provider-binding",
        provider_id="provider.external-runtime-fixture",
        observation_keyring={OBSERVATION_KEY_ID: OBSERVATION_KEY},
        entrypoint_id=fixture._request().entrypoint_id,
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


def _run(authorization, execution, authority, ledger, *, invoke):
    return run_runtime_provider(
        fixture._request().entrypoint_id,
        authorization=authorization,
        execution=execution,
        invoke=invoke,
        output_digests=lambda value: (OUTPUT_SHA,),
        observation_authority=authority,
        observation_binding_ledger=ledger,
    )


def _trace_terminals(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record every terminal outcome without altering terminal behaviour."""

    original = RuntimeBoundEffectAuthorization.finish_effect
    outcomes: list[str] = []

    def traced(self, start_receipt, *, outcome, output_digests=(), detail_sha256=None):
        outcomes.append(outcome)
        return original(
            self,
            start_receipt,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
        )

    monkeypatch.setattr(RuntimeBoundEffectAuthorization, "finish_effect", traced)
    return outcomes


def _count_verifications(monkeypatch: pytest.MonkeyPatch, *, after_second=None):
    """Count facade verifications and optionally mutate trust after the last one."""

    original = RuntimeBoundEffectAuthorization.verify
    calls = {"count": 0}

    def counted(self):
        calls["count"] += 1
        record = original(self)
        if calls["count"] == 2 and after_second is not None:
            after_second(self, record)
        return record

    monkeypatch.setattr(RuntimeBoundEffectAuthorization, "verify", counted)
    return calls


def _rotate_record_identity(ledger, record) -> None:
    """Replace the ACTIVE record with an equally authentic, differently identified one.

    This is the rotation the terminal fence must catch: the persisted row still
    authenticates under the ledger's integrity key and is still ACTIVE, but its
    ``record_sha256`` no longer equals the digest sealed into the capability.
    """

    rotated = trust_store._make_record(
        integrity_key=ledger._integrity_key,
        runtime_id=record.runtime_id,
        envelope_sha256=record.envelope_sha256,
        probe_identity_sha256=record.probe_identity_sha256,
        conformance_receipt_sha256=record.conformance_receipt_sha256,
        runtime_manifest_sha256=record.runtime_manifest_sha256,
        source_revision=record.source_revision,
        observed_at=record.observed_at,
        admitted_at=record.admitted_at,
        expires_at=record.expires_at,
        state=record.state,
        state_changed_at=trust_store._timestamp(fixture.NOW - timedelta(minutes=5)),
        reason="",
    )
    assert rotated.record_sha256 != record.record_sha256
    with ledger._connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        ledger._replace(connection, rotated)
        connection.execute("COMMIT")


def _record_state(ledger, runtime_id: str) -> str:
    records = ledger.records(runtime_id)
    assert len(records) == 1
    return records[0].state


def test_runtime_trust_and_effect_ledgers_must_be_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_property,
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    shared = dataclasses.replace(
        authorization,
        effect_ledger=EffectLeaseLedger(authorization.runtime_trust_ledger.path),
    )
    verifications = _count_verifications(monkeypatch)
    terminals = _trace_terminals(monkeypatch)

    with pytest.raises(RuntimeProviderBindingMismatch, match="distinct SQLite"):
        _run(shared, execution, authority, ledger, invoke=lambda: {"must": "not run"})

    assert verifications["count"] == 0
    assert terminals == []
    assert shared.effect_ledger.execution_state(execution.execution_id) is None
    report_runtime_fault_outcome(
        record_property,
        terminal_outcome=terminals[0] if terminals else None,
        execution_state=shared.effect_ledger.execution_state(execution.execution_id),
    )


def test_quarantine_waits_until_completed_receipt_is_durable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_property,
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    trust = authorization.runtime_trust_ledger
    capability = authorization.capability

    original_finish = RuntimeBoundEffectAuthorization.finish_effect
    terminals: list[str] = []
    finish_entered = threading.Event()
    finish_release = threading.Event()

    def blocking_finish(
        self, start_receipt, *, outcome, output_digests=(), detail_sha256=None
    ):
        if outcome == "completed":
            finish_entered.set()
            assert finish_release.wait(timeout=5)
        terminals.append(outcome)
        return original_finish(
            self,
            start_receipt,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
        )

    monkeypatch.setattr(
        RuntimeBoundEffectAuthorization, "finish_effect", blocking_finish
    )

    result_box: dict[str, object] = {}
    error_box: list[BaseException] = []

    def invoke_broker() -> None:
        try:
            result_box["result"] = _run(
                authorization,
                execution,
                authority,
                ledger,
                invoke=lambda: {"answer": 42},
            )
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            error_box.append(exc)

    broker_thread = threading.Thread(target=invoke_broker)
    broker_thread.start()
    assert finish_entered.wait(timeout=5)

    quarantine_done = threading.Event()
    quarantine_error: list[BaseException] = []

    def quarantine() -> None:
        try:
            trust.quarantine(
                runtime_id=capability.runtime_id,
                envelope_sha256=capability.runtime_envelope_sha256,
                reason="terminal-fence-serialization-probe",
                quarantined_at=fixture.NOW,
            )
        except BaseException as exc:  # pragma: no cover - surfaced by assertion
            quarantine_error.append(exc)
        quarantine_done.set()

    quarantine_thread = threading.Thread(target=quarantine)
    quarantine_thread.start()

    # The terminal fence owns BEGIN IMMEDIATE while the effect receipt is being
    # persisted, so a concurrent quarantine cannot commit in the middle.
    assert quarantine_done.wait(timeout=0.1) is False
    finish_release.set()
    broker_thread.join(timeout=10)
    quarantine_thread.join(timeout=10)

    assert not broker_thread.is_alive()
    assert not quarantine_thread.is_alive()
    assert not error_box
    assert not quarantine_error
    result = result_box["result"]
    assert result.executed is True  # type: ignore[union-attr]
    assert result.terminal_receipt.outcome == "COMPLETED"  # type: ignore[union-attr]
    assert terminals == ["completed"]
    assert (
        authorization.effect_ledger.execution_state(execution.execution_id)
        == "COMPLETED"
    )
    assert quarantine_done.is_set()
    assert _record_state(trust, capability.runtime_id) == "QUARANTINED"
    report_runtime_fault_outcome(
        record_property,
        terminal_outcome=terminals[0],
        execution_state=authorization.effect_ledger.execution_state(
            execution.execution_id
        ),
    )


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("quarantine", "quarantined before terminal completion"),
        ("replace-record", "changed before terminal completion: record_sha256"),
    ],
    # The canonical fault catalog addresses these two rows as
    # ...fence[quarantine] and ...fence[replace-record]. Without explicit ids
    # pytest folds the expected *message* into the node id, so the catalog's
    # executor locator silently stops resolving whenever that wording is
    # edited. Pinning the ids makes the identity the contract, not the prose.
    ids=("quarantine", "replace-record"),
)
def test_trust_change_after_last_plain_verify_is_caught_by_terminal_fence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected: str,
    record_property,
) -> None:
    authorization, execution, authority, ledger = _subject(tmp_path, monkeypatch)
    trust = authorization.runtime_trust_ledger
    capability = authorization.capability

    def mutate(_self, record) -> None:
        if mutation == "quarantine":
            trust.quarantine(
                runtime_id=capability.runtime_id,
                envelope_sha256=capability.runtime_envelope_sha256,
                reason="rotated-after-last-plain-verify",
                quarantined_at=fixture.NOW,
            )
        else:
            _rotate_record_identity(trust, record)

    verifications = _count_verifications(monkeypatch, after_second=mutate)
    terminals = _trace_terminals(monkeypatch)

    with pytest.raises(RuntimeProviderTrustFenceError, match=expected):
        _run(
            authorization,
            execution,
            authority,
            ledger,
            invoke=lambda: {"must": "not be released"},
        )

    # The provider already ran, but the broker withheld its value and converted
    # the durable execution to CANCELLED rather than publishing COMPLETED.
    assert verifications["count"] == 2
    assert terminals == ["cancelled"]
    assert (
        authorization.effect_ledger.execution_state(execution.execution_id)
        == "CANCELLED"
    )
    report_runtime_fault_outcome(
        record_property,
        terminal_outcome=terminals[0],
        execution_state=authorization.effect_ledger.execution_state(
            execution.execution_id
        ),
    )
