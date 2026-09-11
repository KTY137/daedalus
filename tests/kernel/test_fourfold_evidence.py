from __future__ import annotations

import dataclasses
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from daedalus.kernel.fourfold_evidence import (
    FOURFOLD_EVALUATOR,
    FourfoldEvidenceExpectation,
    FourfoldEvidenceMismatch,
    FourfoldEvidenceUnstorable,
    assemble_fourfold_evidence_packet,
    verify_fourfold_evidence_packet,
)
from daedalus.kernel.source_trees import SourceTreeStore
from daedalus.schemas import (
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    ResourceUsage,
)
from daedalus.spine.envelope import canonical_sha
from daedalus.storage import ArtifactStore
from daedalus.twin import compile_reference_project

REVISION = "b" * 40
OTHER_REVISION = "c" * 40
NOW = "2026-08-01T21:30:00Z"
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"
ATTEMPT_SHA = canonical_sha({"attempt": "g0-rcp-04a"})
POLICY_SHA = canonical_sha({"policy": "gate0-read-only"})


def _compile(root: Path, revision: str = REVISION):
    return compile_reference_project(
        root,
        source_revision=revision,
        created_at=NOW,
        trace_id="g0-rcp-04a",
    )


def _expectation(result) -> FourfoldEvidenceExpectation:
    return FourfoldEvidenceExpectation(
        candidate_artifact_sha256=result.source_bundle_sha256,
        candidate_artifact_locator=(
            f"artifact-locator:sha256:{result.source_bundle_sha256}"
        ),
        snapshot_sha256=result.snapshot.digest,
        source_revision=result.snapshot.source_revision,
    )


def _packet(result) -> EvidencePacket:
    return assemble_fourfold_evidence_packet(
        snapshot=result.snapshot,
        candidate_artifact_sha256=result.source_bundle_sha256,
        candidate_artifact_locator=(
            f"artifact-locator:sha256:{result.source_bundle_sha256}"
        ),
        packet_id="g0-rcp-04a-evidence",
        mission_id="g0-rcp-04a",
        attempt_id="g0-rcp-04a-attempt",
        attempt_contract_sha256=ATTEMPT_SHA,
        policy_decision_sha256=POLICY_SHA,
        collected_at=NOW,
        usage=ResourceUsage(wall_time_ms=1),
        trace_id="g0-rcp-04a",
    )


def test_real_wiki_snapshot_is_bound_to_candidate_and_revision() -> None:
    result = _compile(FIXTURE)
    packet = _packet(result)
    item = next(
        item for item in packet.items if item.evaluator == FOURFOLD_EVALUATOR
    )

    assert len(result.snapshot.bindings) == 31
    assert packet.source_revision == REVISION
    assert packet.subject_sha256 == result.source_bundle_sha256
    assert packet.candidate_artifact_sha256 == result.source_bundle_sha256
    assert item.output_sha256 == result.snapshot.digest
    assert item.details["fourfold_snapshot_sha256"] == result.snapshot.digest
    assert item.details["source_forest_sha256"] == result.forest.content_sha256
    verify_fourfold_evidence_packet(
        packet,
        snapshot=result.snapshot,
        expectation=_expectation(result),
    )


def test_source_mutation_changes_candidate_and_snapshot_and_old_packet_refuses(
    tmp_path: Path,
) -> None:
    root = tmp_path / "wiki"
    shutil.copytree(FIXTURE, root)
    before = _compile(root)
    before_packet = _packet(before)

    source = root / "src" / "knowledge_hub" / "search.py"
    source.write_text(
        source.read_text(encoding="utf-8") + "\n# gate-0 source mutation\n",
        encoding="utf-8",
    )
    after = _compile(root)

    assert after.source_bundle_sha256 != before.source_bundle_sha256
    assert after.snapshot.digest != before.snapshot.digest
    with pytest.raises(FourfoldEvidenceMismatch, match="candidate|snapshot"):
        verify_fourfold_evidence_packet(
            before_packet,
            snapshot=after.snapshot,
            expectation=_expectation(after),
        )


def test_snapshot_from_another_revision_is_refused() -> None:
    first = _compile(FIXTURE, REVISION)
    second = _compile(FIXTURE, OTHER_REVISION)

    with pytest.raises(FourfoldEvidenceMismatch, match="revision|snapshot"):
        verify_fourfold_evidence_packet(
            _packet(first),
            snapshot=second.snapshot,
            expectation=_expectation(second),
        )


