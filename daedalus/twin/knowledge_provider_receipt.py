"""Join the knowledge evidence chain to the final provider slice mapping."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, ClassVar

from ..spine.envelope import canonical_sha
from .knowledge_correlation import KnowledgeCorrelationError
from .knowledge_receipt import KnowledgeAttemptContextReceipt
from .knowledge_slice_bridge import KnowledgeAugmentedSlices


_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


def _sha(value: str, name: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
        raise KnowledgeCorrelationError(f"{name} must be lowercase sha256")
    return value


@dataclass(frozen=True)
class KnowledgeProviderContextReceipt:
    knowledge_attempt_receipt_sha256: str
    slice_bridge_receipt_sha256: str
    provider_context_sha256: str
    source_revision: str
    target_paths: tuple[str, ...]
    merged_chars: int

    SCHEMA: ClassVar[str] = "daedalus-knowledge-provider-context-receipt/1"

    def __post_init__(self) -> None:
        for name in (
            "knowledge_attempt_receipt_sha256",
            "slice_bridge_receipt_sha256",
            "provider_context_sha256",
        ):
            object.__setattr__(self, name, _sha(getattr(self, name), name))
        if not isinstance(self.source_revision, str) or not self.source_revision.strip():
            raise KnowledgeCorrelationError("source_revision must not be empty")
        paths = tuple(sorted(set(self.target_paths)))
        if not paths:
            raise KnowledgeCorrelationError("provider context receipt requires paths")
        object.__setattr__(self, "target_paths", paths)
        if (
            isinstance(self.merged_chars, bool)
            or not isinstance(self.merged_chars, int)
            or self.merged_chars < 0
        ):
            raise KnowledgeCorrelationError("merged_chars must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "knowledge_attempt_receipt_sha256": (
                self.knowledge_attempt_receipt_sha256
            ),
            "slice_bridge_receipt_sha256": self.slice_bridge_receipt_sha256,
            "provider_context_sha256": self.provider_context_sha256,
            "source_revision": self.source_revision,
            "target_paths": list(self.target_paths),
            "merged_chars": self.merged_chars,
            "model_invocation_claimed": False,
            "effect_performed": False,
            "authority_granted": False,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def build_knowledge_provider_context_receipt(
    knowledge_receipt: KnowledgeAttemptContextReceipt,
    augmented: KnowledgeAugmentedSlices,
) -> KnowledgeProviderContextReceipt:
    """Bind the knowledge receipt to the exact merged provider context."""

    if not isinstance(knowledge_receipt, KnowledgeAttemptContextReceipt):
        raise KnowledgeCorrelationError(
            "knowledge_receipt must be KnowledgeAttemptContextReceipt"
        )
    if not isinstance(augmented, KnowledgeAugmentedSlices):
        raise KnowledgeCorrelationError(
            "augmented must be KnowledgeAugmentedSlices"
        )
    bridge = augmented.receipt
    if bridge.knowledge_prompt_sha256 != knowledge_receipt.prompt_envelope_sha256:
        raise KnowledgeCorrelationError(
            "slice bridge does not bind the knowledge prompt from the attempt receipt"
        )
    if not set(knowledge_receipt.target_paths).issubset(bridge.paths):
        raise KnowledgeCorrelationError(
            "slice bridge omitted a knowledge target path"
        )
    return KnowledgeProviderContextReceipt(
        knowledge_attempt_receipt_sha256=knowledge_receipt.digest,
        slice_bridge_receipt_sha256=bridge.digest,
        provider_context_sha256=augmented.digest,
        source_revision=knowledge_receipt.source_revision,
        target_paths=bridge.paths,
        merged_chars=bridge.merged_chars,
    )


__all__ = [
    "KnowledgeProviderContextReceipt",
    "build_knowledge_provider_context_receipt",
]
