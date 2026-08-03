from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from daedalus.twin.extractors.contracts import SourceArtifact
from daedalus.twin.extractors import root_file_adapter as adapter

REVISION = "f" * 40
BUNDLE = "c" * 64
CONTENT = b"synthetic-root-metadata"


class FakeTree:
    def typenames(self):
        return {"voltage": "double", "channel": "int32_t"}


class FakeRootFile:
    closed = False

    def classnames(self, *, recursive: bool, cycle: bool):
        assert recursive is True
        assert cycle is False
        return {"Events": "TTree"}

    def __getitem__(self, path: str):
        assert path == "Events"
        return FakeTree()

    def close(self) -> None:
        self.closed = True


class FakeUproot:
    def __init__(self) -> None:
        self.file = FakeRootFile()

    def open(self, stream, *, object_cache, array_cache):
        assert stream.read() == CONTENT
        assert object_cache is None
        assert array_cache is None
        return self.file


def artifact() -> SourceArtifact:
    return SourceArtifact(
        repository_id="root-fixture",
        source_revision=REVISION,
        path="data/events.root",
        content_sha256=hashlib.sha256(CONTENT).hexdigest(),
        size_bytes=len(CONTENT),
        language_id="root-binary",
        artifact_kind="binary",
        framework_hints=("root",),
    )


def test_metadata_inventory_is_partial_without_optional_uproot(monkeypatch) -> None:
    fake = FakeUproot()
    monkeypatch.setattr(adapter, "_load_uproot", lambda: (fake, "fake-uproot=1"))

    report = adapter.inspect_root_artifact(
        artifact(),
        CONTENT,
        source_bundle_sha256=BUNDLE,
    )

    assert report.result.status == "partial"
    assert [item.code for item in report.result.diagnostics] == ["metadata-only"]
    assert fake.file.closed is True
    assert report.total_fields == 2
    assert {field.name for field in report.objects[0].fields} == {
        "voltage",
        "channel",
    }


def test_root_adapter_contains_no_success_complete_assignment() -> None:
    source = Path("daedalus/twin/extractors/root_file_adapter.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    status_values: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "status"
                for target in node.targets
            ) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                status_values.append(node.value.value)
        elif isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and node.target.id == "status"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                status_values.append(node.value.value)

    assert "complete" not in status_values
    assert "partial" in status_values
