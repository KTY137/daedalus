"""G1-IKARUS-01 acceptance matrix — the supervisor slice, all six rows.

Work packet: docs/work-packets/G1-IKARUS-01-supervisor-slice.md.  Every test
here is one frozen matrix row; the mutation probe for the ledger chain lives
in row 2's second half (a revision is edited on disk and verification must
refuse).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daedalus.orchestration.ikarus.supervisor import (  # noqa: E402
    MissionSupervisor,
    PlannedItem,
    RoleHarness,
    StateLedgerBroken,
    SupervisorRefused,
    plan_mission,
    verify_state_ledger,
)
from daedalus.orchestration.execution import (  # noqa: E402
    compose_task_attempt,
)
from daedalus.schemas import ResourceBudget  # noqa: E402
from daedalus.spine.attempt import GateResult  # noqa: E402


# --------------------------------------------------------------------------- #
# fixtures: a real target repo and a deterministic coder role                  #
# --------------------------------------------------------------------------- #
@pytest.fixture
def target_repo(tmp_path):
    repo = tmp_path / "target"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)

    git("init")
    git("config", "user.name", "t")
    git("config", "user.email", "t@example.invalid")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("alpha\n", encoding="utf-8")
    (repo / "docs" / "b.md").write_text("beta\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "seed")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()
    return repo, head


def _writing_runner(item: PlannedItem):
    def runner(ctx):
        wrote = []
        for rel in item.paths:
            target = Path(ctx.worktree) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("written by coder\n", encoding="utf-8")
            wrote.append(rel)
        return {"wrote": wrote}
    return runner


def _bouncing_runner(item: PlannedItem):
    def runner(ctx):
        raise RuntimeError("this coder bounces by design")
    return runner


def _passing_gate(item: PlannedItem):
    def gate(ctx):
        return GateResult(passed=True, name="unit-gate", command=())
    return gate


def _coder(runner_factory=_writing_runner) -> dict[str, RoleHarness]:
    return {
        "coder": RoleHarness(
            role="coder", runner_factory=runner_factory, gate_factory=_passing_gate
        )
    }


def _items() -> list[PlannedItem]:
    return [
        PlannedItem(objective="rewrite docs/a.md", role="coder", paths=("docs/a.md",)),
        PlannedItem(objective="rewrite docs/b.md", role="coder", paths=("docs/b.md",)),
    ]


def _budget() -> ResourceBudget:
    return ResourceBudget(max_wall_time_s=600)


def _plan(repo, head, items=None):
    return plan_mission(
        "supervisor slice probe",
        repo_root=repo,
        items=items or _items(),
        base_revision=head,
        budget=_budget(),
        success_criteria=("both docs are rewritten and gated",),
    )


def _run(repo, head, run_dir, *, roles=None, items=None, monkeypatch=None):
    items = items or _items()
    session, mission = _plan(repo, head, items)
    supervisor = MissionSupervisor(
        repo_root=repo,
        run_dir=run_dir,
        roles=roles or _coder(),
        gate_timeout_s=120,
        attempt_factory=compose_task_attempt,
    )
    final = supervisor.run(session, mission, items)
    return session, mission, supervisor, final


# --------------------------------------------------------------------------- #
# row 1 — same plan, same identity                                             #
# --------------------------------------------------------------------------- #
def test_the_same_plan_yields_the_same_mission_and_work_item_ids(target_repo):
    repo, head = target_repo
    s1, m1 = _plan(repo, head)
    s2, m2 = _plan(repo, head)
    assert m1.mission_id == m2.mission_id
    assert m1.work_item_ids == m2.work_item_ids
    # ...and the identity is a function of the PLAN: a different plan moves it.
    other = [PlannedItem(objective="something else entirely",
                         role="coder", paths=("docs/a.md",))]
    _, m3 = _plan(repo, head, other)
    assert m3.mission_id != m1.mission_id


# --------------------------------------------------------------------------- #
# rows 2 + 5 — a green run leaves the artifacts, and the chain verifies        #
# --------------------------------------------------------------------------- #
def test_a_green_run_leaves_mission_ledger_and_receipt_digests(
        target_repo, tmp_path, monkeypatch):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "wt"))
    run_dir = tmp_path / "run"
    session, mission, supervisor, final = _run(repo, head, run_dir)

    assert final["outcome"] == "landed"
    rows = final["items"]
    assert [r["status"] for r in rows] == ["landed", "landed"]
    # digests, present and distinct per item
    receipts = [r["attempt_receipt_sha256"] for r in rows]
    assert all(receipts), rows
    assert len(set(receipts)) == 2
    # the mission contract is retained beside the ledger and matches by digest
    contract = json.loads((run_dir / "mission.json").read_text(encoding="utf-8"))
    assert final["mission_sha256"] == mission.digest
    assert contract["mission_id"] == mission.mission_id
    # the chain verifies end to end and its last revision IS the final state
    revisions = verify_state_ledger(run_dir / "ledger")
    assert revisions[-1]["revision_sha256"] == final["revision_sha256"]
    assert revisions[0]["items"][0]["status"] == "planned"


def test_a_tampered_or_thinned_ledger_is_refused(target_repo, tmp_path, monkeypatch):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "wt"))
    run_dir = tmp_path / "run"
    _run(repo, head, run_dir)
    ledger_dir = run_dir / "ledger"
    paths = sorted(ledger_dir.glob("[0-9]*.json"))
    assert len(paths) >= 4

    # Mutation 1: edit one body in place.
    victim = paths[1]
    original = victim.read_text(encoding="utf-8")
    body = json.loads(original)
    body["items"][0]["status"] = "landed"  # history says otherwise
    victim.write_text(json.dumps(body, indent=1, sort_keys=True),
                      encoding="utf-8", newline="\n")
    with pytest.raises(StateLedgerBroken, match="does not match its digest"):
        verify_state_ledger(ledger_dir)
    victim.write_text(original, encoding="utf-8", newline="")
    verify_state_ledger(ledger_dir)  # restored -> green again

    # Mutation 2: remove a middle revision — a GAP, not just a bad digest.
    removed = paths[2].read_text(encoding="utf-8")
    paths[2].unlink()
    with pytest.raises(StateLedgerBroken, match="missing or reordered"):
        verify_state_ledger(ledger_dir)
    paths[2].write_text(removed, encoding="utf-8", newline="")
    verify_state_ledger(ledger_dir)

    # And an empty directory is "could not verify", never "verified, empty".
    empty = tmp_path / "empty-ledger"
    empty.mkdir()
    with pytest.raises(StateLedgerBroken, match="no ledger revisions"):
        verify_state_ledger(empty)


# --------------------------------------------------------------------------- #
# row 3 — an unknown role refuses before any attempt                           #
# --------------------------------------------------------------------------- #
def test_an_unknown_role_refuses_the_whole_plan_before_any_attempt(
        target_repo, tmp_path, monkeypatch):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "wt"))
    run_dir = tmp_path / "run"
    items = [
        PlannedItem(objective="rewrite docs/a.md", role="coder", paths=("docs/a.md",)),
        PlannedItem(objective="analyse docs/b.md", role="data-analyst",
                    paths=("docs/b.md",)),
    ]
    with pytest.raises(SupervisorRefused, match="data-analyst"):
        _run(repo, head, run_dir, items=items)

    # Nothing ran: no attempt artifacts, no spine ledger, and the state ledger
    # says WHY on every row.
    assert not (run_dir / "artifacts").exists()
    assert not (run_dir / "spine.sqlite3").exists()
    revisions = verify_state_ledger(run_dir / "ledger")
    last = revisions[-1]
    assert last["outcome"] == "refused"
    statuses = {r["role"]: r["status"] for r in last["items"]}
    assert statuses == {"coder": "skipped", "data-analyst": "refused"}
    # the target repo itself is untouched
    assert (repo / "docs" / "a.md").read_text(encoding="utf-8") == "alpha\n"


# --------------------------------------------------------------------------- #
# row 4 — fail-fast: a bounce stops the mission and the ledger says so         #
# --------------------------------------------------------------------------- #
def test_a_bounced_item_stops_dispatch_and_is_named_in_the_ledger(
        target_repo, tmp_path, monkeypatch):
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "wt"))
    run_dir = tmp_path / "run"
    _, _, supervisor, final = _run(
        repo, head, run_dir, roles=_coder(_bouncing_runner)
    )

    assert final["outcome"] == "bounced"
    first, second = final["items"]
    assert first["status"] == "bounced"
    assert "this coder bounces by design" in (first["detail"] or "")
    assert second["status"] == "skipped"
    assert "fail-fast" in (second["detail"] or "")
    # exactly ONE attempt ran
    assert len(supervisor.results) == 1


# --------------------------------------------------------------------------- #
# row 6 — chat is not state                                                    #
# --------------------------------------------------------------------------- #
def test_the_ledger_carries_typed_state_and_no_transcript(
        target_repo, tmp_path, monkeypatch):
    """The supervisor API accepts no transcript, and the ledger's vocabulary
    is closed: mission identity, typed rows, chain fields.  A conversational
    key appearing here is the drift the plan forbids (chat as orchestration
    state), so the shape itself is pinned."""
    repo, head = target_repo
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "wt"))
    run_dir = tmp_path / "run"
    _run(repo, head, run_dir)
    for body in verify_state_ledger(run_dir / "ledger"):
        assert set(body.keys()) == {
            "schema", "sequence", "previous_ledger_sha256", "published_at",
            "mission_id", "mission_sha256", "objective", "source_revision",
            "items", "outcome", "revision_sha256",
        }
        for row in body["items"]:
            assert set(row.keys()) == {
                "work_item_id", "objective", "role", "runtime_id",
                "runtime_binding_sha256", "paths", "status",
                "attempt_id", "attempt_receipt_sha256",
                "evidence_packet_sha256", "detail",
            }
            assert row["runtime_id"] == "inprocess"
            assert row["runtime_binding_sha256"] is None
            assert row["status"] in (
                "planned", "dispatched", "landed", "bounced", "skipped", "refused"
            )
