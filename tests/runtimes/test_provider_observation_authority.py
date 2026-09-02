from __future__ import annotations

import contextlib
import dataclasses
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.kernel.effects import EffectExecutionRequest, LeasedEffectStartReceipt
from daedalus.runtimes.provider_observation import (
    ProviderObservationAuthorityBindingError,
    ProviderObservationAuthoritySignatureError,
    ProviderObservationAuthorityStateError,
    ProviderObservationBindingLedger,
    issue_provider_observation_authority,
    observation_keyring_digest,
    verify_provider_observation_authority,
)
from daedalus.spine.envelope import canonical_sha


NOW = datetime(2026, 8, 4, 19, 0, tzinfo=timezone.utc)
REVISION = "1" * 40
LEASE_SHA = "2" * 64
AUTHORITY_KEY = b"provider-authority-key-material-at-least-32-bytes"
OBSERVATION_KEY = b"provider-observation-key-material-at-least-32-bytes"
RECORD_KEY = b"provider-binding-record-key-material-at-least-32-bytes"
AUTHORITY_KEYRING = {"provider-authority-key": AUTHORITY_KEY}
OBSERVATION_KEYRING = {"provider-observation-key": OBSERVATION_KEY}


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="provider-observation-execution",
        idempotency_key="provider-observation-idempotency",
        requested_effects=("network_egress", "process_spawn"),
        egress_endpoints=("https://provider.invalid",),
        tools=("provider-runtime",),
        kill_switch_ref="provider-kill-switch",
        kill_switch_generation=1,
    )


def _start(execution: EffectExecutionRequest) -> LeasedEffectStartReceipt:
    body = {
        "lease_sha256": LEASE_SHA,
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


def _authority(
    execution: EffectExecutionRequest,
    *,
    provider_id: str = "provider.external-fixture",
    observation_keyring=OBSERVATION_KEYRING,
):
    return issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id="provider-authority-key",
        authority_secret=AUTHORITY_KEY,
        binding_id="provider-observation-binding",
        provider_id=provider_id,
        observation_keyring=observation_keyring,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution=execution,
        lease_sha256=LEASE_SHA,
        source_revision=REVISION,
        issued_at=NOW - timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )


def _ledger(tmp_path: Path, *, observation_keyring=OBSERVATION_KEYRING):
    return ProviderObservationBindingLedger(
        tmp_path / "provider-observation.sqlite3",
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=observation_keyring,
        record_secret=RECORD_KEY,
    )


def test_signed_authority_binds_provider_and_exact_observation_key_set() -> None:
    execution = _execution()
    authority = _authority(execution)
    verify_provider_observation_authority(
        authority,
        authority_id="authority.runtime-provider-observation",
        authority_keyring=AUTHORITY_KEYRING,
        observation_keyring=OBSERVATION_KEYRING,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution=execution,
        lease_sha256=LEASE_SHA,
        source_revision=REVISION,
        at=NOW,
    )
    assert authority.provider_id == "provider.external-fixture"
    assert authority.observation_issuer_key_ids == ("provider-observation-key",)
    assert authority.observation_keyring_sha256 == observation_keyring_digest(
        OBSERVATION_KEYRING
    )


@pytest.mark.parametrize(
    "dimension",
    [
        "provider",
        "authority_signature",
        "observation_key_id",
        "observation_key_material",
        "entrypoint",
        "runtime",
        "execution",
        "lease",
        "revision",
    ],
)
def test_substituted_authority_subject_refuses(dimension: str) -> None:
    execution = _execution()
    authority = _authority(execution)
    authority_keyring = AUTHORITY_KEYRING
    observation_keyring = OBSERVATION_KEYRING
    entrypoint = "provider.runtime-fixture"
    runtime = "runtime-fixture"
    candidate_execution = execution
    lease = LEASE_SHA
    revision = REVISION

    if dimension == "provider":
        authority = dataclasses.replace(authority, provider_id="provider.foreign")
    elif dimension == "authority_signature":
        authority = dataclasses.replace(authority, signature_sha256="0" * 64)
    elif dimension == "observation_key_id":
        observation_keyring = {"foreign-observation-key": OBSERVATION_KEY}
    elif dimension == "observation_key_material":
        observation_keyring = {
            "provider-observation-key":
                b"foreign-observation-key-material-at-least-32-bytes"
        }
    elif dimension == "entrypoint":
        entrypoint = "provider.foreign-runtime"
    elif dimension == "runtime":
        runtime = "foreign-runtime"
    elif dimension == "execution":
        candidate_execution = dataclasses.replace(
            execution,
            execution_id="foreign-execution",
        )
    elif dimension == "lease":
        lease = "4" * 64
    else:
        revision = "5" * 40

    error = (
        ProviderObservationAuthoritySignatureError
        if dimension in {"provider", "authority_signature"}
        else ProviderObservationAuthorityBindingError
    )
    with pytest.raises(error):
        verify_provider_observation_authority(
            authority,
            authority_id="authority.runtime-provider-observation",
            authority_keyring=authority_keyring,
            observation_keyring=observation_keyring,
            entrypoint_id=entrypoint,
            runtime_id=runtime,
            execution=candidate_execution,
            lease_sha256=lease,
            source_revision=revision,
            at=NOW,
        )


