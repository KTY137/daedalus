"""Strict untrusted-input loading for Gate-0 release reports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .release import Gate0ReleaseReport


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_gate0_release_report(payload: Mapping[str, Any]) -> Gate0ReleaseReport:
    """Parse one exact canonical release-report mapping.

    Derived fields are retained and checked by :meth:`Gate0ReleaseReport.from_dict`.
    The final equality check rejects alternate nested representations rather than
    silently canonicalizing attacker-controlled input before verification.
    """

    if not isinstance(payload, Mapping):
        raise ValueError("Gate-0 release report must be an object")
    wire = dict(payload)
    value = Gate0ReleaseReport.from_dict(wire)
    if wire != value.to_dict():
        raise ValueError("Gate-0 release report must use its exact canonical wire form")
    return value


def load_gate0_release_report(path: str | Path) -> Gate0ReleaseReport:
    """Load strict UTF-8 JSON while rejecting duplicate keys recursively."""

    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(payload, Mapping):
        raise ValueError("Gate-0 release report must be an object")
    return parse_gate0_release_report(payload)


__all__ = ["load_gate0_release_report", "parse_gate0_release_report"]
