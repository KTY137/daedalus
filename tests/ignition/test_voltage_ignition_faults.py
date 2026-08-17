"""Fail-closed behavior of the Gate-1 rehearsal runner under faults.

The green-path suite proves the rename slice works and replays digest-
identically.  These tests pin the refusal semantics the activation checklist
depends on: what happens on restart over debris, on a candidate that is not
isolated, on a fixture whose preconditions do not hold, and on a source tree
that mutates while the candidate materializes.  Every scenario must end in a
refusal, never in a silently mixed candidate -- and the exact restart recipe
(fresh root, identical digests) is asserted rather than assumed.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

import daedalus.ignition.runner as runner
from daedalus.ignition import run_voltage_ignition
from daedalus.ignition.runner import IgnitionError

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "ignition" / "voltage"
BASE = "1" * 40
CANDIDATE = "2" * 40
NOW = "2026-08-02T00:00:00Z"


def _run(source: Path, candidate_root: Path):
    return run_voltage_ignition(
        source,
        candidate_root,
        base_revision=BASE,
        candidate_revision=CANDIDATE,
        collected_at=NOW,
    )


def _tree_digest(root: Path) -> str:
    return runner._tree_digest(root)


def test_restart_over_debris_refuses_and_a_fresh_root_replays_identically(
    tmp_path: Path,
) -> None:
    """Restart semantics: debris is refused, the recipe is a fresh root.

    A crashed or interrupted run can leave a partial candidate directory.
    The runner must never materialize over it (a mixed candidate would carry
    files from two runs while claiming one identity).  The supported restart
    path is a new candidate root, and it must reproduce the original digests
    exactly -- that pair of properties is what "restart/replay works" means
    for this slice.
    """
    first = _run(FIXTURE, tmp_path / "one")

    debris = tmp_path / "two"
    debris.mkdir()
    (debris / "partial.py").write_text("leftover = True\n", encoding="utf-8")
    fixture_before = _tree_digest(FIXTURE)
    with pytest.raises(IgnitionError, match="must not already exist"):
        _run(FIXTURE, debris)
    # the refusal itself performed no effect: debris kept, fixture untouched
    assert (debris / "partial.py").read_text(encoding="utf-8") == "leftover = True\n"
    assert sorted(p.name for p in debris.iterdir()) == ["partial.py"]
    assert _tree_digest(FIXTURE) == fixture_before

    replay = _run(FIXTURE, tmp_path / "three")
    assert replay.candidate_source_bundle_sha256 == first.candidate_source_bundle_sha256
    assert replay.candidate_snapshot.digest == first.candidate_snapshot.digest
    assert replay.evidence_packet.digest == first.evidence_packet.digest


def test_candidate_root_nested_inside_the_source_is_refused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    shutil.copytree(FIXTURE, source)
    before = _tree_digest(source)
    with pytest.raises(IgnitionError, match="isolated"):
        _run(source, source / "nested-candidate")
    # candidate == source hits the pre-existing-root refusal first; either
    # message is a refusal, and nothing may be written in both cases
    with pytest.raises(IgnitionError, match="must not already exist"):
        _run(source, source)
    assert _tree_digest(source) == before, "the refusal must not touch the source"


def test_base_whose_claims_do_not_hold_cannot_even_compile(tmp_path: Path) -> None:
    """Layer 1: cross-plane claim verification refuses a tampered base.

    Renaming the dataclass field out from under fourfold.json makes the
    type_matches claims false, and the base Twin compilation refuses before
    any candidate exists.  A base that does not satisfy its own claims can
    produce neither a candidate nor evidence.
    """
    from daedalus.twin._reference_common import ReferenceCompileError

    source = tmp_path / "tampered"
    shutil.copytree(FIXTURE, source)
    models = source / "src/ignition_app/models.py"
    models.write_text(
        models.read_text(encoding="utf-8").replace(
            "    voltage: float", "    something_else: float"
        ),
        encoding="utf-8",
    )

    candidate_root = tmp_path / "candidate"
    with pytest.raises(ReferenceCompileError, match="Event.voltage"):
        _run(source, candidate_root)
    assert not candidate_root.exists(), (
        "base compilation refused, so no candidate tree may have been created"
    )


def test_fixture_that_violates_a_rename_precondition_fails_closed(
    tmp_path: Path,
) -> None:
    """Layer 2: exact-count rename preconditions refuse after a valid compile.

    Tampering a rename site that no cross-plane claim binds (the exact
    repository.py expression) lets the base compile but must stop the
    materialization at its precondition -- before behavior or evidence.  The
    partial candidate the abort leaves behind is then refused by the next
    run rather than silently completed: fail-closed twice, and the restart
    recipe stays "fresh root only".
    """
    source = tmp_path / "tampered"
    shutil.copytree(FIXTURE, source)
    repository = source / "src/ignition_app/repository.py"
    repository.write_text(
        repository.read_text(encoding="utf-8").replace(
            'voltage=float(row["voltage"])', 'voltage=float(row.get("voltage"))'
        ),
        encoding="utf-8",
    )

    candidate_root = tmp_path / "candidate"
    with pytest.raises(IgnitionError, match="rename precondition failed"):
        _run(source, candidate_root)

    # the aborted materialization may leave a partial tree; reusing it is
    # refused, which is the documented restart contract (fresh root only)
    if candidate_root.exists():
        with pytest.raises(IgnitionError, match="must not already exist"):
            _run(source, candidate_root)


def test_source_mutation_during_materialization_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The primary-tree tripwire fires when the source changes mid-run."""
    source = tmp_path / "source"
    shutil.copytree(FIXTURE, source)
    original = runner.materialize_voltage_rename

    def mutating(source_root, candidate_root):
        result = original(source_root, candidate_root)
        marker = Path(source_root) / "wiki" / "Event.md"
        marker.write_text(
            marker.read_text(encoding="utf-8") + "\nmutated-during-run\n",
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(runner, "materialize_voltage_rename", mutating)
    with pytest.raises(IgnitionError, match="source fixture changed"):
        _run(source, tmp_path / "candidate")
