from __future__ import annotations

import dataclasses
import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import daedalus.runtimes.provider_observation_store as store_module
from daedalus.kernel.effects import EffectExecutionRequest, LeasedEffectStartReceipt
from daedalus.runtimes.provider_observation import (
    ProviderObservationAuthorityBindingError,
    ProviderObservationAuthorityStateError,
    issue_provider_observation_authority,
)
from daedalus.runtimes.provider_observation_store import (
    SCHEMA_SHA256,
    PreprovisionedProviderObservationBindingLedger,
    ProviderObservationStoreError,
    ProviderObservationStoreTarget,
    initialize_provider_observation_binding_store,
    inspect_provider_observation_binding_store,
)
from daedalus.spine.envelope import canonical_sha


REVISION = "8c3429119a6eeffdf81ef553aa3886ee73477e44"
STALE_REVISION = "1" * 40
NOW = datetime(2026, 8, 4, 21, 30, tzinfo=timezone.utc)
LEASE_SHA256 = "2" * 64
AUTHORITY_SECRET = b"provider-authority-secret-material-at-least-32-bytes"
OBSERVATION_SECRET = b"provider-observation-secret-material-at-least-32-bytes"
RECORD_SECRET = b"provider-record-secret-material-at-least-32-bytes"
AUTHORITY_KEYRING = {"provider-authority-key": AUTHORITY_SECRET}
OBSERVATION_KEYRING = {"provider-observation-key": OBSERVATION_SECRET}


def _target(tmp_path: Path, *, revision: str = REVISION) -> ProviderObservationStoreTarget:
    primary = tmp_path / "primary-checkout"
    attempt = tmp_path / "attempt"
    state = attempt / "state"
    primary.mkdir(exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    return ProviderObservationStoreTarget(
        path=str((state / "provider-observation.sqlite3").resolve()),
        attempt_root=str(attempt.resolve()),
        primary_checkout_root=str(primary.resolve()),
        source_revision=revision,
    )


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="provider-store-execution",
        idempotency_key="provider-store-idempotency",
        requested_effects=("network_egress",),
        egress_endpoints=("https://provider.invalid",),
        tools=("provider-runtime",),
        kill_switch_ref="provider-kill-switch",
        kill_switch_generation=1,
    )


def _start(execution: EffectExecutionRequest) -> LeasedEffectStartReceipt:
    body = {
        "lease_sha256": LEASE_SHA256,
        "execution_id": execution.execution_id,
        "idempotency_key": execution.idempotency_key,
        "execution_request_sha256": execution.digest,
        "boundary_receipt_sha256": "3" * 64,
        "started_at": NOW.isoformat(timespec="microseconds"),
    }
    return LeasedEffectStartReceipt(
        **body,
        receipt_sha256=canonical_sha(body),
    )


def _authority(execution: EffectExecutionRequest):
    return issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id="provider-authority-key",
        authority_secret=AUTHORITY_SECRET,
        binding_id="provider-store-binding",
        provider_id="provider.external-fixture",
        observation_keyring=OBSERVATION_KEYRING,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution=execution,
        lease_sha256=LEASE_SHA256,
        source_revision=REVISION,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )


def _ledger(target: ProviderObservationStoreTarget):
    return PreprovisionedProviderObservationBindingLedger(
        target,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        record_secret=RECORD_SECRET,
    )


