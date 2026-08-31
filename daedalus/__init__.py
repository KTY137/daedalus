"""Lightweight event-driven agent harness for local app-building work.

The package root is a compatibility facade. Imports are lazy so inspecting an
independent hierarchy package cannot initialize router or contract owners.
"""

from importlib import import_module as _import_module


_EXPORTS = {
    "AgentReport": ("daedalus.orchestration.legacy_reports", "AgentReport"),
    "AgentTask": ("daedalus.orchestration.legacy_reports", "AgentTask"),
    "RunState": ("daedalus.orchestration.legacy_reports", "RunState"),
    "route_task": ("daedalus.router", "route_task"),
    "validate_report": ("daedalus.orchestration.legacy_reports", "validate_report"),
}

__all__ = ["AgentReport", "AgentTask", "RunState", "route_task", "validate_report"]


def __getattr__(name: str):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    value = getattr(_import_module(module_name), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
