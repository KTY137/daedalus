"""Nemesis regressions for Tier-2 semantic and terminal evidence integrity."""
from __future__ import annotations

import copy

from daedalus.eval import harness, report, tier2
from daedalus.eval.tasks import TASKS


_CONTROL_BYTES = ("\x00", "\x07", "\x1b", "\x7f", "\r")


def test_corrections_questions_and_contradictions_do_not_score_as_success() -> None:
    adversarial = (
        "It calls cached_index? No.",
        "It calls cached_index! False.",
        "It calls cached_index — false.",
        "It calls cached_index, but that is incorrect.",
        "It calls cached_index. It does not call cached_index.",
        "Claim: it calls cached_index. Correction: it does not.",
        "It calls cached_index. Actually, it calls build_index instead.",
        "It calls cached_index. Instead, it calls build_index.",
        "It calls cached_index. I retract that claim.",
        "cached_index is wrong here.",
    )
    for answer in adversarial:
        success, fraction = harness._score(answer, ["cached_index"])
        assert fraction == 1.0, answer
        assert success is False, answer


def test_documented_retractions_replacements_and_prohibitions_fail_semantics() -> None:
    tasks = {task["id"]: task for task in TASKS}
    adversarial = (
        ("web_api_file", "Claim: it calls cached_index. Correction: it does not."),
        ("web_api_file", "It calls cached_index. Actually, it calls build_index instead."),
        ("web_api_file", "It calls cached_index. Instead, it calls build_index."),
        ("web_api_file", "It calls cached_index. I retract that claim."),
        ("garden_plants_file", "The cactus interval is 14 days. Correction: 10 days."),
        ("garden_plants_file", "The cactus interval is 14 days. Actually, it is 10 days."),
        ("garden_cli_file", "The command says water is prohibited."),
        ("garden_cli_file", "The command forbids water."),
        ("garden_cli_file", "Water should be avoided."),
        ("garden_cli_file", "Water is unnecessary."),
    )
    for task_id, answer in adversarial:
        task = tasks[task_id]
        guarded, fraction = harness._score(answer, task["answer_contains"])
        verdict = tier2._validate_task_answer(task, answer)
        assert fraction == 1.0, answer
        assert guarded is False, answer
        assert verdict["validated"] is True, answer
        assert verdict["semantic_success"] is False, answer


def test_modal_negations_fail_closed_for_identifiers_and_numeric_labels() -> None:
    subjects = (
        ("water_every_days", "water_every_days"),
        ("total_tokens", "total_tokens"),
        ("unit_clusters", "unit_clusters"),
        ("needs_water", "needs_water"),
        ("14 days", "14"),
    )
    modal_rejections = (
        "{subject} should not be used.",
        "{subject} must not be used.",
        "{subject} should never be used.",
        "{subject} shouldn't be used.",
        "{subject} mustn't be used.",
        "{subject} shouldn\u2019t be used.",
        "{subject} mustn\u2019t be used.",
    )

    for subject, expected in subjects:
        for template in modal_rejections:
            answer = template.format(subject=subject)
            guarded, fraction = harness._score(answer, [expected])
            assert fraction == 1.0, answer
            assert guarded is False, answer


def test_modal_words_do_not_globally_poison_positive_assertions() -> None:
    positive = (
        ("Actually, water_every_days should be used.", "water_every_days"),
        ("Use total_tokens; the fallback should not be used.", "total_tokens"),
        ("unit_clusters is used, not window_clusters.", "unit_clusters"),
        ("needs_water should be called, not watering_plan.", "needs_water"),
        ("14 days should be used, not 10 days.", "14"),
    )
    for answer, expected in positive:
        guarded, fraction = harness._score(answer, [expected])
        assert fraction == 1.0, answer
        assert guarded is True, answer


def test_but_actually_replacement_rejects_only_when_fact_is_not_reasserted() -> None:
    rejected = "It uses water, but actually it uses fertilizer."
    guarded, fraction = harness._score(rejected, ["water"])
    assert fraction == 1.0
    assert guarded is False

    reasserted = "It uses water, but actually it uses water and fertilizer."
    guarded, fraction = harness._score(reasserted, ["water"])
    assert fraction == 1.0
    assert guarded is True


