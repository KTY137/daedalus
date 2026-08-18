"""The whole matrix with its third column present.

The point of this file is one comparison: assembled without the live column the
verdict carries ``fault.missing`` for both live rows; assembled with it, those
two rows carry real observations instead. Whether they then pass or block is the
run's business -- but they stop being absent, which is what "complete fault
matrix" asks for.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.runtimes.fault_attestation_issuer import build_matrix_from_run_directory
from daedalus.runtimes.fault_attestations import issue_runtime_fault_attestation
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.fixture_fault_attestation_issuer import (
    build_matrix_from_fixture_run_directory,
)
from daedalus.runtimes.live_fault_attestation_issuer import (
    build_matrix_from_live_run_directory,
)
from daedalus.runtimes.live_fault_collector import (
    retain_live_fault_run,
    run_live_fault_catalog,
)
from daedalus.runtimes.whole_fault_matrix import (
    FaultAttestationBundle,
    WholeRuntimeFaultMatrixError,
    verify_whole_runtime_fault_matrix,
)

ROOT = Path(__file__).resolve().parents[2]
LANDED_DIR = ROOT / "runs" / "gate0-matrix-2026-08-17"
LANDED_REVISION = "c93191fef4a89de316529d22d54713acebeae097"

FIXTURE_SECRET = b"live-column-fixture-secret" * 2
HOST_SECRET = b"live-column-host-secret-xxxx" * 2
LIVE_SECRET = b"live-column-live-secret-xxxx" * 2

LIVE_ROWS = (
    "runtime.live-envelope.expiry",
    "runtime.live-envelope.binary-drift",
)

needs_landed_evidence = pytest.mark.skipif(
    not (LANDED_DIR / "fixture").is_dir(),
    reason="the landed gate0 matrix evidence bundle is not present in this checkout",
)


def _live_run_dir(tmp_path: Path, revision: str = LANDED_REVISION) -> Path:
    run_dir = tmp_path / "live"
    for run in run_live_fault_catalog(
        catalog=RUNTIME_FAULT_CATALOG, source_revision=revision, executors={}
    ):
        retain_live_fault_run(run_dir, run)
    return run_dir


def _bundle(matrix, authority: str, issuer: str, key: str, secret: bytes, now):
    return FaultAttestationBundle(
        authority=authority,
        issuer_id=issuer,
        key_class="development",
        attestations=tuple(
            issue_runtime_fault_attestation(
                observation,
                catalog=RUNTIME_FAULT_CATALOG,
                attestation_id=f"{issuer}.{observation.scenario_id}",
                issuer_id=issuer,
                key_id=key,
                nonce=f"nonce-{observation.scenario_id}",
                issued_at=now,
                expires_at=now + timedelta(days=1),
                secret=secret,
            )
            for observation in matrix.observations
        ),
    )


def _columns(tmp_path: Path, *, with_live: bool):
    # The live collector stamps its observations with the wall clock, so the
    # attestation instant has to be taken after the run exists -- an issuance
    # that predates its own observation is refused, and rightly so.
    live_dir = _live_run_dir(tmp_path) if with_live else None
    now = datetime.now(timezone.utc) + timedelta(seconds=1)

    fixture_matrix = build_matrix_from_fixture_run_directory(
        LANDED_DIR / "fixture", catalog=RUNTIME_FAULT_CATALOG, source_revision=LANDED_REVISION
    )
    host_matrix = build_matrix_from_run_directory(
        LANDED_DIR / "linux-host", catalog=RUNTIME_FAULT_CATALOG, source_revision=LANDED_REVISION
    )
    kwargs = dict(
        fixture_run_dir=LANDED_DIR / "fixture",
        fixture_bundle=_bundle(
            fixture_matrix, "deterministic-fixture", "issuer.lc-fixture", "k1",
            FIXTURE_SECRET, now,
        ),
        fixture_secret=FIXTURE_SECRET,
        host_run_dir=LANDED_DIR / "linux-host",
        host_bundle=_bundle(
            host_matrix, "linux-host", "issuer.lc-host", "k2", HOST_SECRET, now
        ),
        host_secret=HOST_SECRET,
        source_revision=LANDED_REVISION,
        now=now,
    )
    if live_dir is not None:
        live_matrix = build_matrix_from_live_run_directory(
            live_dir, catalog=RUNTIME_FAULT_CATALOG, source_revision=LANDED_REVISION
        )
        kwargs.update(
            live_run_dir=live_dir,
            live_bundle=_bundle(
                live_matrix, "live-runtime", "issuer.lc-live", "k3", LIVE_SECRET, now
            ),
            live_secret=LIVE_SECRET,
        )
    return kwargs


@needs_landed_evidence
def test_without_the_live_column_both_rows_are_missing(tmp_path: Path) -> None:
    verdict = verify_whole_runtime_fault_matrix(**_columns(tmp_path, with_live=False))

    assert len(verdict.columns) == 2
    missing = set(verdict.blockers_by_class.get("fault.missing", ()))
    assert missing == {f"fault.missing:{row}" for row in LIVE_ROWS}


@needs_landed_evidence
def test_with_the_live_column_the_rows_become_observations(tmp_path: Path) -> None:
    verdict = verify_whole_runtime_fault_matrix(**_columns(tmp_path, with_live=True))

    assert len(verdict.columns) == 3
    assert {column.authority for column in verdict.columns} == {
        "deterministic-fixture",
        "linux-host",
        "live-runtime",
    }
    # The decisive change: no live row is absent any more.
    missing = set(verdict.blockers_by_class.get("fault.missing", ()))
    assert not any(f"fault.missing:{row}" in missing for row in LIVE_ROWS)
    # They are observed and, on a host without live evidence, honestly blocked.
    blocked = set(verdict.blockers_by_class.get("fault.blocked", ()))
    assert {f"fault.blocked:{row}" for row in LIVE_ROWS} <= blocked

    live_column = next(
        column for column in verdict.columns if column.authority == "live-runtime"
    )
    assert live_column.observations == 2
    assert live_column.attestations == 2
    assert live_column.key_class == "development"
    assert verdict.production_key_material is False


@needs_landed_evidence
def test_the_live_column_needs_its_whole_triple(tmp_path: Path) -> None:
    kwargs = _columns(tmp_path, with_live=True)
    kwargs.pop("live_secret")

    with pytest.raises(WholeRuntimeFaultMatrixError, match="together"):
        verify_whole_runtime_fault_matrix(**kwargs)


@needs_landed_evidence
def test_three_columns_may_not_share_one_issuer(tmp_path: Path) -> None:
    kwargs = _columns(tmp_path, with_live=True)
    live_bundle = kwargs["live_bundle"]
    kwargs["live_bundle"] = FaultAttestationBundle(
        authority=live_bundle.authority,
        issuer_id=kwargs["host_bundle"].issuer_id,
        key_class=live_bundle.key_class,
        attestations=(),
    )

    with pytest.raises(WholeRuntimeFaultMatrixError, match="issuer identity"):
        verify_whole_runtime_fault_matrix(**kwargs)


def test_the_live_column_observes_exactly_the_catalogs_live_rows(tmp_path: Path) -> None:
    live_dir = _live_run_dir(tmp_path, revision="a" * 40)
    matrix = build_matrix_from_live_run_directory(
        live_dir, catalog=RUNTIME_FAULT_CATALOG, source_revision="a" * 40
    )

    assert {row.scenario_id for row in matrix.observations} == set(LIVE_ROWS)
    assert all(row.authority == "live-runtime" for row in matrix.observations)
