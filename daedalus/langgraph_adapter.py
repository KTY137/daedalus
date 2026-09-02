"""Compatibility facade for :mod:`daedalus.orchestration.langgraph_adapter`.

G1-FLAT-01 moved the implementation into ``daedalus.orchestration``, the
package ``CLAUDE.md`` already names as the home of the one canonical
orchestration adapter. This module preserves the flat dotted path with exact
object identity and holds no second implementation -- moving it did not create
the "zweiter, danebenstehender Runner" that repo policy and master-plan section
13 forbid, because there is still exactly one implementation and this file
contains none of it.

The re-export is a plain module-scope ``from`` import on purpose; see the note
in :mod:`daedalus.ikarus_runtime_events` for why an opaque forwarder was
rejected.

Two properties this facade must not break, both pinned by tests:

* No module-scope ``langgraph`` import. The owner keeps its ``langgraph``
  imports inside ``build_graph``/``build_advisory_fleet_graph``, so importing
  this facade still costs zero third-party dependencies. That deferral is
  OPTIONAL-DEPENDENCY ISOLATION, not cycle avoidance, and must stay.
* ``daedalus.runbook`` still imports ``run_brief`` lazily, inside the
  ``engine == "langgraph"`` branch, for the same reason.

``langgraph_available`` is re-exported BY VALUE. Rebinding it on this facade
does not change what the owner's ``build_graph`` resolves, so a test that
monkeypatches it must patch ``daedalus.orchestration.langgraph_adapter``.
"""

from .orchestration.langgraph_adapter import (
    MAX_ADVISORY_FLEET_CAPACITY,
    AdvisoryFleetState,
    BriefState,
    LangGraphUnavailable,
    build_advisory_fleet_graph,
    build_graph,
    langgraph_available,
    plan_advisory_fleet,
    run_brief,
    tracing_is_pinned_off,
)

__all__ = [
    "MAX_ADVISORY_FLEET_CAPACITY",
    "AdvisoryFleetState",
    "BriefState",
    "LangGraphUnavailable",
    "build_advisory_fleet_graph",
    "build_graph",
    "langgraph_available",
    "plan_advisory_fleet",
    "run_brief",
    "tracing_is_pinned_off",
]
