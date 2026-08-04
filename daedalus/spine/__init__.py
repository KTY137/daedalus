"""daedalus.spine -- Mission Spine light.

The durable intent ledger for the self-improvement loop: intent is recorded and
COMMITTED before the external effect, so a crash can never leave an effect the
system has no record of intending. See :mod:`daedalus.spine.ledger` for the
crash-window contract (closed by effect identification, not by the key alone).
"""
from .ledger import (
    DEFAULT_BUSY_TIMEOUT_MS,
    DEFAULT_DB_PATH,
    SCHEMA_VERSION,
    STATE_COMPLETED,
    STATE_FAILED,
    STATE_INTENDED,
    TERMINAL_STATES,
    Intent,
    IntentAlreadyResolved,
    IntentEvent,
    SpineError,
    SpineLedger,
    UnknownIntent,
    canonical_json,
    canonical_sha,
    default_db_path,
)
from .durability import (
    Gate0DurabilityError,
    Gate0DurabilityStatus,
    enforce_gate0_durability,
    inspect_gate0_durability,
    open_gate0_spine_writer,
)
from .writer_inventory import (
    WriterCallsite,
    WriterInventory,
    WriterInventoryError,
    scan_event_store_writers,
)

# Controlled strangler installation: normal imports of
# ``daedalus.spine.effect_boundary`` execute this package initializer first, so
# the registry tuple, mapping and captured defaults are updated before a caller
# can observe them. The rows remain LOCAL_GUARDS until a later packet composes
# EffectLease, runtime-conformance and Docker-sandbox authority.
from . import effect_boundary as _effect_boundary
from .promotion_effect_rows import (
    install_promotion_effect_rows as _install_promotion_effect_rows,
)

_install_promotion_effect_rows(_effect_boundary)
del _install_promotion_effect_rows
del _effect_boundary


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
