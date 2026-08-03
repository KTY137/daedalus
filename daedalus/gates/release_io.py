"""Strict untrusted-input loading for Gate-0 release verification artifacts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .release import Gate0ReleaseReport
from .report import GateReport


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _load_object(path: str | Path, label: str) -> Mapping[str, Any]:
    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must be an object")
    return payload


def parse_gate0_release_report(payload: Mapping[str, Any]) -> Gate0ReleaseReport:
    """Parse one exact canonical release-report mapping."""

    if not isinstance(payload, Mapping):
        raise ValueError("Gate-0 release report must be an object")
    wire = dict(payload)
    value = Gate0ReleaseReport.from_dict(wire)
    if wire != value.to_dict():
        raise ValueError("Gate-0 release report must use its exact canonical wire form")
    return value


def load_gate0_release_report(path: str | Path) -> Gate0ReleaseReport:
    """Load strict UTF-8 JSON while rejecting duplicate keys recursively."""

    return parse_gate0_release_report(_load_object(path, "Gate-0 release report"))


def parse_mechanical_gate_report(payload: Mapping[str, Any]) -> GateReport:
    """Parse the original Gate projection without normalizing its wire claims."""

    if not isinstance(payload, Mapping):
        raise ValueError("mechanical Gate report must be an object")
    wire = dict(payload)
    value = GateReport.from_dict(wire)
    if wire != value.to_dict():
        raise ValueError("mechanical Gate report must use its exact canonical wire form")
    return value


def load_mechanical_gate_report(path: str | Path) -> GateReport:
    """Load the mechanical report through duplicate-key and canonical checks."""

    return parse_mechanical_gate_report(_load_object(path, "mechanical Gate report"))


__all__ = [
    "load_gate0_release_report",
    "load_mechanical_gate_report",
    "parse_gate0_release_report",
    "parse_mechanical_gate_report",
]
