"""Canonical internal orchestration services.

The package owns composition only. Mission, work-item, effect, attempt and
evidence authority remains in the existing kernel contracts and execution
ports. Legacy report projections remain owned by ``legacy_reports``.
"""

from .missions import run_mission

__all__ = ["run_mission"]
