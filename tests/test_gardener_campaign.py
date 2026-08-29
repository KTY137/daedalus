"""Contract tests for the deadline-bounded Fourfold/Tensor campaign guard."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "gardener_campaign.py"
CAMPAIGN_PATH = (
    ROOT / "docs" / "campaigns" / "FOURFOLD_TENSOR_GARDENER_20260929.json"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("gardener_campaign", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GARDENER = _load_module()


def _campaign() -> dict:
    return GARDENER.load_campaign(CAMPAIGN_PATH)


def _repository_state() -> dict:
    return {
        "head": "a" * 40,
        "branch": "campaign",
        "dirty": False,
        "dirty_paths": [],
        "branches": [["campaign", "a" * 40]],
        "worktrees": [],
    }


def _plan_state() -> dict:
    return {
        "master_plan_sha256": "b" * 64,
        "master_plan_revision": 8,
        "master_plan_version": "1.3.0",
        "active_delivery_gate": "Gate 1",
        "execution_plan_sha256": "c" * 64,
    }


def _queue_state(*, pending=("task.1", "task.2", "task.3")) -> dict:
    rows = [
        {
            "task_id": task_id,
            "definition_attempts": 0,
            "attempted": False,
            "target_paths": [f"docs/{task_id}.md"],
        }
        for task_id in pending
    ]
    return {
        "source": {"state": "valid", "policy_blocked": 0},
        "candidates": rows,
        "pending_task_ids": list(pending),
        "converged": False,
        "no_ready_candidates": not rows,
    }


def _patch_common(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    observed: datetime,
) -> None:
    monkeypatch.setattr(GARDENER, "berlin_now", lambda: (observed, "test"))
    monkeypatch.setattr(
        GARDENER,
        "repository_state",
        lambda root: _repository_state(),
    )
    monkeypatch.setattr(
        GARDENER,
        "plan_state",
        lambda root, campaign: _plan_state(),
    )
    monkeypatch.setattr(
        GARDENER,
        "_campaign_root",
        lambda root, campaign: tmp_path / str(campaign["campaign_id"]),
    )


def test_campaign_contract_is_bounded_and_non_promoting() -> None:
    campaign = _campaign()
    assert campaign["campaign_id"] == "fourfold-tensor-gardener-20260929"
    assert campaign["timezone"] == "Europe/Berlin"
    assert campaign["_cutoff"].isoformat() == "2026-09-29"
    assert campaign["schedule"]["interval_minutes"] == 360
    assert campaign["activation_bounds"] == {
        "max_iterations": 3,
        "max_wall_clock_s": 1500,
        "max_spend_usd": 1.0,
        "max_attempts_per_candidate": 1,
        "queue_limit": 25,
    }
    authority = campaign["authority"]
    assert authority["automatic_merge"] is False
    assert authority["automatic_promotion"] is False
    assert authority["may_mint_owner_approval"] is False
    assert authority["may_change_gate_state"] is False


def test_campaign_refuses_authority_escalation(tmp_path: Path) -> None:
    raw = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
    raw["authority"]["automatic_promotion"] = True
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(GARDENER.CampaignError, match="automatic_promotion"):
        GARDENER.load_campaign(path)


def test_loop_argv_reuses_only_the_bounded_canonical_loop() -> None:
    campaign = _campaign()
    command = GARDENER.loop_argv(ROOT, campaign, pending_count=2)
    rendered = " ".join(command)
    assert command[:3] == (sys.executable, "-m", "daedalus.loop")
    assert "--max-iterations 2" in rendered
    assert "--max-wall-clock-s 1500" in rendered
    assert "--max-spend-usd 1.00" in rendered
    assert "--max-attempts-per-candidate 1" in rendered
    assert "--queue-limit 25" in rendered
    assert "--json" in command
    assert "--arm" in command
    assert "--force" not in command
    with pytest.raises(GARDENER.CampaignError, match="pending task"):
        GARDENER.loop_argv(ROOT, campaign, pending_count=0)


def test_cutoff_never_reads_queue_or_invokes_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed = datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)
    _patch_common(monkeypatch, tmp_path, observed=observed)
    monkeypatch.setattr(
        GARDENER,
        "curated_queue_state",
        lambda root: pytest.fail("queue must not be read at cutoff"),
    )
    monkeypatch.setattr(GARDENER, "_stop", lambda root, reason: 0)
    monkeypatch.setattr(
        GARDENER,
        "_run",
        lambda *args, **kwargs: pytest.fail("candidate process is forbidden"),
    )

    assert GARDENER.run_campaign(ROOT, CAMPAIGN_PATH) == 0
    final_path = tmp_path / "fourfold-tensor-gardener-20260929" / "final.json"
    receipt = json.loads(final_path.read_text(encoding="ascii"))
    assert receipt["schema"] == GARDENER.FINAL_SCHEMA
    assert receipt["candidate_execution_performed"] is False
    assert receipt["kill_switch_stop_returncode"] == 0
    assert receipt["claim_boundary"]["automatic_promotion"] is False


def test_pre_cutoff_activation_invokes_one_bounded_loop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    _patch_common(monkeypatch, tmp_path, observed=observed)
    queue = _queue_state()
    monkeypatch.setattr(GARDENER, "curated_queue_state", lambda root: queue)
    seen: list[tuple[str, ...]] = []

    def run(command, root, **kwargs):
        seen.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout='{"ok":true}\n', stderr="")

    monkeypatch.setattr(GARDENER, "_run", run)
    assert GARDENER.run_campaign(ROOT, CAMPAIGN_PATH) == 0
    assert seen == [GARDENER.loop_argv(ROOT, _campaign(), pending_count=3)]
    receipts = list(tmp_path.rglob("activations/*/receipt.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="ascii"))
    assert receipt["schema"] == GARDENER.ACTIVATION_SCHEMA
    assert receipt["candidate_execution_performed"] is True
    assert receipt["queue_before"] == queue
    assert receipt["authority"] == {
        "automatic_merge": False,
        "automatic_promotion": False,
        "gate_state_changed": False,
        "owner_approval_minted": False,
    }


def test_iterations_are_capped_by_remaining_pending_definitions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    _patch_common(monkeypatch, tmp_path, observed=observed)
    monkeypatch.setattr(
        GARDENER,
        "curated_queue_state",
        lambda root: _queue_state(pending=("only-one",)),
    )
    seen: list[tuple[str, ...]] = []

    def run(command, root, **kwargs):
        seen.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    monkeypatch.setattr(GARDENER, "_run", run)
    assert GARDENER.run_campaign(ROOT, CAMPAIGN_PATH) == 0
    rendered = " ".join(seen[0])
    assert "--max-iterations 1" in rendered
    assert "--max-iterations 3" not in rendered


def test_converged_queue_waits_for_owner_without_candidate_process(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)
    _patch_common(monkeypatch, tmp_path, observed=observed)
    queue = {
        "source": {"state": "valid", "policy_blocked": 0},
        "candidates": [
            {
                "task_id": "done.1",
                "definition_attempts": 1,
                "attempted": True,
                "target_paths": ["docs/a.md"],
            }
        ],
        "pending_task_ids": [],
        "converged": True,
        "no_ready_candidates": False,
    }
    monkeypatch.setattr(GARDENER, "curated_queue_state", lambda root: queue)
    monkeypatch.setattr(
        GARDENER,
        "_run",
        lambda *args, **kwargs: pytest.fail("loop must not run after convergence"),
    )

    assert GARDENER.run_campaign(ROOT, CAMPAIGN_PATH) == 0
    waiting = tmp_path / "fourfold-tensor-gardener-20260929" / "waiting-owner.json"
    receipt = json.loads(waiting.read_text(encoding="ascii"))
    assert receipt["schema"] == GARDENER.WAITING_SCHEMA
    assert receipt["candidate_execution_performed"] is False
    assert "waiting for owner integration" in receipt["reason"]


def test_curated_queue_state_uses_exact_definition_attempt_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import daedalus.spine.picker as picker

    candidates = (
        SimpleNamespace(
            source="work_queue",
            task_id="new",
            evidence={"prior_attempts_same_definition": 0},
            target_paths=("docs/new.md",),
        ),
        SimpleNamespace(
            source="work_queue",
            task_id="old",
            evidence={"prior_attempts_same_definition": 1},
            target_paths=("docs/old.md",),
        ),
    )
    monkeypatch.setattr(
        picker,
        "build_queue",
        lambda root, limit=None: SimpleNamespace(
            candidates=candidates,
            sources={"work_queue": {"state": "valid", "policy_blocked": 0}},
        ),
    )
    state = GARDENER.curated_queue_state(ROOT)
    assert state["pending_task_ids"] == ["new"]
    assert state["converged"] is False
    assert state["candidates"][1]["attempted"] is True


def test_plan_state_requires_adopted_master_plan_markers(tmp_path: Path) -> None:
    docs = tmp_path / "docs"
    docs.mkdir()
    master = docs / "MASTER.md"
    execution = docs / "EXECUTION.md"
    master.write_text(
        "\n".join(
            (
                "Revision: 8",
                "Version: 1.3.0",
                "Status: adopted",
                "Active delivery gate: Gate 1 — Renovation ignition slice",
                "This is the sole semantic authority.",
                "## 5. The Project Twin: the strongest falsifiable prior",
                "## 10. Mandatory build and review chain",
            )
        ),
        encoding="utf-8",
    )
    execution.write_text("derived", encoding="utf-8")
    campaign = {
        "authority": {
            "master_plan": "docs/MASTER.md",
            "derived_execution_plan": "docs/EXECUTION.md",
        }
    }
    state = GARDENER.plan_state(tmp_path, campaign)
    assert state["master_plan_revision"] == 8
    assert state["master_plan_version"] == "1.3.0"
    assert state["active_delivery_gate"].startswith("Gate 1")

    master.write_text("Revision: 8\nVersion: 1.3.0\n", encoding="utf-8")
    with pytest.raises(GARDENER.CampaignError, match="marker"):
        GARDENER.plan_state(tmp_path, campaign)


def test_python_guard_does_not_own_task_scheduler_or_repository_promotion() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "New-ScheduledTask",
        "Register-ScheduledTask",
        "schtasks.exe",
        '"git", "merge"',
        '"git", "push"',
        '"git", "reset"',
        "promote_candidates(",
        "OwnerApproval(",
        "PromotionReceipt(",
    ):
        assert forbidden not in source
