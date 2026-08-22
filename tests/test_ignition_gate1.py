"""Gate-1 ignition slice: the sentences of plan §10 Gate 1, as assertions.

WHAT EACH TEST IS FOR
---------------------
Every test here names one clause of the Gate-1 paragraph and fails if that
clause stops being true:

* one MissionContract, with exactly two work items;
* both attempts produce an AttemptContract and an AttemptReceipt;
* the EvidencePacket validates and names the three check kinds;
* replay is deterministic in the things that are supposed to be deterministic;
* promotion status is never "promoted".

The slice is run ONCE per module. It writes nothing into the repository: the
target project is a temp git repo, and the receipts and the content-addressed
store go to ``tmp_path_factory``.

THE GUARD TESTS ARE THE POINT OF THE REST. ``test_assurance_*`` and
``test_check_*_goes_red_*`` disable, invert or corrupt one condition each and
require the corresponding verdict to flip. A green suite in which those cannot
go red would mean the checks measure nothing.
"""
from __future__ import annotations

import json
import shutil

import pytest

from daedalus.ignition import checks as ignition_checks
from daedalus.ignition import gate1
from daedalus.schemas import EvidencePacket, MissionContract


# --------------------------------------------------------------------------- #
# the one expensive run                                                        #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def slice_result(tmp_path_factory):
    receipts = tmp_path_factory.mktemp("ignition-receipts")
    return gate1.run_gate1_ignition(
        receipt_root=receipts,
        collected_at="2026-08-22T00:00:00Z",
    )


@pytest.fixture(scope="module")
def replayed(tmp_path_factory):
    """The same inputs, run twice into the same receipt directory."""

    receipts = tmp_path_factory.mktemp("ignition-replay")
    first = gate1.run_gate1_ignition(
        receipt_root=receipts, collected_at="2026-08-22T00:00:00Z"
    )
    second = gate1.run_gate1_ignition(
        receipt_root=receipts, collected_at="2026-08-22T00:00:00Z"
    )
    return first, second


# --------------------------------------------------------------------------- #
# "Ikarus produces one MissionContract"                                        #
# --------------------------------------------------------------------------- #
def test_slice_yields_one_validating_mission_contract(slice_result):
    mission = slice_result.mission
    assert isinstance(mission, MissionContract)
    # Round-tripping through the contract's own reader is the validation: a
    # record that was assembled loosely fails to reconstruct.
    assert MissionContract.from_dict(mission.to_dict()).digest == mission.digest
    assert mission.mission_id == "mission-gate1-voltage-ignition"
    assert mission.provenance.origin == "daedalus.build"


def test_mission_names_exactly_two_work_items(slice_result):
    assert len(slice_result.mission.work_item_ids) == 2
    assert set(slice_result.mission.work_item_ids) == set(slice_result.work_item_ids)


def test_work_item_ids_are_derived_not_written(slice_result):
    # derive_work_item_id's shape: wi-<ordinal>-<12 hex>. A hand-written id
    # ("rename-code-type", which is what the slice used to carry) fails here.
    for ordinal, work_item_id in enumerate(sorted(slice_result.work_item_ids)):
        prefix, index, digest = work_item_id.split("-")
        assert prefix == "wi"
        assert index == f"{ordinal:03d}"
        assert len(digest) == 12 and int(digest, 16) >= 0


def test_work_items_come_from_the_four_plane_manifest(tmp_path):
    repo, _ = gate1.prepare_ignition_repo(gate1.DEFAULT_FIXTURE, tmp_path / "target")
    planned = gate1.plan_work_items(repo)
    assert [item.planes for item in planned] == [("code", "type"), ("data", "knowledge")]
    manifest = json.loads((repo / "fourfold.json").read_text(encoding="utf-8"))
    declared = {
        *manifest["code_files"], *manifest["data_files"], *manifest["knowledge_files"],
        "fourfold.json",
    }
    for item in planned:
        assert set(item.paths) <= declared


def test_plan_refuses_a_manifest_whose_code_plane_lost_the_symbol(tmp_path):
    """Disable the derivation's precondition and it must refuse, not invent."""

    repo, _ = gate1.prepare_ignition_repo(gate1.DEFAULT_FIXTURE, tmp_path / "target")
    for rel in ("src/ignition_app/models.py", "src/ignition_app/repository.py"):
        path = repo / rel
        path.write_text(
            path.read_text(encoding="utf-8").replace("voltage", "already_renamed"),
            encoding="utf-8",
        )
    with pytest.raises(gate1.IgnitionError):
        gate1.plan_work_items(repo)


