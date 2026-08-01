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

__all__ = [
    "LANGUAGE_SPECS",
    "ExtractorCapabilities",
    "ExtractorDiagnostic",
    "ExtractorResult",
    "LanguageDetection",
    "LanguageSpec",
    "SourceArtifact",
    "detect_language",
    "registered_language_ids",
]