def test_missing_or_repackaged_fourfold_evidence_is_refused() -> None:
    result = _compile(FIXTURE)
    packet = _packet(result)
    expectation = _expectation(result)

    unrelated = EvidenceItem(
        evidence_id="other:evidence",
        evaluator="other-evaluator",
        assurance="deterministic",
        verdict="passed",
        output_sha256="d" * 64,
        evidence_locator=f"artifact-locator:sha256:{'d' * 64}",
        collected_at=NOW,
        provenance=ContractProvenance(
            origin="test.other",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=("d" * 64,),
        ),
        details={"kind": "not-fourfold"},
    )
    tampered = EvidencePacket(
        packet_id=packet.packet_id,
        mission_id=packet.mission_id,
        attempt_id=packet.attempt_id,
        source_revision=packet.source_revision,
        attempt_contract_sha256=packet.attempt_contract_sha256,
        subject_sha256=packet.subject_sha256,
        evaluation_status="passed",
        items=(unrelated,),
        policy_decision_sha256=packet.policy_decision_sha256,
        usage=packet.usage,
        provenance=ContractProvenance(
            origin="test.repackaged",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=tuple(
                sorted(
                    {
                        packet.attempt_contract_sha256,
                        packet.subject_sha256,
                        packet.policy_decision_sha256,
                        unrelated.output_sha256,
                        result.source_bundle_sha256,
                    }
                )
            ),
        ),
        candidate_artifact_sha256=result.source_bundle_sha256,
        candidate_artifact_locator=(
            f"artifact-locator:sha256:{result.source_bundle_sha256}"
        ),
    )

    with pytest.raises(FourfoldEvidenceMismatch, match="evidence_count"):
        verify_fourfold_evidence_packet(
            tampered,
            snapshot=result.snapshot,
            expectation=expectation,
        )

    wrong_snapshot = "e" * 64
    manipulated_item = EvidenceItem(
        evidence_id="g0-rcp-04a-attempt:fourfold",
        evaluator=FOURFOLD_EVALUATOR,
        assurance="deterministic",
        verdict="passed",
        output_sha256=wrong_snapshot,
        evidence_locator=f"artifact-locator:sha256:{wrong_snapshot}",
        collected_at=NOW,
        provenance=ContractProvenance(
            origin="test.manipulated-fourfold",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=(
                result.source_bundle_sha256,
                result.snapshot.source_forest_sha256,
                wrong_snapshot,
            ),
        ),
        details={
            "schema": "daedalus-fourfold-evidence/1",
            "repository_id": result.snapshot.repository_id,
            "source_revision": REVISION,
            "candidate_artifact_sha256": result.source_bundle_sha256,
            "source_forest_sha256": result.snapshot.source_forest_sha256,
            "fourfold_snapshot_sha256": wrong_snapshot,
        },
    )
    manipulated_packet = EvidencePacket(
        packet_id=packet.packet_id,
        mission_id=packet.mission_id,
        attempt_id=packet.attempt_id,
        source_revision=packet.source_revision,
        attempt_contract_sha256=packet.attempt_contract_sha256,
        subject_sha256=packet.subject_sha256,
        evaluation_status="passed",
        items=(manipulated_item,),
        policy_decision_sha256=packet.policy_decision_sha256,
        usage=packet.usage,
        provenance=ContractProvenance(
            origin="test.manipulated-fourfold-packet",
            source_revision=REVISION,
            created_at=NOW,
            input_digests=tuple(
                sorted(
                    {
                        packet.attempt_contract_sha256,
                        packet.subject_sha256,
                        packet.policy_decision_sha256,
                        manipulated_item.output_sha256,
                    }
                )
            ),
        ),
        candidate_artifact_sha256=result.source_bundle_sha256,
        candidate_artifact_locator=(
            f"artifact-locator:sha256:{result.source_bundle_sha256}"
        ),
    )
    with pytest.raises(FourfoldEvidenceMismatch, match="snapshot"):
        verify_fourfold_evidence_packet(
            manipulated_packet,
            snapshot=result.snapshot,
            expectation=expectation,
        )