# --------------------------------------------------------------------------- #
# "attempts run in isolation"                                                  #
# --------------------------------------------------------------------------- #
def test_both_attempts_produce_an_attempt_contract_and_receipt(slice_result):
    rows = slice_result.receipt["attempts"]
    assert len(rows) == 2
    for row in rows:
        assert row["state"] == "clean"
        assert row["contracts_error"] is None
        assert row["attempt_contract_sha256"] and len(row["attempt_contract_sha256"]) == 64
        assert row["attempt_receipt_sha256"] and len(row["attempt_receipt_sha256"]) == 64
        assert row["policy_decision_sha256"] and row["policy_verdict"] == "allow"
        assert row["evidence_packet_sha256"]


def test_each_attempt_stayed_inside_its_declared_write_scope(slice_result):
    for row in slice_result.receipt["attempts"]:
        assert set(row["changed_paths"]) <= set(row["target_paths"])
        assert row["changed_paths"], "an attempt that changed nothing gated nothing"


def test_each_attempt_persisted_its_patch_to_the_content_addressed_store(slice_result):
    for row in slice_result.receipt["attempts"]:
        assert row["patch_sha256"]
        assert str(row["patch_locator"]).startswith("artifact-locator:sha256:")


def test_the_repository_fixture_is_never_written(slice_result):
    fixture_now = gate1.tree_digest(gate1.DEFAULT_FIXTURE)
    assert slice_result.receipt["replay"]["fixture_tree_sha256"] == fixture_now


# --------------------------------------------------------------------------- #
# "tests, schema checks and link checks produce an EvidencePacket"             #
# --------------------------------------------------------------------------- #
def test_evidence_packet_validates(slice_result):
    packet = slice_result.packet
    assert isinstance(packet, EvidencePacket)
    assert EvidencePacket.from_dict(packet.to_dict()).digest == packet.digest
    assert packet.evaluation_status == "passed"
    assert packet.mission_id == slice_result.mission.mission_id


def test_evidence_packet_names_the_three_check_kinds(slice_result):
    assert slice_result.receipt["check_kinds"] == ["link", "pytest", "schema"]
    ids = {item.evidence_id for item in slice_result.packet.items}
    assert {"gate1-check-pytest", "gate1-check-schema", "gate1-check-links"} <= ids


def test_every_evidence_locator_resolves_to_stored_bytes(slice_result, tmp_path):
    """A locator is a promise that the bytes are re-readable. Read them."""

    from daedalus.storage import ArtifactStore

    store = ArtifactStore(slice_result.receipt_path.parent / "store")
    for item in slice_result.packet.items:
        if item.evaluator == "fourfold.snapshot-binding":
            continue  # the snapshot's locator is minted by the kernel, not stored here
        digest = item.evidence_locator.rsplit(":", 1)[-1]
        assert store.locator_path(digest).exists(), item.evidence_id


def test_evidence_packet_binds_both_attempts(slice_result):
    binding = next(
        item for item in slice_result.packet.items
        if item.evidence_id == "gate1-attempt-binding"
    )
    bound = {row["work_item_id"] for row in binding.details["detail"]["attempts"]}
    assert bound == set(slice_result.work_item_ids)


def test_packet_records_the_attempt_packets_real_status(slice_result):
    """The weak part is reported, not laundered into the Gate-1 packet."""

    binding = next(
        item for item in slice_result.packet.items
        if item.evidence_id == "gate1-attempt-binding"
    )
    for row in binding.details["detail"]["attempts"]:
        assert row["evidence_status"] in {"passed", "inconclusive"}
        assert isinstance(row["evidence_assurance"], list)


# --------------------------------------------------------------------------- #
# restart / replay                                                             #
# --------------------------------------------------------------------------- #
def test_replay_is_deterministic_in_identity(replayed):
    first, second = replayed
    assert second.mission.mission_id == first.mission.mission_id
    assert second.work_item_ids == first.work_item_ids
    replay = second.receipt["replay"]
    assert replay["is_replay"] is True
    assert replay["mission_id_stable"] is True
    assert replay["work_item_ids_stable"] is True
    assert replay["base_revision_stable"] is True
    assert replay["candidate_revision_stable"] is True
    assert replay["graph_delta_stable"] is True
    assert replay["check_reports_stable"] is True


def test_replay_does_not_claim_a_stable_packet_digest(replayed):
    """The one thing that is NOT stable is recorded as not stable.

    Evidence items bind raw evaluator output and pytest prints its own duration.
    A receipt claiming otherwise would be a false determinism claim, which is
    worse than the instability.
    """

    _, second = replayed
    assert second.receipt["replay"]["packet_sha256_stable"] is False


def test_attempt_ids_are_expected_to_differ_between_runs(replayed):
    first, second = replayed
    assert set(first.attempt_ids).isdisjoint(second.attempt_ids)


