"""Compatibility wrapper for :mod:`daedalus.kairos.decompose`."""

from .kairos.decompose import (
    _ask_model,
    _coerce_item,
    _fallback,
    _parse_subtasks,
    _user_prompt,
    decompose,
)

__all__ = ["decompose"]
