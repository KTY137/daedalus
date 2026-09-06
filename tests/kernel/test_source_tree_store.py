from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from daedalus.kernel import (
    SourceTreeCaptureError,
    SourceTreeCorruptionError,
    SourceTreeEntry,
    SourceTreeManifest,
    SourceTreeStore,
    SourceTreeStoreError,
)
from daedalus.schemas import ContractProvenance


REVISION = "a" * 40
NOW = "2026-08-03T21:00:00+00:00"


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    (root / "README.md").write_text("# Example\n", encoding="utf-8")
    (root / "duplicate.txt").write_text("# Example\n", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("must-not-enter-cas\n", encoding="utf-8")
    (root / ".daedalus").mkdir()
    (root / ".daedalus" / "runtime.sqlite3").write_bytes(b"runtime")
    return root


def _capture(store: SourceTreeStore, source: Path, *, revision: str = REVISION):
    return store.capture_tree(
        source,
        tree_id="candidate-tree-1",
        source_revision=revision,
        origin="tests.source-tree",
        created_at=NOW,
        trace_id="attempt-1",
    )


def test_open_existing_is_effect_free_and_refuses_an_absent_store(tmp_path) -> None:
    root = tmp_path / "cas"
    provisioned = SourceTreeStore(root)
    ref = provisioned.put_bytes(b"immutable")
    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }

    opened = SourceTreeStore.open_existing(root)

    assert opened.read_bytes(ref, max_bytes=32) == b"immutable"
    assert {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    } == before
    missing = tmp_path / "missing"
    with pytest.raises(SourceTreeStoreError, match="existing"):
        SourceTreeStore.open_existing(missing)
    assert missing.exists() is False


def test_capture_is_deterministic_external_and_materializes_exact_tree(tmp_path) -> None:
    source = _source(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    before = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }

    first = _capture(store, source)
    second = _capture(store, source)

    assert first == second
    assert first.ref.sha256 == first.manifest.digest
    assert [entry.path for entry in first.manifest.entries] == [
        "README.md",
        "duplicate.txt",
        "pkg/app.py",
    ]
    assert len(first.manifest.provenance.input_digests) == 2
    assert all(not path.startswith((".git/", ".daedalus/")) for path in (
        entry.path for entry in first.manifest.entries
    ))
    after = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    assert after == before

    destination = tmp_path / "attempt-workspace"
    manifest = store.materialize_tree(first.ref, destination)
    assert manifest == first.manifest
    assert (destination / "README.md").read_text(encoding="utf-8") == "# Example\n"
    assert (destination / "pkg" / "app.py").read_text(encoding="utf-8") == "print('hello')\n"
    assert not (destination / ".git").exists()
    assert not (destination / ".daedalus").exists()


