"""Hardened public facade for the retained repository-write verifier chain.

The frozen implementation core remains in
``_repository_write_chain_result_base`` so this facade can tighten artifact
admission without changing the schema or duplicating its typed wire classes.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import _repository_write_chain_result_base as _base
from ._repository_write_chain_result_base import *  # noqa: F401,F403

# These remain module-level seams because the focused contract tests replace
# them with exact typed stage-report fixtures.  Production callers cannot pass
# completed reports through the public builder.
_run_stage_verifiers = _base._run_stage_verifiers
_compose_authenticated_surfaces = _base._compose_authenticated_surfaces
canonical_json = _base.canonical_json


def _chain_surface(
    row: Any,
    auth: _base.SurfaceEvidenceAuthentication,
) -> RepositoryWriteChainSurface:
    """Retain one exact authentication row and reconcile N/A identities."""

    digest = _base.surface_binding_sha256(row.source_revision, row.surface)
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

    admission = getattr(row, "non_runtime_conformity", None)
    admission_binding = "" if admission is None else admission.execution_id
    if (
        auth.not_applicable_binding
        and admission_binding
        and auth.not_applicable_binding != admission_binding
    ):
        raise RepositoryWriteChainResultError(
            "authentication non-runtime binding mismatch"
        )
    binding = auth.not_applicable_binding or admission_binding

    return RepositoryWriteChainSurface(
        source_revision=row.source_revision,
        surface_sha256=digest,
        path=row.surface.path,
        line=row.surface.line,
        column=row.surface.column,
        origin=row.surface.origin,
        classification_verdict=_base.surface_classification_verdict(row),
        candidate_blockers=tuple(sorted(set(row.candidate_blockers))),
        applicable=tuple(sorted(stage.value for stage in auth.applicable)),
        stages=tuple(auth.verdicts),
        not_applicable_binding=binding,
    )


def build_repository_write_chain_result(
    report: _base.RepositoryWriteClassificationReport,
    *,
    inputs: _base.RepositoryWriteAuthenticationInputs,
    non_runtime_bindings: Iterable[_base.NonRuntimeConformityBinding] = (),
    collector_secrets: Mapping[str, bytes | str] | None = None,
) -> RepositoryWriteChainResult:
    """Run all six verifiers and retain their exact composition."""

    if type(report) is not _base.RepositoryWriteClassificationReport:
        raise RepositoryWriteChainResultError(
            "an exact classification report is required"
        )
    reports = _run_stage_verifiers(report, inputs)
    if set(reports) != set(_base.AuthenticationStage):
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
        if type(auth) is not _base.SurfaceEvidenceAuthentication:
            raise RepositoryWriteChainResultError(
                "a classified surface has no exact authentication record"
            )
        surfaces.append(_chain_surface(row, auth))
    return RepositoryWriteChainResult(
        source_revision=report.source_revision,
        inventory_digest=report.inventory_digest,
        classification_digest=report.digest,
        classification_schema=_base.CLASSIFICATION_SCHEMA,
        inventory_surface_count=report.inventory_surface_count,
        missing_surface_count=len(report.missing_surfaces),
        stage_digests=tuple(
            sorted(
                (
                    stage.value,
                    _base._string(
                        getattr(reports[stage], "digest", None),
                        "stage digest",
                    ),
                )
                for stage in _base.AuthenticationStage
            )
        ),
        surfaces=tuple(
            sorted(surfaces, key=RepositoryWriteChainSurface.sort_key)
        ),
    )


def load_repository_write_chain_result(
    path: str | Path,
) -> RepositoryWriteChainResult:
    """Load one semantically and byte-for-byte canonical chain result."""

    try:
        raw = Path(path).read_bytes()
    except (OSError, TypeError) as exc:
        raise RepositoryWriteChainResultError(
            "chain result could not be read"
        ) from exc
    if len(raw) > _base._MAX_BYTES:
        raise RepositoryWriteChainResultError(
            "chain result exceeds maximum size"
        )
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_base._pairs,
            parse_constant=_base._constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RepositoryWriteChainResultError(
            "chain result is malformed JSON"
        ) from exc
    result = RepositoryWriteChainResult.from_dict(
        _base._mapping(payload, "chain result")
    )
    canonical = canonical_json(result.to_dict()).encode("ascii")
    if raw != canonical:
        raise RepositoryWriteChainResultError(
            "chain result bytes are non-canonical"
        )
    return result


__all__ = tuple(_base.__all__)
