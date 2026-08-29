"""Canonical sidecar reconstruction for signed non-runtime conformity.

A classification declaration must not be able to mint ``not_applicable`` by
writing a boolean or execution id.  At the same time, the in-process
``SurfaceClassification.non_runtime_conformity`` admission must be
reconstructible across process/artifact boundaries.

This module provides that bridge without changing the classification-input
wire.  The declaration row still has the same eight fields.  A central row may
omit its runtime-conformance receipt only when a separately transported,
collector-signed ``NonRuntimeConformityBinding`` exists for that exact surface
and the retained execution is replayed successfully *before* the typed row is
constructed.

The binding-set envelope is content-addressable transport only.  Authority
comes from each member's collector signature plus ``NonRuntimeConformityAdmission``
replay, never from the envelope digest itself.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from daedalus.spine.envelope import canonical_json

from .repository_write_classification import (
    CLASSIFICATION_INPUT_SCHEMA,
    EvidenceBinding,
    GuardDisposition,
    NonRuntimeConformityAdmission,
    NonRuntimeConformityBinding,
    RepositoryWriteClassificationError,
    RepositoryWriteClassificationReport,
    SurfaceClassification,
    TargetDisposition,
    project_repository_write_classifications,
    surface_binding_sha256,
)
from .repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)


BINDING_SET_SCHEMA = "daedalus-gate0-non-runtime-conformity-binding-set/1"
_MAX_BINDING_SET_BYTES = 2 * 1024 * 1024
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RepositoryWriteNonRuntimeSidecarError(RepositoryWriteClassificationError):
    """The non-runtime sidecar or sidecar-aware projection is invalid."""


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RepositoryWriteNonRuntimeSidecarError(
                "non-runtime binding set contains duplicate JSON keys"
            )
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise RepositoryWriteNonRuntimeSidecarError(
        f"non-runtime binding set contains forbidden JSON constant {value}"
    )


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(
        not isinstance(key, str) for key in value
    ):
        raise RepositoryWriteNonRuntimeSidecarError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise RepositoryWriteNonRuntimeSidecarError(f"{label} must be an array")
    return value


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise RepositoryWriteNonRuntimeSidecarError(f"{label} must be text")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int:
        raise RepositoryWriteNonRuntimeSidecarError(f"{label} must be an integer")
    return value


def _boolean(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise RepositoryWriteNonRuntimeSidecarError(f"{label} must be a boolean")
    return value


def _exact_keys(
    value: Mapping[str, object], required: set[str], label: str
) -> None:
    if set(value) != required:
        raise RepositoryWriteNonRuntimeSidecarError(f"{label} keys are invalid")


def _binding_from_dict(value: Mapping[str, object]) -> NonRuntimeConformityBinding:
    _exact_keys(
        value,
        {
            "schema",
            "source_revision",
            "surface_sha256",
            "execution_id",
            "authorization_class",
            "collector_id",
            "collector_key_id",
            "issued_at",
            "signature_sha256",
        },
        "non-runtime conformity binding",
    )
    if value.get("schema") != "daedalus-gate0-non-runtime-conformity-binding/1":
        raise RepositoryWriteNonRuntimeSidecarError(
            "non-runtime conformity binding schema is unsupported"
        )
    try:
        return NonRuntimeConformityBinding(
            source_revision=_string(value["source_revision"], "binding revision"),
            surface_sha256=_string(value["surface_sha256"], "binding surface"),
            execution_id=_string(value["execution_id"], "binding execution"),
            authorization_class=_string(
                value["authorization_class"], "binding authorization class"
            ),
            collector_id=_string(value["collector_id"], "binding collector"),
            collector_key_id=_string(
                value["collector_key_id"], "binding collector key"
            ),
            issued_at=_string(value["issued_at"], "binding issue time"),
            signature_sha256=_string(
                value["signature_sha256"], "binding signature"
            ),
        )
    except (TypeError, ValueError) as exc:
        raise RepositoryWriteNonRuntimeSidecarError(
            "non-runtime conformity binding is malformed"
        ) from exc


def _binding_sort_key(
    binding: NonRuntimeConformityBinding,
) -> tuple[str, str, str, str, str, str]:
    return (
        binding.surface_sha256,
        binding.execution_id,
        binding.collector_id,
        binding.collector_key_id,
        binding.issued_at,
        binding.signature_sha256,
    )


@dataclass(frozen=True)
class RepositoryWriteNonRuntimeBindingSet:
    """Canonical transport for independently signed non-runtime bindings."""

    source_revision: str
    inventory_digest: str
    bindings: tuple[NonRuntimeConformityBinding, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source_revision, str) or not _REVISION.fullmatch(
            self.source_revision
        ):
            raise RepositoryWriteNonRuntimeSidecarError(
                "binding-set source_revision must be lowercase 40-hex"
            )
        if not isinstance(self.inventory_digest, str) or not _SHA256.fullmatch(
            self.inventory_digest
        ):
            raise RepositoryWriteNonRuntimeSidecarError(
                "binding-set inventory_digest must be lowercase sha256"
            )
        if not isinstance(self.bindings, tuple):
            raise RepositoryWriteNonRuntimeSidecarError(
                "binding-set bindings must be an immutable tuple"
            )
        if any(type(item) is not NonRuntimeConformityBinding for item in self.bindings):
            raise RepositoryWriteNonRuntimeSidecarError(
                "binding-set members must be exact typed bindings"
            )
        if tuple(sorted(self.bindings, key=_binding_sort_key)) != self.bindings:
            raise RepositoryWriteNonRuntimeSidecarError(
                "binding-set members must be canonically sorted"
            )
        if len({item.surface_sha256 for item in self.bindings}) != len(self.bindings):
            raise RepositoryWriteNonRuntimeSidecarError(
                "binding-set contains duplicate surface bindings"
            )
        if any(item.source_revision != self.source_revision for item in self.bindings):
            raise RepositoryWriteNonRuntimeSidecarError(
                "binding-set member revision differs from envelope revision"
            )

    def _payload(self) -> dict[str, object]:
        return {
            "schema": BINDING_SET_SCHEMA,
            "source_revision": self.source_revision,
            "inventory_digest": self.inventory_digest,
            "binding_count": len(self.bindings),
            "bindings": [item.to_dict() for item in self.bindings],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {**self._payload(), "digest": self.digest}

    @classmethod
    def from_dict(
        cls, value: Mapping[str, object]
    ) -> "RepositoryWriteNonRuntimeBindingSet":
        document = _mapping(value, "non-runtime binding set")
        _exact_keys(
            document,
            {
                "schema",
                "source_revision",
                "inventory_digest",
                "binding_count",
                "bindings",
                "digest",
            },
            "non-runtime binding set",
        )
        if document.get("schema") != BINDING_SET_SCHEMA:
            raise RepositoryWriteNonRuntimeSidecarError(
                "non-runtime binding-set schema is unsupported"
            )
        bindings = tuple(
            sorted(
                (
                    _binding_from_dict(
                        _mapping(item, "non-runtime conformity binding")
                    )
                    for item in _list(document["bindings"], "bindings")
                ),
                key=_binding_sort_key,
            )
        )
        count = _integer(document["binding_count"], "binding_count")
        if count != len(bindings):
            raise RepositoryWriteNonRuntimeSidecarError(
                "non-runtime binding-set count is inconsistent"
            )
        instance = cls(
            source_revision=_string(
                document["source_revision"], "binding-set source_revision"
            ),
            inventory_digest=_string(
                document["inventory_digest"], "binding-set inventory_digest"
            ),
            bindings=bindings,
        )
        claimed = _string(document["digest"], "binding-set digest")
        if not _SHA256.fullmatch(claimed) or claimed != instance.digest:
            raise RepositoryWriteNonRuntimeSidecarError(
                "non-runtime binding-set digest mismatch"
            )
        if dict(document) != instance.to_dict():
            raise RepositoryWriteNonRuntimeSidecarError(
                "non-runtime binding set is non-canonical"
            )
        return instance


def load_repository_write_non_runtime_binding_set(
    path: str | Path,
) -> RepositoryWriteNonRuntimeBindingSet:
    """Load one bounded, duplicate-key-free, byte-canonical binding set."""

    try:
        raw = Path(path).read_bytes()
    except (OSError, TypeError) as exc:
        raise RepositoryWriteNonRuntimeSidecarError(
            "non-runtime binding set could not be read"
        ) from exc
    if len(raw) > _MAX_BINDING_SET_BYTES:
        raise RepositoryWriteNonRuntimeSidecarError(
            "non-runtime binding set exceeds maximum size"
        )
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_constant,
        )
    except UnicodeDecodeError as exc:
        raise RepositoryWriteNonRuntimeSidecarError(
            "non-runtime binding set must be UTF-8"
        ) from exc
    except (json.JSONDecodeError, RecursionError) as exc:
        raise RepositoryWriteNonRuntimeSidecarError(
            "non-runtime binding set is malformed JSON"
        ) from exc
    instance = RepositoryWriteNonRuntimeBindingSet.from_dict(
        _mapping(payload, "non-runtime binding set")
    )
    canonical = canonical_json(instance.to_dict()).encode("ascii")
    if raw != canonical:
        raise RepositoryWriteNonRuntimeSidecarError(
            "non-runtime binding-set bytes are non-canonical"
        )
    return instance


def _surface_from_input(value: Mapping[str, object]) -> RepositoryWriteSurface:
    _exact_keys(
        value,
        {
            "path",
            "line",
            "column",
            "origin",
            "kind",
            "callee",
            "operation",
            "blocking",
        },
        "repository write surface",
    )
    try:
        return RepositoryWriteSurface(
            path=_string(value["path"], "surface path"),
            line=_integer(value["line"], "surface line"),
            column=_integer(value["column"], "surface column"),
            origin=_string(value["origin"], "surface origin"),
            kind=_string(value["kind"], "surface kind"),
            callee=_string(value["callee"], "surface callee"),
            operation=_string(value["operation"], "surface operation"),
            blocking=_boolean(value["blocking"], "surface blocking"),
        )
    except (TypeError, ValueError) as exc:
        raise RepositoryWriteNonRuntimeSidecarError(
            "repository write surface is invalid"
        ) from exc


def _row_surface_identity(value: Mapping[str, object]) -> tuple[str, RepositoryWriteSurface]:
    _exact_keys(
        value,
        {
            "source_revision",
            "surface",
            "target",
            "guard",
            "production_reachable",
            "guard_contracts",
            "evidence",
            "notes",
        },
        "surface classification",
    )
    revision = _string(value["source_revision"], "classification source_revision")
    surface = _surface_from_input(_mapping(value["surface"], "surface"))
    return revision, surface


def _row_with_admission(
    value: Mapping[str, object],
    admission: NonRuntimeConformityAdmission,
) -> SurfaceClassification:
    revision, surface = _row_surface_identity(value)
    contracts = tuple(
        _string(item, "guard contract")
        for item in _list(value["guard_contracts"], "guard_contracts")
    )
    evidence = tuple(
        EvidenceBinding.from_dict(_mapping(item, "evidence binding"))
        for item in _list(value["evidence"], "evidence")
    )
    try:
        target = TargetDisposition(_string(value["target"], "target disposition"))
        guard = GuardDisposition(_string(value["guard"], "guard disposition"))
        return SurfaceClassification(
            source_revision=revision,
            surface=surface,
            target=target,
            guard=guard,
            production_reachable=_boolean(
                value["production_reachable"], "production_reachable"
            ),
            guard_contracts=contracts,
            evidence=evidence,
            notes=_string(value["notes"], "classification notes"),
            non_runtime_conformity=admission,
        )
    except (TypeError, ValueError) as exc:
        raise RepositoryWriteNonRuntimeSidecarError(
            "sidecar-admitted surface classification is invalid"
        ) from exc


def project_classification_input_with_non_runtime_sidecar(
    inventory: RepositoryWriteInventoryV2,
    value: Mapping[str, object],
    binding_set: RepositoryWriteNonRuntimeBindingSet,
    *,
    subjects: Mapping[str, object],
    collector_secrets: Mapping[str, bytes | str],
) -> RepositoryWriteClassificationReport:
    """Project a classification document after signed non-runtime replay.

    Rows without a sidecar binding go through the existing strict
    ``SurfaceClassification.from_dict`` path unchanged.  A row with a binding
    is parsed in two phases so the verified admission exists before the row's
    central evidence-kind invariant is evaluated.
    """

    if type(inventory) is not RepositoryWriteInventoryV2:
        raise RepositoryWriteNonRuntimeSidecarError(
            "sidecar projection requires exact inventory-v2"
        )
    if type(binding_set) is not RepositoryWriteNonRuntimeBindingSet:
        raise RepositoryWriteNonRuntimeSidecarError(
            "sidecar projection requires exact binding-set type"
        )
    document = _mapping(value, "classification input")
    _exact_keys(
        document,
        {"schema", "source_revision", "inventory_digest", "classifications"},
        "classification input",
    )
    if document.get("schema") != CLASSIFICATION_INPUT_SCHEMA:
        raise RepositoryWriteNonRuntimeSidecarError(
            "classification input schema is unsupported"
        )
    if document.get("source_revision") != inventory.source_revision:
        raise RepositoryWriteNonRuntimeSidecarError(
            "classification input source revision is stale"
        )
    if document.get("inventory_digest") != inventory.digest:
        raise RepositoryWriteNonRuntimeSidecarError(
            "classification input inventory digest is stale"
        )
    if binding_set.source_revision != inventory.source_revision:
        raise RepositoryWriteNonRuntimeSidecarError(
            "non-runtime binding set names another source revision"
        )
    if binding_set.inventory_digest != inventory.digest:
        raise RepositoryWriteNonRuntimeSidecarError(
            "non-runtime binding set names another inventory"
        )
    if not isinstance(subjects, Mapping):
        raise RepositoryWriteNonRuntimeSidecarError(
            "non-runtime subjects must be a mapping"
        )
    if not isinstance(collector_secrets, Mapping):
        raise RepositoryWriteNonRuntimeSidecarError(
            "collector secrets must be a mapping"
        )

    by_surface = {item.surface_sha256: item for item in binding_set.bindings}
    consumed: set[str] = set()
    rows: list[SurfaceClassification] = []
    for raw_item in _list(document["classifications"], "classifications"):
        item = _mapping(raw_item, "surface classification")
        revision, surface = _row_surface_identity(item)
        try:
            surface_sha256 = surface_binding_sha256(revision, surface)
        except ValueError as exc:
            raise RepositoryWriteNonRuntimeSidecarError(
                "classification surface identity is invalid"
            ) from exc
        binding = by_surface.get(surface_sha256)
        if binding is None:
            rows.append(SurfaceClassification.from_dict(item))
            continue
        if surface_sha256 in consumed:
            raise RepositoryWriteNonRuntimeSidecarError(
                "classification repeats a sidecar-bound surface"
            )
        subject = subjects.get(binding.execution_id)
        if subject is None:
            raise RepositoryWriteNonRuntimeSidecarError(
                "non-runtime binding has no retained execution subject"
            )
        try:
            admission = NonRuntimeConformityAdmission(
                binding=binding,
                subject=subject,
                collector_secrets=collector_secrets,
            )
        except (RepositoryWriteClassificationError, TypeError, ValueError) as exc:
            raise RepositoryWriteNonRuntimeSidecarError(
                "non-runtime binding signature or retained replay was refused"
            ) from exc
        rows.append(_row_with_admission(item, admission))
        consumed.add(surface_sha256)

    unused = sorted(set(by_surface) - consumed)
    if unused:
        raise RepositoryWriteNonRuntimeSidecarError(
            "non-runtime binding set contains a surface absent from classification"
        )
    try:
        return project_repository_write_classifications(inventory, tuple(rows))
    except RepositoryWriteClassificationError as exc:
        raise RepositoryWriteNonRuntimeSidecarError(
            "sidecar-aware classification projection was refused"
        ) from exc


__all__ = [
    "BINDING_SET_SCHEMA",
    "RepositoryWriteNonRuntimeBindingSet",
    "RepositoryWriteNonRuntimeSidecarError",
    "load_repository_write_non_runtime_binding_set",
    "project_classification_input_with_non_runtime_sidecar",
]
