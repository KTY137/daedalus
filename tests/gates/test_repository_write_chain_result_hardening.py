"""Hardening tests for canonical bytes and non-runtime identity conflicts."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import daedalus.gates.repository_write_chain_result as chain
from daedalus.gates.repository_write_classification import (
    CLASSIFICATION_SCHEMA,
    STAGE_VERDICT_NOT_APPLICABLE,
    STAGE_VERDICT_VERIFIED,
    AuthenticationStage,
    SurfaceEvidenceAuthentication,
    surface_binding_sha256,
)
from daedalus.gates.repository_write_inventory_v2 import RepositoryWriteSurface
from daedalus.spine.envelope import canonical_json

REVISION = "a" * 40


def _result() -> chain.RepositoryWriteChainResult:
    stages = tuple(
        sorted(
            (stage.value, STAGE_VERDICT_VERIFIED)
            for stage in AuthenticationStage
        )
    )
    surface = chain.RepositoryWriteChainSurface(
        source_revision=REVISION,
        surface_sha256="b" * 64,
        path="daedalus/example.py",
        line=7,
        column=4,
        origin="base_v1",
        classification_verdict="cleared:central",
        candidate_blockers=(),
        applicable=tuple(name for name, _ in stages),
        stages=stages,
    )
    return chain.RepositoryWriteChainResult(
        source_revision=REVISION,
        inventory_digest="c" * 64,
        classification_digest="d" * 64,
        classification_schema=CLASSIFICATION_SCHEMA,
        inventory_surface_count=1,
        missing_surface_count=0,
        stage_digests=tuple(
            sorted(
                (stage.value, str(index) * 64)
                for index, stage in enumerate(AuthenticationStage, start=1)
            )
        ),
        surfaces=(surface,),
    )


def test_loader_requires_exact_canonical_bytes(tmp_path: Path) -> None:
    result = _result()
    canonical_path = tmp_path / "canonical.json"
    canonical_path.write_bytes(canonical_json(result.to_dict()).encode("ascii"))
    assert chain.load_repository_write_chain_result(canonical_path) == result

    pretty_path = tmp_path / "pretty.json"
    pretty_path.write_text(
        json.dumps(result.to_dict(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    with pytest.raises(
        chain.RepositoryWriteChainResultError,
        match="bytes are non-canonical",
    ):
        chain.load_repository_write_chain_result(pretty_path)


def test_conflicting_non_runtime_binding_is_refused() -> None:
    surface = RepositoryWriteSurface(
        path="daedalus/non_runtime.py",
        line=7,
        column=4,
        origin="base_v1",
        kind="open_write",
        callee="open",
        operation="mode='wb'",
        blocking=True,
    )
    row = SimpleNamespace(
        source_revision=REVISION,
        surface=surface,
        candidate_blockers=(),
        guard=SimpleNamespace(value="central"),
        non_runtime_conformity=SimpleNamespace(execution_id="execution.row"),
    )
    applicable = frozenset(
        stage
        for stage in AuthenticationStage
        if stage is not AuthenticationStage.CONFORMITY
    )
    auth = SurfaceEvidenceAuthentication(
        source_revision=REVISION,
        surface_sha256=surface_binding_sha256(REVISION, surface),
        path=surface.path,
        line=surface.line,
        column=surface.column,
        origin=surface.origin,
        applicable=applicable,
        verdicts=tuple(
            sorted(
                (
                    stage.value,
                    STAGE_VERDICT_NOT_APPLICABLE
                    if stage is AuthenticationStage.CONFORMITY
                    else STAGE_VERDICT_VERIFIED,
                )
                for stage in AuthenticationStage
            )
        ),
        authenticated=True,
        not_applicable_binding="execution.external",
    )

    with pytest.raises(
        chain.RepositoryWriteChainResultError,
        match="non-runtime binding mismatch",
    ):
        chain._chain_surface(row, auth)
