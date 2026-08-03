"""Strict JSON boundary for Gate-0 exact-head evidence.

Dataclass ``from_dict`` methods are useful for already typed internal values,
but untrusted JSON requires shape checks before any tuple/list coercion. This
module is the supported file/wire entrypoint and rejects duplicate object keys,
strings repackaged as arrays, malformed nested records, and noncanonical wires
that would otherwise normalize into the same evidence identity.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .evidence import GateEvidenceIndex

_TOP_ARRAY_FIELDS = (
    "required_workflow_ids",
    "required_artifact_kinds",
    "required_runtime_ids",
    "required_fault_matrix_ids",
    "required_review_perspectives",
    "workflows",
    "artifacts",
    "runtimes",
    "fault_matrices",
    "reviews",
)


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
        raise ValueError(f"{label} must be an array, not {type(value).__name__}")
    return value


def _validate_shape(payload: Mapping[str, Any]) -> None:
    for field_name in _TOP_ARRAY_FIELDS:
        if field_name not in payload:
            continue
        _array(payload[field_name], field_name)

    for index, row in enumerate(_array(payload.get("workflows", ()), "workflows")):
        record = _object(row, f"workflows[{index}]")
        if "artifact_sha256s" in record:
            _array(record["artifact_sha256s"], f"workflows[{index}].artifact_sha256s")
        if "provenance" in record:
            _object(record["provenance"], f"workflows[{index}].provenance")

    for field_name in ("artifacts", "runtimes"):
        for index, row in enumerate(_array(payload.get(field_name, ()), field_name)):
            record = _object(row, f"{field_name}[{index}]")
            if "provenance" in record:
                _object(record["provenance"], f"{field_name}[{index}].provenance")

    for index, row in enumerate(
        _array(payload.get("fault_matrices", ()), "fault_matrices")
    ):
        record = _object(row, f"fault_matrices[{index}]")
        if "scenario_ids" in record:
            _array(record["scenario_ids"], f"fault_matrices[{index}].scenario_ids")
        if "provenance" in record:
            _object(record["provenance"], f"fault_matrices[{index}].provenance")

    for index, row in enumerate(_array(payload.get("reviews", ()), "reviews")):
        record = _object(row, f"reviews[{index}]")
        if "unresolved_finding_ids" in record:
            _array(
                record["unresolved_finding_ids"],
                f"reviews[{index}].unresolved_finding_ids",
            )
        if "provenance" in record:
            _object(record["provenance"], f"reviews[{index}].provenance")

    owner = payload.get("owner_decision")
    if owner is not None:
        record = _object(owner, "owner_decision")
        if "provenance" in record:
            _object(record["provenance"], "owner_decision.provenance")
    if "provenance" in payload:
        _object(payload["provenance"], "provenance")


def parse_gate_evidence_index(payload: Mapping[str, Any]) -> GateEvidenceIndex:
    """Parse only the exact canonical evidence-index wire representation."""

    record = _object(payload, "Gate evidence index")
    _validate_shape(record)
    wire = dict(record)
    index = GateEvidenceIndex.from_dict(wire)
    if wire != index.to_dict():
        raise ValueError("Gate evidence index must use its exact canonical wire form")
    return index


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_gate_evidence_index(path: str | Path) -> GateEvidenceIndex:
    """Read strict UTF-8 JSON and reject duplicate keys at every object level."""

    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    return parse_gate_evidence_index(_object(payload, "Gate evidence index"))


__all__ = ["load_gate_evidence_index", "parse_gate_evidence_index"]
