from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from daedalus.twin.extractors.contracts import SourceArtifact
from daedalus.twin.extractors import tree_sitter_adapter as adapter

REVISION = "d" * 40
BUNDLE = "b" * 64
SOURCE = b"pub fn run() {}\n"


class FakeNode:
    def __init__(
        self,
        node_type: str,
        start_byte: int,
        end_byte: int,
        *,
        children=(),
        fields=None,
        missing: bool = False,
        has_error: bool = False,
    ) -> None:
        self.type = node_type
        self.start_byte = start_byte
        self.end_byte = end_byte
        self.children = tuple(children)
        self.named_children = tuple(children)
        self._fields = dict(fields or {})
        self.is_missing = missing
        self.has_error = has_error

    def child_by_field_name(self, name: str):
        return self._fields.get(name)


class FakeParser:
    def __init__(self, root: FakeNode) -> None:
        self.root = root

    def parse(self, content: bytes):
        assert content == SOURCE
        return type("FakeTree", (), {"root_node": self.root})()


def source_artifact() -> SourceArtifact:
    return SourceArtifact(
        repository_id="polyglot-fixture",
        source_revision=REVISION,
        path="src/lib.rs",
        content_sha256=hashlib.sha256(SOURCE).hexdigest(),
        size_bytes=len(SOURCE),
        language_id="rust",
        artifact_kind="text",
    )


def fake_root() -> FakeNode:
    identifier = FakeNode("identifier", 7, 10)
    function = FakeNode(
        "function_item",
        0,
        len(SOURCE),
        children=(identifier,),
        fields={"name": identifier},
    )
    return FakeNode(
        "source_file",
        0,
        len(SOURCE),
        children=(function,),
    )


def test_clean_structural_parse_is_partial_without_optional_tree_sitter(monkeypatch) -> None:
    monkeypatch.setattr(
        adapter,
        "_load_language",
        lambda language_id: (FakeParser(fake_root()), "fake-parser=1", language_id),
    )

    report = adapter.parse_artifact(
        source_artifact(),
        SOURCE,
        source_bundle_sha256=BUNDLE,
    )

    assert report.result.status == "partial"
    assert [item.code for item in report.result.diagnostics] == ["structural-only"]
    assert len(report.symbols) == 1
    assert report.symbols[0].kind == "function"
    assert report.symbols[0].name == "run"


def test_structural_adapter_contains_no_success_complete_assignment() -> None:
    source = Path("daedalus/twin/extractors/tree_sitter_adapter.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    assignments = [
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and (
            any(
                isinstance(target, ast.Name) and target.id == "status"
                for target in node.targets
            )
            if isinstance(node, ast.Assign)
            else isinstance(node.target, ast.Name) and node.target.id == "status"
        )
    ]
    assert "complete" not in assignments
    assert "partial" in assignments
