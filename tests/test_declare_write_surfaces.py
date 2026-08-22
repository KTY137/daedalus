"""The declaration generator may only declare what an anchor provably dominates.

These tests pin the four properties that make the declaration honest rather
than convenient:

1. a surface inside the anchor's post-``begin_effect`` region is declared;
2. a surface the anchor does not dominate -- before the call, in a public
   helper, in a method, or in a private helper some other module also names --
   is left out, and therefore stays ``unclassified`` in the report;
3. the declaration document binds the exact ``source_revision`` and
   ``inventory_digest`` of the scan it was derived from, and a document bound
   to a different scan clears nothing;
4. running the reporter's own classification wire with the declaration lowers
   the ``unclassified`` verdict count by exactly the number of declared rows,
   and by no more -- nothing becomes ``cleared``.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from daedalus.gates.report_v3 import _classify_repository_write_surfaces
from daedalus.gates.repository_write_classification import (
    EvidenceKind,
    GuardDisposition,
    RepositoryWriteClassificationError,
    SurfaceClassification,
    TargetDisposition,
    project_classification_input,
    surface_binding_sha256,
)
from daedalus.gates.repository_write_inventory_v2 import (
    scan_repository_write_surfaces_v2,
)


def _load_generator():
    """Import the generator by path: ``scripts/`` is not an importable package."""

    path = ROOT / "scripts" / "declare_write_surfaces.py"
    spec = importlib.util.spec_from_file_location("declare_write_surfaces", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["declare_write_surfaces"] = module
    spec.loader.exec_module(module)
    return module


GEN = _load_generator()

REVISION = "4fd2daa718c7304984c01fb6685a0d15aeac0d8f"
OTHER_REVISION = "0" * 40

# One module that exercises every dominance decision at once.
#
# * ``main`` writes once BEFORE ``begin_effect`` and once after;
# * ``_after_helper`` is private and named only from the post-anchor region;
# * ``public_helper`` is not private, so it is never admitted;
# * ``_shared_helper`` is private but also reachable from ``public_helper``,
#   which sits outside the dominated region;
# * ``Store.append`` is a method, so no anchor dominates it.
MODULE_SOURCE = '''\
"""Fixture module."""
import subprocess
from pathlib import Path


def public_helper(path):
    Path(path).write_text("public", encoding="utf-8")
    return _shared_helper(path)


def _shared_helper(path):
    Path(path).write_text("shared", encoding="utf-8")


def _after_helper(path):
    Path(path).write_text("after", encoding="utf-8")


class Store:
    def __init__(self, path):
        self.path = Path(path)

    def append(self, text):
        self.path.parent.mkdir(parents=True, exist_ok=True)


def main(argv=None):
    from .effect_boundary import begin_effect

    Path("before.txt").write_text("before", encoding="utf-8")
    begin_effect("test.door", (), ())
    Path("after.txt").write_text("after", encoding="utf-8")
    _after_helper("helper.txt")
    _shared_helper("shared.txt")
    subprocess.run(["git", "status"], check=False)
    return 0
'''


@pytest.fixture()
def fixture_root(tmp_path: Path) -> Path:
    package = tmp_path / "daedalus"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text(MODULE_SOURCE, encoding="utf-8")
    return tmp_path


@pytest.fixture()
def door() -> "GEN.DoorAnchor":
    return GEN.DoorAnchor(
        door_id="test.door",
        module="daedalus.mod",
        rel_path="daedalus/mod.py",
        symbol=("main",),
        contracts=("budget.process_guard",),
    )


def _lines(root: Path, name: str) -> int:
    text = (root / "daedalus" / "mod.py").read_text(encoding="utf-8")
    for number, line in enumerate(text.splitlines(), start=1):
        if name in line:
            return number
    raise AssertionError(f"{name!r} not found in the fixture module")


def _declared(root: Path, door) -> set[tuple[str, int, int]]:
    inventory = scan_repository_write_surfaces_v2(root, source_revision=REVISION)
    dominance = GEN._dominance(root, door, GEN.NameIndex.build(root))
    return {
        (surface.path, surface.line, surface.column)
        for surface in inventory.surfaces
        if surface.blocking
        and (surface.line, surface.column) in dominance.positions
    }


# ---------------------------------------------------------------------------
# 1 + 2: only anchor-dominated surfaces
# ---------------------------------------------------------------------------


def test_the_write_after_begin_effect_is_dominated(fixture_root, door):
    declared = _declared(fixture_root, door)
    after = _lines(fixture_root, 'Path("after.txt")')
    assert any(line == after for _, line, _ in declared)


def test_the_write_before_begin_effect_is_not_dominated(fixture_root, door):
    declared = _declared(fixture_root, door)
    before = _lines(fixture_root, 'Path("before.txt")')
    assert all(line != before for _, line, _ in declared), (
        "a write lexically before the begin_effect statement was declared; "
        "the anchor cannot dominate it"
    )


def test_a_private_helper_reached_only_after_the_anchor_is_dominated(
    fixture_root, door
):
    declared = _declared(fixture_root, door)
    helper = _lines(fixture_root, '"after", encoding')
    assert any(line == helper for _, line, _ in declared)


def test_a_public_helper_is_never_dominated(fixture_root, door):
    declared = _declared(fixture_root, door)
    public = _lines(fixture_root, '"public", encoding')
    assert all(line != public for _, line, _ in declared)


def test_a_private_helper_reachable_from_undominated_code_is_not_dominated(
    fixture_root, door
):
    declared = _declared(fixture_root, door)
    shared = _lines(fixture_root, '"shared", encoding')
    assert all(line != shared for _, line, _ in declared), (
        "_shared_helper is also called from public_helper, so reaching it does "
        "not imply the anchor ran"
    )


def test_a_method_body_is_never_dominated(fixture_root, door):
    declared = _declared(fixture_root, door)
    method = _lines(fixture_root, "self.path.parent.mkdir")
    assert all(line != method for _, line, _ in declared)


def test_a_private_helper_named_by_another_module_is_not_dominated(
    fixture_root, door
):
    """The cross-module name check is what makes level 2 sound."""

    (fixture_root / "daedalus" / "other.py").write_text(
        "def caller():\n    return _after_helper\n", encoding="utf-8"
    )
    declared = _declared(fixture_root, door)
    helper = _lines(fixture_root, '"after", encoding')
    assert all(line != helper for _, line, _ in declared), (
        "another module names _after_helper, so it can be reached without the door"
    )


# ``with begin_effect(...) as lease:`` fires nowhere in the tree at the time of
# writing -- every anchor is a plain statement call -- so the branch that
# handles it is pinned here rather than by a real door.
WITH_CONTEXT_SOURCE = '''\
"""Fixture module whose anchor is a context manager."""
from pathlib import Path


def main(argv=None):
    from .effect_boundary import begin_effect

    Path("before.txt").write_text("before", encoding="utf-8")
    with begin_effect("test.door", (), ()) as lease:
        Path("inside.txt").write_text("inside", encoding="utf-8")
    return 0
'''


def test_a_with_begin_effect_body_is_dominated(tmp_path, door):
    package = tmp_path / "daedalus"
    package.mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text(WITH_CONTEXT_SOURCE, encoding="utf-8")

    dominance = GEN._dominance(tmp_path, door, GEN.NameIndex.build(tmp_path))
    assert dominance.shape == "with-context"

    inventory = scan_repository_write_surfaces_v2(
        tmp_path, source_revision=REVISION
    )
    declared = {
        surface.line
        for surface in inventory.surfaces
        if surface.blocking
        and (surface.line, surface.column) in dominance.positions
    }
    text = (package / "mod.py").read_text(encoding="utf-8").splitlines()
    inside = next(
        i for i, line in enumerate(text, start=1) if '"inside", encoding' in line
    )
    before = next(
        i for i, line in enumerate(text, start=1) if '"before", encoding' in line
    )
    assert inside in declared
    assert before not in declared


def test_an_anchor_without_begin_effect_declares_nothing(fixture_root):
    source = MODULE_SOURCE.replace('begin_effect("test.door", (), ())', "pass")
    (fixture_root / "daedalus" / "mod.py").write_text(source, encoding="utf-8")
    anchor = GEN.DoorAnchor(
        door_id="test.door",
        module="daedalus.mod",
        rel_path="daedalus/mod.py",
        symbol=("main",),
        contracts=(),
    )
    with pytest.raises(GEN.DeclarationError):
        GEN._dominance(fixture_root, anchor, GEN.NameIndex.build(fixture_root))


# ---------------------------------------------------------------------------
# 3: the declaration binds revision and inventory digest
# ---------------------------------------------------------------------------


def _rows(root: Path, door) -> tuple[SurfaceClassification, ...]:
    inventory = scan_repository_write_surfaces_v2(root, source_revision=REVISION)
    dominance = GEN._dominance(root, door, GEN.NameIndex.build(root))
    digest = GEN.hashlib.sha256(
        (root / "daedalus" / "mod.py").read_bytes()
    ).hexdigest()
    rows = []
    for surface in inventory.surfaces:
        if not surface.blocking:
            continue
        if (surface.line, surface.column) not in dominance.positions:
            continue
        binding, _raw = GEN.source_anchor_evidence(REVISION, surface, digest)
        rows.append(
            SurfaceClassification(
                source_revision=REVISION,
                surface=surface,
                target=TargetDisposition.UNKNOWN,
                guard=GuardDisposition.INVENTORY_ONLY,
                production_reachable=True,
                guard_contracts=(),
                evidence=(binding,),
                notes=f"anchor-dominated by door {door.door_id}",
            )
        )
    return tuple(sorted(rows, key=SurfaceClassification.sort_key))


def test_the_document_binds_the_exact_revision_and_inventory_digest(
    fixture_root, door
):
    inventory = scan_repository_write_surfaces_v2(
        fixture_root, source_revision=REVISION
    )
    rows = _rows(fixture_root, door)
    derivation = GEN.Derivation(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        inventory_surface_count=len(inventory.surfaces),
        rows=rows,
        blobs={},
        per_door=(),
        skipped_doors=(),
        undominated_in_door_modules=0,
    )
    document = GEN.declaration_document(derivation)
    assert document["schema"] == GEN.INPUT_SCHEMA
    assert document["source_revision"] == REVISION
    assert document["inventory_digest"] == inventory.digest
    # ``candidate_blockers`` is the chain's derivation, never a declared field.
    assert all("candidate_blockers" not in row for row in document["classifications"])
    # The chain accepts the document against the scan it was bound to.
    projection = project_classification_input(inventory, document)
    assert len(projection.classifications) == len(rows)


def test_a_document_bound_to_another_revision_is_refused(fixture_root, door):
    inventory = scan_repository_write_surfaces_v2(
        fixture_root, source_revision=REVISION
    )
    derivation = GEN.Derivation(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        inventory_surface_count=len(inventory.surfaces),
        rows=_rows(fixture_root, door),
        blobs={},
        per_door=(),
        skipped_doors=(),
        undominated_in_door_modules=0,
    )
    document = dict(GEN.declaration_document(derivation))
    document["source_revision"] = OTHER_REVISION
    with pytest.raises(RepositoryWriteClassificationError):
        project_classification_input(inventory, document)


def test_a_document_bound_to_another_inventory_digest_is_refused(
    fixture_root, door
):
    inventory = scan_repository_write_surfaces_v2(
        fixture_root, source_revision=REVISION
    )
    derivation = GEN.Derivation(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        inventory_surface_count=len(inventory.surfaces),
        rows=_rows(fixture_root, door),
        blobs={},
        per_door=(),
        skipped_doors=(),
        undominated_in_door_modules=0,
    )
    document = dict(GEN.declaration_document(derivation))
    document["inventory_digest"] = "f" * 64
    with pytest.raises(RepositoryWriteClassificationError):
        project_classification_input(inventory, document)


def test_the_minted_evidence_materializes_against_its_own_bytes(
    fixture_root, door
):
    from daedalus.gates.repository_write_evidence_materialization import (
        materialize_repository_write_evidence,
    )
    from daedalus.gates.repository_write_classification import (
        project_repository_write_classifications,
    )

    inventory = scan_repository_write_surfaces_v2(
        fixture_root, source_revision=REVISION
    )
    dominance = GEN._dominance(fixture_root, door, GEN.NameIndex.build(fixture_root))
    digest = GEN.hashlib.sha256(
        (fixture_root / "daedalus" / "mod.py").read_bytes()
    ).hexdigest()
    rows = []
    blobs = {}
    for surface in inventory.surfaces:
        if not surface.blocking:
            continue
        if (surface.line, surface.column) not in dominance.positions:
            continue
        binding, raw = GEN.source_anchor_evidence(REVISION, surface, digest)
        blobs[binding.locator] = raw
        rows.append(
            SurfaceClassification(
                source_revision=REVISION,
                surface=surface,
                target=TargetDisposition.UNKNOWN,
                guard=GuardDisposition.INVENTORY_ONLY,
                production_reachable=True,
                guard_contracts=(),
                evidence=(binding,),
            )
        )
    projection = project_repository_write_classifications(
        inventory, tuple(sorted(rows, key=SurfaceClassification.sort_key))
    )
    report = materialize_repository_write_evidence(projection, blobs)
    assert report.missing_locators == ()
    assert len(report.records) == len(rows)
    assert all(
        record.kind is EvidenceKind.SOURCE_ANCHOR for record in report.records
    )


# ---------------------------------------------------------------------------
# 4: the reporter's own wire moves by exactly the declared count
# ---------------------------------------------------------------------------


def _census(verdicts) -> dict[str, int]:
    return {
        name: int(count)
        for name, _, count in (row.rpartition(":") for row in verdicts)
    }


def test_the_declaration_lowers_unclassified_by_exactly_the_declared_count(
    fixture_root, door, tmp_path
):
    inventory = scan_repository_write_surfaces_v2(
        fixture_root, source_revision=REVISION
    )
    rows = _rows(fixture_root, door)
    assert rows, "the fixture must declare at least one surface"

    before_failures, before_verdicts, _ = _classify_repository_write_surfaces(
        inventory, None
    )
    before = _census(before_verdicts)

    derivation = GEN.Derivation(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        inventory_surface_count=len(inventory.surfaces),
        rows=rows,
        blobs={},
        per_door=(),
        skipped_doors=(),
        undominated_in_door_modules=0,
    )
    path = tmp_path / "classification-input.json"
    path.write_text(
        json.dumps(GEN.declaration_document(derivation)), encoding="utf-8"
    )
    after_failures, after_verdicts, schema = _classify_repository_write_surfaces(
        inventory, path
    )
    after = _census(after_verdicts)

    assert schema == "daedalus-gate0-repository-write-classification/1"
    assert before["unclassified"] - after["unclassified"] == len(rows)
    # An honest declaration clears nothing, so no aggregate row appears and the
    # failure count does not move: the verdicts get names, not absolution.
    assert len(after_failures) == len(before_failures)
    assert not any(row.startswith("classification:") for row in after_failures)
    assert "cleared:central" not in after
    assert after.get(
        "blocked:write-target-unknown+production-write-inventory_only"
    ) == len(rows)


def test_a_declaration_bound_to_a_foreign_scan_clears_nothing(
    fixture_root, door, tmp_path
):
    inventory = scan_repository_write_surfaces_v2(
        fixture_root, source_revision=REVISION
    )
    derivation = GEN.Derivation(
        source_revision=REVISION,
        inventory_digest=inventory.digest,
        inventory_surface_count=len(inventory.surfaces),
        rows=_rows(fixture_root, door),
        blobs={},
        per_door=(),
        skipped_doors=(),
        undominated_in_door_modules=0,
    )
    document = dict(GEN.declaration_document(derivation))
    document["inventory_digest"] = "f" * 64
    path = tmp_path / "stale.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    failures, verdicts, _ = _classify_repository_write_surfaces(inventory, path)
    census = _census(verdicts)
    assert "classification:input-refused" in failures
    assert census["unclassified"] == len(inventory.blockers)
