"""Canonical event-envelope, intent-ledger, and durability ownership.

The owner package is lazy so importing one pure envelope helper does not also
load SQLite durability machinery.  ``daedalus.spine`` remains the historical
compatibility surface while callers migrate to this hierarchy.
"""

from __future__ import annotations

from importlib import import_module
from typing import Final

_SUBMODULES: Final = frozenset({"durability", "envelope", "ledger"})

_EXPORTS: Final = {
    **{
        name: "envelope"
        for name in (
            "CONVERTED_PRODUCERS",
            "GEN_AI",
            "IN_TOTO_STATEMENT_TYPE",
            "LOCAL_TO_GEN_AI",
            "PREDICATE_BRIDGE_REPORT",
            "PREDICATE_BRIDGE_REQUEST",
            "PREDICATE_LOOP_LEDGER",
            "PREDICATE_SPINE_INTENT",
            "TRACE_ID_ENV",
            "TRACE_KEY",
            "UNCONVERTED_PRODUCERS",
            "adopt_trace",
            "bind_trace_id",
            "canonical_json",
            "canonical_sha",
            "current_trace_id",
            "gen_ai_attributes",
            "is_statement",
            "new_trace_id",
            "stamp",
            "statement",
            "subject_for",
            "trace_context",
            "trace_of",
            "unwrap",
        )
    },
    **{
        name: "ledger"
        for name in (
            "DEFAULT_BUSY_TIMEOUT_MS",
            "DEFAULT_DB_PATH",
            "ROOT",
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
            "default_db_path",
        )
    },
    **{
        name: "durability"
        for name in (
            "Gate0DurabilityError",
            "Gate0DurabilityStatus",
            "enforce_gate0_durability",
            "inspect_gate0_durability",
            "open_gate0_spine_writer",
        )
    },
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name in _SUBMODULES:
        value = import_module(f"{__name__}.{name}")
    else:
        module_name = _EXPORTS.get(name)
        if module_name is None:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
        value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_SUBMODULES) | set(__all__))
