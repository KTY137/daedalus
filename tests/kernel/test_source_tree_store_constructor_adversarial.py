from __future__ import annotations

from types import SimpleNamespace

import pytest

from daedalus.kernel import (
    SourceTreeEntry,
    SourceTreeManifest,
    SourceTreeStore,
    StoredSourceTree,
)
from daedalus.schemas import ContractProvenance


REVISION = "a" * 40
NOW = "2026-08-03T21:00:00+00:00"
DIGEST = "1" * 64


def _provenance() -> ContractProvenance:
    return ContractProvenance(
        origin="tests.source-tree-constructor",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(DIGEST,),
    )


def test_manifest_rejects_entry_shaped_constructor_bypass() -> None:
    fake = SimpleNamespace(path="file.txt", blob_sha256=DIGEST, size=1, executable=False)
    with pytest.raises(ValueError, match="SourceTreeEntry records"):
        SourceTreeManifest(
            tree_id="tree-1",
            source_revision=REVISION,
            entries=(fake,),
            ignored_roots=(".daedalus", ".git"),
            provenance=_provenance(),
        )


def test_manifest_rejects_provenance_shaped_constructor_bypass() -> None:
    fake = SimpleNamespace(
        source_revision=REVISION,
        input_digests=(DIGEST,),
    )
    with pytest.raises(ValueError, match="ContractProvenance"):
        SourceTreeManifest(
            tree_id="tree-1",
            source_revision=REVISION,
            entries=(SourceTreeEntry("file.txt", DIGEST, 1),),
            ignored_roots=(".daedalus", ".git"),
            provenance=fake,
        )


def test_stored_tree_rejects_artifact_ref_shaped_constructor_bypass() -> None:
    manifest = SourceTreeManifest(
        tree_id="tree-1",
        source_revision=REVISION,
        entries=(SourceTreeEntry("file.txt", DIGEST, 1),),
        ignored_roots=(".daedalus", ".git"),
        provenance=_provenance(),
    )
    fake_ref = SimpleNamespace(sha256=manifest.digest, locator="artifact-locator:sha256:" + manifest.digest)
    with pytest.raises(ValueError, match="ArtifactRef"):
        StoredSourceTree(manifest=manifest, ref=fake_ref)


def test_uppercase_configuration_cannot_replace_canonical_mandatory_names(tmp_path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    store = SourceTreeStore(tmp_path / "cas")
    with pytest.raises(ValueError, match="mandatory exclusions"):
        store.capture_tree(
            source,
            tree_id="tree-1",
            source_revision=REVISION,
            origin="tests.source-tree-constructor",
            created_at=NOW,
            ignored_roots=(".DAEDALUS", ".GIT"),
        )


def test_read_ref_rejects_arbitrary_digest_shaped_objects(tmp_path) -> None:
    store = SourceTreeStore(tmp_path / "cas")
    fake = SimpleNamespace(sha256=DIGEST, locator="artifact-locator:sha256:" + DIGEST)
    with pytest.raises(ValueError, match="ArtifactRef or canonical locator"):
        store.read_bytes(fake, max_bytes=1)
