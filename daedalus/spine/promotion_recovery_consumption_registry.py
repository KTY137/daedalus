"""Install recovery-consumption rows and the exact scanner hook.

The historical :mod:`daedalus.spine.effect_boundary` module remains the sole
registry and scanner authority.  This strangler adapter consumes the reviewed
inventory delta, adds only its exact owner-decision guard and two non-central
rows, refreshes captured immutable defaults, and teaches the static scanner the
exact two writer methods.  It does not execute an effect, issue owner authority,
open SQLite, cancel an Effect Lease, invoke Git, or promote a candidate.
"""
from __future__ import annotations

from functools import wraps
from types import MappingProxyType
from typing import Any, Callable

from .promotion_recovery_consumption_inventory import (
    ENTRYPOINTS as INVENTORY_ENTRYPOINTS,
    GUARD_CONTRACTS as INVENTORY_GUARD_CONTRACTS,
    SCANNER_CLASS,
    SCANNER_METHODS,
    SCANNER_MODULE,
    recognizes_recovery_consumption_method,
)


_EXPECTED_IDS = (
    "kernel.promotion_recovery_consumption.initialize",
    "kernel.promotion_recovery_consumption.consume",
)
_SCANNER_MARKER = "daedalus-promotion-recovery-consumption-scanner/1"


def _anchors(boundary: Any, entrypoint_id: str) -> tuple[Any, ...]:
    prefix = (
        "daedalus.kernel.promotion_recovery_consumption:"
        "PromotionRecoveryConsumptionLedger."
    )
    if entrypoint_id == _EXPECTED_IDS[0]:
        return (
            boundary.GuardAnchor(target=prefix + "__init__", call="_initialize"),
            boundary.GuardAnchor(target=prefix + "_initialize", call="_connect_writer"),
        )
    if entrypoint_id == _EXPECTED_IDS[1]:
        return (
            boundary.GuardAnchor(
                target=prefix + "consume",
                call="verify_promotion_recovery_decision",
            ),
            boundary.GuardAnchor(target=prefix + "consume", call="_connect_writer"),
        )
    raise RuntimeError("unknown recovery-consumption entrypoint identity")


def _canonical_rows(boundary: Any) -> tuple[Any, ...]:
    if tuple(row.id for row in INVENTORY_ENTRYPOINTS) != _EXPECTED_IDS:
        raise RuntimeError("recovery-consumption inventory identities changed")
    rows: list[Any] = []
    for proposed in INVENTORY_ENTRYPOINTS:
        try:
            surface = boundary.Surface(proposed.surface)
            effects = tuple(boundary.Effect(value) for value in proposed.effects)
            wiring = boundary.Wiring(proposed.wiring)
        except ValueError as exc:
            raise RuntimeError(
                "recovery-consumption inventory contains an unknown canonical enum"
            ) from exc
        rows.append(
            boundary.EntrypointSpec(
                id=proposed.id,
                surface=surface,
                target=proposed.target,
                effects=effects,
                guard_contracts=proposed.guard_contracts,
                wiring=wiring,
                anchors=_anchors(boundary, proposed.id),
                notes=(
                    "Installed from the reviewed recovery-consumption inventory "
                    "delta; this row is intentionally non-central."
                ),
                migration=proposed.migration,
            )
        )
    return tuple(rows)


def _required_guards() -> dict[str, bool]:
    required = {row.id: row.implemented for row in INVENTORY_GUARD_CONTRACTS}
    if required != {"promotion.owner_recovery_decision": True}:
        raise RuntimeError("recovery-consumption guard inventory changed")
    return required


def _scanner_wrapper(
    boundary: Any,
    original: Callable[[Any, str], Any],
) -> Callable[[Any, str], Any]:
    @wraps(original)
    def classify(model: Any, qualname: str) -> Any:
        if "." in qualname:
            class_name, method = qualname.split(".", 1)
            if recognizes_recovery_consumption_method(
                model.module,
                class_name,
                method,
            ):
                return boundary.Surface.PYTHON
        return original(model, qualname)

    setattr(classify, "__daedalus_scanner_marker__", _SCANNER_MARKER)
    setattr(classify, "__daedalus_scanner_module__", SCANNER_MODULE)
    setattr(classify, "__daedalus_scanner_class__", SCANNER_CLASS)
    setattr(classify, "__daedalus_scanner_methods__", SCANNER_METHODS)
    return classify


