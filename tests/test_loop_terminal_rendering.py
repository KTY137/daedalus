from __future__ import annotations

import copy
import dataclasses
from pathlib import Path

import pytest

from daedalus.loop import IterationResult, LoopBounds, LoopReport, render
from daedalus.foundation.text_integrity import (
    TERMINAL_FIELD_MAX_CHARS,
    safe_terminal_text,
)


ROOT = Path(__file__).resolve().parents[1]
LOOP_SOURCE = ROOT / "daedalus" / "loop.py"

_REPORT_FIELDS = {
    "run_id",
    "trace_id",
    "mode",
    "governance_state",
    "stop_reason",
    "stop_detail",
    "killswitch_path",
}
_ITERATION_FIELDS = {
    "candidate_id",
    "outcome",
    "status",
    "reason",
    "lane",
    "worker",
    "integration_branch",
}
_RUNTIME_TEXT_SURFACES = tuple(
    sorted(
        _REPORT_FIELDS
        | _ITERATION_FIELDS
        | {
            "skipped_candidate_id",
            "skipped_reason",
            "note",
        }
    )
)
_FORMAT_CONTROLS = "".join(
    chr(codepoint)
    for codepoint in (
        0x061C,  # Arabic letter mark
        0x200B,  # zero-width space
        0x200C,  # zero-width non-joiner
        0x200D,  # zero-width joiner
        0x200E,  # left-to-right mark
        0x200F,  # right-to-left mark
        0x202A,  # left-to-right embedding
        0x202B,  # right-to-left embedding
        0x202C,  # pop directional formatting
        0x202D,  # left-to-right override
        0x202E,  # right-to-left override
        0x2060,  # word joiner
        0x2061,  # function application
        0x2062,  # invisible times
        0x2063,  # invisible separator
        0x2064,  # invisible plus
        0x2066,  # left-to-right isolate
        0x2067,  # right-to-left isolate
        0x2068,  # first-strong isolate
        0x2069,  # pop directional isolate
        0xFEFF,  # byte-order mark / zero-width no-break space
    )
)


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


def _set_surface(report: LoopReport, surface: str, value: str) -> None:
    if surface in _REPORT_FIELDS:
        setattr(report, surface, value)
        return
    if surface in _ITERATION_FIELDS:
        report.iterations[0] = dataclasses.replace(
            report.iterations[0],
            **{surface: value},
        )
        return
    if surface == "skipped_candidate_id":
        report.skipped[0]["candidate_id"] = value
        return
    if surface == "skipped_reason":
        report.skipped[0]["reason"] = value
        return
    if surface == "note":
        report.notes[0] = value
        return
    raise AssertionError(f"unknown rendered text surface: {surface}")


@pytest.mark.parametrize(
    ("label", "value"),
    (
        ("c0", "A" + "".join(chr(codepoint) for codepoint in range(0x20)) + "B"),
        ("del-c1", "A" + "".join(chr(codepoint) for codepoint in range(0x7F, 0xA0)) + "B"),
        ("format", "A" + _FORMAT_CONTROLS + "B"),
        ("surrogate", "A\ud800\udfffB"),
        ("multiline", "A\r\n\tB\vC\fD"),
    ),
)
def test_safe_terminal_text_is_one_line_printable_ascii(
    label: str,
    value: str,
) -> None:
    del label

    rendered = safe_terminal_text(value)

    assert "\n" not in rendered
    assert "\r" not in rendered
    assert rendered.encode("ascii").decode("ascii") == rendered
    assert all(0x20 <= ord(character) <= 0x7E for character in rendered)
    assert len(rendered) <= TERMINAL_FIELD_MAX_CHARS


def test_safe_terminal_text_bounds_after_sanitization_including_ellipsis() -> None:
    raw = ("\x1b" * 80) + (_FORMAT_CONTROLS * 10) + ("x" * 500)

    rendered = safe_terminal_text(raw)

    assert len(rendered) == TERMINAL_FIELD_MAX_CHARS
    assert rendered.endswith("...")
    assert all(0x20 <= ord(character) <= 0x7E for character in rendered)


@pytest.mark.parametrize("surface", _RUNTIME_TEXT_SURFACES)
def test_every_runtime_text_surface_is_ascii_bounded_and_evidence_immutable(
    surface: str,
) -> None:
    raw = "field\x00\x1b[2J\u202e\u2066\ufeff\ud800\n" + ("z" * 500)
    report = _report("safe", reason="safe")
    _set_surface(report, surface, raw)
    before = copy.deepcopy(report.to_dict())

    rendered = render(report)

    expected = safe_terminal_text(raw)
    if surface == "mode":
        expected = expected.upper()
    assert len(expected) == TERMINAL_FIELD_MAX_CHARS
    assert expected.endswith("...")
    assert expected in rendered
    assert raw not in rendered
    assert rendered.encode("ascii").decode("ascii") == rendered
    assert all(
        character == "\n" or 0x20 <= ord(character) <= 0x7E
        for character in rendered
    )
    assert report.to_dict() == before


def test_loop_uses_neutral_canonical_terminal_helper() -> None:
    source = LOOP_SOURCE.read_text(encoding="utf-8")

    # The OWNER path, not just the leaf name: G1-FLAT-04 moved the helper
    # into daedalus/foundation/, and this assertion is about which module
    # supplies safe_terminal_text, so it has to name the one that does.
    assert "from .foundation.text_integrity import safe_terminal_text" in source
    assert "def _terminal_text" not in source
    assert "from .eval" not in source
    assert "daedalus.eval" not in source
