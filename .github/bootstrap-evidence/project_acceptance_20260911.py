"""Executable project acceptance, NOT a live-LLM capability benchmark.

The opt-in cases use the real Ikarus loop, ComputerService, leases, Ariadne,
contained project tests and source CAS. Only planning is scripted. The entire
pinned Daedalus checkout is the subject, not a padded synthetic project.

Run on a supported containment host with DAEDALUS_PROJECT_ACCEPTANCE=1.
A missing sandbox fails the run; there is no host-process fallback. No
candidate is promoted or written into the subject checkout.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

import pytest

from daedalus.ariadne.campaign import (
    TestCommandEvaluator as FrozenTestCommand, protected_prefix_for, run_campaign,
)
from daedalus.foundation import projects
from daedalus.kernel.policy.computer import ARIADNE_TOOLS, ComputerPolicy, policy_path
from daedalus.orchestration.ikarus import computer_loop
from daedalus.runtimes.computer import ComputerService
from daedalus.runtimes.computer_ariadne import AriadneCampaignTool, CampaignRunner
from daedalus.spine import killswitch
from daedalus.spine.durability import open_gate0_spine_writer

ROOT = Path(__file__).resolve().parents[1]
TOOL = "daedalus.ariadne_campaign"
TARGET = "daedalus/twin/semiring.py"
BEFORE = "first + second"
REFACTOR = "(first + second)"
REGRESSION = "first * second"
EVALUATOR = FrozenTestCommand(
    argv=("python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/twin"),
    timeout_s=120,
)
PROJECT_CASE = pytest.mark.skipif(
    os.environ.get("DAEDALUS_PROJECT_ACCEPTANCE") != "1",
    reason="explicit project acceptance requires actual candidate containment",
)


def _git(*args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(ROOT), *args], check=True, capture_output=True, timeout=30,
    ).stdout


def _read_hashed_json(locator: str, expected: str) -> dict:
    payload = Path(locator).read_bytes()
    assert hashlib.sha256(payload).hexdigest() == expected
    return json.loads(payload)


def _retain(report: dict, name: str, fallback: Path) -> None:
    # Keep the acceptance evidence outside the candidate tree, on failure too.
    destination = Path(os.environ.get("RUNNER_TEMP", str(fallback))) / "project-acceptance"
    destination.mkdir(parents=True, exist_ok=True)
    (destination / f"{name}.json").write_text(
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True), encoding="utf-8",
    )


@PROJECT_CASE
@pytest.mark.parametrize("case,after", [("refactor", REFACTOR), ("regression", REGRESSION)])
def test_real_ikarus_runs_the_full_repository_candidate_through_ariadne(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, after: str,
) -> None:
    """Prove orchestration/non-regression and negative control, not model skill."""
    revision = _git("rev-parse", "HEAD").decode().strip()
    source_paths = _git("ls-tree", "-r", "--name-only", "HEAD").decode().splitlines()
    python_files = sum(path.endswith(".py") for path in source_paths)
    assert python_files >= 1000, "this acceptance must exercise the real large repository"
    source = _git("show", f"HEAD:{TARGET}")
    assert source.decode().count(BEFORE) == 1
    tracked_before = _git("status", "--porcelain", "--untracked-files=no")
    target_before = (ROOT / TARGET).read_bytes()
    assert target_before == source, "do not evaluate a different dirty target as HEAD"
    assert protected_prefix_for(TARGET) is None

    # Relocate only test-owned profile/registry state; all real admission,
    # leases, subprocess containment and evidence checks remain enabled.
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    monkeypatch.setenv("USERPROFILE" if os.name == "nt" else "HOME", str(profile))
    monkeypatch.delenv("DAEDALUS_KILLSWITCH", raising=False)
    monkeypatch.delenv("DAEDALUS_EXECUTION_LIMIT_POLICY", raising=False)
    authority = tmp_path / "authority"
    authority.mkdir()
    monkeypatch.setattr(projects, "PROJECT_DIR", authority / "projects")
    registration = projects.register_project(str(ROOT), "project-acceptance")
    assert registration["created"] is True
    workspace = tmp_path / "computer-workspace"
    workspace.mkdir()
    policy = ComputerPolicy(
        workspace=workspace, tools=ARIADNE_TOOLS, max_steps=4, timeout_s=900,
        planner_provider="claude_code_cli", allow_remote_context=True,
    )
    policy_file = policy_path(authority)
    policy_file.parent.mkdir(parents=True, exist_ok=True)
    policy_file.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    switches = [killswitch.KillSwitch(repo_root=root, sweep_managed=False)
                for root in (authority, ROOT)]
    for switch in switches:
        assert switch.arm(note="explicit, isolated project acceptance").running

    receipts: list[dict] = []
    calls: list[dict] = []

    def real_campaign(**kwargs):
        # Existing caller-owned evaluator seam: no mocked receipt or effect.
        calls.append(dict(kwargs))
        receipt = run_campaign(**kwargs, evaluator=EVALUATOR)
        receipts.append(receipt)
        return receipt

    runner = CampaignRunner(
        run_campaign=real_campaign, head_revision=computer_loop.head_revision,
        protected_prefix_for=protected_prefix_for,
    )
    service = ComputerService(authority, project=registration["name"], campaign_runner=runner)
    proposals = iter([
        {"type": "tool", "tool": TOOL, "arguments": {
            "target_path": TARGET, "before": BEFORE, "after": after,
            "campaign_id": f"project-{case}", "timeout_s": 120,
        }},
        {"type": "finish", "summary": "The measured campaign outcome is retained; nothing was applied."},
    ])
    planner_calls = 0

    def scripted_planner(*_args):
        nonlocal planner_calls
        planner_calls += 1
        return json.dumps(next(proposals))

    evidence = {
        "schema": "daedalus-project-acceptance/1", "case": case,
        "source_revision": revision, "tracked_file_count": len(source_paths),
        "python_file_count": python_files, "target_path": TARGET,
        "planner_kind": "scripted integration fixture; no LLM inference",
        "evaluator_sha256": EVALUATOR.digest,
        "claim": "single-file candidate on full repository; not autonomous project development",
        "passed": False,
    }
    try:
        with open_gate0_spine_writer(tmp_path / "mission-spine.sqlite3") as ledger:
            mission = computer_loop.run_computer_task(
                authority, "Evaluate a controlled project refactor against the project tests.",
                service=service, ledger=ledger, propose=scripted_planner,
                mission_id=f"project-{case}",
            )
        evidence["mission"] = mission
        assert len(calls) == 1, "uncertain or failed effects must not be repeated"
        assert calls[0]["source_revision"] == revision
        assert mission["task_success_verified"] is False, "a scripted finish grants no capability claim"
        assert len(mission["steps"]) == 1 and mission["steps"][0]["tool"] == TOOL
        if case == "regression":
            assert mission["state"] == "blocked" and receipts == []
            assert planner_calls == 1
            outcome = mission["steps"][0]["outcome"]
            assert outcome["ok"] is False
            assert outcome["state"] == "reconciliation_required"
            assert outcome["error_type"] == "_CampaignFailure"
            assert outcome["error"].startswith("AriadneCampaignError:")
            failure_record = outcome["evidence"]["failure_record"]
            assert set(failure_record) == {"locator", "sha256"}
            assert failure_record["locator"] == (
                "artifact-locator:sha256:" + failure_record["sha256"]
            )
            assert len(failure_record["sha256"]) == 64
        else:
            assert mission["state"] == "completed", mission
            assert planner_calls == 2 and len(receipts) == 1
            receipt = receipts[0]
            assert receipt["source_revision"] == revision
            assert receipt["metric_names"] == ["tests_pass"]
            assert [trial["status"] for trial in receipt["trials"]] == ["passed", "failed", "passed"]
            observed = []
            for trial in receipt["trials"]:
                packet = _read_hashed_json(trial["evidence_packet_locator"], trial["evidence_packet_sha256"])
                assert packet["source_revision"] == revision
                item, = packet["items"]
                observation = _read_hashed_json(item["evidence_locator"], item["output_sha256"])
                assert observation["workspace_removed"] is True
                assert observation["workspace_files"] >= 1000
                assert observation["verdict_is_self_reported"] is True
                assert observation["containment"], "never silently run on the host"
                observed.append(observation)
            assert observed[0]["report"]["executed"] >= 400
            assert observed[0]["report"]["executed"] == observed[2]["report"]["executed"]
            projection = mission["steps"][0]["outcome"]["result"]
            assert projection["postcondition_verified"] is True and projection["applied"] is False
            assert "test-command" in projection["evaluator"]
            assert "self-report" in projection["evaluator"]
            evidence["observations"] = observed
            evidence["candidate_tree_sha256"] = receipt["candidate_tree_sha256"]
        evidence["passed"] = True
    finally:
        service.close()
        for switch in switches:
            switch.stop("project acceptance finished")
        evidence["source_unchanged"] = (
            _git("rev-parse", "HEAD").decode().strip() == revision
            and _git("status", "--porcelain", "--untracked-files=no") == tracked_before
            and (ROOT / TARGET).read_bytes() == target_before
        )
        _retain(evidence, case, tmp_path)
        assert evidence["source_unchanged"], "no candidate may alter the subject checkout"


@pytest.mark.parametrize("metrics,label", [
    (["tests_pass"], "test-command-evaluator (candidate self-report)"),
    (["exact_match"], "frozen-evaluator (exact match)"),
    (["unknown"], "unrecognized campaign evaluator (unverified)"),
])
def test_campaign_projection_names_the_actual_evaluator_without_upgrading_trust(
    tmp_path: Path, metrics: list[str], label: str,
) -> None:
    def forbidden(**_kwargs):
        pytest.fail("a receipt projection must not run a campaign")

    tool = AriadneCampaignTool(
        ComputerPolicy(workspace=tmp_path), "unregistered", lambda: None,
        tmp_path, CampaignRunner(forbidden, lambda _: "0" * 40, lambda _: None),
    )
    result = tool._project_receipt(
        {"outcome": "failed", "metric_names": metrics, "trials": []},
        "pkg/module.py", "projection-only", "0" * 40, str(tmp_path), time.time(),
    )
    assert label in result["evaluator"]
    assert result["applied"] is False and result["postcondition_verified"] is False
    assert any(bound in result["note"] for bound in (
        "not improvement", "not autonomous improvement", "no test or improvement claim",
    ))
