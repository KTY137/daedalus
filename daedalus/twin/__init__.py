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
    "DEFAULT_REFERENCE_LIMITS",
    "FOURFOLD_PLANES",
    "REFERENCE_SCHEMA",
    "CrossPlaneBinding",
    "FourfoldSnapshot",
    "PlaneSnapshot",
    "ProjectionFinding",
    "ProjectionVerificationReport",
    "ReferenceCompileError",
    "ReferenceCompileResult",
    "ReferenceLimits",
    "compile_reference_project",
    "fourfold_from_knowledge_forest",
    "parse_fourfold_snapshot",
    "require_forest_projection",
    "verify_forest_projection",
]
