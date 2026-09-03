"""G1-HIER-03A acceptance for the single canonical event implementation."""

from __future__ import annotations

import ast
import importlib
import pickle
import sqlite3
from pathlib import Path

from daedalus.spine.effect_boundary import registry_sha256


REPO_ROOT = Path(__file__).resolve().parents[2]
EVENT_ROOT = REPO_ROOT / "daedalus" / "kernel" / "events"
LEGACY_ROOT = REPO_ROOT / "daedalus" / "spine"


def test_legacy_modules_are_exact_aliases_of_the_canonical_owners() -> None:
    for leaf in ("envelope", "ledger", "durability"):
        legacy = importlib.import_module(f"daedalus.spine.{leaf}")
        owner = importlib.import_module(f"daedalus.kernel.events.{leaf}")
        assert legacy is owner

    legacy_ledger = importlib.import_module("daedalus.spine.ledger")
    owner_ledger = importlib.import_module("daedalus.kernel.events.ledger")
    legacy_durability = importlib.import_module("daedalus.spine.durability")
    owner_durability = importlib.import_module(
        "daedalus.kernel.events.durability"
    )
    assert legacy_ledger.SpineLedger is owner_ledger.SpineLedger
    assert legacy_ledger._SCHEMA is owner_ledger._SCHEMA
    assert legacy_ledger._uri_path is owner_ledger._uri_path
    assert legacy_durability._read_connection_status is (
        owner_durability._read_connection_status
    )


def test_spine_package_public_inventory_and_order_are_unchanged() -> None:
    spine = importlib.import_module("daedalus.spine")
    assert spine.__all__ == [
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


def test_legacy_pickle_globals_resolve_to_owner_objects() -> None:
    owner_ledger = importlib.import_module("daedalus.kernel.events.ledger")
    owner_envelope = importlib.import_module("daedalus.kernel.events.envelope")
    assert pickle.loads(b"cdaedalus.spine.ledger\nIntent\n.") is owner_ledger.Intent
    assert pickle.loads(
        b"cdaedalus.spine.ledger\nSpineLedger\n."
    ) is owner_ledger.SpineLedger
    assert pickle.loads(
        b"cdaedalus.spine.envelope\ncanonical_json\n."
    ) is owner_envelope.canonical_json


def test_canonical_envelope_bytes_and_digest_are_unchanged() -> None:
    legacy = importlib.import_module("daedalus.spine.envelope")
    owner = importlib.import_module("daedalus.kernel.events.envelope")
    payload = {"z": 2, "a": [1, True, None]}
    expected = '{"a":[1,true,null],"z":2}'
    expected_sha256 = (
        "4d5c618c867797f4c7b4a63a6b49e19933d70aefa15ba79e520314818340e712"
    )
    assert legacy.canonical_json(payload) == expected
    assert owner.canonical_json(payload).encode("ascii") == expected.encode("ascii")
    assert legacy.canonical_sha(payload) == expected_sha256
    assert owner.canonical_sha(payload) == expected_sha256


def test_new_owner_writes_and_legacy_locator_replays_the_same_rows(tmp_path) -> None:
    owner = importlib.import_module("daedalus.kernel.events.ledger")
    legacy = importlib.import_module("daedalus.spine.ledger")
    db_path = tmp_path / "spine.sqlite3"

    with owner.SpineLedger(db_path) as ledger:
        intent = ledger.record_intent(
            "hierarchy.fixture",
            {"z": 2, "a": [1, True, None]},
            effect_key="fixture:one",
        )
        ledger.mark_completed(
            intent.id,
            effect_id="fixture:complete",
            result={"ok": True},
        )

    with legacy.SpineLedger(db_path, read_only=True) as replay:
        restored = replay.get(intent.id)
        assert restored is not None
        assert restored.payload_json == '{"a":[1,true,null],"z":2}'
        assert restored.payload_sha == (
            "4d5c618c867797f4c7b4a63a6b49e19933d70aefa15ba79e520314818340e712"
        )
        assert [event.state for event in replay.events(intent.id)] == [
            owner.STATE_INTENDED,
            owner.STATE_COMPLETED,
        ]

    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute(
            "SELECT kind, effect_key, payload, payload_sha FROM intents"
        ).fetchall() == [
            (
                "hierarchy.fixture",
                "fixture:one",
                '{"a":[1,true,null],"z":2}',
                "4d5c618c867797f4c7b4a63a6b49e19933d70aefa15ba79e520314818340e712",
            )
        ]
    finally:
        connection.close()


def test_durability_owner_and_facade_read_the_same_connection(tmp_path) -> None:
    ledger_owner = importlib.import_module("daedalus.kernel.events.ledger")
    durability_owner = importlib.import_module("daedalus.kernel.events.durability")
    durability_legacy = importlib.import_module("daedalus.spine.durability")

    ledger = durability_owner.open_gate0_spine_writer(tmp_path / "spine.sqlite3")
    try:
        assert type(ledger).__mro__[1] is ledger_owner.SpineLedger
        assert durability_legacy.inspect_gate0_durability(ledger).to_dict() == (
            durability_owner.inspect_gate0_durability(ledger).to_dict()
        )
        assert durability_owner.inspect_gate0_durability(ledger).satisfied is True
    finally:
        ledger.close()


def test_definitions_exist_only_at_the_new_owner_paths() -> None:
    expected = {
        "canonical_json": EVENT_ROOT / "envelope.py",
        "SpineLedger": EVENT_ROOT / "ledger.py",
        "Gate0DurabilityStatus": EVENT_ROOT / "durability.py",
        "open_gate0_spine_writer": EVENT_ROOT / "durability.py",
    }
    candidates = [
        *(EVENT_ROOT / f"{leaf}.py" for leaf in ("envelope", "ledger", "durability")),
        *(LEGACY_ROOT / f"{leaf}.py" for leaf in ("envelope", "ledger", "durability")),
    ]
    found = {name: [] for name in expected}
    for path in candidates:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in found:
                    found[node.name].append(path)
    assert found == {name: [path] for name, path in expected.items()}


def test_kernel_events_has_no_forbidden_dependency_edge() -> None:
    forbidden = (
        "daedalus.spine",
        "daedalus.gates",
        "daedalus.runtimes",
        "daedalus.providers",
        "daedalus.kairos",
        "daedalus.eval",
        "daedalus.chip_design",
    )
    violations: list[str] = []
    for path in sorted(EVENT_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                if name.startswith(forbidden):
                    violations.append(f"{path.relative_to(REPO_ROOT)}:{node.lineno}:{name}")
    assert violations == []


def test_effect_registry_digest_is_unchanged_by_structure_packet() -> None:
    assert registry_sha256() == (
        "44222aa9f9269eb1c9d9f5cf118786cbb1a1d602f6f3ca77aeb00d4f599214c9"
    )
