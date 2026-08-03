"""Optional read-only ROOT file metadata extraction through Uproot.

The adapter inventories object classes and TTree/RNTuple field schemas without
reading event payloads. Its output is staged Data-Plane evidence, not an
authoritative Forest publication.

A successful inventory is therefore always ``partial``. It does not establish
payload validity, event-level invariants, semantic type identity, provenance,
or data lineage.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib
from importlib import metadata
import io
from typing import Any, Mapping

from ...spine.envelope import canonical_sha
from .contracts import ExtractorDiagnostic, ExtractorResult, SourceArtifact


class RootReaderUnavailable(RuntimeError):
    """Raised when the optional Uproot dependency is unavailable."""


@dataclass(frozen=True)
class RootReadLimits:
    max_source_bytes: int = 512_000_000
    max_objects: int = 100_000
    max_fields_per_object: int = 100_000
    max_total_fields: int = 500_000

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")


DEFAULT_ROOT_READ_LIMITS = RootReadLimits()


@dataclass(frozen=True)
class RootFieldRecord:
    node_id: str
    object_node_id: str
    object_path: str
    name: str
    type_name: str
    evidence_sha256: str
    relation_sha256: str


@dataclass(frozen=True)
class RootObjectRecord:
    node_id: str
    object_path: str
    classname: str
    kind: str
    evidence_sha256: str
    fields: tuple[RootFieldRecord, ...] = ()


@dataclass(frozen=True)
class RootDataReport:
    artifact: SourceArtifact
    objects: tuple[RootObjectRecord, ...]
    total_fields: int
    report_sha256: str
    result: ExtractorResult


def _load_uproot():
    try:
        uproot = importlib.import_module("uproot")
    except ImportError as exc:
        raise RootReaderUnavailable("optional uproot dependency is missing") from exc
    try:
        version = f"uproot={metadata.version('uproot')}"
    except metadata.PackageNotFoundError:
        version = "uproot=unknown"
    return uproot, version


def _object_kind(classname: str) -> str:
    if classname == "ROOT::RNTuple" or "RNTuple" in classname:
        return "rntuple"
    if "TTree" in classname:
        return "tree"
    if classname.startswith(("TH1", "TH2", "TH3", "TProfile")):
        return "histogram"
    if "TDirectory" in classname:
        return "directory"
    return "object"


def _failed_report(
    artifact: SourceArtifact,
    *,
    version: str,
    source_bundle_sha256: str,
    code: str,
    message: str,
) -> RootDataReport:
    diagnostic = ExtractorDiagnostic(code, "error", message, artifact.path)
    result = ExtractorResult(
        extractor_id="uproot-root-file",
        extractor_version=version,
        source_revision=artifact.source_revision,
        source_bundle_sha256=source_bundle_sha256,
        status="failed",
        diagnostics=(diagnostic,),
    )
    report_sha = canonical_sha({
        "schema": "daedalus-root-data-report/1",
        "artifact_sha256": artifact.content_sha256,
        "status": "failed",
        "diagnostic": code,
    })
    return RootDataReport(artifact, (), 0, report_sha, result)


def inspect_root_artifact(
    artifact: SourceArtifact,
    content: bytes,
    *,
    source_bundle_sha256: str,
    limits: RootReadLimits = DEFAULT_ROOT_READ_LIMITS,
) -> RootDataReport:
    """Inventory one immutable ROOT file as metadata-only partial evidence."""

    if not isinstance(artifact, SourceArtifact):
        raise ValueError("artifact must be a SourceArtifact")
    if artifact.language_id != "root-binary" or artifact.artifact_kind != "binary":
        raise ValueError("artifact must be a root-binary binary SourceArtifact")
    if not isinstance(content, bytes):
        raise ValueError("content must be bytes")
    if hashlib.sha256(content).hexdigest() != artifact.content_sha256:
        raise ValueError("content does not match artifact.content_sha256")
    if len(content) != artifact.size_bytes:
        raise ValueError("content length does not match artifact.size_bytes")
    if not isinstance(limits, RootReadLimits):
        raise ValueError("limits must be a RootReadLimits record")

    uproot, version = _load_uproot()
    if len(content) > limits.max_source_bytes:
        return _failed_report(
            artifact,
            version=version,
            source_bundle_sha256=source_bundle_sha256,
            code="root-file-too-large",
            message=(
                f"ROOT file exceeds metadata-reader byte limit: "
                f"{len(content)} > {limits.max_source_bytes}"
            ),
        )

    try:
        root_file = uproot.open(
            io.BytesIO(content),
            object_cache=None,
            array_cache=None,
        )
    except Exception as exc:
        return _failed_report(
            artifact,
            version=version,
            source_bundle_sha256=source_bundle_sha256,
            code="root-open-failed",
            message=f"Uproot could not open ROOT metadata: {type(exc).__name__}: {exc}",
        )

    records: list[RootObjectRecord] = []
    diagnostics: list[ExtractorDiagnostic] = []
    total_fields = 0
    relation_digests: list[str] = []
    try:
        try:
            classnames = root_file.classnames(recursive=True, cycle=False)
        except Exception as exc:
            return _failed_report(
                artifact,
                version=version,
                source_bundle_sha256=source_bundle_sha256,
                code="root-metadata-enumeration-failed",
                message=(
                    "Uproot could not enumerate ROOT object metadata: "
                    f"{type(exc).__name__}: {exc}"
                ),
            )
        if len(classnames) > limits.max_objects:
            return _failed_report(
                artifact,
                version=version,
                source_bundle_sha256=source_bundle_sha256,
                code="root-object-limit-exceeded",
                message=(
                    f"ROOT object count exceeds limit: "
                    f"{len(classnames)} > {limits.max_objects}"
                ),
            )

        for object_path, raw_classname in sorted(classnames.items()):
            classname = str(raw_classname)
            kind = _object_kind(classname)
            path_digest = hashlib.sha256(object_path.encode("utf-8")).hexdigest()[:20]
            object_node_id = f"data:root-object:{artifact.path}#{path_digest}"
            object_evidence = canonical_sha({
                "schema": "daedalus-root-object-evidence/1",
                "artifact_sha256": artifact.content_sha256,
                "object_path": object_path,
                "classname": classname,
                "kind": kind,
            })
            fields: list[RootFieldRecord] = []
            if kind in {"tree", "rntuple"}:
                try:
                    obj = root_file[object_path]
                    typenames_method = getattr(obj, "typenames", None)
                    typenames = typenames_method() if callable(typenames_method) else {}
                    if not isinstance(typenames, Mapping):
                        typenames = {}
                    if len(typenames) > limits.max_fields_per_object:
                        return _failed_report(
                            artifact,
                            version=version,
                            source_bundle_sha256=source_bundle_sha256,
                            code="root-field-limit-exceeded",
                            message=(
                                f"ROOT field count exceeds per-object limit for "
                                f"{object_path}: {len(typenames)} > "
                                f"{limits.max_fields_per_object}"
                            ),
                        )
                    for field_name, raw_type_name in sorted(typenames.items()):
                        total_fields += 1
                        if total_fields > limits.max_total_fields:
                            return _failed_report(
                                artifact,
                                version=version,
                                source_bundle_sha256=source_bundle_sha256,
                                code="root-total-field-limit-exceeded",
                                message=(
                                    f"ROOT total field count exceeds limit: "
                                    f"{total_fields} > {limits.max_total_fields}"
                                ),
                            )
                        type_name = str(raw_type_name)
                        field_identity = f"{object_path}\0{field_name}"
                        field_digest = hashlib.sha256(
                            field_identity.encode("utf-8")
                        ).hexdigest()[:20]
                        field_node_id = (
                            f"data:root-field:{artifact.path}#{field_digest}"
                        )
                        field_evidence = canonical_sha({
                            "schema": "daedalus-root-field-evidence/1",
                            "artifact_sha256": artifact.content_sha256,
                            "object_path": object_path,
                            "field_name": field_name,
                            "type_name": type_name,
                        })
                        relation_sha = canonical_sha({
                            "schema": "daedalus-root-relation/1",
                            "source": object_node_id,
                            "target": field_node_id,
                            "relation": "has_field",
                            "evidence_sha256": field_evidence,
                        })
                        relation_digests.append(relation_sha)
                        fields.append(RootFieldRecord(
                            node_id=field_node_id,
                            object_node_id=object_node_id,
                            object_path=object_path,
                            name=str(field_name),
                            type_name=type_name,
                            evidence_sha256=field_evidence,
                            relation_sha256=relation_sha,
                        ))
                except Exception as exc:
                    diagnostics.append(ExtractorDiagnostic(
                        "root-field-metadata-failed",
                        "warning",
                        (
                            f"Could not inspect field metadata for {object_path}: "
                            f"{type(exc).__name__}: {exc}"
                        ),
                        artifact.path,
                    ))
            records.append(RootObjectRecord(
                node_id=object_node_id,
                object_path=str(object_path),
                classname=classname,
                kind=kind,
                evidence_sha256=object_evidence,
                fields=tuple(fields),
            ))
    finally:
        close = getattr(root_file, "close", None)
        if callable(close):
            close()

    diagnostics.append(
        ExtractorDiagnostic(
            "metadata-only",
            "warning",
            (
                "Uproot inventories object and field metadata without reading "
                "event payloads; payload validity, event invariants, semantic "
                "types, provenance, and data lineage remain unverified"
            ),
            artifact.path,
        )
    )
    records_tuple = tuple(records)
    report_sha = canonical_sha({
        "schema": "daedalus-root-data-report/1",
        "artifact_sha256": artifact.content_sha256,
        "objects": [
            {
                "node_id": record.node_id,
                "object_path": record.object_path,
                "classname": record.classname,
                "kind": record.kind,
                "evidence_sha256": record.evidence_sha256,
                "fields": [
                    {
                        "node_id": field.node_id,
                        "name": field.name,
                        "type_name": field.type_name,
                        "evidence_sha256": field.evidence_sha256,
                        "relation_sha256": field.relation_sha256,
                    }
                    for field in record.fields
                ],
            }
            for record in records_tuple
        ],
        "diagnostics": [item.code for item in diagnostics],
    })
    node_ids = tuple(
        node_id
        for record in records_tuple
        for node_id in (record.node_id, *(field.node_id for field in record.fields))
    )
    evidence = {
        artifact.content_sha256,
        report_sha,
        *(record.evidence_sha256 for record in records_tuple),
        *(
            field.evidence_sha256
            for record in records_tuple
            for field in record.fields
        ),
    }
    status = "partial"
    result = ExtractorResult(
        extractor_id="uproot-root-file",
        extractor_version=version,
        source_revision=artifact.source_revision,
        source_bundle_sha256=source_bundle_sha256,
        status=status,
        node_ids=node_ids,
        relation_sha256s=tuple(relation_digests),
        evidence_sha256s=tuple(evidence),
        diagnostics=tuple(diagnostics),
    )
    return RootDataReport(
        artifact=artifact,
        objects=records_tuple,
        total_fields=total_fields,
        report_sha256=report_sha,
        result=result,
    )


__all__ = [
    "DEFAULT_ROOT_READ_LIMITS",
    "RootDataReport",
    "RootFieldRecord",
    "RootObjectRecord",
    "RootReadLimits",
    "RootReaderUnavailable",
    "inspect_root_artifact",
]
