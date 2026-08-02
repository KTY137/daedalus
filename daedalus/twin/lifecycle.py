"""Revision-exact Project Twin lifecycle contracts for Gate 2.

A lifecycle is an append-only chain of already verified Project Twin manifests.
Each transition binds the previous head, the next manifest, and an explicit drift
classification.  The module deliberately does not mutate source trees or consume
approvals; it only records and verifies identity transitions.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.schemas import _revision, _sha256
from daedalus.spine.envelope import canonical_json, canonical_sha

from .genesis import ProjectTwinContractError, ProjectTwinManifest

_ALLOWED_DRIFT = frozenset({"initial", "source", "compiler", "evidence", "mixed"})


@dataclass(frozen=True)
class ProjectTwinTransition:
    repository_id: str
    previous_manifest_sha256: str | None
    next_manifest_sha256: str
    source_revision: str
    drift_class: str

    def __post_init__(self) -> None:
        repository_id = str(self.repository_id).strip()
        if not repository_id:
            raise ProjectTwinContractError("repository_id must be non-empty")
        object.__setattr__(self, "repository_id", repository_id)
        if self.previous_manifest_sha256 is not None:
            object.__setattr__(
                self,
                "previous_manifest_sha256",
                _sha256(self.previous_manifest_sha256, "previous_manifest_sha256"),
            )
        object.__setattr__(
            self, "next_manifest_sha256", _sha256(self.next_manifest_sha256, "next_manifest_sha256")
        )
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        drift_class = str(self.drift_class).strip().lower()
        if drift_class not in _ALLOWED_DRIFT:
            raise ProjectTwinContractError("unsupported Project Twin drift_class")
        if self.previous_manifest_sha256 is None and drift_class != "initial":
            raise ProjectTwinContractError("first Project Twin transition must be initial")
        if self.previous_manifest_sha256 is not None and drift_class == "initial":
            raise ProjectTwinContractError("non-initial transition cannot use initial drift")
        if self.previous_manifest_sha256 == self.next_manifest_sha256:
            raise ProjectTwinContractError("Project Twin transition cannot self-reference")
        object.__setattr__(self, "drift_class", drift_class)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-project-twin-transition/1",
            "repository_id": self.repository_id,
            "previous_manifest_sha256": self.previous_manifest_sha256,
            "next_manifest_sha256": self.next_manifest_sha256,
            "source_revision": self.source_revision,
            "drift_class": self.drift_class,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ProjectTwinTransition":
        if payload.get("schema") != "daedalus-project-twin-transition/1":
            raise ProjectTwinContractError("unsupported Project Twin transition schema")
        return cls(
            repository_id=payload["repository_id"],
            previous_manifest_sha256=payload.get("previous_manifest_sha256"),
            next_manifest_sha256=payload["next_manifest_sha256"],
            source_revision=payload["source_revision"],
            drift_class=payload["drift_class"],
        )


def classify_manifest_drift(
    previous: ProjectTwinManifest | None,
    current: ProjectTwinManifest,
) -> str:
    if previous is None:
        return "initial"
    if previous.repository_id != current.repository_id:
        raise ProjectTwinContractError("Project Twin repository identity changed")
    source_changed = (
        previous.source_artifact != current.source_artifact
        or previous.source_forest_sha256 != current.source_forest_sha256
        or previous.fourfold_snapshot_sha256 != current.fourfold_snapshot_sha256
        or previous.source_revision != current.source_revision
    )
    compiler_changed = previous.compiler_contract_sha256 != current.compiler_contract_sha256
    evidence_changed = previous.evidence_packet_sha256 != current.evidence_packet_sha256
    changed = sum((source_changed, compiler_changed, evidence_changed))
    if changed == 0:
        raise ProjectTwinContractError("Project Twin transition contains no identity change")
    if changed > 1:
        return "mixed"
    if source_changed:
        return "source"
    if compiler_changed:
        return "compiler"
    return "evidence"


def build_transition(
    previous: ProjectTwinManifest | None,
    current: ProjectTwinManifest,
) -> ProjectTwinTransition:
    return ProjectTwinTransition(
        repository_id=current.repository_id,
        previous_manifest_sha256=None if previous is None else previous.digest,
        next_manifest_sha256=current.digest,
        source_revision=current.source_revision,
        drift_class=classify_manifest_drift(previous, current),
    )


def verify_lifecycle(
    manifests: Sequence[ProjectTwinManifest],
    transitions: Sequence[ProjectTwinTransition],
) -> None:
    if not manifests:
        raise ProjectTwinContractError("Project Twin lifecycle must contain a manifest")
    if len(manifests) != len(transitions):
        raise ProjectTwinContractError("Project Twin lifecycle cardinality mismatch")
    repository_id = manifests[0].repository_id
    seen_revisions: set[str] = set()
    seen_manifests: set[str] = set()
    previous: ProjectTwinManifest | None = None
    for manifest, transition in zip(manifests, transitions):
        if manifest.repository_id != repository_id:
            raise ProjectTwinContractError("Project Twin lifecycle crosses repositories")
        if manifest.source_revision in seen_revisions:
            raise ProjectTwinContractError("Project Twin lifecycle replays a source revision")
        if manifest.digest in seen_manifests:
            raise ProjectTwinContractError("Project Twin lifecycle replays a manifest")
        expected = build_transition(previous, manifest)
        if transition != expected:
            raise ProjectTwinContractError("Project Twin lifecycle transition mismatch")
        seen_revisions.add(manifest.source_revision)
        seen_manifests.add(manifest.digest)
        previous = manifest


class AtomicProjectTwinLifecycleStore:
    """Append and resolve one canonical lifecycle per repository.

    The complete lifecycle is rewritten atomically, but append validation makes
    it logically append-only.  Any stale writer, history rewrite, replay, or
    non-canonical on-disk representation is rejected.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _repository_key(repository_id: str) -> str:
        normalized = str(repository_id).strip()
        if not normalized:
            raise ProjectTwinContractError("repository_id must be non-empty")
        return canonical_sha({"repository_id": normalized})

    def _path(self, repository_id: str) -> Path:
        return self.root / f"{self._repository_key(repository_id)}.json"

    @staticmethod
    def _payload(
        manifests: Sequence[ProjectTwinManifest],
        transitions: Sequence[ProjectTwinTransition],
    ) -> dict[str, Any]:
        verify_lifecycle(manifests, transitions)
        return {
            "schema": "daedalus-project-twin-lifecycle/1",
            "repository_id": manifests[0].repository_id,
            "manifests": [manifest.to_dict() for manifest in manifests],
            "transitions": [transition.to_dict() for transition in transitions],
            "head_manifest_sha256": manifests[-1].digest,
        }

    def load(
        self, repository_id: str
    ) -> tuple[tuple[ProjectTwinManifest, ...], tuple[ProjectTwinTransition, ...]]:
        path = self._path(repository_id)
        if not path.exists():
            return (), ()
        raw = path.read_bytes()
        try:
            payload = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectTwinContractError("Project Twin lifecycle is not canonical JSON") from exc
        if not isinstance(payload, Mapping) or payload.get("schema") != "daedalus-project-twin-lifecycle/1":
            raise ProjectTwinContractError("unsupported Project Twin lifecycle schema")
        if payload.get("repository_id") != str(repository_id).strip():
            raise ProjectTwinContractError("Project Twin lifecycle repository mismatch")
        manifest_payloads = payload.get("manifests")
        transition_payloads = payload.get("transitions")
        if not isinstance(manifest_payloads, list) or not isinstance(transition_payloads, list):
            raise ProjectTwinContractError("Project Twin lifecycle payload is incomplete")
        manifests = tuple(ProjectTwinManifest.from_dict(item) for item in manifest_payloads)
        transitions = tuple(ProjectTwinTransition.from_dict(item) for item in transition_payloads)
        verify_lifecycle(manifests, transitions)
        if payload.get("head_manifest_sha256") != manifests[-1].digest:
            raise ProjectTwinContractError("Project Twin lifecycle head mismatch")
        if canonical_json(payload).encode("ascii") != raw:
            raise ProjectTwinContractError("Project Twin lifecycle is not canonically encoded")
        return manifests, transitions

    def append(
        self,
        manifest: ProjectTwinManifest,
        *,
        expected_head_sha256: str | None,
    ) -> ArtifactRef:
        manifests, transitions = self.load(manifest.repository_id)
        actual_head = None if not manifests else manifests[-1].digest
        expected = None if expected_head_sha256 is None else _sha256(
            expected_head_sha256, "expected_head_sha256"
        )
        if actual_head != expected:
            raise ProjectTwinContractError("Project Twin lifecycle head changed")
        previous = None if not manifests else manifests[-1]
        transition = build_transition(previous, manifest)
        new_manifests = (*manifests, manifest)
        new_transitions = (*transitions, transition)
        payload = self._payload(new_manifests, new_transitions)
        raw = canonical_json(payload).encode("ascii")
        path = self._path(manifest.repository_id)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=self.root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(self.root, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
        return ArtifactRef.from_sha256(canonical_sha(payload))

    def resolve_head(self, repository_id: str) -> ProjectTwinManifest:
        manifests, _ = self.load(repository_id)
        if not manifests:
            raise ProjectTwinContractError("Project Twin lifecycle does not exist")
        return manifests[-1]


__all__ = [
    "AtomicProjectTwinLifecycleStore",
    "ProjectTwinTransition",
    "build_transition",
    "classify_manifest_drift",
    "verify_lifecycle",
]