def test_materialization_retries_a_transient_atomic_publish_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import daedalus.atomic as atomic_module

    source = _source(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    stored = _capture(store, source)
    destination = tmp_path / "attempt-workspace"
    real_replace = atomic_module.os.replace
    attempts = 0

    def transient_replace(staging: object, target: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            error = PermissionError("transient Windows directory publish conflict")
            error.winerror = 5
            raise error
        real_replace(staging, target)

    monkeypatch.setattr(atomic_module.os, "replace", transient_replace)

    manifest = store.materialize_tree(stored.ref, destination)

    assert attempts == 2
    assert manifest == stored.manifest
    assert (destination / "README.md").read_bytes() == (
        source / "README.md"
    ).read_bytes()


def test_revision_is_part_of_manifest_identity(tmp_path) -> None:
    source = _source(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    first = _capture(store, source, revision=REVISION)
    second = _capture(store, source, revision="b" * 40)
    assert first.ref.sha256 != second.ref.sha256
    assert first.manifest.entries == second.manifest.entries


def test_store_inside_source_tree_is_refused_before_capture(tmp_path) -> None:
    source = _source(tmp_path)
    store = SourceTreeStore(source / "cas")
    with pytest.raises(SourceTreeCaptureError, match="outside the source tree"):
        _capture(store, source)


def test_symlink_and_special_entries_fail_closed(tmp_path) -> None:
    source = _source(tmp_path)
    link = source / "escape"
    try:
        os.symlink(source / "README.md", link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation is unavailable")
    store = SourceTreeStore(tmp_path / "cas")
    with pytest.raises(SourceTreeCaptureError, match="symlink"):
        _capture(store, source)


def test_bounds_are_applied_before_tree_publication(tmp_path) -> None:
    source = _source(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    with pytest.raises(SourceTreeCaptureError, match="exceeds"):
        store.capture_tree(
            source,
            tree_id="bounded-tree",
            source_revision=REVISION,
            origin="tests.source-tree",
            created_at=NOW,
            max_file_bytes=4,
            max_total_bytes=1024,
        )
    with pytest.raises(SourceTreeCaptureError, match="exceeds"):
        store.capture_tree(
            source,
            tree_id="bounded-tree",
            source_revision=REVISION,
            origin="tests.source-tree",
            created_at=NOW,
            max_file_bytes=1024,
            max_total_bytes=4,
        )


def test_corrupt_blob_and_manifest_are_rejected_on_every_read(tmp_path) -> None:
    source = _source(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    stored = _capture(store, source)
    blob = stored.manifest.entries[0]
    blob_path = store._object_path(blob.blob_sha256)
    blob_path.write_bytes(b"corrupt")
    with pytest.raises(SourceTreeCorruptionError, match="address"):
        store.read_bytes(
            f"artifact-locator:sha256:{blob.blob_sha256}",
            max_bytes=1024,
        )

    malformed = dict(stored.manifest.to_dict())
    malformed["entries"] = list(reversed(malformed["entries"]))
    malformed_ref = store.put_bytes(
        json.dumps(malformed, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    with pytest.raises(SourceTreeCorruptionError, match="noncanonical|digest"):
        store.load_tree(malformed_ref)


def test_duplicate_manifest_keys_are_refused(tmp_path) -> None:
    store = SourceTreeStore(tmp_path / "cas")
    raw = b'{"contract_type":"daedalus.source-tree-manifest","contract_type":"daedalus.source-tree-manifest"}'
    ref = store.put_bytes(raw)
    with pytest.raises(SourceTreeCorruptionError, match="strict UTF-8 JSON"):
        store.load_tree(ref)


def test_existing_destination_and_tight_materialization_limits_refuse_atomically(tmp_path) -> None:
    source = _source(tmp_path)
    store = SourceTreeStore(tmp_path / "cas")
    stored = _capture(store, source)
    destination = tmp_path / "existing"
    destination.mkdir()
    with pytest.raises(SourceTreeCaptureError, match="must not exist"):
        store.materialize_tree(stored.ref, destination)
    assert list(destination.iterdir()) == []

    bounded = tmp_path / "bounded-output"
    with pytest.raises(SourceTreeCaptureError, match="max_file_bytes"):
        store.materialize_tree(stored.ref, bounded, max_file_bytes=4)
    assert not bounded.exists()


def test_manifest_refuses_missing_metadata_exclusions_and_path_collisions() -> None:
    digest = "1" * 64
    provenance = ContractProvenance(
        origin="tests.source-tree",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(digest,),
    )
    with pytest.raises(ValueError, match="mandatory exclusions"):
        SourceTreeManifest(
            tree_id="tree-1",
            source_revision=REVISION,
            entries=(SourceTreeEntry("a", digest, 1),),
            ignored_roots=(".git",),
            provenance=provenance,
        )
    with pytest.raises(ValueError, match="case-insensitively"):
        SourceTreeManifest(
            tree_id="tree-1",
            source_revision=REVISION,
            entries=(
                SourceTreeEntry("A.txt", digest, 1),
                SourceTreeEntry("a.txt", digest, 1),
            ),
            ignored_roots=(".git", ".daedalus"),
            provenance=provenance,
        )


@pytest.mark.parametrize(
    "path",
    (".git/HEAD", ".GIT/HEAD", ".daedalus/state.json", ".DAEDALUS/state.json"),
)
def test_manifest_refuses_entries_below_ignored_roots_case_insensitively(
    path: str,
) -> None:
    digest = "1" * 64
    with pytest.raises(ValueError, match="must not live under ignored roots"):
        SourceTreeManifest(
            tree_id="ignored-entry",
            source_revision=REVISION,
            entries=(SourceTreeEntry(path, digest, 1),),
            ignored_roots=(".git", ".daedalus"),
            provenance=ContractProvenance(
                origin="tests.source-tree.ignored-entry",
                source_revision=REVISION,
                created_at=NOW,
                input_digests=(digest,),
            ),
        )


def test_shared_artifact_locator_authority_is_not_redefined() -> None:
    import daedalus.kernel.artifacts as artifacts
    import daedalus.kernel.source_trees as source_trees

    assert source_trees.artifact_locator is artifacts.artifact_locator
    assert not hasattr(source_trees, "locator_sha256")


def test_windows_creation_time_is_not_used_as_a_stability_clock() -> None:
    import daedalus.kernel.source_trees as source_trees

    windows_file = source_trees._stable_metadata_fields("nt", directory=False)
    windows_directory = source_trees._stable_metadata_fields("nt", directory=True)
    posix_file = source_trees._stable_metadata_fields("posix", directory=False)
    posix_directory = source_trees._stable_metadata_fields("posix", directory=True)

    assert "st_ctime_ns" not in windows_file
    assert "st_ctime_ns" not in windows_directory
    assert "st_ctime_ns" in posix_file
    assert "st_ctime_ns" in posix_directory
    assert windows_file == ("st_dev", "st_ino", "st_mtime_ns", "st_size")
    assert windows_directory == ("st_dev", "st_ino", "st_mtime_ns")
