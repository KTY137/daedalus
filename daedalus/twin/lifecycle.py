"""Revision-exact Project Twin lifecycle contracts for Gate 2.

A lifecycle is an append-only chain of already verified Project Twin manifests.
Each transition binds the previous head, the next manifest, and an explicit drift
classification. The module deliberately does not mutate source trees or consume
approvals; it only records and verifies identity transitions.
"""
from __future__ import annotations

import json
import os
import socket
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

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
            object.__setattr__(self, "previous_manifest_sha256", _sha256(self.previous_manifest_sha256, "previous_manifest_sha256"))
        object.__setattr__(self, "next_manifest_sha256", _sha256(self.next_manifest_sha256, "next_manifest_sha256"))
        object.__setattr__(self, "source_revision", _revision(self.source_revision, "source_revision"))
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


def classify_manifest_drift(previous: ProjectTwinManifest | None, current: ProjectTwinManifest) -> str:
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


def build_transition(previous: ProjectTwinManifest | None, current: ProjectTwinManifest) -> ProjectTwinTransition:
    return ProjectTwinTransition(
        repository_id=current.repository_id,
        previous_manifest_sha256=None if previous is None else previous.digest,
        next_manifest_sha256=current.digest,
        source_revision=current.source_revision,
        drift_class=classify_manifest_drift(previous, current),
    )


def verify_lifecycle(manifests: Sequence[ProjectTwinManifest], transitions: Sequence[ProjectTwinTransition]) -> None:
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


