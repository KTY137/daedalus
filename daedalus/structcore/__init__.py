"""structcore — the Universal Structural Core (Daedalus Movement I).

A derived, regenerated (never hand-maintained) multi-language structural index:
duplication clusters, dependency fan-in/out, and per-unit health metrics across
Python, C/C++, Java, Rust, JS/TS, Go, QML and more.

Design contract (matches the harness invariants):
  * stdlib-first — works with ZERO third-party deps (Python via ``ast``; every
    other language via a universal windowed-normalization clone pass + comment-
    aware metrics).
  * degrade cleanly — if ``tree_sitter_language_pack`` is installed, unit-level
    (function/method) clone detection and precise metrics light up for the other
    languages too; if ``lizard`` is installed, real cyclomatic complexity is
    added. Neither is required; absence never crashes, it only lowers precision.
  * derive, don't maintain — regenerate and it is true by construction.

This generalizes ``project_tct/TCT_app/tools/codemap.py`` (Python+QML only) into
a language-agnostic core the rest of Daedalus consumes.
"""
from __future__ import annotations

from .languages import LanguageSpec, spec_for, SPECS
from .index import build_index, backend_status, cached_index
from .forest import (
    ForestEdge,
    ForestHyperedge,
    ForestNode,
    KnowledgeForest,
    build_knowledge_forest,
)
from .dss import (
    ContextPlan,
    DSSConfig,
    DSSReceipt,
    DSSResult,
    ForestHierarchy,
    build_forest_hierarchy,
    semantic_super_sample,
)

# NOTE: ``semantic_slice`` lives in ``daedalus.structcore.slice`` and is imported
# lazily (below) rather than eagerly, so ``python -m daedalus.structcore.slice``
# doesn't trip the "module imported before execution" RuntimeWarning.
__all__ = [
    "LanguageSpec", "spec_for", "SPECS", "build_index", "backend_status",
    "cached_index", "semantic_slice", "estimate_tokens",
    "ForestNode", "ForestEdge", "ForestHyperedge", "KnowledgeForest",
    "build_knowledge_forest",
    "ForestHierarchy", "DSSConfig", "ContextPlan", "DSSReceipt", "DSSResult",
    "build_forest_hierarchy", "semantic_super_sample",
]


def __getattr__(name):  # PEP 562 lazy re-export
    if name in ("semantic_slice", "estimate_tokens"):
        from . import slice as _slice

        return getattr(_slice, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
