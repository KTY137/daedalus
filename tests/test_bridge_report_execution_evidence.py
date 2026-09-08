import json

from daedalus import file_bridge


# These are executor-owned terminal facts; request/chat metadata is adversarial input here.
EXECUTION_EVIDENCE = {
    "runtime_id": "claude-cli-v1",
    "work_item_id": "work-7f32",
    "attempt_id": "attempt-4b19",
    "phase": "terminal",
    "terminal_receipt_sha256": "a" * 64,
}


def test_report_brief_projects_terminal_execution_evidence_only(tmp_path):
    report = tmp_path / "task.report.json"
    report.write_text(
        json.dumps(
            {
                "request": {
                    "project": "project_tct",
                    "lane": "claude",
                    "agent": "request-agent-must-not-win",
                    "runtime_id": "request-runtime-must-not-win",
                    "work_item_id": "request-work-item-must-not-win",
                    "attempt_id": "request-attempt-must-not-win",
                    "phase": "request-phase-must-not-win",
                    "terminal_receipt_sha256": "b" * 64,
                },
                "bridge_status": "done",
                "lane": "claude",
                "agent": "qa-critic",
                "provider": "claude_cli",
                "replay": True,
                "runtime_receipt": {"executed": False},
                **EXECUTION_EVIDENCE,
                "report": {"summary": "  verified   terminal evidence  "},
            }
        ),
        encoding="utf-8",
    )

    assert file_bridge._report_brief(report) == {
        "name": "task.report.json",
        "status": "done",
        "lane": "claude",
        "project": "project_tct",
        "agent": "qa-critic",
        "provider": "claude_cli",
        "replay": True,
        "execution_executed": False,
        **EXECUTION_EVIDENCE,
        "summary": "verified terminal evidence",
    }


def test_report_brief_never_invents_execution_identity_from_request(tmp_path):
    report = tmp_path / "task.report.json"
    report.write_text(
        json.dumps(
            {
                "request": {
                    "project": "project_tct",
                    "lane": "local_only",
                    "agent": "request-agent-must-not-be-promoted",
                    "runtime_id": "request-runtime-must-not-be-promoted",
                    "work_item_id": "request-work-item-must-not-be-promoted",
                    "attempt_id": "request-attempt-must-not-be-promoted",
                    "phase": "request-phase-must-not-be-promoted",
                    "terminal_receipt_sha256": "c" * 64,
                    "provider": "request-provider-must-not-be-promoted",
                    "replay": True,
                    "runtime_receipt": {"executed": True},
                },
                "bridge_status": "failed",
                "error": "executor unavailable",
            }
        ),
        encoding="utf-8",
    )

    brief = file_bridge._report_brief(report)
    assert brief["agent"] == ""
    assert brief["provider"] == ""
    assert brief["replay"] is None
    assert brief["execution_executed"] is None
    assert brief["runtime_id"] == ""
    assert brief["work_item_id"] == ""
    assert brief["attempt_id"] == ""
    assert brief["phase"] == ""
    assert brief["terminal_receipt_sha256"] == ""
    assert brief["summary"] == "executor unavailable"


def test_project_report_projection_carries_terminal_execution_identity_to_live_bus(tmp_path, monkeypatch):
    monkeypatch.setattr(file_bridge, "INBOX", tmp_path)
    report = tmp_path / "task.report.json"
    report.write_text(
        json.dumps(
            {
                "request": {"project": "project_tct", "lane": "codex"},
                "bridge_status": "done",
                "lane": "codex",
                "agent": "core-dev",
                **EXECUTION_EVIDENCE,
                "report": {"summary": "finished"},
            }
        ),
        encoding="utf-8",
    )

    rows = file_bridge._project_report_briefs("project_tct")
    assert len(rows) == 1
    assert rows[0]["agent"] == "core-dev"
    for key, value in EXECUTION_EVIDENCE.items():
        assert rows[0][key] == value


def test_report_brief_keeps_exact_provider_execution_booleans_only(tmp_path):
    report = tmp_path / "task.report.json"
    report.write_text(
        json.dumps(
            {
                "request": {"project": "project_tct", "lane": "claude"},
                "bridge_status": "done",
                "lane": "claude",
                "provider": "claude_cli",
                "replay": "false",
                "runtime_receipt": {"executed": 0},
                "report": {"summary": "malformed optional execution mode"},
            }
        ),
        encoding="utf-8",
    )

    brief = file_bridge._report_brief(report)
    assert brief["provider"] == "claude_cli"
    assert brief["replay"] is None
    assert brief["execution_executed"] is None
