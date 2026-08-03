from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

import daedalus.gates.trust_bundle as compatibility_module
from daedalus.gates import (
    load_evidence_trust_bundle,
    parse_evidence_trust_bundle,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "tests" / "gates" / "test_evidence_trust_bundle.py"


def _fixture():
    name = "daedalus_test_trust_bundle_canonical_fixture"
    spec = importlib.util.spec_from_file_location(name, FIXTURE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _fixture()


def _bundle(tmp_path: Path):
    root = fixture._repo(tmp_path)
    index = fixture._index()
    return fixture._bundle(index, root)


def test_exact_canonical_bundle_round_trips_from_mapping_and_file(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    assert parse_evidence_trust_bundle(bundle.to_dict()) == bundle

    path = tmp_path / "trust-bundle.json"
    path.write_text(
        json.dumps(bundle.to_dict(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    assert load_evidence_trust_bundle(path) == bundle


def test_compatibility_module_names_are_strict_strangler_aliases() -> None:
    assert compatibility_module.parse_evidence_trust_bundle is parse_evidence_trust_bundle
    assert compatibility_module.load_evidence_trust_bundle is load_evidence_trust_bundle


def test_reordered_signed_digest_array_is_not_silently_normalized(
    tmp_path: Path,
) -> None:
    payload = _bundle(tmp_path).to_dict()
    values = payload["review_evidence_sha256s"]
    assert len(values) == 2
    payload["review_evidence_sha256s"] = list(reversed(values))

    with pytest.raises(ValueError, match="exact canonical wire"):
        parse_evidence_trust_bundle(payload)
    with pytest.raises(ValueError, match="exact canonical wire"):
        compatibility_module.parse_evidence_trust_bundle(payload)


def test_reordered_signed_provenance_inputs_are_refused(tmp_path: Path) -> None:
    payload = _bundle(tmp_path).to_dict()
    values = payload["provenance"]["input_digests"]
    assert len(values) > 3
    payload["provenance"]["input_digests"] = list(reversed(values))

    with pytest.raises(ValueError, match="exact canonical wire"):
        parse_evidence_trust_bundle(payload)


def test_file_loader_refuses_recursive_duplicate_keys(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    wire = json.dumps(bundle.to_dict(), sort_keys=True, separators=(",", ":"))
    marker = '"provenance":{'
    assert marker in wire
    path = tmp_path / "duplicate-trust-bundle.json"
    path.write_text(
        wire.replace(marker, marker + '"origin":"foreign",', 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate JSON key 'origin'"):
        load_evidence_trust_bundle(path)


def test_tuple_is_not_accepted_as_an_alternate_wire_array(tmp_path: Path) -> None:
    payload = _bundle(tmp_path).to_dict()
    payload["artifact_evidence_sha256s"] = tuple(
        payload["artifact_evidence_sha256s"]
    )

    with pytest.raises(ValueError, match="exact canonical wire"):
        parse_evidence_trust_bundle(payload)


def test_counter_review_pins_package_and_module_compatibility_boundary() -> None:
    init_source = (ROOT / "daedalus" / "gates" / "__init__.py").read_text(
        encoding="utf-8"
    )
    io_source = (
        ROOT / "daedalus" / "gates" / "trust_bundle_io.py"
    ).read_text(encoding="utf-8")
    assert "wire = dict(payload)" in io_source
    assert "bundle = EvidenceTrustBundle.from_dict(wire)" in io_source
    assert "wire != bundle.to_dict()" in io_source
    assert "_trust_bundle.parse_evidence_trust_bundle = parse_evidence_trust_bundle" in init_source
    assert "_trust_bundle.load_evidence_trust_bundle = load_evidence_trust_bundle" in init_source


def test_counter_review_does_not_claim_collector_owner_or_gate_authority() -> None:
    source = Path(__file__).read_text(encoding="utf-8").lower()
    assert "collector verified" not in source
    assert "approved by owner" not in source
    assert "human review passed" not in source
    assert "gate 0 closed" not in source
