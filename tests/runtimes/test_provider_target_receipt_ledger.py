from __future__ import annotations

import dataclasses
import runpy
from pathlib import Path

import pytest

from daedalus.kernel.source_trees import SourceTreeStore, SourceTreeStoreError
from daedalus.runtimes.provider.target_receipt_ledger import (
    ProviderTargetReceiptLedger,
    ProviderTargetReceiptRetentionBindingError,
    ProviderTargetReceiptRetentionStateError,
)
from daedalus.spine.ledger import SpineLedger


_HELPERS = runpy.run_path(
    str(Path(__file__).with_name("test_provider_target_verification.py"))
)
_fixture = _HELPERS["_fixture"]
_issue = _HELPERS["_issue"]
NOW = _HELPERS["NOW"]
TARGET_CONTRACT_ID = _HELPERS["TARGET_CONTRACT_ID"]
AUTHORITY_KEYRING = _HELPERS["AUTHORITY_KEYRING"]
OBSERVATION_KEYRING = _HELPERS["OBSERVATION_KEYRING"]
VERIFIER_KEYRING = _HELPERS["VERIFIER_KEYRING"]


def _ledger(tmp_path: Path, fixture):
    primary = tmp_path / "primary"
    primary.mkdir(parents=True)
    spine = SpineLedger(tmp_path / "state" / "spine.sqlite3")
    ledger = ProviderTargetReceiptLedger(
        spine,
        fixture.store,
        primary_checkout=primary,
    )
    return primary, spine, ledger


def _retain(ledger, receipt, fixture, **overrides):
    values = {
        "target_contract_id": TARGET_CONTRACT_ID,
        "authority_id": "authority.runtime-provider-observation",
        "authority_keyring": AUTHORITY_KEYRING,
        "observation_keyring": OBSERVATION_KEYRING,
        "verifier_id": "provider-target-verifier",
        "verifier_keyring": VERIFIER_KEYRING,
        "at": NOW,
    }
    values.update(overrides)
    return ledger.retain(
        receipt,
        fixture.target_authority,
        fixture.invocation_authority,
        fixture.identity_registry,
        fixture.execution,
        fixture.target_manifest,
        fixture.tree_ref,
        **values,
    )


def _tree_digest(root: Path) -> tuple[tuple[str, bytes], ...]:
    return tuple(
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in sorted(root.rglob("*"))
        if path.is_file()
    )


def test_exact_receipt_is_retained_in_cas_and_replay_is_inert(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    primary, spine, ledger = _ledger(tmp_path, fixture)
    before = _tree_digest(primary)

    first = _retain(ledger, receipt, fixture)
    second = _retain(ledger, receipt, fixture)

    assert first.executed is True
    assert second.executed is False
    assert first.intent_id == second.intent_id
    assert first.artifact == second.artifact
    assert first.artifact.sha256 == receipt.digest
    assert fixture.store.read_bytes(
        first.artifact,
        max_bytes=1024 * 1024,
    )
    assert _tree_digest(primary) == before
    rows = spine.resolve_by_effect(
        "provider-target-verification-receipt:" + receipt.digest
    )
    assert len(rows) == 1
    assert rows[0].state == "COMPLETED"
    spine.close()


def test_restart_after_cas_publication_completes_same_pending_intent(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    _, spine, ledger = _ledger(tmp_path, fixture)
    original = SourceTreeStore.put_bytes
    calls = 0

    def crash_after_publish(self, payload):
        nonlocal calls
        calls += 1
        original(self, payload)
        raise SourceTreeStoreError("simulated crash after publication")

    monkeypatch.setattr(SourceTreeStore, "put_bytes", crash_after_publish)
    with pytest.raises(
        ProviderTargetReceiptRetentionStateError,
        match="requires replay",
    ):
        _retain(ledger, receipt, fixture)
    assert calls == 1
    pending = spine.resolve_by_effect(
        "provider-target-verification-receipt:" + receipt.digest
    )
    assert len(pending) == 1
    assert pending[0].state == "INTENDED"

    monkeypatch.setattr(SourceTreeStore, "put_bytes", original)
    replay = _retain(ledger, receipt, fixture)
    assert replay.executed is True
    terminal = spine.resolve_by_effect(
        "provider-target-verification-receipt:" + receipt.digest
    )
    assert len(terminal) == 1
    assert terminal[0].state == "COMPLETED"
    spine.close()


def test_invalid_signature_refuses_before_event_or_artifact_write(
    tmp_path,
    monkeypatch,
) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = dataclasses.replace(_issue(fixture), signature_sha256="0" * 64)
    _, spine, ledger = _ledger(tmp_path, fixture)
    writes = []
    monkeypatch.setattr(
        spine,
        "record_intent",
        lambda *args, **kwargs: writes.append("intent"),
    )
    monkeypatch.setattr(
        fixture.store,
        "put_bytes",
        lambda payload: writes.append("cas"),
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionBindingError,
        match="did not authenticate",
    ):
        _retain(ledger, receipt, fixture)
    assert writes == []
    spine.close()


def test_completed_replay_refuses_substituted_cas_bytes(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    _, spine, ledger = _ledger(tmp_path, fixture)
    result = _retain(ledger, receipt, fixture)
    object_path = fixture.store._object_path(result.artifact.sha256)
    object_path.write_bytes(b"substituted")

    with pytest.raises(
        ProviderTargetReceiptRetentionStateError,
        match="unavailable or corrupt",
    ):
        _retain(ledger, receipt, fixture)
    spine.close()


def test_duplicate_or_noncanonical_event_state_fails_closed(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
    receipt = _issue(fixture)
    _, spine, ledger = _ledger(tmp_path, fixture)
    result = _retain(ledger, receipt, fixture)
    with spine._txn() as connection:
        connection.execute(
            "UPDATE intents SET payload=? WHERE id=?",
            ('{"schema" : "tampered"}', result.intent_id),
        )

    with pytest.raises(
        ProviderTargetReceiptRetentionStateError,
        match="noncanonical|digest",
    ):
        _retain(ledger, receipt, fixture)
    spine.close()


def test_retention_topology_refuses_primary_checkout_overlap(tmp_path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    store = SourceTreeStore(primary / "cas")
    spine = SpineLedger(tmp_path / "state" / "spine.sqlite3")

    with pytest.raises(
        ProviderTargetReceiptRetentionBindingError,
        match="disjoint from the primary checkout",
    ):
        ProviderTargetReceiptLedger(
            spine,
            store,
            primary_checkout=primary,
        )
    spine.close()


def test_retention_requires_exact_writer_and_store_types(tmp_path) -> None:
    fixture = _fixture(tmp_path / "fixture")
    primary = tmp_path / "primary"
    primary.mkdir()
    spine = SpineLedger(tmp_path / "state" / "spine.sqlite3")

    class DerivedSpine(SpineLedger):
        pass

    class DerivedStore(SourceTreeStore):
        pass

    derived_spine = DerivedSpine(tmp_path / "other" / "spine.sqlite3")
    with pytest.raises(
        ProviderTargetReceiptRetentionBindingError,
        match="exact writable SpineLedger",
    ):
        ProviderTargetReceiptLedger(
            derived_spine,
            fixture.store,
            primary_checkout=primary,
        )
    derived_spine.close()

    derived_store = DerivedStore(tmp_path / "derived-cas")
    with pytest.raises(
        ProviderTargetReceiptRetentionBindingError,
        match="exact SourceTreeStore",
    ):
        ProviderTargetReceiptLedger(
            spine,
            derived_store,
            primary_checkout=primary,
        )
    spine.close()
