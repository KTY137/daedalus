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
from .root_file_adapter import (
    DEFAULT_ROOT_READ_LIMITS,
    RootDataReport,
    RootFieldRecord,
    RootObjectRecord,
    RootReadLimits,
    RootReaderUnavailable,
    inspect_root_artifact,
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
    "DEFAULT_ROOT_READ_LIMITS",
    "LANGUAGE_SPECS",
    "ExtractorCapabilities",
    "ExtractorDiagnostic",
    "ExtractorResult",
    "LanguageDetection",
    "LanguageSpec",
    "ParseLimits",
    "RootDataReport",
    "RootFieldRecord",
    "RootObjectRecord",
    "RootReadLimits",
    "RootReaderUnavailable",
    "SourceArtifact",
    "StructuralParseReport",
    "StructuralSymbol",
    "TreeSitterUnavailable",
    "detect_language",
    "inspect_root_artifact",
    "parse_artifact",
    "registered_language_ids",
]
