"""Gate-1 ignition, green path and identity -- asserted about the SHIPPED door.

Each node below is one row of the matrix `docs/work-packets/
G1_ACTIVATION_CHECKLIST.md` §1 cites. Until G1-RENOVATION-02A they were
asserted about `daedalus.ignition.runner.run_voltage_ignition`, the in-process
rehearsal with synthetic `"1"*40` revisions, which `python -m daedalus.ignition`
does not call [MEASURED 2026-09-06, G1-RENOVATION-01 §3 finding 1]. The rows are
the same; the subject is now `run_gate1_ignition`.
"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.ignition import gate1
from daedalus.ignition.runner import tree_digest
from daedalus.kernel.approvals import (
    ApprovalBindingMismatch,
    ApprovalExpectation,
    issue_owner_approval,
    verify_owner_approval,
)
from daedalus.kernel.source_trees import SourceTreeStore
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha
from daedalus.twin import compile_reference_project

#: The fixture that plays the target project -- the door's own default,
#: named through :mod:`daedalus.ignition.gate1` so a move cannot leave this
#: directory pointing at a path that no longer exists.
FIXTURE = gate1.DEFAULT_FIXTURE

NOW = "2026-09-06T00:00:00Z"
SECRET = b"owner-secret-material-must-be-at-least-thirty-two-bytes"


def test_gate1_voltage_rename_builds_real_fourfold_delta_and_evidence(
    gate1_replay, door_exit_code
) -> None:
    """One run of the door: the fixture is untouched, the candidate is a
    different tree with a different Twin, the delta has additions AND removals,
    the rename actually landed, and the packet that comes out validates.

    The runner version of this row asserted the same properties about values it
    returned in memory. The door's are content-addressed: the candidate
    artifact the packet names IS the ``StoredSourceTree`` the run put in CAS,
    which is half of what checklist §2.2 was open on.
    """

    run, _ = gate1_replay
    result = run.result
    receipt = result.receipt

    # the repository fixture is never written
    assert receipt["replay"]["fixture_tree_sha256"] == tree_digest(FIXTURE)

    # base and candidate are different trees with different Twins
    assert (
        receipt["fourfold"]["base_source_bundle_sha256"]
        != receipt["fourfold"]["candidate_source_bundle_sha256"]
    )
    assert (
        receipt["fourfold"]["base_snapshot_sha256"]
        != receipt["fourfold"]["candidate_snapshot_sha256"]
    )
    assert result.base_source_tree.ref.sha256 != result.candidate_source_tree.ref.sha256

    # the delta is observable in both directions
    assert result.graph_delta.added_nodes
    assert result.graph_delta.removed_nodes

    # one EvidencePacket, passed, bound to the stored candidate tree
    assert result.packet is not None
    assert result.packet.evaluation_status == "passed"
    assert result.packet.candidate_artifact_sha256 == result.candidate_source_tree.ref.sha256
    assert result.candidate_source_tree.ref.locator.startswith("artifact-locator:sha256:")
    assert {item.evaluator for item in result.packet.items} >= {
        "fourfold.snapshot-binding",
        "ignition-behavior",
        "ignition-graph-delta",
    }
    assert receipt["check_kinds"] == ["link", "pytest", "schema"]
    assert door_exit_code(result) == 0

    # and the rename landed in the candidate tree the attempts composed
    candidate = run.candidate_root
    assert "bias_voltage" in (candidate / "src/ignition_app/models.py").read_text(encoding="utf-8")
    assert "id,bias_voltage" in (candidate / "data/events.csv").read_text(encoding="utf-8")
    assert '"bias_voltage"' in (candidate / "schemas/event.schema.json").read_text(encoding="utf-8")
    assert "`voltage`" not in (candidate / "wiki/Event.md").read_text(encoding="utf-8")


def test_gate1_replay_is_digest_identical(gate1_replay, door_exit_code) -> None:
    """Two runs of the door from identical inputs agree on every identity the
    slice claims to be deterministic in -- and the receipt SAYS the replay was
    demonstrated, which since G1-RENOVATION-02A is what the exit code means."""

    first, second = gate1_replay
    assert (
        first.result.candidate_source_tree.ref.sha256
        == second.result.candidate_source_tree.ref.sha256
    )
    assert first.result.candidate_snapshot.digest == second.result.candidate_snapshot.digest
    assert first.result.graph_delta.digest == second.result.graph_delta.digest
    # NOT ``tree_digest(candidate_root)``: the composed tree is the evaluators'
    # working directory as well as their subject, and they leave ``__pycache__``
    # and ``.pytest_cache`` in it (MEASURED 2026-09-06: two runs' post-run
    # candidate roots digest differently while every artifact identity above
    # matches). The CAS artifact is captured immediately after composition, so
    # ``candidate_source_tree.ref.sha256`` is the composed tree's identity and
    # the post-run directory is not.

    replay = second.result.receipt["replay"]
    assert replay["is_replay"] is True
    assert replay["previous_run_complete"] is True
    assert replay["same_evaluator_bundle"] is True
    assert replay["same_fixture"] is True
    for name in gate1.REPLAY_REQUIRED_STABLE:
        assert replay[name] is True, name
    assert replay["replay_demonstrated"] is True
    assert list(second.result.blockers) == []
    assert door_exit_code(second.result) == 0


def test_gate1_owner_approval_binds_exact_candidate_and_evidence(gate1_replay) -> None:
    """An OwnerApproval binds THIS candidate and THIS packet; a mismatched
    expectation refuses. Nothing is consumed and nothing is promoted.

    Ported unchanged except for what it binds: the runner's in-memory bundle
    digest and its ``"1"*40`` base revision are now the door's CAS artifact
    sha256 and the real resolved git revision of the prepared base repository.
    Checklist §2.6 remains open -- this is still the schema-level bind/verify
    pair, not a dry-run against the sealed ``promote_candidates`` stack.
    """

    run, _ = gate1_replay
    result = run.result
    assert result.packet is not None
    base_revision = result.receipt["replay"]["base_revision"]
    candidate_sha = result.candidate_source_tree.ref.sha256
    packet_sha = result.packet.digest

    nomination = canonical_sha({"nomination": "gate1"})
    now = datetime.fromisoformat(NOW.replace("Z", "+00:00")).astimezone(timezone.utc)
    approval = issue_owner_approval(
        approval_id="gate1-approval",
        owner_id="KTY137",
        key_id="owner-key",
        operation="promote-candidate",
        nomination_receipt_sha256=nomination,
        candidate_artifact_sha256=candidate_sha,
        evidence_packet_sha256=packet_sha,
        base_revision=base_revision,
        target_ref="experimental",
        expected_target_revision="3" * 40,
        nonce="gate1-nonce",
        issued_at=now.isoformat(),
        expires_at=(now + timedelta(minutes=10)).isoformat(),
        provenance=ContractProvenance(
            origin="tests.gate1.approval",
            source_revision=base_revision,
            created_at=now.isoformat(),
            input_digests=(nomination, candidate_sha, packet_sha),
        ),
        secret=SECRET,
    )
    expectation = ApprovalExpectation(
        operation="promote-candidate",
        nomination_receipt_sha256=nomination,
        candidate_artifact_sha256=candidate_sha,
        evidence_packet_sha256=packet_sha,
        base_revision=base_revision,
        target_ref="experimental",
        current_target_revision="3" * 40,
    )
    verified = verify_owner_approval(
        approval,
        keyring={("KTY137", "owner-key"): SECRET},
        expectation=expectation,
        now=now + timedelta(seconds=1),
    )
    assert verified.candidate_artifact_sha256 == candidate_sha
    assert verified.evidence_packet_sha256 == packet_sha

    with pytest.raises(ApprovalBindingMismatch, match="candidate_artifact_sha256"):
        verify_owner_approval(
            approval,
            keyring={("KTY137", "owner-key"): SECRET},
            expectation=ApprovalExpectation(
                **{**expectation.__dict__, "candidate_artifact_sha256": "f" * 64}
            ),
            now=now + timedelta(seconds=1),
        )

    # nothing was consumed and nothing was promoted by any of this
    assert result.receipt["promotion"]["status"] == "nominated, not promoted"
    assert result.receipt["promotion"]["auto_merge"] is False
    assert result.receipt["promotion"]["owner_approval"] == "not requested"


def test_gate1_candidate_revision_is_part_of_snapshot_identity(gate1_replay, tmp_path) -> None:
    """The candidate revision is part of the Twin's identity -- and the door
    DERIVES it from the tree instead of accepting it.

    The runner took ``candidate_revision`` as an argument, so this row could
    vary it directly. ``run_gate1_ignition`` computes it: ``candidate_digest =
    tree_digest(candidate_root)`` (``gate1.py:991``), handed to
    ``compile_reference_project`` (``gate1.py:1015``) and to ``capture_tree``
    (``gate1.py:992``). The row is asserted at that seam. The first half -- the
    recorded revision IS the content digest of the tree the receipt points a
    reader at, so nothing can assert it into agreement -- is the stronger
    claim, and only the door can make it.

    The digest is read back from CAS rather than from the workspace on purpose:
    the composed tree is also the evaluators' working directory, and by the end
    of the run it carries their ``__pycache__``/``.pytest_cache`` debris. The
    stored tree is what the receipt actually offers a reader.
    """

    run, _ = gate1_replay
    receipt = run.result.receipt
    stored = run.result.candidate_source_tree
    candidate_revision = receipt["replay"]["candidate_revision"]

    assert stored.manifest.source_revision == candidate_revision
    assert candidate_revision != receipt["replay"]["base_revision"]

    store = SourceTreeStore.open_existing(receipt["source_trees"]["store_root"])
    restored = tmp_path / "restored"
    store.materialize_tree(stored.ref, restored)
    assert tree_digest(restored) == candidate_revision

    # ...and the revision is bound into the snapshot, not carried beside it
    tree = tmp_path / "project"
    shutil.copytree(restored, tree)
    first = compile_reference_project(
        tree, source_revision="a" * 64, created_at=NOW, trace_id="candidate-identity"
    )
    second = compile_reference_project(
        tree, source_revision="b" * 64, created_at=NOW, trace_id="candidate-identity"
    )
    assert first.source_bundle_sha256 == second.source_bundle_sha256
    assert first.snapshot.digest != second.snapshot.digest
