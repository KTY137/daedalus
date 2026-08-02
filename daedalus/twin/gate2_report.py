"""Deterministic, fail-closed Gate-2 closure reporting."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from typing import Any, Iterable, Mapping

from daedalus.schemas import _revision, _sha256
from daedalus.twin.corpus_genesis import CorpusGenesisBinding
from daedalus.twin.motifs import MotifProvenance

_REQUIRED_WORKFLOWS = (
    "Gate 2 Corpus Pilot",
    "Gate 2 Project Twin",
    "Iron Plan",
)
_CONCLUSIONS = frozenset({"success", "failure", "cancelled", "skipped", "timed_out"})
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class Gate2ReportError(ValueError):
    """Raised when Gate-2 evidence is malformed or noncanonical."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Gate2ReportError(f"{field} must be a non-empty string")
    return value


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _validated_sorted_sha(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if not values:
        raise Gate2ReportError(f"{field} must not be empty")
    normalized = tuple(_sha256(value, field) for value in values)
    if normalized != tuple(sorted(set(normalized))):
        raise Gate2ReportError(f"{field} must be unique and sorted")
    return normalized


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
        object.__setattr__(self, "attestation_sha256", _sha256(self.attestation_sha256, "attestation_sha256"))

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkflowEvidence":
        if set(payload) != {"workflow_name", "run_id", "head_sha", "conclusion", "attestation_sha256"}:
            raise Gate2ReportError("workflow evidence fields are not canonical")
        return cls(**payload)


@dataclasses.dataclass(frozen=True, slots=True)
class Gate2Report:
    schema: str
    head_sha: str
    iron_plan_sha256: str
    workflow_evidence: tuple[WorkflowEvidence, ...]
    binding_sha256s: tuple[str, ...]
    motif_provenance_sha256s: tuple[str, ...]
    blockers: tuple[str, ...]
    external_constraints: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema != "daedalus-gate2-report/1":
            raise Gate2ReportError("unsupported Gate-2 report schema")
        object.__setattr__(self, "head_sha", _revision(self.head_sha, "head_sha"))
        object.__setattr__(self, "iron_plan_sha256", _sha256(self.iron_plan_sha256, "iron_plan_sha256"))
        names = tuple(item.workflow_name for item in self.workflow_evidence)
        if names != tuple(sorted(set(names))):
            raise Gate2ReportError("workflow_evidence must be unique and sorted")
        if not set(names).issubset(_REQUIRED_WORKFLOWS):
            raise Gate2ReportError("workflow_evidence contains a non-required workflow")
        _validated_sorted_sha(self.binding_sha256s, "binding_sha256s")
        _validated_sorted_sha(self.motif_provenance_sha256s, "motif_provenance_sha256s")
        for field, values in (("blockers", self.blockers), ("external_constraints", self.external_constraints)):
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
            "motif_provenance_sha256s": list(self.motif_provenance_sha256s),
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
            "motif_provenance_sha256s",
            "blockers",
            "external_constraints",
            "closed",
        }
        if set(payload) != expected:
            raise Gate2ReportError("Gate-2 report fields are not canonical")
        collection_fields = (
            "workflow_evidence",
            "binding_sha256s",
            "motif_provenance_sha256s",
            "blockers",
            "external_constraints",
        )
        if not all(isinstance(payload[field], list) for field in collection_fields):
            raise Gate2ReportError("report collection fields must be arrays")
        report = cls(
            schema=payload["schema"],
            head_sha=payload["head_sha"],
            iron_plan_sha256=payload["iron_plan_sha256"],
            workflow_evidence=tuple(WorkflowEvidence.from_dict(item) for item in payload["workflow_evidence"]),
            binding_sha256s=tuple(payload["binding_sha256s"]),
            motif_provenance_sha256s=tuple(payload["motif_provenance_sha256s"]),
            blockers=tuple(payload["blockers"]),
            external_constraints=tuple(payload["external_constraints"]),
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
    motifs: Iterable[MotifProvenance],
    external_constraints: Iterable[str] = (),
) -> Gate2Report:
    """Project exact-head evidence into a deterministic open/closed decision."""
    normalized_head = _revision(head_sha, "head_sha")
    checks = tuple(sorted(workflow_evidence, key=lambda item: item.workflow_name))
    names = tuple(item.workflow_name for item in checks)
    if names != tuple(sorted(set(names))):
        raise Gate2ReportError("workflow evidence names must be unique")
    binding_items = tuple(bindings)
    motif_items = tuple(motifs)
    if not binding_items:
        raise Gate2ReportError("at least one corpus Genesis binding is required")
    if not motif_items:
        raise Gate2ReportError("at least one motif provenance artifact is required")

    blockers: set[str] = set()
    present = set(names)
    for required in _REQUIRED_WORKFLOWS:
        if required not in present:
            blockers.add(f"workflow-{_slug(required)}-missing")
    for check in checks:
        if check.head_sha != normalized_head:
            blockers.add(f"workflow-{_slug(check.workflow_name)}-stale-head")
        if check.conclusion != "success":
            blockers.add(f"workflow-{_slug(check.workflow_name)}-{check.conclusion}")

    repository_ids: set[str] = set()
    for binding in binding_items:
        if not isinstance(binding, CorpusGenesisBinding):
            raise Gate2ReportError("bindings must contain CorpusGenesisBinding values")
        if binding.repository_id in repository_ids:
            raise Gate2ReportError("bindings must use unique repository_id values")
        repository_ids.add(binding.repository_id)
        blockers.update(f"binding-{binding.repository_id}-{item}" for item in binding.blockers)

    motif_ids: set[str] = set()
    for motif in motif_items:
        if not isinstance(motif, MotifProvenance):
            raise Gate2ReportError("motifs must contain MotifProvenance values")
        if motif.motif_id in motif_ids:
            raise Gate2ReportError("motifs must use unique motif_id values")
        motif_ids.add(motif.motif_id)
        blockers.update(f"motif-{motif.motif_id}-{item}" for item in motif.blockers)

    return Gate2Report(
        schema="daedalus-gate2-report/1",
        head_sha=normalized_head,
        iron_plan_sha256=iron_plan_sha256,
        workflow_evidence=checks,
        binding_sha256s=tuple(sorted(binding.digest for binding in binding_items)),
        motif_provenance_sha256s=tuple(sorted(motif.digest for motif in motif_items)),
        blockers=tuple(sorted(blockers)),
        external_constraints=tuple(sorted(set(external_constraints))),
    )


def assert_monotonic_gate2_report(previous: Gate2Report, current: Gate2Report) -> None:
    if previous.head_sha == current.head_sha and previous.digest != current.digest:
        raise Gate2ReportError("one exact head must not have competing Gate-2 reports")
    if set(previous.binding_sha256s) - set(current.binding_sha256s):
        raise Gate2ReportError("current report drops previously retained binding evidence")
    if set(previous.motif_provenance_sha256s) - set(current.motif_provenance_sha256s):
        raise Gate2ReportError("current report drops previously retained motif evidence")
    if previous.closed and not current.closed:
        raise Gate2ReportError("a closed Gate-2 report cannot regress to open")


__all__ = ["Gate2Report", "Gate2ReportError", "WorkflowEvidence", "assert_monotonic_gate2_report", "build_gate2_report"]
