"""Kairos orchestration compatibility and capability-bearing entrypoints."""

from .promotion_entrypoint import (
    promote_candidates as promote_candidates_with_persisted_effect,
)

__all__ = ["promote_candidates_with_persisted_effect"]