def test_binding_is_persisted_before_replay_and_conflicts_fail(
    tmp_path: Path,
) -> None:
    execution = _execution()
    start = _start(execution)
    authority = _authority(execution)
    ledger = _ledger(tmp_path)
    ledger.verify_authority(
        authority,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution=execution,
        lease_sha256=LEASE_SHA,
        source_revision=REVISION,
        at=NOW,
    )
    record = ledger.bind_start(authority, start, bound_at=NOW)
    loaded = ledger.require_bound(
        authority,
        start,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution=execution,
        lease_sha256=LEASE_SHA,
        source_revision=REVISION,
    )
    assert loaded == record
    assert loaded.start_receipt == start

    foreign = _authority(execution, provider_id="provider.foreign")
    with pytest.raises(
        ProviderObservationAuthorityBindingError,
        match="retained provider observation authority differs",
    ):
        ledger.require_bound(
            foreign,
            start,
            entrypoint_id="provider.runtime-fixture",
            runtime_id="runtime-fixture",
            execution=execution,
            lease_sha256=LEASE_SHA,
            source_revision=REVISION,
        )


def test_missing_and_tampered_persisted_binding_refuse(tmp_path: Path) -> None:
    execution = _execution()
    start = _start(execution)
    authority = _authority(execution)
    ledger = _ledger(tmp_path)
    assert ledger.load(execution.execution_id) is None
    ledger.bind_start(authority, start, bound_at=NOW)

    with contextlib.closing(sqlite3.connect(ledger.path)) as connection:
        connection.execute(
            "UPDATE provider_observation_bindings "
            "SET record_hmac_sha256=? WHERE execution_id=?",
            ("0" * 64, execution.execution_id),
        )
        connection.commit()
    with pytest.raises(
        ProviderObservationAuthoritySignatureError,
        match="HMAC column mismatch",
    ):
        ledger.load(execution.execution_id)


def test_malformed_and_noncanonical_rows_stay_inside_authority_error_domain(
    tmp_path: Path,
) -> None:
    execution = _execution()
    start = _start(execution)
    authority = _authority(execution)
    ledger = _ledger(tmp_path)
    ledger.bind_start(authority, start, bound_at=NOW)
    with contextlib.closing(sqlite3.connect(ledger.path)) as connection:
        connection.execute(
            "UPDATE provider_observation_bindings "
            "SET record_json=? WHERE execution_id=?",
            ('{"record_hmac_sha256":"bad"}', execution.execution_id),
        )
        connection.commit()
    with pytest.raises(ProviderObservationAuthorityStateError):
        ledger.load(execution.execution_id)