def test_expectation_rejects_candidate_locator_repackaging() -> None:
    result = _compile(FIXTURE)
    with pytest.raises(FourfoldEvidenceMismatch, match="locator"):
        FourfoldEvidenceExpectation(
            candidate_artifact_sha256=result.source_bundle_sha256,
            candidate_artifact_locator=f"artifact-locator:sha256:{'e' * 64}",
            snapshot_sha256=result.snapshot.digest,
            source_revision=REVISION,
        )


@pytest.fixture(scope="module")
def retention_source(tmp_path_factory):
    """A real complete compilation bound to a separate source-tree CAS."""
    source_store = SourceTreeStore(tmp_path_factory.mktemp("retention-source"))
    source = source_store.capture_tree(
        FIXTURE,
        tree_id="retention-wiki-source",
        source_revision=REVISION,
        origin="tests.fourfold-retention",
        created_at=NOW,
    )
    compiled = compile_reference_project(
        FIXTURE,
        source_revision=REVISION,
        created_at=NOW,
        source_tree_sha256=source.ref.sha256,
    )
    assert all(plane.status == "complete" for plane in compiled.snapshot.planes)
    assert source.ref.sha256 in compiled.snapshot.provenance.input_digests
    manifest_bytes = source.manifest.to_json().encode("ascii")
    assert source_store.read_bytes(source.ref, max_bytes=len(manifest_bytes)) == manifest_bytes
    return compiled, source


def _retention_arguments(retention_source, store: ArtifactStore) -> dict:
    compiled, source = retention_source
    return {
        "snapshot": compiled.snapshot,
        "candidate_artifact_sha256": source.ref.sha256,
        "candidate_artifact_locator": source.locator,
        "packet_id": "retention-evidence",
        "mission_id": "retention-mission",
        "attempt_id": "retention-attempt",
        "attempt_contract_sha256": ATTEMPT_SHA,
        "policy_decision_sha256": POLICY_SHA,
        "collected_at": NOW,
        "usage": ResourceUsage(wall_time_ms=7),
        "trace_id": "retention-test",
        "store": store,
    }


def _stored_observation(
    store: ArtifactStore,
    *,
    index: int = 0,
    verdict: str = "failed",
    assurance: str = "deterministic",
) -> tuple[EvidenceItem, bytes]:
    raw = f"observed check {index}: {verdict}\nraw diagnostic: \u00e4\x00\n".encode("utf-8")
    output_sha = hashlib.sha256(raw).hexdigest()
    provenance = ContractProvenance(
        origin="tests.fourfold-retention-output",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(output_sha,),
    )
    stored = store.put_bytes(
        raw,
        expected_sha256=output_sha,
        metadata={"check": index},
        provenance=provenance.to_dict(),
    )
    return EvidenceItem(
        evidence_id=f"retention-check-{index}",
        evaluator="tests.retained-observation",
        assurance=assurance,
        verdict=verdict,
        output_sha256=output_sha,
        evidence_locator=stored.locator_uri,
        collected_at=NOW,
        provenance=dataclasses.replace(
            provenance,
            input_digests=tuple(sorted({output_sha, stored.locator_sha256})),
        ),
        details={"observation": index, "raw_byte_length": len(raw)},
    ), raw


@pytest.mark.parametrize(
    ("verdict", "assurance"),
    [("failed", "deterministic"), ("error", "independent"),
     ("cancelled", "deterministic"), ("passed", "unverified"),
     ("failed", "unverified")],
)
def test_default_assembly_refuses_negative_and_unverified_items(
    retention_source, tmp_path: Path, verdict: str, assurance: str,
) -> None:
    store = ArtifactStore(tmp_path / "evidence")
    item, _ = _stored_observation(store, verdict=verdict, assurance=assurance)
    arguments = _retention_arguments(retention_source, store)
    with pytest.raises(ValueError, match="passed|unverified|conclusive"):
        assemble_fourfold_evidence_packet(**arguments, extra_items=(item,))


