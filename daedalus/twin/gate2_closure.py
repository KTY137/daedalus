"""One-use, exact-head Gate-2 closure approval contracts.

Approval is not evidence and cannot turn an open report into a closed one.  It
binds an already closed deterministic Gate2Report to the exact head, report and
supporting authority digests, required workflow run IDs, expiry and nonce.  The
ledger consumes the approval with exclusive creation and durable directory
synchronization so replay fails before any gate-state mutation.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from daedalus.schemas import _revision, _sha256
from daedalus.twin.gate2_report import Gate2Report

_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REQUIRED_WORKFLOWS = ("Gate 2 Corpus Pilot", "Gate 2 Project Twin", "Iron Plan")


class Gate2ClosureError(ValueError):
    """Raised when closure approval is stale, replayed, or insufficiently bound."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")


def _parse_utc(value: str, field: str) -> dt.datetime:
    if not isinstance(value, str) or not _TIME_RE.fullmatch(value):
        raise Gate2ClosureError(f"{field} must be canonical UTC seconds")
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


@dataclasses.dataclass(frozen=True, slots=True)
class Gate2ClosureApproval:
    head_sha: str
    iron_plan_sha256: str
    report_sha256: str
    evidence_packet_sha256: str
    corpus_manifest_sha256: str
    capability_matrix_sha256: str
    motif_provenance_sha256s: tuple[str, ...]
    workflow_run_ids: tuple[tuple[str, int], ...]
    target_state: str
    issued_at: str
    expires_at: str
    nonce: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "head_sha", _revision(self.head_sha, "head_sha"))
        for field in (
            "iron_plan_sha256",
            "report_sha256",
            "evidence_packet_sha256",
            "corpus_manifest_sha256",
            "capability_matrix_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        motifs = tuple(_sha256(value, "motif_provenance_sha256") for value in self.motif_provenance_sha256s)
        if not motifs or motifs != tuple(sorted(set(motifs))):
            raise Gate2ClosureError("motif_provenance_sha256s must be non-empty, unique and sorted")
        names = tuple(name for name, _ in self.workflow_run_ids)
        if names != _REQUIRED_WORKFLOWS:
            raise Gate2ClosureError("workflow_run_ids must contain every required workflow in canonical order")
        if any(isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0 for _, run_id in self.workflow_run_ids):
            raise Gate2ClosureError("workflow run IDs must be positive integers")
        if self.target_state != "gate-2-closed":
            raise Gate2ClosureError("target_state must be gate-2-closed")
        issued = _parse_utc(self.issued_at, "issued_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= issued:
            raise Gate2ClosureError("expires_at must be later than issued_at")
        if not isinstance(self.nonce, str) or not _NONCE_RE.fullmatch(self.nonce):
            raise Gate2ClosureError("nonce must be a canonical high-entropy identifier")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json_bytes()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-gate2-closure-approval/1",
            "head_sha": self.head_sha,
            "iron_plan_sha256": self.iron_plan_sha256,
            "report_sha256": self.report_sha256,
            "evidence_packet_sha256": self.evidence_packet_sha256,
            "corpus_manifest_sha256": self.corpus_manifest_sha256,
            "capability_matrix_sha256": self.capability_matrix_sha256,
            "motif_provenance_sha256s": list(self.motif_provenance_sha256s),
            "workflow_run_ids": [
                {"workflow_name": name, "run_id": run_id}
                for name, run_id in self.workflow_run_ids
            ],
            "target_state": self.target_state,
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict()) + b"\n"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "Gate2ClosureApproval":
        expected = {
            "schema", "head_sha", "iron_plan_sha256", "report_sha256",
            "evidence_packet_sha256", "corpus_manifest_sha256",
            "capability_matrix_sha256", "motif_provenance_sha256s",
            "workflow_run_ids", "target_state", "issued_at", "expires_at", "nonce",
        }
        if set(payload) != expected or payload.get("schema") != "daedalus-gate2-closure-approval/1":
            raise Gate2ClosureError("closure approval fields or schema are not canonical")
        motifs = payload["motif_provenance_sha256s"]
        runs = payload["workflow_run_ids"]
        if not isinstance(motifs, list) or not isinstance(runs, list):
            raise Gate2ClosureError("motif and workflow fields must be arrays")
        normalized_runs: list[tuple[str, int]] = []
        for item in runs:
            if not isinstance(item, Mapping) or set(item) != {"workflow_name", "run_id"}:
                raise Gate2ClosureError("workflow run record is not canonical")
            normalized_runs.append((item["workflow_name"], item["run_id"]))
        return cls(
            head_sha=payload["head_sha"],
            iron_plan_sha256=payload["iron_plan_sha256"],
            report_sha256=payload["report_sha256"],
            evidence_packet_sha256=payload["evidence_packet_sha256"],
            corpus_manifest_sha256=payload["corpus_manifest_sha256"],
            capability_matrix_sha256=payload["capability_matrix_sha256"],
            motif_provenance_sha256s=tuple(motifs),
            workflow_run_ids=tuple(normalized_runs),
            target_state=payload["target_state"],
            issued_at=payload["issued_at"],
            expires_at=payload["expires_at"],
            nonce=payload["nonce"],
        )

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "Gate2ClosureApproval":
        try:
            decoded = json.loads(payload.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise Gate2ClosureError("closure approval must be canonical JSON") from exc
        if not isinstance(decoded, Mapping):
            raise Gate2ClosureError("closure approval root must be an object")
        approval = cls.from_dict(decoded)
        if payload != approval.to_json_bytes():
            raise Gate2ClosureError("closure approval bytes must be canonical JSON plus one newline")
        return approval


def verify_gate2_closure_approval(
    *,
    approval: Gate2ClosureApproval,
    report: Gate2Report,
    evidence_packet_sha256: str,
    corpus_manifest_sha256: str,
    capability_matrix_sha256: str,
    now: str,
) -> None:
    """Verify all closure bindings before consumption."""
    if not report.closed:
        raise Gate2ClosureError("an open Gate-2 report cannot be approved for closure")
    expected_runs = tuple((item.workflow_name, item.run_id) for item in report.workflow_evidence)
    mismatches: list[str] = []
    if approval.head_sha != report.head_sha:
        mismatches.append("head_sha")
    if approval.iron_plan_sha256 != report.iron_plan_sha256:
        mismatches.append("iron_plan")
    if approval.report_sha256 != report.digest:
        mismatches.append("report")
    if approval.evidence_packet_sha256 != _sha256(evidence_packet_sha256, "evidence_packet_sha256"):
        mismatches.append("evidence_packet")
    if approval.corpus_manifest_sha256 != _sha256(corpus_manifest_sha256, "corpus_manifest_sha256"):
        mismatches.append("corpus_manifest")
    if approval.capability_matrix_sha256 != _sha256(capability_matrix_sha256, "capability_matrix_sha256"):
        mismatches.append("capability_matrix")
    if approval.motif_provenance_sha256s != report.motif_provenance_sha256s:
        mismatches.append("motif_provenance")
    if approval.workflow_run_ids != expected_runs:
        mismatches.append("workflow_runs")
    current = _parse_utc(now, "now")
    if current < _parse_utc(approval.issued_at, "issued_at"):
        mismatches.append("not_yet_valid")
    if current >= _parse_utc(approval.expires_at, "expires_at"):
        mismatches.append("expired")
    if mismatches:
        raise Gate2ClosureError("closure approval mismatch: " + ", ".join(sorted(mismatches)))


class Gate2ClosureLedger:
    """Durably consume each approval digest and nonce exactly once."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def consume(
        self,
        *,
        approval: Gate2ClosureApproval,
        report: Gate2Report,
        evidence_packet_sha256: str,
        corpus_manifest_sha256: str,
        capability_matrix_sha256: str,
        now: str,
    ) -> Path:
        verify_gate2_closure_approval(
            approval=approval,
            report=report,
            evidence_packet_sha256=evidence_packet_sha256,
            corpus_manifest_sha256=corpus_manifest_sha256,
            capability_matrix_sha256=capability_matrix_sha256,
            now=now,
        )
        nonce_digest = hashlib.sha256(approval.nonce.encode("ascii")).hexdigest()
        path = self.root / f"{nonce_digest}.json"
        payload = _canonical_json({
            "schema": "daedalus-gate2-closure-consumption/1",
            "approval_sha256": approval.digest,
            "nonce_sha256": nonce_digest,
            "head_sha": report.head_sha,
            "report_sha256": report.digest,
            "consumed_at": now,
        }) + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        try:
            fd = os.open(path, flags, 0o600)
        except FileExistsError as exc:
            raise Gate2ClosureError("closure approval nonce has already been consumed") from exc
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(fd, payload[offset:])
                if written <= 0:
                    raise Gate2ClosureError("closure ledger write made no progress")
                offset += written
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            path.unlink(missing_ok=True)
            raise
        else:
            os.close(fd)
        directory_fd = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return path


__all__ = [
    "Gate2ClosureApproval", "Gate2ClosureError", "Gate2ClosureLedger",
    "verify_gate2_closure_approval",
]
