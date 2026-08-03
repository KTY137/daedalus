"""Revision-bound Fourfold Project Twin contracts and adapters.

The package is intentionally additive while Gate 0 is active. It does not
replace :mod:`daedalus.structcore.forest`, create another store, or schedule
work. A FourfoldSnapshot is a canonical semantic view over evidence produced
for one exact source revision.
"""

from .contracts import (
    FOURFOLD_PLANES,
    CrossPlaneBinding,
    FourfoldSnapshot,
    PlaneSnapshot,
    parse_fourfold_snapshot,
)
from .delta import (
    BindingDelta,
    GraphDelta,
    PlaneDelta,
    compute_graph_delta,
    parse_graph_delta,
    require_graph_delta,
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

__all__ = [
    "BindingDelta",
    "DEFAULT_REFERENCE_LIMITS",
    "FOURFOLD_PLANES",
    "REFERENCE_SCHEMA",
    "CrossPlaneBinding",
    "FourfoldSnapshot",
    "GraphDelta",
    "PlaneDelta",
    "PlaneSnapshot",
    "ProjectionFinding",
    "ProjectionVerificationReport",
    "ReferenceCompileError",
    "ReferenceCompileResult",
    "ReferenceLimits",
    "compile_reference_project",
    "compute_graph_delta",
    "fourfold_from_knowledge_forest",
    "parse_fourfold_snapshot",
    "parse_graph_delta",
    "require_forest_projection",
    "require_graph_delta",
    "verify_forest_projection",
]