def _default_owner_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class AtomicProjectTwinLifecycleStore:
    """Append and resolve one canonical lifecycle per repository.

    Writers are serialized with an exclusive repository lock. Lock records bind a
    host, process, and random ownership token. An abandoned same-host lock may be
    reclaimed only after the recorded process is proven absent. Foreign-host,
    malformed, symlinked, or live locks always fail closed.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        fault_injector: Callable[[str], None] | None = None,
        owner_alive: Callable[[int], bool] | None = None,
        hostname: str | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._fault_injector = fault_injector
        self._owner_alive = owner_alive or _default_owner_alive
        self._hostname = hostname or socket.gethostname()
        self._cleanup_orphaned_temporaries()

    def _fault(self, phase: str) -> None:
        if self._fault_injector is not None:
            self._fault_injector(phase)

    @staticmethod
    def _write_all(fd: int, raw: bytes) -> None:
        view = memoryview(raw)
        offset = 0
        while offset < len(view):
            written = os.write(fd, view[offset:])
            if written <= 0:
                raise ProjectTwinContractError("Project Twin lifecycle lock write made no progress")
            offset += written

    def _fsync_root_directory(self) -> None:
        directory_fd = os.open(self.root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    @staticmethod
    def _repository_key(repository_id: str) -> str:
        normalized = str(repository_id).strip()
        if not normalized:
            raise ProjectTwinContractError("repository_id must be non-empty")
        return canonical_sha({"repository_id": normalized})

    def _path(self, repository_id: str) -> Path:
        return self.root / f"{self._repository_key(repository_id)}.json"

    def _lock_path(self, repository_id: str) -> Path:
        return self.root / f"{self._repository_key(repository_id)}.lock"

    def _cleanup_orphaned_temporaries(self) -> None:
        for path in self.root.glob(".*.tmp"):
            if path.is_file() and not path.is_symlink():
                path.unlink(missing_ok=True)

    @staticmethod
    def _decode_lock(raw: bytes) -> Mapping[str, Any]:
        try:
            payload = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProjectTwinContractError("Project Twin lifecycle lock is malformed") from exc
        if not isinstance(payload, Mapping) or payload.get("schema") != "daedalus-project-twin-lock/1":
            raise ProjectTwinContractError("Project Twin lifecycle lock schema is invalid")
        if canonical_json(payload).encode("ascii") != raw:
            raise ProjectTwinContractError("Project Twin lifecycle lock is not canonically encoded")
        if not isinstance(payload.get("hostname"), str) or not payload["hostname"]:
            raise ProjectTwinContractError("Project Twin lifecycle lock hostname is invalid")
        if not isinstance(payload.get("pid"), int) or payload["pid"] <= 0:
            raise ProjectTwinContractError("Project Twin lifecycle lock pid is invalid")
        token = payload.get("owner_token")
        if not isinstance(token, str) or len(token) != 32:
            raise ProjectTwinContractError("Project Twin lifecycle lock owner token is invalid")
        try:
            int(token, 16)
        except ValueError as exc:
            raise ProjectTwinContractError("Project Twin lifecycle lock owner token is invalid") from exc
        return payload

    def _try_reclaim_abandoned_lock(self, lock_path: Path) -> bool:
        if lock_path.is_symlink():
            raise ProjectTwinContractError("Project Twin lifecycle lock cannot be a symlink")
        try:
            raw = lock_path.read_bytes()
        except FileNotFoundError:
            return True
        payload = self._decode_lock(raw)
        if payload["hostname"] != self._hostname:
            return False
        if self._owner_alive(payload["pid"]):
            return False
        try:
            if lock_path.read_bytes() != raw:
                return False
            lock_path.unlink()
            self._fsync_root_directory()
        except FileNotFoundError:
            return True
        return True

    @contextmanager
    def _exclusive_writer(self, repository_id: str) -> Iterator[None]:
        lock_path = self._lock_path(repository_id)
        payload = {
            "schema": "daedalus-project-twin-lock/1",
            "hostname": self._hostname,
            "pid": os.getpid(),
            "owner_token": uuid.uuid4().hex,
        }
        raw = canonical_json(payload).encode("ascii")
        fd: int | None = None
        for attempt in range(2):
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                break
            except FileExistsError as exc:
                if attempt == 0 and self._try_reclaim_abandoned_lock(lock_path):
                    continue
                raise ProjectTwinContractError("Project Twin lifecycle writer is already active") from exc
        if fd is None:  # pragma: no cover - defensive guard
            raise ProjectTwinContractError("Project Twin lifecycle writer lock was not acquired")
        try:
            self._write_all(fd, raw)
            os.fsync(fd)
            self._fsync_root_directory()
            yield
        finally:
            os.close(fd)
            try:
                current = lock_path.read_bytes()
            except FileNotFoundError:
                current = None
            if current == raw:
                lock_path.unlink(missing_ok=True)
                self._fsync_root_directory()

    @staticmethod
    def _payload(manifests: Sequence[ProjectTwinManifest], transitions: Sequence[ProjectTwinTransition]) -> dict[str, Any]:
        verify_lifecycle(manifests, transitions)
        return {
            "schema": "daedalus-project-twin-lifecycle/1",
            "repository_id": manifests[0].repository_id,
            "manifests": [manifest.to_dict() for manifest in manifests],
            "transitions": [transition.to_dict() for transition in transitions],
            "head_manifest_sha256": manifests[-1].digest,
        }

    def load(self, repository_id: str) -> tuple[tuple[ProjectTwinManifest, ...], tuple[ProjectTwinTransition, ...]]:
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

    def append(self, manifest: ProjectTwinManifest, *, expected_head_sha256: str | None) -> ArtifactRef:
        with self._exclusive_writer(manifest.repository_id):
            manifests, transitions = self.load(manifest.repository_id)
            actual_head = None if not manifests else manifests[-1].digest
            expected = None if expected_head_sha256 is None else _sha256(expected_head_sha256, "expected_head_sha256")
            if actual_head != expected:
                raise ProjectTwinContractError("Project Twin lifecycle head changed")
            previous = None if not manifests else manifests[-1]
            transition = build_transition(previous, manifest)
            payload = self._payload((*manifests, manifest), (*transitions, transition))
            raw = canonical_json(payload).encode("ascii")
            path = self._path(manifest.repository_id)
            fd, temporary_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=self.root)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                self._fault("after_temp_fsync")
                os.replace(temporary, path)
                self._fault("after_replace")
                directory_fd = os.open(self.root, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
                self._fault("after_directory_fsync")
                loaded_manifests, _ = self.load(manifest.repository_id)
                if loaded_manifests[-1].digest != manifest.digest:
                    raise ProjectTwinContractError("Project Twin lifecycle readback mismatch")
            finally:
                temporary.unlink(missing_ok=True)
            return ArtifactRef.from_sha256(canonical_sha(payload))

    def resolve_head(self, repository_id: str) -> ProjectTwinManifest:
        manifests, _ = self.load(repository_id)
        if not manifests:
            raise ProjectTwinContractError("Project Twin lifecycle does not exist")
        return manifests[-1]


__all__ = ["AtomicProjectTwinLifecycleStore", "ProjectTwinTransition", "build_transition", "classify_manifest_drift", "verify_lifecycle"]
