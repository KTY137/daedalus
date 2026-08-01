from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from daedalus.twin import (
    ReferenceCompileError,
    ReferenceLimits,
    compile_reference_project,
)

REVISION = "b" * 40
NOW = "2026-08-01T18:45:00Z"
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"


def _copy_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "wiki_app"
    shutil.copytree(FIXTURE, target)
    return target


def _compile(root: Path, *, revision: str = REVISION, limits: ReferenceLimits | None = None):
    kwargs = {}
    if limits is not None:
        kwargs["limits"] = limits
    return compile_reference_project(
        root,
        source_revision=revision,
        created_at=NOW,
        trace_id="tr-reference-hardening",
        **kwargs,
    )


def test_source_bundle_identity_binds_exact_bytes_not_revision_label(tmp_path: Path) -> None:
    first_root = _copy_fixture(tmp_path / "first")
    second_root = _copy_fixture(tmp_path / "second")

    first = _compile(first_root)
    second = _compile(second_root, revision="c" * 40)

    assert len(first.source_bundle_sha256) == 64
    assert first.source_bundle_sha256 == second.source_bundle_sha256
    assert first.snapshot.digest != second.snapshot.digest
    assert first.forest.provenance["source_bundle_sha256"] == first.source_bundle_sha256

    source = second_root / "src" / "knowledge_hub" / "search.py"
    source.write_text(source.read_text(encoding="utf-8") + "\n# mutation\n", encoding="utf-8")
    mutated = _compile(second_root, revision="c" * 40)
    assert mutated.source_bundle_sha256 != second.source_bundle_sha256


def test_duplicate_manifest_and_schema_json_keys_refuse(tmp_path: Path) -> None:
    manifest_root = _copy_fixture(tmp_path / "manifest")
    manifest_path = manifest_root / "fourfold.json"
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        manifest_text.replace(
            "{\n",
            '{\n  "schema": "daedalus-fourfold-reference/1",\n',
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(ReferenceCompileError, match="duplicate JSON key 'schema'"):
        _compile(manifest_root)

    schema_root = _copy_fixture(tmp_path / "schema")
    schema_path = schema_root / "schemas" / "article.schema.json"
    schema_text = schema_path.read_text(encoding="utf-8")
    schema_path.write_text(
        schema_text.replace("{\n", '{\n  "type": "object",\n', 1),
        encoding="utf-8",
    )
    with pytest.raises(ReferenceCompileError, match="duplicate JSON key 'type'"):
        _compile(schema_root)


def test_reference_resource_limits_fail_closed(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)

    with pytest.raises(ReferenceCompileError, match="file count exceeds limit"):
        _compile(root, limits=ReferenceLimits(max_files=1))

    with pytest.raises(ReferenceCompileError, match="file exceeds byte limit"):
        _compile(root, limits=ReferenceLimits(max_file_bytes=10))

    with pytest.raises(ReferenceCompileError, match="claim count exceeds limit"):
        _compile(root, limits=ReferenceLimits(max_claims=1))

    with pytest.raises(ReferenceCompileError, match="source bytes exceed limit"):
        _compile(root, limits=ReferenceLimits(max_total_bytes=100))


def test_declared_symlink_is_refused(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    source = root / "src" / "knowledge_hub" / "search.py"
    source.unlink()
    try:
        source.symlink_to("models.py")
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ReferenceCompileError, match="symbolic link"):
        _compile(root)


def test_non_object_json_schema_refuses_cleanly(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    schema_path = root / "schemas" / "article.schema.json"
    schema_path.write_text("[]\n", encoding="utf-8")

    with pytest.raises(ReferenceCompileError, match="JSON Schema must be an object"):
        _compile(root)
