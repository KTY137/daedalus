from pathlib import Path

CORE = Path("daedalus/core.py")
TEST = Path("tests/providers/test_claude_sealed_output_evidence.py")

old = '''        return {
            "request": payload,
            "bridge_status": "done",
            "lane": "claude",
            "agent": result["agent"],
            "report": result["report"],
        }
'''
new = '''        terminal_report = {
            "request": payload,
            "bridge_status": "done",
            "lane": "claude",
            "agent": result["agent"],
            "report": result["report"],
        }
        # Execution identity is provider evidence, never requested routing
        # metadata.  Keep this as an allowlist so future provider internals do
        # not leak into the durable bridge report by accident.
        for name in (
            "runtime_id",
            "work_item_id",
            "attempt_id",
            "phase",
            "terminal_receipt_sha256",
        ):
            if name in result:
                terminal_report[name] = result[name]
        return terminal_report
'''

core = CORE.read_text(encoding="utf-8")
if core.count(old) != 1:
    raise SystemExit("expected exactly one Claude terminal-report block")
CORE.write_text(core.replace(old, new, 1), encoding="utf-8")

test = TEST.read_text(encoding="utf-8")
import_line = "from daedalus import core\n"
if import_line not in test:
    anchor = "from daedalus.providers import claude_cli as subject\n"
    if anchor not in test:
        raise SystemExit("Claude evidence test import anchor missing")
    test = test.replace(anchor, import_line + anchor, 1)

marker = "def test_claude_bridge_terminal_report_uses_provider_execution_evidence"
if marker not in test:
    test += '''


def test_claude_bridge_terminal_report_uses_provider_execution_evidence(monkeypatch) -> None:
    request = {
        "objective": "verify runtime evidence",
        "repo_root": "/isolated/worktree",
        "paths": [],
        "model": "sonnet",
        "runtime_id": "request-runtime-must-not-win",
        "work_item_id": "request-work-item-must-not-win",
        "attempt_id": "request-attempt-must-not-win",
        "phase": "request-phase-must-not-win",
        "terminal_receipt_sha256": "9" * 64,
    }
    provider_result = {
        "agent": "qa-critic",
        "report": {"status": "done", "summary": "verified"},
        "runtime_id": subject.RUNTIME_ID,
        "attempt_id": ATTEMPT_ID,
        "phase": "terminal",
        "terminal_receipt_sha256": TERMINAL_RECEIPT_SHA256,
    }
    monkeypatch.setattr(core, "ask_claude", lambda **_kwargs: provider_result)

    report = core._ask_claude_report(request)

    assert report["runtime_id"] == subject.RUNTIME_ID
    assert report["attempt_id"] == ATTEMPT_ID
    assert report["phase"] == "terminal"
    assert report["terminal_receipt_sha256"] == TERMINAL_RECEIPT_SHA256
    assert "work_item_id" not in report
    assert report["request"]["work_item_id"] == "request-work-item-must-not-win"


def test_claude_bridge_never_promotes_requested_execution_identity(monkeypatch) -> None:
    request = {
        "objective": "verify runtime evidence",
        "repo_root": "/isolated/worktree",
        "paths": [],
        "model": "sonnet",
        "runtime_id": "request-runtime-must-not-win",
        "work_item_id": "request-work-item-must-not-win",
        "attempt_id": "request-attempt-must-not-win",
        "phase": "request-phase-must-not-win",
        "terminal_receipt_sha256": "9" * 64,
    }
    monkeypatch.setattr(
        core,
        "ask_claude",
        lambda **_kwargs: {
            "agent": "qa-critic",
            "report": {"status": "done", "summary": "no runtime evidence"},
        },
    )

    report = core._ask_claude_report(request)

    for name in (
        "runtime_id",
        "work_item_id",
        "attempt_id",
        "phase",
        "terminal_receipt_sha256",
    ):
        assert name not in report
'''

TEST.write_text(test, encoding="utf-8")
