"""Acceptance test C3 (G3-BASE-01 §5c): the single-LLM-loop baseline arm.

This is the only Gate-3 arm allowed to make a model call, and it must degrade
cleanly to a skip when no provider is reachable. Every test in this module is
fast, offline, and makes NO real network call: ``harness.detect_provider`` and
``tier2._ask`` are monkeypatched at their module attribute (the same seam
``test_arm_bm25.py`` uses for ``harness._bm25_scores``), and one test proves
directly that even an unmocked provider call cannot escape to the real
network by exploding ``urllib.request.urlopen`` and asserting the arm still
returns an ordinary errored outcome instead of propagating.
"""
from __future__ import annotations

import math
import urllib.request
from pathlib import Path

import pytest

from daedalus.eval import harness, tier2
from daedalus.eval.gate3.arms.single_llm_loop import SingleLlmLoopArm
from daedalus.eval.gate3.contracts import ArmBudget, FreezeError
from daedalus.eval.gate3.protocols import SealedEvaluator, Task, run_trial

_FAKE_PROV = {
    "kind": "ollama",
    "host": "http://127.0.0.1:11434",
    "model": "test-model",
    "models": ["test-model"],
}


def _build_repo(tmp_path: Path) -> str:
    (tmp_path / "widget.py").write_text(
        'def widget():\n    """A tiny widget."""\n    return "widget"\n',
        encoding="utf-8",
    )
    return str(tmp_path)


def _task(repo_root: str) -> Task:
    return Task(task_id="t1", repo_root=repo_root, question="what does widget do?",
                target="widget.py::widget", label_plane="code")


def _marker_evaluator(scores: dict[str, float], default: float = 0.0,
                       max_calls: int | None = None) -> SealedEvaluator:
    """Score by which marker substring appears in the candidate."""

    def score_fn(candidate: str, task: Task) -> float:
        for marker, value in scores.items():
            if marker in candidate:
                return value
        return default

    return SealedEvaluator("marker", score_fn, max_calls=max_calls)


def _ok_receipt(text: str) -> dict:
    return {
        "ok": True, "text": text, "text_chars": len(text),
        "text_sha256": "deadbeef", "text_truncated": False,
        "error_type": None, "error": None,
    }


def _err_receipt(message: str) -> dict:
    return {
        "ok": False, "text": None, "text_chars": 0, "text_sha256": None,
        "text_truncated": False, "error_type": "SimulatedProviderError",
        "error": message,
    }


def _scripted_ask(responses: list[str]):
    """A fake ``tier2._ask`` that hands out ``responses`` in order, then
    errors once the script runs out. Returns ``(fn, calls)`` so a test can
    inspect exactly how many times -- and with what question text -- it was
    invoked."""
    calls: list[tuple[dict, str, str]] = []

    def fake_ask(prov: dict, question: str, context: str) -> dict:
        calls.append((prov, question, context))
        idx = len(calls) - 1
        if idx < len(responses):
            return _ok_receipt(responses[idx])
        return _err_receipt("scripted responses exhausted")

    return fake_ask, calls


# --------------------------------------------------------------------------- #
# provider gating: the hard requirement                                       #
# --------------------------------------------------------------------------- #
def test_no_provider_returns_clean_skip_never_a_crash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "detect_provider", lambda *a, **k: None)
    repo = _build_repo(tmp_path)
    arm = SingleLlmLoopArm()
    evaluator = _marker_evaluator({}, max_calls=None)

    outcome = arm.run(_task(repo), ArmBudget(max_calls=3), evaluator, seed=0)

    assert outcome.error is not None
    assert "single_llm_loop" in outcome.error
    assert "skip" in outcome.error.lower()
    assert outcome.success is None
    assert outcome.score is None
    assert evaluator.calls == 0  # never touched -- skip happens before any work


def test_no_provider_run_trial_has_error_and_no_success_or_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "detect_provider", lambda *a, **k: None)
    repo = _build_repo(tmp_path)
    arm = SingleLlmLoopArm()
    evaluator = _marker_evaluator({}, max_calls=None)

    result = run_trial(arm, _task(repo), ArmBudget(max_calls=3), evaluator, seed=0)

    assert result.error is not None
    assert result.success is None
    assert result.score is None
    assert result.measured is False


