from __future__ import annotations

import ast
import dataclasses
import inspect
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import daedalus.kernel.promotion_receipts as receipts
from daedalus.kernel.promotion import PromotionAuthorization
from daedalus.spine.envelope import canonical_sha


NOW = datetime(2026, 8, 3, 21, 0, tzinfo=timezone.utc)
PRIMARY = "1" * 64


def _authorization(**changes) -> PromotionAuthorization:
    body = {
        "promotion_id": "promotion-review-1",
        "candidate_artifact_sha256": "2" * 64,
        "evidence_packet_sha256": "3" * 64,
        "source_revision": "a" * 40,
        "target_ref": "refs/heads/experimental",
        "live_target_revision": "b" * 40,
        "approval_consumption_sha256": "4" * 64,
    }
    body.update(changes)
    return PromotionAuthorization(**body, authorization_sha256=canonical_sha(body))


def _successful_report() -> dict[str, object]:
    return {
        "promoted": [{"task_id": "task-1", "promoted": True}],
        "refused": [],
        "not_gated": [],
        "integration_branch": "integration-review-1",
    }


def test_restart_replay_uses_persisted_start_time_not_retry_clock(tmp_path) -> None:
    ledger = receipts.PromotionLedger(tmp_path / "promotion.sqlite3")
    first = ledger.begin(
        _authorization(),
        start_id="start-review-1",
        primary_checkout_before_sha256=PRIMARY,
        started_at=NOW,
    )
    assert first.execute

    replay = receipts.PromotionLedger(tmp_path / "promotion.sqlite3").begin(
        _authorization(),
        start_id="start-review-1",
        primary_checkout_before_sha256=PRIMARY,
        started_at=NOW + timedelta(days=7),
    )
    assert not replay.execute
    assert replay.pending_reconciliation
    assert replay.start == first.start
    assert replay.start.started_at == NOW.isoformat(timespec="microseconds")


def test_naive_start_and_terminal_timestamps_are_refused(tmp_path) -> None:
    ledger = receipts.PromotionLedger(tmp_path / "promotion.sqlite3")
    with pytest.raises(ValueError, match="timezone-aware"):
        ledger.begin(
            _authorization(),
            start_id="start-review-1",
            primary_checkout_before_sha256=PRIMARY,
            started_at=datetime(2026, 8, 3, 21, 0),
        )

    start = ledger.begin(
        _authorization(),
        start_id="start-review-1",
        primary_checkout_before_sha256=PRIMARY,
        started_at=NOW,
    ).start
    with pytest.raises(ValueError, match="timezone-aware"):
        ledger.complete(
            start,
            receipt_id="receipt-review-1",
            outcome="succeeded",
            report=_successful_report(),
            primary_checkout_after_sha256=PRIMARY,
            integration_branch="integration-review-1",
            integration_revision="c" * 40,
            completed_at=datetime(2026, 8, 3, 21, 1),
        )


def test_schema_required_fields_match_canonical_receipt_contract() -> None:
    root = Path(__file__).resolve().parents[2]
    schema = json.loads(
        (root / "configs/schemas/promotion-receipt-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    contract_fields = {field.name for field in dataclasses.fields(receipts.PromotionReceipt)}
    expected = {"contract_type", "contract_version", *contract_fields}
    assert set(schema["required"]) == expected
    assert set(schema["properties"]) == expected
    assert schema["additionalProperties"] is False
    assert schema["properties"]["contract_type"]["const"] == (
        receipts.PromotionReceipt.CONTRACT_TYPE
    )
    assert schema["properties"]["contract_version"]["const"] == (
        receipts.PromotionReceipt.CONTRACT_VERSION
    )


def test_receipt_module_has_no_repository_or_provider_effect_primitives() -> None:
    source = inspect.getsource(receipts)
    tree = ast.parse(source)
    imported_roots: set[str] = set()
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Name):
                called_names.add(function.id)
            elif isinstance(function, ast.Attribute):
                called_names.add(function.attr)

    assert imported_roots.isdisjoint(
        {"subprocess", "shutil", "requests", "httpx", "urllib", "docker"}
    )
    assert called_names.isdisjoint(
        {
            "Popen",
            "system",
            "rename",
            "unlink",
            "rmtree",
            "copytree",
            "checkout",
            "merge",
            "push",
        }
    )
    assert "git worktree" not in source
    assert "git push" not in source
    assert "merge_pull_request" not in source


def test_sqlite_authority_and_replay_decision_are_explicit_in_source() -> None:
    source = inspect.getsource(receipts)
    for required in (
        "PRAGMA foreign_keys=ON",
        "PRAGMA journal_mode=WAL",
        "PRAGMA synchronous=FULL",
        "PRAGMA busy_timeout=30000",
        'connection.execute("BEGIN IMMEDIATE")',
        "authorization_sha256 TEXT NOT NULL UNIQUE",
        "approval_consumption_sha256 TEXT NOT NULL UNIQUE",
        "receipt_sha256 TEXT NOT NULL UNIQUE",
        "start_sha256 TEXT NOT NULL UNIQUE",
        "execute=False",
        "pending_reconciliation",
        "persisted promotion receipt digest mismatch",
        "primary checkout identity changed",
    ):
        assert required in source


def test_authorization_and_terminal_bindings_are_not_optional() -> None:
    source = inspect.getsource(receipts)
    assert "authorization_sha256 != canonical_sha(authorization_body)" in source
    assert "promotion authorization digest does not bind its fields" in source
    assert "successful promotion receipt requires integration branch and revision" in source
    assert "successful receipt requires exactly one promoted result" in source
    assert "promotion report integration branch mismatch" in source
    assert "promotion completion is not bound to the persisted start" in source


def test_contract_parser_rejects_extra_fields_and_stale_provenance(tmp_path) -> None:
    ledger = receipts.PromotionLedger(tmp_path / "ledger.sqlite3")
    start = ledger.begin(
        _authorization(),
        start_id="start-review-parse",
        primary_checkout_before_sha256=PRIMARY,
        started_at=NOW,
    ).start
    completion = ledger.complete(
        start,
        receipt_id="receipt-review-parse",
        outcome="succeeded",
        report=_successful_report(),
        primary_checkout_after_sha256=PRIMARY,
        integration_branch="integration-review-1",
        integration_revision="c" * 40,
        completed_at=NOW + timedelta(seconds=1),
    )
    payload = completion.receipt.to_dict()
    payload["extra"] = True
    with pytest.raises(ValueError, match="extra"):
        receipts.PromotionReceipt.from_dict(payload)

    payload = completion.receipt.to_dict()
    payload["provenance"]["source_revision"] = "d" * 40
    with pytest.raises(ValueError, match="source_revision"):
        receipts.PromotionReceipt.from_dict(payload)
