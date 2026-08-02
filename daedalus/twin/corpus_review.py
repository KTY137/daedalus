"""Authenticated, content-addressed corpus review records for Gate 2."""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from typing import Any, Mapping

from daedalus.kernel.approvals import ApprovalExpectation, VerifiedOwnerApproval, verify_owner_approval
from daedalus.kernel.contracts import OwnerApproval
from daedalus.schemas import _revision, _sha256
from daedalus.twin.capabilities import CapabilityMatrix
from daedalus.twin.corpus import CorpusManifest, CorpusManifestError, CorpusRepository

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DECISIONS = frozenset({"reviewed", "rejected"})
_OPERATION = "review-corpus-repository"


class CorpusReviewError(ValueError):
    """Raised when corpus review evidence is stale, incomplete, or unauthenticated."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CorpusReviewError(f"{field} must be a non-empty string")
    return value


def _parse_utc(value: str, field: str) -> dt.datetime:
    if not isinstance(value, str) or not _TIME_RE.fullmatch(value):
        raise CorpusReviewError(f"{field} must be canonical UTC seconds")
    return dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=dt.timezone.utc)


def _sorted_text(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    if not values:
        raise CorpusReviewError(f"{field} must not be empty")
    for value in values:
        _text(value, field)
    if values != tuple(sorted(set(values))):
        raise CorpusReviewError(f"{field} must be unique and sorted")
    return values


@dataclasses.dataclass(frozen=True, slots=True)
class CorpusReviewRecord:
    repository_id: str
    repository_url: str
    source_revision: str
    include_prefixes: tuple[str, ...]
    language_ids: tuple[str, ...]
    license_spdx: str
    license_path: str
    license_file_sha256: str
    source_inventory_sha256: str
    capability_matrix_sha256: str
    reviewer_id: str
    reviewed_at: str
    decision: str
    rationale_sha256: str

    def __post_init__(self) -> None:
        if not _ID_RE.fullmatch(_text(self.repository_id, "repository_id")):
            raise CorpusReviewError("repository_id must use a canonical identifier")
        _text(self.repository_url, "repository_url")
        object.__setattr__(self, "source_revision", _revision(self.source_revision, "source_revision"))
        _sorted_text(self.include_prefixes, "include_prefixes")
        _sorted_text(self.language_ids, "language_ids")
        _text(self.license_spdx, "license_spdx")
        _text(self.license_path, "license_path")
        for field in (
            "license_file_sha256",
            "source_inventory_sha256",
            "capability_matrix_sha256",
            "rationale_sha256",
        ):
            object.__setattr__(self, field, _sha256(getattr(self, field), field))
        reviewer = _text(self.reviewer_id, "reviewer_id")
        if not _ID_RE.fullmatch(reviewer):
            raise CorpusReviewError("reviewer_id must use a canonical identifier")
        _parse_utc(self.reviewed_at, "reviewed_at")
        if self.decision not in _DECISIONS:
            raise CorpusReviewError("unsupported corpus review decision")

    @property
    def digest(self) -> str:
        return hashlib.sha256(self.to_json_bytes()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-corpus-review-record/1",
            "repository_id": self.repository_id,
            "repository_url": self.repository_url,
            "source_revision": self.source_revision,
            "include_prefixes": list(self.include_prefixes),
            "language_ids": list(self.language_ids),
            "license_spdx": self.license_spdx,
            "license_path": self.license_path,
            "license_file_sha256": self.license_file_sha256,
            "source_inventory_sha256": self.source_inventory_sha256,
            "capability_matrix_sha256": self.capability_matrix_sha256,
            "reviewer_id": self.reviewer_id,
            "reviewed_at": self.reviewed_at,
            "decision": self.decision,
            "rationale_sha256": self.rationale_sha256,
        }

    def to_json_bytes(self) -> bytes:
        return _canonical_json(self.to_dict()) + b"\n"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CorpusReviewRecord":
        expected = {
            "schema", "repository_id", "repository_url", "source_revision",
            "include_prefixes", "language_ids", "license_spdx", "license_path",
            "license_file_sha256", "source_inventory_sha256",
            "capability_matrix_sha256", "reviewer_id", "reviewed_at",
            "decision", "rationale_sha256",
        }
        if set(payload) != expected or payload.get("schema") != "daedalus-corpus-review-record/1":
            raise CorpusReviewError("corpus review fields or schema are not canonical")
        prefixes = payload["include_prefixes"]
        languages = payload["language_ids"]
        if not isinstance(prefixes, list) or not isinstance(languages, list):
            raise CorpusReviewError("include_prefixes and language_ids must be arrays")
        values = dict(payload)
        values.pop("schema")
        values["include_prefixes"] = tuple(prefixes)
        values["language_ids"] = tuple(languages)
        return cls(**values)

    @classmethod
    def from_json_bytes(cls, payload: bytes) -> "CorpusReviewRecord":
        try:
            decoded = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CorpusReviewError("corpus review must be valid UTF-8 JSON") from exc
        if not isinstance(decoded, Mapping):
            raise CorpusReviewError("corpus review root must be an object")
        record = cls.from_dict(decoded)
        if payload != record.to_json_bytes():
            raise CorpusReviewError("corpus review bytes must be canonical JSON plus one newline")
        return record


def owner_approval_expectation(
    *,
    manifest: CorpusManifest,
    record: CorpusReviewRecord,
) -> ApprovalExpectation:
    return ApprovalExpectation(
        operation=_OPERATION,
        nomination_receipt_sha256=record.source_inventory_sha256,
        candidate_artifact_sha256=record.digest,
        evidence_packet_sha256=record.license_file_sha256,
        base_revision=record.source_revision,
        target_ref=f"corpus/{manifest.corpus_id}/{record.repository_id}",
        current_target_revision=record.source_revision,
    )


def verify_corpus_review_approval(
    *,
    manifest: CorpusManifest,
    record: CorpusReviewRecord,
    owner_approval: OwnerApproval,
    keyring: Mapping[tuple[str, str], bytes | str],
    now: str,
) -> VerifiedOwnerApproval:
    instant = _parse_utc(now, "now")
    verified = verify_owner_approval(
        owner_approval,
        keyring=keyring,
        expectation=owner_approval_expectation(manifest=manifest, record=record),
        now=instant,
    )
    mismatches: list[str] = []
    if verified.owner_id != record.reviewer_id:
        mismatches.append("reviewer_id")
    if verified.issued_at != record.reviewed_at:
        mismatches.append("reviewed_at")
    if mismatches:
        raise CorpusReviewError("owner approval does not bind corpus review: " + ", ".join(mismatches))
    return verified


def apply_reviewed_record(
    *,
    manifest: CorpusManifest,
    capability_matrix: CapabilityMatrix,
    record: CorpusReviewRecord,
    owner_approval: OwnerApproval,
    keyring: Mapping[tuple[str, str], bytes | str],
    now: str,
) -> CorpusManifest:
    """Upgrade exactly one declared repository after authenticated exact review."""
    if record.decision != "reviewed":
        raise CorpusReviewError("only a reviewed decision may upgrade a corpus manifest")
    matches = tuple(item for item in manifest.repositories if item.repository_id == record.repository_id)
    if len(matches) != 1:
        raise CorpusReviewError("record must identify exactly one manifest repository")
    repository = matches[0]
    if repository.review_state != "declared" or repository.review_evidence is not None:
        raise CorpusReviewError("only a declared repository may be upgraded")
    expected = {
        "repository_url": repository.repository_url,
        "source_revision": repository.source_revision,
        "include_prefixes": repository.include_prefixes,
        "language_ids": repository.language_ids,
        "license_spdx": repository.license_spdx,
        "license_path": repository.license_path,
    }
    for field, expected_value in expected.items():
        if getattr(record, field) != expected_value:
            raise CorpusReviewError(f"corpus review does not match repository {field}")
    if record.capability_matrix_sha256 != capability_matrix.digest:
        raise CorpusReviewError("corpus review does not bind the exact capability matrix")
    if capability_matrix.corpus_manifest_digest != f"sha256:{manifest.digest}":
        raise CorpusReviewError("capability matrix does not bind the source corpus manifest")
    matrix_languages = {profile.language_id for profile in capability_matrix.profiles}
    if set(repository.language_ids) - matrix_languages:
        raise CorpusReviewError("capability matrix does not cover reviewed repository languages")

    verified = verify_corpus_review_approval(
        manifest=manifest,
        record=record,
        owner_approval=owner_approval,
        keyring=keyring,
        now=now,
    )
    evidence_identity = hashlib.sha256(
        _canonical_json({
            "schema": "daedalus-reviewed-corpus-evidence/1",
            "record_sha256": record.digest,
            "owner_approval_sha256": verified.approval_sha256,
        })
    ).hexdigest()
    replacement = CorpusRepository(
        repository_id=repository.repository_id,
        repository_url=repository.repository_url,
        source_revision=repository.source_revision,
        include_prefixes=repository.include_prefixes,
        language_ids=repository.language_ids,
        license_spdx=repository.license_spdx,
        license_path=repository.license_path,
        review_state="reviewed",
        review_evidence=f"sha256:{evidence_identity}",
    )
    repositories = tuple(replacement if item.repository_id == replacement.repository_id else item for item in manifest.repositories)
    try:
        return CorpusManifest(schema=manifest.schema, corpus_id=manifest.corpus_id, repositories=repositories)
    except CorpusManifestError as exc:
        raise CorpusReviewError("reviewed corpus manifest is invalid") from exc


__all__ = [
    "CorpusReviewError",
    "CorpusReviewRecord",
    "apply_reviewed_record",
    "owner_approval_expectation",
    "verify_corpus_review_approval",
]
