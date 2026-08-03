from __future__ import annotations

import os
from pathlib import Path

import pytest

from daedalus.kernel.artifacts import (
    ArtifactCorruptionError,
    ArtifactStore,
    ArtifactStoreError,
    SourceTreeEntry,
    SourceTreeError,
    SourceTreeManifest,
    locator_sha256,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json


REVISION = "a" * 40
NOW = "2026-08-03T05:40:00+00:00"


def capture(store: ArtifactStore, root: Path, *, tree_id: str = "tree-1"):
    return store.capture_tree(
        root,
        tree_id=tree_id,
        source_revision=REVISION,
        origin="tests.source-tree",
        created_at=NOW,
        trace_id="mission-1",
    )


def test_capture_is_deterministic_content_addressed_and_materializable(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "pkg").mkdir()
    (source / "README.md").write_text("# project\n", encoding="utf-8")
    executable = source / "pkg" / "run.py"
    executable.write_text("print('ok')\n", encoding="utf-8")
    executable.chmod(0o755)

    store = ArtifactStore(tmp_path / "cas")
    first = capture(store, source)
    second = capture(store, source)

    assert first == second
    assert locator_sha256(first.locator) == first.manifest.digest
    assert tuple(entry.path for entry in first.manifest.entries) == (
        "README.md",
        "pkg/run.py",
    )
    assert store.exists(first.locator)

    destination = tmp_path / "candidate"
    loaded = store.materialize_tree(first.locator, destination)
    assert loaded == first.manifest
    assert (destination / "README.md").read_text(encoding="utf-8") == "# project\n"
    assert (destination / "pkg" / "run.py").read_text(encoding="utf-8") == "print('ok')\n"
    if os.name != "nt":
        assert os.access(destination / "pkg" / "run.py", os.X_OK)


def test_source_mutation_changes_tree_identity_without_mutating_prior_object(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    path = source / "event.py"
    path.write_text("voltage = 10\n", encoding="utf-8")
    store = ArtifactStore(tmp_path / "cas")

    before = capture(store, source)
    before_bytes = store.read_bytes(before.locator)
    path.write_text("bias_voltage = 10\n", encoding="utf-8")
    after = capture(store, source)

    assert before.locator != after.locator
    assert before.manifest.entries[0].blob_sha256 != after.manifest.entries[0].blob_sha256
    assert store.read_bytes(before.locator) == before_bytes


def test_duplicate_blobs_are_deduplicated_but_paths_remain_distinct(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_bytes(b"same")
    (source / "b.txt").write_bytes(b"same")
    store = ArtifactStore(tmp_path / "cas")

    captured = capture(store, source)

    assert len(captured.manifest.entries) == 2
    assert len({entry.blob_sha256 for entry in captured.manifest.entries}) == 1
    object_files = [path for path in store.objects.rglob("*") if path.is_file()]
    assert len(object_files) == 2  # one shared blob plus one manifest object


def test_git_and_daedalus_metadata_are_not_candidate_identity(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("x = 1\n", encoding="utf-8")
    (source / ".git").mkdir()
    (source / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (source / ".daedalus").mkdir()
    (source / ".daedalus" / "evaluator.json").write_text("{}", encoding="utf-8")
    store = ArtifactStore(tmp_path / "cas")

    captured = capture(store, source)

    assert tuple(entry.path for entry in captured.manifest.entries) == ("app.py",)
    assert captured.manifest.ignored_roots == (".daedalus", ".git")


def test_symlink_source_root_and_entries_are_refused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "secret"
    outside.write_text("secret", encoding="utf-8")
    link = source / "escape"
    root_link = tmp_path / "source-link"
    try:
        link.symlink_to(outside)
        root_link.symlink_to(source, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")

    store = ArtifactStore(tmp_path / "cas")
    with pytest.raises(SourceTreeError, match="symlink"):
        capture(store, source)
    with pytest.raises(SourceTreeError, match="source root"):
        capture(store, root_link)


def test_special_files_and_address_symlinks_are_refused(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    if hasattr(os, "mkfifo"):
        fifo = source / "pipe"
        os.mkfifo(fifo)
        with pytest.raises(SourceTreeError, match="not a regular file"):
            capture(ArtifactStore(tmp_path / "cas-fifo"), source)
    else:
        pytest.skip("special-file creation unavailable on this platform")

    store = ArtifactStore(tmp_path / "cas-object")
    locator = store.put_bytes(b"trusted")
    target = store._object_path(locator_sha256(locator))
    target.unlink()
    outside = tmp_path / "outside-object"
    outside.write_bytes(b"trusted")
    try:
        target.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("object symlinks are unavailable on this platform")
    with pytest.raises(ArtifactCorruptionError, match="regular file"):
        store.read_bytes(locator)
    with pytest.raises(ArtifactCorruptionError, match="regular file"):
        store.put_bytes(b"trusted")


def test_malformed_traversal_and_stale_revision_manifests_fail_closed(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "cas")
    blob = locator_sha256(store.put_bytes(b"payload"))
    provenance = {
        "origin": "tests.source-tree",
        "source_revision": REVISION,
        "created_at": NOW,
        "input_digests": [blob],
        "trace_id": "mission-1",
    }
    malformed = {
        "contract_type": "daedalus.source-tree-manifest",
        "contract_version": "1.0.0",
        "tree_id": "tree-1",
        "source_revision": REVISION,
        "entries": [
            {
                "path": "../escape",
                "blob_sha256": blob,
                "size": 7,
                "executable": False,
            }
        ],
        "ignored_roots": [".git"],
        "provenance": provenance,
    }
    malformed_locator = store.put_bytes(canonical_json(malformed).encode("utf-8"))
    with pytest.raises(SourceTreeError, match="malformed"):
        store.load_tree(malformed_locator)

    stale = dict(malformed)
    stale["entries"] = [
        {
            "path": "safe.txt",
            "blob_sha256": blob,
            "size": 7,
            "executable": False,
        }
    ]
    stale["source_revision"] = "b" * 40
    stale_locator = store.put_bytes(canonical_json(stale).encode("utf-8"))
    with pytest.raises(SourceTreeError, match="malformed"):
        store.load_tree(stale_locator)


def test_corrupt_object_is_never_returned_or_reported_as_existing(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "cas")
    locator = store.put_bytes(b"trusted")
    store._object_path(locator_sha256(locator)).write_bytes(b"tampered")

    assert not store.exists(locator)
    with pytest.raises(ArtifactCorruptionError, match="content address"):
        store.read_bytes(locator)
    with pytest.raises(ArtifactCorruptionError, match="existing object"):
        store.put_bytes(b"trusted")


def test_materialization_refuses_existing_destination_and_missing_blob(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.txt").write_text("a", encoding="utf-8")
    store = ArtifactStore(tmp_path / "cas")
    captured = capture(store, source)

    destination = tmp_path / "candidate"
    destination.mkdir()
    with pytest.raises(SourceTreeError, match="must not already exist"):
        store.materialize_tree(captured.locator, destination)

    blob = captured.manifest.entries[0].blob_sha256
    store._object_path(blob).unlink()
    missing_destination = tmp_path / "missing-candidate"
    with pytest.raises(ArtifactStoreError, match="missing"):
        store.materialize_tree(captured.locator, missing_destination)
    assert not missing_destination.exists()
    assert not list(tmp_path.glob(".missing-candidate.tmp-*"))


def test_read_and_materialization_bounds_fail_before_publication(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "large.bin").write_bytes(b"0123456789")
    store = ArtifactStore(tmp_path / "cas")
    captured = capture(store, source)

    blob_locator = "artifact-locator:sha256:" + captured.manifest.entries[0].blob_sha256
    with pytest.raises(ArtifactStoreError, match="read bound"):
        store.read_bytes(blob_locator, max_bytes=9)
    with pytest.raises(SourceTreeError, match="max_file_bytes"):
        store.materialize_tree(
            captured.locator,
            tmp_path / "bounded-candidate",
            max_file_bytes=9,
        )
    assert not (tmp_path / "bounded-candidate").exists()

    with pytest.raises(SourceTreeError, match="max_total_bytes"):
        store.materialize_tree(
            captured.locator,
            tmp_path / "total-bounded-candidate",
            max_total_bytes=9,
        )
    assert not (tmp_path / "total-bounded-candidate").exists()


def test_contract_rejects_case_collisions_file_child_conflicts_and_ignored_collisions() -> None:
    digest = "1" * 64
    provenance = ContractProvenance(
        origin="tests.source-tree",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(digest,),
    )
    with pytest.raises(ValueError, match="case-insensitive"):
        SourceTreeManifest(
            tree_id="tree-1",
            source_revision=REVISION,
            entries=(
                SourceTreeEntry("A.txt", digest, 0),
                SourceTreeEntry("a.txt", digest, 0),
            ),
            ignored_roots=(".git",),
            provenance=provenance,
        )
    with pytest.raises(ValueError, match="file/child"):
        SourceTreeManifest(
            tree_id="tree-1",
            source_revision=REVISION,
            entries=(
                SourceTreeEntry("a", digest, 0),
                SourceTreeEntry("a/b.txt", digest, 0),
            ),
            ignored_roots=(".git",),
            provenance=provenance,
        )
    with pytest.raises(ValueError, match="case-insensitively unique"):
        SourceTreeManifest(
            tree_id="tree-1",
            source_revision=REVISION,
            entries=(SourceTreeEntry("safe.txt", digest, 0),),
            ignored_roots=(".GIT", ".git"),
            provenance=provenance,
        )


def test_failed_atomic_replace_leaves_no_addressed_object(tmp_path: Path, monkeypatch) -> None:
    import hashlib

    import daedalus.kernel.artifacts as artifacts

    store = ArtifactStore(tmp_path / "cas")
    digest = hashlib.sha256(b"payload").hexdigest()

    def fail_replace(source, target):
        raise OSError("fault injection")

    monkeypatch.setattr(artifacts.os, "replace", fail_replace)
    with pytest.raises(OSError, match="fault injection"):
        store.put_bytes(b"payload")
    assert not store._object_path(digest).exists()
    assert not list(store._object_path(digest).parent.glob(f".{digest}.*"))
