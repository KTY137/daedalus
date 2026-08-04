from __future__ import annotations

from types import MappingProxyType, SimpleNamespace

import pytest

from daedalus.spine import effect_boundary
from daedalus.spine.promotion_effect_registry import install_promotion_execution_rows


IDS = (
    "kernel.promotion_execution.open",
    "kernel.promotion_execution.begin",
    "kernel.promotion_execution.complete",
)


def _installed_rows():
    return tuple(effect_boundary.REGISTRY_BY_ID[entrypoint_id] for entrypoint_id in IDS)


def test_exact_rows_are_installed_once_in_canonical_registry() -> None:
    rows = _installed_rows()
    assert tuple(row.id for row in rows) == IDS
    assert len(effect_boundary.ENTRYPOINTS) == len(effect_boundary.REGISTRY_BY_ID)
    assert all(row.wiring is effect_boundary.Wiring.LOCAL_GUARDS for row in rows)
    assert all(row.effects == (effect_boundary.Effect.FILESYSTEM_WRITE,) for row in rows)
    assert all(row.guard_contracts == ("spine.intent_ledger",) for row in rows)
    assert all("Docker sandbox" in row.migration for row in rows)


def test_installed_rows_retain_exact_source_anchors() -> None:
    opened, begun, completed = _installed_rows()
    assert tuple(anchor.call for anchor in opened.anchors) == (
        "open_gate0_spine_writer",
        "_install_single_start_invariant",
    )
    assert tuple(anchor.target for anchor in opened.anchors) == (opened.target, opened.target)
    assert tuple(anchor.call for anchor in begun.anchors) == ("record_intent",)
    assert tuple(anchor.call for anchor in completed.anchors) == ("mark_completed",)


def test_captured_registry_defaults_use_installed_authority() -> None:
    assert effect_boundary.registry_sha256.__defaults__ == (
        effect_boundary.ENTRYPOINTS,
    )
    assert (
        effect_boundary.begin_effect.__kwdefaults__["registry"]
        is effect_boundary.REGISTRY_BY_ID
    )
    assert (
        effect_boundary.check_conformance.__kwdefaults__["registry"]
        is effect_boundary.ENTRYPOINTS
    )


def test_repeated_exact_install_is_idempotent() -> None:
    before = effect_boundary.ENTRYPOINTS
    install_promotion_execution_rows(effect_boundary)
    assert effect_boundary.ENTRYPOINTS is before
    assert tuple(row.id for row in _installed_rows()) == IDS


def test_local_rows_still_refuse_generic_effect_start() -> None:
    for entrypoint_id in IDS:
        with pytest.raises(effect_boundary.EffectStartRefused, match="not central"):
            effect_boundary.begin_effect(
                entrypoint_id,
                (effect_boundary.Effect.FILESYSTEM_WRITE,),
                (),
            )


def test_partial_or_conflicting_installation_refuses() -> None:
    opened = effect_boundary.REGISTRY_BY_ID[IDS[0]]
    fake = SimpleNamespace(
        EntrypointSpec=effect_boundary.EntrypointSpec,
        GuardAnchor=effect_boundary.GuardAnchor,
        Surface=effect_boundary.Surface,
        Effect=effect_boundary.Effect,
        Wiring=effect_boundary.Wiring,
        ENTRYPOINTS=(opened,),
        REGISTRY_BY_ID=MappingProxyType({opened.id: opened}),
        registry_sha256=effect_boundary.registry_sha256,
        begin_effect=effect_boundary.begin_effect,
        check_conformance=effect_boundary.check_conformance,
    )
    with pytest.raises(RuntimeError, match="partially or incorrectly"):
        install_promotion_execution_rows(fake)


def test_registry_mapping_is_immutable() -> None:
    with pytest.raises(TypeError):
        effect_boundary.REGISTRY_BY_ID["kernel.promotion_execution.extra"] = _installed_rows()[0]
