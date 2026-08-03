from __future__ import annotations

from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha
from daedalus.twin import FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.delta import (
    compute_graph_delta,
    parse_graph_delta,
    require_graph_delta,
)

REVISION = "a" * 40
CREATED_AT = "2026-08-03T14:00:00+00:00"


def _digest(label: str) -> str:
    return canonical_sha({"label": label})


def _snapshot() -> FourfoldSnapshot:
    planes = tuple(
        PlaneSnapshot(
            plane=name,
            source_revision=REVISION,
            status="complete",
            node_ids=(f"{name}:node",),
            evidence_sha256s=(_digest(f"{name}:evidence"),),
        )
        for name in ("code", "type", "data", "knowledge")
    )
    forest_sha256 = _digest("forest")
    provenance = ContractProvenance(
        origin="tests.graph-delta-exact-noop",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            forest_sha256,
            *(plane.digest for plane in planes),
        ),
        trace_id="exact-noop",
    )
    return FourfoldSnapshot(
        repository_id="exact-noop-fixture",
        source_revision=REVISION,
        source_forest_sha256=forest_sha256,
        planes=planes,
        bindings=(),
        provenance=provenance,
    )


def test_exact_snapshot_identity_produces_a_canonical_noop_delta() -> None:
    snapshot = _snapshot()

    delta = compute_graph_delta(
        snapshot,
        snapshot,
        created_at=CREATED_AT,
        trace_id="exact-noop",
    )

    assert delta.base_snapshot_sha256 == snapshot.digest
    assert delta.candidate_snapshot_sha256 == snapshot.digest
    assert delta.base_revision == REVISION
    assert delta.candidate_revision == REVISION
    assert delta.semantic_changed is False
    assert delta.evidence_changed is False
    assert delta.changed is False
    assert all(item.changed is False for item in delta.plane_deltas)
    assert delta.binding_deltas == ()
    assert delta.provenance.input_digests.count(snapshot.digest) == 1
    assert parse_graph_delta(delta.to_dict()) == delta
    require_graph_delta(delta, snapshot, snapshot)
