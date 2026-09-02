"""What the loop's own receipts must say about the capability and the revision.

Two defects are pinned here, both measured on 2026-08-22:

1. a loop iteration's receipt named no capability at all, so a spend could not
   be joined to the authority that permitted it (``runs/loop/blocker_*.json``);
2. ``governance_verdict`` named HEAD ``6225d3e4`` -- the HEAD of
   ``Desktop/agent_env``, the first REGISTERED project -- while the loop was
   running in ``agent_env_g0`` at ``9887a98e``. ``core.get_governance``
   resolves its repository from the project registry, not from ``--repo-root``.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

from daedalus.orchestration.loop import IterationResult, LoopBounds, LoopDriver, LoopReport

REPO_ROOT = str(Path(__file__).resolve().parents[1])

LEASE_RECEIPT = {
    "verdict": "allow",
    "entrypoint_id": "python.offload",
    "lease_id": "loop-test-wave-offload-w0-abcdef01",
    "lease_sha256": "c" * 64,
    "requested_effects": ["filesystem_write", "network_egress",
                          "process_spawn", "spend"],
    "execution_id": "loop-test-wave-offload-w0-abcdef01-exec-0",
    "policy_decision_id": "loop-test-wave-offload-w0-allow",
    "max_cost_microusd": 250_000,
    "kill_switch_generation": 7,
}


def _git_head(repo_root: str) -> str:
    proc = subprocess.run(["git", "-C", repo_root, "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True)
    return proc.stdout.strip().lower()


def test_iteration_receipt_carries_lease_id_and_effect_set():
    row = IterationResult(
        index=0, candidate_id="cand-1", instruction="fix", source="docref",
        score=1.0, outcome="clean", status="offloaded", promoted=False,
        reason="", effect_lease=dict(LEASE_RECEIPT)).to_dict()
    assert row["effect_lease"]["lease_id"] == LEASE_RECEIPT["lease_id"]
    # The COMPLETE declared set, in the receipt, because a partial set is what
    # offload refuses and a reader must be able to see which one was bound.
    assert row["effect_lease"]["requested_effects"] == [
        "filesystem_write", "network_egress", "process_spawn", "spend"]
    assert row["effect_lease"]["execution_id"].endswith("-exec-0")


def test_report_publishes_the_revision_and_the_governance_revision():
    report = LoopReport(
        run_id="loop-test", repo_root=REPO_ROOT, project=None,
        bounds=LoopBounds(), dry_run=False,
        source_revision="a" * 40, governance_head="b" * 40,
        governance_repo_root=r"C:\elsewhere").to_dict()
    # Both, separately named. One field holding "the HEAD" is what let a
    # verdict about another checkout read as a fact about this one.
    assert report["source_revision"] == "a" * 40
    assert report["governance_head"] == "b" * 40
    assert report["governance_repo_root"] == r"C:\elsewhere"


def test_driver_reads_this_repositorys_head_at_run_start(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    driver = LoopDriver(REPO_ROOT, bounds=LoopBounds(max_iterations=1),
                        runs_dir=tmp_path)
    # MEASURED against git itself, not against get_governance's answer.
    assert driver.source_revision == _git_head(REPO_ROOT)
    # And the bound the wave's lease will be issued under is the loop's own.
    assert driver.executor.effect_bounds.source_revision == driver.source_revision
    assert driver.executor.effect_bounds.switch is driver.switch


def test_governance_about_another_checkout_locks_promotion(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    foreign = {
        "promotion_allowed": True,          # a PASS, from the wrong repository
        "verdict": "the gate has demonstrated discrimination at this revision",
        "state": "working",
        "head": "d" * 40,
        "repo_root": str(tmp_path / "some-other-checkout"),
    }
    driver = LoopDriver(REPO_ROOT, bounds=LoopBounds(max_iterations=1),
                        runs_dir=tmp_path)
    driver.switch.arm(note="test")
    with mock.patch("daedalus.core.get_governance", return_value=foreign):
        with mock.patch.object(LoopDriver, "_pick",
                               return_value=(None, [], "nothing admissible")):
            report = driver.run()
    # NARROWING ONLY: a verdict measured somewhere else can lock promotion, it
    # can never unlock it.
    assert report.promotion_allowed is False
    assert report.governance_repo_root == foreign["repo_root"]
    assert report.governance_head == "d" * 40
    assert report.source_revision == _git_head(REPO_ROOT)
    assert any("GOVERNANCE IS ABOUT ANOTHER CHECKOUT" in n
               for n in report.notes)


def test_governance_about_this_checkout_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "killswitch"))
    driver = LoopDriver(REPO_ROOT, bounds=LoopBounds(max_iterations=1),
                        runs_dir=tmp_path)
    driver.switch.arm(note="test")
    ours = {
        "promotion_allowed": False,
        "verdict": "promotion is REFUSED: the gate has not discriminated here",
        "state": "degraded",
        "head": _git_head(REPO_ROOT),
        "repo_root": REPO_ROOT,
    }
    with mock.patch("daedalus.core.get_governance", return_value=ours):
        with mock.patch.object(LoopDriver, "_pick",
                               return_value=(None, [], "nothing admissible")):
            report = driver.run()
    assert report.governance_head == report.source_revision
    assert not any("GOVERNANCE IS ABOUT ANOTHER CHECKOUT" in n
                   for n in report.notes)


def test_ledger_detail_carries_the_capability(tmp_path):
    from daedalus.orchestration.loop import LoopLedger

    ledger = LoopLedger(tmp_path / "ledger.json", trace_id="tr-test")
    ledger.record("cand-1", outcome="clean", iteration=0,
                  attempt_task_ids=("kairos-ollama-abc",),
                  detail={"status": "offloaded",
                          "effect_lease": dict(LEASE_RECEIPT)})
    saved = LoopLedger.load(ledger.save())
    detail = saved["attempts"]["cand-1"]["detail"][0]
    # attempt_task_ids says WHICH attempt, trace_id says WHICH run, and this
    # says under WHOSE AUTHORITY -- the other half of an effect-ledger row.
    assert detail["effect_lease"]["lease_id"] == LEASE_RECEIPT["lease_id"]
    assert detail["effect_lease"]["execution_id"].endswith("-exec-0")
