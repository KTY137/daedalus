"""Frozen spec/result identity and retained-negative-evidence checks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from experiments.forest_v2.tensor_embeddings.encoding import HASH_FEATURE_FAMILY
from experiments.forest_v2.tensor_embeddings.stats import (
    ReportValidationError,
    SPEC_DIGEST,
    validate_report,
)


ROOT = Path(__file__).resolve().parent


def _canonical_digest(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def test_embedded_spec_digest_and_feature_family_match_frozen_json() -> None:
    path = ROOT / "EXPERIMENT_SPEC.json"
    spec = json.loads(path.read_text(encoding="utf-8"))
    assert _canonical_digest(path) == SPEC_DIGEST
    assert spec["hash_feature_family"] == HASH_FEATURE_FAMILY
    assert spec["filler_backend"] == "signed-subword-hash-shared-word-p4-s4/2"
    assert spec["dense_scalar_budget"] == (
        len(spec["planes"]) * len(spec["roles"]) * spec["feature_dimension"]
    )


def test_superseded_role_salted_smoke_is_retained_but_rejected_by_current_spec() -> None:
    report = json.loads(
        (ROOT / "results" / "s09_c00_smoke.json").read_text(encoding="utf-8")
    )
    assert report["spec_digest"] == (
        "sha256:5ac3be24819682fea3ad2c49fe8dd01ab755002e258bd169dc26c8f7de18461f"
    )
    assert report["spec_digest"] != SPEC_DIGEST
    with pytest.raises(ReportValidationError, match="spec_digest"):
        validate_report(report)
    assert report["status"] == "VALID"
    assert report["conclusion"] == "INCONCLUSIVE"
    assert report["comparisons"][0]["delta"] == 0.0
    assert report["comparisons"][0]["superiority_claim"] is False
    for arm in report["arms"].values():
        for run in arm.values():
            assert run["per_case"]["c00"]["reciprocal_rank"] == 0.0


def test_cost_failures_are_retained_with_no_speedup_claim() -> None:
    note = (ROOT / "PERFORMANCE_NOTE.md").read_text(encoding="utf-8")
    collapsed = " ".join(note.split())
    assert "more than 150 seconds" in collapsed
    assert "more than 120 seconds" in collapsed
    assert "must not be cited as a tensor speedup" in collapsed
    assert "not scientifically evaluable" in note
    assert "superseded" in note
