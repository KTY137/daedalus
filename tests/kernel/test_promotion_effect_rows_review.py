from __future__ import annotations

import ast
from pathlib import Path

import pytest

from daedalus.spine.effect_boundary import Effect, EffectStartRefused, begin_effect


ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "daedalus" / "spine" / "promotion_effect_rows.py"
IDS = (
    "kernel.promotion_execution.open",
    "kernel.promotion_execution.begin",
    "kernel.promotion_execution.complete",
)


def test_counter_review_rows_claim_no_central_or_runtime_authority() -> None:
    source = TARGET.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(TARGET))
    assert source.count("boundary.Wiring.LOCAL_GUARDS") == 1
    assert "boundary.Wiring.CENTRAL" not in source
    assert "RuntimeConformanceReceipt" not in source
    assert "EffectLease" not in source
    forbidden = {"subprocess", "Popen", "system", "GitWorktreeManager"}
    assert not {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in forbidden
    }


def test_counter_review_requires_exact_three_ids_and_write_anchors() -> None:
    source = TARGET.read_text(encoding="utf-8")
    for entrypoint_id in IDS:
        assert source.count(f'id="{entrypoint_id}"') == 1
    for anchor in (
        "open_gate0_spine_writer",
        "_install_single_start_invariant",
        "record_intent",
        "mark_completed",
    ):
        assert source.count(f'"{anchor}"') == 1
    assert "MappingProxyType" in source
    assert "registry_sha256.__defaults__" in source
    assert "begin_effect.__kwdefaults__" in source
    assert "check_conformance.__kwdefaults__" in source


def test_local_rows_still_refuse_generic_effect_start() -> None:
    for entrypoint_id in IDS:
        with pytest.raises(EffectStartRefused, match="not central"):
            begin_effect(entrypoint_id, (Effect.FILESYSTEM_WRITE,), ())
