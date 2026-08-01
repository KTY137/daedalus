from __future__ import annotations

import pytest

from daedalus.twin.extractors import (
    ExtractorCapabilities,
    ExtractorDiagnostic,
    ExtractorResult,
    SourceArtifact,
    detect_language,
    registered_language_ids,
)

SHA = "a" * 64


def test_polyglot_registry_distinguishes_languages_and_root_formats() -> None:
    assert detect_language("src/lib.rs").language_id == "rust"
    assert detect_language("src/main/java/org/example/App.java").language_id == "java"
    assert detect_language("src/event.cxx").language_id == "cpp"
    assert detect_language("macros/scan.C").language_id == "root-macro"
    assert detect_language("data/events.root").language_id == "root-binary"
    assert detect_language("schema/article.schema.json").language_id == "json-schema"
    assert detect_language("include/event.h").language_id == "c-cpp-header"


def test_root_binary_is_data_not_source_code() -> None:
    result = detect_language("samples/run42.root")
    assert result is not None
    assert result.artifact_kind == "binary"
    assert result.framework_hints == ("root",)


def test_build_system_files_are_discovered_without_claiming_language_semantics() -> None:
    assert detect_language("Cargo.toml").language_id == "rust-build"
    assert detect_language("backend/pom.xml").language_id == "java-build"
    assert detect_language("cpp/CMakeLists.txt").language_id == "cmake"


def test_registry_contains_initial_advanced_language_targets() -> None:
    ids = set(registered_language_ids())
    assert {"python", "rust", "java", "cpp", "root-macro", "root-binary"} <= ids


def test_source_artifact_requires_normalized_content_addressed_identity() -> None:
    artifact = SourceArtifact(
        repository_id="root-project-root",
        source_revision="e2340033ee068808980d9131a271111c6e77dc4f",
        path="tree/tree/src/TTree.cxx",
        content_sha256=SHA,
        size_bytes=42,
        language_id="cpp",
        artifact_kind="text",
        framework_hints=("root",),
    )
    assert artifact.path == "tree/tree/src/TTree.cxx"
    with pytest.raises(ValueError):
        SourceArtifact(
            repository_id="repo",
            source_revision="rev",
            path="../escape.rs",
            content_sha256=SHA,
            size_bytes=1,
            language_id="rust",
            artifact_kind="text",
        )


def test_extractor_capabilities_are_canonicalized() -> None:
    capabilities = ExtractorCapabilities(
        extractor_id="tree-sitter-rust",
        version="0.1.0",
        languages=("rust",),
        emitted_node_kinds=("function", "module", "struct"),
        emitted_relation_kinds=("declares", "has-field"),
    )
    assert capabilities.emitted_node_kinds == ("function", "module", "struct")


def test_complete_result_requires_evidence_and_no_error() -> None:
    with pytest.raises(ValueError):
        ExtractorResult(
            extractor_id="java-parser",
            extractor_version="1",
            source_revision="rev",
            source_bundle_sha256=SHA,
            status="complete",
        )
    with pytest.raises(ValueError):
        ExtractorResult(
            extractor_id="java-parser",
            extractor_version="1",
            source_revision="rev",
            source_bundle_sha256=SHA,
            status="complete",
            evidence_sha256s=(SHA,),
            diagnostics=(ExtractorDiagnostic("parse-error", "error", "bad source"),),
        )


def test_partial_and_unsupported_results_are_fail_closed() -> None:
    partial = ExtractorResult(
        extractor_id="root-dictionary",
        extractor_version="0.1",
        source_revision="rev",
        source_bundle_sha256=SHA,
        status="partial",
        node_ids=("type:root:TTree",),
        evidence_sha256s=(SHA,),
        diagnostics=(
            ExtractorDiagnostic(
                "dictionary-unavailable",
                "warning",
                "ROOT dictionary metadata was unavailable",
            ),
        ),
    )
    assert partial.status == "partial"

    with pytest.raises(ValueError):
        ExtractorResult(
            extractor_id="root-binary",
            extractor_version="0.1",
            source_revision="rev",
            source_bundle_sha256=SHA,
            status="unsupported",
            node_ids=("data:file.root",),
            diagnostics=(ExtractorDiagnostic("unsupported", "warning", "no uproot adapter"),),
        )
