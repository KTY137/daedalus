"""Compatibility facade for :mod:`daedalus.orchestration.ikarus_runtime_events`.

G1-FLAT-01 moved the implementation into ``daedalus.orchestration``. This
module preserves the flat dotted path with exact object identity and holds no
second implementation.

The re-export is a plain module-scope ``from`` import on purpose. A
``sys.modules`` swap or a ``ModuleType.__getattr__`` forwarder would make this
edge invisible to ``ast.walk``, which is the only thing the import-boundary
checker, the SCC census and ``test_nothing_imports_langgraph_at_module_scope``
can see. Opacity here would buy nothing -- this module has no monkeypatch seam
to forward -- and would cost every static instrument its view of the edge.

Source-level and monkeypatch assertions belong on the owner, not here: a test
that reads this file's source would be reading a re-export list and would pass
no matter what the implementation did.
"""

from .orchestration.ikarus_runtime_events import (
    RUNTIME_EVENT_PROJECTION_SCHEMA,
    RuntimeEventProjection,
    RuntimeEventProjectionError,
    RuntimeEventProjector,
    RuntimeToolEvent,
    RuntimeToolPlanEntry,
    RuntimeToolProjectionRow,
)

__all__ = [
    "RUNTIME_EVENT_PROJECTION_SCHEMA",
    "RuntimeEventProjection",
    "RuntimeEventProjectionError",
    "RuntimeEventProjector",
    "RuntimeToolEvent",
    "RuntimeToolPlanEntry",
    "RuntimeToolProjectionRow",
]
