"""Fail-closed behavior of the SHIPPED Gate-1 door under faults.

The green-path file proves the slice works and replays. These six rows pin the
refusal semantics the activation checklist depends on: restart over debris, a
workspace that is not isolated from the source, a base whose cross-plane claims
do not hold, a fixture that violates a rename precondition, a source tree that
mutates while the candidate is built, and a crash between rename writes.

WHAT CHANGED IN G1-RENOVATION-02A. Every row above used to be asserted about
``daedalus.ignition.runner.run_voltage_ignition`` -- the in-process rehearsal
``python -m daedalus.ignition`` does not call. The rows are unchanged; the
subject is now ``run_gate1_ignition``, and where the shipped path refuses
differently the difference is asserted as measured rather than assumed. One
such difference is recorded as an OPEN row in
``docs/work-packets/G1_ACTIVATION_CHECKLIST.md`` §2.3 (F5): the door detects a
non-isolated workspace with its tree-digest tripwire AFTER the run, where the
rehearsal refused before the first write.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from daedalus.ignition import gate1
from daedalus.ignition.runner import IgnitionError, tree_digest

#: The fixture that plays the target project -- the door's own default.
FIXTURE = gate1.DEFAULT_FIXTURE


def _fixture_copy(tmp_path: Path, name: str = "source") -> Path:
    """A private copy of the target project.

    Every row here injects a fault into the fixture or writes near it, and the
    repository's own ``tests/fixtures/ignition/voltage`` is the base revision
    of the shipped slice -- writing it would move every identity in the
    receipt. The copy is what gets tampered with.
    """

    source = tmp_path / name
    shutil.copytree(FIXTURE, source)
    return source


def _file_map(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_restart_over_debris_refuses_and_a_fresh_root_replays_identically(
    tmp_path: Path, door, gate1_replay
) -> None:
    """Restart semantics: debris is refused, the recipe is a fresh workspace.

    A crashed or interrupted run leaves a partial scratch tree. The door must
    never build over it -- a mixed tree would carry files from two runs while
    claiming one identity. Both of its materialising steps refuse a destination
    that already exists (``prepare_ignition_repo``, ``gate1.py:355``;
    ``compose_candidate``, ``gate1.py:521``), and the supported restart is a new
    workspace, which must reproduce the original digests exactly. That pair of
    properties is what "restart/replay works" means for this slice.
    """

    workspace = tmp_path / "ws"
    debris = workspace / "target"
    debris.mkdir(parents=True)
    (debris / "partial.py").write_text("leftover = True\n", encoding="utf-8")
    fixture_before = tree_digest(FIXTURE)

    with pytest.raises(IgnitionError, match="must not already exist"):
        door(
            receipt_root=tmp_path / "receipts",
            workspace=workspace,
        )

    # the refusal itself performed no effect: debris kept, fixture untouched,
    # no receipt written
    assert (debris / "partial.py").read_text(encoding="utf-8") == "leftover = True\n"
    assert sorted(p.name for p in debris.iterdir()) == ["partial.py"]
    assert tree_digest(FIXTURE) == fixture_before
    assert not (
        tmp_path / "receipts" / gate1.SESSION_MISSION_ID / "receipt.json"
    ).exists(), "a refused run must not leave a receipt claiming a Gate-1 result"

    # the second materialising step refuses the same way
    with pytest.raises(IgnitionError, match="candidate root must not already exist"):
        gate1.compose_candidate(debris, [b"diff"], debris)

    # and the supported restart -- a fresh workspace -- replays identically
    first, second = gate1_replay
    assert (
        first.result.candidate_source_tree.ref.sha256
        == second.result.candidate_source_tree.ref.sha256
    )
    assert first.result.graph_delta.digest == second.result.graph_delta.digest
    assert second.result.receipt["replay"]["replay_demonstrated"] is True


def test_a_workspace_nested_inside_the_source_is_refused(
    tmp_path: Path, door
) -> None:
    """A workspace that is not isolated from the source tree is refused.

    THE SHIPPED PATH REFUSES LATER THAN THE REHEARSAL DID, and this row says so
    rather than implying parity. ``run_voltage_ignition`` compared the candidate
    root against the source up front (``candidate == source or source in
    candidate.parents``) and refused before the first write.
    ``run_gate1_ignition`` has no such precondition: it measures the fixture's
    tree digest before and after (``gate1.py:727``, ``gate1.py:1280``) and
    raises when it moved.

    MEASURED 2026-09-06: the run completes, writes ``target/``, ``candidate/``,
    ``controls/`` and ``coverage/`` INTO the fixture root, and only then raises
    ``the fixture tree changed while the slice ran``. Every declared file of the
    fixture survives byte-identical -- the tripwire is real and the source is
    not corrupted -- but the refusal is late and it is dirty. Recorded as OPEN
    row F5 in ``docs/work-packets/G1_ACTIVATION_CHECKLIST.md`` §2.3; asserting
    an early refusal here would assert a guard the shipped path does not have.
    """

    source = _fixture_copy(tmp_path)
    declared_before = _file_map(source)

    with pytest.raises(IgnitionError, match="the fixture tree changed while the slice ran"):
        door(
            fixture_root=source,
            receipt_root=tmp_path / "receipts",
            workspace=source,          # <-- not isolated from the source
        )

    # the source's own files are intact: the tripwire caught a real change and
    # nothing rewrote the target project
    declared_after = _file_map(source)
    for rel, blob in declared_before.items():
        assert declared_after.get(rel) == blob, rel

    # ...and the measured residual: the refusal is late, so scratch debris was
    # written into the source root before it fired
    assert sorted(set(declared_after) - set(declared_before)) != [], (
        "if the door ever refuses BEFORE writing, this row becomes the stronger "
        "assertion the rehearsal made and checklist §2.3 row F5 closes"
    )


def test_base_whose_claims_do_not_hold_cannot_even_compile(
    tmp_path: Path, door
) -> None:
    """Layer 1: cross-plane claim verification refuses a tampered base.

    Renaming the dataclass field out from under ``fourfold.json`` makes the
    ``type_matches`` claims false, and the BASE Twin compilation refuses
    (``gate1.py:813``) before any attempt runs. A base that does not satisfy its
    own claims can produce neither a candidate nor evidence.
    """

    from daedalus.twin._reference_common import ReferenceCompileError

    source = _fixture_copy(tmp_path, "tampered")
    models = source / "src/ignition_app/models.py"
    models.write_text(
        models.read_text(encoding="utf-8").replace(
            "    voltage: float", "    something_else: float"
        ),
        encoding="utf-8",
    )
    workspace = tmp_path / "ws"

    with pytest.raises(ReferenceCompileError, match="Event.voltage"):
        door(
            fixture_root=source,
            receipt_root=tmp_path / "receipts",
            workspace=workspace,
        )

    assert not (workspace / "candidate").exists(), (
        "base compilation refused, so no candidate tree may have been composed"
    )
    assert not (
        tmp_path / "receipts" / gate1.SESSION_MISSION_ID / "receipt.json"
    ).exists(), "a refused run must not leave a receipt claiming a Gate-1 result"


def test_fixture_that_violates_a_rename_precondition_fails_closed(
    tmp_path: Path, door
) -> None:
    """Layer 2: rename preconditions refuse after a valid compile.

    The rehearsal's precondition was an exact occurrence COUNT inside
    ``materialize_voltage_rename``. The door states the same rule twice, in the
    two places that can hold it: ``plan_work_items`` refuses a manifest whose
    code plane no longer carries the retired symbol (``gate1.py:223``), and
    ``rename_operator`` refuses a declared path that does not carry it
    (``gate1.py:394``) rather than emitting an empty patch. Both fail closed
    before any candidate exists.
    """

    source = _fixture_copy(tmp_path, "tampered")
    for rel in ("src/ignition_app/models.py", "src/ignition_app/repository.py"):
        path = source / rel
        path.write_text(
            path.read_text(encoding="utf-8").replace("voltage", "tension"),
            encoding="utf-8",
        )
    workspace = tmp_path / "ws"

    with pytest.raises(IgnitionError, match="no declared code file carries"):
        door(
            fixture_root=source,
            receipt_root=tmp_path / "receipts",
            workspace=workspace,
        )
    assert not (workspace / "candidate").exists()
    assert not (
        tmp_path / "receipts" / gate1.SESSION_MISSION_ID / "receipt.json"
    ).exists(), "a refused run must not leave a receipt claiming a Gate-1 result"

    # the operator holds the same rule for a single declared path
    class _Ctx:
        worktree = source

    with pytest.raises(IgnitionError, match="rename precondition failed"):
        gate1.rename_operator(("src/ignition_app/models.py",))(_Ctx())


def test_source_mutation_during_materialization_is_detected(
    tmp_path: Path, door, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The primary-tree tripwire fires when the source changes mid-run.

    ``run_gate1_ignition`` digests the fixture before the run (``gate1.py:727``)
    and again after the packet is assembled (``gate1.py:1280``); a source that
    moved in between means the receipt cannot say what was built from what. The
    mutation is injected at ``compose_candidate``, the door's own materialising
    step, so the run is a real one up to the tripwire.
    """

    source = _fixture_copy(tmp_path)
    original = gate1.compose_candidate

    def mutating(repo, patches, destination):
        result = original(repo, patches, destination)
        marker = source / "wiki" / "Event.md"
        marker.write_text(
            marker.read_text(encoding="utf-8") + "\nmutated-during-run\n",
            encoding="utf-8",
        )
        return result

    monkeypatch.setattr(gate1, "compose_candidate", mutating)
    with pytest.raises(IgnitionError, match="the fixture tree changed while the slice ran"):
        door(
            fixture_root=source,
            receipt_root=tmp_path / "receipts",
            workspace=tmp_path / "ws",
        )


