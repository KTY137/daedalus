from __future__ import annotations

import inspect
import json
import re
from pathlib import Path

import daedalus.spine.durability as durability
from daedalus.spine.ledger import SpineLedger


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/work-packets/G0-ES-14_EVENT_STORE_DURABILITY.json"


def test_profile_does_not_create_a_second_event_store_authority() -> None:
    """Invariant 1, one kernel: this module hardens the canonical Event Store,
    it does not become a second one.

    The literal ``"SpineLedger(" not in source`` that used to stand for that
    was a proxy, and c962517 ("open canonical Event Store at FULL before
    migration") made the proxy wrong without making the invariant wrong: the
    module now owns the Gate-0 writer factory, whose whole point is that a
    production writer reaches ``synchronous=FULL`` BEFORE the canonical
    ledger's first migration write -- which is only reachable from inside the
    opening path. That factory constructs ``_Gate0OpeningSpineLedger``, and the
    forbidden substring is inside that name.

    The check is therefore structural instead of lexical, and it is strictly
    the stronger one: it still forbids a second connection, a second schema and
    any write path, and it now also pins that the module instantiates exactly
    ONE ledger type, that the type is a PRIVATE subclass of the one canonical
    ledger, that it is not exported, and that it overrides nothing but the
    connection-local opening pragma. A real second authority -- an independent
    class, a second exported ledger name, an override of a schema or
    transaction method -- fails here; the substring could not have caught any
    of those.
    """
    source = inspect.getsource(durability)
    assert "sqlite3.connect" not in source
    assert "CREATE TABLE" not in source
    assert "CREATE INDEX" not in source
    assert "record_intent(" not in source
    assert "mark_completed(" not in source
    assert "mark_failed(" not in source

    # Exactly one ledger type is INSTANTIATED here, and it is the private
    # opening profile. `(?<!class )` drops the class statement itself; the base
    # class in `(SpineLedger)` and the `isinstance(..., SpineLedger)` guards
    # are followed by `)`, never `(`, so they never match.
    constructed = set(re.findall(r"(?<!class )\b(\w*SpineLedger)\(", source))
    assert constructed == {"_Gate0OpeningSpineLedger"}, (
        f"durability.py instantiates ledger type(s) {sorted(constructed)}; "
        "only the private Gate-0 opening profile may be built here")

    opening = durability._Gate0OpeningSpineLedger
    assert issubclass(opening, SpineLedger), (
        "the opening profile must inherit the canonical ledger, not "
        "reimplement one")
    assert opening.__name__.startswith("_"), "the opening profile stays private"
    assert opening.__name__ not in durability.__all__, (
        "exporting the opening profile would publish a second ledger name")
    overrides = {name for name in vars(opening) if not name.startswith("__")}
    assert overrides == {"_apply_pragmas"}, (
        f"the opening profile overrides {sorted(overrides)}; it may specialize "
        "only the connection-local opening posture and must inherit every "
        "schema, transaction, read and write path unchanged")


def test_profile_refuses_persistent_journal_rewrite_and_reads_back_atomically() -> None:
    source = inspect.getsource(durability.enforce_gate0_durability)
    assert "existing WAL journal mode" in source
    assert "PRAGMA journal_mode=" not in source
    assert 'connection.execute("PRAGMA synchronous=FULL")' in source
    assert 'connection.execute("PRAGMA foreign_keys=ON")' in source
    assert "with lock:" in source
    assert source.count("_read_connection_status(connection)") == 2
    assert "if not status.satisfied" in source


def test_machine_status_contains_only_readback_not_unverified_claims() -> None:
    fields = tuple(durability.Gate0DurabilityStatus.__dataclass_fields__)
    assert fields == (
        "schema",
        "journal_mode",
        "synchronous",
        "busy_timeout_ms",
        "foreign_keys",
        "satisfied",
    )
    assert "power_loss_proven" not in fields
    assert "all_writers_migrated" not in fields


def test_fault_matrix_remains_partial_until_all_writer_and_power_faults_close() -> None:
    payload = json.loads(MATRIX.read_text(encoding="utf-8"))
    assert payload["schema"] == "daedalus-gate0-event-store-durability-review/1"
    assert payload["status"] == "partial"
    assert payload["security_boundary_claimed"] is False
    faults = {row["fault"]: row for row in payload["fault_matrix"]}
    assert faults["host_power_loss_or_storage_cache_loss"]["state"] == (
        "open_external_fault_harness"
    )
    blockers = {row["code"] for row in payload["migration_blockers"]}
    assert "writer.profile_not_centralized" in blockers
    assert "legacy.default_is_normal" in blockers
    assert "exact_head_execution_unavailable" in blockers
    assert "independent_review_missing" in blockers
    assert payload["verification_state"]["all_production_writers_migrated"] is False
