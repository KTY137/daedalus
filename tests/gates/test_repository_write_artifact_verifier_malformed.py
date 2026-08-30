# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

import pytest

from daedalus.gates.repository_write_artifact_verifier import (
    RepositoryWriteArtifactVerificationError,
    _strict_inventory_from_bytes,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
    RepositoryWriteSurface,
)


REVISION = "1" * 40


def _payload() -> dict:
    return RepositoryWriteInventoryV2(
        source_revision=REVISION,
        package_root="daedalus",
        scan_input_sha256="2" * 64,
        files_scanned=1,
        base_inventory_digest="3" * 64,
        stdlib_delta_digest="4" * 64,
        surfaces=(
            RepositoryWriteSurface(
                path="daedalus/example.py",
                line=3,
                column=1,
                origin="base_v1",
                kind="path-write",
                callee="Path.write_text",
                operation="write_text",
                blocking=True,
            ),
        ),
    ).to_dict()


def _raw(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("files_scanned", True),
        ("files_scanned", 0),
        ("surface_count", True),
        ("blocker_count", False),
        ("inventory_generation", True),
        ("closed", 1),
        ("canonical_scanner_integrated", 1),
        ("inventory_only", 1),
        ("primary_checkout_target_proven", 0),
    ],
)
def test_wrong_scalar_types_or_derived_values_refuse(
    field: str,
    value,
) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="malformed|non-canonical",
    ):
        _strict_inventory_from_bytes(_raw(payload))


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_revision", "A" * 40),
        ("package_root", "../daedalus"),
        ("scan_input_sha256", "not-a-digest"),
    ],
)
def test_malformed_inventory_identity_refuses(field: str, value: str) -> None:
    payload = _payload()
    payload[field] = value
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="contract is malformed",
    ):
        _strict_inventory_from_bytes(_raw(payload))


def test_unsorted_surfaces_refuse() -> None:
    payload = _payload()
    first = dict(payload["surfaces"][0])
    second = {
        **first,
        "path": "daedalus/another.py",
        "line": 1,
        "column": 0,
    }
    payload["surfaces"] = [first, second]
    payload["surface_count"] = 2
    payload["blocker_count"] = 2
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="contract is malformed",
    ):
        _strict_inventory_from_bytes(_raw(payload))


def test_duplicate_surface_positions_refuse() -> None:
    payload = _payload()
    duplicate = {
        **payload["surfaces"][0],
        "kind": "binary-write",
        "callee": "Path.write_bytes",
        "operation": "write_bytes",
    }
    payload["surfaces"] = [payload["surfaces"][0], duplicate]
    payload["surface_count"] = 2
    payload["blocker_count"] = 2
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="contract is malformed",
    ):
        _strict_inventory_from_bytes(_raw(payload))


def test_component_digest_substitution_refuses_canonical_digest_check() -> None:
    payload = _payload()
    payload["components"]["base_inventory_digest"] = "5" * 64
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="non-canonical",
    ):
        _strict_inventory_from_bytes(_raw(payload))


def test_declared_inventory_digest_substitution_refuses() -> None:
    payload = _payload()
    payload["digest"] = "6" * 64
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="non-canonical",
    ):
        _strict_inventory_from_bytes(_raw(payload))
