"""Contract tests for the deadline-bounded gardener campaign."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import date, datetime, timezone
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


def test_campaign_contract_is_bounded_and_non_promoting() -> None:
    campaign = GARDENER.Campaign.load(CAMPAIGN_PATH)
    assert campaign.campaign_id == "fourfold-tensor-gardener-20260929"
    assert campaign.timezone_name == "Europe/Berlin"
    assert campaign.cutoff == date(2026, 9, 29)
    assert campaign.interval_minutes == 360
    assert campaign.bounds.iterations == 3
    assert campaign.bounds.wall_s == 1500
    assert campaign.bounds.spend_usd == 1.0
    assert campaign.bounds.attempts == 1
    assert campaign.bounds.queue_limit == 25

    raw = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
    authority = raw["authority"]
    assert authority["automatic_merge"] is False
    assert authority["automatic_promotion"] is False
    assert authority["may_mint_owner_approval"] is False
    assert authority["may_change_gate_state"] is False


def test_loop_command_reuses_canonical_loop_with_every_bound() -> None:
    campaign = GARDENER.Campaign.load(CAMPAIGN_PATH)
    command = GARDENER.loop_argv(ROOT, campaign)
    rendered = " ".join(command)
    assert command[:3] == (sys.executable, "-m", "daedalus.loop")
    assert "--max-iterations 3" in rendered
    assert "--max-wall-clock-s 1500" in rendered
    assert "--max-spend-usd 1.00" in rendered
    assert "--max-attempts-per-candidate 1" in rendered
    assert "--queue-limit 25" in rendered
    assert "--json" in command
    assert "--arm" in command
    assert "--force" not in command
    assert "merge" not in command
    assert "push" not in command
    assert "promote" not in command


def test_cutoff_routes_directly_to_finalization_without_candidate_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cutoff = datetime(2026, 9, 29, 0, 0, tzinfo=timezone.utc)
    calls: list[tuple[Path, str]] = []

    monkeypatch.setattr(GARDENER, "berlin_now", lambda: (cutoff, "test"))

    def final(repo_root, campaign, now, source):
        calls.append((repo_root, campaign.campaign_id))
        assert now is cutoff
        assert source == "test"
        return 17

    monkeypatch.setattr(GARDENER, "finalize", final)
    monkeypatch.setattr(
        GARDENER,
        "_run",
        lambda *args, **kwargs: pytest.fail("loop/command execution is forbidden at cutoff"),
    )

    assert GARDENER.activate(ROOT, CAMPAIGN_PATH) == 17
    assert calls == [(ROOT, "fourfold-tensor-gardener-20260929")]


def test_pre_cutoff_activation_invokes_one_loop_and_retains_authority_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    campaign = GARDENER.Campaign.load(CAMPAIGN_PATH)
    before = datetime(2026, 9, 28, 23, 0, tzinfo=timezone.utc)
    command_seen: list[tuple[str, ...]] = []

    monkeypatch.setattr(GARDENER, "berlin_now", lambda: (before, "test"))
    monkeypatch.setattr(
        GARDENER,
        "repo_state",
        lambda root: {
            "head": "a" * 40,
            "branch": "campaign",
            "dirty": False,
            "dirty_paths": [],
            "branch_count": 1,
            "branches": [{"name": "campaign", "sha": "a" * 40}],
            "worktrees": [],
        },
    )
    monkeypatch.setattr(
        GARDENER,
        "plan_state",
        lambda root, selected: {
            "master_plan_sha256": "b" * 64,
            "master_plan_revision": 8,
            "active_delivery_gate": "Gate 1",
        },
    )
    monkeypatch.setattr(
        GARDENER,
        "_campaign_root",
        lambda root, selected: tmp_path / selected.campaign_id,
    )

    def run(command, repo_root, **kwargs):
        command_seen.append(tuple(command))
        return subprocess.CompletedProcess(command, 0, stdout='{"ok":true}\n', stderr="")

    monkeypatch.setattr(GARDENER, "_run", run)

    assert GARDENER.activate(ROOT, CAMPAIGN_PATH) == 0
    assert command_seen == [GARDENER.loop_argv(ROOT, campaign)]
    receipts = list(tmp_path.rglob("receipt.json"))
    assert len(receipts) == 1
    receipt = json.loads(receipts[0].read_text(encoding="ascii"))
    assert receipt["schema"] == GARDENER.ACTIVATION_SCHEMA
    assert receipt["candidate_execution_performed"] is True
    assert receipt["authority"] == {
        "automatic_merge": False,
        "automatic_promotion": False,
        "gate_state_changed": False,
        "owner_approval_minted": False,
    }


def test_plan_state_requires_the_adopted_master_plan_markers(tmp_path: Path) -> None:
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
    campaign = SimpleNamespace(master_plan="docs/MASTER.md", execution_plan="docs/EXECUTION.md")

    state = GARDENER.plan_state(tmp_path, campaign)
    assert state["master_plan_revision"] == 8
    assert state["master_plan_version"] == "1.3.0"
    assert state["active_delivery_gate"].startswith("Gate 1")

    master.write_text("Revision: 8\nVersion: 1.3.0\n", encoding="utf-8")
    with pytest.raises(GARDENER.CampaignError, match="authority marker"):
        GARDENER.plan_state(tmp_path, campaign)


def test_campaign_refuses_authority_escalation(tmp_path: Path) -> None:
    raw = json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))
    raw["authority"]["automatic_promotion"] = True
    path = tmp_path / "campaign.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(GARDENER.CampaignError, match="automatic_promotion"):
        GARDENER.Campaign.load(path)


def test_installer_is_ignore_new_interactive_limited_and_has_final_trigger() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "-MultipleInstances IgnoreNew" in source
    assert "-LogonType Interactive" in source
    assert "-RunLevel Limited" in source
    assert "$final = New-ScheduledTaskTrigger -Once" in source
    assert "@($repeat, $final)" in source
    assert "automatic merge or promotion" in source


def test_scheduler_source_contains_no_repository_merge_or_promotion_command() -> None:
    source = MODULE_PATH.read_text(encoding="utf-8")
    forbidden = (
        '"git", "merge"',
        '"git", "push"',
        '"git", "reset"',
        "promote_candidates(",
        "OwnerApproval(",
        "PromotionReceipt(",
    )
    for needle in forbidden:
        assert needle not in source
