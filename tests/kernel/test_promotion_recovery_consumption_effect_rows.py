from __future__ import annotations

from dataclasses import dataclass, replace

import pytest

from daedalus.spine.promotion_recovery_consumption_effect_rows import (
    PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS,
    PromotionRecoveryConsumptionRowDescriptor,
    materialize_promotion_recovery_consumption_rows,
)


@dataclass(frozen=True)
class FakeAnchor:
    target: str
    call: str


@dataclass(frozen=True)
class FakeRow:
    id: str
    surface: object
    target: str
    effects: tuple[object, ...]
    guard_contracts: tuple[str, ...]
    wiring: object
    anchors: tuple[FakeAnchor, ...]
    notes: str


SURFACES = {"python": object()}
EFFECTS = {"filesystem_write": object()}
WIRINGS = {"local_guards": object()}


def _materialize(*, descriptors=PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS):
    return materialize_promotion_recovery_consumption_rows(
        entrypoint_spec=FakeRow,
        guard_anchor=FakeAnchor,
        surface_values=SURFACES,
        effect_values=EFFECTS,
        wiring_values=WIRINGS,
        descriptors=descriptors,
    )


def test_exact_descriptor_subjects_are_small_and_noncentral() -> None:
    rows = PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS

    assert tuple(row.entrypoint_id for row in rows) == (
        "kernel.promotion_recovery_consumption.open",
        "kernel.promotion_recovery_consumption.consume",
    )
    assert tuple(row.target for row in rows) == (
        "daedalus.kernel.promotion_recovery_consumption:"
        "PromotionRecoveryConsumptionLedger.__init__",
        "daedalus.kernel.promotion_recovery_consumption:"
        "PromotionRecoveryConsumptionLedger.consume",
    )
    assert all(row.surface == "python" for row in rows)
    assert all(row.effects == ("filesystem_write",) for row in rows)
    assert all(row.wiring == "local_guards" for row in rows)
    assert rows[0].guard_contracts == (
        "promotion.recovery_consumption_store",
    )
    assert rows[1].guard_contracts == (
        "promotion.owner_recovery_decision",
        "promotion.recovery_consumption_store",
    )


def test_exact_anchors_name_real_local_boundaries() -> None:
    open_row, consume_row = PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS

    assert open_row.anchors == (
        (
            "daedalus.kernel.promotion_recovery_consumption:"
            "PromotionRecoveryConsumptionLedger.__init__",
            "_initialize",
        ),
        (
            "daedalus.kernel.promotion_recovery_consumption:"
            "PromotionRecoveryConsumptionLedger._initialize",
            "_connect_writer",
        ),
    )
    assert consume_row.anchors == (
        (
            "daedalus.kernel.promotion_recovery_consumption:"
            "PromotionRecoveryConsumptionLedger.consume",
            "verify_promotion_recovery_decision",
        ),
        (
            "daedalus.kernel.promotion_recovery_consumption:"
            "PromotionRecoveryConsumptionLedger.consume",
            "_connect_writer",
        ),
    )


def test_materialization_uses_only_injected_canonical_types() -> None:
    rows = _materialize()

    assert len(rows) == 2
    assert all(isinstance(row, FakeRow) for row in rows)
    assert rows[0].surface is SURFACES["python"]
    assert rows[0].effects == (EFFECTS["filesystem_write"],)
    assert rows[0].wiring is WIRINGS["local_guards"]
    assert all(
        isinstance(anchor, FakeAnchor)
        for row in rows
        for anchor in row.anchors
    )
    assert tuple(row.id for row in rows) == tuple(
        descriptor.entrypoint_id
        for descriptor in PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS
    )


def test_materialization_is_deterministic_and_pure() -> None:
    before = tuple(
        descriptor.to_dict()
        for descriptor in PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS
    )

    first = _materialize()
    second = _materialize()

    assert first == second
    assert tuple(
        descriptor.to_dict()
        for descriptor in PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS
    ) == before


@pytest.mark.parametrize(
    "field,value",
    [
        ("entrypoint_id", "kernel.promotion_recovery_consumption.other"),
        (
            "target",
            "daedalus.kernel.promotion_recovery_consumption:"
            "PromotionRecoveryConsumptionLedger.verify_consumption",
        ),
        ("surface", "cli"),
        ("effects", ("filesystem_write", "repository_mutation")),
        ("wiring", "central"),
        ("anchors", ()),
        (
            "anchors",
            (
                (
                    "daedalus.kernel.promotion_recovery_consumption:"
                    "PromotionRecoveryConsumptionLedger.__init__",
                    "_connect_writer",
                ),
            ),
        ),
    ],
)
def test_descriptor_refuses_identity_effect_wiring_and_anchor_widening(
    field: str,
    value: object,
) -> None:
    original = PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS[0]

    with pytest.raises(ValueError):
        replace(original, **{field: value})


def test_descriptor_refuses_guard_substitution() -> None:
    original = PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS[1]

    with pytest.raises(ValueError):
        replace(
            original,
            guard_contracts=("promotion.owner_approval",),
        )


def test_descriptor_refuses_validly_shaped_anchor_substitution() -> None:
    original = PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS[1]

    with pytest.raises(ValueError):
        replace(
            original,
            anchors=tuple(reversed(original.anchors)),
        )


@pytest.mark.parametrize(
    "descriptors",
    [
        tuple(reversed(PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS)),
        (
            PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS[0],
            PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS[0],
        ),
        (PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS[0],),
    ],
)
def test_materializer_refuses_reordered_duplicate_or_partial_subjects(
    descriptors: tuple[PromotionRecoveryConsumptionRowDescriptor, ...],
) -> None:
    with pytest.raises(ValueError):
        _materialize(descriptors=descriptors)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"surface_values": {}},
        {"effect_values": {}},
        {"wiring_values": {}},
    ],
)
def test_materializer_refuses_incomplete_canonical_mappings(
    kwargs: dict[str, object],
) -> None:
    arguments = {
        "entrypoint_spec": FakeRow,
        "guard_anchor": FakeAnchor,
        "surface_values": SURFACES,
        "effect_values": EFFECTS,
        "wiring_values": WIRINGS,
    }
    arguments.update(kwargs)

    with pytest.raises(ValueError):
        materialize_promotion_recovery_consumption_rows(**arguments)


def test_materializer_refuses_untyped_or_smuggled_factories() -> None:
    with pytest.raises(TypeError):
        materialize_promotion_recovery_consumption_rows(
            entrypoint_spec=None,
            guard_anchor=FakeAnchor,
            surface_values=SURFACES,
            effect_values=EFFECTS,
            wiring_values=WIRINGS,
        )
    with pytest.raises(TypeError):
        materialize_promotion_recovery_consumption_rows(
            entrypoint_spec=FakeRow,
            guard_anchor=None,
            surface_values=SURFACES,
            effect_values=EFFECTS,
            wiring_values=WIRINGS,
        )
    with pytest.raises(TypeError):
        materialize_promotion_recovery_consumption_rows(
            entrypoint_spec=FakeRow,
            guard_anchor=FakeAnchor,
            surface_values=SURFACES,
            effect_values=EFFECTS,
            wiring_values=WIRINGS,
            descriptors=list(PROMOTION_RECOVERY_CONSUMPTION_ROW_DESCRIPTORS),
        )