# --------------------------------------------------------------------------- #
# "no auto-merge"                                                              #
# --------------------------------------------------------------------------- #
def test_promotion_status_is_never_promoted(slice_result):
    promotion = slice_result.receipt["promotion"]
    assert promotion["status"] == "nominated, not promoted"
    assert promotion["auto_merge"] is False
    assert promotion["owner_approval"] == "not requested"


def test_the_slice_imports_no_promotion_machinery():
    """The import GRAPH, not a substring: prose about promotion is allowed.

    An earlier version of this test grepped the file and passed only because the
    docstring says "imports nothing from daedalus.kernel.promotion" -- the same
    sentence that would have made a real import invisible to it.
    """

    import ast

    tree = ast.parse(
        (gate1.ROOT / "daedalus" / "ignition" / "gate1.py").read_text(encoding="utf-8")
    )
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            imported.add(base)
            imported.update(f"{base}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if name:
                called.add(name)
    assert not [name for name in imported if "promotion" in name or "approval" in name]
    assert not [name for name in called if "promote" in name.lower()]


# --------------------------------------------------------------------------- #
# the assurance rule -- disable a condition, the verdict must fall             #
# --------------------------------------------------------------------------- #
def _report(kind, criterion, subject=("x",)):
    return ignition_checks.CheckReport(
        kind=kind, evaluator=f"ignition-{kind}", passed=True,
        criterion_paths=tuple(criterion), subject_paths=tuple(subject),
        detail={}, output="",
    )


def test_assurance_is_deterministic_when_a_criterion_is_frozen_outside_scope():
    assurance, _, problem = gate1._derive_assurance(
        [_report("pytest", ("tests/test_event_field.py",)), _report("schema", ())],
        ["data/events.csv"],
    )
    assert assurance == "deterministic" and problem is None


def test_assurance_falls_when_the_criterion_is_inside_the_write_scope():
    assurance, reason, problem = gate1._derive_assurance(
        [_report("pytest", ("tests/test_event_field.py",))],
        ["tests/test_event_field.py"],
    )
    assert assurance == "unverified"
    assert "target_paths" in reason and problem


def test_assurance_falls_when_no_check_is_anchored():
    """Schema and link checks alone cannot tell a right rename from a wrong one."""

    assurance, reason, problem = gate1._derive_assurance(
        [_report("schema", ()), _report("link", ())],
        ["data/events.csv"],
    )
    assert assurance == "unverified"
    assert "outside the candidate's write scope" in reason and problem


def test_an_unverified_assurance_prevents_the_packet(slice_result):
    """The kernel refuses the packet rather than downgrading it -- confirm it."""

    from daedalus.schemas import EvidenceItem

    item = slice_result.packet.items[0]
    with pytest.raises(ValueError):
        EvidencePacket(
            **{
                **{
                    field: getattr(slice_result.packet, field)
                    for field in (
                        "packet_id", "mission_id", "attempt_id", "source_revision",
                        "attempt_contract_sha256", "subject_sha256",
                        "policy_decision_sha256", "usage", "provenance",
                        "candidate_artifact_sha256", "candidate_artifact_locator",
                    )
                },
                "evaluation_status": "passed",
                "items": (
                    EvidenceItem(
                        **{
                            **{
                                field: getattr(item, field)
                                for field in (
                                    "evidence_id", "evaluator", "verdict",
                                    "output_sha256", "evidence_locator",
                                    "collected_at", "provenance", "details",
                                )
                            },
                            "assurance": "unverified",
                        }
                    ),
                ),
            }
        )


# --------------------------------------------------------------------------- #
# each check must be able to go red                                            #
# --------------------------------------------------------------------------- #
def test_check_pytest_goes_red_on_the_base_revision(slice_result):
    control = slice_result.receipt["discrimination"]["negative_controls"]
    assert control["pytest.base_revision"]["passed"] is False


def test_check_schema_goes_red_on_a_half_finished_rename(slice_result):
    control = slice_result.receipt["discrimination"]["negative_controls"]
    assert control["schema.half_renamed"]["passed"] is False
    assert control["schema.half_renamed"]["problems"]


def test_check_link_goes_red_on_a_missing_target(slice_result):
    control = slice_result.receipt["discrimination"]["negative_controls"]
    assert control["link.missing_target"]["passed"] is False


def test_schema_check_goes_red_when_only_the_csv_is_renamed(tmp_path):
    tree = tmp_path / "tree"
    shutil.copytree(gate1.DEFAULT_FIXTURE, tree)
    csv_path = tree / "data" / "events.csv"
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8").replace("voltage", "bias_voltage"),
        encoding="utf-8",
    )
    assert gate1.plan_work_items  # the module under test, not a stale import
    report = ignition_checks.schema_check(tree)
    assert report.passed is False
    assert any("bias_voltage" in problem for problem in report.detail["problems"])


