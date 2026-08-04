from __future__ import annotations

import json
from pathlib import Path

import daedalus.gates.repository_write_inventory as inventory
from daedalus.spine.ledger import ROOT


SCHEMA = ROOT / "configs" / "schemas" / "repository-write-inventory-v1.schema.json"


def test_schema_matches_runtime_contract_surface() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert payload["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert payload["additionalProperties"] is False
    assert set(payload["required"]) == {
        "schema",
        "source_revision",
        "package_root",
        "scan_input_sha256",
        "files_scanned",
        "callsites",
        "blocker_count",
        "closed",
        "scope",
        "primary_checkout_target_proven",
        "digest",
    }
    assert payload["properties"]["primary_checkout_target_proven"] == {
        "const": False
    }
    assert payload["properties"]["scope"] == {
        "const": "potential_repository_write_surface"
    }
    callsite = payload["$defs"]["callsite"]
    assert callsite["additionalProperties"] is False
    assert set(callsite["properties"]["kind"]["enum"]) == set(
        inventory._ALLOWED_KINDS
    )


def test_only_exact_read_only_sqlite_is_nonblocking() -> None:
    payload = json.loads(SCHEMA.read_text(encoding="utf-8"))
    kinds = set(payload["$defs"]["callsite"]["properties"]["kind"]["enum"])
    assert inventory._BLOCKING_KINDS < kinds
    assert kinds - inventory._BLOCKING_KINDS == {"sqlite_read_only"}
