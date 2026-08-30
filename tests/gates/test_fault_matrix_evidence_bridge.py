# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The whole-matrix verdict reaches the release path only through the existing row.

The bridge maps a :class:`WholeRuntimeFaultMatrixVerdict` into the existing
``FaultMatrixEvidence`` release-path line and nothing else: the strict verifier's
``trusted_fault_matrix_sha256s`` check then binds exactly the matrix digest from
the verdict contract.  A development-key verdict is retained but marked and can
never claim closure through this path.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from daedalus.gates import strict_mechanical_blockers
from daedalus.gates.evidence import FaultMatrixEvidence, GateEvidenceIndex
from daedalus.gates.fault_matrix_binding import (
    PRODUCTION_KEY_CLASS,
    fault_matrix_evidence_from_verdict,
)
from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG
from daedalus.runtimes.whole_fault_matrix import WholeRuntimeFaultMatrixVerdict
from daedalus.schemas import ContractProvenance

REVISION = "a" * 40
TREE = "b" * 40
NOW = datetime(2026, 8, 17, 22, 0, 0, 766566, tzinfo=timezone.utc)
MATRIX_SHA = f"{9001:064x}"


def _verdict(
    *,
    key_class: str = PRODUCTION_KEY_CLASS,
    blockers: tuple[str, ...] = (),
    catalog_sha256: str | None = None,
) -> WholeRuntimeFaultMatrixVerdict:
    catalog_sha = RUNTIME_FAULT_CATALOG.digest if catalog_sha256 is None else catalog_sha256
    trusted = sorted(f"{index + 1:064x}" for index in range(2))
    attestations = sorted(f"{index + 1001:064x}" for index in range(2))
    grouped: dict[str, list[str]] = {}
    for blocker in sorted(blockers):
        grouped.setdefault(blocker.split(":", 1)[0], []).append(blocker)
    payload: dict[str, Any] = {
        "source_revision": REVISION,
        "catalog_sha256": catalog_sha,
        "catalog_scenarios": len(RUNTIME_FAULT_CATALOG.scenarios),
        "matrix_sha256": MATRIX_SHA,
        "observations": 2,
        "columns": {
            "deterministic-fixture": {
                "issuer_id": "issuer.fixture",
                "key_class": key_class,
                "observations": 2,
                "attestations": 2,
            }
        },
        "closed": not blockers,
        "blocker_count": len(blockers),
        "blockers_by_class": {name: sorted(rows) for name, rows in sorted(grouped.items())},
        "verification": {
            "fault_verification": {
                "matrix_sha256": MATRIX_SHA,
                "catalog_sha256": catalog_sha,
                "source_revision": REVISION,
                "trusted_observation_sha256s": trusted,
                "blockers": sorted(blockers),
                "closed": not blockers,
            },
            "attestation_sha256s": attestations,
            "verified_at": NOW.isoformat(),
            "closed": not blockers,
        },
    }
    return WholeRuntimeFaultMatrixVerdict.from_dict(payload)


def _bridge(verdict: WholeRuntimeFaultMatrixVerdict) -> FaultMatrixEvidence:
    return fault_matrix_evidence_from_verdict(
        verdict,
        matrix_id="gate0-whole-matrix",
        executed_at=NOW.isoformat(),
    )


def _index(row: FaultMatrixEvidence) -> GateEvidenceIndex:
    iron_sha = "7" * 64
    registry_sha = "8" * 64
    return GateEvidenceIndex(
        index_id="mission3-bridge-index",
        gate=0,
        source_revision=REVISION,
        source_tree_revision=TREE,
        iron_plan_sha256=iron_sha,
        registry_sha256=registry_sha,
        generated_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(days=1)).isoformat(),
        required_workflow_ids=("iron-plan",),
        required_artifact_kinds=("wheel",),
        required_runtime_ids=("claude-code-cli",),
        required_fault_matrix_ids=(row.matrix_id,),
        required_review_perspectives=("architecture",),
        workflows=(),
        artifacts=(),
        runtimes=(),
        fault_matrices=(row,),
        reviews=(),
        owner_decision=None,
        provenance=ContractProvenance(
            origin="tests.bridge-index",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=tuple(sorted({iron_sha, registry_sha, row.digest})),
        ),
    )


def test_a_closed_production_verdict_bridges_to_an_accepted_row() -> None:
    verdict = _verdict()
    row = _bridge(verdict)
    assert row.status == "passed"
    assert row.matrix_sha256 == verdict.matrix_sha256
    assert row.source_revision == verdict.source_revision
    assert row.scenario_ids == tuple(
        sorted(item.scenario_id for item in RUNTIME_FAULT_CATALOG.scenarios)
    )
    assert row.provenance.origin.endswith(PRODUCTION_KEY_CLASS)
    assert verdict.digest in row.provenance.input_digests
    assert verdict.catalog_sha256 in row.provenance.input_digests

    blockers = strict_mechanical_blockers(
        _index(row),
        current_revision=REVISION,
        current_tree_revision=TREE,
        now=NOW + timedelta(hours=1),
        trusted_fault_matrix_sha256s=(verdict.matrix_sha256,),
    )
    assert f"fault-matrix:{row.matrix_id}:untrusted-matrix" not in blockers
    assert f"fault-matrix:{row.matrix_id}:status-failed" not in blockers


def test_an_untrusted_matrix_digest_is_a_blocker() -> None:
    row = _bridge(_verdict())
    blockers = strict_mechanical_blockers(
        _index(row),
        current_revision=REVISION,
        current_tree_revision=TREE,
        now=NOW + timedelta(hours=1),
        trusted_fault_matrix_sha256s=(f"{4242:064x}",),
    )
    assert f"fault-matrix:{row.matrix_id}:untrusted-matrix" in blockers


def test_a_catalog_digest_mismatch_refuses_to_bridge() -> None:
    verdict = _verdict(catalog_sha256=f"{9002:064x}")
    with pytest.raises(ValueError, match="catalog digest does not match"):
        _bridge(verdict)


def test_a_development_key_verdict_is_marked_and_cannot_claim_closure() -> None:
    verdict = _verdict(key_class="development")
    assert verdict.closed is True  # closed, but not under production custody
    row = _bridge(verdict)
    assert row.status == "failed"
    assert "development" in row.provenance.origin
    assert PRODUCTION_KEY_CLASS not in row.provenance.origin

    blockers = strict_mechanical_blockers(
        _index(row),
        current_revision=REVISION,
        current_tree_revision=TREE,
        now=NOW + timedelta(hours=1),
        trusted_fault_matrix_sha256s=(verdict.matrix_sha256,),
    )
    assert f"fault-matrix:{row.matrix_id}:status-failed" in blockers


def test_an_open_production_verdict_does_not_claim_passed() -> None:
    verdict = _verdict(blockers=("fault.missing:runtime.live-envelope.expiry",))
    row = _bridge(verdict)
    assert row.status == "failed"


def test_non_verdict_input_is_refused() -> None:
    with pytest.raises(ValueError, match="exact whole-matrix verdict"):
        fault_matrix_evidence_from_verdict(
            "not-a-verdict",  # type: ignore[arg-type]
            matrix_id="gate0-whole-matrix",
            executed_at=NOW.isoformat(),
        )
