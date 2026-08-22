"""Canonical low-level storage primitives for the Daedalus kernel.

This module owns two related, deliberately small contracts:

* the fail-closed storage watermark used before allocating worktrees; and
* the content-addressed artifact store used for authoritative candidate bytes.

The artifact store is not an archive index, event store, promotion mechanism,
or graph authority.  It stores immutable bytes under a verified SHA-256 digest
and emits an immutable locator containing caller-supplied metadata and
provenance.  The locator may be referenced by the spine ledger; it does not
replace the ledger.

Publication is create-once and atomic.  Existing objects are verified before an
idempotent put succeeds, and corruption is surfaced rather than overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from daedalus.atomic import publish_bytes_once

DEFAULT_MIN_FREE_GIB = 2.0
_GIB = 1024**3

ARTIFACT_LOCATOR_SCHEMA = "daedalus.artifact-locator/1"
ARTIFACT_ALGORITHM = "sha256"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_READ_CHUNK_BYTES = 1024 * 1024

__all__ = [
    "ARTIFACT_ALGORITHM",
    "ARTIFACT_LOCATOR_SCHEMA",
    "ArtifactCorruption",
    "ArtifactDigestMismatch",
    "ArtifactLocator",
    "ArtifactNotFound",
    "ArtifactStore",
    "ArtifactStoreError",
    "DEFAULT_MIN_FREE_GIB",
    "StorageStatus",
    "StorageUnavailable",
    "artifact_locator_uri",
    "artifact_manifest",
    "check_storage",
    "require_storage",
]


class StorageUnavailable(RuntimeError):
    """A required volume is missing or below the free-space watermark."""


class ArtifactStoreError(RuntimeError):
    """Base class for artifact-store refusals."""


class ArtifactDigestMismatch(ArtifactStoreError):
    """The supplied bytes do not match their claimed digest."""


class ArtifactCorruption(ArtifactStoreError):
    """Published bytes or locator metadata no longer match their identity."""


class ArtifactNotFound(ArtifactStoreError):
    """A requested artifact or locator is absent."""


@dataclass(frozen=True)
class StorageStatus:
    path: str
    total_bytes: int
    free_bytes: int
    min_free_bytes: int
    state: str  # "ok" | "storage_unavailable"

    @property
    def ok(self) -> bool:
        return self.state == "ok"


@dataclass(frozen=True)
class ArtifactLocator:
    """A verified reference to one immutable artifact and its provenance.

    ``manifest_bytes`` are the exact bytes whose SHA-256 is
    ``locator_sha256``.  Mapping properties decode a fresh object on every
    access so callers cannot mutate the frozen record through a nested dict.
    Paths are derived from the store root and the two verified digests; no path
    from the manifest is trusted as an arbitrary filesystem target.
    """

    root: Path
    artifact_sha256: str
    byte_length: int
    locator_sha256: str
    manifest_bytes: bytes

    @property
    def uri(self) -> str:
        return f"{ARTIFACT_ALGORITHM}:{self.artifact_sha256}"

    @property
    def locator_uri(self) -> str:
        return f"artifact-locator:{ARTIFACT_ALGORITHM}:{self.locator_sha256}"

    @property
    def blob_path(self) -> Path:
        return _digest_path(
            self.root, "blobs", self.artifact_sha256)

    @property
    def locator_path(self) -> Path:
        return _digest_path(
            self.root, "locators", self.locator_sha256, suffix=".json")

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.manifest_bytes.decode("ascii"))

    @property
    def metadata(self) -> dict[str, Any]:
        return self.to_dict()["metadata"]

    @property
    def provenance(self) -> dict[str, Any]:
        return self.to_dict()["provenance"]

    def portable_summary(self) -> dict[str, Any]:
        """Root-independent identity, metadata, and provenance projection."""
        return {
            "uri": self.uri,
            "locator_uri": self.locator_uri,
            "byte_length": self.byte_length,
            "metadata": self.metadata,
            "provenance": self.provenance,
        }

    def summary(self) -> dict[str, Any]:
        """Ledger projection with portable identity and explicit local hints.

        ``local_paths`` are diagnostics for this store instance, not portable
        artifact identity.  Consumers that cross machines use
        :meth:`portable_summary` and resolve its URIs in their own store.
        """
        return {
            **self.portable_summary(),
            "local_paths": {
                "blob": str(self.blob_path),
                "locator": str(self.locator_path),
            },
        }


def _min_free_bytes(min_free_gib: float | None) -> int:
    if min_free_gib is None:
        raw = os.environ.get("DAEDALUS_MIN_FREE_GIB", "")
        try:
            min_free_gib = float(raw) if raw else DEFAULT_MIN_FREE_GIB
        except ValueError:
            min_free_gib = DEFAULT_MIN_FREE_GIB
    return int(min_free_gib * _GIB)


def check_storage(
        path: str | os.PathLike[str],
        min_free_gib: float | None = None) -> StorageStatus:
    min_free = _min_free_bytes(min_free_gib)
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return StorageStatus(
            path=str(path),
            total_bytes=0,
            free_bytes=0,
            min_free_bytes=min_free,
            state="storage_unavailable",
        )
    state = "ok" if usage.free >= min_free else "storage_unavailable"
    return StorageStatus(
        path=str(path),
        total_bytes=usage.total,
        free_bytes=usage.free,
        min_free_bytes=min_free,
        state=state,
    )


def require_storage(
        path: str | os.PathLike[str],
        min_free_gib: float | None = None) -> StorageStatus:
    status = check_storage(path, min_free_gib=min_free_gib)
    if not status.ok:
        raise StorageUnavailable(
            f"storage_unavailable: {status.path} has {status.free_bytes} bytes free, "
            f"requires {status.min_free_bytes} bytes; refusing to fall back to another volume"
        )
    return status


def _normalise_digest(value: str) -> str:
    digest = str(value or "").strip().lower()
    if digest.startswith(f"{ARTIFACT_ALGORITHM}:"):
        digest = digest.split(":", 1)[1]
    if not _SHA256_RE.fullmatch(digest):
        raise ValueError(
            "artifact digest must be exactly 64 hexadecimal SHA-256 characters")
    return digest


def _digest_path(
        root: Path,
        family: str,
        digest: str,
        *,
        suffix: str = "") -> Path:
    checked = _normalise_digest(digest)
    return root / family / ARTIFACT_ALGORITHM / checked[:2] / (
        f"{checked[2:]}{suffix}")


def _resolved_os_path(path: Path) -> str:
    """One comparable spelling for resolved paths, including Windows devices."""
    rendered = str(path.resolve(strict=False))
    if os.name == "nt":
        # pathlib can add this prefix only after the leaf appears, so two
        # resolutions of the same path can otherwise compare unequal during a
        # concurrent create.
        if rendered.startswith("\\\\?\\UNC\\"):
            rendered = "\\\\" + rendered[8:]
        elif rendered.startswith("\\\\?\\"):
            rendered = rendered[4:]
    return os.path.normcase(os.path.normpath(rendered))


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"artifact metadata/provenance must be canonical JSON: {exc}") from exc
    return text.encode("ascii")


def _json_mapping(value: Mapping[str, Any] | None, *, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be a mapping")
    # Canonical round-trip both validates nested values and severs references to
    # mutable caller-owned dictionaries.
    decoded = json.loads(_canonical_json_bytes(dict(value)).decode("ascii"))
    if not isinstance(decoded, dict):  # defensive; dict(value) already implies it
        raise TypeError(f"{name} must encode to a JSON object")
    return decoded


def _canonical_provenance(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the canonical ``ContractProvenance.to_dict()`` projection.

    This low-level module intentionally does not import ``daedalus.schemas``:
    the contract layer already depends on spine primitives and reversing that
    direction would create a cycle.  The exact five-field wire shape is small
    enough to enforce here at the artifact trust boundary.
    """
    clean = _json_mapping(value, name="provenance")
    required = {"origin", "source_revision", "created_at", "input_digests"}
    allowed = required | {"trace_id"}
    missing = required - set(clean)
    unknown = set(clean) - allowed
    if missing:
        raise ValueError(
            f"artifact provenance is missing canonical field(s): {sorted(missing)}")
    if unknown:
        raise ValueError(
            f"artifact provenance has unknown field(s): {sorted(unknown)}")

    origin = clean["origin"]
    if not isinstance(origin, str) or not _IDENTIFIER_RE.fullmatch(origin):
        raise ValueError("artifact provenance origin is not a canonical identifier")

    source_revision = str(clean["source_revision"]).lower()
    if not _REVISION_RE.fullmatch(source_revision):
        raise ValueError(
            "artifact provenance source_revision must be an exact 40- or "
            "64-character source digest")
    clean["source_revision"] = source_revision

    created_at = clean["created_at"]
    if not isinstance(created_at, str):
        raise ValueError("artifact provenance created_at must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(
            "artifact provenance created_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("artifact provenance created_at must include a timezone")
    clean["created_at"] = parsed.astimezone(timezone.utc).isoformat(
        timespec="microseconds")

    inputs = clean["input_digests"]
    if not isinstance(inputs, list):
        raise ValueError("artifact provenance input_digests must be a JSON array")
    normalised_inputs: list[str] = []
    for index, digest in enumerate(inputs):
        candidate = str(digest).lower()
        if not _SHA256_RE.fullmatch(candidate):
            raise ValueError(
                f"artifact provenance input_digests[{index}] is not a SHA-256 digest")
        normalised_inputs.append(candidate)
    if len(set(normalised_inputs)) != len(normalised_inputs):
        raise ValueError("artifact provenance input_digests must not contain duplicates")
    clean["input_digests"] = sorted(normalised_inputs)

    trace_id = clean.get("trace_id")
    if (trace_id is not None
            and (not isinstance(trace_id, str)
                 or not _IDENTIFIER_RE.fullmatch(trace_id))):
        raise ValueError(
            "artifact provenance trace_id must be null or a canonical identifier")
    clean.setdefault("trace_id", None)
    return clean


def artifact_locator_uri(locator_sha256: str) -> str:
    """The ``artifact-locator:sha256:<digest>`` URI for one locator digest."""
    return f"artifact-locator:{ARTIFACT_ALGORITHM}:{_normalise_digest(locator_sha256)}"


def artifact_manifest(
        data: bytes | bytearray | memoryview,
        *,
        media_type: str = "application/octet-stream",
        metadata: Mapping[str, Any] | None = None,
        provenance: Mapping[str, Any]) -> tuple[str, bytes, str]:
    """``(artifact_sha256, manifest_bytes, locator_sha256)`` for these bytes.

    Root-independent by construction: the manifest names its blob by the
    store-RELATIVE path, so identical bytes with identical metadata and
    provenance produce the identical locator digest in every store.  That is
    what lets a caller PREDICT the locator a :meth:`ArtifactStore.put_bytes`
    will return, and therefore lets a verifier holding no store re-derive the
    exact locator an evidence record is required to carry, instead of trusting
    whatever string that record happens to contain.

    :meth:`ArtifactStore.put_bytes` builds its manifest here, so a prediction
    and the bytes actually stored cannot drift into two implementations.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("artifact data must be bytes-like")
    payload = bytes(data)
    artifact_sha256 = hashlib.sha256(payload).hexdigest()
    clean_metadata = _json_mapping(metadata, name="metadata")
    clean_provenance = _canonical_provenance(provenance)
    clean_media_type = str(media_type or "").strip()
    if not clean_media_type:
        raise ValueError("artifact media_type must be non-empty")
    manifest = {
        "schema": ARTIFACT_LOCATOR_SCHEMA,
        "artifact": {
            "algorithm": ARTIFACT_ALGORITHM,
            "sha256": artifact_sha256,
            "byte_length": len(payload),
            "path": _digest_path(Path("."), "blobs", artifact_sha256).as_posix(),
        },
        "media_type": clean_media_type,
        "metadata": clean_metadata,
        "provenance": clean_provenance,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    return artifact_sha256, manifest_bytes, hashlib.sha256(manifest_bytes).hexdigest()


def _existing_ancestor(path: Path) -> Path:
    """Nearest existing ground for a side-effect-free volume measurement."""
    candidate = path
    while not candidate.exists() and candidate.parent != candidate:
        candidate = candidate.parent
    return candidate


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(_READ_CHUNK_BYTES)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
    except FileNotFoundError as exc:
        raise ArtifactNotFound(f"artifact object is missing: {path}") from exc
    except OSError as exc:
        raise ArtifactStoreError(f"artifact object cannot be read: {path}: {exc}") from exc
    return digest.hexdigest(), size


def _read_verified_bytes(
        path: Path,
        expected_sha256: str,
        *,
        expected_size: int | None = None,
        label: str) -> bytes:
    """Read once and verify the exact bytes returned to the caller."""
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise ArtifactNotFound(f"{label} is missing: {path}") from exc
    except OSError as exc:
        raise ArtifactStoreError(f"{label} cannot be read: {path}: {exc}") from exc
    actual_sha256 = hashlib.sha256(data).hexdigest()
    if actual_sha256 != expected_sha256:
        raise ArtifactCorruption(
            f"{label} corruption at {path}: expected sha256 "
            f"{expected_sha256}, found {actual_sha256}")
    if expected_size is not None and len(data) != expected_size:
        raise ArtifactCorruption(
            f"{label} corruption at {path}: expected {expected_size} bytes, "
            f"found {len(data)}")
    return data


class ArtifactStore:
    """Create-once, SHA-256-addressed bytes plus immutable locator manifests."""

    def __init__(
            self,
            root: str | os.PathLike[str],
            *,
            min_free_gib: float | None = None):
        raw = Path(root)
        # Resolve once so a pre-existing symlink used as the root cannot make
        # later paths appear to live somewhere different from their real root.
        self.root = raw.expanduser().resolve(strict=False)
        self._root_identity = _resolved_os_path(self.root)
        self.min_free_gib = min_free_gib

    def blob_path(self, digest: str) -> Path:
        return _digest_path(self.root, "blobs", digest)

    def locator_path(self, locator_digest: str) -> Path:
        return _digest_path(
            self.root, "locators", locator_digest, suffix=".json")

    def _assert_confined(self, path: Path) -> None:
        """Refuse existing symlink/junction components that escape ``root``.

        The store never accepts a caller-provided relative payload path, but an
        existing directory component can still redirect a generated path.  A
        resolve-and-compare check catches that before publication.  This is not
        advertised as a hostile concurrent-filesystem sandbox; Gate 0's effect
        boundary remains responsible for keeping candidate processes away from
        the store root.
        """
        try:
            # Windows pathlib may add ``\\?\`` only after the leaf appears;
            # _resolved_os_path normalises that spelling before comparing the
            # child with the root identity pinned at construction.
            resolved_path = _resolved_os_path(path)
            common = os.path.commonpath((self._root_identity, resolved_path))
            if os.path.normcase(common) != os.path.normcase(self._root_identity):
                raise ValueError("resolved child is outside resolved root")
        except (OSError, ValueError) as exc:
            raise ArtifactStoreError(
                f"artifact path escapes store root through an existing link: {path}"
            ) from exc
        if path.is_symlink():
            raise ArtifactStoreError(
                f"artifact path is a symlink, refusing content-addressed alias: {path}")

    @staticmethod
    def _verify_file(
            path: Path,
            expected_sha256: str,
            *,
            expected_size: int | None = None,
            label: str = "artifact") -> None:
        actual_sha256, actual_size = _hash_file(path)
        if actual_sha256 != expected_sha256:
            raise ArtifactCorruption(
                f"{label} corruption at {path}: expected sha256 "
                f"{expected_sha256}, found {actual_sha256}")
        if expected_size is not None and actual_size != expected_size:
            raise ArtifactCorruption(
                f"{label} corruption at {path}: expected {expected_size} bytes, "
                f"found {actual_size}")

    def _publish_immutable(
            self,
            path: Path,
            data: bytes,
            expected_sha256: str,
            *,
            label: str) -> None:
        self._assert_confined(path)
        try:
            publish_bytes_once(path, data)
        except OSError as exc:
            raise ArtifactStoreError(
                f"{label} could not be atomically published at {path}: {exc}") from exc
        # Verify after both the created and already-existed outcomes.  This also
        # catches a fault injected after link creation and turns the next retry
        # into a deterministic idempotent recovery.
        self._verify_file(
            path, expected_sha256, expected_size=len(data), label=label)

    def put_bytes(
            self,
            data: bytes | bytearray | memoryview,
            *,
            expected_sha256: str | None = None,
            media_type: str = "application/octet-stream",
            metadata: Mapping[str, Any] | None = None,
            provenance: Mapping[str, Any]) -> ArtifactLocator:
        """Store ``data`` and return its verified immutable locator.

        ``expected_sha256`` is optional for fresh source bytes and mandatory in
        spirit for a caller that already claims an identity.  When present it
        is checked *before any directory is created*.  ``provenance`` must name
        a non-empty ``origin`` so material bytes cannot enter the kernel as an
        unattributed object.
        """
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError("artifact data must be bytes-like")
        payload = bytes(data)
        actual_sha256 = hashlib.sha256(payload).hexdigest()
        if expected_sha256 is not None:
            claimed_sha256 = _normalise_digest(expected_sha256)
            if claimed_sha256 != actual_sha256:
                raise ArtifactDigestMismatch(
                    f"artifact digest mismatch: claimed {claimed_sha256}, "
                    f"computed {actual_sha256}")

        # ONE implementation of the manifest, shared with the module-level
        # `artifact_manifest`, so a caller that predicts a locator and this
        # method that stores one cannot drift into two answers.
        _, manifest_bytes, locator_sha256 = artifact_manifest(
            payload,
            media_type=media_type,
            metadata=metadata,
            provenance=provenance)

        blob_path = self.blob_path(actual_sha256)
        locator_path = self.locator_path(locator_sha256)

        # Check the artifact volume itself, which may differ from the worktree
        # volume TaskAttempt already checked.  Both generated paths are
        # confined before the watermark read, and the read happens before
        # publish_bytes_once can mkdir.
        self._assert_confined(blob_path)
        self._assert_confined(locator_path)
        require_storage(
            _existing_ancestor(self.root),
            min_free_gib=self.min_free_gib,
        )

        # Blob first, locator second.  A crash can leave an unreferenced,
        # content-addressed blob, which a retry safely reuses.  The inverse
        # ordering could leave a locator claiming bytes that never existed.
        self._publish_immutable(
            blob_path, payload, actual_sha256, label="artifact blob")
        self._publish_immutable(
            locator_path, manifest_bytes, locator_sha256,
            label="artifact locator")
        return ArtifactLocator(
            root=self.root,
            artifact_sha256=actual_sha256,
            byte_length=len(payload),
            locator_sha256=locator_sha256,
            manifest_bytes=manifest_bytes,
        )

    def get_bytes(self, digest: str) -> bytes:
        """Read bytes only after their path identity has been verified."""
        checked = _normalise_digest(digest)
        path = self.blob_path(checked)
        self._assert_confined(path)
        return _read_verified_bytes(
            path, checked, label="artifact blob")

    def load_locator(self, locator_digest: str) -> ArtifactLocator:
        """Load and structurally validate an immutable locator by its digest."""
        checked_locator = _normalise_digest(locator_digest)
        path = self.locator_path(checked_locator)
        self._assert_confined(path)
        try:
            manifest_bytes = _read_verified_bytes(
                path, checked_locator, label="artifact locator")
            manifest = json.loads(manifest_bytes.decode("ascii"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ArtifactCorruption(
                f"artifact locator cannot be decoded at {path}: {exc}") from exc
        if _canonical_json_bytes(manifest) != manifest_bytes:
            raise ArtifactCorruption(
                f"artifact locator at {path} is not canonical JSON")
        if not isinstance(manifest, dict) or manifest.get("schema") != ARTIFACT_LOCATOR_SCHEMA:
            raise ArtifactCorruption(
                f"artifact locator at {path} has an unknown schema")
        if set(manifest) != {
                "schema", "artifact", "media_type", "metadata", "provenance"}:
            raise ArtifactCorruption(
                f"artifact locator at {path} has an unknown top-level field")

        artifact = manifest.get("artifact")
        if not isinstance(artifact, dict):
            raise ArtifactCorruption(
                f"artifact locator at {path} has no artifact object")
        if set(artifact) != {"algorithm", "sha256", "byte_length", "path"}:
            raise ArtifactCorruption(
                f"artifact locator at {path} has an unknown artifact field")
        try:
            artifact_sha256 = _normalise_digest(artifact.get("sha256", ""))
        except ValueError as exc:
            raise ArtifactCorruption(
                f"artifact locator at {path} has an invalid artifact digest") from exc
        byte_length = artifact.get("byte_length")
        if isinstance(byte_length, bool) or not isinstance(byte_length, int) or byte_length < 0:
            raise ArtifactCorruption(
                f"artifact locator at {path} has an invalid byte_length")
        expected_blob = self.blob_path(artifact_sha256)
        expected_relpath = expected_blob.relative_to(self.root).as_posix()
        if (artifact.get("algorithm") != ARTIFACT_ALGORITHM
                or artifact.get("path") != expected_relpath):
            raise ArtifactCorruption(
                f"artifact locator at {path} does not name its derived blob path")
        if not isinstance(manifest.get("metadata"), dict):
            raise ArtifactCorruption(
                f"artifact locator at {path} has invalid metadata")
        provenance = manifest.get("provenance")
        try:
            canonical_provenance = _canonical_provenance(provenance)
        except (TypeError, ValueError) as exc:
            raise ArtifactCorruption(
                f"artifact locator at {path} has invalid provenance") from exc
        if canonical_provenance != provenance:
            raise ArtifactCorruption(
                f"artifact locator at {path} has non-canonical provenance")
        media_type = manifest.get("media_type")
        if (not isinstance(media_type, str)
                or not media_type
                or media_type != media_type.strip()):
            raise ArtifactCorruption(
                f"artifact locator at {path} has an invalid media_type")

        return ArtifactLocator(
            root=self.root,
            artifact_sha256=artifact_sha256,
            byte_length=byte_length,
            locator_sha256=checked_locator,
            manifest_bytes=manifest_bytes,
        )

    def verify(self, locator: ArtifactLocator) -> ArtifactLocator:
        """Re-read locator and blob, refusing any identity or size drift."""
        if locator.root != self.root:
            raise ArtifactStoreError(
                f"locator belongs to {locator.root}, not store {self.root}")
        loaded = self.load_locator(locator.locator_sha256)
        if (loaded.artifact_sha256 != locator.artifact_sha256
                or loaded.manifest_bytes != locator.manifest_bytes):
            raise ArtifactCorruption(
                "in-memory artifact locator disagrees with its stored manifest")
        blob_path = loaded.blob_path
        self._assert_confined(blob_path)
        self._verify_file(
            blob_path,
            loaded.artifact_sha256,
            expected_size=loaded.byte_length,
            label="artifact blob",
        )
        return loaded
