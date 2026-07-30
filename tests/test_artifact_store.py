"""Gate-0 contract for the canonical content-addressed artifact store.

Every test uses an isolated temporary root.  Nothing here depends on the
repository checkout, global Daedalus state, or a successful model/evaluator.
"""
from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import daedalus.atomic as atomic
import daedalus.storage as storage
from daedalus.atomic import publish_bytes_once
from daedalus.storage import (
    ArtifactCorruption,
    ArtifactDigestMismatch,
    ArtifactNotFound,
    ArtifactStore,
    ArtifactStoreError,
)


PAYLOAD = b"\x00candidate patch\n\xffauthoritative bytes\n"
DIGEST = hashlib.sha256(PAYLOAD).hexdigest()
PROVENANCE = {
    "origin": "test.artifact-store",
    "source_revision": "a" * 40,
    "created_at": "2026-07-30T00:00:00.000000+00:00",
    "input_digests": ["1" * 64],
    "trace_id": None,
}


def put(store: ArtifactStore, **overrides):
    kwargs = {
        "expected_sha256": DIGEST,
        "media_type": "application/vnd.daedalus.test",
        "metadata": {"kind": "candidate", "number": 1},
        "provenance": PROVENANCE,
    }
    kwargs.update(overrides)
    return store.put_bytes(PAYLOAD, **kwargs)


def test_put_verifies_identity_and_emits_a_provenance_locator(tmp_path):
    store = ArtifactStore(tmp_path / "cas")
    locator = put(store)

    assert locator.artifact_sha256 == DIGEST
    assert locator.uri == f"sha256:{DIGEST}"
    assert locator.byte_length == len(PAYLOAD)
    assert locator.blob_path.read_bytes() == PAYLOAD
    assert locator.locator_path.is_file()
    assert locator.metadata == {"kind": "candidate", "number": 1}
    assert locator.provenance == PROVENANCE
    assert "local_paths" not in locator.portable_summary()
    assert str(store.root) not in str(locator.portable_summary())
    assert locator.summary()["local_paths"] == {
        "blob": str(locator.blob_path),
        "locator": str(locator.locator_path),
    }

    loaded = store.load_locator(locator.locator_sha256)
    assert loaded == locator
    assert store.verify(locator) == locator
    assert store.get_bytes(locator.uri) == PAYLOAD


def test_wrong_claim_is_refused_before_the_store_root_exists(tmp_path):
    root = tmp_path / "cas"
    store = ArtifactStore(root)

    with pytest.raises(ArtifactDigestMismatch):
        store.put_bytes(
            PAYLOAD,
            expected_sha256="0" * 64,
            provenance=PROVENANCE,
        )

    assert not root.exists()


def test_put_is_idempotent_for_identical_bytes_and_locator(tmp_path):
    store = ArtifactStore(tmp_path / "cas")

    first = put(store)
    blob_mtime = first.blob_path.stat().st_mtime_ns
    locator_mtime = first.locator_path.stat().st_mtime_ns
    second = put(store)

    assert second == first
    assert second.blob_path.stat().st_mtime_ns == blob_mtime
    assert second.locator_path.stat().st_mtime_ns == locator_mtime
    assert list((store.root / "blobs").rglob("*"))[-1].is_file()
    assert len([p for p in (store.root / "blobs").rglob("*") if p.is_file()]) == 1
    assert len([p for p in (store.root / "locators").rglob("*") if p.is_file()]) == 1


def test_distinct_provenance_reuses_blob_but_gets_distinct_locator(tmp_path):
    store = ArtifactStore(tmp_path / "cas")

    one = put(store)
    two = put(
        store,
        provenance={
            "origin": "test.artifact-store",
            "source_revision": "b" * 40,
            "created_at": "2026-07-30T00:00:00.000000+00:00",
            "input_digests": ["2" * 64],
            "trace_id": None,
        },
    )

    assert one.artifact_sha256 == two.artifact_sha256
    assert one.blob_path == two.blob_path
    assert one.locator_sha256 != two.locator_sha256
    assert len([p for p in (store.root / "blobs").rglob("*") if p.is_file()]) == 1
    assert len([p for p in (store.root / "locators").rglob("*") if p.is_file()]) == 2


def test_existing_corrupt_blob_is_detected_and_never_repaired_silently(tmp_path):
    store = ArtifactStore(tmp_path / "cas")
    locator = put(store)
    locator.blob_path.write_bytes(b"x" * len(PAYLOAD))

    with pytest.raises(ArtifactCorruption):
        store.get_bytes(DIGEST)
    with pytest.raises(ArtifactCorruption):
        put(store)

    assert locator.blob_path.read_bytes() == b"x" * len(PAYLOAD)


def test_corrupt_locator_is_detected_before_its_metadata_is_trusted(tmp_path):
    store = ArtifactStore(tmp_path / "cas")
    locator = put(store)
    locator.locator_path.write_bytes(locator.manifest_bytes + b" ")

    with pytest.raises(ArtifactCorruption):
        store.load_locator(locator.locator_sha256)
    with pytest.raises(ArtifactCorruption):
        store.verify(locator)


