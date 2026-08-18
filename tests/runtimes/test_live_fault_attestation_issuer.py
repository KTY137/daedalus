"""The live-runtime issuer: one authority, one key, and refusal in both directions.

The three column issuers are siblings, not instances of one parameterised
issuer. The property that matters is mutual: this issuer must refuse the other
columns' rows, and the other issuers must refuse this one's. A test that only
checks one direction would still pass if the columns quietly shared a key.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.runtimes.fault_attestation_issuer import (
    FaultAttestationRefusal,
    LinuxHostFaultAttestationIssuer,
)
from daedalus.runtimes.fault_attestations import (
    RuntimeFaultAttestationBindingMismatch,
    verify_attested_runtime_fault_matrix,
)
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.fixture_fault_attestation_issuer import (
    FixtureFaultAttestationIssuer,
)
from daedalus.runtimes.live_fault_attestation_issuer import (
    LiveFaultAttestationBundle,
    LiveFaultAttestationIssuer,
    build_matrix_from_live_run_directory,
    issue_live_run_directory,
    load_live_fault_run,
)
from daedalus.runtimes.live_fault_collector import (
    retain_live_fault_run,
    run_live_fault_catalog,
)

REVISION = "e" * 40
NOW = datetime(2026, 8, 18, 8, 0, tzinfo=timezone.utc)
LIVE_KEY = b"live-column-secret-material-32-bytes-minimum!!"
OTHER_KEY = b"another-column-secret-material-32-bytes-min!!!"

FIXTURE_ROW = "runtime.broker.exact-replay-inert"
HOST_ROW = "runtime.process.timeout"
LIVE_ROW = "runtime.live-envelope.expiry"


def _live_run_dir(tmp_path: Path) -> Path:
    # The clock is frozen at NOW: the issuer rightly refuses an attestation
    # issued before its observation, so a fixture observed at wall-clock time
    # but issued at a pinned NOW would rot the moment real time passes NOW.
    run_dir = tmp_path / "live"
    for run in run_live_fault_catalog(
        catalog=RUNTIME_FAULT_CATALOG,
        source_revision=REVISION,
        executors={},
        clock=lambda: NOW,
    ):
        retain_live_fault_run(run_dir, run)
    return run_dir


def _issuer(issuer_id: str = "gate0-live-issuer") -> LiveFaultAttestationIssuer:
    return LiveFaultAttestationIssuer(
        issuer_id=issuer_id,
        key_id="gate0-live-key",
        secret=LIVE_KEY,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        validity=timedelta(hours=12),
    )


def test_every_retained_live_row_is_attested(tmp_path: Path) -> None:
    bundle = issue_live_run_directory(
        _live_run_dir(tmp_path),
        issuer=_issuer(),
        key_class="development",
        issued_at=NOW,
    )

    assert bundle.complete
    assert len(bundle.attestations) == 2
    assert all(row.authority == "live-runtime" for row in bundle.attestations)


def test_a_blocked_row_is_attested_unchanged(tmp_path: Path) -> None:
    """A signature means authentic, never passed."""

    run_dir = _live_run_dir(tmp_path)
    bundle = issue_live_run_directory(
        run_dir, issuer=_issuer(), key_class="development", issued_at=NOW
    )
    matrix = build_matrix_from_live_run_directory(
        run_dir, catalog=RUNTIME_FAULT_CATALOG, source_revision=REVISION
    )
    verification = verify_attested_runtime_fault_matrix(
        matrix,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
        attestations=bundle.attestations,
        keyring={(row.issuer_id, row.key_id): LIVE_KEY for row in bundle.attestations},
        issuer_authorities={"gate0-live-issuer": ("live-runtime",)},
        now=NOW,
    )

    assert not verification.closed
    assert any(blocker.startswith("fault.blocked") for blocker in verification.blockers)


def test_the_live_issuer_refuses_the_other_columns_rows() -> None:
    issuer = _issuer()

    for foreign in (FIXTURE_ROW, HOST_ROW):
        with pytest.raises(FaultAttestationRefusal) as excinfo:
            issuer._scenario(foreign)
        assert excinfo.value.reason == "refusal.foreign-authority"


def test_the_other_issuers_refuse_the_live_rows() -> None:
    """The other direction: a live row cannot be signed by a sibling column."""

    fixture_issuer = FixtureFaultAttestationIssuer(
        issuer_id="gate0-fixture-issuer",
        key_id="gate0-fixture-key",
        secret=OTHER_KEY,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
    )
    host_issuer = LinuxHostFaultAttestationIssuer(
        issuer_id="gate0-host-issuer",
        key_id="gate0-host-key",
        secret=OTHER_KEY,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision=REVISION,
    )

    for issuer in (fixture_issuer, host_issuer):
        with pytest.raises(FaultAttestationRefusal) as excinfo:
            issuer._scenario(LIVE_ROW)
        assert excinfo.value.reason == "refusal.foreign-authority"


def test_a_live_bundle_refuses_a_foreign_authority_attestation(tmp_path: Path) -> None:
    bundle = issue_live_run_directory(
        _live_run_dir(tmp_path),
        issuer=_issuer(),
        key_class="development",
        issued_at=NOW,
    )
    foreign = bundle.attestations[0].to_dict()
    foreign["authority"] = "linux-host"

    with pytest.raises(ValueError, match="must only carry live-runtime"):
        LiveFaultAttestationBundle(
            schema="daedalus-live-runtime-fault-attestation-bundle/1",
            issuer_id=bundle.issuer_id,
            key_id=bundle.key_id,
            key_class=bundle.key_class,
            key_sha256=bundle.key_sha256,
            catalog_sha256=bundle.catalog_sha256,
            source_revision=bundle.source_revision,
            issued_at=bundle.issued_at,
            attestations=(type(bundle.attestations[0]).from_dict(foreign),),
            refusals=(),
        )


def test_verification_refuses_a_live_row_scoped_to_another_column(
    tmp_path: Path,
) -> None:
    """The scoping is enforced again at verification, not only at issuance."""

    run_dir = _live_run_dir(tmp_path)
    bundle = issue_live_run_directory(
        run_dir, issuer=_issuer(), key_class="development", issued_at=NOW
    )
    matrix = build_matrix_from_live_run_directory(
        run_dir, catalog=RUNTIME_FAULT_CATALOG, source_revision=REVISION
    )

    with pytest.raises(
        RuntimeFaultAttestationBindingMismatch, match="not authorized for the observation"
    ):
        verify_attested_runtime_fault_matrix(
            matrix,
            catalog=RUNTIME_FAULT_CATALOG,
            expected_source_revision=REVISION,
            attestations=bundle.attestations,
            keyring={
                (row.issuer_id, row.key_id): LIVE_KEY for row in bundle.attestations
            },
            issuer_authorities={"gate0-live-issuer": ("deterministic-fixture",)},
            now=NOW,
        )


def test_a_run_from_another_revision_is_refused(tmp_path: Path) -> None:
    run_dir = _live_run_dir(tmp_path)
    issuer = LiveFaultAttestationIssuer(
        issuer_id="gate0-live-issuer",
        key_id="gate0-live-key",
        secret=LIVE_KEY,
        catalog=RUNTIME_FAULT_CATALOG,
        expected_source_revision="f" * 40,
    )
    bundle = issue_live_run_directory(
        run_dir, issuer=issuer, key_class="development", issued_at=NOW
    )

    assert not bundle.complete
    assert {row.reason for row in bundle.refusals} == {"refusal.stale-revision"}


def test_key_class_is_recorded_and_never_inferred(tmp_path: Path) -> None:
    run_dir = _live_run_dir(tmp_path)
    development = issue_live_run_directory(
        run_dir, issuer=_issuer(), key_class="development", issued_at=NOW
    )
    production = issue_live_run_directory(
        run_dir, issuer=_issuer(), key_class="production", issued_at=NOW
    )

    assert development.key_class == "development"
    assert development.production_key_material is False
    assert production.production_key_material is True
    # Identical rows, different custody claim: the digest must record that.
    assert development.digest != production.digest


def test_a_retained_run_revalidates_its_own_binding(tmp_path: Path) -> None:
    run_dir = _live_run_dir(tmp_path)
    run = load_live_fault_run(run_dir, LIVE_ROW)

    assert run.observation.scenario_id == LIVE_ROW
    assert run.observation.evidence_sha256 == run.evidence.digest

    (run_dir / f"{LIVE_ROW}.raw").write_bytes(b'{"tampered":true}')
    with pytest.raises(FaultAttestationRefusal) as excinfo:
        load_live_fault_run(run_dir, LIVE_ROW)
    assert excinfo.value.reason == "refusal.run-binding-mismatch"
