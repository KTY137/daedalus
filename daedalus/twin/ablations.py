"""Frozen four-plane ablation evidence for Gate 2."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
from typing import Any, Mapping

from daedalus.schemas import _sha256

_VARIANTS = (
    "code-only",
    "four-separate-indices",
    "full-four-plane",
    "without-code",
    "without-data",
    "without-knowledge",
    "without-type",
)
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class FourPlaneAblationError(ValueError):
    """Raised when ablation evidence is incomplete, incomparable, or noncanonical."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise FourPlaneAblationError(f"{field} must be a non-empty string")
    return value


@dataclasses.dataclass(frozen=True, slots=True)
class AblationResult:
    variant: str
    quality_score: float
    cost_units: float
    successful_tasks: int
    total_tasks: int
    evidence_sha256: str

    def __post_init__(self) -> None:
        if self.variant not in _VARIANTS:
            raise FourPlaneAblationError("unsupported ablation variant")
        if isinstance(self.quality_score, bool) or not isinstance(self.quality_score, (int, float)) or not math.isfinite(self.quality_score):
            raise FourPlaneAblationError("quality_score must be finite")
        if self.quality_score < 0.0 or self.quality_score > 1.0:
            raise FourPlaneAblationError("quality_score must be between zero and one")
        if isinstance(self.cost_units, bool) or not isinstance(self.cost_units, (int, float)) or not math.isfinite(self.cost_units) or self.cost_units <= 0:
            raise FourPlaneAblationError("cost_units must be finite and positive")
        if isinstance(self.successful_tasks, bool) or not isinstance(self.successful_tasks, int) or self.successful_tasks < 0:
            raise FourPlaneAblationError("successful_tasks must be a non-negative integer")
        if isinstance(self.total_tasks, bool) or not isinstance(self.total_tasks, int) or self.total_tasks <= 0:
            raise FourPlaneAblationError("total_tasks must be a positive integer")
        if self.successful_tasks > self.total_tasks:
            raise FourPlaneAblationError("successful_tasks cannot exceed total_tasks")
        object.__setattr__(self, "quality_score", float(self.quality_score))
        object.__setattr__(self, "cost_units", float(self.cost_units))
        object.__setattr__(self, "evidence_sha256", _sha256(self.evidence_sha256, "evidence_sha256"))

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AblationResult":
        if set(payload) != {"variant", "quality_score", "cost_units", "successful_tasks", "total_tasks", "evidence_sha256"}:
            raise FourPlaneAblationError("ablation result fields are not canonical")
        return cls(**payload)


@dataclasses.dataclass(frozen=True, slots=True)
class FourPlaneAblationReport:
    schema: str
    project_twin_manifest_sha256: str
    evaluator_contract_sha256: str
    task_set_sha256: str
    budget_contract_sha256: str
    seed_policy_sha256: str
    metric_id: str
    minimum_margin: float
    results: tuple[AblationResult, ...]

    def __post_init__(self) -> None:
        if self.schema != "daedalus-four-plane-ablation-report/1":
            raise FourPlaneAblationError("unsupported four-plane ablation schema")
        for field in (
            "project_twin_manifest_sha256",
            "evaluator_contract_sha256",
            "task_set_sha256",
            "budget_contract_sha256",
            "seed_policy_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        if not _ID_RE.fullmatch(_text(self.metric_id, "metric_id")):
            raise FourPlaneAblationError("metric_id must use a canonical identifier")
        if isinstance(self.minimum_margin, bool) or not isinstance(self.minimum_margin, (int, float)) or not math.isfinite(self.minimum_margin):
            raise FourPlaneAblationError("minimum_margin must be finite")
        if self.minimum_margin <= 0.0 or self.minimum_margin > 1.0:
            raise FourPlaneAblationError("minimum_margin must be in (0, 1]")
        object.__setattr__(self, "minimum_margin", float(self.minimum_margin))
        variants = tuple(item.variant for item in self.results)
        if variants != _VARIANTS:
            raise FourPlaneAblationError("results must contain every required variant once in canonical order")
        if len({item.total_tasks for item in self.results}) != 1:
            raise FourPlaneAblationError("all variants must use the same task count")

    @property
    def blockers(self) -> tuple[str, ...]:
        by_variant = {item.variant: item for item in self.results}
        full = by_variant["full-four-plane"]
        blockers: set[str] = set()
        simpler = (by_variant["code-only"], by_variant["four-separate-indices"])
        best_simple = max(simpler, key=lambda item: item.quality_score)
        if full.quality_score < best_simple.quality_score + self.minimum_margin:
            blockers.add("full-representation-does-not-beat-simpler-control")
        if full.cost_units > max(item.cost_units for item in simpler):
            blockers.add("full-representation-exceeds-control-budget")
        for plane in ("code", "data", "knowledge", "type"):
            removed = by_variant[f"without-{plane}"]
            if full.quality_score <= removed.quality_score:
                blockers.add(f"plane-{plane}-has-no-positive-marginal-contribution")
        return tuple(sorted(blockers))

    @property
    def closed_for_gate2(self) -> bool:
        return not self.blockers

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json_bytes()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "project_twin_manifest_sha256": self.project_twin_manifest_sha256,
            "evaluator_contract_sha256": self.evaluator_contract_sha256,
            "task_set_sha256": self.task_set_sha256,
            "budget_contract_sha256": self.budget_contract_sha256,
            "seed_policy_sha256": self.seed_policy_sha256,
            "metric_id": self.metric_id,
            "minimum_margin": self.minimum_margin,
            "results": [item.to_dict() for item in self.results],
            "blockers": list(self.blockers),
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict()) + b"\n"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FourPlaneAblationReport":
        expected = {
            "schema", "project_twin_manifest_sha256", "evaluator_contract_sha256",
            "task_set_sha256", "budget_contract_sha256", "seed_policy_sha256",
            "metric_id", "minimum_margin", "results", "blockers",
        }
        if set(payload) != expected:
            raise FourPlaneAblationError("ablation report fields are not canonical")
        if not isinstance(payload["results"], list) or not isinstance(payload["blockers"], list):
            raise FourPlaneAblationError("results and blockers must be arrays")
        report = cls(
            schema=payload["schema"],
            project_twin_manifest_sha256=payload["project_twin_manifest_sha256"],
            evaluator_contract_sha256=payload["evaluator_contract_sha256"],
            task_set_sha256=payload["task_set_sha256"],
            budget_contract_sha256=payload["budget_contract_sha256"],
            seed_policy_sha256=payload["seed_policy_sha256"],
            metric_id=payload["metric_id"],
            minimum_margin=payload["minimum_margin"],
            results=tuple(AblationResult.from_dict(item) for item in payload["results"]),
        )
        if tuple(payload["blockers"]) != report.blockers:
            raise FourPlaneAblationError("blockers must be mechanically derived")
        return report

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "FourPlaneAblationReport":
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FourPlaneAblationError("ablation report must be valid UTF-8 JSON") from exc
        if not isinstance(decoded, Mapping):
            raise FourPlaneAblationError("ablation report root must be an object")
        report = cls.from_dict(decoded)
        if payload != report.to_json_bytes():
            raise FourPlaneAblationError("ablation report bytes must be canonical JSON plus one newline")
        return report


__all__ = ["AblationResult", "FourPlaneAblationError", "FourPlaneAblationReport"]