def test_modal_and_actual_replacements_reach_builtin_tier2_validators() -> None:
    tasks = {task["id"]: task for task in TASKS}
    adversarial = (
        ("garden_care_file", "water_every_days should not be used."),
        ("slice_semantic_slice", "total_tokens must not be used."),
        ("index_build_index", "unit_clusters shouldn\u2019t be used."),
        ("garden_watering_plan", "needs_water mustn't be called."),
        ("garden_plants_file", "14 days should never be used."),
        ("garden_cli_file", "It uses water, but actually it uses fertilizer."),
    )
    for task_id, answer in adversarial:
        verdict = tier2._validate_task_answer(tasks[task_id], answer)
        assert verdict["validated"] is True, answer
        assert verdict["guarded_lexical_success"] is False, answer
        assert verdict["lexical_fraction"] == 1.0, answer
        assert verdict["semantic_success"] is False, answer

    positive = (
        ("garden_care_file", "Actually, it uses water_every_days."),
        ("slice_semantic_slice", "It uses total_tokens; fallback should not be used."),
        ("index_build_index", "It uses unit_clusters, not window_clusters."),
        ("garden_watering_plan", "It calls needs_water, not watering_plan."),
        ("garden_plants_file", "It uses 14 days, not 10 days."),
        ("garden_cli_file", "It uses water, but actually it uses water and fertilizer."),
    )
    for task_id, answer in positive:
        verdict = tier2._validate_task_answer(tasks[task_id], answer)
        assert verdict["validated"] is True, answer
        assert verdict["semantic_success"] is True, answer


def test_negative_second_mention_poisoning_is_fail_closed_for_multi_fact_answers() -> None:
    success, fraction = harness._score(
        "It calls load_project and uses repo_root. Later correction: repo_root is not used.",
        ["load_project", "repo_root"],
    )
    assert fraction == 1.0
    assert success is False


def test_unrelated_negation_and_numeric_correction_remain_valid_positive_controls() -> None:
    success, fraction = harness._score("It calls cached_index, not build_index.", ["cached_index"])
    assert success is True
    assert fraction == 1.0

    success, fraction = harness._score("The cactus interval is 14 days, not 10 days.", ["14"])
    assert success is True
    assert fraction == 1.0

    success, fraction = harness._score("The cactus interval is 14 days instead of 10.", ["14"])
    assert success is True
    assert fraction == 1.0


def test_correction_vocabulary_before_a_positive_assertion_is_not_blacklisted() -> None:
    tasks = {task["id"]: task for task in TASKS}
    positive = (
        ("web_api_file", "Correction: it calls cached_index, not build_index."),
        ("garden_plants_file", "Actually, the cactus interval is 14 days, not 10 days."),
        ("garden_cli_file", "Water is allowed; the command forbids fertilizer."),
    )
    for task_id, answer in positive:
        verdict = tier2._validate_task_answer(tasks[task_id], answer)
        assert verdict["validated"] is True, answer
        assert verdict["semantic_success"] is True, answer


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
                "provider_error_A": {"type": "Timeout\x07", "message": "boom\x1b[2J\nFORGED"},
                "provider_error_B": None,
                "answer_A_truncated": False,
                "answer_B_truncated": False,
            },
        ],
        "measurement_errors": [
            {
                "id": "error\x1b[H\nFORGED",
                "provider_error_A": {"type": "Timeout\x07", "message": "boom\x1b[2J\nFORGED"},
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


def test_safe_ascii_field_is_bounded_after_sanitization() -> None:
    value = "x\x1b[2J\n" + "z" * (tier2._MAX_TERMINAL_FIELD_CHARS * 4)
    rendered = tier2._safe_ascii(value)
    assert len(rendered) == tier2._MAX_TERMINAL_FIELD_CHARS
    assert rendered.endswith("...")
    assert "\x1b" not in rendered
    assert "\n" not in rendered
    assert all(32 <= ord(ch) <= 126 for ch in rendered)


def test_safe_ascii_field_replaces_all_c0_del_c1_and_bidi_controls() -> None:
    controls = "".join(chr(codepoint) for codepoint in range(160)) + "\u202e"
    rendered = tier2._safe_ascii(controls)
    assert "\n" not in rendered
    assert "\r" not in rendered
    assert all(32 <= ord(ch) <= 126 for ch in rendered)
    assert len(rendered) <= tier2._MAX_TERMINAL_FIELD_CHARS


def test_every_renderer_field_is_bounded_without_mutating_evidence() -> None:
    result = _malicious_result()
    long = "z" * (tier2._MAX_TERMINAL_FIELD_CHARS * 4)
    result["provider"] = {"kind": long, "model": long, "host": long}
    result["scoring_method"] = long
    result["per_task"][0]["id"] = long
    result["per_task"][0]["project"] = long
    result["measurement_errors"][0]["id"] = long
    result["measurement_errors"][0]["provider_error_A"] = {
        "type": long,
        "message": long,
    }
    result["unvalidated"] = [{"id": long}]
    result["errored"] = [{
        "id": long,
        "target": long,
        "label_provenance": long,
        "label_tier": long,
        "error": long,
    }]
    before = copy.deepcopy(result)

    rendered = report.render_tier2(result)

    assert long[: tier2._MAX_TERMINAL_FIELD_CHARS + 1] not in rendered
    assert "..." in rendered
    assert result == before
