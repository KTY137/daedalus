# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib

import pytest

uproot = pytest.importorskip("uproot")
np = pytest.importorskip("numpy")

from daedalus.twin.extractors import (
    RootReadLimits,
    SourceArtifact,
    inspect_root_artifact,
)

REVISION = "f" * 40
BUNDLE = "c" * 64


def artifact(content: bytes) -> SourceArtifact:
    return SourceArtifact(
        repository_id="root-fixture",
        source_revision=REVISION,
        path="data/events.root",
        content_sha256=hashlib.sha256(content).hexdigest(),
        size_bytes=len(content),
        language_id="root-binary",
        artifact_kind="binary",
        framework_hints=("root",),
    )


def test_root_file_extractor_inventories_tree_fields_without_reading_payloads(
    tmp_path,
) -> None:
    path = tmp_path / "events.root"
    with uproot.recreate(path) as root_file:
        tree = root_file.mktree(
            "Events",
            {"voltage": "float64", "channel": "int32"},
        )
        tree.extend({
            "voltage": np.asarray([1.0, 2.0], dtype="float64"),
            "channel": np.asarray([3, 4], dtype="int32"),
        })
    content = path.read_bytes()

    report = inspect_root_artifact(
        artifact(content),
        content,
        source_bundle_sha256=BUNDLE,
    )

    assert report.result.status == "complete"
    event = next(record for record in report.objects if record.object_path == "Events")
    assert event.kind == "tree"
    assert {field.name for field in event.fields} == {"voltage", "channel"}
    assert report.total_fields == 2
    assert len(report.result.relation_sha256s) == 2
    assert len(report.report_sha256) == 64


def test_root_report_is_deterministic(tmp_path) -> None:
    path = tmp_path / "minimal.root"
    with uproot.recreate(path) as root_file:
        root_file["value"] = "metadata"
    content = path.read_bytes()
    source = artifact(content)

    first = inspect_root_artifact(source, content, source_bundle_sha256=BUNDLE)
    second = inspect_root_artifact(source, content, source_bundle_sha256=BUNDLE)
    assert first == second


def test_invalid_or_oversized_root_file_fails_closed() -> None:
    invalid = b"not a ROOT file"
    failed = inspect_root_artifact(
        artifact(invalid),
        invalid,
        source_bundle_sha256=BUNDLE,
    )
    assert failed.result.status == "failed"
    assert failed.result.diagnostics[0].code == "root-open-failed"

    limited = inspect_root_artifact(
        artifact(invalid),
        invalid,
        source_bundle_sha256=BUNDLE,
        limits=RootReadLimits(max_source_bytes=1),
    )
    assert limited.result.status == "failed"
    assert limited.result.diagnostics[0].code == "root-file-too-large"
