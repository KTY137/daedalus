from __future__ import annotations

import json
from pathlib import Path

from scripts.report_provider_observation_persistence_inventory import main


ROOT = Path(__file__).resolve().parents[2]
REVISION = "1" * 40


def test_cli_emits_machine_report_and_nonzero_blocker_exit(capsys) -> None:
    result = main([str(ROOT), "--source-revision", REVISION])
    assert result == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["closed"] is False
    assert payload["inventory_only"] is True
    assert payload["canonical_inventory_integrated"] is False
    assert payload["surface_count"] == payload["blocker_count"] == 11
    assert captured.err == ""


def test_cli_emits_machine_error_and_distinct_error_exit(capsys) -> None:
    result = main([str(ROOT), "--source-revision", "not-a-revision"])
    assert result == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload == {
        "schema": "daedalus-gate0-provider-observation-persistence-inventory-error/1",
        "closed": False,
        "error": "source_revision must be a lowercase 40-hex commit",
    }
    assert captured.err == ""
