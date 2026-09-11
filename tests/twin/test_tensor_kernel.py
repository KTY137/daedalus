from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.twin.tensor import (
    MAX_TENSOR_AXES,
    SparseTensorEntry,
    TensorAxis,
    TensorView,
    parse_tensor_view,
)

REVISION = "a" * 40
FOREST = "b" * 64
FOURFOLD = "c" * 64
NOW = "2026-08-30T01:00:00Z"
ROOT = Path(__file__).resolve().parents[2]


def provenance() -> ContractProvenance:
    return ContractProvenance(
        origin="test.tensor",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(FOREST, FOURFOLD),
        trace_id="tensor-contract-test",
    )


def entry(node: str, plane: str, *, value: float = 1.0, evidence: str = "d") -> SparseTensorEntry:
    return SparseTensorEntry(
        coordinates=(("plane", plane), ("node", node)),
        relation="membership",
        value=value,
        evidence_sha256s=(evidence * 64,),
    )


def view(*, reverse: bool = False, status: str = "complete", reason: str = "") -> TensorView:
    axes = [
        TensorAxis("plane", ("knowledge", "code")),
        TensorAxis("node", ("src/b.py", "src/a.py")),
    ]
    entries = [entry("src/a.py", "code"), entry("src/b.py", "knowledge", evidence="e")]
    if reverse:
        axes.reverse()
        entries.reverse()
        entries = [
            SparseTensorEntry(
                coordinates=tuple(reversed(item.coordinates)),
                relation=item.relation,
                value=item.value,
                masked=item.masked,
                evidence_sha256s=tuple(reversed(item.evidence_sha256s)),
            )
            for item in entries
        ]
    return TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=FOREST,
        source_fourfold_sha256=FOURFOLD,
        status=status,
        axes=tuple(axes),
        entries=tuple(entries),
        provenance=provenance(),
        reason=reason,
    )


def test_input_order_is_canonical_and_digest_stable() -> None:
    first = view()
    second = view(reverse=True)

    assert first == second
    assert first.to_json() == second.to_json()
    assert first.digest == second.digest
    assert tuple(axis.name for axis in first.axes) == ("node", "plane")
    assert first.axes[0].labels == ("src/a.py", "src/b.py")
    assert first.axes[1].labels == ("code", "knowledge")
    assert first.shape == (2, 2)


def test_tensor_view_does_not_expose_parallel_axis_mapping_view() -> None:
    tensor = view()

    assert not hasattr(tensor, "axis_map")
    assert tuple(axis.name for axis in tensor.axes) == ("node", "plane")


def test_sparse_entry_does_not_expose_parallel_coordinate_mapping_view() -> None:
    item = entry("src/a.py", "code")

    assert not hasattr(item, "coordinate_map")
    assert item.coordinates == (("node", "src/a.py"), ("plane", "code"))


def test_entry_validation_and_sorting_share_canonical_label_index() -> None:
    tensor = TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=FOREST,
        source_fourfold_sha256=FOURFOLD,
        status="complete",
        axes=(
            TensorAxis("plane", ("knowledge", "code")),
            TensorAxis("node", ("src/c.py", "src/a.py", "src/b.py")),
        ),
        entries=(
            entry("src/c.py", "knowledge", evidence="f"),
            entry("src/b.py", "code", evidence="e"),
            entry("src/a.py", "code"),
        ),
        provenance=provenance(),
    )

    assert tuple(item.coordinates[0][1] for item in tensor.entries) == (
        "src/a.py",
        "src/b.py",
        "src/c.py",
    )
    assert tuple(tensor.index_coordinate(item) for item in tensor.entries) == (
        (0, 0),
        (1, 0),
        (2, 1),
    )


def test_sparse_entries_have_named_coordinates_and_deterministic_integer_projection() -> None:
    tensor = view()
    selected = tensor.select(node="src/a.py")

    assert len(selected) == 1
    assert selected[0].coordinates == (("node", "src/a.py"), ("plane", "code"))
    assert tensor.index_coordinate(selected[0]) == (0, 0)
    assert tensor.select(plane="knowledge") == (tensor.entries[1],)
    assert tensor.select(node="src/a.py", plane="code") == (tensor.entries[0],)
    assert tensor.select(node="src/a.py", plane="knowledge") == ()

    with pytest.raises(ValueError, match="unknown tensor axis"):
        tensor.select(missing="x")
    with pytest.raises(ValueError, match="not declared"):
        tensor.select(node="src/missing.py")


def test_duplicate_or_incomplete_coordinates_refuse() -> None:
    duplicate = SparseTensorEntry(
        coordinates=(("node", "src/a.py"), ("plane", "code")),
        relation="membership",
        value=2.0,
        evidence_sha256s=("f" * 64,),
    )
    first = view().entries[0]

    with pytest.raises(ValueError, match="repeat a coordinate/relation"):
        TensorView(
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            source_forest_sha256=FOREST,
            source_fourfold_sha256=FOURFOLD,
            status="complete",
            axes=view().axes,
            entries=(first, duplicate),
            provenance=provenance(),
        )

    missing_axis = SparseTensorEntry(
        coordinates=(("node", "src/a.py"),),
        relation="membership",
        evidence_sha256s=("d" * 64,),
    )
    with pytest.raises(ValueError, match="exactly the TensorView axes"):
        TensorView(
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            source_forest_sha256=FOREST,
            source_fourfold_sha256=FOURFOLD,
            status="complete",
            axes=view().axes,
            entries=(missing_axis,),
            provenance=provenance(),
        )

    with pytest.raises(ValueError, match="every axis at most once"):
        SparseTensorEntry(
            coordinates=(("node", "src/a.py"), ("node", "src/b.py")),
            relation="membership",
            evidence_sha256s=("d" * 64,),
        )


