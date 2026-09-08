import json

from daedalus import file_bridge


def test_report_brief_projects_terminal_agent_evidence_only(tmp_path):
    report = tmp_path / "task.report.json"
    report.write_text(
        json.dumps(
            {
                "request": {
                    "project": "project_tct",
                    "lane": "claude",
                    "agent": "request-agent-must-not-win",
                },
                "bridge_status": "done",
                "lane": "claude",
                "agent": "qa-critic",
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
        "summary": "verified terminal evidence",
    }


def test_report_brief_never_invents_agent_from_request(tmp_path):
    report = tmp_path / "task.report.json"
    report.write_text(
        json.dumps(
            {
                "request": {
                    "project": "project_tct",
                    "lane": "local_only",
                    "agent": "request-agent-must-not-be-promoted",
                },
                "bridge_status": "failed",
                "error": "executor unavailable",
            }
        ),
        encoding="utf-8",
    )

    brief = file_bridge._report_brief(report)
    assert brief["agent"] == ""
    assert brief["summary"] == "executor unavailable"


def test_project_report_projection_carries_terminal_agent_to_live_bus(tmp_path, monkeypatch):
    monkeypatch.setattr(file_bridge, "INBOX", tmp_path)
    report = tmp_path / "task.report.json"
    report.write_text(
        json.dumps(
            {
                "request": {"project": "project_tct", "lane": "codex"},
                "bridge_status": "done",
                "lane": "codex",
                "agent": "core-dev",
                "report": {"summary": "finished"},
            }
        ),
        encoding="utf-8",
    )

    rows = file_bridge._project_report_briefs("project_tct")
    assert len(rows) == 1
    assert rows[0]["agent"] == "core-dev"
