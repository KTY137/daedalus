from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from daedalus.kernel.promotion_effect_replay import (
    PromotionEffectReplayError,
    inspect_promotion_effect_execution,
)
from daedalus.spine.envelope import canonical_json

_FIXTURE_PATH = Path(__file__).with_name("test_promotion_effect_capability.py")
_SPEC = importlib.util.spec_from_file_location(
    "_promotion_effect_capability_adversarial_fixture",
    _FIXTURE_PATH,
)
assert _SPEC is not None and _SPEC.loader is not None
_FIXTURE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURE)
build_capability = _FIXTURE.build_capability


def test_orphan_execution_without_lease_is_refused(tmp_path) -> None:
    capability = build_capability(tmp_path)
    capability.grant()
    capability.begin()
    with sqlite3.connect(capability.authorization.effect_ledger.path) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute(
            "DELETE FROM effect_leases WHERE lease_sha256=?",
            (capability.authorization.lease.digest,),
        )
        conn.commit()

    with pytest.raises(PromotionEffectReplayError, match="without its persisted lease"):
        inspect_promotion_effect_execution(capability)


def test_malformed_start_digest_is_normalized_to_replay_error(tmp_path) -> None:
    capability = build_capability(tmp_path)
    capability.grant()
    capability.begin()
    path = capability.authorization.effect_ledger.path
    with sqlite3.connect(path) as conn:
        raw = conn.execute(
            "SELECT start_receipt_json FROM effect_executions WHERE execution_id=?",
            (capability.execution.execution_id,),
        ).fetchone()[0]
        payload = json.loads(raw)
        payload["receipt_sha256"] = "not-a-digest"
        conn.execute(
            "UPDATE effect_executions SET start_receipt_json=? WHERE execution_id=?",
            (canonical_json(payload), capability.execution.execution_id),
        )
        conn.commit()

    with pytest.raises(PromotionEffectReplayError, match="canonical digest"):
        inspect_promotion_effect_execution(capability)


def test_noncanonical_start_json_is_refused_before_hydration(tmp_path) -> None:
    capability = build_capability(tmp_path)
    capability.grant()
    capability.begin()
    path = capability.authorization.effect_ledger.path
    with sqlite3.connect(path) as conn:
        raw = conn.execute(
            "SELECT start_receipt_json FROM effect_executions WHERE execution_id=?",
            (capability.execution.execution_id,),
        ).fetchone()[0]
        payload = json.loads(raw)
        noncanonical = json.dumps(payload, sort_keys=False, indent=2)
        conn.execute(
            "UPDATE effect_executions SET start_receipt_json=? WHERE execution_id=?",
            (noncanonical, capability.execution.execution_id),
        )
        conn.commit()

    with pytest.raises(PromotionEffectReplayError, match="not canonical JSON"):
        inspect_promotion_effect_execution(capability)