def test_unknown_labels_and_non_finite_values_refuse() -> None:
    unknown = SparseTensorEntry(
        coordinates=(("node", "src/missing.py"), ("plane", "code")),
        relation="membership",
        evidence_sha256s=("d" * 64,),
    )
    with pytest.raises(ValueError, match="is not declared by axis"):
        TensorView(
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            source_forest_sha256=FOREST,
            source_fourfold_sha256=FOURFOLD,
            status="complete",
            axes=view().axes,
            entries=(unknown,),
            provenance=provenance(),
        )

    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError, match="finite number"):
            entry("src/a.py", "code", value=bad)


def test_projection_status_is_explicit_and_never_changes_source_plane_status() -> None:
    absent = TensorView(
        repository_id="KTY137/daedalus",
        source_revision=REVISION,
        source_forest_sha256=FOREST,
        source_fourfold_sha256=FOURFOLD,
        status="absent",
        axes=(),
        entries=(),
        provenance=provenance(),
        reason="source semantics are unsupported by this projection",
    )
    assert absent.status == "absent"
    assert absent.reason

    with pytest.raises(ValueError, match="absent tensor must retain a reason"):
        TensorView(
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            source_forest_sha256=FOREST,
            source_fourfold_sha256=FOURFOLD,
            status="absent",
            axes=(),
            entries=(),
            provenance=provenance(),
        )

    with pytest.raises(ValueError, match="partial tensor must explain"):
        view(status="partial")

    partial = view(status="partial", reason="knowledge relation adapter not implemented")
    assert partial.status == "partial"
    assert partial.reason

    with pytest.raises(ValueError, match="complete tensor must not carry"):
        view(reason="pretend limitation")


def test_contract_round_trip_is_strict_and_binds_exact_sources() -> None:
    tensor = view()
    parsed = parse_tensor_view(tensor.to_dict())

    assert parsed == tensor
    assert parsed.digest == tensor.digest

    malformed = tensor.to_dict()
    malformed["pretend_authoritative"] = True
    with pytest.raises(ValueError, match="unknown field"):
        parse_tensor_view(malformed)

    wrong_provenance = ContractProvenance(
        origin="test.tensor",
        source_revision="9" * 40,
        created_at=NOW,
        input_digests=(FOREST, FOURFOLD),
    )
    with pytest.raises(ValueError, match="must match provenance"):
        TensorView(
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            source_forest_sha256=FOREST,
            source_fourfold_sha256=FOURFOLD,
            status="complete",
            axes=tensor.axes,
            entries=tensor.entries,
            provenance=wrong_provenance,
        )

    missing_input = ContractProvenance(
        origin="test.tensor",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(FOREST,),
    )
    with pytest.raises(ValueError, match="provenance does not bind"):
        TensorView(
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            source_forest_sha256=FOREST,
            source_fourfold_sha256=FOURFOLD,
            status="complete",
            axes=tensor.axes,
            entries=tensor.entries,
            provenance=missing_input,
        )


def test_axis_count_has_an_explicit_memory_bound() -> None:
    axes = tuple(TensorAxis(f"axis-{index}", ("x",)) for index in range(MAX_TENSOR_AXES + 1))
    with pytest.raises(ValueError, match="bounded limit"):
        TensorView(
            repository_id="KTY137/daedalus",
            source_revision=REVISION,
            source_forest_sha256=FOREST,
            source_fourfold_sha256=FOURFOLD,
            status="complete",
            axes=axes,
            entries=(),
            provenance=provenance(),
        )


def test_digest_is_stable_across_python_hash_seeds() -> None:
    script = r'''
from daedalus.schemas import ContractProvenance
from daedalus.twin.tensor import SparseTensorEntry, TensorAxis, TensorView
revision = "a" * 40
forest = "b" * 64
fourfold = "c" * 64
axes = tuple({
    TensorAxis("plane", tuple({"knowledge", "code"})),
    TensorAxis("node", tuple({"src/b.py", "src/a.py"})),
})
entries = tuple({
    SparseTensorEntry(
        tuple({("plane", "code"), ("node", "src/a.py")}),
        "membership", evidence_sha256s=("d" * 64,)),
    SparseTensorEntry(
        tuple({("plane", "knowledge"), ("node", "src/b.py")}),
        "membership", evidence_sha256s=("e" * 64,)),
})
provenance = ContractProvenance(
    origin="test.tensor",
    source_revision=revision,
    created_at="2026-08-30T01:00:00Z",
    input_digests=(forest, fourfold),
)
print(TensorView(
    repository_id="KTY137/daedalus",
    source_revision=revision,
    source_forest_sha256=forest,
    source_fourfold_sha256=fourfold,
    status="complete",
    axes=axes,
    entries=entries,
    provenance=provenance,
).digest)
'''
    digests = []
    for seed in ("1", "777"):
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        digests.append(result.stdout.strip())

    assert len(digests[0]) == 64
    assert digests[0] == digests[1]
