from __future__ import annotations

import pytest

from daedalus.twin import PlaneSnapshot

REVISION = "a" * 40
EVIDENCE = ("1" * 64,)


def _partial_code_plane(node_ids) -> PlaneSnapshot:
    return PlaneSnapshot(
        plane="code",
        source_revision=REVISION,
        status="partial",
        node_ids=node_ids,
        evidence_sha256s=EVIDENCE,
        reason="fixture",
    )


def test_plane_snapshot_reuses_exact_canonical_node_id_tuple():
    canonical = ("a.py", "m.py", "z.py")

    plane = _partial_code_plane(canonical)

    assert plane.node_ids is canonical


def test_plane_snapshot_sorts_unsorted_nodes_and_rejects_nonadjacent_duplicate():
    assert _partial_code_plane(("z.py", "a.py", "m.py")).node_ids == (
        "a.py",
        "m.py",
        "z.py",
    )

    with pytest.raises(ValueError, match="must not contain duplicates"):
        _partial_code_plane(("z.py", "a.py", "z.py"))
