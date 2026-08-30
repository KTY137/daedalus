# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_attempt_workspace_schema_accepts_bounded_paths_and_refuses_traversal() -> None:
    schema = json.loads(
        (ROOT / "configs/schemas/attempt-start-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    pattern = schema["properties"]["workspace_relative_path"]["pattern"]

    assert re.fullmatch(pattern, "attempts/attempt-1-deadbeef")
    assert re.fullmatch(pattern, "attempts/campaign-1/attempt-2")

    for value in (
        "attempts/../escape",
        "attempts/./same",
        "attempts/child/../../escape",
        "attempts//empty",
        "../attempts/escape",
        "/attempts/absolute",
    ):
        assert re.fullmatch(pattern, value) is None, value


def test_attempt_schemas_are_strict_objects() -> None:
    for name in ("attempt-start-v1.schema.json", "attempt-terminal-v1.schema.json"):
        schema = json.loads((ROOT / "configs/schemas" / name).read_text(encoding="utf-8"))
        assert schema["additionalProperties"] is False
        assert schema["$schema"].endswith("draft/2020-12/schema")
