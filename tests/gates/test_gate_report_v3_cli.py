from __future__ import annotations

import json
from pathlib import Path

from scripts.report_gate0_v3 import main


ROOT = Path(__file__).resolve().parents[2]
REVISION = "1" * 40


def test_cli_emits_machine_v3_report_and_blocked_exit(capsys) -> None:
    result = main([str(ROOT), "--source-revision", REVISION])
    assert result == 1
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema"] == "daedalus-gate-report/3"
    assert payload["closed"] is False
    assert payload["security_boundary_claimed"] is False
    assert payload["repository_write_inventory_sha256"] is not None
    assert payload["repository_write_scan_input_sha256"] is not None
    assert payload["repository_write_files_scanned"] > 0
    assert payload["repository_write_inventory_generation"] == 2
    assert payload["repository_write_failures"]
    assert captured.err == ""


def test_cli_emits_machine_error_and_distinct_error_exit(capsys) -> None:
    result = main([str(ROOT), "--source-revision", "not-a-revision"])
    assert result == 2
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["schema"] == "daedalus-gate-report-v3-error/1"
    assert payload["closed"] is False
    assert "lowercase 40-hex" in payload["error"]
    assert captured.err == ""


def test_cli_has_no_argument_that_can_claim_security_closure(capsys) -> None:
    try:
        main(
            [
                str(ROOT),
                "--source-revision",
                REVISION,
                "--security-boundary-claimed",
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:  # pragma: no cover - argparse must reject unknown authority
        raise AssertionError("CLI accepted a security-boundary claim argument")
    captured = capsys.readouterr()
    assert "unrecognized arguments" in captured.err
