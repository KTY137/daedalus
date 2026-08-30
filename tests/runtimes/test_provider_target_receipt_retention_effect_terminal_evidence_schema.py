# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from daedalus.runtimes.provider_target_receipt_retention_effect_terminal_evidence import (
    ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt,
)


SCHEMA_PATH = (
    Path(__file__).parents[2]
    / "configs"
    / "schemas"
    / "provider-target-receipt-retention-effect-terminal-evidence.schema.json"
)


def _payload():
    return ProviderTargetReceiptRetentionEffectTerminalEvidenceReceipt(
        source_revision="1" * 40,
        completed_evidence_sha256="2" * 64,
        provider_target_receipt_sha256="3" * 64,
        retention_execution_request_sha256="4" * 64,
        retention_effect_lease_sha256="5" * 64,
        start_receipt_sha256="6" * 64,
        terminal_receipt_sha256="7" * 64,
        terminal_output_set_sha256="8" * 64,
        effect_execution_evidence_sha256="9" * 64,
        effect_lease_store_identity_sha256="a" * 64,
        effect_lease_store_path="/tmp/effect-leases.sqlite3",
        terminal_finished_at="2026-08-05T08:01:00.000000+00:00",
    ).to_dict()


def test_effect_terminal_evidence_schema_is_draft_2020_12_and_exact() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate(_payload())

    extra = _payload()
    extra["unexpected"] = True
    assert list(validator.iter_errors(extra))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_revision", "f" * 64),
        ("completed_evidence_sha256", "x" * 64),
        ("terminal_finished_at", "2026-08-05T08:01:00Z"),
        ("effect_lease_store_path", "bad\npath"),
        ("persisted_effect_terminal_verified", False),
        ("automatic_reexecution_allowed", True),
        ("owner_approval_issued", True),
        ("promotion_authorized", True),
        ("closed", True),
    ],
)
def test_effect_terminal_evidence_schema_refuses_malformed_or_escalated_claims(
    field,
    value,
) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = _payload()
    payload[field] = value
    assert list(Draft202012Validator(schema).iter_errors(payload))
