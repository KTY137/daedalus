from __future__ import annotations

import json

import daedalus.gates.report_v3 as report_v3
from daedalus.spine.ledger import ROOT


SCHEMA = ROOT / "configs" / "schemas" / "gate-report-v3.schema.json"


def test_gate_report_v3_schema_matches_exact_runtime_shape() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert payload["additionalProperties"] is False
    assert set(payload["required"]) == set(report_v3._V3_FIELDS)
    assert payload["properties"]["schema"]["const"] == report_v3._SCHEMA
    assert payload["properties"]["gate"]["const"] == 0
    assert payload["properties"]["source_revision"]["pattern"] == "^[0-9a-f]{40}$"


def test_repository_write_identity_is_mandatory_but_nullable_for_fail_closed_reports() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    for field_name in (
        "repository_write_inventory_sha256",
        "repository_write_scan_input_sha256",
    ):
        assert field_name in payload["required"]
        alternatives = payload["properties"][field_name]["oneOf"]
        assert {tuple(sorted(item.items())) for item in alternatives} == {
            (("$ref", "#/$defs/sha256"),),
            (("type", "null"),),
        }


def test_repository_write_generation_counts_and_failures_match_parser_bounds() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert payload["properties"]["repository_write_files_scanned"] == {
        "type": "integer",
        "minimum": 0,
    }
    assert payload["properties"]["repository_write_inventory_generation"] == {
        "type": "integer",
        "minimum": 0,
    }
    assert payload["properties"]["repository_write_failures"] == {
        "$ref": "#/$defs/stringArray"
    }
    assert payload["$defs"]["sha256"]["pattern"] == "^[0-9a-f]{64}$"
    assert payload["$defs"]["boundedString"]["minLength"] == 1
    assert payload["$defs"]["boundedString"]["maxLength"] == 4000
    assert payload["$defs"]["stringArray"]["uniqueItems"] is True