def test_initialize_inspect_and_construct_without_implicit_schema_work(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    created = initialize_provider_observation_binding_store(target)
    inspected = inspect_provider_observation_binding_store(target)
    ledger = _ledger(target)

    assert created == inspected
    assert created.target_sha256 == target.digest
    assert created.source_revision == REVISION
    assert created.schema_sha256 == SCHEMA_SHA256
    assert created.file_nlink == 1
    assert ledger.store_target_sha256 == target.digest
    assert Path(target.path).is_file()


def test_missing_store_constructor_and_inspection_never_create_state(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)

    with pytest.raises(ProviderObservationStoreError):
        inspect_provider_observation_binding_store(target)
    with pytest.raises(ProviderObservationAuthorityBindingError):
        _ledger(target)

    assert not Path(target.path).exists()
    assert list(Path(target.path).parent.iterdir()) == []


def test_initializer_requires_preexisting_isolated_parent(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    attempt = tmp_path / "attempt"
    primary.mkdir()
    attempt.mkdir()
    missing_parent = attempt / "missing"

    with pytest.raises(ProviderObservationStoreError):
        ProviderObservationStoreTarget(
            path=str((missing_parent / "store.sqlite3").resolve()),
            attempt_root=str(attempt.resolve()),
            primary_checkout_root=str(primary.resolve()),
            source_revision=REVISION,
        )

    assert not missing_parent.exists()


def test_existing_target_parent_must_stay_inside_attempt_root(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    attempt = tmp_path / "attempt"
    outside = tmp_path / "outside"
    primary.mkdir()
    attempt.mkdir()
    outside.mkdir()

    with pytest.raises(ProviderObservationStoreError, match="attempt root"):
        ProviderObservationStoreTarget(
            path=str((outside / "store.sqlite3").resolve()),
            attempt_root=str(attempt.resolve()),
            primary_checkout_root=str(primary.resolve()),
            source_revision=REVISION,
        )


def test_primary_checkout_and_attempt_roots_must_be_disjoint(tmp_path: Path) -> None:
    primary = tmp_path / "checkout"
    attempt = primary / "attempt"
    attempt.mkdir(parents=True)

    with pytest.raises(ProviderObservationStoreError, match="disjoint"):
        ProviderObservationStoreTarget(
            path=str((attempt / "store.sqlite3").resolve()),
            attempt_root=str(attempt.resolve()),
            primary_checkout_root=str(primary.resolve()),
            source_revision=REVISION,
        )


def test_initializer_never_clobbers_an_existing_target(tmp_path: Path) -> None:
    target = _target(tmp_path)
    path = Path(target.path)
    path.write_bytes(b"operator-owned")

    with pytest.raises(ProviderObservationStoreError):
        initialize_provider_observation_binding_store(target)

    assert path.read_bytes() == b"operator-owned"


def test_stale_revision_target_is_refused_by_persisted_metadata(tmp_path: Path) -> None:
    target = _target(tmp_path)
    initialize_provider_observation_binding_store(target)
    stale = dataclasses.replace(target, source_revision=STALE_REVISION)

    assert stale.digest != target.digest
    with pytest.raises(ProviderObservationStoreError, match="metadata binding"):
        inspect_provider_observation_binding_store(stale)
    with pytest.raises(ProviderObservationAuthorityBindingError):
        _ledger(stale)


def test_malformed_metadata_and_schema_are_refused(tmp_path: Path) -> None:
    target = _target(tmp_path)
    path = Path(target.path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE provider_observation_bindings "
            "(execution_id TEXT PRIMARY KEY, record_json TEXT, "
            "record_sha256 TEXT, record_hmac_sha256 TEXT)"
        )
        connection.execute("PRAGMA user_version=1")

    with pytest.raises(ProviderObservationStoreError):
        inspect_provider_observation_binding_store(target)


def test_symlink_target_and_parent_redirection_are_refused(tmp_path: Path) -> None:
    target = _target(tmp_path)
    foreign = tmp_path / "foreign.sqlite3"
    foreign.write_bytes(b"foreign")
    try:
        Path(target.path).symlink_to(foreign)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(ProviderObservationStoreError):
        inspect_provider_observation_binding_store(target)


def test_hard_link_alias_is_refused(tmp_path: Path) -> None:
    target = _target(tmp_path)
    initialize_provider_observation_binding_store(target)
    alias = Path(target.path).with_name("alias.sqlite3")
    try:
        os.link(target.path, alias)
    except OSError:
        pytest.skip("hard-link creation is unavailable")

    with pytest.raises(ProviderObservationStoreError, match="hard-link aliases"):
        inspect_provider_observation_binding_store(target)


def test_preexisting_sqlite_sidecar_is_refused(tmp_path: Path) -> None:
    target = _target(tmp_path)
    initialize_provider_observation_binding_store(target)
    journal = Path(target.path + "-journal")
    journal.write_bytes(b"untrusted-sidecar")

    with pytest.raises(ProviderObservationStoreError, match="sidecar"):
        inspect_provider_observation_binding_store(target)
    with pytest.raises(ProviderObservationAuthorityBindingError):
        _ledger(target)


def test_admitted_store_inode_cannot_be_substituted_with_same_bound_bytes(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    initialize_provider_observation_binding_store(target)
    ledger = _ledger(target)
    replacement = Path(target.path).with_name("replacement.sqlite3")
    shutil.copyfile(target.path, replacement)
    assert replacement.stat().st_ino != Path(target.path).stat().st_ino
    os.replace(replacement, target.path)

    with pytest.raises(
        ProviderObservationAuthorityStateError,
        match="identity changed",
    ):
        ledger.load("provider-store-execution")


def test_binding_round_trip_uses_preprovisioned_store_and_inert_read(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    initialize_provider_observation_binding_store(target)
    ledger = _ledger(target)
    execution = _execution()
    authority = _authority(execution)
    start = _start(execution)

    ledger.verify_authority(
        authority,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution=execution,
        lease_sha256=LEASE_SHA256,
        source_revision=REVISION,
        at=NOW,
    )
    bound = ledger.bind_start(authority, start, bound_at=NOW)
    loaded = ledger.require_bound(
        authority,
        start,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution=execution,
        lease_sha256=LEASE_SHA256,
        source_revision=REVISION,
    )

    assert loaded == bound
    assert Path(target.path).exists()
    assert not Path(target.path + "-journal").exists()
    assert not Path(target.path + "-wal").exists()
    assert not Path(target.path + "-shm").exists()


def test_load_path_opens_only_read_only_query_only_connections(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path)
    initialize_provider_observation_binding_store(target)
    ledger = _ledger(target)
    calls: list[tuple[str, bool]] = []
    original = store_module._open_sqlite

    def record(path: Path, *, mode: str, query_only: bool):
        calls.append((mode, query_only))
        return original(path, mode=mode, query_only=query_only)

    monkeypatch.setattr(store_module, "_open_sqlite", record)
    assert ledger.load("provider-store-execution") is None
    assert calls
    assert set(calls) == {("ro", True)}


def test_deleted_store_is_not_recreated_by_writer_or_reader(tmp_path: Path) -> None:
    target = _target(tmp_path)
    initialize_provider_observation_binding_store(target)
    ledger = _ledger(target)
    Path(target.path).unlink()

    with pytest.raises(ProviderObservationAuthorityStateError):
        ledger.load("provider-store-execution")
    with pytest.raises(ProviderObservationAuthorityStateError):
        ledger._connect()
    assert not Path(target.path).exists()


def test_postpublication_failure_removes_only_own_inode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path)

    def refuse(_target: ProviderObservationStoreTarget):
        raise ProviderObservationStoreError("injected postpublication fault")

    monkeypatch.setattr(
        store_module,
        "inspect_provider_observation_binding_store",
        refuse,
    )
    with pytest.raises(ProviderObservationStoreError):
        initialize_provider_observation_binding_store(target)

    assert not Path(target.path).exists()
    assert list(Path(target.path).parent.glob(".*.provider-observation.tmp")) == []
