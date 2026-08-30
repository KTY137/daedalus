# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path


SCHEMA = Path(
    "configs/schemas/repository-head-revision-receipt.schema.json"
)


def test_repository_head_schema_is_exact_and_non_authorizing() -> None:
    document = json.loads(SCHEMA.read_text(encoding="utf-8"))

    assert document["type"] == "object"
    assert document["additionalProperties"] is False
    assert set(document["required"]) == set(document["properties"])
    assert document["properties"]["schema"]["const"] == (
        "daedalus-repository-head-revision-receipt/1"
    )
    assert document["properties"]["repository_head_verified"]["const"] is True
    assert document["properties"]["commit_object_verified"]["const"] is False
    assert document["properties"]["worktree_clean_verified"]["const"] is False
    assert document["properties"]["process_spawned"]["const"] is False
    assert document["properties"]["repository_mutated"]["const"] is False


def test_repository_head_schema_has_three_disjoint_resolution_shapes() -> None:
    document = json.loads(SCHEMA.read_text(encoding="utf-8"))
    alternatives = document["oneOf"]

    assert len(alternatives) == 3
    shapes = {
        (
            item["properties"]["head_mode"]["const"],
            item["properties"]["resolution_source"]["const"],
        )
        for item in alternatives
    }
    assert shapes == {
        ("detached", "head"),
        ("symbolic", "loose_ref"),
        ("symbolic", "packed_refs"),
    }


def test_detached_shape_requires_null_reference_evidence() -> None:
    document = json.loads(SCHEMA.read_text(encoding="utf-8"))
    detached = next(
        item
        for item in document["oneOf"]
        if item["properties"]["head_mode"].get("const") == "detached"
    )

    for field in (
        "head_ref",
        "reference_path",
        "reference_sha256",
        "reference_size",
    ):
        assert detached["properties"][field]["type"] == "null"


def test_symbolic_shapes_require_ref_evidence() -> None:
    document = json.loads(SCHEMA.read_text(encoding="utf-8"))
    symbolic = [
        item
        for item in document["oneOf"]
        if item["properties"]["head_mode"].get("const") == "symbolic"
    ]

    assert len(symbolic) == 2
    for item in symbolic:
        assert item["properties"]["head_ref"] == {"$ref": "#/$defs/ref"}
        assert item["properties"]["reference_sha256"] == {
            "$ref": "#/$defs/sha256"
        }
        assert item["properties"]["reference_size"]["type"] == "integer"
