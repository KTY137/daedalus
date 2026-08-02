"""Deterministic, fail-closed Gate-2 closure reporting.

The report is a projection over already existing authorities.  It never upgrades
corpus review, extractor capability, workflow conclusions, or Project Twin
identity.  Closure is derived mechanically from exact-head workflow evidence
and corpus-governed Genesis bindings.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from daedalus.schemas import _revision, _sha256
from daedalus.twin.corpus_genesis import CorpusGenesisBinding

_REQUIRED_WORKFLOWS = (
    "Gate 2 Corpus Pilot",
    "Gate 2 Project Twin",
    "Iron Plan",
)
_CONCLUSIONS = frozenset({"success", "failure", "cancelled", "skipped", "timed_out"})
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class Gate2ReportError(ValueError):
    """Raised when Gate-2 evidence is incomplete, stale, or noncanonical."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Gate2ReportError(f"{field} must be a non-empty string")
    return value


@dataclasses.dataclass(frozen=True, slots=True)
class WorkflowEvidence:
    workflow_name: str
    run_id: int
    head_sha: str
    conclusion: str
    attestation_sha256: str

    def __post_init__(self) -> None:
        _text(self.workflow_name, "workflow_name")
        if self.workflow_name not in _REQUIRED_WORKFLOWS:
            raise Gate2ReportError("workflow_name is not a required Gate-2 workflow")
        if isinstance(self.run_id, bool) or not isinstance(self.run_id, int) or self.run_id <= 0:
            raise Gate2ReportError("run_id must be a positive integer")
        object.__setattr__(self, "head_sha", _revision(self.head_sha, "head_sha"))
        if self.conclusion not in _CONCLUSIONS:
            raise Gate2ReportError("unsupported workflow conclusion")
        object.__setattr__(
            self,
            "attestation_sha256",
            _sha256(self.attestation_sha256, "attestation_sha256"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_name": self.workflow_name,
            "run_id": self.run_id,
            "head_sha": self.head_sha,
            "conclusion": self.conclusion,
            "attestation_sha256": self.attestation_sha256,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowEvidence":
        if set(payload) != {
            "workflow_name",
            "run_id",
            "head_sha",
            "conclusion",
            "attestation_sha256",
        }:
            raise Gate2ReportError("workflow evidence fields are not canonical")
        return cls(**payload)


@dataclasses.dataclass(frozen=True, slots=True)
class Gate2Report:
    schema: str
    head_sha: str
    iron_plan_sha256: str
    workflow_evidence: tuple[WorkflowEvidence, ...]
    binding_sha256s: tuple[str, ...]
    blockers: tuple[str, ...]
    external_constraints: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema != "daedalus-gate2-report/1":
            raise Gate2ReportError("unsupported Gate-2 report schema")
        object.__setattr__(self, "head_sha", _revision(self.head_sha, "head_sha"))
        object.__setattr__(
            self, "iron_plan_sha256", _sha256(self.iron_plan_sha256, "iron_plan_sha256")
        )
        names = tuple(item.workflow_name for item in self.workflow_evidence)
        if names != _REQUIRED_WORKFLOWS:
            raise Gate2ReportError(
                "workflow_evidence must contain every required workflow once in canonical order"
            )
        if any(item.head_sha != self.head_sha for item in self.workflow_evidence):
            raise Gate2ReportError("workflow evidence must bind the exact report head")
        if not self.binding_sha256s:
            raise Gate2ReportError("binding_sha256s must not be empty")
        normalized_bindings = tuple(
            _sha256(value, "binding_sha256") for value in self.binding_sha256s
        )
        if normalized_bindings != tuple(sorted(set(normalized_bindings))):
            raise Gate2ReportError("binding_sha256s must be unique and sorted")
        for field, values in (
            ("blockers", self.blockers),
            ("external_constraints", self.external_constraints),
        ):
            if values != tuple(sorted(set(values))):
                raise Gate2ReportError(f"{field} must be unique and sorted")
            for value in values:
                if not _ID_RE.fullmatch(_text(value, field)):
                    raise Gate2ReportError(f"{field} entries must use canonical identifiers")

    @property
    def closed(self) -> bool:
        return not self.blockers

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json_bytes()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "head_sha": self.head_sha,
            "iron_plan_sha256": self.iron_plan_sha256,
            "workflow_evidence": [item.to_dict() for item in self.workflow_evidence],
            "binding_sha256s": list(self.binding_sha256s),
            "blockers": list(self.blockers),
            "external_constraints": list(self.external_constraints),
            "closed": self.closed,
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict()) + b"\n"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Gate2Report":
        expected = {
            "schema",
            "head_sha",
            "iron_plan_sha256",
            "workflow_evidence",
            "binding_sha256s",
            "blockers",
            "external_constraints",
            "closed",
        }
        if set(payload) != expected:
            raise Gate2ReportError("Gate-2 report fields are not canonical")
        workflows = payload["workflow_evidence"]
        bindings = payload["binding_sha256s"]
        blockers = payload["blockers"]
        constraints = payload["external_constraints"]
        if not all(isinstance(value, list) for value in (workflows, bindings, blockers, constraints)):
            raise Gate2ReportError("report collection fields must be arrays")
        report = cls(
            schema=payload["schema"],
            head_sha=payload["head_sha"],
            iron_plan_sha256=payload["iron_plan_sha256"],
            workflow_evidence=tuple(WorkflowEvidence.from_dict(item) for item in workflows),
            binding_sha256s=tuple(bindings),
            blockers=tuple(blockers),
            external_constraints=tuple(constraints),
        )
        if payload["closed"] is not report.closed:
            raise Gate2ReportError("closed must be derived from blockers")
        return report

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "Gate2Report":
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Gate2ReportError("Gate-2 report must be valid UTF-8 JSON") from exc
        if not isinstance(decoded, Mapping):
            raise Gate2ReportError("Gate-2 report root must be an object")
        report = cls.from_dict(decoded)
        if payload != report.to_json_bytes():
            raise Gate2ReportError("Gate-2 report bytes must be canonical JSON plus one newline")
        return report


def build_gate2_report(
    *,
    head_sha: str,
    iron_plan_sha256: str,
    workflow_evidence: Iterable[WorkflowEvidence],
    bindings: Iterable[CorpusGenesisBinding],
    external_constraints: Iterable[str] = (),
) -> Gate2Report:
    """Project exact-head evidence into a deterministic Gate-2 decision."""
    normalized_head = _revision(head_sha, "head_sha")
    checks = tuple(sorted(workflow_evidence, key=lambda item: item.workflow_name))
    binding_items = tuple(bindings)
    if not binding_items:
        raise Gate2ReportError("at least one corpus Genesis binding is required")

    blockers: set[str] = set()
    for check in checks:
        if check.head_sha != normalized_head:
            blockers.add(f"workflow-{_slug(check.workflow_name)}-stale-head")
        if check.conclusion != "success":
            blockers.add(f"workflow-{_slug(check.workflow_name)}-{check.conclusion}")
    present_names = {item.workflow_name for item in checks}
    for required in _REQUIRED_WORKFLOWS:
        if required not in present_names:
            blockers.add(f"workflow-{_slug(required)}-missing")

    repository_ids: set[str] = set()
    for binding in binding_items:
        if not isinstance(binding, CorpusGenesisBinding):
            raise Gate2ReportError("bindings must contain CorpusGenesisBinding values")
        if binding.repository_id in repository_ids:
            raise Gate2ReportError("bindings must use unique repository_id values")
        repository_ids.add(binding.repository_id)
        for blocker in binding.blockers:
            blockers.add(f"binding-{binding.repository_id}-{blocker}")

    return Gate2Report(
        schema="daedalus-gate2-report/1",
        head_sha=normalized_head,
        iron_plan_sha256=iron_plan_sha256,
        workflow_evidence=checks,
        binding_sha256s=tuple(sorted(binding.digest for binding in binding_items)),
        blockers=tuple(sorted(blockers)),
        external_constraints=tuple(sorted(set(external_constraints))),
    )


def assert_monotonic_gate2_report(previous: Gate2Report, current: Gate2Report) -> None:
    """Refuse silent loss of evidence or introduction of unreported blockers."""
    if previous.head_sha == current.head_sha and previous.digest != current.digest:
        raise Gate2ReportError("one exact head must not have competing Gate-2 reports")
    missing_bindings = set(previous.binding_sha256s) - set(current.binding_sha256s)
    if missing_bindings:
        raise Gate2ReportError("current report drops previously retained binding evidence")
    if previous.closed and not current.closed:
        raise Gate2ReportError("a closed Gate-2 report cannot regress to open")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


__all__ = [
    "Gate2Report",
    "Gate2ReportError",
    "WorkflowEvidence",
    "assert_monotonic_gate2_report",
    "build_gate2_report",
]
