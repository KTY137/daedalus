from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from daedalus.gates.release_io import (
    load_mechanical_gate_report,
    parse_mechanical_gate_report,
)

_SUPPORT_PATH = Path(__file__).with_name("release_support.py")
_SPEC = importlib.util.spec_from_file_location("_mechanical_report_support", _SUPPORT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SUPPORT)


def _report_sha(payload: dict[str, object]) -> str:
    body = dict(payload)
    body.pop("report_sha256", None)
    wire = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(wire.encode("utf-8")).hexdigest()


def test_exact_mechanical_report_round_trips_from_mapping_and_file(tmp_path: Path) -> None:
    report = _SUPPORT.local_report(diagnostics=("alpha", "zeta"))
    assert parse_mechanical_gate_report(report.to_dict()) == report

    path = tmp_path / "mechanical.json"
    path.write_text(
        json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    assert load_mechanical_gate_report(path) == report


def test_mechanical_report_duplicate_keys_are_refused(tmp_path: Path) -> None:
    report = _SUPPORT.local_report()
    wire = json.dumps(report.to_dict(), sort_keys=True, separators=(",", ":"))
    path = tmp_path / "duplicate.json"
    path.write_text('{"closed":true,' + wire[1:], encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON key 'closed'"):
        load_mechanical_gate_report(path)


def test_self_digested_but_noncanonical_array_order_is_refused() -> None:
    report = _SUPPORT.local_report(diagnostics=("alpha", "zeta"))
    payload = report.to_dict()
    payload["diagnostics"] = ["zeta", "alpha"]
    payload["report_sha256"] = _report_sha(payload)

    with pytest.raises(ValueError, match="exact canonical wire"):
        parse_mechanical_gate_report(payload)


def test_self_digested_but_forged_derived_claims_are_refused() -> None:
    report = _SUPPORT.local_report()
    payload = report.to_dict()
    payload["closed"] = not report.closed
    payload["blockers"] = ["invented"]
    payload["report_sha256"] = _report_sha(payload)

    with pytest.raises(ValueError, match="exact canonical wire"):
        parse_mechanical_gate_report(payload)
