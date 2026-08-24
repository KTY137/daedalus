"""Isolated Gate-0 semantic-composite tensor experiment.

The package is a proposal-only, precomputed-vector construct.  It has no model
execution, no production authority, and no automatic promotion path.
"""

from .backend import (
    CompositionRequest,
    ComposedSemanticVector,
    DirectSumBackend,
    VectorMaterial,
)
from .contracts import (
    ACTIVE_GATE,
    AUTOMATIC_PROMOTIONS,
    CLASSIFICATION,
    CompositeBlock,
    CompositeReceipt,
    CompositeSpaceSpec,
    CompositeVector,
    EncoderManifest,
    PACKET_SPEC_DIGEST,
    ProjectionManifest,
    SemanticContractError,
    VectorReceipt,
    text_digest,
    vector_digest,
)


__all__ = [
    "ACTIVE_GATE",
    "AUTOMATIC_PROMOTIONS",
    "CLASSIFICATION",
    "CompositeBlock",
    "CompositeReceipt",
    "CompositeSpaceSpec",
    "CompositeVector",
    "CompositionRequest",
    "ComposedSemanticVector",
    "DirectSumBackend",
    "EncoderManifest",
    "PACKET_SPEC_DIGEST",
    "ProjectionManifest",
    "SemanticContractError",
    "VectorMaterial",
    "VectorReceipt",
    "text_digest",
    "vector_digest",
]
