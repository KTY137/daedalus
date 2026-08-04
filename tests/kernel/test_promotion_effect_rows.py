from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from daedalus.spine.effect_boundary import Effect, EntrypointSpec, Surface, Wiring
from daedalus.spine.promotion_effect_rows import (
    PROMOTION_EXECUTION_ROW_DESCRIPTORS,
    PromotionExecutionRowDescriptor,
    materialize_promotion_execution_rows,
)


ROOT = Path(__file__).resolve().parents[2]


def _materialize(*, descriptors=PROMOTION_EXECUTION_ROW_DESCRIPTORS):
    return materialize_promotion_execution_rows(
        entrypoint_spec=EntrypointSpec,
        surface_values={value.value: value for value in Surface},
        effect_values={value.value: value for value in Effect},
        wiring_values={value.value: value for value in Wiring},
        descriptors=descriptors,
    )


def test_descriptors_are_exact_ordered_and_honestly_noncentral() -> None:
    assert tuple(row.entrypoint_id for row in PROMOTION_EXECUTION_ROW_DESCRIPTORS) == (
        "kernel.promotion_execution.open",
        "kernel.promotion_execution.begin",
        "kernel.promotion_execution.complete",
    )
    assert tuple(row.target for row in PROMOTION_EXECUTION_ROW_DESCRIPTORS) == (
        "daedalus.kernel.promotion_execution:PromotionExecutionLedger.__init__",
        "daedalus.kernel.promotion_execution:PromotionExecutionLedger.begin",
        "daedalus.kernel.promotion_execution:PromotionExecutionLedger.complete",
    )
    assert all(row.surface == "python" for row in PROMOTION_EXECUTION_ROW_DESCRIPTORS)
    assert all(
        row.effects == ("filesystem_write",)
        for row in PROMOTION_EXECUTION_ROW_DESCRIPTORS
    )
    assert all(
        row.guard_contracts == ("spine.intent_ledger",)
        for row in PROMOTION_EXECUTION_ROW_DESCRIPTORS
    )
    assert all(
        row.wiring == "local_guards"
        for row in PROMOTION_EXECUTION_ROW_DESCRIPTORS
    )
    assert all("Inventory only" in row.notes for row in PROMOTION_EXECUTION_ROW_DESCRIPTORS)


def test_materialization_uses_only_canonical_injected_types() -> None:
    rows = _materialize()
    assert len(rows) == 3
    assert all(isinstance(row, EntrypointSpec) for row in rows)
    assert tuple(row.id for row in rows) == tuple(
        descriptor.entrypoint_id
        for descriptor in PROMOTION_EXECUTION_ROW_DESCRIPTORS
    )
    assert all(row.surface is Surface.PYTHON for row in rows)
    assert all(row.effects == (Effect.FILESYSTEM_WRITE,) for row in rows)
    assert all(row.guard_contracts == ("spine.intent_ledger",) for row in rows)
    assert all(row.wiring is Wiring.LOCAL_GUARDS for row in rows)
    assert all(row.runtime_id == "" for row in rows)


def test_materializer_is_pure_and_deterministic() -> None:
    first = _materialize()
    second = _materialize()
    assert first == second
    assert first is not second
    assert tuple(row.to_dict() for row in first) == tuple(
        row.to_dict() for row in second
    )


def test_wrong_descriptor_identity_order_or_duplicate_refuses() -> None:
    first, second, third = PROMOTION_EXECUTION_ROW_DESCRIPTORS
    with pytest.raises(ValueError, match="identities are not exact"):
        _materialize(descriptors=(second, first, third))
    with pytest.raises(ValueError, match="identities are not exact"):
        _materialize(descriptors=(first, first, third))


def test_widened_effect_guard_or_wiring_refuses_at_descriptor_boundary() -> None:
    template = PROMOTION_EXECUTION_ROW_DESCRIPTORS[0]
    with pytest.raises(ValueError, match="one filesystem effect"):
        dataclasses.replace(template, effects=("process_spawn",))
    with pytest.raises(ValueError, match="intent ledger"):
        dataclasses.replace(template, guard_contracts=("promotion.owner_approval",))
    with pytest.raises(ValueError, match="remain local_guards"):
        dataclasses.replace(template, wiring="central")


def test_incomplete_enum_mapping_refuses_without_partial_rows() -> None:
    with pytest.raises(ValueError, match="mapping is incomplete"):
        materialize_promotion_execution_rows(
            entrypoint_spec=EntrypointSpec,
            surface_values={"python": Surface.PYTHON},
            effect_values={},
            wiring_values={"local_guards": Wiring.LOCAL_GUARDS},
        )


def test_descriptor_module_has_no_registry_or_effect_authority() -> None:
    source = (
        ROOT / "daedalus" / "spine" / "promotion_effect_rows.py"
    ).read_text(encoding="utf-8").lower()
    forbidden = (
        "from daedalus.spine.effect_boundary",
        "import daedalus.spine.effect_boundary",
        "entrypoints +=",
        "registry_by_id",
        "subprocess",
        "sqlite3",
        "open_gate0_spine_writer",
        "issue_owner_approval",
        "effectlease",
        "git worktree",
    )
    for token in forbidden:
        assert token not in source
