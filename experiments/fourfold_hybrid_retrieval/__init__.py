"""Contained Fourfold hybrid-retrieval experiment.

The package demonstrates the intended layering:

logical typed paths
    -> physical relation-block indices
    -> BM25/exact seed retrieval
    -> evidence-bearing graph expansion
    -> proposal-only ranking

Nothing here mutates Forest/Fourfold authority or participates in promotion.
"""

from .planner import (
    ContractionHit,
    ContractionPlan,
    ContractionResult,
    EvidenceDerivation,
    PathExpression,
    PhysicalContractionPlan,
    PhysicalPlanner,
    ReferenceContractionExecutor,
    RelationStep,
)
from .relations import (
    ProjectionSubject,
    RelationBlockCatalog,
    RelationCell,
    RelationSignature,
    TypedRelationBlock,
    compile_relation_blocks,
)
from .retrieval import (
    HybridHit,
    HybridRequest,
    HybridRetrievalReceipt,
    HybridRetriever,
    LexicalHit,
    NodeDocument,
    NodeDocumentIndex,
)

__all__ = [
    "ContractionHit",
    "ContractionPlan",
    "ContractionResult",
    "EvidenceDerivation",
    "HybridHit",
    "HybridRequest",
    "HybridRetrievalReceipt",
    "HybridRetriever",
    "LexicalHit",
    "NodeDocument",
    "NodeDocumentIndex",
    "PathExpression",
    "PhysicalContractionPlan",
    "PhysicalPlanner",
    "ProjectionSubject",
    "ReferenceContractionExecutor",
    "RelationBlockCatalog",
    "RelationCell",
    "RelationSignature",
    "RelationStep",
    "TypedRelationBlock",
    "compile_relation_blocks",
]