@pytest.mark.parametrize("verdict", ["failed", "error"])
def test_explicit_item_status_assembly_preserves_verdict_assurance_and_bytes(
    retention_source, tmp_path: Path, verdict: str,
) -> None:
    store = ArtifactStore(tmp_path / "evidence")
    item, raw = _stored_observation(store, verdict=verdict)
    packet = assemble_fourfold_evidence_packet(
        **_retention_arguments(retention_source, store),
        extra_items=(item,), status_mode="from_items",
    )
    assert packet.evaluation_status == "failed"
    assert next(value for value in packet.items if value.evidence_id == item.evidence_id) == item
    assert packet.usage == ResourceUsage(wall_time_ms=7)
    structural = next(value for value in packet.items if value.evaluator == FOURFOLD_EVALUATOR)
    assert (structural.verdict, structural.assurance) == ("passed", "deterministic")
    assert structural.output_sha256 == retention_source[0].snapshot.digest
    assert packet.candidate_artifact_sha256 == retention_source[1].ref.sha256
    assert packet.candidate_artifact_locator == retention_source[1].locator
    assert not store.locator_path(retention_source[1].ref.sha256).exists()
    for value in packet.items:
        stored = store.verify(store.load_locator(value.evidence_locator.rsplit(":", 1)[1]))
        assert stored.artifact_sha256 == value.output_sha256
    assert store.get_bytes(item.output_sha256) == raw
    assert EvidencePacket.from_dict(packet.to_dict()) == packet


@pytest.mark.parametrize(
    ("observations", "expected"),
    [
        ((("passed", "deterministic"),), "passed"),
        ((("passed", "independent"), ("passed", "deterministic")), "passed"),
        ((("failed", "independent"),), "failed"),
        ((("error", "deterministic"),), "failed"),
        ((("cancelled", "independent"),), "inconclusive"),
        ((("passed", "unverified"),), "inconclusive"),
        ((("error", "unverified"),), "inconclusive"),
        ((("failed", "deterministic"), ("cancelled", "independent")), "inconclusive"),
        ((("failed", "independent"), ("passed", "unverified")), "inconclusive"),
        ((("error", "unverified"), ("failed", "deterministic")), "inconclusive"),
    ],
)
def test_explicit_item_status_precedence_is_conservative(
    retention_source, tmp_path: Path, observations, expected: str,
) -> None:
    store = ArtifactStore(tmp_path / "evidence")
    items = tuple(
        _stored_observation(store, index=index, verdict=verdict, assurance=assurance)[0]
        for index, (verdict, assurance) in enumerate(observations)
    )
    packet = assemble_fourfold_evidence_packet(
        **_retention_arguments(retention_source, store),
        extra_items=items, status_mode="from_items",
    )
    assert packet.evaluation_status == expected
    assert tuple(value for value in packet.items if value.evaluator != FOURFOLD_EVALUATOR) == items


def test_passed_assembly_modes_produce_identical_canonical_packet_bytes(
    retention_source, tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "evidence")
    item, _ = _stored_observation(store, verdict="passed", assurance="independent")
    arguments = {**_retention_arguments(retention_source, store), "extra_items": (item,)}
    default = assemble_fourfold_evidence_packet(**arguments)
    explicit = assemble_fourfold_evidence_packet(**arguments, status_mode="passed_only")
    derived = assemble_fourfold_evidence_packet(**arguments, status_mode="from_items")
    repeated = assemble_fourfold_evidence_packet(**arguments, status_mode="from_items")
    assert default.to_json() == explicit.to_json() == derived.to_json() == repeated.to_json()
    assert default.digest == derived.digest == repeated.digest


@pytest.mark.parametrize("mode", ["unknown", None, False, True])
def test_assembly_rejects_unknown_status_mode_before_storage(
    retention_source, tmp_path: Path, monkeypatch, mode,
) -> None:
    store = ArtifactStore(tmp_path / "untouched")
    writes: list[bytes] = []

    def record_unexpected_write(data, **kwargs):
        writes.append(bytes(data))
        raise AssertionError("invalid status mode reached storage")

    monkeypatch.setattr(store, "put_bytes", record_unexpected_write)
    with pytest.raises(ValueError, match="status_mode"):
        assemble_fourfold_evidence_packet(
            **_retention_arguments(retention_source, store), status_mode=mode,
        )
    assert writes == []
    assert not store.root.exists()


