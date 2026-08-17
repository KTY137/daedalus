from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from daedalus.gates import load_gate_evidence_index, parse_gate_evidence_index

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "tests" / "gates" / "test_evidence_trust_bundle.py"


def _fixture():
    name = "daedalus_test_evidence_index_canonical_fixture"
    spec = importlib.util.spec_from_file_location(name, FIXTURE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _fixture()


def test_exact_canonical_index_round_trips_from_mapping_and_file(tmp_path: Path) -> None:
    index = fixture._index()
    assert parse_gate_evidence_index(index.to_dict()) == index

    path = tmp_path / "index.json"
    path.write_text(
        json.dumps(index.to_dict(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    assert load_gate_evidence_index(path) == index


def test_reordered_required_perspectives_are_not_silently_canonicalized() -> None:
    payload = fixture._index().to_dict()
    assert payload["required_review_perspectives"] == ["architecture", "security"]
    payload["required_review_perspectives"].reverse()

    with pytest.raises(ValueError, match="exact canonical wire"):
        parse_gate_evidence_index(payload)


def test_reordered_nested_signed_provenance_is_refused() -> None:
    payload = fixture._index().to_dict()
    inputs = payload["provenance"]["input_digests"]
    assert len(inputs) > 2
    payload["provenance"]["input_digests"] = list(reversed(inputs))

    with pytest.raises(ValueError, match="exact canonical wire"):
        parse_gate_evidence_index(payload)


def test_python_tuple_is_not_accepted_as_an_alternate_wire_array() -> None:
    payload = fixture._index().to_dict()
    payload["required_workflow_ids"] = tuple(payload["required_workflow_ids"])

    with pytest.raises(ValueError, match="exact canonical wire"):
        parse_gate_evidence_index(payload)


def test_file_loader_refuses_noncanonical_but_parseable_index(tmp_path: Path) -> None:
    payload = fixture._index().to_dict()
    payload["reviews"] = list(reversed(payload["reviews"]))
    path = tmp_path / "reordered-index.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="exact canonical wire"):
        load_gate_evidence_index(path)


def test_counter_review_pins_reconstruction_and_complete_wire_equality() -> None:
    source = (ROOT / "daedalus" / "gates" / "evidence_io.py").read_text(
        encoding="utf-8"
    )
    assert "wire = dict(record)" in source
    assert "index = GateEvidenceIndex.from_dict(wire)" in source
    assert "wire != index.to_dict()" in source
    assert "exact canonical wire form" in source


def test_counter_review_does_not_claim_human_owner_or_gate_authority() -> None:
    # Each forbidden claim is joined from separate words at runtime so this
    # counter-review can name what it refuses to claim without the contiguous
    # phrase appearing in the very file it scans. A claim spelled out anywhere
    # in this file -- prose, comment, docstring or string literal -- still fails.
    forbidden_claims = tuple(
        " ".join(words)
        for words in (
            ("approved", "by", "owner"),
            ("human", "review", "passed"),
            ("gate", "0", "closed"),
        )
    )
    source = Path(__file__).read_text(encoding="utf-8").lower()
    for claim in forbidden_claims:
        assert claim not in source, f"counter-review must not claim: {claim}"
