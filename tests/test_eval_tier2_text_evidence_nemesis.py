"""Nemesis regressions for Tier-2 semantic and terminal evidence integrity."""
from __future__ import annotations

import copy

from daedalus.eval import harness, report, tier2


_CONTROL_BYTES = ("\x00", "\x07", "\x1b", "\x7f", "\r")


def test_corrections_questions_and_contradictions_do_not_score_as_success() -> None:
    adversarial = (
        "It calls cached_index? No.",
        "It calls cached_index! False.",
        "It calls cached_index, but that is incorrect.",
        "It calls cached_index. It does not call cached_index.",
        "cached_index is wrong here.",
    )
    for answer in adversarial:
        success, fraction = harness._score(answer, ["cached_index"])
        assert fraction == 1.0, answer
        assert success is False, answer


def test_negative_second_mention_poisoning_is_fail_closed_for_multi_fact_answers() -> None:
    success, fraction = harness._score(
        "It calls load_project and uses repo_root. Later correction: repo_root is not used.",
        ["load_project", "repo_root"],
    )
    assert fraction == 1.0
    assert success is False


def test_unrelated_negation_and_numeric_correction_remain_valid_positive_controls() -> None:
    success, fraction = harness._score(
        "It calls cached_index, not build_index.",
        ["cached_index"],
    )
    assert success is True
    assert fraction == 1.0

    success, fraction = harness._score(
        "The cactus interval is 14 days, not 10 days.",
        ["14"],
    )
    assert success is True
    assert fraction == 1.0


def _malicious_result() -> dict:
    return {
        "tier": 2,
        "skipped": False,
        "provider": {
            "kind": "ollama\x1b[2J",
            "model": "model\x07\x00\nFORGED",
            "host": "http://127.0.0.1\rFORGED",
        },
        "scoring_method": "validator\x1b]0;spoofed\x07",
        "n_tasks": 2,
        "n_scored_tasks": 1,
        "n_measurement_error_tasks": 1,
        "n_unvalidated_tasks": 0,
        "success_A": 1,
        "success_B": 1,
        "tokens_A": 10,
        "tokens_B": 20,
        "tokens_B_true": 20,
        "b_truncated_any": False,
        "per_task": [
            {
                "id": "task\x1b[2J\nFORGED",
                "project": "project\x07\x00",
                "success_A": True,
                "success_B": True,
                "frac_A": 1.0,
                "frac_B": 1.0,
                "tokens_A": 10,
                "tokens_B": 20,
                "tokens_B_true": 20,
                "b_truncated": False,
            },
            {
                "id": "error\x1b[H\nFORGED",
                "project": "project",
                "tokens_A": 1,
                "tokens_B": 1,
                "tokens_B_true": 1,
                "b_truncated": False,
                "measurement_error": True,
                "provider_error_A": {
                    "type": "Timeout\x07",
                    "message": "boom\x1b[2J\nFORGED",
                },
                "provider_error_B": None,
                "answer_A_truncated": False,
                "answer_B_truncated": False,
            },
        ],
        "measurement_errors": [
            {
                "id": "error\x1b[H\nFORGED",
                "provider_error_A": {
                    "type": "Timeout\x07",
                    "message": "boom\x1b[2J\nFORGED",
                },
                "provider_error_B": None,
                "answer_A_truncated": False,
                "answer_B_truncated": False,
            }
        ],
        "unvalidated": [],
        "errored": [],
    }


def test_tier2_renderer_cannot_emit_raw_terminal_controls_or_injected_lines() -> None:
    result = _malicious_result()
    text = report.render_tier2(result)

    for control in _CONTROL_BYTES:
        assert control not in text
    assert "\nFORGED" not in text
    text.encode("ascii")


def test_renderer_sanitization_does_not_rewrite_canonical_result_evidence() -> None:
    result = _malicious_result()
    before = copy.deepcopy(result)

    report.render_tier2(result)

    assert result == before
    assert result["provider"]["model"] == "model\x07\x00\nFORGED"
    assert result["per_task"][0]["id"] == "task\x1b[2J\nFORGED"


def test_safe_ascii_field_is_single_line_printable_ascii() -> None:
    rendered = tier2._safe_ascii("x\x00\x07\x1b[2J\r\nnext\u202e")
    assert rendered == "x???[2J next?"
    assert all(32 <= ord(ch) <= 126 for ch in rendered)