def _validate_scanner(boundary: Any) -> bool:
    current = boundary._surface_for_function
    marker = getattr(current, "__daedalus_scanner_marker__", None)
    if marker is None:
        return False
    if marker != _SCANNER_MARKER:
        raise RuntimeError("conflicting recovery-consumption scanner hook")
    if getattr(current, "__daedalus_scanner_module__", None) != SCANNER_MODULE:
        raise RuntimeError("recovery-consumption scanner module changed")
    if getattr(current, "__daedalus_scanner_class__", None) != SCANNER_CLASS:
        raise RuntimeError("recovery-consumption scanner class changed")
    if getattr(current, "__daedalus_scanner_methods__", None) != SCANNER_METHODS:
        raise RuntimeError("recovery-consumption scanner methods changed")
    return True


def _refresh_captured_registry_defaults(boundary: Any) -> None:
    boundary.registry_sha256.__defaults__ = (boundary.ENTRYPOINTS,)
    boundary.begin_effect.__kwdefaults__ = {
        **(boundary.begin_effect.__kwdefaults__ or {}),
        "registry": boundary.REGISTRY_BY_ID,
    }
    boundary.check_conformance.__kwdefaults__ = {
        **(boundary.check_conformance.__kwdefaults__ or {}),
        "registry": boundary.ENTRYPOINTS,
    }


def install_promotion_recovery_consumption_inventory(boundary: Any) -> None:
    """Install the exact reviewed delta without claiming Gate-0 closure.

    Conflicting guards, partial rows, reordered retained rows, stale tuple/mapping
    projections and conflicting scanner hooks refuse before installation.  An
    exact repeated call is idempotent and repairs only captured registry defaults.
    """

    required_rows = _canonical_rows(boundary)
    required_guards = _required_guards()
    existing_rows = {row.id: row for row in boundary.ENTRYPOINTS}
    if len(existing_rows) != len(boundary.ENTRYPOINTS):
        raise RuntimeError("canonical effect registry contains duplicate ids")

    present_rows = tuple(existing_rows.get(row.id) for row in required_rows)
    if any(row is not None for row in present_rows):
        if present_rows != required_rows:
            raise RuntimeError(
                "recovery-consumption rows are partially or incorrectly installed"
            )
        if tuple(boundary.ENTRYPOINTS[-len(required_rows) :]) != required_rows:
            raise RuntimeError(
                "recovery-consumption rows are not the exact ordered registry suffix"
            )

    existing_guards = dict(boundary.GUARD_CONTRACT_IMPLEMENTED)
    for name, implemented in required_guards.items():
        if name in existing_guards and existing_guards[name] is not implemented:
            raise RuntimeError("conflicting recovery-consumption guard contract")

    scanner_installed = _validate_scanner(boundary)
    expected_mapping = {row.id: row for row in boundary.ENTRYPOINTS}
    if dict(boundary.REGISTRY_BY_ID) != expected_mapping:
        raise RuntimeError("canonical registry tuple and mapping disagree")

    if not all(row is not None for row in present_rows):
        boundary.ENTRYPOINTS = (*boundary.ENTRYPOINTS, *required_rows)
        boundary.REGISTRY_BY_ID = MappingProxyType(
            {row.id: row for row in boundary.ENTRYPOINTS}
        )
        if len(boundary.REGISTRY_BY_ID) != len(boundary.ENTRYPOINTS):
            raise RuntimeError(
                "recovery-consumption installation created duplicate ids"
            )

    if any(name not in existing_guards for name in required_guards):
        existing_guards.update(required_guards)
        boundary.GUARD_CONTRACT_IMPLEMENTED = MappingProxyType(existing_guards)
        boundary.POLICY_CONTRACTS = frozenset(existing_guards)

    if not scanner_installed:
        boundary._surface_for_function = _scanner_wrapper(
            boundary,
            boundary._surface_for_function,
        )

    _refresh_captured_registry_defaults(boundary)


__all__ = ["install_promotion_recovery_consumption_inventory"]
