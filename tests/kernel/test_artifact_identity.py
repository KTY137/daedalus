# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.kernel.artifacts import (
    ArtifactIdentityError,
    ArtifactRef,
    artifact_locator,
    digest_file_tree,
    store_canonical_json,
)


def test_artifact_ref_derives_and_verifies_exact_locator() -> None:
    digest = "a" * 64
    ref = ArtifactRef.from_sha256(digest)
    assert ref.sha256 == digest
    assert ref.locator == f"artifact-locator:sha256:{digest}"
    assert artifact_locator(digest) == ref.locator
    with pytest.raises(ArtifactIdentityError, match="does not resolve"):
        ArtifactRef(digest, f"artifact-locator:sha256:{'b' * 64}")


def test_canonical_json_store_is_idempotent_and_collision_safe(tmp_path: Path) -> None:
    first = store_canonical_json(tmp_path, {"b": 2, "a": 1})
    second = store_canonical_json(tmp_path, {"a": 1, "b": 2})
    assert first == second
    path = tmp_path / f"{first.sha256}.json"
    assert json.loads(path.read_text(encoding="ascii")) == {"a": 1, "b": 2}

    path.write_text("{}", encoding="ascii")
    with pytest.raises(ArtifactIdentityError, match="collision"):
        store_canonical_json(tmp_path, {"a": 1, "b": 2})


def test_file_tree_digest_is_order_stable_and_content_sensitive(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "b.txt").write_text("beta", encoding="utf-8")
    (left / "a.txt").write_text("alpha", encoding="utf-8")
    (right / "a.txt").write_text("alpha", encoding="utf-8")
    (right / "b.txt").write_text("beta", encoding="utf-8")
    assert digest_file_tree(left) == digest_file_tree(right)

    (right / "b.txt").write_text("changed", encoding="utf-8")
    assert digest_file_tree(left) != digest_file_tree(right)


def test_file_tree_digest_refuses_symlink_state(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    target = root / "target.txt"
    target.write_text("payload", encoding="utf-8")
    link = root / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlinks are unavailable on this platform")
    with pytest.raises(ArtifactIdentityError, match="symlink"):
        digest_file_tree(root)