@pytest.mark.parametrize("verdict", ["failed", "passed"])
@pytest.mark.parametrize(
    "fault",
    ["missing_blob", "corrupt_blob", "missing_manifest", "corrupt_manifest",
     "foreign_payload", "wrong_byte_length"],
)
def test_explicit_assembly_rereads_every_item_output(
    retention_source, tmp_path: Path, verdict: str, fault: str,
) -> None:
    store = ArtifactStore(tmp_path / "evidence")
    item, raw = _stored_observation(store, verdict=verdict)
    locator = store.verify(store.load_locator(item.evidence_locator.rsplit(":", 1)[1]))
    assert store.get_bytes(locator.artifact_sha256) == raw
    if fault == "missing_blob":
        locator.blob_path.unlink()
    elif fault == "corrupt_blob":
        locator.blob_path.write_bytes(b"X" * len(raw))
    elif fault == "missing_manifest":
        locator.locator_path.unlink()
    elif fault == "corrupt_manifest":
        locator.locator_path.write_bytes(b"{}")
    else:
        if fault == "foreign_payload":
            foreign, _ = _stored_observation(store, index=99, verdict=verdict)
            locator_sha = foreign.evidence_locator.rsplit(":", 1)[1]
            assert store.verify(store.load_locator(locator_sha)).artifact_sha256 != item.output_sha256
        else:
            manifest = locator.to_dict()
            manifest["artifact"]["byte_length"] += 1
            encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")
            locator_sha = hashlib.sha256(encoded).hexdigest()
            target = store.locator_path(locator_sha)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(encoded)
            assert store.load_locator(locator_sha).byte_length == len(raw) + 1
        item = dataclasses.replace(
            item,
            evidence_locator=f"artifact-locator:sha256:{locator_sha}",
            provenance=dataclasses.replace(
                item.provenance,
                input_digests=tuple(sorted({*item.provenance.input_digests, locator_sha})),
            ),
        )
    with pytest.raises((FourfoldEvidenceMismatch, FourfoldEvidenceUnstorable)):
        assemble_fourfold_evidence_packet(
            **_retention_arguments(retention_source, store),
            extra_items=(item,), status_mode="from_items",
        )


@pytest.mark.parametrize(
    "fault",
    ["partial_plane", "unbound_candidate", "foreign_candidate", "foreign_locator",
     "foreign_item_revision", "duplicate_fourfold", "duplicate_id",
     "invalid_assurance", "invalid_verdict"],
)
def test_explicit_negative_assembly_refuses_partial_and_foreign_bindings(
    retention_source, tmp_path: Path, fault: str,
) -> None:
    store = ArtifactStore(tmp_path / "evidence")
    arguments = _retention_arguments(retention_source, store)
    item, _ = _stored_observation(store)
    snapshot = arguments["snapshot"]
    if fault == "partial_plane":
        planes = list(snapshot.planes)
        planes[0] = dataclasses.replace(
            planes[0], status="partial", reason="frozen incomplete-plane discriminator",
        )
        arguments["snapshot"] = dataclasses.replace(
            snapshot,
            planes=tuple(planes),
            provenance=dataclasses.replace(
                snapshot.provenance,
                input_digests=tuple(sorted({
                    *snapshot.provenance.input_digests,
                    *(plane.digest for plane in planes),
                })),
            ),
        )
    elif fault == "unbound_candidate":
        candidate_sha = arguments["candidate_artifact_sha256"]
        arguments["snapshot"] = dataclasses.replace(
            snapshot,
            provenance=dataclasses.replace(
                snapshot.provenance,
                input_digests=tuple(
                    digest for digest in snapshot.provenance.input_digests
                    if digest != candidate_sha
                ),
            ),
        )
    elif fault == "foreign_candidate":
        arguments["candidate_artifact_sha256"] = "f" * 64
        arguments["candidate_artifact_locator"] = f"artifact-locator:sha256:{'f' * 64}"
    elif fault == "foreign_locator":
        arguments["candidate_artifact_locator"] = f"artifact-locator:sha256:{'f' * 64}"
    elif fault == "foreign_item_revision":
        item = dataclasses.replace(
            item, provenance=dataclasses.replace(item.provenance, source_revision=OTHER_REVISION),
        )
    elif fault == "duplicate_fourfold":
        item = dataclasses.replace(item, evaluator=FOURFOLD_EVALUATOR)
    elif fault == "duplicate_id":
        item = dataclasses.replace(item, evidence_id="retention-attempt:fourfold")
    else:
        # A caller can bypass a frozen dataclass; the consumer must rebuild it.
        forged = object.__new__(EvidenceItem)
        for field in dataclasses.fields(item):
            object.__setattr__(forged, field.name, getattr(item, field.name))
        object.__setattr__(
            forged, "assurance" if fault == "invalid_assurance" else "verdict", "unknown",
        )
        item = forged
    with pytest.raises(ValueError):
        assemble_fourfold_evidence_packet(
            **arguments, extra_items=(item,), status_mode="from_items",
        )
