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
difference was the late, dirty F5 refusal, retained as the negative baseline
in G1-IGNITION-03. The shipped door now admits its layout before writing;
these rows assert early source and prior-evidence preservation.

G1-IGNITION-04 adds unknown compiler diagnostics after real source capture,
including refusal to invent evidence when an actual attempt binding is absent.
"""
from __future__ import annotations

import hashlib
import json
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
    mission = tmp_path / "receipts" / gate1.SESSION_MISSION_ID
    for name in ("store/blobs", "store/locators", "source-trees/objects"):
        directory = mission / name
        directory.mkdir(parents=True)
        (directory / "prior").write_bytes(b"retained evidence")
    (mission / "receipt.json").write_bytes(b'{"previous":true}\n')
    retained_before = _file_map(mission)

    with pytest.raises(IgnitionError, match="workspace must be empty"):
        door(
            receipt_root=tmp_path / "receipts",
            workspace=workspace,
        )

    # the refusal itself performed no effect: debris kept, fixture untouched,
    # prior receipts and evidence retained
    assert (debris / "partial.py").read_text(encoding="utf-8") == "leftover = True\n"
    assert sorted(p.name for p in debris.iterdir()) == ["partial.py"]
    assert tree_digest(FIXTURE) == fixture_before
    assert _file_map(mission) == retained_before

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
    """The real shipped F5 invocation refuses before leaving any scratch debris.

    G1-IGNITION-03 retains the original late-pollution baseline. This is still
    entry-time admission, not a same-attempt recovery or concurrent-swap claim.
    """

    source = _fixture_copy(tmp_path)
    declared_before = _file_map(source)
    with pytest.raises(IgnitionError, match="workspace conflicts with source"):
        door(fixture_root=source, receipt_root=tmp_path / "receipts", workspace=source)
    assert _file_map(source) == declared_before
    assert not (tmp_path / "receipts").exists()


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
    with pytest.raises(IgnitionError, match="workspace must be empty"):
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


_UNKNOWN_COMPILE_MESSAGE = "G1-IGNITION-04 unknown compiler infrastructure fault"


@pytest.fixture(scope="module", params=(False, True), ids=("bound", "missing-binding"))
def unknown_candidate_compile(request, tmp_path_factory, door):
    """Two real door runs total, shared by the diagnostic/retention assertions.

    Base compilation, both attempts and source capture run normally. Only the
    candidate compiler raises an unknown infrastructure error. The second case
    additionally withholds one actual contract-set read to prove that absent
    binding data cannot be replaced with invented evidence authority.
    """
    from daedalus.kernel.attempt_execution import AttemptResult
    from daedalus.kernel.source_trees import SourceTreeStore
    from daedalus.storage import ArtifactStore

    case_root = tmp_path_factory.mktemp("unknown-candidate-compile")
    source = _fixture_copy(case_root)
    source_before = _file_map(source)
    fixture_before = tree_digest(FIXTURE)
    receipts = case_root / "receipts"
    workspace = case_root / "workspace"
    store_root = receipts / gate1.SESSION_MISSION_ID / "store"
    store = ArtifactStore(store_root)
    prior_bytes = b"an earlier evidence observation must survive compiler refusal\n"
    prior = store.put_bytes(
        prior_bytes,
        metadata={"kind": "prior-compiler-fault-control"},
        provenance={
            "origin": "tests.ignition.compiler-fault-retention",
            "source_revision": fixture_before,
            "created_at": "2026-09-06T00:00:00Z",
            "input_digests": [hashlib.sha256(prior_bytes).hexdigest()],
            "trace_id": None,
        },
    )
    prior_files = _file_map(store_root)
    captures, base_compiles, failed_inputs = [], [], []
    contract_reads, output_writes = [], {}
    real_compile = gate1.compile_reference_project
    real_capture = SourceTreeStore.capture_tree
    real_contract_set = AttemptResult.contract_set
    real_put = ArtifactStore.put_bytes

    def observe_capture(self, candidate, **kwargs):
        captured = real_capture(self, candidate, **kwargs)
        captures.append((Path(candidate), kwargs, captured))
        return captured

    def failing_candidate_compile(candidate, **kwargs):
        if kwargs.get("trace_id") == "gate1-bias-voltage-candidate":
            failed_inputs.append((Path(candidate), dict(kwargs)))
            raise RuntimeError(_UNKNOWN_COMPILE_MESSAGE)
        compiled = real_compile(candidate, **kwargs)
        base_compiles.append(compiled)
        return compiled

    def observed_contract_set(self):
        actual = real_contract_set(self)
        contract_reads.append(actual)
        if request.param and len(contract_reads) == 1:
            return None
        return actual

    def observe_put(self, data, **kwargs):
        locator = real_put(self, data, **kwargs)
        if self.root == store.root:
            output_writes[locator.locator_uri] = bytes(data)
        return locator

    with pytest.MonkeyPatch.context() as patcher:
        patcher.setattr(SourceTreeStore, "capture_tree", observe_capture)
        patcher.setattr(gate1, "compile_reference_project", failing_candidate_compile)
        patcher.setattr(AttemptResult, "contract_set", observed_contract_set)
        patcher.setattr(ArtifactStore, "put_bytes", observe_put)
        result = door(
            fixture_root=source, receipt_root=receipts, workspace=workspace,
        )
    return {
        "result": result, "source": source, "source_before": source_before,
        "fixture_before": fixture_before, "workspace": workspace,
        "store": store, "prior": prior, "prior_bytes": prior_bytes,
        "prior_files": prior_files, "captures": captures,
        "base_compiles": base_compiles, "failed_inputs": failed_inputs,
        "contract_reads": contract_reads, "output_writes": output_writes,
        "missing_binding": request.param,
    }


def test_unknown_compile_refusal_keeps_actual_attempt_and_source_identities(
    unknown_candidate_compile, door_exit_code,
):
    from daedalus.kernel.source_trees import SourceTreeStore

    case = unknown_candidate_compile
    result = case["result"]
    assert len(case["base_compiles"]) == 1
    assert all(plane.status == "complete" for plane in case["base_compiles"][0].snapshot.planes)
    assert len(case["failed_inputs"]) == 1
    candidate_path, compile_arguments = case["failed_inputs"][0]
    captured = next(
        tree for path, kwargs, tree in case["captures"]
        if kwargs.get("origin") == "daedalus.ignition.gate1-candidate"
    )
    assert candidate_path == case["workspace"] / "candidate"
    assert result.candidate_source_tree.ref == captured.ref
    assert compile_arguments["source_tree_sha256"] == captured.ref.sha256
    assert compile_arguments["source_revision"] == tree_digest(candidate_path)
    assert result.receipt["source_trees"]["candidate_sha256"] == captured.ref.sha256
    tree_store = SourceTreeStore.open_existing(result.receipt["source_trees"]["store_root"])
    assert tree_store.load_tree(captured.ref).to_dict() == captured.manifest.to_dict()
    assert result.receipt["replay"]["candidate_revision"] == compile_arguments["source_revision"]
    assert len(case["contract_reads"]) == 2
    assert all(contracts is not None and contracts.complete for contracts in case["contract_reads"])
    assert tuple(c.attempt.attempt_id for c in case["contract_reads"]) == result.attempt_ids
    assert all(row["gate_passed"] is True for row in result.receipt["attempts"])
    assert sum(c is None for c in result.attempt_contract_sets) == int(case["missing_binding"])
    assert result.candidate_snapshot is None
    assert result.receipt["fourfold"]["base_snapshot_sha256"] == case["base_compiles"][0].snapshot.digest
    for field in ("candidate_source_bundle_sha256", "candidate_snapshot_sha256",
                  "graph_delta", "graph_delta_sha256"):
        assert result.receipt["fourfold"][field] is None
    assert all(not nodes for nodes in result.graph_delta.to_dict().values())
    assert any(_UNKNOWN_COMPILE_MESSAGE in blocker for blocker in result.blockers)
    assert result.receipt["replay"]["replay_demonstrated"] is False
    assert door_exit_code(result) == 1
    assert _file_map(case["source"]) == case["source_before"]
    assert tree_digest(FIXTURE) == case["fixture_before"]


def test_unknown_compile_refusal_persists_only_a_truthfully_bound_diagnostic(
    unknown_candidate_compile,
):
    from daedalus.kernel.fourfold_evidence import FOURFOLD_EVALUATOR
    from daedalus.schemas import EvidencePacket
    from daedalus.spine.envelope import canonical_sha

    case = unknown_candidate_compile
    result, store = case["result"], case["store"]
    projection = result.receipt["evidence_packet"]
    if case["missing_binding"]:
        assert result.packet is None
        assert projection["packet_sha256"] is None
        assert projection.get("packet_locator") is None
        assert projection.get("evaluation_status") is None
        assert any("contract" in blocker.lower() for blocker in result.blockers)
        assert projection["error"], "packet absence must carry a named refusal"
        return

    packet = result.packet
    assert isinstance(packet, EvidencePacket)
    assert packet.evaluation_status == "inconclusive"
    assert EvidencePacket.from_dict(packet.to_dict()).digest == packet.digest
    assert packet.source_revision == case["failed_inputs"][0][1]["source_revision"]
    assert packet.subject_sha256 == result.candidate_source_tree.ref.sha256
    assert packet.candidate_artifact_sha256 == result.candidate_source_tree.ref.sha256
    assert packet.candidate_artifact_locator == result.candidate_source_tree.ref.locator
    for field, member in [("attempt_contract_sha256", "attempt"),
                          ("policy_decision_sha256", "policy")]:
        expected = canonical_sha({
            "schema": f"daedalus-ignition-{member}-chain/1",
            "digests": [getattr(c, member).digest for c in case["contract_reads"]],
        })
        assert getattr(packet, field) == expected
    assert all(item.evaluator != FOURFOLD_EVALUATOR for item in packet.items)
    diagnostics = []
    for item in packet.items:
        locator = store.load_locator(item.evidence_locator.rsplit(":", 1)[-1])
        store.verify(locator)
        payload = store.get_bytes(locator.artifact_sha256)
        assert payload == case["output_writes"][item.evidence_locator]
        assert hashlib.sha256(payload).hexdigest() == item.output_sha256
        if _UNKNOWN_COMPILE_MESSAGE.encode() in payload:
            diagnostics.append(item)
            assert b"RuntimeError" in payload
            assert item.verdict == "error"
            assert item.assurance == "unverified"
            assert item.provenance.source_revision == packet.source_revision
    assert diagnostics, "the actual compiler exception bytes must remain retrievable"
    portable = projection["packet_locator"]
    packet_locator = store.load_locator(portable["locator_uri"].rsplit(":", 1)[-1])
    store.verify(packet_locator)
    assert portable == packet_locator.portable_summary()
    assert packet_locator.artifact_sha256 == packet.digest
    assert store.get_bytes(packet_locator.artifact_sha256) == packet.to_json().encode("utf-8")
    assert projection["packet_sha256"] == packet.digest
    assert projection["evaluation_status"] == "inconclusive"


def test_unknown_compile_refusal_retains_prior_evidence_without_nomination(
    unknown_candidate_compile,
):
    case = unknown_candidate_compile
    result, store = case["result"], case["store"]
    for relative, old_bytes in case["prior_files"].items():
        assert (store.root / relative).read_bytes() == old_bytes
    retained = store.load_locator(case["prior"].locator_sha256)
    store.verify(retained)
    assert retained.manifest_bytes == case["prior"].manifest_bytes
    assert store.get_bytes(retained.artifact_sha256) == case["prior_bytes"]
    assert result.receipt["promotion"]["status"] == "refused, not promoted"
    assert result.receipt["promotion"]["auto_merge"] is False
    assert json.loads(result.receipt_path.read_bytes()) == result.receipt
