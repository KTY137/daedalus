"""Revision-bound Fourfold Project Twin contracts and computational adapters.

Forest and Fourfold remain authoritative. Tensor views, relation blocks,
semiring observers and transformation 2-cells are bounded, regenerable semantic
projections: importing this package creates no store, schedules no work, grants
no trust and performs no promotion.
"""

from .contracts import (
    FOURFOLD_PLANES,
    CrossPlaneBinding,
    FourfoldSnapshot,
    PlaneSnapshot,
    parse_fourfold_snapshot,
)
from .legacy_forest import fourfold_from_knowledge_forest
from .projection_verifier import (
    ProjectionFinding,
    ProjectionVerificationReport,
    require_forest_projection,
    verify_forest_projection,
)
from .reference_compiler import (
    DEFAULT_REFERENCE_LIMITS,
    REFERENCE_SCHEMA,
    ReferenceCompileError,
    ReferenceCompileResult,
    ReferenceLimits,
    compile_reference_project,
)
from .relation_blocks import (
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from .relation_projection import boolean_relation_block_from_fourfold
from .semiring import (
    BooleanSemiring,
    EvidenceDagSemiring,
    EvidenceValue,
    NaturalSemiring,
    Semiring,
    TropicalSemiring,
)
from .tensor import SparseTensorEntry, TensorAxis, TensorView, parse_tensor_view
from .two_category import (
    BoundaryMap,
    BoundaryPort,
    OpenFourfoldComponent,
    Transformation2Cell,
    TypedBoundary,
    VerificationStatus,
)

__all__ = [
    "DEFAULT_REFERENCE_LIMITS",
    "FOURFOLD_PLANES",
    "REFERENCE_SCHEMA",
    "BooleanSemiring",
    "BoundaryMap",
    "BoundaryPort",
    "CrossPlaneBinding",
    "EvidenceDagSemiring",
    "EvidenceValue",
    "FourfoldSnapshot",
    "NaturalSemiring",
    "OpenFourfoldComponent",
    "PlaneSnapshot",
    "ProjectionFinding",
    "ProjectionSubject",
    "ProjectionVerificationReport",
    "ReferenceCompileError",
    "ReferenceCompileResult",
    "ReferenceLimits",
    "RelationSignature",
    "Semiring",
    "SparseTensorEntry",
    "TensorAxis",
    "TensorView",
    "Transformation2Cell",
    "TropicalSemiring",
    "TypedAxis",
    "TypedBoundary",
    "TypedRelationBlock",
    "VerificationStatus",
    "boolean_relation_block_from_fourfold",
    "compile_reference_project",
    "fourfold_from_knowledge_forest",
    "parse_fourfold_snapshot",
    "parse_tensor_view",
    "require_forest_projection",
    "verify_forest_projection",
]
