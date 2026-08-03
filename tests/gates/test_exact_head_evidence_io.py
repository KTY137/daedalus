from __future__ import annotations

from pathlib import Path

import pytest

from daedalus.gates import load_gate_evidence_index, parse_gate_evidence_index


def test_top_level_string_cannot_be_repacked_as_required_array() -> None:
    with pytest.raises(ValueError, match="required_workflow_ids must be an array"):
        parse_gate_evidence_index({"required_workflow_ids": "iron-plan"})


def test_nested_string_cannot_be_repacked_as_scenario_or_findings_array() -> None:
    with pytest.raises(ValueError, match="scenario_ids must be an array"):
        parse_gate_evidence_index(
            {"fault_matrices": [{"scenario_ids": "approval-replay"}]}
        )
    with pytest.raises(ValueError, match="unresolved_finding_ids must be an array"):
        parse_gate_evidence_index(
            {"reviews": [{"unresolved_finding_ids": ""}]}
        )


def test_nested_record_must_be_an_object() -> None:
    with pytest.raises(ValueError, match=r"workflows\[0\] must be an object"):
        parse_gate_evidence_index({"workflows": ["not-an-object"]})


def test_duplicate_json_keys_are_refused_before_contract_parsing(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text(
        '{"contract_type":"one","contract_type":"two"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_gate_evidence_index(path)


def test_non_object_json_root_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "array.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        load_gate_evidence_index(path)
