from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.gates.provider_observation_persistence_inventory import (
    ProviderObservationPersistenceInventoryError,
    scan_provider_observation_persistence,
)


REVISION = "1" * 40
SOURCE_PATH = Path("daedalus/runtimes/provider_observation.py")
ROOT = Path(__file__).resolve().parents[2]


FIXTURE = '''
import sqlite3

class ProviderObservationBindingLedger:
    def __init__(self, path):
        self.path = path
        self._initialize()

    def _connect(self):
        return sqlite3.connect(self.path)

    def _initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS provider_observation_bindings (
                    execution_id TEXT PRIMARY KEY
                )
            """)

    def bind_start(self, authority):
        connection = self._connect()
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute("SELECT 1").fetchone()
        if row is not None:
            connection.execute("ROLLBACK")
            return row
        connection.execute("""
            INSERT INTO provider_observation_bindings (execution_id)
            VALUES (?)
        """, (authority.execution_id,))
        connection.commit()

    def load(self, execution_id):
        with self._connect() as connection:
            return connection.execute("SELECT 1").fetchone()

    def require_bound(self, authority):
        return self.load(authority.execution_id)
'''.lstrip()


def _root(tmp_path: Path, source: str = FIXTURE) -> Path:
    path = tmp_path / SOURCE_PATH
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    return tmp_path


def test_real_provider_observation_source_has_all_known_blocking_surfaces() -> None:
    inventory = scan_provider_observation_persistence(ROOT, source_revision=REVISION)
    assert len(inventory.surfaces) == 11
    assert len(inventory.blockers) == 11
    assert inventory.closed is False
    report = inventory.to_dict()
    assert report["inventory_only"] is True
    assert report["canonical_inventory_integrated"] is False
    assert report["guard_contracts_complete"] is False
    assert report["primary_checkout_mutation_excluded"] is False
    assert report["blocker_count"] == report["surface_count"] == 11
    assert {row["wiring"] for row in report["surfaces"]} == {"inventory_only"}
    assert {row["guard_contract_bound"] for row in report["surfaces"]} == {False}


def test_fixture_inventory_is_deterministic_and_content_addressed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    first = scan_provider_observation_persistence(root, source_revision=REVISION)
    second = scan_provider_observation_persistence(root, source_revision=REVISION)
    assert first == second
    assert first.digest == second.digest
    assert first.surfaces == tuple(sorted(first.surfaces))
    assert len(first.surfaces) == 11
    payload = first.to_dict()
    assert len(payload["digest"]) == 64
    assert json.loads(json.dumps(payload, sort_keys=True)) == payload


def test_every_expected_public_or_internal_mutation_path_is_named(tmp_path: Path) -> None:
    inventory = scan_provider_observation_persistence(
        _root(tmp_path), source_revision=REVISION
    )
    functions = [row.function for row in inventory.surfaces]
    assert functions.count("ProviderObservationBindingLedger.__init__") == 1
    assert functions.count("ProviderObservationBindingLedger._connect") == 1
    assert functions.count("ProviderObservationBindingLedger._initialize") == 2
    assert functions.count("ProviderObservationBindingLedger.bind_start") == 5
    assert functions.count("ProviderObservationBindingLedger.load") == 1
    assert functions.count("ProviderObservationBindingLedger.require_bound") == 1
    operations = {row.operation for row in inventory.surfaces}
    assert "constructor-implicitly-creates-parent-database-and-schema" in operations
    assert "nominal-read-can-create-empty-sqlite-file" in operations
    assert "replay-and-recovery-read-transitively-can-create-sqlite-file" in operations
    assert "insert-authenticated-provider-observation-binding" in operations


@pytest.mark.parametrize(
    "revision",
    [None, 1, True, "", "A" * 40, "1" * 39, "1" * 41, "g" * 40],
)
def test_malformed_revision_refuses(tmp_path: Path, revision) -> None:
    with pytest.raises(
        ProviderObservationPersistenceInventoryError,
        match="lowercase 40-hex",
    ):
        scan_provider_observation_persistence(
            _root(tmp_path), source_revision=revision
        )


def test_missing_non_utf8_and_invalid_python_sources_refuse(tmp_path: Path) -> None:
    with pytest.raises(
        ProviderObservationPersistenceInventoryError, match="could not be read"
    ):
        scan_provider_observation_persistence(tmp_path, source_revision=REVISION)

    path = tmp_path / SOURCE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(ProviderObservationPersistenceInventoryError, match="not UTF-8"):
        scan_provider_observation_persistence(tmp_path, source_revision=REVISION)

    path.write_text("class ProviderObservationBindingLedger(:\n", encoding="utf-8")
    with pytest.raises(ProviderObservationPersistenceInventoryError, match="parsed"):
        scan_provider_observation_persistence(tmp_path, source_revision=REVISION)


def test_missing_or_duplicate_required_anchor_refuses(tmp_path: Path) -> None:
    missing = FIXTURE.replace("        self._initialize()\n", "        pass\n")
    with pytest.raises(
        ProviderObservationPersistenceInventoryError,
        match="exactly one implicit initializer",
    ):
        scan_provider_observation_persistence(
            _root(tmp_path / "missing", missing), source_revision=REVISION
        )

    duplicate = FIXTURE.replace(
        "        return sqlite3.connect(self.path)\n",
        "        sqlite3.connect(self.path)\n        return sqlite3.connect(self.path)\n",
    )
    with pytest.raises(
        ProviderObservationPersistenceInventoryError,
        match="exactly one sqlite connect",
    ):
        scan_provider_observation_persistence(
            _root(tmp_path / "duplicate", duplicate), source_revision=REVISION
        )


def test_byte_drift_changes_inventory_digest_without_laundering_blockers(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path, FIXTURE)
    before = scan_provider_observation_persistence(root, source_revision=REVISION)
    path = root / SOURCE_PATH
    path.write_text(FIXTURE + "\n# byte drift\n", encoding="utf-8")
    after = scan_provider_observation_persistence(root, source_revision=REVISION)
    assert after.source_sha256 != before.source_sha256
    assert after.digest != before.digest
    assert after.blockers == before.blockers
    assert after.closed is False


def test_source_symlink_refuses_when_platform_supports_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "actual.py"
    target.write_text(FIXTURE, encoding="utf-8")
    path = tmp_path / SOURCE_PATH
    path.parent.mkdir(parents=True)
    try:
        path.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable on this platform")
    with pytest.raises(ProviderObservationPersistenceInventoryError, match="symlink"):
        scan_provider_observation_persistence(tmp_path, source_revision=REVISION)
