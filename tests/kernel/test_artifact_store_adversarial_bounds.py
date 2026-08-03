from __future__ import annotations

from pathlib import Path

import pytest

import daedalus.kernel.artifacts as artifacts
from daedalus.kernel.artifacts import ArtifactStore, SourceTreeError


REVISION = "a" * 40
NOW = "2026-08-03T06:40:00+00:00"


def capture(
    store: ArtifactStore,
    root: Path,
    **changes,
):
    values = {
        "tree_id": "tree-adversarial",
        "source_revision": REVISION,
        "origin": "tests.source-tree-adversarial",
        "created_at": NOW,
        "trace_id": "mission-adversarial",
    }
    values.update(changes)
    return store.capture_tree(root, **values)


def test_source_limit_refuses_before_reading_the_full_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "large.bin").write_bytes(b"0123456789")
    store = ArtifactStore(tmp_path / "cas")

    real_read = artifacts.os.read
    requested_sizes: list[int] = []

    def guarded_read(descriptor: int, count: int) -> bytes:
        requested_sizes.append(count)
        if count > 5:
            raise AssertionError("source boundary attempted an unbounded read")
        return real_read(descriptor, count)

    monkeypatch.setattr(artifacts.os, "read", guarded_read)

    with pytest.raises(SourceTreeError, match="max_file_bytes"):
        capture(store, source, max_file_bytes=4)

    # A stat-visible oversized file is refused before the first data read. If a
    # file grows after open, the production loop reads at most limit + 1 bytes.
    assert requested_sizes == []
    assert not [path for path in store.objects.rglob("*") if path.is_file()]


def test_total_limit_is_enforced_before_reading_the_next_blob(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "a.bin").write_bytes(b"1234")
    (source / "b.bin").write_bytes(b"5678")
    store = ArtifactStore(tmp_path / "cas")

    real_read_source = store._read_source_file
    calls: list[tuple[str, int, str]] = []

    def observed_read(path: Path, *, max_bytes: int, limit_name: str):
        calls.append((path.name, max_bytes, limit_name))
        return real_read_source(path, max_bytes=max_bytes, limit_name=limit_name)

    monkeypatch.setattr(store, "_read_source_file", observed_read)

    with pytest.raises(SourceTreeError, match="max_total_bytes"):
        capture(store, source, max_file_bytes=10, max_total_bytes=6)

    assert calls == [
        ("a.bin", 6, "max_total_bytes"),
        ("b.bin", 2, "max_total_bytes"),
    ]


def test_mandatory_repository_metadata_exclusions_cannot_be_removed(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("x = 1\n", encoding="utf-8")
    store = ArtifactStore(tmp_path / "cas")

    with pytest.raises(ValueError, match="mandatory metadata exclusions"):
        capture(store, source, ignored_roots=(".git",))

    assert not [path for path in store.objects.rglob("*") if path.is_file()]


def test_directory_replacement_during_capture_is_not_silently_omitted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    package = source / "pkg"
    package.mkdir()
    (package / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    store = ArtifactStore(tmp_path / "cas")

    real_walk = artifacts.os.walk

    def replacing_walk(*args, **kwargs):
        first = True
        for row in real_walk(*args, **kwargs):
            yield row
            if first:
                package.rename(source / "pkg-original")
                package.mkdir()
                first = False

    monkeypatch.setattr(artifacts.os, "walk", replacing_walk)

    with pytest.raises(SourceTreeError, match="directory changed|disappeared"):
        capture(store, source)

    # Blobs may be orphaned in a CAS after a refused capture, but no manifest
    # object or StoredSourceTree is published to the caller.