def test_self_consistent_but_under_attributed_locator_is_not_trusted(tmp_path):
    store = ArtifactStore(tmp_path / "cas")
    locator = put(store)
    forged = locator.to_dict()
    forged["provenance"] = {"origin": "forged"}
    forged_bytes = json.dumps(
        forged,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    forged_digest = hashlib.sha256(forged_bytes).hexdigest()
    forged_path = store.locator_path(forged_digest)
    forged_path.parent.mkdir(parents=True)
    forged_path.write_bytes(forged_bytes)

    with pytest.raises(ArtifactCorruption, match="invalid provenance"):
        store.load_locator(forged_digest)


def test_missing_blob_and_locator_are_named_refusals(tmp_path):
    store = ArtifactStore(tmp_path / "cas")

    with pytest.raises(ArtifactNotFound):
        store.get_bytes("1" * 64)
    with pytest.raises(ArtifactNotFound):
        store.load_locator("2" * 64)


@pytest.mark.parametrize(
    "bad_provenance, expected",
    [
        ({}, "missing canonical"),
        (
            {
                "origin": "test",
                "created_at": "2026-07-30T00:00:00+00:00",
                "input_digests": [],
            },
            "source_revision",
        ),
        (
            {
                "origin": "test",
                "source_revision": "not-a-revision",
                "created_at": "2026-07-30T00:00:00+00:00",
                "input_digests": [],
            },
            "source_revision",
        ),
        (
            {
                "origin": "test",
                "source_revision": "a" * 40,
                "created_at": "2026-07-30T00:00:00",
                "input_digests": [],
            },
            "timezone",
        ),
        (
            {
                "origin": "test",
                "source_revision": "a" * 40,
                "created_at": "2026-07-30T00:00:00+00:00",
                "input_digests": ["not-a-digest"],
            },
            "input_digests",
        ),
    ],
)
def test_provenance_is_structurally_required(
        tmp_path, bad_provenance, expected):
    store = ArtifactStore(tmp_path / "cas")

    with pytest.raises(ValueError, match=expected):
        store.put_bytes(PAYLOAD, provenance=bad_provenance)


def test_provenance_must_be_canonical_json(tmp_path):
    store = ArtifactStore(tmp_path / "cas")

    with pytest.raises(ValueError, match="canonical JSON"):
        store.put_bytes(
            PAYLOAD,
            provenance={**PROVENANCE, "bad": float("nan")},
        )


def test_artifact_volume_watermark_fails_before_any_directory_write(
        tmp_path, monkeypatch):
    root = tmp_path / "cas"
    store = ArtifactStore(root, min_free_gib=2.0)
    usage = type("Usage", (), {
        "total": 10 * 1024**3,
        "used": 9 * 1024**3,
        "free": 1024**3,
    })()
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda _: usage)

    with pytest.raises(storage.StorageUnavailable, match="storage_unavailable"):
        put(store)

    assert not root.exists()


def test_atomic_create_once_never_replaces_existing_bytes(tmp_path):
    target = tmp_path / "object"

    assert publish_bytes_once(target, b"first") is True
    assert publish_bytes_once(target, b"second") is False

    assert target.read_bytes() == b"first"
    assert list(tmp_path.glob("*.tmp")) == []


def test_link_publish_fault_leaves_no_partial_object_or_temp(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path / "cas")

    def refuse_link(source, target):
        raise OSError("fault injection: filesystem refused hard link")

    monkeypatch.setattr(atomic.os, "link", refuse_link)
    with pytest.raises(ArtifactStoreError, match="atomically published"):
        put(store)

    assert [p for p in store.root.rglob("*") if p.is_file()] == []
    assert list(store.root.rglob("*.tmp")) == []


def test_fault_between_blob_and_locator_is_safe_and_retryable(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path / "cas")
    real_publish = storage.publish_bytes_once
    calls = 0

    def fail_second_publish(path, data):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("fault injection: lost before locator publish")
        return real_publish(path, data)

    monkeypatch.setattr(storage, "publish_bytes_once", fail_second_publish)
    with pytest.raises(ArtifactStoreError, match="locator"):
        put(store)

    # Blob-first ordering leaves valid, reusable bytes and no false locator.
    assert store.get_bytes(DIGEST) == PAYLOAD
    locator_root = store.root / "locators"
    assert not locator_root.exists() or not any(
        p.is_file() for p in locator_root.rglob("*"))

    monkeypatch.setattr(storage, "publish_bytes_once", real_publish)
    recovered = put(store)
    assert store.verify(recovered) == recovered


def test_concurrent_identical_puts_converge_on_one_blob_and_locator(tmp_path):
    store = ArtifactStore(tmp_path / "cas")

    with ThreadPoolExecutor(max_workers=12) as pool:
        locators = list(pool.map(lambda _: put(store), range(48)))

    assert {item.artifact_sha256 for item in locators} == {DIGEST}
    assert {item.locator_sha256 for item in locators} == {
        locators[0].locator_sha256}
    assert len([p for p in (store.root / "blobs").rglob("*") if p.is_file()]) == 1
    assert len([p for p in (store.root / "locators").rglob("*") if p.is_file()]) == 1
    assert list(store.root.rglob("*.tmp")) == []


def test_existing_link_component_cannot_redirect_generated_paths(tmp_path):
    root = tmp_path / "cas"
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir()
    try:
        (root / "blobs").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable in this environment: {exc}")

    with pytest.raises(ArtifactStoreError, match="escapes store root"):
        put(ArtifactStore(root))

    assert [p for p in outside.rglob("*") if p.is_file()] == []


def test_store_root_cannot_be_replaced_with_a_redirect_after_construction(tmp_path):
    root = tmp_path / "cas"
    outside = tmp_path / "outside"
    outside.mkdir()
    store = ArtifactStore(root)
    try:
        root.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable in this environment: {exc}")

    with pytest.raises(ArtifactStoreError, match="escapes store root"):
        put(store)

    assert [p for p in outside.rglob("*") if p.is_file()] == []
