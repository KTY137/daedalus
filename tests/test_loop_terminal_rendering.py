from __future__ import annotations

from daedalus.loop import IterationResult, LoopBounds, LoopReport, render


def _report(value: str, *, reason: str | None = None) -> LoopReport:
    iteration = IterationResult(
        index=0,
        candidate_id=value,
        instruction="kept only in evidence",
        source="test",
        score=1.0,
        outcome=value,
        status=value,
        promoted=False,
        reason=value if reason is None else reason,
        lane=value,
        worker=value,
        integration_branch=value,
    )
    return LoopReport(
        run_id=value,
        trace_id=value,
        repo_root=".",
        project=None,
        bounds=LoopBounds(),
        dry_run=True,
        mode=value,
        governance_state=value,
        stop_reason=value,
        stop_detail=value,
        iterations=[iteration],
        skipped=[{"candidate_id": value, "reason": value}],
        notes=[value],
        killswitch_path=value,
    )


def test_render_strips_terminal_controls_without_rewriting_evidence() -> None:
    raw = "failure\x1b[2J\x1b]0;spoofed\x07\x00\x7f\x9b\nnext-line"
    report = _report(raw)

    rendered = render(report)

    for control in ("\x1b", "\x07", "\x00", "\x7f", "\x9b"):
        assert control not in rendered
    assert "failure[2J]0;spoofed next-line" in rendered
    assert "\nnext-line" not in rendered

    evidence = report.to_dict()
    assert evidence["run_id"] == raw
    assert evidence["trace_id"] == raw
    assert evidence["stop_reason"] == raw
    assert evidence["stop_detail"] == raw
    assert evidence["notes"] == [raw]
    assert evidence["skipped"][0]["candidate_id"] == raw
    assert evidence["skipped"][0]["reason"] == raw
    assert evidence["iterations"][0]["candidate_id"] == raw
    assert evidence["iterations"][0]["reason"] == raw
    assert evidence["iterations"][0]["integration_branch"] == raw


def test_reason_truncation_happens_after_control_sanitization() -> None:
    reason = ("\x1b" * 80) + ("x" * 205)
    report = _report("safe", reason=reason)

    rendered = render(report)

    assert "why: " + ("x" * 200) + "..." in rendered
    assert "\x1b" not in rendered
