"""Canonical internal orchestration services.

The package owns composition only. Mission, work-item, effect, attempt and
evidence authority remains in the existing kernel contracts and execution
ports. Legacy report projections remain owned by ``legacy_reports``.
"""

from importlib import import_module

__all__ = ["run_mission"]


def __getattr__(name: str):
    if name != "run_mission":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = import_module(f"{__name__}.missions").run_mission
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
