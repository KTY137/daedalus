from __future__ import annotations

import inspect
import json
from pathlib import Path

import daedalus.spine.durability as durability


ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs/work-packets/G0-ES-14_EVENT_STORE_DURABILITY.json"


def test_profile_does_not_create_a_second_event_store_authority() -> None:
    source = inspect.getsource(durability)
    assert "sqlite3.connect" not in source
    assert "CREATE TABLE" not in source
    assert "CREATE INDEX" not in source
    assert "SpineLedger(" not in source
    assert "record_intent(" not in source
    assert "mark_completed(" not in source
    assert "mark_failed(" not in source


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
