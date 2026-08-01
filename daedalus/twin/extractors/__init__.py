"""Versioned, language-neutral extractor adapter contracts."""

from .contracts import (
    ExtractorCapabilities,
    ExtractorDiagnostic,
    ExtractorResult,
    LanguageSpec,
    SourceArtifact,
)
from .registry import (
    LANGUAGE_SPECS,
    LanguageDetection,
    detect_language,
    registered_language_ids,
)
from .tree_sitter_adapter import (
    DEFAULT_PARSE_LIMITS,
    ParseLimits,
    StructuralParseReport,
    StructuralSymbol,
    TreeSitterUnavailable,
    parse_artifact,
)

__all__ = [
    "DEFAULT_PARSE_LIMITS",
    "LANGUAGE_SPECS",
    "ExtractorCapabilities",
    "ExtractorDiagnostic",
    "ExtractorResult",
    "LanguageDetection",
    "LanguageSpec",
    "ParseLimits",
    "SourceArtifact",
    "StructuralParseReport",
    "StructuralSymbol",
    "TreeSitterUnavailable",
    "detect_language",
    "parse_artifact",
    "registered_language_ids",
]
