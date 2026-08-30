from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "recovery" / "GARDENER_POST_RELEASE_CONTAINMENT_20260830T0900.json"
PACKET = ROOT / "docs" / "work-packets" / "G1-GARDEN-CONTAINMENT-03.json"


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_checkpoint_is_bound_to_current_authority_and_main() -> None:
    report = _load(REPORT)
    assert report["schema"] == "daedalus-gardener-post-release-containment/1"
    assert report["timezone"] == "Europe/Berlin"
    assert report["authority"] == {
        "master_plan": "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
        "revision": 8,
        "version": "1.3.0",
        "status": "adopted",
        "active_gate": "Gate 1 — Renovation ignition slice",
        "classification": "ALIGNED",
    }
    assert report["repository"]["main_sha"] == (
        "e5f55840a12dcfb1a50935c6080f06306a8854a8"
    )
    assert report["repository"]["local_linked_worktrees"] == "unknown"


def test_resolved_issues_require_current_main_source_evidence() -> None:
    report = _load(REPORT)
    rows = {row["issue"]: row for row in report["resolved_delivery"]}
    assert set(rows) == {249, 271}
    assert rows[249]["delivery_pr"] == 258
    assert rows[249]["delivery_state"] == "merged"
    assert rows[249]["current_main_evidence"] == {
        "path": "daedalus/loop.py",
        "blob_sha": "0ba77b7d23e193de2cbd2552df959b2e08194aff",
        "finding": (
            "LoopBounds rejects non-positive or non-finite wall-clock/spend values "
            "and requires exact positive integer count bounds"
        ),
    }
    assert rows[271]["delivery_pr"] == 275
    assert rows[271]["delivery_state"] == "merged"
    assert rows[271]["current_main_evidence"]["blob_sha"] == (
        "3d20cac6a6f12b767d54c3a1068e066b01d36397"
    )


def test_experiments_and_diverged_candidates_are_not_laundered_into_main() -> None:
    report = _load(REPORT)
    rows = {row["pr"]: row for row in report["retained_open_lines"]}
    assert rows[255]["classification"] == "experiment"
    assert rows[262]["classification"] == "experiment"
    assert rows[277]["classification"] == "active_candidate"
    assert rows[277]["measured_compare"] == {
        "base": "d9244822d5f6df76c82189c02a0f24a082882ab8",
        "head": "main",
        "status": "diverged",
        "main_ahead_by": 48,
        "candidate_unique_commits": 27,
        "merge_base": "24c2f1ecbaac0244a121b08f13d0f4ba623f7bf2",
    }
    assert rows[291]["classification"] == "active_candidate"


def test_stale_topology_retirement_preserves_evidence() -> None:
    report = _load(REPORT)
    stale = report["superseded_checkpoint"]
    assert stale["pr"] == 273
    assert stale["classification"] == "historical_evidence"
    assert stale["recommended_pr_action"] == "close_without_deleting_branch"


def test_packet_cannot_authorize_merge_promotion_or_gate_change() -> None:
    report = _load(REPORT)
    packet = _load(PACKET)
    assert packet["work_packet_id"] == "G1-GARDEN-CONTAINMENT-03"
    assert packet["classification"] == "ALIGNED"
    assert packet["gate"] == 1
    assert packet["base_revision"] == report["repository"]["main_sha"]

    boundary = report["authority_boundary"]
    assert boundary == {
        "automatic_merge": False,
        "automatic_promotion": False,
        "owner_approval_issued": False,
        "gate_transition": False,
        "branch_deleted": False,
        "force_ref_update": False,
        "benchmark_superiority_claim": False,
    }

    out_of_scope = " ".join(packet["scope"]["out_of_scope"]).lower()
    for phrase in (
        "branch deletion",
        "force updates",
        "automatic merge",
        "ownerapproval",
        "promotion",
        "gate transition",
    ):
        assert phrase in out_of_scope
