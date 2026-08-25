"""Retained terminal result of the repository-write verifier chain.

Building this artifact runs the six typed verifiers from raw inputs. Loading it
only validates retained canonical bytes; it cannot mint evidence or close a
Gate.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from daedalus.spine.envelope import canonical_json

from .repository_write_classification import (
    CLASSIFICATION_SCHEMA,
    STAGE_VERDICT_ABSENT,
    STAGE_VERDICT_NOT_APPLICABLE,
    STAGE_VERDICT_VERIFIED,
    AuthenticationStage,
    NonRuntimeConformityBinding,
    RepositoryWriteAuthenticationInputs,
    RepositoryWriteClassificationReport,
    SurfaceEvidenceAuthentication,
    _compose_authenticated_surfaces,
    _run_stage_verifiers,
    authenticated_over_stages,
    surface_binding_sha256,
    surface_classification_verdict,
)

CHAIN_RESULT_SCHEMA = "daedalus-gate0-repository-write-chain-result/1"
_MAX_BYTES = 16 * 1024 * 1024
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_STAGE_NAMES = tuple(sorted(stage.value for stage in AuthenticationStage))
_VERDICTS = {
    STAGE_VERDICT_ABSENT,
    STAGE_VERDICT_NOT_APPLICABLE,
    STAGE_VERDICT_VERIFIED,
}


class RepositoryWriteChainResultError(ValueError):
    """The chain result is malformed, stale, foreign, or non-canonical."""


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(k, str) for k in value):
        raise RepositoryWriteChainResultError(f"{label} must be an object")
    return value


def _list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise RepositoryWriteChainResultError(f"{label} must be an array")
    return value


def _string(value: object, label: str, *, empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 4000
        or "\n" in value
        or "\r" in value
    ):
        raise RepositoryWriteChainResultError(f"{label} must be a bounded string")
    if not empty and not value:
        raise RepositoryWriteChainResultError(f"{label} must not be empty")
    return value


def _integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise RepositoryWriteChainResultError(
            f"{label} must be a non-negative integer"
        )
    return value


def _exact(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        raise RepositoryWriteChainResultError(f"{label} fields are not exact")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RepositoryWriteChainResultError(f"duplicate key: {key}")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise RepositoryWriteChainResultError(f"non-finite constant: {value}")


@dataclass(frozen=True)
class RepositoryWriteChainSurface:
    source_revision: str
    surface_sha256: str
    path: str
    line: int
    column: int
    origin: str
    classification_verdict: str
    candidate_blockers: tuple[str, ...]
    applicable: tuple[str, ...]
    stages: tuple[tuple[str, str], ...]
    not_applicable_binding: str = ""

    def __post_init__(self) -> None:
        if not _REVISION.fullmatch(self.source_revision):
            raise RepositoryWriteChainResultError("invalid surface revision")
        if not _SHA256.fullmatch(self.surface_sha256):
            raise RepositoryWriteChainResultError("invalid surface digest")
        _string(self.path, "path")
        _integer(self.line, "line")
        _integer(self.column, "column")
        _string(self.origin, "origin")
        _string(self.classification_verdict, "classification_verdict")
        if self.candidate_blockers != tuple(sorted(set(self.candidate_blockers))):
            raise RepositoryWriteChainResultError(
                "candidate blockers must be sorted and unique"
            )
        for blocker in self.candidate_blockers:
            _string(blocker, "candidate blocker")
        prefix = "blocked:" if self.candidate_blockers else "cleared:"
        if not self.classification_verdict.startswith(prefix):
            raise RepositoryWriteChainResultError(
                "classification verdict contradicts candidate blockers"
            )
        if self.applicable != tuple(sorted(set(self.applicable))):
            raise RepositoryWriteChainResultError(
                "applicable stages must be sorted and unique"
            )
        if any(name not in _STAGE_NAMES for name in self.applicable):
            raise RepositoryWriteChainResultError("unknown applicable stage")
        if tuple(name for name, _ in self.stages) != _STAGE_NAMES:
            raise RepositoryWriteChainResultError(
                "stage verdicts must name every stage exactly once"
            )
        if any(verdict not in _VERDICTS for _, verdict in self.stages):
            raise RepositoryWriteChainResultError("unknown stage verdict")
        applicable = set(self.applicable)
        for name, verdict in self.stages:
            if (name in applicable) == (verdict == STAGE_VERDICT_NOT_APPLICABLE):
                raise RepositoryWriteChainResultError(
                    "stage applicability contradicts its verdict"
                )
        conformity = dict(self.stages)[AuthenticationStage.CONFORMITY.value]
        if conformity == STAGE_VERDICT_NOT_APPLICABLE:
            _string(
                self.not_applicable_binding,
                "not_applicable_binding",
            )
        elif self.not_applicable_binding:
            raise RepositoryWriteChainResultError(
                "only conformity may carry a not-applicable binding"
            )

    @property
    def authenticated(self) -> bool:
        applicable = frozenset(AuthenticationStage(name) for name in self.applicable)
        verdicts = {
            AuthenticationStage(name): verdict for name, verdict in self.stages
        }
        return not self.candidate_blockers and authenticated_over_stages(
            applicable, verdicts
        )

    def sort_key(self) -> tuple[str, int, int, str, str]:
        return self.path, self.line, self.column, self.origin, self.surface_sha256

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_revision": self.source_revision,
            "surface_sha256": self.surface_sha256,
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "origin": self.origin,
            "classification_verdict": self.classification_verdict,
            "candidate_blockers": list(self.candidate_blockers),
            "applicable": list(self.applicable),
            "stages": dict(self.stages),
            "not_applicable_binding": self.not_applicable_binding,
            "authenticated": self.authenticated,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RepositoryWriteChainSurface":
        _exact(
            value,
            {
                "source_revision",
                "surface_sha256",
                "path",
                "line",
                "column",
                "origin",
                "classification_verdict",
                "candidate_blockers",
                "applicable",
                "stages",
                "not_applicable_binding",
                "authenticated",
            },
            "chain surface",
        )
        stages = _mapping(value["stages"], "stages")
        if set(stages) != set(_STAGE_NAMES):
            raise RepositoryWriteChainResultError("stage fields are not exact")
        result = cls(
            source_revision=_string(value["source_revision"], "source_revision"),
            surface_sha256=_string(value["surface_sha256"], "surface_sha256"),
            path=_string(value["path"], "path"),
            line=_integer(value["line"], "line"),
            column=_integer(value["column"], "column"),
            origin=_string(value["origin"], "origin"),
            classification_verdict=_string(
                value["classification_verdict"], "classification_verdict"
            ),
            candidate_blockers=tuple(
                _string(item, "candidate blocker")
                for item in _list(value["candidate_blockers"], "candidate_blockers")
            ),
            applicable=tuple(
                _string(item, "applicable stage")
                for item in _list(value["applicable"], "applicable")
            ),
            stages=tuple(
                (name, _string(stages[name], f"stage {name}"))
                for name in _STAGE_NAMES
            ),
            not_applicable_binding=_string(
                value["not_applicable_binding"],
                "not_applicable_binding",
                empty=True,
            ),
        )
        if type(value["authenticated"]) is not bool:
            raise RepositoryWriteChainResultError("authenticated must be a boolean")
        if value["authenticated"] != result.authenticated:
            raise RepositoryWriteChainResultError("authenticated is not derived")
        return result


@dataclass(frozen=True)
class RepositoryWriteChainResult:
    source_revision: str
    inventory_digest: str
    classification_digest: str
    classification_schema: str
    inventory_surface_count: int
    missing_surface_count: int
    stage_digests: tuple[tuple[str, str], ...]
    surfaces: tuple[RepositoryWriteChainSurface, ...]

    def __post_init__(self) -> None:
        if not _REVISION.fullmatch(self.source_revision):
            raise RepositoryWriteChainResultError("invalid source revision")
        if not _SHA256.fullmatch(self.inventory_digest):
            raise RepositoryWriteChainResultError("invalid inventory digest")
        if not _SHA256.fullmatch(self.classification_digest):
            raise RepositoryWriteChainResultError("invalid classification digest")
        if self.classification_schema != CLASSIFICATION_SCHEMA:
            raise RepositoryWriteChainResultError("unsupported classification schema")
        _integer(self.inventory_surface_count, "inventory_surface_count")
        _integer(self.missing_surface_count, "missing_surface_count")
        if tuple(name for name, _ in self.stage_digests) != _STAGE_NAMES:
            raise RepositoryWriteChainResultError(
                "stage digests must name every stage exactly once"
            )
        if any(not _SHA256.fullmatch(digest) for _, digest in self.stage_digests):
            raise RepositoryWriteChainResultError("invalid stage digest")
        ordered = tuple(sorted(self.surfaces, key=RepositoryWriteChainSurface.sort_key))
        if self.surfaces != ordered:
            raise RepositoryWriteChainResultError("surfaces must be sorted")
        if len({row.surface_sha256 for row in self.surfaces}) != len(self.surfaces):
            raise RepositoryWriteChainResultError("surface records must be unique")
        if any(row.source_revision != self.source_revision for row in self.surfaces):
            raise RepositoryWriteChainResultError("surface revision mismatch")
        if (
            len(self.surfaces) + self.missing_surface_count
            != self.inventory_surface_count
        ):
            raise RepositoryWriteChainResultError("inventory surface count mismatch")

    @property
    def applicable_surface_count(self) -> int:
        return sum(bool(row.applicable) for row in self.surfaces)

    @property
    def authenticated_surface_count(self) -> int:
        return sum(row.authenticated for row in self.surfaces)

    @property
    def evidence_authenticated(self) -> bool:
        return bool(self.surfaces) and not self.missing_surface_count and all(
            row.authenticated for row in self.surfaces
        )

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": CHAIN_RESULT_SCHEMA,
            "source_revision": self.source_revision,
            "inventory_digest": self.inventory_digest,
            "classification_digest": self.classification_digest,
            "classification_schema": self.classification_schema,
            "inventory_surface_count": self.inventory_surface_count,
            "classified_surface_count": len(self.surfaces),
            "missing_surface_count": self.missing_surface_count,
            "stage_digests": dict(self.stage_digests),
            "surfaces": [row.to_dict() for row in self.surfaces],
            "applicable_surface_count": self.applicable_surface_count,
            "authenticated_surface_count": self.authenticated_surface_count,
            "evidence_authenticated": self.evidence_authenticated,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "digest": self.digest}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "RepositoryWriteChainResult":
        _exact(
            value,
            {
                "schema",
                "source_revision",
                "inventory_digest",
                "classification_digest",
                "classification_schema",
                "inventory_surface_count",
                "classified_surface_count",
                "missing_surface_count",
                "stage_digests",
                "surfaces",
                "applicable_surface_count",
                "authenticated_surface_count",
                "evidence_authenticated",
                "digest",
            },
            "chain result",
        )
        if value["schema"] != CHAIN_RESULT_SCHEMA:
            raise RepositoryWriteChainResultError("unsupported chain-result schema")
        stage_digests = _mapping(value["stage_digests"], "stage_digests")
        if set(stage_digests) != set(_STAGE_NAMES):
            raise RepositoryWriteChainResultError("stage digest fields are not exact")
        result = cls(
            source_revision=_string(value["source_revision"], "source_revision"),
            inventory_digest=_string(value["inventory_digest"], "inventory_digest"),
            classification_digest=_string(
                value["classification_digest"], "classification_digest"
            ),
            classification_schema=_string(
                value["classification_schema"], "classification_schema"
            ),
            inventory_surface_count=_integer(
                value["inventory_surface_count"], "inventory_surface_count"
            ),
            missing_surface_count=_integer(
                value["missing_surface_count"], "missing_surface_count"
            ),
            stage_digests=tuple(
                (name, _string(stage_digests[name], f"stage digest {name}"))
                for name in _STAGE_NAMES
            ),
            surfaces=tuple(
                RepositoryWriteChainSurface.from_dict(_mapping(item, "surface"))
                for item in _list(value["surfaces"], "surfaces")
            ),
        )
        if dict(value) != result.to_dict():
            raise RepositoryWriteChainResultError("chain result is non-canonical")
        return result


def _chain_surface(
    row: Any,
    auth: SurfaceEvidenceAuthentication,
) -> RepositoryWriteChainSurface:
    digest = surface_binding_sha256(row.source_revision, row.surface)
    identity = (auth.path, auth.line, auth.column, auth.origin)
    expected = (
        row.surface.path,
        row.surface.line,
        row.surface.column,
        row.surface.origin,
    )
    if auth.source_revision != row.source_revision or auth.surface_sha256 != digest:
        raise RepositoryWriteChainResultError("authentication binding mismatch")
    if identity != expected:
        raise RepositoryWriteChainResultError("authentication identity mismatch")
    binding = auth.not_applicable_binding
    admission = getattr(row, "non_runtime_conformity", None)
    if not binding and admission is not None:
        binding = admission.execution_id
    return RepositoryWriteChainSurface(
        source_revision=row.source_revision,
        surface_sha256=digest,
        path=row.surface.path,
        line=row.surface.line,
        column=row.surface.column,
        origin=row.surface.origin,
        classification_verdict=surface_classification_verdict(row),
        candidate_blockers=tuple(sorted(set(row.candidate_blockers))),
        applicable=tuple(sorted(stage.value for stage in auth.applicable)),
        stages=tuple(auth.verdicts),
        not_applicable_binding=binding,
    )


def build_repository_write_chain_result(
    report: RepositoryWriteClassificationReport,
    *,
    inputs: RepositoryWriteAuthenticationInputs,
    non_runtime_bindings: Iterable[NonRuntimeConformityBinding] = (),
    collector_secrets: Mapping[str, bytes | str] | None = None,
) -> RepositoryWriteChainResult:
    """Run all six verifiers and retain their exact composition."""

    if type(report) is not RepositoryWriteClassificationReport:
        raise RepositoryWriteChainResultError(
            "an exact classification report is required"
        )
    reports = _run_stage_verifiers(report, inputs)
    if set(reports) != set(AuthenticationStage):
        raise RepositoryWriteChainResultError("all six stage reports are required")
    authentications = _compose_authenticated_surfaces(
        report,
        reports,
        non_runtime_bindings=non_runtime_bindings,
        collector_secrets=collector_secrets,
    )
    surfaces = []
    for row in report.classifications:
        auth = authentications.get(row.surface)
        if type(auth) is not SurfaceEvidenceAuthentication:
            raise RepositoryWriteChainResultError(
                "a classified surface has no exact authentication record"
            )
        surfaces.append(_chain_surface(row, auth))
    return RepositoryWriteChainResult(
        source_revision=report.source_revision,
        inventory_digest=report.inventory_digest,
        classification_digest=report.digest,
        classification_schema=CLASSIFICATION_SCHEMA,
        inventory_surface_count=report.inventory_surface_count,
        missing_surface_count=len(report.missing_surfaces),
        stage_digests=tuple(
            sorted(
                (
                    stage.value,
                    _string(getattr(reports[stage], "digest", None), "stage digest"),
                )
                for stage in AuthenticationStage
            )
        ),
        surfaces=tuple(sorted(surfaces, key=RepositoryWriteChainSurface.sort_key)),
    )


def load_repository_write_chain_result(path: str | Path) -> RepositoryWriteChainResult:
    """Strictly load one retained chain-result artifact."""

    try:
        raw = Path(path).read_bytes()
    except (OSError, TypeError) as exc:
        raise RepositoryWriteChainResultError("chain result could not be read") from exc
    if len(raw) > _MAX_BYTES:
        raise RepositoryWriteChainResultError("chain result exceeds maximum size")
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_constant=_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RepositoryWriteChainResultError("chain result is malformed JSON") from exc
    return RepositoryWriteChainResult.from_dict(_mapping(payload, "chain result"))


__all__ = [
    "CHAIN_RESULT_SCHEMA",
    "RepositoryWriteChainResult",
    "RepositoryWriteChainResultError",
    "RepositoryWriteChainSurface",
    "build_repository_write_chain_result",
    "load_repository_write_chain_result",
]