# --------------------------------------------------------------------------- #
# the loop itself, under a scripted mock provider                             #
# --------------------------------------------------------------------------- #
def test_loop_iterates_and_returns_best_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "detect_provider", lambda *a, **k: dict(_FAKE_PROV))
    fake_ask, calls = _scripted_ask([
        "draft one, no marker yet",
        "draft two, getting closer MARK_MID",
        "final answer MARK_FULL achieved",
    ])
    monkeypatch.setattr(tier2, "_ask", fake_ask)

    repo = _build_repo(tmp_path)
    arm = SingleLlmLoopArm()
    evaluator = _marker_evaluator({"MARK_FULL": 1.0, "MARK_MID": 0.6}, default=0.2)

    outcome = arm.run(_task(repo), ArmBudget(max_calls=5), evaluator, seed=0)

    assert outcome.error is None
    assert outcome.success is True
    assert outcome.score == 1.0
    assert "MARK_FULL" in outcome.candidate
    # stops as soon as the success ceiling is reached -- does not burn the
    # remaining declared budget once there is nothing left to gain.
    assert len(calls) == 3
    assert outcome.notes["iterations_run"] == 3
    assert outcome.notes["model_id"] == "test-model"
    assert outcome.notes["tokens_estimated"] is True


def test_loop_respects_max_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "detect_provider", lambda *a, **k: dict(_FAKE_PROV))
    fake_ask, calls = _scripted_ask([
        "draft one, no marker yet",
        "draft two, getting closer MARK_MID",
        "final answer MARK_FULL achieved",
    ])
    monkeypatch.setattr(tier2, "_ask", fake_ask)

    repo = _build_repo(tmp_path)
    arm = SingleLlmLoopArm()
    evaluator = _marker_evaluator({"MARK_FULL": 1.0, "MARK_MID": 0.6}, default=0.2,
                                   max_calls=2)

    outcome = arm.run(_task(repo), ArmBudget(max_calls=2), evaluator, seed=0)

    assert outcome.error is None
    assert len(calls) == 2  # never reaches the third, winning response
    assert evaluator.calls == 2
    assert outcome.success is False  # best reachable in 2 calls is 0.6
    assert outcome.score == 0.6
    assert outcome.notes["iterations_run"] == 2
    assert outcome.notes["max_iterations"] == 2


