"""Historical compatibility facade for the canonical event spine.

Event-envelope, ledger, and durability implementations now live under
``daedalus.kernel.events``.  This package keeps the public API lazy and stable;
the writer inventory remains at its existing locator until its own packet.
"""

from __future__ import annotations

from importlib import import_module
from typing import Final

_EXPORTS: Final = {
    **{
        name: "daedalus.kernel.events.ledger"
        for name in (
            "DEFAULT_BUSY_TIMEOUT_MS",
            "DEFAULT_DB_PATH",
            "SCHEMA_VERSION",
            "STATE_COMPLETED",
            "STATE_FAILED",
            "STATE_INTENDED",
            "TERMINAL_STATES",
            "Intent",
            "IntentAlreadyResolved",
            "IntentEvent",
            "SpineError",
            "SpineLedger",
            "UnknownIntent",
            "canonical_json",
            "canonical_sha",
            "default_db_path",
        )
    },
    **{
        name: "daedalus.kernel.events.durability"
        for name in (
            "Gate0DurabilityError",
            "Gate0DurabilityStatus",
            "enforce_gate0_durability",
            "inspect_gate0_durability",
            "open_gate0_spine_writer",
        )
    },
    **{
        name: "daedalus.spine.writer_inventory"
        for name in (
            "WriterCallsite",
            "WriterInventory",
            "WriterInventoryError",
            "scan_event_store_writers",
        )
    },
}

# Preserve the historical public order exactly; callers and inventory tests may
# treat it as a stable compatibility contract.
__all__ = [
    "DEFAULT_BUSY_TIMEOUT_MS",
    "DEFAULT_DB_PATH",
    "Gate0DurabilityError",
    "Gate0DurabilityStatus",
    "SCHEMA_VERSION",
    "STATE_COMPLETED",
    "STATE_FAILED",
    "STATE_INTENDED",
    "TERMINAL_STATES",
    "Intent",
    "IntentAlreadyResolved",
    "IntentEvent",
    "SpineError",
    "SpineLedger",
    "UnknownIntent",
    "WriterCallsite",
    "WriterInventory",
    "WriterInventoryError",
    "canonical_json",
    "canonical_sha",
    "default_db_path",
    "enforce_gate0_durability",
    "inspect_gate0_durability",
    "open_gate0_spine_writer",
    "scan_event_store_writers",
]


def __getattr__(name: str):
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
