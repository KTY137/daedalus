from __future__ import annotations

import json

import pytest

from daedalus.gates.repository_write_artifact_verifier import (
    RepositoryWriteArtifactVerificationError,
    _strict_inventory_from_bytes,
)
from daedalus.gates.repository_write_inventory_v2 import (
    RepositoryWriteInventoryV2,
)
from daedalus.spine.envelope import canonical_json


INVENTORY = RepositoryWriteInventoryV2(
    source_revision="1" * 40,
    package_root="daedalus",
    scan_input_sha256="2" * 64,
    files_scanned=1,
    base_inventory_digest="3" * 64,
    stdlib_delta_digest="4" * 64,
    surfaces=(),
)


def test_exact_canonical_bytes_are_accepted() -> None:
    raw = canonical_json(INVENTORY.to_dict()).encode("ascii")
    assert _strict_inventory_from_bytes(raw) == INVENTORY


def test_pretty_printed_semantically_equal_json_refuses() -> None:
    raw = json.dumps(
        INVENTORY.to_dict(),
        sort_keys=True,
        indent=2,
    ).encode("ascii")
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="bytes are non-canonical",
    ):
        _strict_inventory_from_bytes(raw)


def test_reordered_semantically_equal_json_refuses() -> None:
    payload = INVENTORY.to_dict()
    reversed_payload = dict(reversed(tuple(payload.items())))
    raw = json.dumps(
        reversed_payload,
        sort_keys=False,
        separators=(",", ":"),
    ).encode("ascii")
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="bytes are non-canonical",
    ):
        _strict_inventory_from_bytes(raw)


def test_trailing_newline_refuses() -> None:
    raw = canonical_json(INVENTORY.to_dict()).encode("ascii") + b"\n"
    with pytest.raises(
        RepositoryWriteArtifactVerificationError,
        match="bytes are non-canonical",
    ):
        _strict_inventory_from_bytes(raw)
