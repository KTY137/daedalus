"""Trust regressions for the MissionSupervisor attempt-identity projection."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import daedalus.ikarus_claude_attempt_handoff as handoff  # noqa: E402
from daedalus.ikarus_supervisor import (  # noqa: E402
    MissionSupervisor,
    PlannedItem,
    RoleHarness,
    SupervisorRefused,
    _canonical_attempt_identity,
    plan_mission,
)
from daedalus.schemas import ResourceBudget  # noqa: E402
from daedalus.spine.attempt import GateResult  # noqa: E402


def _result(attempt_id: str = "attempt-1", *, base_revision: str = "a" * 40):
    return SimpleNamespace(
        effect_key=attempt_id,
        branch=attempt_id,
        base_revision=base_revision,
    )


def _contracts(
    attempt_id: str = "attempt-1",
    *,
    mission_id: str = "mission-1",
    task_id: str = "work-item-1",
    base_revision: str = "a" * 40,
):
    return SimpleNamespace(
        attempt=SimpleNamespace(
            attempt_id=attempt_id,
            mission_id=mission_id,
            task_id=task_id,
            base_revision=base_revision,
        )
    )


def test_canonical_attempt_contract_is_the_only_identity_source() -> None:
    attempt_id, error = _canonical_attempt_identity(
        _result(),
        _contracts(),
        mission_id="mission-1",
        work_item_id="work-item-1",
    )
    assert attempt_id == "attempt-1"
    assert error is None

    # A transport/effect identity without a canonical contract must never be
    # promoted into the Work Pulse / state-ledger attempt_id field.
    attempt_id, error = _canonical_attempt_identity(
        _result(),
        None,
        mission_id="mission-1",
        work_item_id="work-item-1",
    )
    assert attempt_id is None
    assert "AttemptContract is unavailable" in (error or "")


def test_transport_branch_cannot_override_canonical_attempt_identity() -> None:
    result = _result("transport-branch")
    attempt_id, error = _canonical_attempt_identity(
        result,
        _contracts(attempt_id="canonical-attempt"),
        mission_id="mission-1",
        work_item_id="work-item-1",
    )
    assert attempt_id is None
    assert "effect/branch identity" in (error or "")


@pytest.mark.parametrize(
    ("contracts", "message"),
    [
        (_contracts(mission_id="mission-foreign"), "mission_id"),
        (_contracts(task_id="work-item-foreign"), "task_id"),
        (_contracts(base_revision="b" * 40), "base_revision"),
    ],
)
def test_canonical_attempt_must_bind_mission_work_item_and_revision(
    contracts, message: str
) -> None:
    attempt_id, error = _canonical_attempt_identity(
        _result(),
        contracts,
        mission_id="mission-1",
        work_item_id="work-item-1",
    )
    assert attempt_id is None
    assert message in (error or "")


# --------------------------------------------------------------------------- #
# Product path: supervisor -> TaskAttempt -> authenticated runner -> terminal  #
# --------------------------------------------------------------------------- #
def _target_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "target"
    repo.mkdir()

    def git(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        )
        return proc.stdout.strip()

    git("init")
    git("config", "user.name", "t")
    git("config", "user.email", "t@example.invalid")
    (repo / "docs").mkdir()
    (repo / "docs" / "a.md").write_text("alpha\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "seed")
    return repo, git("rev-parse", "HEAD")


def _passing_gate(_item: PlannedItem):
    def gate(_ctx):
        return GateResult(passed=True, name="unit-gate", command=())

    return gate


def _writing_runner(item: PlannedItem):
    def runner(ctx):
        target = Path(ctx.worktree) / item.paths[0]
        target.write_text("written through guarded runner\n", encoding="utf-8")
        return {"wrote": item.paths[0]}

    return runner


def _run_product_path(
    tmp_path: Path,
    monkeypatch,
    runner_factory,
    *,
    handoff_runner_factory=None,
) -> tuple[MissionSupervisor, dict]:
    repo, head = _target_repo(tmp_path)
    monkeypatch.setenv("DAEDALUS_WORKTREE_ROOT", str(tmp_path / "wt"))
    item = PlannedItem(
        objective="rewrite docs/a.md",
        role="coder",
        paths=("docs/a.md",),
    )
    session, mission = plan_mission(
        "TaskAttempt Claude handoff probe",
        repo_root=repo,
        items=(item,),
        base_revision=head,
        budget=ResourceBudget(max_wall_time_s=120),
        success_criteria=("docs/a.md is rewritten and gated",),
    )
    supervisor = MissionSupervisor(
        repo_root=repo,
        run_dir=tmp_path / "run",
        roles={
            "coder": RoleHarness(
                role="coder",
                runner_factory=runner_factory,
                gate_factory=_passing_gate,
                handoff_runner_factory=handoff_runner_factory,
            )
        },
        gate_timeout_s=120,
    )
    return supervisor, supervisor.run(session, mission, (item,))


def test_runner_context_is_authenticated_before_runner_factory(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[str] = []
    real_guard = handoff.require_task_attempt_runner_context

    def guard(binding, context):
        events.append("guard")
        return real_guard(binding, context)

    def factory(item: PlannedItem):
        events.append("factory")
        return _writing_runner(item)

    monkeypatch.setattr(handoff, "require_task_attempt_runner_context", guard)
    supervisor, final = _run_product_path(tmp_path, monkeypatch, factory)

    assert final["outcome"] == "landed"
    assert events == ["guard", "factory"]
    assert len(supervisor.results) == 1
    assert final["items"][0]["attempt_id"] == supervisor.results[0].branch


def test_handoff_runner_factory_receives_authenticated_snapshot_after_guard(
    tmp_path: Path, monkeypatch
) -> None:
    events: list[str] = []
    received: list[handoff.ClaudeTaskAttemptRunnerHandoff] = []
    live_worktrees: list[Path] = []
    real_guard = handoff.require_task_attempt_runner_context

    def guard(binding, context):
        events.append("guard")
        return real_guard(binding, context)

    def factory(item: PlannedItem, runner_handoff):
        events.append("handoff_factory")
        assert type(runner_handoff) is handoff.ClaudeTaskAttemptRunnerHandoff
        # The isolated worktree is provider authority only while this attempt
        # owns it; TaskAttempt is allowed to remove it after terminal cleanup.
        assert runner_handoff.worktree.is_dir()
        live_worktrees.append(runner_handoff.worktree)
        received.append(runner_handoff)
        # Provider/runtime code may retain or even deliberately mutate its
        # detached evidence copy. The supervisor's terminal binding must not
        # be an alias of this object.
        object.__setattr__(runner_handoff, "attempt_id", "provider-mutated")
        return _writing_runner(item)

    monkeypatch.setattr(handoff, "require_task_attempt_runner_context", guard)
    supervisor, final = _run_product_path(
        tmp_path,
        monkeypatch,
        None,
        handoff_runner_factory=factory,
    )

    assert final["outcome"] == "landed"
    assert events == ["guard", "handoff_factory"]
    assert len(received) == 1
    assert len(live_worktrees) == 1
    runner_handoff = received[0]
    assert runner_handoff.mission_id == final["mission_id"]
    assert runner_handoff.work_item_id == final["items"][0]["work_item_id"]
    assert runner_handoff.source_revision == final["source_revision"]
    assert runner_handoff.target_paths == ("docs/a.md",)
    assert runner_handoff.attempt_id == "provider-mutated"
    assert final["items"][0]["attempt_id"] == supervisor.results[0].branch
    assert final["items"][0]["attempt_id"] != "provider-mutated"


def test_runner_context_refusal_blocks_runner_factory(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []

    def refuse(_binding, _context):
        raise handoff.IkarusClaudeAttemptHandoffRefused("context substitution probe")

    def factory(item: PlannedItem):
        calls.append(item.objective)
        return _writing_runner(item)

    monkeypatch.setattr(handoff, "require_task_attempt_runner_context", refuse)
    supervisor, final = _run_product_path(tmp_path, monkeypatch, factory)

    assert calls == []
    assert final["outcome"] == "bounced"
    assert final["items"][0]["status"] == "bounced"
    assert len(supervisor.results) == 1
    assert supervisor.results[0].state == "runner_failed"
    assert "context substitution probe" in (supervisor.results[0].error or "")


def test_runner_context_refusal_blocks_handoff_runner_factory(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []

    def refuse(_binding, _context):
        raise handoff.IkarusClaudeAttemptHandoffRefused("handoff guard probe")

    def factory(item: PlannedItem, _runner_handoff):
        calls.append(item.objective)
        return _writing_runner(item)

    monkeypatch.setattr(handoff, "require_task_attempt_runner_context", refuse)
    supervisor, final = _run_product_path(
        tmp_path,
        monkeypatch,
        None,
        handoff_runner_factory=factory,
    )

    assert calls == []
    assert final["outcome"] == "bounced"
    assert final["items"][0]["status"] == "bounced"
    assert supervisor.results[0].state == "runner_failed"
    assert "handoff guard probe" in (supervisor.results[0].error or "")


def test_role_harness_refuses_ambiguous_runner_factories_before_attempt(
    tmp_path: Path, monkeypatch
) -> None:
    calls: list[str] = []

    def handoff_factory(item: PlannedItem, _runner_handoff):
        calls.append(item.objective)
        return _writing_runner(item)

    with pytest.raises(SupervisorRefused, match="declares both runner_factory"):
        _run_product_path(
            tmp_path,
            monkeypatch,
            _writing_runner,
            handoff_runner_factory=handoff_factory,
        )
    assert calls == []


def test_terminal_binding_refusal_withholds_trusted_attempt_identity(
    tmp_path: Path, monkeypatch
) -> None:
    def refuse(_binding, _attempt):
        raise handoff.IkarusClaudeAttemptHandoffRefused("terminal substitution probe")

    monkeypatch.setattr(handoff, "require_task_attempt_terminal_contract", refuse)
    supervisor, final = _run_product_path(tmp_path, monkeypatch, _writing_runner)

    # The candidate itself can be clean while the supervisor refuses to expose
    # it as trusted Ikarus terminal evidence. Producer evidence remains
    # inspectable by digest, but no Attempt identity is promoted into Work Pulse.
    assert supervisor.results[0].ok is True
    assert final["outcome"] == "bounced"
    row = final["items"][0]
    assert row["status"] == "bounced"
    assert row["attempt_id"] is None
    assert row["attempt_receipt_sha256"]
    assert "terminal substitution probe" in (row["detail"] or "")
