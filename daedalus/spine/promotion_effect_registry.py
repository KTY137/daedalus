"""Install promotion-execution descriptors into the canonical effect registry.

The large historical registry in :mod:`daedalus.spine.effect_boundary` remains
canonical.  This module is a narrow strangler adapter: package initialization
passes that module explicitly, the inert descriptors are materialized with the
canonical contract types, and exactly three non-central rows are appended.

No effect is executed here.  In particular, this adapter does not create an
EffectLease, start a runtime, open a sandbox, issue OwnerApproval, or upgrade a
row to ``central``.
"""
from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import Any

from .promotion_effect_rows import materialize_promotion_execution_rows


_EXPECTED_IDS = (
    "kernel.promotion_execution.open",
    "kernel.promotion_execution.begin",
    "kernel.promotion_execution.complete",
)
_ANCHOR_CALLS: dict[str, tuple[str, ...]] = {
    "kernel.promotion_execution.open": (
        "open_gate0_spine_writer",
        "_install_single_start_invariant",
    ),
    "kernel.promotion_execution.begin": ("record_intent",),
    "kernel.promotion_execution.complete": ("mark_completed",),
}
_MIGRATION = (
    "Compose the exact persisted EffectLease, Runtime Manifest, current "
    "RuntimeConformanceReceipt, kill-switch generation and selected Docker "
    "sandbox before upgrading this row from local_guards to central."
)


def _canonical_rows(boundary: Any) -> tuple[Any, ...]:
    rows = materialize_promotion_execution_rows(
        entrypoint_spec=boundary.EntrypointSpec,
        surface_values={value.value: value for value in boundary.Surface},
        effect_values={value.value: value for value in boundary.Effect},
        wiring_values={value.value: value for value in boundary.Wiring},
    )
    if tuple(row.id for row in rows) != _EXPECTED_IDS:
        raise RuntimeError("promotion execution rows have an unexpected identity set")

    anchored: list[Any] = []
    for row in rows:
        calls = _ANCHOR_CALLS.get(row.id)
        if not calls:
            raise RuntimeError("promotion execution row has no exact source anchor")
        anchored.append(
            replace(
                row,
                anchors=tuple(
                    boundary.GuardAnchor(target=row.target, call=call)
                    for call in calls
                ),
                migration=_MIGRATION,
            )
        )
    return tuple(anchored)


def _refresh_captured_registry_defaults(boundary: Any) -> None:
    """Refresh historical function defaults after the immutable projection moves."""
    boundary.registry_sha256.__defaults__ = (boundary.ENTRYPOINTS,)
    boundary.begin_effect.__kwdefaults__ = {
        **(boundary.begin_effect.__kwdefaults__ or {}),
        "registry": boundary.REGISTRY_BY_ID,
    }
    boundary.check_conformance.__kwdefaults__ = {
        **(boundary.check_conformance.__kwdefaults__ or {}),
        "registry": boundary.ENTRYPOINTS,
    }


def install_promotion_execution_rows(boundary: Any) -> None:
    """Append exactly three local-guard rows to the canonical registry.

    Duplicate IDs, partial installations, conflicting rows, reordered retained
    rows and stale registry projections refuse. Repeating the exact installation
    is idempotent and repairs only the captured immutable defaults.
    """
    required = _canonical_rows(boundary)
    existing = {row.id: row for row in boundary.ENTRYPOINTS}
    if len(existing) != len(boundary.ENTRYPOINTS):
        raise RuntimeError("canonical effect registry contains duplicate ids")

    present = tuple(existing.get(row.id) for row in required)
    if any(row is not None for row in present):
        if present != required:
            raise RuntimeError(
                "promotion execution rows are partially or incorrectly installed"
            )
        if tuple(boundary.ENTRYPOINTS[-len(required) :]) != required:
            raise RuntimeError(
                "promotion execution rows are not the exact ordered registry suffix"
            )
        expected_mapping = {row.id: row for row in boundary.ENTRYPOINTS}
        if dict(boundary.REGISTRY_BY_ID) != expected_mapping:
            raise RuntimeError("canonical registry tuple and mapping disagree")
        _refresh_captured_registry_defaults(boundary)
        return

    boundary.ENTRYPOINTS = (*boundary.ENTRYPOINTS, *required)
    boundary.REGISTRY_BY_ID = MappingProxyType(
        {row.id: row for row in boundary.ENTRYPOINTS}
    )
    if len(boundary.REGISTRY_BY_ID) != len(boundary.ENTRYPOINTS):
        raise RuntimeError("promotion execution installation created duplicate ids")
    _refresh_captured_registry_defaults(boundary)


__all__ = ["install_promotion_execution_rows"]
