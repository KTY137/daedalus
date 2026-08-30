# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKET = ROOT / (
    "docs/work-packets/"
    "G0-RTC-07H_PROVIDER_TARGET_RECEIPT_RETENTION_INVENTORY_REFRESH.json"
)
INVENTORY_TEST = (
    ROOT / "tests/gates/test_provider_target_receipt_retention_inventory.py"
)

EXPECTED_PARENT = "0df759d1fd9bc5d83e9fc72f1c850756afa93fe5"
EXPECTED_BLOB = "a5e3d1321e257c9ce1d70e9a68e4079445c6985a"
STALE_PARENT = "b2bda280f8f98d6e977e092c5429da3c85427a33"


def _assignments(tree: ast.Module) -> dict[str, object]:
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if isinstance(target, ast.Name):
            try:
                values[target.id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    return values


def test_refresh_fixture_uses_exact_hardened_identity() -> None:
    tree = ast.parse(INVENTORY_TEST.read_text(encoding="utf-8"))
    assignments = _assignments(tree)

    assert assignments["REVISION"] == EXPECTED_PARENT
    assert assignments["SOURCE_GIT_BLOB_SHA1"] == EXPECTED_BLOB
    assert assignments["PRE_HARDENING_REVISION"] == STALE_PARENT
    assert assignments["REVISION"] != assignments["PRE_HARDENING_REVISION"]


def test_packet_does_not_launder_fixture_binding_into_head_authentication() -> None:
    payload = json.loads(PACKET.read_text(encoding="utf-8"))

    assert payload["exact_parent"]["revision"] == EXPECTED_PARENT
    assert payload["source_identity"]["git_blob_sha1"] == EXPECTED_BLOB
    assert payload["source_identity"]["pre_hardening_revision"] == STALE_PARENT
    assert payload["scope"]["production_behavior_changed"] is False
    assert payload["scope"]["canonical_effect_inventory_changed"] is False
    assert payload["scope"]["effect_lease_consumed"] is False
    assert payload["revision_authentication"][
        "authenticated_git_head_receipt_consumed"
    ] is False
    assert payload["revision_authentication"][
        "caller_supplied_revision_runtime_refusal"
    ] is False
    assert payload["verification"]["hard_evidence_claimed"] is False
    assert "claim-gate-closure" in payload["forbidden_actions"]


def test_refresh_contains_no_production_or_gate_authority() -> None:
    tree = ast.parse(INVENTORY_TEST.read_text(encoding="utf-8"))
    calls = {
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    forbidden_fragments = {
        "begin_effect",
        "grant",
        "finish_effect",
        "retain",
        "promote_candidates",
        "OwnerApproval",
    }
    assert not any(
        fragment in call
        for call in calls
        for fragment in forbidden_fragments
    )
