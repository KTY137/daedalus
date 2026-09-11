from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from daedalus.limit_policy import (
    ExecutionLimitPolicy,
    LimitAxes,
    MODE_CUSTOM,
    MODE_UNBOUNDED_EXECUTION,
)
from daedalus.orchestration.loop import LoopBounds, LoopDriver, LoopLedger, LoopMisconfigured, _Spend


class _Switch:
    def __init__(self, stopped: bool = False) -> None:
        self.stopped = stopped
        self.reason = "owner stop" if stopped else ""
        self.path = "killswitch.json"

    def should_stop(self) -> bool:
        return self.stopped


def _policy(**axes: bool) -> ExecutionLimitPolicy:
    configured = LimitAxes(**{**LimitAxes().as_dict(), **axes})
    return ExecutionLimitPolicy(mode=MODE_CUSTOM, configured=configured)


def _driver(tmp_path, policy: ExecutionLimitPolicy, *, stopped: bool = False):
    return LoopDriver(
        tmp_path,
        bounds=LoopBounds(
            max_iterations=1,
            max_wall_clock_s=0.01,
            max_spend_usd=0.01,
            max_attempts_per_candidate=1,
        ),
        switch=_Switch(stopped),
        executor=object(),
        dry_run=False,
        runs_dir=tmp_path / "runs",
        limit_policy=policy,
    )


def test_unbounded_loop_skips_numeric_stops_but_never_the_kill_switch(tmp_path):
    unlimited = ExecutionLimitPolicy(mode=MODE_UNBOUNDED_EXECUTION)
    driver = _driver(tmp_path, unlimited)

    assert driver._stop_reason(
        iterations_done=100,
        started_monotonic=time.monotonic() - 10_000,
        spend_at_start=_Spend("period", 0.0, True),
    ) is None

    stopped = _driver(tmp_path, unlimited, stopped=True)
    reason = stopped._stop_reason(
        iterations_done=0,
        started_monotonic=time.monotonic(),
        spend_at_start=_Spend("period", 0.0, True),
    )
    assert reason == ("killswitch", "owner stop")


def test_attempt_axis_controls_candidate_retry_admission_without_erasing_history():
    ledger = LoopLedger(None)
    ledger.attempts["candidate"] = {"n": 7, "outcomes": ["failed"] * 7}
    bounds = LoopBounds(max_attempts_per_candidate=1)

    refused, detail = ledger.verdict("candidate", (), bounds, _policy(attempts=True))
    admitted, unbounded_detail = ledger.verdict(
        "candidate", (), bounds, _policy(attempts=False)
    )

    assert refused is False
    assert "attempted 7x" in detail
    assert admitted is True
    assert unbounded_detail == ""
    assert ledger.n_attempts("candidate") == 7


def test_work_scope_axis_requests_the_full_ranked_queue(tmp_path, monkeypatch):
    seen: list[int | None] = []

    def build_queue(_root, *, limit, **_kwargs):
        seen.append(limit)
        return SimpleNamespace(candidates=[])

    monkeypatch.setattr("daedalus.spine.picker.build_queue", build_queue)

    bounded = _driver(tmp_path, _policy(work_scope=True))
    bounded._pick()
    unlimited = _driver(tmp_path, _policy(work_scope=False))
    unlimited._pick()

    assert seen == [25, None]


def test_loop_captures_policy_in_effect_bounds_and_report(tmp_path, monkeypatch):
    captured = {}

    class Executor:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("daedalus.build_exec.WaveExecutor", Executor)
    policy = _policy(mission_spend=False, wall_time=False)
    driver = LoopDriver(
        tmp_path,
        switch=_Switch(),
        runs_dir=tmp_path / "runs",
        limit_policy=policy,
    )

    effect_bounds = captured["effect_bounds"]
    assert effect_bounds.max_spend_usd == driver.bounds.max_spend_usd
    assert effect_bounds.timeout_s == driver.bounds.max_wall_clock_s
    assert effect_bounds.limit_policy is policy
    assert driver.limit_policy.as_dict() == policy.as_dict()
    assert len(driver.limit_policy.fingerprint_sha256) == 64


def test_invalid_ambient_limit_policy_refuses_loop_construction(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_EXECUTION_LIMIT_POLICY", "{broken")
    with pytest.raises(LoopMisconfigured, match="execution limit policy is invalid"):
        LoopDriver(tmp_path, switch=_Switch(), executor=object())
