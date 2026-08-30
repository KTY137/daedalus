# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Authenticated external trust bundle for exact-head Gate-0 evidence.

The evidence index is canonical but not authenticated by construction.  This
module lets a separately controlled collector sign the exact trust material it
observed, including repository workflow bytes, without turning the repository
candidate into its own trust authority.
"""
from __future__ import annotations

import dataclasses
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar, Mapping, Sequence

from daedalus.schemas import (
    CanonicalContract,
    ContractProvenance,
    _identifier,
    _record_payload,
    _repo_path,
    _revision,
    _sha256,
    _sorted_strings,
    _utc_timestamp,
)
from daedalus.spine.envelope import canonical_sha

from .evidence import GateEvidenceIndex
from .evidence_verifier import (
    assert_strict_exact_head,
    evidence_requirements_sha256,
)

_TRUST_BUNDLE_SCHEMA = "daedalus-gate-evidence-trust-bundle/1"
_TRUST_BUNDLE_ORIGIN = "gates.evidence-trust-bundle"
_MAX_BUNDLE_TTL = timedelta(hours=24)


class EvidenceTrustBundleError(RuntimeError):
    """Base error for authenticated release-evidence trust material."""


class EvidenceTrustBundleSignatureError(EvidenceTrustBundleError):
    """The collector signature cannot be authenticated."""


class EvidenceTrustBundleBindingError(EvidenceTrustBundleError):
    """The bundle does not match the index or exact repository state."""


@dataclass(frozen=True)
class WorkflowDefinitionAnchor:
    """Bind one workflow run evidence record to exact repository YAML bytes."""

    workflow_id: str
    repository_path: str
    workflow_evidence_sha256: str
    definition_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "workflow_id",
            _identifier(self.workflow_id, "workflow_id"),
        )
        path = _repo_path(self.repository_path, "repository_path")
        if not path.startswith(".github/workflows/"):
            raise ValueError("workflow definition must be inside .github/workflows")
        if Path(path).suffix not in {".yml", ".yaml"}:
            raise ValueError("workflow definition must be YAML")
        object.__setattr__(self, "repository_path", path)
        object.__setattr__(
            self,
            "workflow_evidence_sha256",
            _sha256(
                self.workflow_evidence_sha256,
                "workflow_evidence_sha256",
            ),
        )
        object.__setattr__(
            self,
            "definition_sha256",
            _sha256(self.definition_sha256, "definition_sha256"),
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "workflow_id": self.workflow_id,
            "repository_path": self.repository_path,
            "workflow_evidence_sha256": self.workflow_evidence_sha256,
            "definition_sha256": self.definition_sha256,
        }

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "WorkflowDefinitionAnchor":
        return cls(
            **_record_payload(
                cls,
                payload,
                "workflow definition anchor",
            )
        )

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class EvidenceTrustBundle(CanonicalContract):
    """One externally authenticated trust projection for one evidence index."""

    CONTRACT_TYPE: ClassVar[str] = _TRUST_BUNDLE_SCHEMA

    bundle_id: str
    collector_id: str
    collector_key_id: str
    index_sha256: str
    source_revision: str
    source_tree_revision: str
    requirements_sha256: str
    iron_plan_sha256: str
    registry_sha256: str
    workflow_anchors: tuple[WorkflowDefinitionAnchor, ...]
    artifact_evidence_sha256s: tuple[str, ...]
    runtime_envelope_sha256s: tuple[str, ...]
    fault_matrix_sha256s: tuple[str, ...]
    review_evidence_sha256s: tuple[str, ...]
    owner_verifier_sha256s: tuple[str, ...]
    issued_at: str
    expires_at: str
    signature_sha256: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "bundle_id",
            _identifier(self.bundle_id, "bundle_id"),
        )
        object.__setattr__(
            self,
            "collector_id",
            _identifier(self.collector_id, "collector_id"),
        )
        object.__setattr__(
            self,
            "collector_key_id",
            _identifier(self.collector_key_id, "collector_key_id"),
        )
        for field_name in (
            "index_sha256",
            "requirements_sha256",
            "iron_plan_sha256",
            "registry_sha256",
            "signature_sha256",
        ):
            object.__setattr__(
                self,
                field_name,
                _sha256(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "source_tree_revision",
            _revision(self.source_tree_revision, "source_tree_revision"),
        )

        anchors = tuple(
            sorted(
                self.workflow_anchors,
                key=lambda item: (item.workflow_id, item.repository_path),
            )
        )
        if not anchors:
            raise ValueError("evidence trust bundle must retain workflow anchors")
        workflow_ids = [item.workflow_id for item in anchors]
        workflow_paths = [item.repository_path for item in anchors]
        if len(set(workflow_ids)) != len(workflow_ids):
            raise ValueError("workflow anchors contain duplicate workflow identities")
        if len(set(workflow_paths)) != len(workflow_paths):
            raise ValueError("workflow anchors contain duplicate repository paths")
        object.__setattr__(self, "workflow_anchors", anchors)

        for field_name in (
            "artifact_evidence_sha256s",
            "runtime_envelope_sha256s",
            "fault_matrix_sha256s",
            "review_evidence_sha256s",
            "owner_verifier_sha256s",
        ):
            object.__setattr__(
                self,
                field_name,
                _sorted_strings(
                    getattr(self, field_name),
                    field_name,
                    digests=True,
                ),
            )

        object.__setattr__(
            self,
            "issued_at",
            _utc_timestamp(self.issued_at, "issued_at"),
        )
        object.__setattr__(
            self,
            "expires_at",
            _utc_timestamp(self.expires_at, "expires_at"),
        )
        issued = _parse_utc(self.issued_at, "issued_at")
        expires = _parse_utc(self.expires_at, "expires_at")
        if expires <= issued:
            raise ValueError("trust bundle expires_at must follow issued_at")
        if expires - issued > _MAX_BUNDLE_TTL:
            raise ValueError("trust bundle lifetime must not exceed 24 hours")
        if not isinstance(self.provenance, ContractProvenance):
            raise ValueError("provenance must be ContractProvenance")
        if self.provenance.origin != _TRUST_BUNDLE_ORIGIN:
            raise ValueError("trust bundle provenance origin is invalid")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("trust bundle source revision contradicts provenance")
        if self.provenance.created_at != self.issued_at:
            raise ValueError("trust bundle issued_at contradicts provenance")
        if self.provenance.trace_id != self.bundle_id:
            raise ValueError("trust bundle trace_id must equal bundle_id")
        expected_inputs = _bundle_input_digests(self)
        if tuple(self.provenance.input_digests) != expected_inputs:
            raise ValueError(
                "trust bundle provenance must bind exactly all retained trust inputs"
            )

    @property
    def signing_digest(self) -> str:
        body = self.to_dict()
        body["signature_sha256"] = "0" * 64
        return canonical_sha(body)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvidenceTrustBundle":
        body = cls._contract_payload(payload)
        anchors = body["workflow_anchors"]
        if isinstance(anchors, (str, bytes)) or not isinstance(
            anchors,
            Sequence,
        ):
            raise ValueError("workflow_anchors must be an array")
        body["workflow_anchors"] = tuple(
            WorkflowDefinitionAnchor.from_dict(item) for item in anchors
        )
        for field_name in (
            "artifact_evidence_sha256s",
            "runtime_envelope_sha256s",
            "fault_matrix_sha256s",
            "review_evidence_sha256s",
            "owner_verifier_sha256s",
        ):
            values = body[field_name]
            if isinstance(values, (str, bytes)) or not isinstance(
                values,
                Sequence,
            ):
                raise ValueError(f"{field_name} must be an array")
            body[field_name] = tuple(values)
        provenance = body["provenance"]
        if not isinstance(provenance, Mapping):
            raise ValueError("provenance must be an object")
        body["provenance"] = ContractProvenance.from_dict(provenance)
        return cls(**body)


def _parse_utc(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceTrustBundleBindingError(
            f"{label} is not ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceTrustBundleBindingError(
            f"{label} must include a timezone"
        )
    return parsed.astimezone(timezone.utc)


def _as_utc(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _secret_bytes(secret: bytes | str) -> bytes:
    value = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if len(value) < 32:
        raise ValueError("collector secret must contain at least 32 bytes")
    return value


def _signature(digest: str, secret: bytes | str) -> str:
    return hmac.new(
        _secret_bytes(secret),
        digest.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def _bundle_input_digests(
    bundle: EvidenceTrustBundle,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                bundle.index_sha256,
                bundle.requirements_sha256,
                bundle.iron_plan_sha256,
                bundle.registry_sha256,
                *(item.digest for item in bundle.workflow_anchors),
                *bundle.artifact_evidence_sha256s,
                *bundle.runtime_envelope_sha256s,
                *bundle.fault_matrix_sha256s,
                *bundle.review_evidence_sha256s,
                *bundle.owner_verifier_sha256s,
            }
        )
    )


def _safe_workflow_path(repo_root: Path, repository_path: str) -> Path:
    root = repo_root.resolve(strict=True)
    normalized = _repo_path(repository_path, "repository_path")
    candidate = root
    for part in PurePosixPath(normalized).parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise EvidenceTrustBundleBindingError(
                f"workflow definition path must not contain a symlink: {repository_path}"
            )
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise EvidenceTrustBundleBindingError(
            f"workflow definition is missing: {repository_path}"
        ) from exc
    if root not in resolved.parents:
        raise EvidenceTrustBundleBindingError(
            f"workflow definition escapes repository: {repository_path}"
        )
    if not resolved.is_file():
        raise EvidenceTrustBundleBindingError(
            f"workflow definition is not a file: {repository_path}"
        )
    return resolved


def workflow_definition_sha256(
    repo_root: Path,
    repository_path: str,
) -> str:
    """Hash exact workflow bytes after component-wise containment checks."""

    path = _safe_workflow_path(repo_root, repository_path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence_time_bounds(
    index: GateEvidenceIndex,
) -> tuple[datetime, datetime]:
    retained_times = [
        _parse_utc(index.generated_at, "index.generated_at"),
        *(
            _parse_utc(item.completed_at, f"workflow:{item.workflow_id}.completed_at")
            for item in index.workflows
        ),
        *(
            _parse_utc(item.built_at, f"artifact:{item.artifact_kind}.built_at")
            for item in index.artifacts
        ),
        *(
            _parse_utc(item.observed_at, f"runtime:{item.runtime_id}.observed_at")
            for item in index.runtimes
        ),
        *(
            _parse_utc(item.executed_at, f"fault:{item.matrix_id}.executed_at")
            for item in index.fault_matrices
        ),
        *(
            _parse_utc(item.reviewed_at, f"review:{item.review_id}.reviewed_at")
            for item in index.reviews
        ),
    ]
    if index.owner_decision is not None:
        retained_times.append(
            _parse_utc(
                index.owner_decision.verified_at,
                "owner_decision.verified_at",
            )
        )
    expiries = [
        _parse_utc(index.expires_at, "index.expires_at"),
        *(
            _parse_utc(item.expires_at, f"workflow:{item.workflow_id}.expires_at")
            for item in index.workflows
        ),
        *(
            _parse_utc(item.expires_at, f"runtime:{item.runtime_id}.expires_at")
            for item in index.runtimes
        ),
    ]
    return max(retained_times), min(expiries)


def issue_evidence_trust_bundle(
    index: GateEvidenceIndex,
    *,
    repo_root: Path,
    workflow_paths: Mapping[str, str],
    bundle_id: str,
    collector_id: str,
    collector_key_id: str,
    collector_secret: bytes | str,
    issued_at: datetime,
    expires_at: datetime,
) -> EvidenceTrustBundle:
    """Issue a short-lived bundle from a separately controlled collector."""

    instant = _as_utc(issued_at, "issued_at")
    expiry = _as_utc(expires_at, "expires_at")
    latest_evidence, earliest_expiry = _evidence_time_bounds(index)
    if instant < latest_evidence:
        raise EvidenceTrustBundleBindingError(
            "trust bundle issuance predates retained evidence"
        )
    if expiry > earliest_expiry:
        raise EvidenceTrustBundleBindingError(
            "trust bundle outlives retained evidence"
        )
    workflow_map = {item.workflow_id: item for item in index.workflows}
    if set(workflow_paths) != set(workflow_map):
        raise EvidenceTrustBundleBindingError(
            "workflow path identities must exactly match retained workflow evidence"
        )
    anchors = tuple(
        WorkflowDefinitionAnchor(
            workflow_id=workflow_id,
            repository_path=workflow_paths[workflow_id],
            workflow_evidence_sha256=workflow_map[workflow_id].digest,
            definition_sha256=workflow_definition_sha256(
                repo_root,
                workflow_paths[workflow_id],
            ),
        )
        for workflow_id in sorted(workflow_map)
    )
    owner_verifiers = (
        ()
        if index.owner_decision is None
        else (index.owner_decision.verifier_receipt_sha256,)
    )
    requirements_sha256 = evidence_requirements_sha256(index)
    artifact_evidence_sha256s = tuple(
        item.digest for item in index.artifacts
    )
    runtime_envelope_sha256s = tuple(
        item.envelope_sha256 for item in index.runtimes
    )
    fault_matrix_sha256s = tuple(
        item.matrix_sha256 for item in index.fault_matrices
    )
    review_evidence_sha256s = tuple(
        item.digest for item in index.reviews
    )
    input_digests = tuple(
        sorted(
            {
                index.digest,
                requirements_sha256,
                index.iron_plan_sha256,
                index.registry_sha256,
                *(item.digest for item in anchors),
                *artifact_evidence_sha256s,
                *runtime_envelope_sha256s,
                *fault_matrix_sha256s,
                *review_evidence_sha256s,
                *owner_verifiers,
            }
        )
    )
    placeholder = EvidenceTrustBundle(
        bundle_id=bundle_id,
        collector_id=collector_id,
        collector_key_id=collector_key_id,
        index_sha256=index.digest,
        source_revision=index.source_revision,
        source_tree_revision=index.source_tree_revision,
        requirements_sha256=requirements_sha256,
        iron_plan_sha256=index.iron_plan_sha256,
        registry_sha256=index.registry_sha256,
        workflow_anchors=anchors,
        artifact_evidence_sha256s=artifact_evidence_sha256s,
        runtime_envelope_sha256s=runtime_envelope_sha256s,
        fault_matrix_sha256s=fault_matrix_sha256s,
        review_evidence_sha256s=review_evidence_sha256s,
        owner_verifier_sha256s=owner_verifiers,
        issued_at=instant.isoformat(timespec="microseconds"),
        expires_at=expiry.isoformat(timespec="microseconds"),
        signature_sha256="0" * 64,
        provenance=ContractProvenance(
            origin=_TRUST_BUNDLE_ORIGIN,
            source_revision=index.source_revision,
            created_at=instant.isoformat(timespec="microseconds"),
            input_digests=input_digests,
            trace_id=bundle_id,
        ),
    )
    return dataclasses.replace(
        placeholder,
        signature_sha256=_signature(
            placeholder.signing_digest,
            collector_secret,
        ),
    )


def verify_evidence_trust_bundle(
    bundle: EvidenceTrustBundle,
    index: GateEvidenceIndex,
    *,
    repo_root: Path,
    keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    expected_workflow_paths: Mapping[str, str],
    current_revision: str,
    current_tree_revision: str,
    now: datetime,
) -> None:
    """Authenticate the collector and re-check exact local workflow bytes."""

    secret = keyring.get(
        (bundle.collector_id, bundle.collector_key_id)
    )
    if secret is None:
        raise EvidenceTrustBundleSignatureError(
            "collector key is unknown"
        )
    expected_signature = _signature(bundle.signing_digest, secret)
    if not hmac.compare_digest(
        bundle.signature_sha256,
        expected_signature,
    ):
        raise EvidenceTrustBundleSignatureError(
            "collector signature mismatch"
        )

    instant = _as_utc(now, "now")
    issued = _parse_utc(bundle.issued_at, "issued_at")
    expires = _parse_utc(bundle.expires_at, "expires_at")
    if issued > instant:
        raise EvidenceTrustBundleBindingError(
            "trust bundle is from the future"
        )
    if instant >= expires:
        raise EvidenceTrustBundleBindingError("trust bundle is expired")
    latest_evidence, earliest_expiry = _evidence_time_bounds(index)
    if issued < latest_evidence:
        raise EvidenceTrustBundleBindingError(
            "trust bundle issuance predates retained evidence"
        )
    if expires > earliest_expiry:
        raise EvidenceTrustBundleBindingError(
            "trust bundle outlives retained evidence"
        )

    current = _revision(current_revision, "current_revision")
    current_tree = _revision(
        current_tree_revision,
        "current_tree_revision",
    )
    comparisons = {
        "collector_id": (
            bundle.collector_id,
            _identifier(expected_collector_id, "expected_collector_id"),
        ),
        "index_sha256": (bundle.index_sha256, index.digest),
        "source_revision": (bundle.source_revision, current),
        "index_source_revision": (index.source_revision, current),
        "source_tree_revision": (
            bundle.source_tree_revision,
            current_tree,
        ),
        "index_source_tree_revision": (
            index.source_tree_revision,
            current_tree,
        ),
        "requirements_sha256": (
            bundle.requirements_sha256,
            evidence_requirements_sha256(index),
        ),
        "iron_plan_sha256": (
            bundle.iron_plan_sha256,
            index.iron_plan_sha256,
        ),
        "registry_sha256": (
            bundle.registry_sha256,
            index.registry_sha256,
        ),
    }
    mismatches = sorted(
        name
        for name, (actual, expected) in comparisons.items()
        if actual != expected
    )
    if mismatches:
        raise EvidenceTrustBundleBindingError(
            "trust bundle binding mismatch: " + ", ".join(mismatches)
        )

    expected_workflows = {
        item.workflow_id: item.digest for item in index.workflows
    }
    adopted_paths = {
        _identifier(workflow_id, "expected_workflow_id"): _repo_path(
            repository_path,
            "expected_workflow_path",
        )
        for workflow_id, repository_path in expected_workflow_paths.items()
    }
    if set(adopted_paths) != set(expected_workflows):
        raise EvidenceTrustBundleBindingError(
            "adopted workflow paths do not exactly match retained workflow evidence"
        )
    anchors = {
        item.workflow_id: item for item in bundle.workflow_anchors
    }
    if set(anchors) != set(expected_workflows):
        raise EvidenceTrustBundleBindingError(
            "workflow anchors do not exactly match retained workflow evidence"
        )
    for workflow_id, evidence_sha256 in expected_workflows.items():
        anchor = anchors[workflow_id]
        if anchor.repository_path != adopted_paths[workflow_id]:
            raise EvidenceTrustBundleBindingError(
                f"workflow {workflow_id} repository path mismatch"
            )
        if anchor.workflow_evidence_sha256 != evidence_sha256:
            raise EvidenceTrustBundleBindingError(
                f"workflow {workflow_id} evidence digest mismatch"
            )
        current_definition = workflow_definition_sha256(
            repo_root,
            anchor.repository_path,
        )
        if anchor.definition_sha256 != current_definition:
            raise EvidenceTrustBundleBindingError(
                f"workflow {workflow_id} definition digest mismatch"
            )

    exact_sets = {
        "artifact_evidence_sha256s": (
            bundle.artifact_evidence_sha256s,
            tuple(sorted(item.digest for item in index.artifacts)),
        ),
        "runtime_envelope_sha256s": (
            bundle.runtime_envelope_sha256s,
            tuple(
                sorted(
                    item.envelope_sha256 for item in index.runtimes
                )
            ),
        ),
        "fault_matrix_sha256s": (
            bundle.fault_matrix_sha256s,
            tuple(
                sorted(item.matrix_sha256 for item in index.fault_matrices)
            ),
        ),
        "review_evidence_sha256s": (
            bundle.review_evidence_sha256s,
            tuple(sorted(item.digest for item in index.reviews)),
        ),
        "owner_verifier_sha256s": (
            bundle.owner_verifier_sha256s,
            ()
            if index.owner_decision is None
            else (index.owner_decision.verifier_receipt_sha256,),
        ),
    }
    set_mismatches = sorted(
        name
        for name, (actual, expected) in exact_sets.items()
        if actual != expected
    )
    if set_mismatches:
        raise EvidenceTrustBundleBindingError(
            "trust bundle evidence-set mismatch: "
            + ", ".join(set_mismatches)
        )


def assert_strict_exact_head_with_bundle(
    index: GateEvidenceIndex,
    bundle: EvidenceTrustBundle,
    *,
    repo_root: Path,
    keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    expected_workflow_paths: Mapping[str, str],
    current_revision: str,
    current_tree_revision: str,
    now: datetime,
) -> None:
    """Authenticate the bundle, then invoke the existing strict verifier."""

    verify_evidence_trust_bundle(
        bundle,
        index,
        repo_root=repo_root,
        keyring=keyring,
        expected_collector_id=expected_collector_id,
        expected_workflow_paths=expected_workflow_paths,
        current_revision=current_revision,
        current_tree_revision=current_tree_revision,
        now=now,
    )
    assert_strict_exact_head(
        index,
        current_revision=current_revision,
        current_tree_revision=current_tree_revision,
        now=now,
        trusted_requirements_sha256s=(bundle.requirements_sha256,),
        trusted_iron_plan_sha256s=(bundle.iron_plan_sha256,),
        trusted_registry_sha256s=(bundle.registry_sha256,),
        trusted_workflow_evidence_sha256s=tuple(
            item.workflow_evidence_sha256
            for item in bundle.workflow_anchors
        ),
        trusted_artifact_evidence_sha256s=(
            bundle.artifact_evidence_sha256s
        ),
        trusted_runtime_envelope_sha256s=(
            bundle.runtime_envelope_sha256s
        ),
        trusted_fault_matrix_sha256s=bundle.fault_matrix_sha256s,
        trusted_review_evidence_sha256s=(
            bundle.review_evidence_sha256s
        ),
        trusted_owner_verifier_sha256s=(
            bundle.owner_verifier_sha256s
        ),
    )


def _reject_duplicate_keys(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_evidence_trust_bundle(
    payload: Mapping[str, Any],
) -> EvidenceTrustBundle:
    """Parse one untrusted mapping with strict recursive shape checks."""

    if not isinstance(payload, Mapping):
        raise ValueError("evidence trust bundle must be an object")
    anchors = payload.get("workflow_anchors")
    if isinstance(anchors, (str, bytes)) or not isinstance(
        anchors,
        (list, tuple),
    ):
        raise ValueError("workflow_anchors must be an array")
    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, Mapping):
            raise ValueError(
                f"workflow_anchors[{index}] must be an object"
            )
    for field_name in (
        "artifact_evidence_sha256s",
        "runtime_envelope_sha256s",
        "fault_matrix_sha256s",
        "review_evidence_sha256s",
        "owner_verifier_sha256s",
    ):
        values = payload.get(field_name)
        if isinstance(values, (str, bytes)) or not isinstance(
            values,
            (list, tuple),
        ):
            raise ValueError(f"{field_name} must be an array")
    if not isinstance(payload.get("provenance"), Mapping):
        raise ValueError("provenance must be an object")
    return EvidenceTrustBundle.from_dict(payload)


def load_evidence_trust_bundle(
    path: str | Path,
) -> EvidenceTrustBundle:
    """Load strict UTF-8 JSON and reject duplicate keys at every level."""

    payload = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_keys,
    )
    if not isinstance(payload, Mapping):
        raise ValueError("evidence trust bundle must be an object")
    return parse_evidence_trust_bundle(payload)


__all__ = [
    "EvidenceTrustBundle",
    "EvidenceTrustBundleBindingError",
    "EvidenceTrustBundleError",
    "EvidenceTrustBundleSignatureError",
    "WorkflowDefinitionAnchor",
    "assert_strict_exact_head_with_bundle",
    "issue_evidence_trust_bundle",
    "load_evidence_trust_bundle",
    "parse_evidence_trust_bundle",
    "verify_evidence_trust_bundle",
    "workflow_definition_sha256",
]
