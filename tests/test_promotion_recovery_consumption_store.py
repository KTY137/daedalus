from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from daedalus.kernel.promotion_recovery_consumption import (
    PromotionRecoveryConsumptionStateError,
)
from daedalus.kernel.promotion_recovery_consumption_store import (
    SCHEMA_SHA256,
    PreprovisionedPromotionRecoveryConsumptionLedger,
    PromotionRecoveryConsumptionStoreError,
    initialize_promotion_recovery_consumption_store,
    inspect_promotion_recovery_consumption_store,
)


def test_initialize_inspect_and_open_preprovisioned_store(tmp_path: Path) -> None:
    path = tmp_path / "recovery-consumption.sqlite3"

    created = initialize_promotion_recovery_consumption_store(path)
    inspected = inspect_promotion_recovery_consumption_store(path)
    ledger = PreprovisionedPromotionRecoveryConsumptionLedger(path)

    assert created == inspected
    assert created.path == str(path.resolve())
    assert created.schema_version == 1
    assert created.schema_sha256 == SCHEMA_SHA256
    assert created.identity == ledger.store_status.identity
    assert path.is_file()
    assert not path.is_symlink()


def test_normal_open_never_creates_a_missing_store(tmp_path: Path) -> None:
    path = tmp_path / "missing.sqlite3"

    with pytest.raises(PromotionRecoveryConsumptionStoreError):
        PreprovisionedPromotionRecoveryConsumptionLedger(path)

    assert not path.exists()


def test_initializer_requires_preprovisioned_parent(tmp_path: Path) -> None:
    parent = tmp_path / "missing-parent"
    path = parent / "store.sqlite3"

    with pytest.raises(PromotionRecoveryConsumptionStoreError):
        initialize_promotion_recovery_consumption_store(path)

    assert not parent.exists()
    assert not path.exists()


def test_initializer_never_replaces_an_existing_target(tmp_path: Path) -> None:
    path = tmp_path / "store.sqlite3"
    path.write_bytes(b"operator-owned")
    before = path.read_bytes()

    with pytest.raises(PromotionRecoveryConsumptionStoreError):
        initialize_promotion_recovery_consumption_store(path)

    assert path.read_bytes() == before


def test_initializer_is_one_use_for_an_exact_target(tmp_path: Path) -> None:
    path = tmp_path / "store.sqlite3"
    first = initialize_promotion_recovery_consumption_store(path)

    with pytest.raises(PromotionRecoveryConsumptionStoreError):
        initialize_promotion_recovery_consumption_store(path)

    assert inspect_promotion_recovery_consumption_store(path) == first


def test_malformed_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "malformed.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE promotion_recovery_consumptions_v1 (x TEXT)")
        connection.execute("PRAGMA user_version=1")

    with pytest.raises(PromotionRecoveryConsumptionStoreError):
        inspect_promotion_recovery_consumption_store(path)
    with pytest.raises(PromotionRecoveryConsumptionStoreError):
        PreprovisionedPromotionRecoveryConsumptionLedger(path)


def test_writer_open_uses_existing_store_and_does_not_create(tmp_path: Path) -> None:
    path = tmp_path / "store.sqlite3"
    initialize_promotion_recovery_consumption_store(path)
    ledger = PreprovisionedPromotionRecoveryConsumptionLedger(path)

    connection = ledger._connect_writer()
    try:
        assert int(connection.execute("PRAGMA query_only").fetchone()[0]) == 0
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()

    path.unlink()
    with pytest.raises(PromotionRecoveryConsumptionStateError):
        ledger._connect_writer()
    assert not path.exists()


def test_admitted_store_identity_cannot_be_substituted(tmp_path: Path) -> None:
    path = tmp_path / "store.sqlite3"
    initialize_promotion_recovery_consumption_store(path)
    ledger = PreprovisionedPromotionRecoveryConsumptionLedger(path)
    original_identity = ledger.store_status.identity

    path.unlink()
    replacement = initialize_promotion_recovery_consumption_store(path)
    assert replacement.identity != original_identity

    with pytest.raises(PromotionRecoveryConsumptionStateError):
        _ = ledger.store_status
    with pytest.raises(PromotionRecoveryConsumptionStateError):
        ledger._connect_read_only()


def test_inspection_is_read_only(tmp_path: Path) -> None:
    path = tmp_path / "store.sqlite3"
    initialize_promotion_recovery_consumption_store(path)
    before = path.stat()

    first = inspect_promotion_recovery_consumption_store(path)
    second = inspect_promotion_recovery_consumption_store(path)
    after = path.stat()

    assert first == second
    assert before.st_size == after.st_size
    assert before.st_mtime_ns == after.st_mtime_ns


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlink unsupported")
def test_symlinked_parent_and_store_are_refused(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    redirected_parent = tmp_path / "redirected"
    try:
        os.symlink(real_parent, redirected_parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable")

    redirected_store = redirected_parent / "store.sqlite3"
    with pytest.raises(PromotionRecoveryConsumptionStoreError):
        initialize_promotion_recovery_consumption_store(redirected_store)
    assert not (real_parent / "store.sqlite3").exists()

    real_store = real_parent / "real.sqlite3"
    initialize_promotion_recovery_consumption_store(real_store)
    store_link = real_parent / "link.sqlite3"
    try:
        os.symlink(real_store, store_link)
    except (OSError, NotImplementedError):
        pytest.skip("file symlink creation unavailable")
    with pytest.raises(PromotionRecoveryConsumptionStoreError):
        inspect_promotion_recovery_consumption_store(store_link)
