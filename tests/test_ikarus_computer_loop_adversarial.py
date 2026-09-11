"""Adversarial pins for G1-IKARUS-26 (stage 13), lane 9.

Two properties the packet states as contract had no test: mutation testing on a
scratch copy of ``cfe8d34b`` showed that normalising whitespace in the
identical-plan comparison, and reverting the ``/computer status`` sentence to
its single pre-stage-13 form, both left ``tests/test_ikarus_computer_loop.py``
and ``tests/runtimes/test_computer_service.py`` fully green (56 passed).

Packet: docs/work-packets/G1-IKARUS-26_COMPUTER_LOOP_LIVE.md, "Contracts and
behavior".  Review: docs/evidence/G1-IKARUS-26_COMPUTER_LOOP_LIVE/adversarial_review.md.
Fake adapters are contract evidence, not live host evidence.
"""
from __future__ import annotations

import json

import pytest

from daedalus.orchestration.ikarus import computer_loop as loop
from daedalus.spine.durability import open_gate0_spine_writer

RELEASE_LOCK = ("workspace path tools are disabled in v0.1.6 until handle-relative, "
                "reparse-safe I/O is independently verified")
# Same literal steps; the second differs only by trailing/leading whitespace.
PLAN = {"type": "plan", "steps": ["Read the page and report the title.",
                                  "Observe the current browser DOM again."]}
PLAN_PADDED = {"type": "plan", "steps": ["Read the page and report the title. ",
                                         " Observe the current browser DOM again."]}
FINISH = {"type": "finish", "summary": "nothing to do"}


class _Service:
    """Minimal computer adapter double; grants nothing and executes nothing."""

    policy_digest = "a" * 64

    def __init__(self, *, max_steps=8):
        self.calls = []
        self.max_steps = max_steps

    def capabilities(self):
        return {"enabled": True, "unavailable": {},
                "tools": [{"name": "file.read", "description": "Read a permitted file",
                           "parameters": {}}],
                "max_steps": self.max_steps, "timeout_s": 10, "planner_provider": "ollama_http"}

    def check_cancelled(self):
        return None

    def execute(self, tool, arguments, *, mission_id, attempt_id):  # pragma: no cover
        self.calls.append(tool)
        raise AssertionError("no tool may run in these plan-only missions")


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("DAEDALUS_EXECUTION_LIMIT_POLICY", raising=False)
    monkeypatch.setattr(loop, "control_root", lambda root: tmp_path / "control")
    monkeypatch.setattr(loop, "_context_snapshot",
                        lambda root: {"context_sha256": "d" * 64, "notes": [], "skills": []})
    with open_gate0_spine_writer(tmp_path / "spine.sqlite3") as ledger:
        yield tmp_path, ledger


def _planner(*responses):
    pending = iter(responses)
    return lambda *args: json.dumps(next(pending))


def test_a_whitespace_only_difference_is_a_different_plan(isolated):
    """The packet pins exact comparison of the parsed ordered steps: "no whitespace
    normalisation, which could equate different literals" (Codex, room 16:49).  A
    normalising comparison would stall here on planner call 3.

    Three plans, not four: since G1-IKARUS-29 the loop also stalls after
    ``_MAX_PLANS_PER_STEP`` (4) consecutive plans without a tool step, counted
    regardless of content, so the sequence stays below that budget and the
    only rule that can fire here is the identical-plan comparison under test."""
    root, ledger = isolated
    service = _Service()
    result = loop.run_computer_task(
        root, "Read fixture", service=service, ledger=ledger,
        propose=_planner(PLAN, PLAN_PADDED, PLAN, FINISH))
    assert result["state"] == "no_actions", result["summary"]
    assert result["planner_calls"] == 4, result["summary"]
    assert result["plan"]["steps"] == PLAN["steps"]
    assert service.calls == []


def test_three_padded_plans_do_stall_so_the_rule_is_literal_not_absent(isolated):
    """The counterpart: the same padded literal three times in a row still stalls, so
    the previous test pins literal comparison rather than a broken counter."""
    root, ledger = isolated
    result = loop.run_computer_task(
        root, "Read fixture", service=_Service(), ledger=ledger,
        propose=_planner(PLAN_PADDED, PLAN_PADDED, PLAN_PADDED, FINISH))
    assert result["state"] == "stalled"
    assert "identical advisory plans" in result["summary"]
    assert result["planner_calls"] == 3


def _status_summary(monkeypatch, capabilities):
    from daedalus.runtimes import computer as runtimes_computer
    monkeypatch.setattr(runtimes_computer, "computer_status", lambda root, project=None, project_readers=None, campaign_runner=None: capabilities)
    events = [payload for event, payload in loop.conversation_events(None, "/computer status")
              if event == "final"]
    return events[-1]["assistant"]


@pytest.mark.parametrize("capabilities, opening, closing", [
    ({"enabled": False, "tools": [], "unavailable": {"file.read": RELEASE_LOCK}},
     "every configured tool is unavailable on this host", "Unavailable: file.read"),
    ({"enabled": False, "tools": []},
     "unavailable until its owner policy is configured", None),
    ({"enabled": True, "tools": [{"name": "browser.read"}], "workspace": "W",
      "unavailable": {"file.read": RELEASE_LOCK}},
     "Computer assistance is configured. Use /computer", "Unavailable: file.read"),
])
def test_computer_status_sentence_distinguishes_locked_mixed_and_missing_policy(
        monkeypatch, capabilities, opening, closing):
    """G1-IKARUS-26 primary claim: /computer status names "configured but every tool
    unavailable" apart from "no policy", and a mixed policy stays configured."""
    summary = _status_summary(monkeypatch, capabilities)
    assert opening in summary.splitlines()[0], summary.splitlines()[0]
    if closing is None:
        assert "Unavailable:" not in summary
    else:
        assert closing in summary
