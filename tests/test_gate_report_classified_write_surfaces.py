"""GateReport-v5 repository-write counters come from CLASSIFIED surfaces.

Before this wire, ``repository_write_failures`` was the raw syntactic scan:
every callsite the AST walker emitted was a blocker, a registered door
subtracted nothing, and the classification chain
(``repository_write_classification`` -> lease -> materialization -> origin ->
anchor semantics -> guard structure -> runtime conformance) was never imported
by the reporter.  These cases pin the wire that closes that gap and the fences
that keep it from becoming a way to declare the counter away.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.gates.report_v3 import (
    _CLASSIFICATION_SCHEMA,
    _classify_repository_write_surfaces,
    _repository_write_evidence,
    build_gate0_report_v3,
)
from daedalus.gates.repository.write_classification import (
    CLASSIFICATION_SCHEMA,
    EvidenceBinding,
    EvidenceKind,
    GuardDisposition,
    SurfaceClassification,
    TargetDisposition,
    surface_binding_sha256,
    surface_classification_verdict,
)
from daedalus.gates.repository.write_inventory_v2 import (
    RepositoryWriteSurface,
    scan_repository_write_surfaces_v2,
)


REVISION = "1" * 40
ROOT = Path(__file__).resolve().parents[1]

# Index of the ``_repository_write_evidence`` tuple.
_FAILURES = 4
_SURFACES_TOTAL = 8
_CLASSIFICATION = 9
_VERDICTS = 10


def _tree(tmp_path: Path) -> Path:
    package = tmp_path / "daedalus"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "writer.py").write_text(
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def save(target: Path) -> None:\n"
        "    target.write_text('x', encoding='utf-8')\n",
        encoding="utf-8",
    )
    return tmp_path


def _evidence(
    surface: RepositoryWriteSurface,
    pairs: list[tuple[EvidenceKind, str]],
) -> tuple[EvidenceBinding, ...]:
    binding = surface_binding_sha256(REVISION, surface)
    rows = [
        EvidenceBinding(
            kind=kind,
            source_revision=REVISION,
            surface_sha256=binding,
            sha256=f"{index:064x}",
            locator=f"cas:sha256:{index:064x}",
            guard_contract=contract,
        )
        for index, (kind, contract) in enumerate(pairs, start=1)
    ]
    return tuple(sorted(rows, key=EvidenceBinding.sort_key))


def _leased_under_a_door(surface: RepositoryWriteSurface) -> SurfaceClassification:
    """A production surface behind a central door with the full evidence set."""

    return SurfaceClassification(
        source_revision=REVISION,
        surface=surface,
        target=TargetDisposition.CHECKOUT_EXTERNAL,
        guard=GuardDisposition.CENTRAL,
        production_reachable=True,
        guard_contracts=("daedalus.writer.door",),
        evidence=_evidence(
            surface,
            [
                (EvidenceKind.GUARD_CONTRACT, "daedalus.writer.door"),
                (EvidenceKind.EFFECT_LEASE_RECEIPT, ""),
                (EvidenceKind.RUNTIME_CONFORMANCE_RECEIPT, ""),
                (EvidenceKind.PRIMARY_CHECKOUT_DISJOINTNESS_RECEIPT, ""),
            ],
        ),
    )


def _reachable_but_unleased(
    surface: RepositoryWriteSurface,
) -> SurfaceClassification:
    """A production-reachable surface with no lease and no central guard."""

    return SurfaceClassification(
        source_revision=REVISION,
        surface=surface,
        target=TargetDisposition.PRIMARY_CHECKOUT,
        guard=GuardDisposition.UNGUARDED,
        production_reachable=True,
        guard_contracts=(),
        evidence=(),
    )


def _declaration(inventory, rows: list[SurfaceClassification]) -> dict[str, object]:
    payload = []
    for row in rows:
        item = row.to_dict()
        # ``candidate_blockers`` is derived, not declared.
        item.pop("candidate_blockers")
        payload.append(item)
    return {
        "schema": "daedalus-gate0-repository-write-classification-input/1",
        "source_revision": inventory.source_revision,
        "inventory_digest": inventory.digest,
        "classifications": payload,
    }


def _write(path: Path, document: dict[str, object]) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_a_leased_surface_under_a_registered_door_is_not_a_failure(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path)
    inventory = scan_repository_write_surfaces_v2(root, source_revision=REVISION)
    surface = inventory.blockers[0]

    unclassified = _repository_write_evidence(root, source_revision=REVISION)
    assert any(
        row.startswith(f"{surface.path}:{surface.line}:")
        for row in unclassified[_FAILURES]
    )
    assert unclassified[_VERDICTS] == ("unclassified:1",)

    document = _write(
        tmp_path / "classification.json",
        _declaration(inventory, [_leased_under_a_door(surface)]),
    )
    leased = _repository_write_evidence(
        root,
        source_revision=REVISION,
        classification_input=document,
    )
    # The surface identity is gone from the failure list.
    assert not any(
        row.startswith(f"{surface.path}:{surface.line}:")
        for row in leased[_FAILURES]
    )
    assert leased[_VERDICTS] == ("cleared:central:1",)


def test_a_production_reachable_unleased_surface_is_a_failure(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path)
    inventory = scan_repository_write_surfaces_v2(root, source_revision=REVISION)
    surface = inventory.blockers[0]
    document = _write(
        tmp_path / "classification.json",
        _declaration(inventory, [_reachable_but_unleased(surface)]),
    )
    result = _repository_write_evidence(
        root,
        source_revision=REVISION,
        classification_input=document,
    )
    verdict = (
        "blocked:primary-checkout-write-target+production-write-unguarded"
    )
    assert result[_VERDICTS] == (f"{verdict}:1",)
    assert result[_FAILURES] == (
        f"{surface.path}:{surface.line}:{surface.column}:"
        f"{surface.kind}:{surface.callee}:{surface.operation}:verdict={verdict}",
    )


def test_a_door_id_rides_along_with_the_verdict_when_the_chain_names_one(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path)
    inventory = scan_repository_write_surfaces_v2(root, source_revision=REVISION)
    surface = inventory.blockers[0]
    local = SurfaceClassification(
        source_revision=REVISION,
        surface=surface,
        target=TargetDisposition.UNKNOWN,
        guard=GuardDisposition.LOCAL_GUARDS,
        production_reachable=True,
        guard_contracts=("daedalus.writer.door",),
        evidence=_evidence(
            surface, [(EvidenceKind.GUARD_CONTRACT, "daedalus.writer.door")]
        ),
    )
    document = _write(
        tmp_path / "classification.json", _declaration(inventory, [local])
    )
    result = _repository_write_evidence(
        root,
        source_revision=REVISION,
        classification_input=document,
    )
    assert len(result[_FAILURES]) == 1
    assert result[_FAILURES][0].endswith(":door=daedalus.writer.door")


def test_clearing_a_surface_cannot_empty_the_counter_by_declaration(
    tmp_path: Path,
) -> None:
    """The chain declares its own evidence unauthenticated; the report says so."""

    root = _tree(tmp_path)
    inventory = scan_repository_write_surfaces_v2(root, source_revision=REVISION)
    document = _write(
        tmp_path / "classification.json",
        _declaration(inventory, [_leased_under_a_door(inventory.blockers[0])]),
    )
    failures = _repository_write_evidence(
        root,
        source_revision=REVISION,
        classification_input=document,
    )[_FAILURES]
    assert "classification:evidence-unauthenticated:1" in failures
    assert "classification:gate-report-binding-missing" in failures


@pytest.mark.parametrize(
    "corruption",
    [
        {"inventory_digest": "0" * 64},
        {"source_revision": "2" * 40},
    ],
)
def test_a_declaration_that_does_not_bind_to_this_scan_clears_nothing(
    tmp_path: Path,
    corruption: dict[str, str],
) -> None:
    root = _tree(tmp_path)
    inventory = scan_repository_write_surfaces_v2(root, source_revision=REVISION)
    surface = inventory.blockers[0]
    document = _declaration(inventory, [_leased_under_a_door(surface)])
    document.update(corruption)
    path = _write(tmp_path / "classification.json", document)
    result = _repository_write_evidence(
        root,
        source_revision=REVISION,
        classification_input=path,
    )
    assert "classification:input-refused" in result[_FAILURES]
    assert result[_VERDICTS] == ("unclassified:1",)


def test_an_unreadable_declaration_clears_nothing(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    path = tmp_path / "classification.json"
    path.write_text("{not json", encoding="utf-8")
    result = _repository_write_evidence(
        root,
        source_revision=REVISION,
        classification_input=path,
    )
    assert "classification:input-unreadable" in result[_FAILURES]
    assert result[_VERDICTS] == ("unclassified:1",)


def test_total_and_failure_counts_are_both_declared_and_the_census_is_complete(
    tmp_path: Path,
) -> None:
    root = _tree(tmp_path)
    result = _repository_write_evidence(root, source_revision=REVISION)
    total = result[_SURFACES_TOTAL]
    assert total == 1
    assert (
        sum(int(row.rsplit(":", 1)[1]) for row in result[_VERDICTS]) == total
    )
    # The raw syntactic blocker count stays declared as a diagnostic, so the
    # classified census can never hide how many callsites the scanner found.
    assert result[5] == ("repository_write_syntactic_blockers:1",)


def test_the_chain_that_classified_is_declared_in_the_report() -> None:
    report = build_gate0_report_v3(ROOT, source_revision=REVISION)
    assert report.repository_write_classification_schema == CLASSIFICATION_SCHEMA
    assert _CLASSIFICATION_SCHEMA == CLASSIFICATION_SCHEMA
    assert report.repository_write_surfaces_total > 0
    assert sum(
        int(row.rsplit(":", 1)[1])
        for row in report.repository_write_surface_verdicts
    ) == report.repository_write_surfaces_total
    # No declaration exists at HEAD, so every blocking surface is unclassified
    # and stays a failure: the wire changes the shape, not the verdict.
    assert report.repository_write_surface_verdicts == (
        f"unclassified:{report.repository_write_surfaces_total}",
    )
    assert len(report.repository_write_failures) == (
        report.repository_write_surfaces_total
    )
    assert report.closed is False


def test_the_verdict_vocabulary_belongs_to_the_chain(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    inventory = scan_repository_write_surfaces_v2(root, source_revision=REVISION)
    surface = inventory.blockers[0]
    assert (
        surface_classification_verdict(_leased_under_a_door(surface))
        == "cleared:central"
    )
    assert surface_classification_verdict(_reachable_but_unleased(surface)) == (
        "blocked:primary-checkout-write-target+production-write-unguarded"
    )
    # The reporter derives its census from that function and mints nothing.
    failures, verdicts, declared = _classify_repository_write_surfaces(
        inventory, None
    )
    assert declared == CLASSIFICATION_SCHEMA
    assert verdicts == ("unclassified:1",)
    assert len(failures) == 1
