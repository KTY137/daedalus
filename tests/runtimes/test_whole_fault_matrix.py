"""The whole-matrix verdict is a contract, not a summary someone can retype."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from daedalus.runtimes.whole_fault_matrix import (
    FaultAttestationBundle,
    WholeMatrixColumn,
    WholeRuntimeFaultMatrixError,
    WholeRuntimeFaultMatrixVerdict,
    catalog_authorities,
    discover_whole_matrix_verdicts,
    load_whole_matrix_verdict,
    verify_whole_runtime_fault_matrix,
)
from daedalus.spine.envelope import canonical_json


ROOT = Path(__file__).resolve().parents[2]
LANDED_DIR = ROOT / "runs" / "gate0-matrix-2026-08-17"
LANDED = LANDED_DIR / "whole-matrix-verdict.json"
REVISION = "a" * 40

# The mutation sandbox copies daedalus/, tests/ and configs/ only, so the landed
# evidence bundle is absent there.  The contract tests below must still run in
# it -- they are what kills a mutated verdict parser -- so only the three tests
# that read the landed artifact stand down when it is not in the checkout.
needs_landed_evidence = pytest.mark.skipif(
    not LANDED.is_file(),
    reason="the landed gate0 matrix evidence bundle is not present in this checkout",
)


def _digest(seed: int) -> str:
    return f"{seed:064x}"


def _payload(
    *,
    blockers: tuple[str, ...] = (),
    trusted: int = 2,
    key_class: str = "production",
    revision: str = REVISION,
    columns: dict[str, Any] | None = None,
) -> dict[str, Any]:
    trusted_rows = [_digest(index + 1) for index in range(trusted)]
    attestation_rows = [_digest(index + 1001) for index in range(trusted)]
    fault_verification = {
        "matrix_sha256": _digest(9001),
        "catalog_sha256": _digest(9002),
        "source_revision": revision,
        "trusted_observation_sha256s": sorted(trusted_rows),
        "blockers": sorted(blockers),
        "closed": not blockers,
    }
    grouped: dict[str, list[str]] = {}
    for blocker in sorted(blockers):
        grouped.setdefault(blocker.split(":", 1)[0], []).append(blocker)
    if columns is None:
        columns = {
            "deterministic-fixture": {
                "issuer_id": "issuer.fixture",
                "key_class": key_class,
                "observations": trusted,
                "attestations": trusted,
            }
        }
    verdict = {
        "source_revision": revision,
        "catalog_sha256": _digest(9002),
        "catalog_scenarios": 24,
        "matrix_sha256": _digest(9001),
        "observations": sum(column["observations"] for column in columns.values()),
        "columns": columns,
        "closed": not blockers,
        "blocker_count": len(blockers),
        "blockers_by_class": {name: sorted(rows) for name, rows in sorted(grouped.items())},
        "verification": {
            "fault_verification": fault_verification,
            "attestation_sha256s": sorted(attestation_rows),
            "verified_at": "2026-08-17T20:46:48.766566+00:00",
            "closed": not blockers,
        },
    }
    return verdict


@needs_landed_evidence
def test_landed_verdict_round_trips_byte_for_byte() -> None:
    verdict = load_whole_matrix_verdict(LANDED)
    assert canonical_json(verdict.to_dict()) + "\n" == LANDED.read_text(encoding="utf-8")
    assert verdict.closed is False
    assert verdict.blocker_count == 6
    assert verdict.key_classes == ("development",)
    assert verdict.production_key_material is False
    assert set(verdict.blockers_by_class) == {"fault.blocked", "fault.missing"}
    assert len(verdict.blockers_by_class["fault.blocked"]) == 4
    assert len(verdict.blockers_by_class["fault.missing"]) == 2


def test_a_clean_synthetic_verdict_is_accepted_and_closed() -> None:
    verdict = WholeRuntimeFaultMatrixVerdict.from_dict(_payload())
    assert verdict.closed is True
    assert verdict.production_key_material is True
    assert verdict.blocker_count == 0


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("blocker_count", 0, "blocker count"),
        ("closed", True, "closed flag"),
        ("observations", 99, "observation count"),
        ("catalog_scenarios", 0, "positive"),
    ),
)
def test_retyped_derived_fields_are_refused(field: str, value: Any, match: str) -> None:
    payload = _payload(blockers=("fault.missing:runtime.live-envelope.expiry",))
    payload[field] = value
    with pytest.raises(WholeRuntimeFaultMatrixError, match=match):
        WholeRuntimeFaultMatrixVerdict.from_dict(payload)


def test_a_dropped_blocker_class_is_refused() -> None:
    payload = _payload(
        blockers=(
            "fault.blocked:runtime.process.oom",
            "fault.missing:runtime.live-envelope.expiry",
        )
    )
    payload["blockers_by_class"].pop("fault.blocked")
    with pytest.raises(WholeRuntimeFaultMatrixError, match="blocker classes"):
        WholeRuntimeFaultMatrixVerdict.from_dict(payload)


def test_a_rewritten_blocker_row_is_refused() -> None:
    payload = _payload(blockers=("fault.missing:runtime.live-envelope.expiry",))
    payload["blockers_by_class"]["fault.missing"] = ["fault.missing:something-else"]
    with pytest.raises(WholeRuntimeFaultMatrixError, match="blocker class"):
        WholeRuntimeFaultMatrixVerdict.from_dict(payload)


def test_closed_cannot_be_flipped_inside_the_verification() -> None:
    payload = _payload(blockers=("fault.missing:runtime.live-envelope.expiry",))
    payload["verification"]["fault_verification"]["closed"] = True
    with pytest.raises(WholeRuntimeFaultMatrixError, match="closed flag"):
        WholeRuntimeFaultMatrixVerdict.from_dict(payload)


def test_the_outer_verification_closed_flag_is_checked_too() -> None:
    payload = _payload(blockers=("fault.missing:runtime.live-envelope.expiry",))
    payload["verification"]["closed"] = True
    with pytest.raises(WholeRuntimeFaultMatrixError, match="closed flag"):
        WholeRuntimeFaultMatrixVerdict.from_dict(payload)


def test_verdict_identity_must_agree_with_its_own_verification() -> None:
    payload = _payload()
    payload["matrix_sha256"] = _digest(4242)
    with pytest.raises(WholeRuntimeFaultMatrixError, match="matrix digest"):
        WholeRuntimeFaultMatrixVerdict.from_dict(payload)


def test_attestation_count_must_agree_with_the_columns() -> None:
    payload = _payload()
    payload["columns"]["deterministic-fixture"]["attestations"] = 7
    with pytest.raises(WholeRuntimeFaultMatrixError, match="attestation count"):
        WholeRuntimeFaultMatrixVerdict.from_dict(payload)


def test_two_columns_may_not_share_one_issuer_identity() -> None:
    columns = {
        "deterministic-fixture": {
            "issuer_id": "issuer.shared",
            "key_class": "production",
            "observations": 1,
            "attestations": 1,
        },
        "linux-host": {
            "issuer_id": "issuer.shared",
            "key_class": "production",
            "observations": 1,
            "attestations": 1,
        },
    }
    payload = _payload(trusted=2, columns=columns)
    with pytest.raises(WholeRuntimeFaultMatrixError, match="issuer identity"):
        WholeRuntimeFaultMatrixVerdict.from_dict(payload)


def test_an_unknown_authority_is_refused() -> None:
    columns = {
        "windows-host": {
            "issuer_id": "issuer.windows",
            "key_class": "production",
            "observations": 2,
            "attestations": 2,
        }
    }
    with pytest.raises(WholeRuntimeFaultMatrixError, match="unknown collector authority"):
        WholeRuntimeFaultMatrixVerdict.from_dict(_payload(columns=columns))


def test_extra_and_missing_fields_are_refused() -> None:
    payload = _payload()
    payload["extra"] = 1
    with pytest.raises(WholeRuntimeFaultMatrixError, match="fields are not exact"):
        WholeRuntimeFaultMatrixVerdict.from_dict(payload)
    payload = _payload()
    payload.pop("catalog_sha256")
    with pytest.raises(WholeRuntimeFaultMatrixError, match="fields are not exact"):
        WholeRuntimeFaultMatrixVerdict.from_dict(payload)


def test_unreadable_and_malformed_artifacts_are_refused(tmp_path: Path) -> None:
    with pytest.raises(WholeRuntimeFaultMatrixError, match="could not be read"):
        load_whole_matrix_verdict(tmp_path / "absent.json")
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(WholeRuntimeFaultMatrixError, match="malformed JSON"):
        load_whole_matrix_verdict(broken)
    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(WholeRuntimeFaultMatrixError, match="must be an object"):
        load_whole_matrix_verdict(array)


@needs_landed_evidence
def test_discovery_finds_the_landed_bundle_and_nothing_else() -> None:
    found = discover_whole_matrix_verdicts(ROOT)
    assert LANDED in found


def test_the_combiner_refuses_a_shared_issuer_or_authority(tmp_path: Path) -> None:
    authorities = sorted(catalog_authorities())
    shared = FaultAttestationBundle(
        authority=authorities[0], issuer_id="issuer.one", key_class="development",
        attestations=(),
    )
    other = FaultAttestationBundle(
        authority=authorities[0], issuer_id="issuer.two", key_class="development",
        attestations=(),
    )
    now = datetime.now(timezone.utc)
    with pytest.raises(WholeRuntimeFaultMatrixError, match="issuer identity"):
        verify_whole_runtime_fault_matrix(
            fixture_run_dir=tmp_path, fixture_bundle=shared, fixture_secret=b"x",
            host_run_dir=tmp_path, host_bundle=shared, host_secret=b"y",
            source_revision=REVISION, now=now,
        )
    with pytest.raises(WholeRuntimeFaultMatrixError, match="same authority"):
        verify_whole_runtime_fault_matrix(
            fixture_run_dir=tmp_path, fixture_bundle=shared, fixture_secret=b"x",
            host_run_dir=tmp_path, host_bundle=other, host_secret=b"y",
            source_revision=REVISION, now=now,
        )


@needs_landed_evidence
def test_a_column_cannot_hold_a_foreign_issuers_attestation() -> None:
    landed = json.loads(
        (LANDED_DIR / "fixture-attestations.json").read_text(
            encoding="utf-8"
        )
    )
    from daedalus.runtimes.fault_attestations import RuntimeFaultAttestation

    rows = tuple(RuntimeFaultAttestation.from_dict(row) for row in landed["attestations"])
    with pytest.raises(WholeRuntimeFaultMatrixError, match="bundle issuer identity"):
        FaultAttestationBundle(
            authority="deterministic-fixture",
            issuer_id="issuer.someone-else",
            key_class="development",
            attestations=rows,
        )


@needs_landed_evidence
def test_the_promoted_combiner_reproduces_the_landed_verdict_from_the_observations() -> None:
    """Independently minted keys must reach the same matrix identity and blockers.

    The original run's two development secrets are not retained, so the landed
    signatures cannot be recomputed.  What the combiner claims to derive from the
    retained observations -- matrix identity, trusted set, blocker set -- must
    nonetheless come out identical when the same observations are re-attested
    under keys chosen here.  If it did not, the promoted module would not be the
    thing that produced the evidence the gate report now binds.
    """

    from datetime import timedelta

    from daedalus.runtimes.fault_attestation_issuer import (
        build_matrix_from_run_directory,
    )
    from daedalus.runtimes.fault_attestations import issue_runtime_fault_attestation
    from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
    from daedalus.runtimes.fixture_fault_attestation_issuer import (
        build_matrix_from_fixture_run_directory,
    )

    landed_revision = "c93191fef4a89de316529d22d54713acebeae097"
    now = datetime.now(timezone.utc)
    catalog = RUNTIME_FAULT_CATALOG
    fixture_secret = b"replay-secret-one" * 4
    host_secret = b"replay-secret-two" * 4

    def _bundle(matrix, authority: str, issuer: str, key: str, secret: bytes):
        return FaultAttestationBundle(
            authority=authority,
            issuer_id=issuer,
            key_class="development",
            attestations=tuple(
                issue_runtime_fault_attestation(
                    observation,
                    catalog=catalog,
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

    fixture_matrix = build_matrix_from_fixture_run_directory(
        LANDED_DIR / "fixture", catalog=catalog, source_revision=landed_revision
    )
    host_matrix = build_matrix_from_run_directory(
        LANDED_DIR / "linux-host", catalog=catalog, source_revision=landed_revision
    )
    replay = verify_whole_runtime_fault_matrix(
        fixture_run_dir=LANDED_DIR / "fixture",
        fixture_bundle=_bundle(
            fixture_matrix, "deterministic-fixture", "issuer.replay-fixture", "k1",
            fixture_secret,
        ),
        fixture_secret=fixture_secret,
        host_run_dir=LANDED_DIR / "linux-host",
        host_bundle=_bundle(
            host_matrix, "linux-host", "issuer.replay-host", "k2", host_secret
        ),
        host_secret=host_secret,
        source_revision=landed_revision,
        now=now,
    )
    landed = load_whole_matrix_verdict(LANDED)
    assert replay.matrix_sha256 == landed.matrix_sha256
    assert replay.blockers == landed.blockers
    assert (
        replay.verification.trusted_observation_sha256s
        == landed.verification.trusted_observation_sha256s
    )
    assert replay.observations == landed.observations
    assert replay.closed is landed.closed is False


def test_a_column_row_count_must_be_a_real_integer() -> None:
    with pytest.raises(WholeRuntimeFaultMatrixError, match="non-negative integer"):
        WholeMatrixColumn(
            authority="deterministic-fixture",
            issuer_id="issuer.fixture",
            key_class="development",
            observations=-1,
            attestations=0,
        )
