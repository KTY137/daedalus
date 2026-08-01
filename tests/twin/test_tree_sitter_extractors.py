from __future__ import annotations

import hashlib

import pytest

pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_rust")
pytest.importorskip("tree_sitter_java")
pytest.importorskip("tree_sitter_cpp")

from daedalus.twin.extractors import SourceArtifact
from daedalus.twin.extractors.tree_sitter_adapter import ParseLimits, parse_artifact

REVISION = "d" * 40
BUNDLE = "b" * 64


def artifact(
    path: str,
    language: str,
    source: bytes,
    *,
    frameworks: tuple[str, ...] = (),
) -> SourceArtifact:
    return SourceArtifact(
        repository_id="polyglot-fixture",
        source_revision=REVISION,
        path=path,
        content_sha256=hashlib.sha256(source).hexdigest(),
        size_bytes=len(source),
        language_id=language,
        artifact_kind="text",
        framework_hints=frameworks,
    )


@pytest.mark.parametrize(
    ("path", "language", "source", "expected"),
    [
        (
            "src/lib.rs",
            "rust",
            b"pub struct Event { pub voltage: f64 }\n"
            b"pub trait Readout { fn read(&self); }\n"
            b"impl Readout for Event { fn read(&self) {} }\n"
            b"pub fn run() {}\n",
            {"struct", "trait", "impl", "function"},
        ),
        (
            "src/main/java/org/example/Event.java",
            "java",
            b"package org.example; "
            b"public record Event(double voltage) { "
            b"public double scaled() { return voltage * 2; } } "
            b"interface Readout { void read(); }",
            {"record", "method", "interface"},
        ),
        (
            "src/Event.cxx",
            "cpp",
            b"namespace det { struct Event { double voltage; }; "
            b"double scale(double x) { return x * 2.0; } }",
            {"namespace", "struct", "function"},
        ),
        (
            "macros/scan.C",
            "root-macro",
            b"void scan() { int bins = 16; }",
            {"function"},
        ),
    ],
)
def test_tree_sitter_extracts_staged_structural_symbols(
    path: str,
    language: str,
    source: bytes,
    expected: set[str],
) -> None:
    report = parse_artifact(
        artifact(
            path,
            language,
            source,
            frameworks=("root",) if language == "root-macro" else (),
        ),
        source,
        source_bundle_sha256=BUNDLE,
    )
    assert report.result.status == "complete"
    assert expected <= {symbol.kind for symbol in report.symbols}
    assert set(report.result.node_ids) == {symbol.node_id for symbol in report.symbols}
    assert len(report.report_sha256) == 64


def test_tree_sitter_report_is_deterministic() -> None:
    source = b"pub enum State { Ready, Running }\npub fn start() {}\n"
    source_artifact = artifact("src/state.rs", "rust", source)
    first = parse_artifact(source_artifact, source, source_bundle_sha256=BUNDLE)
    second = parse_artifact(source_artifact, source, source_bundle_sha256=BUNDLE)
    assert first == second


def test_parser_errors_are_partial_not_complete() -> None:
    source = b"public class Broken { void run( { }"
    report = parse_artifact(
        artifact("src/Broken.java", "java", source),
        source,
        source_bundle_sha256=BUNDLE,
    )
    assert report.result.status == "partial"
    assert report.error_nodes > 0
    assert report.result.diagnostics[0].code == "syntax-errors"


def test_parser_limits_and_content_identity_fail_closed() -> None:
    source = b"pub fn run() {}\n"
    source_artifact = artifact("src/lib.rs", "rust", source)
    failed = parse_artifact(
        source_artifact,
        source,
        source_bundle_sha256=BUNDLE,
        limits=ParseLimits(max_source_bytes=1),
    )
    assert failed.result.status == "failed"
    assert not failed.symbols

    with pytest.raises(ValueError, match="content does not match"):
        parse_artifact(
            source_artifact,
            source + b"x",
            source_bundle_sha256=BUNDLE,
        )
