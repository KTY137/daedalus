"""G1-EVAL-USAGE-01 -- provider-reported usage inside the Tier-2 harness receipt.

The Tier-2 ``_ask`` receipt carries the provider's own token report next to
the harness's local estimate, and ``run_tier2`` aggregates the two in
separate fields that are never added together. Four buckets are pinned:
``reported``, ``absent``, ``malformed`` (from the provider), ``error`` (the
call raised) -- plus ``unknown`` for a receipt that never carried the field,
which is not a provider observation and is never folded into ``absent``.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from daedalus.eval import harness, report, tier2
from daedalus.providers import _openai_compat as compat
from daedalus.providers._openai_compat import (
    PROVIDER_TOKENIZER_UNKNOWN,
    ChatReceipt,
    ProviderUsage,
)

PROVIDER = {"kind": "ollama", "host": "http://127.0.0.1:11434", "model": "usage-test"}
RECEIPT_TARGET = "daedalus.providers._openai_compat.chat_completion_receipt"
USAGE_KEYS = (
    "usage", "usage_status", "usage_error", "usage_raw_json",
    "usage_raw_truncated", "usage_raw_sha256", "provider_call",
)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _chat_receipt(
    text: Any = "The cactus interval is 14 days.",
    usage: ProviderUsage | None = ProviderUsage(10, 2, 12),
    usage_error: str | None = None,
    raw: Any = "__from_usage__",
    truncated: bool = False,
    endpoint: str = "http://127.0.0.1:11434/v1",
) -> ChatReceipt:
    if raw == "__from_usage__":
        raw = None if usage is None else {
            "prompt_tokens": usage.input_tokens, "completion_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
        }
    raw_json = None if raw is None else _canonical(raw)
    return ChatReceipt(
        text=text, usage=usage, usage_error=usage_error, usage_raw_json=raw_json,
        usage_raw_truncated=truncated,
        usage_raw_sha256=None if raw_json is None else hashlib.sha256(
            raw_json.encode("utf-8")).hexdigest(),
        response_model="usage-test:served", finish_reason="stop",
        endpoint=endpoint, request_model="usage-test",
    )


# ---------------------------------------------------------------------------
# _ask receipts
# ---------------------------------------------------------------------------

def test_ask_receipt_reported_usage_is_typed_with_provenance() -> None:
    with patch(RECEIPT_TARGET, return_value=_chat_receipt()) as call:
        receipt = tier2._ask(PROVIDER, "q", "ctx")
    assert call.call_args.kwargs["base_url"] == "http://127.0.0.1:11434/v1"
    assert receipt["ok"] is True
    for key in USAGE_KEYS:
        assert key in receipt, key
    assert receipt["usage"] == {
        "input_tokens": 10, "output_tokens": 2, "total_tokens": 12,
        "tokenizer": PROVIDER_TOKENIZER_UNKNOWN,
    }
    assert receipt["usage_status"] == "reported"
    assert receipt["usage_error"] is None
    raw = _canonical({"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12})
    assert receipt["usage_raw_json"] == raw
    assert receipt["usage_raw_truncated"] is False
    assert receipt["usage_raw_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert receipt["provider_call"] == {
        "kind": "ollama", "host_endpoint": "http://127.0.0.1:11434/v1",
        "request_model": "usage-test", "response_model": "usage-test:served",
        "finish_reason": "stop",
    }


def test_ask_receipt_absent_usage() -> None:
    with patch(RECEIPT_TARGET, return_value=_chat_receipt(usage=None)):
        receipt = tier2._ask(PROVIDER, "q", "ctx")
    assert receipt["ok"] is True
    assert receipt["usage"] is None
    assert receipt["usage_status"] == "absent"
    assert receipt["usage_error"] is None
    assert receipt["usage_raw_json"] is None
    assert receipt["usage_raw_sha256"] is None
    assert receipt["provider_call"]["host_endpoint"] == "http://127.0.0.1:11434/v1"


def test_ask_receipt_malformed_usage_keeps_raw_and_cleans_error() -> None:
    raw = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 99}
    chat = _chat_receipt(usage=None, usage_error="total mismatch\x1b[2J", raw=raw)
    with patch(RECEIPT_TARGET, return_value=chat):
        receipt = tier2._ask(PROVIDER, "q", "ctx")
    assert receipt["ok"] is True
    assert receipt["usage"] is None
    assert receipt["usage_status"] == "malformed"
    assert receipt["usage_error"] == "total mismatch?[2J"
    assert receipt["usage_raw_json"] == _canonical(raw)
    assert receipt["usage_raw_sha256"] == hashlib.sha256(_canonical(raw).encode()).hexdigest()


def test_ask_receipt_error_path_has_no_provider_observation() -> None:
    with patch(RECEIPT_TARGET, side_effect=TimeoutError("boom\x1b[2J")):
        receipt = tier2._ask(PROVIDER, "q", "ctx")
    assert receipt["ok"] is False
    assert receipt["error_type"] == "TimeoutError"
    assert receipt["usage"] is None
    assert receipt["usage_status"] == "error"
    assert receipt["usage_error"] is None
    assert receipt["usage_raw_json"] is None
    assert receipt["usage_raw_truncated"] is False
    assert receipt["usage_raw_sha256"] is None
    assert receipt["provider_call"] is None


def test_ask_receipt_empty_text_is_measurement_error_but_keeps_spend() -> None:
    with patch(RECEIPT_TARGET, return_value=_chat_receipt(text="  ")):
        receipt = tier2._ask(PROVIDER, "q", "ctx")
    assert receipt["ok"] is False
    assert receipt["error_type"] == "EmptyProviderResponse"
    assert receipt["usage_status"] == "reported"
    assert receipt["usage"]["input_tokens"] == 10
    assert receipt["provider_call"]["request_model"] == "usage-test"


def test_ask_receipt_null_text_is_measurement_error_but_keeps_spend() -> None:
    with patch(RECEIPT_TARGET, return_value=_chat_receipt(text=None)):
        receipt = tier2._ask(PROVIDER, "q", "ctx")
    assert receipt["ok"] is False
    assert receipt["error_type"] == "EmptyProviderResponse"
    assert receipt["usage_status"] == "reported"


def test_ask_receipt_control_bytes_in_raw_and_call_fields_are_neutralised() -> None:
    chat = ChatReceipt(
        text="ok", usage=None, usage_error=None,
        usage_raw_json='{"note":"x\x1b[2J"}', usage_raw_truncated=False,
        usage_raw_sha256="0" * 64, response_model="m\x07", finish_reason="stop\r",
        endpoint="http://127.0.0.1:1/v1\x00", request_model="usage-test",
    )
    with patch(RECEIPT_TARGET, return_value=chat):
        receipt = tier2._ask(PROVIDER, "q", "ctx")
    dumped = json.dumps(receipt)
    for control in ("\\u001b", "\\u0007", "\\r", "\\u0000"):
        assert control not in dumped
    assert receipt["usage_raw_json"] == '{"note":"x?[2J"}'


def test_ask_receipt_never_retains_userinfo_from_the_host_url(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(base_url: str, body: dict[str, Any], api_key: Any, timeout_s: Any) -> dict[str, Any]:
        assert base_url.startswith("http://u:p@")
        return {
            "model": "m", "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
        }

    monkeypatch.setattr(compat, "_post", fake_post)
    prov = dict(PROVIDER, host="http://u:p@127.0.0.1:1")
    receipt = tier2._ask(prov, "q", "ctx")
    assert receipt["ok"] is True
    assert receipt["usage_status"] == "reported"
    assert receipt["provider_call"]["host_endpoint"] == "http://127.0.0.1:1/v1"
    assert "u:p" not in json.dumps(receipt)


# ---------------------------------------------------------------------------
# run_tier2 rows and aggregate
# ---------------------------------------------------------------------------

def _task(task_id: str = "garden_plants_file") -> dict:
    return {
        "id": task_id, "repo": "/virtual/repo", "target": "garden/plants.py",
        "question": "How many days between waterings does a cactus need?",
        "answer_contains": ["14"], "label_provenance": "hand_reachable", "tier": "primary",
    }


def _ok(text: str = "The cactus interval is 14 days.", **usage_fields: Any) -> dict:
    row = {
        "ok": True, "text": text, "text_chars": len(text), "text_sha256": "a" * 64,
        "text_truncated": False, "error_type": None, "error": None,
    }
    row.update(usage_fields)
    return row


def _reported(inp: int, out: int, **more: Any) -> dict:
    raw = {"prompt_tokens": inp, "completion_tokens": out, "total_tokens": inp + out}
    return _ok(
        usage={"input_tokens": inp, "output_tokens": out, "total_tokens": inp + out,
               "tokenizer": PROVIDER_TOKENIZER_UNKNOWN},
        usage_status="reported", usage_error=None, usage_raw_json=_canonical(raw),
        usage_raw_truncated=False,
        usage_raw_sha256=hashlib.sha256(_canonical(raw).encode()).hexdigest(),
        provider_call={"kind": "ollama", "host_endpoint": "http://127.0.0.1:11434/v1",
                       "request_model": "usage-test", "response_model": "usage-test",
                       "finish_reason": "stop"},
        **more,
    )


def _absent() -> dict:
    return _ok(usage=None, usage_status="absent", usage_error=None, usage_raw_json=None,
               usage_raw_truncated=False, usage_raw_sha256=None,
               provider_call={"kind": "ollama", "host_endpoint": "http://127.0.0.1:11434/v1",
                              "request_model": "usage-test", "response_model": None,
                              "finish_reason": None})


def _malformed() -> dict:
    row = _reported(10, 2)
    row.update(usage=None, usage_status="malformed", usage_error="total mismatch")
    return row


def _errored() -> dict:
    return {
        "ok": False, "text": None, "text_chars": 0, "text_sha256": None,
        "text_truncated": False, "error_type": "TimeoutError", "error": "timed out",
        "usage": None, "usage_status": "error", "usage_error": None, "usage_raw_json": None,
        "usage_raw_truncated": False, "usage_raw_sha256": None, "provider_call": None,
    }


def _run(answers: list[dict], tasks: list[dict]) -> dict:
    whole = [("cactus water_every_days = 14", False)] * (2 * len(tasks))
    with patch.object(tier2._legacy, "detect_provider", return_value=PROVIDER), \
         patch.object(tier2._legacy, "resolve_task_repo", return_value="/virtual/repo"), \
         patch.object(tier2._legacy, "cached_index", return_value={}), \
         patch.object(tier2._legacy, "semantic_slice",
                      return_value={"slice_text": "cactus water_every_days = 14"}), \
         patch.object(tier2._legacy, "_whole_repo_text", side_effect=whole), \
         patch.object(tier2, "_ask", side_effect=answers):
        return harness.run_tier2(tasks)


AGGREGATE_KEYS = {
    "calls", "reported", "absent", "malformed", "error", "unknown", "tokenizer",
    "provider_input_tokens_A", "provider_output_tokens_A",
    "provider_input_tokens_B", "provider_output_tokens_B",
}


def test_run_tier2_sums_reported_usage_per_arm_over_scored_rows() -> None:
    result = _run(
        [_reported(10, 2), _reported(100, 5), _reported(7, 3), _reported(70, 6)],
        [_task("garden_plants_file"), _task("garden_plants_file")],
    )
    assert result["n_scored_tasks"] == 2
    rows = result["per_task"]
    assert rows[0]["provider_usage_A"]["input_tokens"] == 10
    assert rows[0]["provider_usage_B"]["input_tokens"] == 100
    assert rows[0]["provider_usage_status_A"] == "reported"
    assert rows[0]["provider_usage_status_B"] == "reported"
    assert rows[0]["provider_usage_evidence_A"]["raw_sha256"] == hashlib.sha256(
        _canonical({"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}).encode()
    ).hexdigest()
    assert rows[0]["provider_usage_evidence_A"]["call"]["request_model"] == "usage-test"
    agg = result["provider_usage"]
    assert set(agg) == AGGREGATE_KEYS
    assert agg["calls"] == 4 and agg["reported"] == 4
    assert (agg["absent"], agg["malformed"], agg["error"], agg["unknown"]) == (0, 0, 0, 0)
    assert agg["tokenizer"] == PROVIDER_TOKENIZER_UNKNOWN
    assert agg["provider_input_tokens_A"] == 17
    assert agg["provider_output_tokens_A"] == 5
    assert agg["provider_input_tokens_B"] == 170
    assert agg["provider_output_tokens_B"] == 11
    # Local estimates are a different measurement and stay what they were.
    assert result["tokens_A"] == 2 * harness.count_tokens("cactus water_every_days = 14")
    assert result["tokens_A"] == result["tokens_B"]
    assert "provider_total_tokens" not in agg
    assert not any("combined" in key or "total" in key for key in agg)


def test_run_tier2_one_absent_call_makes_that_arm_none_not_partial() -> None:
    result = _run(
        [_reported(10, 2), _reported(100, 5), _absent(), _reported(70, 6)],
        [_task(), _task()],
    )
    agg = result["provider_usage"]
    assert agg["calls"] == 4 and agg["reported"] == 3 and agg["absent"] == 1
    assert agg["provider_input_tokens_A"] is None
    assert agg["provider_output_tokens_A"] is None
    assert agg["provider_input_tokens_B"] == 170
    assert agg["provider_output_tokens_B"] == 11
    assert result["per_task"][1]["provider_usage_status_A"] == "absent"
    assert result["per_task"][1]["provider_usage_A"] is None


def test_run_tier2_legacy_receipt_without_usage_field_is_unknown_not_absent() -> None:
    result = _run([_ok(), _reported(100, 5)], [_task()])
    row = result["per_task"][0]
    assert row["provider_usage_status_A"] == "unknown"
    assert row["provider_usage_A"] is None
    assert row["provider_usage_evidence_A"] == {
        "error": None, "raw_json": None, "raw_truncated": False, "raw_sha256": None,
        "call": None,
    }
    agg = result["provider_usage"]
    assert agg["unknown"] == 1 and agg["absent"] == 0 and agg["reported"] == 1
    assert agg["provider_input_tokens_A"] is None
    assert agg["provider_input_tokens_B"] == 100


def test_run_tier2_unrecognised_status_is_normalised_to_unknown() -> None:
    weird = _reported(10, 2)
    weird["usage_status"] = "estimated"
    result = _run([weird, _reported(100, 5)], [_task()])
    row = result["per_task"][0]
    assert row["provider_usage_status_A"] == "unknown"
    assert result["provider_usage"]["unknown"] == 1
    assert result["provider_usage"]["provider_input_tokens_A"] is None


def test_run_tier2_counts_every_call_but_sums_only_scored_rows() -> None:
    result = _run(
        [_reported(10, 2), _reported(100, 5), _malformed(), _errored()],
        [_task(), _task()],
    )
    assert result["n_scored_tasks"] == 1
    assert result["n_measurement_error_tasks"] == 1
    agg = result["provider_usage"]
    assert agg["calls"] == 4
    assert (agg["reported"], agg["malformed"], agg["error"]) == (2, 1, 1)
    # Row two is a measurement error (B raised) so its A call, although
    # malformed, is outside the scored sums; the scored row alone is reported.
    assert agg["provider_input_tokens_A"] == 10
    assert agg["provider_output_tokens_A"] == 2
    assert agg["provider_input_tokens_B"] == 100
    assert agg["provider_output_tokens_B"] == 5
    error_row = result["per_task"][1]
    assert error_row["provider_usage_status_A"] == "malformed"
    assert error_row["provider_usage_status_B"] == "error"
    assert error_row["provider_usage_evidence_A"]["error"] == "total mismatch"


def test_run_tier2_no_scored_rows_yields_none_not_zero() -> None:
    result = _run([_errored(), _reported(100, 5)], [_task()])
    assert result["n_scored_tasks"] == 0
    agg = result["provider_usage"]
    assert agg["calls"] == 2 and agg["reported"] == 1 and agg["error"] == 1
    for arm in ("A", "B"):
        assert agg[f"provider_input_tokens_{arm}"] is None
        assert agg[f"provider_output_tokens_{arm}"] is None


def test_run_tier2_reported_usage_on_a_measurement_error_row_is_counted_not_summed() -> None:
    truncated = _reported(10, 2)
    truncated["text_truncated"] = True
    result = _run([truncated, _reported(100, 5)], [_task()])
    assert result["n_scored_tasks"] == 0
    agg = result["provider_usage"]
    assert agg["reported"] == 2
    assert agg["provider_input_tokens_A"] is None
    assert agg["provider_input_tokens_B"] is None


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

def _nemesis_module():
    path = Path(__file__).with_name("test_eval_tier2_text_evidence_nemesis.py")
    spec = importlib.util.spec_from_file_location("tier2_nemesis", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_render_line_is_present_only_when_the_result_carries_provider_usage() -> None:
    nemesis = _nemesis_module()
    legacy = nemesis._malicious_result()
    before = copy.deepcopy(legacy)
    text = report.render_tier2(legacy)
    assert "provider-reported tokens" not in text
    assert legacy == before

    result = _run(
        [_reported(10, 2), _reported(100, 5), _reported(7, 3), _absent()],
        [_task(), _task()],
    )
    text = report.render_tier2(result)
    text.encode("ascii")
    line = next(l for l in text.splitlines() if "provider-reported tokens" in l)
    assert line == (
        "provider-reported tokens (tokenizer unknown): A in=17 out=5 "
        "B in=n/a out=n/a ; 3/4 calls reported, 1 absent, 0 malformed, 0 error, 0 unknown"
    )


def test_render_line_neutralises_forged_values_in_the_usage_aggregate() -> None:
    nemesis = _nemesis_module()
    result = nemesis._malicious_result()
    result["provider_usage"] = {
        "calls": "2\x1b[2J\nFORGED", "reported": 1, "absent": 0, "malformed": "1\x07",
        "error": 0, "unknown": 0, "tokenizer": "tok\x1b[2J\nFORGED",
        "provider_input_tokens_A": "1\r\nFORGED", "provider_output_tokens_A": 1,
        "provider_input_tokens_B": None, "provider_output_tokens_B": "z" * 4096,
    }
    before = copy.deepcopy(result)
    text = report.render_tier2(result)
    for control in ("\x00", "\x07", "\x1b", "\x7f", "\r"):
        assert control not in text
    assert "\nFORGED" not in text
    assert "z" * (tier2._MAX_TERMINAL_FIELD_CHARS + 1) not in text
    text.encode("ascii")
    assert "provider-reported tokens" in text
    assert result == before
