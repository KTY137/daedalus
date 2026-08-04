from __future__ import annotations

import json

import daedalus.gates.report as report_module
from daedalus.spine.ledger import ROOT


SCHEMA = ROOT / "configs" / "schemas" / "gate-report-v2.schema.json"


def test_gate_report_v2_schema_matches_exact_runtime_shape() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert payload["additionalProperties"] is False
    assert set(payload["required"]) == set(report_module._V2_FIELDS)
    assert payload["properties"]["schema"]["const"] == report_module._SCHEMA
    assert payload["properties"]["gate"]["const"] == 0


def test_schema_keeps_writer_inventory_digest_nullable_but_mandatory() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert "event_store_writer_inventory_sha256" in payload["required"]
    alternatives = payload["properties"][
        "event_store_writer_inventory_sha256"
    ]["oneOf"]
    assert {tuple(sorted(item.items())) for item in alternatives} == {
        (("$ref", "#/$defs/sha256"),),
        (("type", "null"),),
    }


def test_schema_sha256_and_arrays_match_parser_bounds() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert payload["$defs"]["sha256"]["pattern"] == "^[0-9a-f]{64}$"
    assert payload["$defs"]["boundedString"]["minLength"] == 1
    assert payload["$defs"]["boundedString"]["maxLength"] == 4000
    assert payload["$defs"]["stringArray"]["uniqueItems"] is True
