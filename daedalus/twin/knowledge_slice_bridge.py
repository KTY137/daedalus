"""Merge knowledge evidence into the existing provider ``slice_texts`` API.

The bridge does not call a model and does not choose files. It receives an
already access-scoped :class:`KnowledgePromptEnvelope` and an existing mapping
produced by DSS/context planning. Existing source context always remains first;
knowledge is appended as an explicitly untrusted evidence block. The operation
is deterministic and emits a receipt that binds both input mappings and the
merged result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping

from ..spine.envelope import canonical_sha
from .knowledge_correlation import KnowledgeCorrelationError
from .knowledge_prompt import KnowledgePromptEnvelope


_SEPARATOR = "\n\n---\n\n"


def _bounded_mapping(value: Mapping[str, str], label: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, Mapping):
        raise KnowledgeCorrelationError(f"{label} must be a mapping")
    rows: list[tuple[str, str]] = []
    for path, text in value.items():
        if not isinstance(path, str) or not path or path.startswith("/"):
            raise KnowledgeCorrelationError(f"{label} contains an invalid path")
        normalized = path.replace("\\", "/")
        if ".." in normalized.split("/"):
            raise KnowledgeCorrelationError(f"{label} path escapes its root")
        if not isinstance(text, str) or "\x00" in text:
            raise KnowledgeCorrelationError(f"{label}[{path!r}] is not safe text")
        rows.append((normalized, text))
    normalized_rows = tuple(sorted(rows))
    if len({path for path, _ in normalized_rows}) != len(normalized_rows):
        raise KnowledgeCorrelationError(f"{label} paths collide after normalization")
    return normalized_rows


def _mapping_digest(rows: tuple[tuple[str, str], ...]) -> str:
    return canonical_sha(
        [{"path": path, "text_sha256": canonical_sha(text)} for path, text in rows]
    )


@dataclass(frozen=True)
class KnowledgeSliceBridgeReceipt:
    base_slice_sha256: str
    knowledge_prompt_sha256: str
    merged_slice_sha256: str
    paths: tuple[str, ...]
    base_chars: int
    knowledge_chars: int
    merged_chars: int

    SCHEMA: ClassVar[str] = "daedalus-knowledge-slice-bridge-receipt/1"

    def __post_init__(self) -> None:
        paths = tuple(sorted(set(self.paths)))
        if not paths:
            raise KnowledgeCorrelationError("slice bridge receipt requires paths")
        object.__setattr__(self, "paths", paths)
        for name in ("base_chars", "knowledge_chars", "merged_chars"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise KnowledgeCorrelationError(f"{name} must be non-negative")
        expected = self.base_chars + self.knowledge_chars
        overlap_count = len(paths)  # informational only; separator accounted below by builder
        if self.merged_chars < expected:
            raise KnowledgeCorrelationError(
                "merged slice cannot contain fewer characters than its inputs"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "base_slice_sha256": self.base_slice_sha256,
            "knowledge_prompt_sha256": self.knowledge_prompt_sha256,
            "merged_slice_sha256": self.merged_slice_sha256,
            "paths": list(self.paths),
            "base_chars": self.base_chars,
            "knowledge_chars": self.knowledge_chars,
            "merged_chars": self.merged_chars,
            "authority_granted": False,
            "effect_performed": False,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeAugmentedSlices:
    slice_texts: tuple[tuple[str, str], ...]
    receipt: KnowledgeSliceBridgeReceipt

    @property
    def mapping(self) -> Mapping[str, str]:
        return dict(self.slice_texts)

    @property
    def digest(self) -> str:
        return canonical_sha(
            {
                "slice_texts": [
                    {"path": path, "text": text} for path, text in self.slice_texts
                ],
                "receipt_sha256": self.receipt.digest,
            }
        )


def merge_knowledge_slice_texts(
    base_slice_texts: Mapping[str, str],
    knowledge: KnowledgePromptEnvelope,
    *,
    max_total_chars: int = 200_000,
    max_per_path_chars: int = 100_000,
) -> KnowledgeAugmentedSlices:
    """Append untrusted knowledge evidence without replacing source context."""

    if not isinstance(knowledge, KnowledgePromptEnvelope):
        raise KnowledgeCorrelationError("knowledge must be KnowledgePromptEnvelope")
    if max_total_chars < 1 or max_per_path_chars < 1:
        raise KnowledgeCorrelationError("slice bridge budgets must be positive")
    base_rows = _bounded_mapping(base_slice_texts, "base_slice_texts")
    knowledge_rows = _bounded_mapping(knowledge.slice_texts, "knowledge.slice_texts")
    merged = dict(base_rows)
    for path, text in knowledge_rows:
        if path in merged and merged[path]:
            merged[path] = merged[path] + _SEPARATOR + text
        else:
            merged[path] = text
    merged_rows = tuple(sorted(merged.items()))
    for path, text in merged_rows:
        if len(text) > max_per_path_chars:
            raise KnowledgeCorrelationError(
                f"merged slice exceeds per-path budget for {path!r}"
            )
    merged_chars = sum(len(text) for _, text in merged_rows)
    if merged_chars > max_total_chars:
        raise KnowledgeCorrelationError("merged slice exceeds total character budget")
    receipt = KnowledgeSliceBridgeReceipt(
        base_slice_sha256=_mapping_digest(base_rows),
        knowledge_prompt_sha256=knowledge.digest,
        merged_slice_sha256=_mapping_digest(merged_rows),
        paths=tuple(path for path, _ in merged_rows),
        base_chars=sum(len(text) for _, text in base_rows),
        knowledge_chars=sum(len(text) for _, text in knowledge_rows),
        merged_chars=merged_chars,
    )
    return KnowledgeAugmentedSlices(slice_texts=merged_rows, receipt=receipt)


__all__ = [
    "KnowledgeAugmentedSlices",
    "KnowledgeSliceBridgeReceipt",
    "merge_knowledge_slice_texts",
]