def test_revision_prompt_carries_prior_answer_and_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The second call must be a genuine revision, not a repeat of the first
    question -- otherwise this arm is not 'a loop', it is one call twice."""
    monkeypatch.setattr(harness, "detect_provider", lambda *a, **k: dict(_FAKE_PROV))
    fake_ask, calls = _scripted_ask(["first draft MARK_A", "second draft MARK_B"])
    monkeypatch.setattr(tier2, "_ask", fake_ask)

    repo = _build_repo(tmp_path)
    arm = SingleLlmLoopArm()
    evaluator = _marker_evaluator({"MARK_B": 1.0, "MARK_A": 0.4})

    arm.run(_task(repo), ArmBudget(max_calls=2), evaluator, seed=0)

    assert len(calls) == 2
    first_question = calls[0][1]
    second_question = calls[1][1]
    assert first_question == "what does widget do?"
    assert "0.4" in second_question or "0.400" in second_question
    assert "first draft MARK_A" in second_question
    assert second_question != first_question


# --------------------------------------------------------------------------- #
# best-so-far monotonicity (measure D2's underlying invariant)                #
# --------------------------------------------------------------------------- #
def test_best_so_far_is_monotone_even_when_raw_scores_fluctuate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "detect_provider", lambda *a, **k: dict(_FAKE_PROV))
    # Raw scores fluctuate: 0.3 -> 0.9 -> 0.5. The PEAK is in the middle.
    fake_ask, calls = _scripted_ask(["MARK_LOW draft", "MARK_HIGH draft", "MARK_MED draft"])
    monkeypatch.setattr(tier2, "_ask", fake_ask)

    repo = _build_repo(tmp_path)
    arm = SingleLlmLoopArm()
    evaluator = _marker_evaluator(
        {"MARK_HIGH": 0.9, "MARK_MED": 0.5, "MARK_LOW": 0.3})

    outcome = arm.run(_task(repo), ArmBudget(max_calls=3), evaluator, seed=0)

    history = outcome.notes["score_history"]
    assert history == [0.3, 0.9, 0.5]

    running_best = []
    current = -math.inf
    for s in history:
        current = max(current, s)
        running_best.append(current)

    # Monotone non-decreasing by construction of a running max...
    assert all(b1 <= b2 for b1, b2 in zip(running_best, running_best[1:]))
    # ...and the arm's reported best must be the true peak (0.9, from the
    # MIDDLE iteration), not merely the last call's score.
    assert outcome.score == 0.9
    assert "MARK_HIGH" in outcome.candidate
    assert running_best[-1] == outcome.score


# --------------------------------------------------------------------------- #
# ordinary failure: every provider call errors -> errored outcome, no raise   #
# --------------------------------------------------------------------------- #
def test_every_provider_call_failing_yields_error_outcome_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "detect_provider", lambda *a, **k: dict(_FAKE_PROV))

    def always_fails(prov: dict, question: str, context: str) -> dict:
        return _err_receipt("simulated: model unreachable mid-run")

    monkeypatch.setattr(tier2, "_ask", always_fails)

    repo = _build_repo(tmp_path)
    arm = SingleLlmLoopArm()
    evaluator = _marker_evaluator({}, default=0.0)

    outcome = arm.run(_task(repo), ArmBudget(max_calls=3), evaluator, seed=0)

    assert outcome.error is not None
    assert outcome.success is None
    assert outcome.score is None
    assert evaluator.calls == 0  # a failed provider call is never scored

    result = run_trial(arm, _task(repo), ArmBudget(max_calls=3),
                        _marker_evaluator({}, default=0.0), seed=0)
    assert result.error is not None
    assert result.success is None
    assert result.score is None


def test_evaluator_contract_violation_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A FreezeError from the sealed evaluator (exhausted call budget) is a
    contract violation and must propagate, never be swallowed."""
    monkeypatch.setattr(harness, "detect_provider", lambda *a, **k: dict(_FAKE_PROV))
    fake_ask, _ = _scripted_ask(["draft MARK_A", "draft MARK_B"])
    monkeypatch.setattr(tier2, "_ask", fake_ask)

    repo = _build_repo(tmp_path)
    arm = SingleLlmLoopArm()
    evaluator = _marker_evaluator({"MARK_A": 1.0}, max_calls=0)

    with pytest.raises(FreezeError):
        arm.run(_task(repo), ArmBudget(max_calls=3), evaluator, seed=0)


