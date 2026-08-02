from __future__ import annotations

import json
from dataclasses import replace

import pytest

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.spine.envelope import canonical_json
from daedalus.twin.genesis import ProjectTwinContractError, ProjectTwinManifest
from daedalus.twin.lifecycle import (
    AtomicProjectTwinLifecycleStore,
    build_transition,
    classify_manifest_drift,
    verify_lifecycle,
)


def _digest(seed: str) -> str:
    import hashlib

    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _manifest(revision: str, seed: str = "a") -> ProjectTwinManifest:
    return ProjectTwinManifest(
        repository_id="KTY137/daedalus",
        source_revision=revision,
        source_artifact=ArtifactRef.from_sha256(_digest(f"source-{seed}")),
        source_forest_sha256=_digest(f"forest-{seed}"),
        fourfold_snapshot_sha256=_digest(f"snapshot-{seed}"),
        compiler_contract_sha256=_digest("compiler-a"),
        evidence_packet_sha256=_digest(f"evidence-{seed}"),
    )


def test_lifecycle_appends_and_resolves_exact_head(tmp_path):
    store = AtomicProjectTwinLifecycleStore(tmp_path)
    first = _manifest("rev-a", "a")
    second = _manifest("rev-b", "b")

    first_artifact = store.append(first, expected_head_sha256=None)
    second_artifact = store.append(second, expected_head_sha256=first.digest)

    assert first_artifact != second_artifact
    assert store.resolve_head(first.repository_id) == second
    manifests, transitions = store.load(first.repository_id)
    assert manifests == (first, second)
    assert transitions == (build_transition(None, first), build_transition(first, second))
    assert transitions[0].drift_class == "initial"
    assert transitions[1].drift_class == "mixed"


def test_exact_replay_and_stale_writer_fail_closed(tmp_path):
    store = AtomicProjectTwinLifecycleStore(tmp_path)
    first = _manifest("rev-a", "a")
    second = _manifest("rev-b", "b")
    store.append(first, expected_head_sha256=None)

    with pytest.raises(ProjectTwinContractError, match="head changed"):
        store.append(first, expected_head_sha256=None)
    with pytest.raises(ProjectTwinContractError, match="head changed"):
        store.append(second, expected_head_sha256=_digest("stale"))


def test_revision_replay_is_rejected_even_when_manifest_differs(tmp_path):
    store = AtomicProjectTwinLifecycleStore(tmp_path)
    first = _manifest("rev-a", "a")
    replay = _manifest("rev-a", "b")
    store.append(first, expected_head_sha256=None)

    with pytest.raises(ProjectTwinContractError, match="replays a source revision"):
        store.append(replay, expected_head_sha256=first.digest)


def test_repository_substitution_is_rejected():
    first = _manifest("rev-a", "a")
    substituted = replace(_manifest("rev-b", "b"), repository_id="other/repository")
    with pytest.raises(ProjectTwinContractError, match="repository identity changed"):
        classify_manifest_drift(first, substituted)


def test_drift_classes_are_exact():
    first = _manifest("rev-a", "a")
    compiler = replace(
        first,
        source_revision="rev-b",
        compiler_contract_sha256=_digest("compiler-b"),
    )
    evidence = replace(
        first,
        source_revision="rev-c",
        evidence_packet_sha256=_digest("evidence-c"),
    )
    source = replace(
        first,
        source_revision="rev-d",
        source_artifact=ArtifactRef.from_sha256(_digest("source-d")),
    )

    assert classify_manifest_drift(first, compiler) == "mixed"
    assert classify_manifest_drift(first, evidence) == "mixed"
    assert classify_manifest_drift(first, source) == "source"


def test_no_identity_change_is_rejected():
    first = _manifest("rev-a", "a")
    with pytest.raises(ProjectTwinContractError, match="no identity change"):
        classify_manifest_drift(first, first)


def test_transition_tampering_is_rejected():
    first = _manifest("rev-a", "a")
    second = _manifest("rev-b", "b")
    transition = replace(build_transition(first, second), drift_class="source")
    with pytest.raises(ProjectTwinContractError, match="transition mismatch"):
        verify_lifecycle((first, second), (build_transition(None, first), transition))


def test_noncanonical_and_head_tampering_are_rejected(tmp_path):
    store = AtomicProjectTwinLifecycleStore(tmp_path)
    first = _manifest("rev-a", "a")
    store.append(first, expected_head_sha256=None)
    path = store._path(first.repository_id)
    payload = json.loads(path.read_text("ascii"))

    payload["head_manifest_sha256"] = _digest("tampered")
    path.write_text(canonical_json(payload), encoding="ascii")
    with pytest.raises(ProjectTwinContractError, match="head mismatch"):
        store.load(first.repository_id)

    payload["head_manifest_sha256"] = first.digest
    path.write_text(json.dumps(payload, indent=2), encoding="ascii")
    with pytest.raises(ProjectTwinContractError, match="not canonically encoded"):
        store.load(first.repository_id)


def test_missing_lifecycle_head_is_rejected(tmp_path):
    store = AtomicProjectTwinLifecycleStore(tmp_path)
    with pytest.raises(ProjectTwinContractError, match="does not exist"):
        store.resolve_head("KTY137/daedalus")