def test_crash_between_rename_writes_leaves_no_evaluable_candidate(
    tmp_path: Path, door, gate1_replay, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A kill mid-materialization leaves debris, never an evaluable candidate.

    The rehearsal performed six ``_replace`` writes in one process and was
    killed after the third. The door materialises through TWO attempts, each
    producing a patch that ``compose_candidate`` applies; killing the second
    attempt's operator is the same fault at the shipped path's own granularity.

    MEASURED 2026-09-06: work item 0 lands, work item 1's operator raises, its
    attempt produces no artifact, and ``compose_candidate`` refuses with ``work
    item 1 produced an empty patch`` (``gate1.py:543``) -- so the half-composed
    tree never reaches the Fourfold compile, the checks, or the packet. The
    source stays byte-identical, restarting over the same workspace is refused,
    and the fresh-workspace restart replays digest-identically.
    """

    source = _fixture_copy(tmp_path)
    source_before = _file_map(source)
    fixture_before = tree_digest(FIXTURE)
    real_operator = gate1.rename_operator
    calls = {"n": 0}

    def crashing(paths, **kwargs):
        inner = real_operator(paths, **kwargs)

        def _run(ctx):
            calls["n"] += 1
            if calls["n"] > 1:
                raise OSError("simulated crash between rename writes")
            return inner(ctx)

        _run.__module__ = "daedalus.ignition.gate1"
        _run.__qualname__ = "rename_operator"
        return _run

    monkeypatch.setattr(gate1, "rename_operator", crashing)
    workspace = tmp_path / "ws"
    with pytest.raises(IgnitionError, match="produced an empty patch"):
        door(
            fixture_root=source,
            receipt_root=tmp_path / "receipts",
            workspace=workspace,
        )
    monkeypatch.setattr(gate1, "rename_operator", real_operator)

    # both attempts were reached, and the second one is the one that died
    assert calls["n"] == 2
    # no candidate was ever evaluated: no receipt, no packet
    assert not (
        tmp_path / "receipts" / gate1.SESSION_MISSION_ID / "receipt.json"
    ).exists(), "a refused run must not leave a receipt claiming a Gate-1 result"
    # the source tree was never touched -- neither the copy nor the repository's
    assert _file_map(source) == source_before
    assert tree_digest(FIXTURE) == fixture_before

    # the partial workspace is never reused: restart over it refuses...
    with pytest.raises(IgnitionError, match="must not already exist"):
        door(
            fixture_root=source,
            receipt_root=tmp_path / "receipts",
            workspace=workspace,
        )

    # ...and the fresh-workspace restart replays digest-identically
    first, second = gate1_replay
    assert (
        first.result.candidate_source_tree.ref.sha256
        == second.result.candidate_source_tree.ref.sha256
    )
    assert first.result.candidate_snapshot.digest == second.result.candidate_snapshot.digest
    assert second.result.receipt["replay"]["replay_demonstrated"] is True
