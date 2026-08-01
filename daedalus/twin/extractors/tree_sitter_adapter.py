"""Optional Tree-sitter structural extractors for polyglot source artifacts.

Tree-sitter establishes syntax structure, not semantic truth. The adapter emits
staged observations and a fail-closed :class:`ExtractorResult`; a separate
verifier must map accepted observations into the authoritative Forest.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
from importlib import metadata
from typing import Any, Iterator

from ...spine.envelope import canonical_sha
from .contracts import ExtractorDiagnostic, ExtractorResult, SourceArtifact


class TreeSitterUnavailable(RuntimeError):
    """Raised when an optional parser runtime or grammar is not installed."""


@dataclass(frozen=True)
class ParseLimits:
    max_source_bytes: int = 4_000_000
    max_nodes: int = 500_000
    max_symbols: int = 100_000

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_PARSE_LIMITS = ParseLimits()


@dataclass(frozen=True)
class StructuralSymbol:
    node_id: str
    kind: str
    name: str
    syntax_type: str
    start_byte: int
    end_byte: int
    evidence_sha256: str


@dataclass(frozen=True)
class StructuralParseReport:
    artifact: SourceArtifact
    root_kind: str
    symbols: tuple[StructuralSymbol, ...]
    error_nodes: int
    total_nodes: int
    report_sha256: str
    result: ExtractorResult


_LANGUAGE_MODULES: dict[str, tuple[str, str, str]] = {
    "rust": ("tree_sitter_rust", "tree-sitter-rust", "rust"),
    "java": ("tree_sitter_java", "tree-sitter-java", "java"),
    "cpp": ("tree_sitter_cpp", "tree-sitter-cpp", "cpp"),
    "c-cpp-header": ("tree_sitter_cpp", "tree-sitter-cpp", "cpp"),
    "root-macro": ("tree_sitter_cpp", "tree-sitter-cpp", "cpp"),
}

_SYMBOL_KINDS: dict[str, dict[str, str]] = {
    "rust": {
        "function_item": "function",
        "struct_item": "struct",
        "enum_item": "enum",
        "trait_item": "trait",
        "impl_item": "impl",
        "type_item": "type-alias",
        "mod_item": "module",
        "const_item": "constant",
        "static_item": "static",
        "macro_definition": "macro",
    },
    "java": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "record_declaration": "record",
        "annotation_type_declaration": "annotation",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
    },
    "cpp": {
        "namespace_definition": "namespace",
        "class_specifier": "class",
        "struct_specifier": "struct",
        "union_specifier": "union",
        "enum_specifier": "enum",
        "function_definition": "function",
        "alias_declaration": "type-alias",
        "type_definition": "type-definition",
        "concept_definition": "concept",
    },
}

_NAME_NODE_TYPES = frozenset({
    "identifier",
    "type_identifier",
    "field_identifier",
    "namespace_identifier",
    "scoped_identifier",
    "qualified_identifier",
    "destructor_name",
    "operator_name",
})


def _load_language(language_id: str):
    try:
        module_name, distribution, grammar_id = _LANGUAGE_MODULES[language_id]
    except KeyError as exc:
        raise TreeSitterUnavailable(
            f"no Tree-sitter adapter registered for {language_id}"
        ) from exc
    try:
        tree_sitter = importlib.import_module("tree_sitter")
        grammar = importlib.import_module(module_name)
    except ImportError as exc:
        raise TreeSitterUnavailable(
            f"optional Tree-sitter dependency missing for {language_id}"
        ) from exc
    language = tree_sitter.Language(grammar.language())
    parser = tree_sitter.Parser(language)
    try:
        version = (
            f"tree-sitter={metadata.version('tree-sitter')};"
            f"{distribution}={metadata.version(distribution)}"
        )
    except metadata.PackageNotFoundError:
        version = "tree-sitter=unknown;grammar=unknown"
    return parser, version, grammar_id


def _walk(root: Any) -> Iterator[Any]:
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.children))


def _node_text(source: bytes, node: Any) -> str:
    return source[node.start_byte:node.end_byte].decode(
        "utf-8", errors="replace"
    ).strip()


def _first_name_node(node: Any) -> Any | None:
    queue: list[Any] = []
    for field in ("name", "declarator", "type", "trait"):
        candidate = node.child_by_field_name(field)
        if candidate is not None:
            queue.append(candidate)
    queue.extend(node.named_children)
    seen: set[tuple[int, int, str]] = set()
    offset = 0
    while offset < len(queue):
        candidate = queue[offset]
        offset += 1
        key = (candidate.start_byte, candidate.end_byte, candidate.type)
        if key in seen:
            continue
        seen.add(key)
        if candidate.type in _NAME_NODE_TYPES:
            return candidate
        for field in ("name", "declarator", "type", "trait"):
            nested = candidate.child_by_field_name(field)
            if nested is not None:
                queue.append(nested)
        queue.extend(candidate.named_children)
    return None


def _symbol_name(source: bytes, node: Any) -> str:
    candidate = _first_name_node(node)
    if candidate is None:
        return f"anonymous@{node.start_byte}"
    text = _node_text(source, candidate)
    return text if text else f"anonymous@{node.start_byte}"


def _failed_report(
    artifact: SourceArtifact,
    *,
    extractor_id: str,
    version: str,
    source_bundle_sha256: str,
    code: str,
    message: str,
) -> StructuralParseReport:
    diagnostic = ExtractorDiagnostic(code, "error", message, artifact.path)
    result = ExtractorResult(
        extractor_id=extractor_id,
        extractor_version=version,
        source_revision=artifact.source_revision,
        source_bundle_sha256=source_bundle_sha256,
        status="failed",
        diagnostics=(diagnostic,),
    )
    report_sha = canonical_sha({
        "schema": "daedalus-tree-sitter-report/1",
        "artifact": artifact.content_sha256,
        "status": "failed",
        "diagnostic": code,
    })
    return StructuralParseReport(artifact, "", (), 0, 0, report_sha, result)


def parse_artifact(
    artifact: SourceArtifact,
    content: bytes,
    *,
    source_bundle_sha256: str,
    limits: ParseLimits = DEFAULT_PARSE_LIMITS,
) -> StructuralParseReport:
    """Parse one immutable source artifact into staged structural symbols."""

    if not isinstance(artifact, SourceArtifact):
        raise ValueError("artifact must be a SourceArtifact")
    if not isinstance(content, bytes):
        raise ValueError("content must be bytes")
    if hashlib.sha256(content).hexdigest() != artifact.content_sha256:
        raise ValueError("content does not match artifact.content_sha256")
    if len(content) != artifact.size_bytes:
        raise ValueError("content length does not match artifact.size_bytes")
    if not isinstance(limits, ParseLimits):
        raise ValueError("limits must be a ParseLimits record")

    parser, version, grammar_id = _load_language(artifact.language_id)
    extractor_id = f"tree-sitter-{grammar_id}"
    if len(content) > limits.max_source_bytes:
        return _failed_report(
            artifact,
            extractor_id=extractor_id,
            version=version,
            source_bundle_sha256=source_bundle_sha256,
            code="source-too-large",
            message=(
                f"source exceeds parser byte limit: "
                f"{len(content)} > {limits.max_source_bytes}"
            ),
        )

    tree = parser.parse(content)
    root = tree.root_node
    syntax_family = _LANGUAGE_MODULES[artifact.language_id][2]
    kinds = _SYMBOL_KINDS[syntax_family]
    symbols: list[StructuralSymbol] = []
    error_nodes = 0
    total_nodes = 0

    for node in _walk(root):
        total_nodes += 1
        if total_nodes > limits.max_nodes:
            return _failed_report(
                artifact,
                extractor_id=extractor_id,
                version=version,
                source_bundle_sha256=source_bundle_sha256,
                code="node-limit-exceeded",
                message=(
                    f"syntax node limit exceeded: "
                    f"{total_nodes} > {limits.max_nodes}"
                ),
            )
        if node.type == "ERROR" or node.is_missing:
            error_nodes += 1
        kind = kinds.get(node.type)
        if kind is None:
            continue
        if len(symbols) >= limits.max_symbols:
            return _failed_report(
                artifact,
                extractor_id=extractor_id,
                version=version,
                source_bundle_sha256=source_bundle_sha256,
                code="symbol-limit-exceeded",
                message=(
                    f"symbol limit exceeded: "
                    f"{len(symbols) + 1} > {limits.max_symbols}"
                ),
            )
        name = _symbol_name(content, node)
        evidence = canonical_sha({
            "schema": "daedalus-tree-sitter-symbol/1",
            "artifact_sha256": artifact.content_sha256,
            "path": artifact.path,
            "language": artifact.language_id,
            "syntax_type": node.type,
            "kind": kind,
            "name": name,
            "start_byte": node.start_byte,
            "end_byte": node.end_byte,
        })
        name_digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
        node_id = (
            f"code:symbol:{artifact.path}#"
            f"{kind}:{name_digest}@{node.start_byte}"
        )
        symbols.append(
            StructuralSymbol(
                node_id=node_id,
                kind=kind,
                name=name,
                syntax_type=node.type,
                start_byte=node.start_byte,
                end_byte=node.end_byte,
                evidence_sha256=evidence,
            )
        )

    if root.has_error and error_nodes == 0:
        error_nodes = 1
    symbols_tuple = tuple(
        sorted(symbols, key=lambda item: (item.start_byte, item.end_byte, item.node_id))
    )
    report_sha = canonical_sha({
        "schema": "daedalus-tree-sitter-report/1",
        "artifact_sha256": artifact.content_sha256,
        "language": artifact.language_id,
        "root_kind": root.type,
        "error_nodes": error_nodes,
        "total_nodes": total_nodes,
        "symbols": [
            {
                "node_id": item.node_id,
                "kind": item.kind,
                "name": item.name,
                "syntax_type": item.syntax_type,
                "start_byte": item.start_byte,
                "end_byte": item.end_byte,
                "evidence_sha256": item.evidence_sha256,
            }
            for item in symbols_tuple
        ],
    })
    diagnostics: tuple[ExtractorDiagnostic, ...] = ()
    status = "complete"
    if error_nodes:
        status = "partial"
        diagnostics = (
            ExtractorDiagnostic(
                "syntax-errors",
                "warning",
                f"Tree-sitter retained {error_nodes} error or missing nodes",
                artifact.path,
            ),
        )
    result = ExtractorResult(
        extractor_id=extractor_id,
        extractor_version=version,
        source_revision=artifact.source_revision,
        source_bundle_sha256=source_bundle_sha256,
        status=status,
        node_ids=tuple(item.node_id for item in symbols_tuple),
        evidence_sha256s=tuple({
            artifact.content_sha256,
            report_sha,
            *(item.evidence_sha256 for item in symbols_tuple),
        }),
        diagnostics=diagnostics,
    )
    return StructuralParseReport(
        artifact=artifact,
        root_kind=root.type,
        symbols=symbols_tuple,
        error_nodes=error_nodes,
        total_nodes=total_nodes,
        report_sha256=report_sha,
        result=result,
    )


__all__ = [
    "DEFAULT_PARSE_LIMITS",
    "ParseLimits",
    "StructuralParseReport",
    "StructuralSymbol",
    "TreeSitterUnavailable",
    "parse_artifact",
]
