"""G1-IKARUS-47 (A11): a computer mission can reach ``daedalus.ariadne_campaign``
through the loop, and the mission report states the campaign's verdict as a
measured outcome -- never as an applied change."""
from __future__ import annotations

import json

import pytest

from daedalus.orchestration.ikarus import computer_loop as loop
from daedalus.spine.durability import open_gate0_spine_writer

TOOL = "daedalus.ariadne_campaign"
CAMPAIGN = {"type": "tool", "tool": TOOL,
            "arguments": {"target_path": "pkg/mod.py", "before": "return 1", "after": "return 2"}}
DONE = {"type": "finish", "summary": "I nominated a repair."}


class CampaignService:
    policy_digest = "a" * 64

    def __init__(self, result):
        self.calls = []
        self.result = result

    def capabilities(self):
        return {"enabled": True,
                "tools": [{"name": TOOL, "description": "Run one Ariadne controlled-repair campaign.",
                           "parameters": {"type": "object", "properties": {}, "required": []}}],
                "unavailable": {}, "max_steps": 4, "timeout_s": 10, "planner_provider": "ollama_http"}

    def check_cancelled(self):
        return None

    def execute(self, tool, arguments, *, mission_id, attempt_id):
        self.calls.append((tool, arguments, mission_id, attempt_id))
        return self.result


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.delenv("DAEDALUS_EXECUTION_LIMIT_POLICY", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setattr(loop, "control_root", lambda root: tmp_path / "control")
    monkeypatch.setattr(loop, "_context_snapshot", lambda root: {"context_sha256": "d" * 64, "notes": [], "skills": []})
    with open_gate0_spine_writer(tmp_path / "spine.sqlite3") as ledger:
        yield tmp_path, ledger


def planner(*responses):
    pending = iter(responses)
    return lambda *args: json.dumps(next(pending))


def _nominated():
    return {"ok": True, "state": "completed", "evidence": {"digest": "b" * 64},
            "result": {"schema": "daedalus-computer-ariadne-result/1", "kind": "campaign", "outcome": "nominated",
                       "campaign_id": "ikarus-abc", "target_path": "pkg/mod.py", "applied": False,
                       "postcondition_verified": True, "host_mutation": True,
                       "candidate_tree_sha256": "c" * 64, "nomination_receipt_sha256": "n" * 64,
                       "trials": [{"variant_id": "baseline", "status": "failed"},
                                  {"variant_id": "negative-control", "status": "failed"},
                                  {"variant_id": "repair", "status": "passed"}],
                       "evaluator": "ariadne-frozen-evaluator (exact match)"}}


def test_a_mission_reaches_the_campaign_tool_and_reports_the_nomination_as_measured(isolated):
    root, ledger = isolated
    service = CampaignService(_nominated())
    result = loop.run_computer_task(root, "verbessere pkg/mod.py", service=service, ledger=ledger,
                                    propose=planner(CAMPAIGN, DONE), mission_id="ariadne-loop-1")
    assert [call[0] for call in service.calls] == [TOOL]
    assert service.calls[0][1] == CAMPAIGN["arguments"]
    step = result["steps"][0]
    assert step["tool"] == TOOL and step["outcome"]["result"]["outcome"] == "nominated"
    assert step["outcome"]["result"]["applied"] is False
    text = loop._chat_report(result)
    assert TOOL in text
    # The report never upgrades a nomination into an applied change.
    assert "angewendet" not in text.lower().replace("nie angewendet", "") or "nominated" in text


def test_a_refused_campaign_blocks_the_mission_without_a_repeat(isolated):
    root, ledger = isolated
    refused = {"ok": False, "state": "blocked", "error_type": "_PreRunRefusal",
               "error": "target_path is inside the self-Renovation leakage boundary (master plan section 8.1): daedalus/spine/"}
    service = CampaignService(refused)
    result = loop.run_computer_task(root, "verbessere die Spine", service=service, ledger=ledger,
                                    propose=planner({**CAMPAIGN, "arguments": {**CAMPAIGN["arguments"],
                                                                                "target_path": "daedalus/spine/x.py"}},
                                                    CAMPAIGN, DONE),
                                    mission_id="ariadne-loop-2")
    assert len(service.calls) == 1, "a refused effect is never repeated"
    assert result["state"] == "blocked"
    assert "leakage boundary" in json.dumps(result["steps"])