def test_future_expired_and_overlong_authority_refuse() -> None:
    execution = _execution()
    future = issue_provider_observation_authority(
        authority_id="authority.runtime-provider-observation",
        authority_key_id="provider-authority-key",
        authority_secret=AUTHORITY_KEY,
        binding_id="future-binding",
        provider_id="provider.external-fixture",
        observation_keyring=OBSERVATION_KEYRING,
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime-fixture",
        execution=execution,
        lease_sha256=LEASE_SHA,
        source_revision=REVISION,
        issued_at=NOW + timedelta(minutes=1),
        expires_at=NOW + timedelta(hours=1),
    )
    with pytest.raises(
        ProviderObservationAuthorityBindingError,
        match="not yet valid",
    ):
        verify_provider_observation_authority(
            future,
            authority_id="authority.runtime-provider-observation",
            authority_keyring=AUTHORITY_KEYRING,
            observation_keyring=OBSERVATION_KEYRING,
            entrypoint_id="provider.runtime-fixture",
            runtime_id="runtime-fixture",
            execution=execution,
            lease_sha256=LEASE_SHA,
            source_revision=REVISION,
            at=NOW,
        )

    expired = _authority(execution)
    with pytest.raises(
        ProviderObservationAuthorityBindingError,
        match="expired",
    ):
        verify_provider_observation_authority(
            expired,
            authority_id="authority.runtime-provider-observation",
            authority_keyring=AUTHORITY_KEYRING,
            observation_keyring=OBSERVATION_KEYRING,
            entrypoint_id="provider.runtime-fixture",
            runtime_id="runtime-fixture",
            execution=execution,
            lease_sha256=LEASE_SHA,
            source_revision=REVISION,
            at=NOW + timedelta(hours=2),
        )

    with pytest.raises(ValueError, match="lifetime"):
        issue_provider_observation_authority(
            authority_id="authority.runtime-provider-observation",
            authority_key_id="provider-authority-key",
            authority_secret=AUTHORITY_KEY,
            binding_id="overlong-binding",
            provider_id="provider.external-fixture",
            observation_keyring=OBSERVATION_KEYRING,
            entrypoint_id="provider.runtime-fixture",
            runtime_id="runtime-fixture",
            execution=execution,
            lease_sha256=LEASE_SHA,
            source_revision=REVISION,
            issued_at=NOW,
            expires_at=NOW + timedelta(hours=25),
        )


def _sqlite_handle_open(db) -> bool:
    """Whether any connection still holds this SQLite database open.

    NOTE the detector. This store keeps SQLite's default rollback journal --
    ``_connect`` here never sets ``journal_mode=WAL`` -- so a leaked connection
    produces NO ``-wal``/``-shm`` companion, and the companion probe used for
    the WAL-mode sibling stores is silently vacuous against this file. What is
    observable is the operating-system handle: on Windows an open SQLite handle
    blocks renaming the database.

    MEASURED on the pre-fix tree: companion absent in both directions, while
    the handle was open after ``__init__`` and after ``load``, and released by
    ``gc.collect()``.
    """

    database = Path(db)
    moved = database.with_suffix(database.suffix + ".rename-probe")
    try:
        os.rename(database, moved)
    except OSError:
        return True
    os.rename(moved, database)
    return False


def test_binding_ledger_closes_its_connections_and_the_schema_still_commits(
    tmp_path: Path,
) -> None:
    """Connection lifetime is a fact of the code, not of collector timing.

    ``_initialize`` and ``load`` used ``with self._connect() as connection``.
    For sqlite3 that is a TRANSACTION scope, not a closing scope: it commits
    and leaves the connection open. The leaked connection was unreachable
    garbage held in a reference cycle, so the file handle survived until the
    generational collector ran, at a moment decided by how much unrelated work
    the process had allocated.

    Deliberately no ``gc.collect()`` before the assertions -- collecting first
    finalizes the leak and hides the defect.

    The commit matters here more than at the sibling stores: unlike them,
    ``_connect`` does NOT pass ``isolation_level=None``, so this connection is
    in the implicit transaction mode where a dropped commit can genuinely
    discard a write. The reopened ledger below proves the schema survived.
    """

    ledger = _ledger(tmp_path)
    database = Path(ledger.path)
    assert not _sqlite_handle_open(database), "_initialize leaked"

    assert ledger.load("provider-observation-execution") is None
    assert not _sqlite_handle_open(database), "load leaked"

    execution = _execution()
    ledger.bind_start(_authority(execution), _start(execution), bound_at=NOW)
    assert not _sqlite_handle_open(database), "bind_start leaked"

    record = ledger.load(execution.execution_id)
    assert record is not None
    assert not _sqlite_handle_open(database), "load leaked after a write"

    # The CREATE TABLE and the bound row both had to be committed before their
    # connections were closed; a ledger that never owned those connections must
    # see them.
    reopened = _ledger(tmp_path)
    assert reopened.load(execution.execution_id) == record