def test_schema_check_is_green_on_the_untouched_fixture(tmp_path):
    """The control above is only meaningful if the check passes when it should."""

    tree = tmp_path / "tree"
    shutil.copytree(gate1.DEFAULT_FIXTURE, tree)
    assert ignition_checks.schema_check(tree).passed is True


def test_link_check_refuses_a_document_with_no_links(tmp_path):
    """A check that judged nothing must not report green."""

    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "wiki").mkdir()
    (tree / "wiki" / "Event.md").write_text("# Event\n\nno links here\n", encoding="utf-8")
    report = ignition_checks.link_check(tree)
    assert report.passed is False


# --------------------------------------------------------------------------- #
# the operator                                                                 #
# --------------------------------------------------------------------------- #
def test_rename_operator_refuses_a_path_without_the_symbol(tmp_path):
    from daedalus.spine.attempt import RunnerContext, TaskSpec

    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "empty.py").write_text("x = 1\n", encoding="utf-8")
    ctx = RunnerContext(
        worktree=tree, branch="b", base_revision="0" * 40,
        task=TaskSpec(task_id="t", instruction="i"), is_cancelled=lambda: False,
    )
    with pytest.raises(gate1.IgnitionError):
        gate1.rename_operator(["empty.py"])(ctx)


def test_rename_operator_writes_only_the_paths_it_was_given(tmp_path):
    from daedalus.spine.attempt import RunnerContext, TaskSpec

    tree = tmp_path / "tree"
    shutil.copytree(gate1.DEFAULT_FIXTURE, tree)
    before = {
        path: path.read_bytes()
        for path in tree.rglob("*") if path.is_file()
    }
    ctx = RunnerContext(
        worktree=tree, branch="b", base_revision="0" * 40,
        task=TaskSpec(task_id="t", instruction="i"), is_cancelled=lambda: False,
    )
    gate1.rename_operator(["data/events.csv"])(ctx)
    changed = [
        path for path, data in before.items() if path.read_bytes() != data
    ]
    assert [p.name for p in changed] == ["events.csv"]


# --------------------------------------------------------------------------- #
# a half-finished rename must refuse, and must still leave a receipt           #
# --------------------------------------------------------------------------- #
def test_a_half_finished_rename_is_refused_and_still_writes_a_receipt(
    tmp_path, monkeypatch
):
    """Drop one file from a work item's scope; the slice must go red, not green.

    MEASURED, three independent layers deep: the data work item's own attempt
    gate fails (the schema check sees a CSV field the schema does not declare),
    AND the candidate Fourfold refuses to compile (the manifest claims a schema
    field the schema does not have). Either alone would be enough; both firing
    is what makes the green run mean something.

    The receipt is the assertion that matters. A run that raised instead would
    leave nothing behind saying why.
    """

    from dataclasses import replace as _replace

    original = gate1.plan_work_items

    def crippled(root, **kwargs):
        items = original(root, **kwargs)
        data_item = items[1]
        return (
            items[0],
            _replace(
                data_item,
                paths=tuple(p for p in data_item.paths if "schema" not in p),
            ),
        )

    monkeypatch.setattr(gate1, "plan_work_items", crippled)
    result = gate1.run_gate1_ignition(
        receipt_root=tmp_path / "receipts", collected_at="2026-08-22T00:00:00Z"
    )
    assert result.packet is None
    assert result.receipt_path.exists()
    assert result.receipt["schema"] == "daedalus-gate1-ignition-receipt/1"
    assert result.receipt["evidence_packet"]["packet_sha256"] is None
    assert any("does not compile" in blocker for blocker in result.blockers)
    assert any("did not produce a gated candidate" in b for b in result.blockers)
    assert result.receipt["promotion"]["status"] == "nominated, not promoted"


# --------------------------------------------------------------------------- #
# the measured kernel gap                                                      #
# --------------------------------------------------------------------------- #
def test_the_blocker_is_measured_not_asserted(slice_result):
    """It names the gap while the gap exists, and disappears when it closes."""

    blocker = slice_result.receipt["blocker"]
    weak = [
        row for row in slice_result.receipt["attempts"]
        if row["evidence_status"] != "passed"
        or "unverified" in (row["evidence_assurance"] or [])
    ]
    if weak:
        assert blocker and "evaluator_assurance" in blocker["missing_api"]
        assert blocker["hunk"].startswith("--- a/daedalus/spine/receipts.py")
        assert len(blocker["measured"]) == len(weak)
    else:
        assert blocker is None
