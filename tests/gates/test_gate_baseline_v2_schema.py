from __future__ import annotations

import json

import daedalus.gates.baseline as baseline_module
from daedalus.spine.ledger import ROOT


BASELINE_SCHEMA = ROOT / "configs" / "schemas" / "gate-baseline-v2.schema.json"
MONOTONICITY_SCHEMA = (
    ROOT / "configs" / "schemas" / "gate-monotonicity-v2.schema.json"
)


def test_baseline_schema_matches_runtime_wire_contract() -> None:
    payload = json.loads(BASELINE_SCHEMA.read_text(encoding="utf-8"))
    assert payload["additionalProperties"] is False
    assert payload["properties"]["schema"]["const"] == baseline_module._BASELINE_SCHEMA
    assert payload["properties"]["gate"]["const"] == 0
    assert payload["$defs"]["revision"]["pattern"] == "^[0-9a-f]{40}$"
    assert payload["$defs"]["sha256"]["pattern"] == "^[0-9a-f]{64}$"
    assert set(payload["required"]) == {
        "schema",
        "baseline_id",
        "gate",
        "source_revision",
        "source_tree_revision",
        "gate_report_sha256",
        "gate_report_artifact_sha256",
        "registry_sha256",
        "event_store_writer_inventory_sha256",
        "blockers",
        "blocker_set_sha256",
        "created_at",
        "baseline_sha256",
    }


def test_monotonicity_schema_matches_runtime_wire_contract() -> None:
    payload = json.loads(MONOTONICITY_SCHEMA.read_text(encoding="utf-8"))
    assert payload["additionalProperties"] is False
    assert payload["properties"]["schema"]["const"] == baseline_module._MONOTONICITY_SCHEMA
    assert payload["properties"]["gate"]["const"] == 0
    assert set(payload["required"]) == {
        "schema",
        "assessment_id",
        "gate",
        "baseline_sha256",
        "baseline_source_revision",
        "baseline_source_tree_revision",
        "current_source_revision",
        "current_source_tree_revision",
        "current_gate_report_sha256",
        "current_gate_report_artifact_sha256",
        "current_registry_sha256",
        "current_event_store_writer_inventory_sha256",
        "retained_blockers",
        "resolved_blockers",
        "new_blockers",
        "status",
        "assessed_at",
        "receipt_sha256",
    }
    assert payload["properties"]["status"]["enum"] == ["passed", "failed"]


def test_both_schemas_require_unique_bounded_blocker_rows() -> None:
    for path in (BASELINE_SCHEMA, MONOTONICITY_SCHEMA):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["$defs"]["stringArray"]["uniqueItems"] is True
        assert payload["$defs"]["boundedString"]["minLength"] == 1
        assert payload["$defs"]["boundedString"]["maxLength"] == 4000
