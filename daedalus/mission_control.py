"""Compatibility wrapper for :mod:`daedalus.kairos.control`."""

from .kairos.control import (
    dashboard,
    main_dashboard,
    main_models,
    main_review_diff,
    main_squads,
    main_watcher,
    ollama_models,
    quality_gates,
    queue_timeline,
    review_diff,
    squads,
    watcher_status,
)

__all__ = [
    "dashboard",
    "main_dashboard",
    "main_models",
    "main_review_diff",
    "main_squads",
    "main_watcher",
    "ollama_models",
    "quality_gates",
    "queue_timeline",
    "review_diff",
    "squads",
    "watcher_status",
]
