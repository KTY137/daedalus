"""Read-only semantic verification for repository-write source anchors.

The materialization and origin layers prove exact CAS bytes and an authenticated
collector projection.  This module performs the first local semantic replay: it
re-materializes the evidence, re-authenticates its origin, and binds exactly one
source-anchor receipt for every classified write surface to the current regular
repository file at the declared path and AST byte offset.

Only source-anchor semantics are established here.  Guard, Effect-Lease,
runtime-conformance, checkout-disjointness, and retirement receipts remain
unverified, so this module cannot authenticate the complete evidence set, bind a
GateReport, or close Gate 0.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from daedalus.gates.repository_write_classification import (
    EvidenceBinding,
    EvidenceKind,
    RepositoryWriteClassificationReport,
    surface_binding_sha256,
)
from daedalus.gates.repository_write_evidence_materialization import (
    MaterializedEvidenceRecord,
    RepositoryWriteEvidenceMaterializationReport,
    materialize_repository_write_evidence,
)
from daedalus.gates.repository_write_evidence_origin import (
    RepositoryWriteEvidenceOriginAttestation,
    RepositoryWriteEvidenceOriginReport,
    verify_repository_write_evidence_origin,
)
from daedalus.spine.envelope import canonical_json


_REPORT_SCHEMA = "daedalus-gate0-repository-write-source-anchor-semantics/1"
_EVIDENCE_SCHEMA = "daedalus-gate0-repository-write-evidence-object/1"
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY_PATH = re.compile(
    r"^(?!/)(?![A-Za-z]:/)(?!.*(?:^|/)\.\.?(?:/|$))(?!.*//)[^\\\r\n]+$"
)
_MAX_EVIDENCE_BYTES = 1_048_576
_MAX_SOURCE_BYTES = 16 * 1_048_576


class RepositoryWriteSourceAnchorSemanticsError(RuntimeError):
    """Source-anchor evidence was incomplete, stale, or semantically invalid."""


class RepositoryWriteSourceAnchorTreeError(
    RepositoryWriteSourceAnchorSemanticsError
):
    """The selected repository tree cannot support an exact source anchor."""


class RepositoryWriteSourceAnchorBindingError(
    RepositoryWriteSourceAnchorSemanticsError
):
    """The authenticated evidence does not bind the current source tree."""


def _strict_revision(value: object, label: str) -> str:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise RepositoryWriteSourceAnchorSemanticsError(
            f"{label} must be lowercase 40-hex"
        )
    return value


def _strict_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise RepositoryWriteSourceAnchorSemanticsError(
            f"{label} must be lowercase sha256"
        )
    return value


def _strict_path(value: object, label: str) -> str:
    if not isinstance(value, str) or _REPOSITORY_PATH.fullmatch(value) is None:
        raise RepositoryWriteSourceAnchorSemanticsError(
            f"{label} must be normalized repository-relative POSIX"
        )
    return value


def _strict_int(value: object, label: str) -> int:
    if type(value) is not int:
        raise RepositoryWriteSourceAnchorSemanticsError(
            f"{label} must be a strict integer"
        )
    return value


def _require_exact_keys(
    value: Mapping[str, object], required: set[str], label: str
) -> None:
    if set(value) != required:
        raise RepositoryWriteSourceAnchorSemanticsError(
            f"{label} keys differ from the exact schema"
        )


def _reject_duplicate_keys(
    pairs: Sequence[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RepositoryWriteSourceAnchorSemanticsError(
                "evidence JSON contains duplicate keys"
            )
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise RepositoryWriteSourceAnchorSemanticsError(
        f"evidence JSON contains non-finite number {value}"
    )


def _parse_source_anchor_payload(
    binding: EvidenceBinding,
    record: MaterializedEvidenceRecord,
    raw: bytes,
) -> Mapping[str, object]:
    if type(raw) is not bytes:
        raise RepositoryWriteSourceAnchorSemanticsError(
            "source-anchor blob must be exact bytes"
        )
    if len(raw) > _MAX_EVIDENCE_BYTES:
        raise RepositoryWriteSourceAnchorSemanticsError(
            "source-anchor blob exceeds the bounded evidence size"
        )
    if hashlib.sha256(raw).hexdigest() != record.blob_sha256:
        raise RepositoryWriteSourceAnchorBindingError(
            "source-anchor blob changed after materialization"
        )
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise RepositoryWriteSourceAnchorSemanticsError(
            "source-anchor blob encoding is invalid"
        )
    try:
        text = raw.decode("utf-8", errors="strict")
        document = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
        canonical = canonical_json(document).encode("ascii")
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RepositoryWriteSourceAnchorSemanticsError,
        RecursionError,
        TypeError,
        ValueError,
    ) as exc:
        raise RepositoryWriteSourceAnchorSemanticsError(
            "source-anchor blob is not strict canonical JSON"
        ) from exc
    if raw != canonical:
        raise RepositoryWriteSourceAnchorSemanticsError(
            "source-anchor blob bytes are not canonical JSON"
        )
    if not isinstance(document, dict):
        raise RepositoryWriteSourceAnchorSemanticsError(
            "source-anchor evidence must be an object"
        )
    _require_exact_keys(
        document,
        {
            "schema",
            "kind",
            "source_revision",
            "surface_sha256",
            "guard_contract",
            "subject_sha256",
            "payload_sha256",
            "payload",
        },
        "source-anchor envelope",
    )
    expected_envelope = {
        "schema": _EVIDENCE_SCHEMA,
        "kind": EvidenceKind.SOURCE_ANCHOR.value,
        "source_revision": binding.source_revision,
        "surface_sha256": binding.surface_sha256,
        "guard_contract": "",
        "subject_sha256": record.subject_sha256,
    }
    for field, expected in expected_envelope.items():
        if document[field] != expected:
            raise RepositoryWriteSourceAnchorBindingError(
                f"source-anchor envelope {field} differs from its binding"
            )
    payload = document["payload"]
    if not isinstance(payload, dict):
        raise RepositoryWriteSourceAnchorSemanticsError(
            "source-anchor payload must be an object"
        )
    _require_exact_keys(
        payload,
        {"path", "line", "column", "source_sha256"},
        "source-anchor payload",
    )
    payload_sha256 = hashlib.sha256(
        canonical_json(payload).encode("ascii")
    ).hexdigest()
    if document["payload_sha256"] != payload_sha256:
        raise RepositoryWriteSourceAnchorBindingError(
            "source-anchor payload digest is invalid"
        )
    if record.payload_sha256 != payload_sha256:
        raise RepositoryWriteSourceAnchorBindingError(
            "source-anchor payload differs from materialization"
        )
    return payload


def _resolve_repository_root(repository_root: Path) -> Path:
    if not isinstance(repository_root, Path):
        raise RepositoryWriteSourceAnchorTreeError(
            "repository_root must be a pathlib.Path"
        )
    try:
        metadata = repository_root.lstat()
    except OSError as exc:
        raise RepositoryWriteSourceAnchorTreeError(
            "repository root is unavailable"
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise RepositoryWriteSourceAnchorTreeError(
            "repository root must be a real directory"
        )
    try:
        return repository_root.resolve(strict=True)
    except OSError as exc:
        raise RepositoryWriteSourceAnchorTreeError(
            "repository root cannot be resolved"
        ) from exc


def _read_exact_source(root: Path, relative_path: str) -> bytes:
    relative = Path(*relative_path.split("/"))
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            component = current.lstat()
        except OSError as exc:
            raise RepositoryWriteSourceAnchorTreeError(
                f"source anchor path is unavailable: {relative_path}"
            ) from exc
        if stat.S_ISLNK(component.st_mode):
            raise RepositoryWriteSourceAnchorTreeError(
                f"source anchor path contains a symlink: {relative_path}"
            )
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(
            component.st_mode
        ):
            raise RepositoryWriteSourceAnchorTreeError(
                f"source anchor parent is not a directory: {relative_path}"
            )
    if not stat.S_ISREG(component.st_mode):
        raise RepositoryWriteSourceAnchorTreeError(
            f"source anchor path is not a regular file: {relative_path}"
        )
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RepositoryWriteSourceAnchorTreeError(
            f"source anchor escapes the repository root: {relative_path}"
        ) from exc
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(current, flags)
    except OSError as exc:
        raise RepositoryWriteSourceAnchorTreeError(
            f"source anchor file cannot be opened safely: {relative_path}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise RepositoryWriteSourceAnchorTreeError(
                f"opened source anchor is not regular: {relative_path}"
            )
        if (before.st_dev, before.st_ino) != (component.st_dev, component.st_ino):
            raise RepositoryWriteSourceAnchorTreeError(
                f"source anchor changed before open: {relative_path}"
            )
        if before.st_size > _MAX_SOURCE_BYTES:
            raise RepositoryWriteSourceAnchorTreeError(
                f"source anchor file exceeds the bounded source size: {relative_path}"
            )
        chunks: list[bytes] = []
        remaining = _MAX_SOURCE_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > _MAX_SOURCE_BYTES:
            raise RepositoryWriteSourceAnchorTreeError(
                f"source anchor file exceeds the bounded source size: {relative_path}"
            )
        after = os.fstat(descriptor)
    except OSError as exc:
        raise RepositoryWriteSourceAnchorTreeError(
            f"source anchor file cannot be read: {relative_path}"
        ) from exc
    finally:
        os.close(descriptor)
    try:
        final_path = current.lstat()
    except OSError as exc:
        raise RepositoryWriteSourceAnchorTreeError(
            f"source anchor path disappeared after read: {relative_path}"
        ) from exc
    identity_before = (before.st_dev, before.st_ino, before.st_size)
    identity_after = (after.st_dev, after.st_ino, after.st_size)
    identity_path = (final_path.st_dev, final_path.st_ino, final_path.st_size)
    if identity_before != identity_after or identity_after != identity_path:
        raise RepositoryWriteSourceAnchorTreeError(
            f"source anchor file changed while reading: {relative_path}"
        )
    if len(raw) != before.st_size:
        raise RepositoryWriteSourceAnchorTreeError(
            f"source anchor read was incomplete: {relative_path}"
        )
    if b"\x00" in raw:
        raise RepositoryWriteSourceAnchorTreeError(
            f"source anchor file contains NUL bytes: {relative_path}"
        )
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RepositoryWriteSourceAnchorTreeError(
            f"source anchor file is not strict UTF-8: {relative_path}"
        ) from exc
    return raw


def _verify_byte_position(
    raw: bytes,
    *,
    line: int,
    column: int,
    relative_path: str,
) -> None:
    lines = raw.splitlines()
    if line < 1 or line > len(lines):
        raise RepositoryWriteSourceAnchorBindingError(
            f"source anchor line is outside the file: {relative_path}"
        )
    selected = lines[line - 1]
    if column < 0 or column >= len(selected):
        raise RepositoryWriteSourceAnchorBindingError(
            f"source anchor column is outside the line: {relative_path}"
        )
    if selected[column : column + 1].isspace():
        raise RepositoryWriteSourceAnchorBindingError(
            f"source anchor column points at whitespace: {relative_path}"
        )


@dataclass(frozen=True)
class SourceAnchorSemanticRecord:
    surface_sha256: str
    locator: str
    path: str
    line: int
    column: int
    source_sha256: str

    def __post_init__(self) -> None:
        _strict_sha(self.surface_sha256, "surface_sha256")
        _strict_path(self.path, "path")
        if not isinstance(self.locator, str) or not self.locator.startswith(
            "cas:sha256:"
        ):
            raise ValueError("locator must be content-addressed")
        _strict_sha(self.locator.removeprefix("cas:sha256:"), "locator digest")
        if _strict_int(self.line, "line") < 1:
            raise ValueError("line must be positive")
        if _strict_int(self.column, "column") < 0:
            raise ValueError("column must be non-negative")
        _strict_sha(self.source_sha256, "source_sha256")

    def sort_key(self) -> tuple[str, int, int, str]:
        return (self.path, self.line, self.column, self.surface_sha256)

    def to_dict(self) -> dict[str, object]:
        return {
            "surface_sha256": self.surface_sha256,
            "locator": self.locator,
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "source_sha256": self.source_sha256,
        }


@dataclass(frozen=True)
class RepositoryWriteSourceAnchorSemanticsReport:
    source_revision: str
    classification_digest: str
    materialization_digest: str
    origin_report_digest: str
    attestation_digest: str
    classification_count: int
    source_anchor_count: int
    anchored_source_set_sha256: str
    records: tuple[SourceAnchorSemanticRecord, ...]

    def __post_init__(self) -> None:
        _strict_revision(self.source_revision, "source_revision")
        for field_name in (
            "classification_digest",
            "materialization_digest",
            "origin_report_digest",
            "attestation_digest",
            "anchored_source_set_sha256",
        ):
            _strict_sha(getattr(self, field_name), field_name)
        if (
            type(self.classification_count) is not int
            or self.classification_count < 1
        ):
            raise ValueError("classification_count must be positive")
        if (
            type(self.source_anchor_count) is not int
            or self.source_anchor_count < 1
        ):
            raise ValueError("source_anchor_count must be positive")
        if not isinstance(self.records, tuple) or any(
            not isinstance(record, SourceAnchorSemanticRecord)
            for record in self.records
        ):
            raise ValueError("records must be an immutable typed tuple")
        if (
            tuple(sorted(self.records, key=SourceAnchorSemanticRecord.sort_key))
            != self.records
        ):
            raise ValueError("records must be canonically sorted")
        if len(set(self.records)) != len(self.records):
            raise ValueError("records must be unique")
        if self.source_anchor_count != len(self.records):
            raise ValueError("source_anchor_count differs from records")
        if self.source_anchor_count != self.classification_count:
            raise ValueError("every classification must have exactly one source anchor")
        expected_set = hashlib.sha256(
            canonical_json(
                [
                    {"path": path, "source_sha256": digest}
                    for path, digest in sorted(
                        {(record.path, record.source_sha256) for record in self.records}
                    )
                ]
            ).encode("ascii")
        ).hexdigest()
        if self.anchored_source_set_sha256 != expected_set:
            raise ValueError("anchored source set digest is invalid")

    def _payload(self) -> dict[str, object]:
        return {
            "schema": _REPORT_SCHEMA,
            "source_revision": self.source_revision,
            "classification_digest": self.classification_digest,
            "materialization_digest": self.materialization_digest,
            "origin_report_digest": self.origin_report_digest,
            "attestation_digest": self.attestation_digest,
            "classification_count": self.classification_count,
            "source_anchor_count": self.source_anchor_count,
            "anchored_source_set_sha256": self.anchored_source_set_sha256,
            "records": [record.to_dict() for record in self.records],
            "origin_authenticated": True,
            "source_anchor_semantics_verified": True,
            "semantic_receipts_verified": False,
            "evidence_authenticated": False,
            "gate_report_bound": False,
            "closed": False,
            "scope": "repository-write-source-anchor-semantics",
            "blockers": [
                "effect-lease-semantic-verification-missing",
                "gate-report-binding-missing",
                "guard-contract-semantic-verification-missing",
                "primary-checkout-disjointness-semantic-verification-missing",
                "retirement-semantic-verification-missing",
                "runtime-conformance-semantic-verification-missing",
            ],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "digest": self.digest}


def verify_repository_write_source_anchor_semantics(
    classification: RepositoryWriteClassificationReport,
    blobs: Mapping[str, bytes],
    attestation: RepositoryWriteEvidenceOriginAttestation,
    *,
    keyring: Mapping[tuple[str, str], bytes | str],
    expected_collector_id: str,
    current_revision: str,
    now: datetime,
    repository_root: Path,
) -> RepositoryWriteSourceAnchorSemanticsReport:
    """Re-authenticate and semantically bind one source anchor per surface."""

    if not isinstance(classification, RepositoryWriteClassificationReport):
        raise RepositoryWriteSourceAnchorSemanticsError(
            "classification report type is invalid"
        )
    revision = _strict_revision(current_revision, "current_revision")
    if classification.source_revision != revision:
        raise RepositoryWriteSourceAnchorBindingError(
            "classification source revision is stale"
        )
    if not classification.classifications:
        raise RepositoryWriteSourceAnchorSemanticsError(
            "source-anchor verification requires classified surfaces"
        )
    materialization = materialize_repository_write_evidence(
        classification,
        blobs,
    )
    origin = verify_repository_write_evidence_origin(
        attestation,
        materialization,
        keyring=keyring,
        expected_collector_id=expected_collector_id,
        current_revision=revision,
        now=now,
    )
    _verify_chain(classification, materialization, origin, attestation)
    root = _resolve_repository_root(repository_root)
    materialized_by_locator = {
        record.locator: record for record in materialization.records
    }
    records: list[SourceAnchorSemanticRecord] = []
    for row in classification.classifications:
        source_bindings = tuple(
            binding
            for binding in row.evidence
            if binding.kind is EvidenceKind.SOURCE_ANCHOR
        )
        if len(source_bindings) != 1:
            raise RepositoryWriteSourceAnchorBindingError(
                "every classification must have exactly one source-anchor binding"
            )
        binding = source_bindings[0]
        if binding.surface_sha256 != surface_binding_sha256(revision, row.surface):
            raise RepositoryWriteSourceAnchorBindingError(
                "source-anchor surface binding is stale"
            )
        record = materialized_by_locator.get(binding.locator)
        if record is None or record.kind is not EvidenceKind.SOURCE_ANCHOR:
            raise RepositoryWriteSourceAnchorBindingError(
                "source-anchor materialization record is missing"
            )
        raw = blobs.get(binding.locator)
        if raw is None:
            raise RepositoryWriteSourceAnchorBindingError(
                "source-anchor blob is missing after materialization"
            )
        payload = _parse_source_anchor_payload(binding, record, raw)
        path = _strict_path(payload["path"], "source anchor path")
        line = _strict_int(payload["line"], "source anchor line")
        column = _strict_int(payload["column"], "source anchor column")
        source_sha256 = _strict_sha(
            payload["source_sha256"],
            "source anchor source_sha256",
        )
        if (
            path != row.surface.path
            or line != row.surface.line
            or column != row.surface.column
        ):
            raise RepositoryWriteSourceAnchorBindingError(
                "source-anchor position differs from the classified surface"
            )
        source = _read_exact_source(root, path)
        if hashlib.sha256(source).hexdigest() != source_sha256:
            raise RepositoryWriteSourceAnchorBindingError(
                "current source bytes differ from the authenticated anchor"
            )
        _verify_byte_position(
            source,
            line=line,
            column=column,
            relative_path=path,
        )
        records.append(
            SourceAnchorSemanticRecord(
                surface_sha256=binding.surface_sha256,
                locator=binding.locator,
                path=path,
                line=line,
                column=column,
                source_sha256=source_sha256,
            )
        )
    canonical_records = tuple(
        sorted(records, key=SourceAnchorSemanticRecord.sort_key)
    )
    anchored_sources = sorted(
        {(record.path, record.source_sha256) for record in canonical_records}
    )
    anchored_source_set_sha256 = hashlib.sha256(
        canonical_json(
            [
                {"path": path, "source_sha256": digest}
                for path, digest in anchored_sources
            ]
        ).encode("ascii")
    ).hexdigest()
    return RepositoryWriteSourceAnchorSemanticsReport(
        source_revision=revision,
        classification_digest=classification.digest,
        materialization_digest=materialization.digest,
        origin_report_digest=origin.digest,
        attestation_digest=attestation.digest,
        classification_count=len(classification.classifications),
        source_anchor_count=len(canonical_records),
        anchored_source_set_sha256=anchored_source_set_sha256,
        records=canonical_records,
    )


def _verify_chain(
    classification: RepositoryWriteClassificationReport,
    materialization: RepositoryWriteEvidenceMaterializationReport,
    origin: RepositoryWriteEvidenceOriginReport,
    attestation: RepositoryWriteEvidenceOriginAttestation,
) -> None:
    comparisons = {
        "classification_digest": (
            classification.digest,
            materialization.classification_digest,
        ),
        "materialization_digest": (
            materialization.digest,
            origin.materialization_digest,
        ),
        "origin_classification_digest": (
            origin.classification_digest,
            classification.digest,
        ),
        "attestation_digest": (
            origin.attestation_digest,
            attestation.digest,
        ),
        "source_revision": (
            origin.source_revision,
            classification.source_revision,
        ),
        "binding_count": (
            origin.binding_count,
            materialization.binding_count,
        ),
    }
    mismatches = sorted(
        name
        for name, (actual, expected) in comparisons.items()
        if actual != expected
    )
    if mismatches:
        raise RepositoryWriteSourceAnchorBindingError(
            "authenticated source-anchor chain mismatch: " + ", ".join(mismatches)
        )


__all__ = [
    "RepositoryWriteSourceAnchorBindingError",
    "RepositoryWriteSourceAnchorSemanticsError",
    "RepositoryWriteSourceAnchorSemanticsReport",
    "RepositoryWriteSourceAnchorTreeError",
    "SourceAnchorSemanticRecord",
    "verify_repository_write_source_anchor_semantics",
]
