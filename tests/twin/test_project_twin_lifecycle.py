from __future__ import annotations

import json
import threading
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


def _revision(seed: str) -> str:
    return _digest(f"revision-{seed}")


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
    first = _manifest(_revision("a"), "a")
    second = _manifest(_revision("b"), "b")

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
    first = _manifest(_revision("a"), "a")
    second = _manifest(_revision("b"), "b")
    store.append(first, expected_head_sha256=None)

    with pytest.raises(ProjectTwinContractError, match="head changed"):
        store.append(first, expected_head_sha256=None)
    with pytest.raises(ProjectTwinContractError, match="head changed"):
        store.append(second, expected_head_sha256=_digest("stale"))


def test_revision_replay_is_rejected_even_when_manifest_differs(tmp_path):
    store = AtomicProjectTwinLifecycleStore(tmp_path)
    first = _manifest(_revision("a"), "a")
    replay = _manifest(_revision("a"), "b")
    store.append(first, expected_head_sha256=None)

    with pytest.raises(ProjectTwinContractError, match="replays a source revision"):
        store.append(replay, expected_head_sha256=first.digest)


def test_repository_substitution_is_rejected():
    first = _manifest(_revision("a"), "a")
    substituted = replace(_manifest(_revision("b"), "b"), repository_id="other/repository")
    with pytest.raises(ProjectTwinContractError, match="repository identity changed"):
        classify_manifest_drift(first, substituted)


def test_drift_classes_are_exact():
    first = _manifest(_revision("a"), "a")
    compiler = replace(first, source_revision=_revision("b"), compiler_contract_sha256=_digest("compiler-b"))
    evidence = replace(first, source_revision=_revision("c"), evidence_packet_sha256=_digest("evidence-c"))
    source = replace(first, source_revision=_revision("d"), source_artifact=ArtifactRef.from_sha256(_digest("source-d")))

    assert classify_manifest_drift(first, compiler) == "mixed"
    assert classify_manifest_drift(first, evidence) == "mixed"
    assert classify_manifest_drift(first, source) == "source"


def test_no_identity_change_is_rejected():
    first = _manifest(_revision("a"), "a")
    with pytest.raises(ProjectTwinContractError, match="no identity change"):
        classify_manifest_drift(first, first)


def test_transition_tampering_is_rejected():
    first = _manifest(_revision("a"), "a")
    second = _manifest(_revision("b"), "b")
    transition = replace(build_transition(first, second), drift_class="source")
    with pytest.raises(ProjectTwinContractError, match="transition mismatch"):
        verify_lifecycle((first, second), (build_transition(None, first), transition))


def test_noncanonical_and_head_tampering_are_rejected(tmp_path):
    store = AtomicProjectTwinLifecycleStore(tmp_path)
    first = _manifest(_revision("a"), "a")
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


def test_concurrent_writer_is_rejected_while_lock_owner_completes(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    first = _manifest(_revision("a"), "a")

    def fault(phase: str) -> None:
        if phase == "after_temp_fsync":
            entered.set()
            assert release.wait(timeout=5)

    owner = AtomicProjectTwinLifecycleStore(tmp_path, fault_injector=fault)
    contender = AtomicProjectTwinLifecycleStore(tmp_path)
    errors: list[BaseException] = []

    def write_owner() -> None:
        try:
            owner.append(first, expected_head_sha256=None)
        except BaseException as exc:  # pragma: no cover - diagnostic capture
            errors.append(exc)

    thread = threading.Thread(target=write_owner)
    thread.start()
    assert entered.wait(timeout=5)
    with pytest.raises(ProjectTwinContractError, match="writer is already active"):
        contender.append(first, expected_head_sha256=None)
    release.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors == []
    assert owner.resolve_head(first.repository_id) == first


def test_crash_before_replace_preserves_previous_head_and_cleans_state(tmp_path):
    first = _manifest(_revision("a"), "a")
    second = _manifest(_revision("b"), "b")
    stable = AtomicProjectTwinLifecycleStore(tmp_path)
    stable.append(first, expected_head_sha256=None)

    def crash(phase: str) -> None:
        if phase == "after_temp_fsync":
            raise RuntimeError("injected pre-replace crash")

    crashing = AtomicProjectTwinLifecycleStore(tmp_path, fault_injector=crash)
    with pytest.raises(RuntimeError, match="pre-replace"):
        crashing.append(second, expected_head_sha256=first.digest)

    assert stable.resolve_head(first.repository_id) == first
    assert list(tmp_path.glob(".*.tmp")) == []
    assert list(tmp_path.glob("*.lock")) == []


def test_crash_after_replace_recovers_new_canonical_head(tmp_path):
    first = _manifest(_revision("a"), "a")
    second = _manifest(_revision("b"), "b")
    third = _manifest(_revision("c"), "c")
    stable = AtomicProjectTwinLifecycleStore(tmp_path)
    stable.append(first, expected_head_sha256=None)

    def crash(phase: str) -> None:
        if phase == "after_replace":
            raise RuntimeError("injected post-replace crash")

    crashing = AtomicProjectTwinLifecycleStore(tmp_path, fault_injector=crash)
    with pytest.raises(RuntimeError, match="post-replace"):
        crashing.append(second, expected_head_sha256=first.digest)

    recovered = AtomicProjectTwinLifecycleStore(tmp_path)
    assert recovered.resolve_head(first.repository_id) == second
    recovered.append(third, expected_head_sha256=second.digest)
    assert recovered.resolve_head(first.repository_id) == third


def test_startup_removes_only_regular_orphan_temporaries(tmp_path):
    orphan = tmp_path / ".orphan.tmp"
    orphan.write_bytes(b"partial")
    target = tmp_path / "target"
    target.write_bytes(b"keep")
    symlink = tmp_path / ".linked.tmp"
    try:
        symlink.symlink_to(target)
    except OSError:
        pytest.skip("symlinks unavailable")

    AtomicProjectTwinLifecycleStore(tmp_path)

    assert not orphan.exists()
    assert symlink.is_symlink()
    assert target.read_bytes() == b"keep"
