from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from daedalus.gates.release_io import (
    load_gate0_release_report,
    parse_gate0_release_report,
)

_SUPPORT_PATH = Path(__file__).with_name("release_support.py")
_SPEC = importlib.util.spec_from_file_location("_release_io_support", _SUPPORT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SUPPORT)


def _release(tmp_path: Path):
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    bundle = _SUPPORT.trust_bundle(index, root)
    return _SUPPORT.assemble(report, index, bundle, root)


def test_exact_canonical_release_round_trips_from_mapping_and_file(tmp_path: Path) -> None:
    release = _release(tmp_path)
    assert parse_gate0_release_report(release.to_dict()) == release

    path = tmp_path / "release.json"
    path.write_text(release.to_json() + "\n", encoding="utf-8")
    assert load_gate0_release_report(path) == release


def test_loader_rejects_duplicate_keys_at_top_and_nested_levels(tmp_path: Path) -> None:
    release = _release(tmp_path)
    wire = release.to_json()

    top = tmp_path / "top-duplicate.json"
    top.write_text('{"closed":true,' + wire[1:], encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON key 'closed'"):
        load_gate0_release_report(top)

    marker = '"gate_report":{'
    assert marker in wire
    nested = tmp_path / "nested-duplicate.json"
    nested.write_text(
        wire.replace(marker, marker + '"gate":0,', 1),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON key 'gate'"):
        load_gate0_release_report(nested)


def test_loader_refuses_non_object_unknown_and_missing_fields(tmp_path: Path) -> None:
    non_object = tmp_path / "array.json"
    non_object.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="must be an object"):
        load_gate0_release_report(non_object)

    release = _release(tmp_path)
    unknown = release.to_dict()
    unknown["invented"] = True
    with pytest.raises(ValueError, match="unknown field"):
        parse_gate0_release_report(unknown)

    missing = release.to_dict()
    missing.pop("evidence_trust_bundle_sha256")
    with pytest.raises(ValueError, match="missing field"):
        parse_gate0_release_report(missing)


def test_derived_and_nested_claims_cannot_be_repacked(tmp_path: Path) -> None:
    release = _release(tmp_path)

    forged_closed = release.to_dict()
    forged_closed["closed"] = not release.closed
    with pytest.raises(ValueError, match="closed contradicts"):
        parse_gate0_release_report(forged_closed)

    forged_blockers = release.to_dict()
    forged_blockers["blockers"] = ["invented"]
    with pytest.raises(ValueError, match="blockers contradict"):
        parse_gate0_release_report(forged_blockers)

    nested = release.to_dict()
    nested["gate_report"]["security_boundary_claimed"] = "true"
    with pytest.raises(ValueError):
        parse_gate0_release_report(nested)


def test_invalid_utf8_and_trailing_json_are_refused(tmp_path: Path) -> None:
    invalid_utf8 = tmp_path / "invalid-utf8.json"
    invalid_utf8.write_bytes(b"{\xff}")
    with pytest.raises(UnicodeDecodeError):
        load_gate0_release_report(invalid_utf8)

    release = _release(tmp_path)
    trailing = tmp_path / "trailing.json"
    trailing.write_text(release.to_json() + "\n{}", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_gate0_release_report(trailing)