# --------------------------------------------------------------------------- #
# no real network call is ever possible, even when tier2._ask is NOT mocked   #
# --------------------------------------------------------------------------- #
def test_never_makes_a_real_network_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``harness.detect_provider`` is faked (so the real local-Ollama probe
    never runs), but ``tier2._ask`` is left WIRED to the real
    ``_openai_compat.chat_completion`` path. ``urllib.request.urlopen`` is
    replaced with a bomb: if anything on this path ever tried to reach the
    network, this test would raise. It must not -- ``tier2._ask`` catches the
    exception and reports an ordinary provider failure, and this arm must
    turn that into an errored outcome without letting anything escape."""

    def _boom(*args, **kwargs):
        raise AssertionError("a real network call was attempted in a test")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    monkeypatch.setattr(harness, "detect_provider", lambda *a, **k: dict(_FAKE_PROV))

    repo = _build_repo(tmp_path)
    arm = SingleLlmLoopArm()
    evaluator = _marker_evaluator({}, default=0.0)

    outcome = arm.run(_task(repo), ArmBudget(max_calls=2), evaluator, seed=0)

    assert outcome.error is not None
    assert outcome.success is None
    assert outcome.score is None


# --------------------------------------------------------------------------- #
# real provider usage: measured, never assumed                                #
# --------------------------------------------------------------------------- #
def _usage_receipt(text: str, *, total: int | None, status: str = "reported") -> dict:
    """An ok receipt carrying the provider's own usage block, as
    ``tier2._ask`` has returned since it moved to ``chat_completion_receipt``."""
    receipt = _ok_receipt(text)
    receipt["usage_status"] = status
    receipt["usage"] = (
        None if total is None
        else {"input_tokens": total // 2, "output_tokens": total - total // 2,
              "total_tokens": total, "tokenizer": "provider/native"}
    )
    return receipt


def _usage_ask(receipts: list[dict]):
    calls: list[tuple[dict, str, str]] = []

    def fake_ask(prov: dict, question: str, context: str) -> dict:
        calls.append((prov, question, context))
        idx = len(calls) - 1
        return receipts[idx] if idx < len(receipts) else _err_receipt("exhausted")

    return fake_ask, calls


def test_every_call_reporting_usage_makes_tokens_measured_not_estimated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness, "detect_provider", lambda *a, **k: dict(_FAKE_PROV))
    fake_ask, _ = _usage_ask([_usage_receipt("final answer MARK_FULL", total=120)])
    monkeypatch.setattr(tier2, "_ask", fake_ask)

    outcome = SingleLlmLoopArm().run(
        _task(_build_repo(tmp_path)), ArmBudget(max_calls=5),
        _marker_evaluator({"MARK_FULL": 1.0}, default=0.2), seed=0)

    assert outcome.notes["tokens_estimated"] is False
    assert outcome.notes["provider_tokens_reported"] == 120
    assert outcome.notes["provider_calls"] == outcome.notes["provider_calls_with_usage"] == 1
    # The local estimate is carried alongside, never replaced by the provider's.
    assert outcome.notes["local_estimate_tokens"] > 0


def test_one_silent_call_makes_the_whole_run_an_estimate_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case that matters: partial usage must not read as measured.

    A run where the provider reported on some calls and not others is an
    estimate, because the missing calls' spend is unknown -- reporting it as
    measured would present a floor as a total.
    """
    monkeypatch.setattr(harness, "detect_provider", lambda *a, **k: dict(_FAKE_PROV))
    fake_ask, _ = _usage_ask([
        _usage_receipt("draft one, no marker", total=80),
        _usage_receipt("still nothing useful", total=None, status="absent"),
        _usage_receipt("final answer MARK_FULL", total=95),
    ])
    monkeypatch.setattr(tier2, "_ask", fake_ask)

    outcome = SingleLlmLoopArm().run(
        _task(_build_repo(tmp_path)), ArmBudget(max_calls=5),
        _marker_evaluator({"MARK_FULL": 1.0}, default=0.2), seed=0)

    assert outcome.notes["tokens_estimated"] is True
    assert outcome.notes["provider_calls_with_usage"] < outcome.notes["provider_calls"]
    # What WAS reported is still retained -- a floor, honestly labelled.
    assert outcome.notes["provider_tokens_reported"] == 175
    assert outcome.notes["usage_status_counts"].get("absent") == 1


def test_a_provider_reporting_nothing_keeps_the_old_behaviour(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Receipts without a usage key at all -- the pre-receipt shape."""
    monkeypatch.setattr(harness, "detect_provider", lambda *a, **k: dict(_FAKE_PROV))
    fake_ask, _ = _scripted_ask(["final answer MARK_FULL"])
    monkeypatch.setattr(tier2, "_ask", fake_ask)

    outcome = SingleLlmLoopArm().run(
        _task(_build_repo(tmp_path)), ArmBudget(max_calls=5),
        _marker_evaluator({"MARK_FULL": 1.0}, default=0.2), seed=0)

    assert outcome.notes["tokens_estimated"] is True
    assert outcome.notes["provider_tokens_reported"] == 0
    assert outcome.notes["usage_status_counts"] == {"absent": 1}
