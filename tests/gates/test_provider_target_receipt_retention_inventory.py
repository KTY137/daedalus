from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.gates.provider_target_receipt_retention_inventory import (
    ProviderTargetReceiptRetentionInventoryError,
    scan_provider_target_receipt_retention,
)
from daedalus.spine.envelope import canonical_json

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "daedalus/runtimes/provider/target_receipt_ledger.py"
REVISION = "0df759d1fd9bc5d83e9fc72f1c850756afa93fe5"
# Re-pinned in G1-PKG-01. The blob moved because the module moved into
# daedalus/runtimes/provider/ and its own imports went from one dot to two;
# `git diff` over the relocation shows import lines and nothing else.
SOURCE_GIT_BLOB_SHA1 = "cc9dd91f55c543030e82e0e1f526766419cbd98a"
PRE_HARDENING_REVISION = "b2bda280f8f98d6e977e092c5429da3c85427a33"
EXPECTED_OPERATIONS = {
    "open-canonical-event-store-writer-transaction",
    "create-or-reverify-partial-unique-index",
    "append-receipt-retention-intent",
    "invoke-schema-invariant-writer",
    "invoke-canonical-intent-writer",
    "publish-authenticated-receipt-bytes",
    "append-receipt-retention-terminal",
}


def _git_blob_sha1(raw: bytes) -> str:
    header = f"blob {len(raw)}\0".encode("ascii")
    return hashlib.sha1(header + raw, usedforsecurity=False).hexdigest()


def _fixture_root(tmp_path: Path, raw: bytes | None = None) -> Path:
    target = tmp_path / "repo/daedalus/runtimes/provider/target_receipt_ledger.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(SOURCE.read_bytes() if raw is None else raw)
    return tmp_path / "repo"


def test_inventory_is_rebound_to_topology_hardened_parent() -> None:
    raw = SOURCE.read_bytes()
    report = scan_provider_target_receipt_retention(ROOT, source_revision=REVISION)

    assert REVISION != PRE_HARDENING_REVISION
    assert _git_blob_sha1(raw) == SOURCE_GIT_BLOB_SHA1
    assert report.source_revision == REVISION
    assert report.source_sha256 == hashlib.sha256(raw).hexdigest()
    assert report.source_size == len(raw)
    assert {row.operation for row in report.surfaces} == EXPECTED_OPERATIONS


def test_inventory_is_deterministic_and_explicitly_blocking() -> None:
    first = scan_provider_target_receipt_retention(ROOT, source_revision=REVISION)
    second = scan_provider_target_receipt_retention(ROOT, source_revision=REVISION)

    assert first == second
    assert first.digest == second.digest
    assert len(first.surfaces) == 7
    assert {row.operation for row in first.surfaces} == EXPECTED_OPERATIONS
    assert all(row.blocking for row in first.surfaces)

    payload = first.to_dict()
    assert payload["closed"] is False
    assert payload["inventory_only"] is True
    assert payload["canonical_inventory_integrated"] is False
    assert payload["guard_contracts_complete"] is False
    assert payload["effect_lease_semantics_verified"] is False
    assert payload["primary_checkout_mutation_excluded"] is False
    assert payload["surface_count"] == payload["blocker_count"] == 7
    assert all(row["wiring"] == "inventory_only" for row in payload["surfaces"])
    assert all(row["guard_contract_bound"] is False for row in payload["surfaces"])
    assert all(row["effect_lease_consumed"] is False for row in payload["surfaces"])
    assert canonical_json(json.loads(canonical_json(payload))) == canonical_json(payload)


def test_revision_and_source_bytes_are_bound(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path)
    first = scan_provider_target_receipt_retention(root, source_revision="1" * 40)
    second = scan_provider_target_receipt_retention(root, source_revision="2" * 40)
    assert first.source_sha256 == second.source_sha256
    assert first.digest != second.digest

    path = root / "daedalus/runtimes/provider/target_receipt_ledger.py"
    path.write_bytes(path.read_bytes() + b"\n# byte-bound inventory test\n")
    changed = scan_provider_target_receipt_retention(root, source_revision="1" * 40)
    assert changed.source_sha256 != first.source_sha256
    assert changed.digest != first.digest


@pytest.mark.parametrize("revision", ["", "ABC", "f" * 39, "g" * 40, None])
def test_malformed_revision_refuses(revision: object) -> None:
    with pytest.raises(ProviderTargetReceiptRetentionInventoryError):
        scan_provider_target_receipt_retention(ROOT, source_revision=revision)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda source: source.replace(
            "self.source_store.put_bytes(payload)",
            "self.source_store.read_bytes(payload)",
            1,
        ),
        lambda source: source.replace(
            "self.spine.mark_completed(",
            "self.spine.mark_completed(); self.spine.mark_completed(",
            1,
        ),
        lambda source: source.replace(
            "connection.execute(expected)",
            'connection.execute(expected); connection.execute("PRAGMA user_version")',
            1,
        ),
        lambda source: source.replace(
            "class ProviderTargetReceiptLedger:",
            "class RenamedProviderTargetReceiptLedger:",
            1,
        ),
    ],
)
def test_missing_duplicate_renamed_or_unclassified_anchor_refuses(
    tmp_path: Path,
    mutation,
) -> None:
    source = SOURCE.read_text(encoding="utf-8")
    root = _fixture_root(tmp_path, mutation(source).encode("utf-8"))
    with pytest.raises(ProviderTargetReceiptRetentionInventoryError):
        scan_provider_target_receipt_retention(root, source_revision=REVISION)


@pytest.mark.parametrize(
    "raw",
    [
        b"\xef\xbb\xbf" + SOURCE.read_bytes(),
        SOURCE.read_bytes() + b"\x00",
        b"\xff",
        b"class ProviderTargetReceiptLedger(:\n",
    ],
)
def test_malformed_source_refuses(tmp_path: Path, raw: bytes) -> None:
    root = _fixture_root(tmp_path, raw)
    with pytest.raises(ProviderTargetReceiptRetentionInventoryError):
        scan_provider_target_receipt_retention(root, source_revision=REVISION)


def test_source_symlink_refuses_when_supported(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    target = tmp_path / "retention.py"
    target.write_bytes(SOURCE.read_bytes())
    link = root / "daedalus/runtimes/provider/target_receipt_ledger.py"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ProviderTargetReceiptRetentionInventoryError):
        scan_provider_target_receipt_retention(root, source_revision=REVISION)


def test_parent_directory_symlink_refuses_when_supported(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    external = tmp_path / "external/runtimes"
    external.mkdir(parents=True)
    (external / "provider_target_receipt_ledger.py").write_bytes(SOURCE.read_bytes())
    (root / "daedalus").mkdir(parents=True)
    link = root / "daedalus/runtimes"
    try:
        link.symlink_to(external, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")
    with pytest.raises(ProviderTargetReceiptRetentionInventoryError):
        scan_provider_target_receipt_retention(root, source_revision=REVISION)


def test_cli_emits_canonical_blocking_report() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/report_provider_target_receipt_retention_inventory.py",
            str(ROOT),
            "--source-revision",
            REVISION,
        ],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert completed.stderr == ""
    payload = json.loads(completed.stdout)
    assert payload["source_revision"] == REVISION
    assert payload["closed"] is False
    assert payload["surface_count"] == 7
    assert completed.stdout.strip() == canonical_json(payload)
